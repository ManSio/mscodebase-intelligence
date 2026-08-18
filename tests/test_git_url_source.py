"""Тесты Фазы 2 Universal Engine: GitUrlSource (SSRF, лимиты, кэш, INCONCLUSIVE).

Happy-path клонирование тестируется через локальный git-репозиторий и
scheme-оверрайд allowed_schemes={"file"} — продакшн-дефолт (https-only)
проверяется отдельно (scheme-отклонения). Сеть НЕ используется.
"""

import time
from pathlib import Path

import pytest

from src.sources.git_url import (
    DEFAULT_ALLOWED_SCHEMES,
    GitRepoCache,
    GitUrlSource,
    GitUrlSourceError,
    _ips_are_global,
    _run_git,
)

# ── Хелперы ───────────────────────────────────────────────────────────────

def _make_git_repo(root: Path, files: dict[str, str] | None = None) -> Path:
    """Создаёт локальный git-репозиторий с коммитом. Возвращает путь."""
    root.mkdir(parents=True, exist_ok=True)
    assert _run_git(["-c", "user.name=t", "-c", "user.email=t@t", "init", str(root)])[0] == 0
    for name, content in (files or {"a.py": "def a(): pass\n"}).items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    assert _run_git(["-C", str(root), "add", "."])[0] == 0
    rc, _o, err = _run_git(
        ["-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "init"]
    )
    assert rc == 0, err
    return root


def _file_source(repo: Path, cache: Path, **kwargs) -> GitUrlSource:
    """GitUrlSource на локальный репо через file-схему (тестовый оверрайд)."""
    return GitUrlSource(
        repo.as_uri(),
        cache,
        allowed_schemes=frozenset({"file"}),
        extra_git_cfg=("-c", "protocol.file.allow=always"),
        **kwargs,
    )


# ── SSRF: парсинг/валидация URL ───────────────────────────────────────────

def test_https_only_default():
    # Продакшн-дефолт разрешает только https; проверка — в resolve()/parse
    assert DEFAULT_ALLOWED_SCHEMES == frozenset({"https"})


@pytest.mark.asyncio
async def test_parse_rejects_bad_urls(tmp_path):
    bad = [
        ("http://github.com/x/y", "invalid_scheme"),
        ("ssh://git@github.com/x/y", "invalid_scheme"),
        ("git://github.com/x/y", "invalid_scheme"),
        ("file:///tmp/x", "invalid_scheme"),
        ("https://evil.example.com/x", "domain_not_allowed"),
        ("https://user:pass@github.com/x", "credentials_in_url"),
        ("https://github.com:8443/x", "invalid_port"),
    ]
    for url, kind in bad:
        src = GitUrlSource(url, tmp_path / "cache")
        with pytest.raises(GitUrlSourceError) as ei:
            await src.resolve()
        assert ei.value.kind == kind, f"{url}: {ei.value.kind} != {kind}"


@pytest.mark.asyncio
async def test_localhost_https_rejected(tmp_path):
    # localhost резолвится в loopback → non_global_ip (SSRF-защита)
    src = GitUrlSource(
        "https://localhost/x/y",
        tmp_path / "cache",
        allowed_domains=frozenset({"localhost"}),
    )
    with pytest.raises(GitUrlSourceError) as ei:
        await src.resolve()
    assert ei.value.kind == "non_global_ip"


def test_ips_are_global():
    assert not _ips_are_global(["127.0.0.1"])
    assert not _ips_are_global(["10.0.0.1"])
    assert not _ips_are_global(["169.254.169.254"])  # IMDS
    assert not _ips_are_global(["192.168.1.1"])
    assert not _ips_are_global(["::1"])
    assert _ips_are_global(["8.8.8.8"])
    assert _ips_are_global(["8.8.8.8", "1.1.1.1"])
    assert not _ips_are_global(["8.8.8.8", "127.0.0.1"])


# ── Happy-path клонирование (локальный репо, file-схема) ──────────────────

@pytest.mark.asyncio
async def test_clone_and_resolve(tmp_path):
    repo = _make_git_repo(tmp_path / "remote", {"a.py": "x = 1\n", "sub/b.py": "y = 2\n"})
    src = _file_source(repo, tmp_path / "cache")

    resolved = await src.resolve()
    assert resolved.is_dir()
    assert (resolved / "a.py").exists()
    assert (resolved / "sub" / "b.py").exists()
    # в кэше лежит НЕ исходный репо, а клон
    assert resolved != repo


@pytest.mark.asyncio
async def test_second_resolve_hits_cache(tmp_path):
    repo = _make_git_repo(tmp_path / "remote")
    cache = tmp_path / "cache"
    src = _file_source(repo, cache)

    p1 = await src.resolve()
    p2 = await src.resolve()
    assert p1 == p2
    # Кэш-хит не создаёт tmp-клоны (.tmp_*)
    tmps = [p for p in cache.glob(".tmp_*")] if cache.exists() else []
    assert tmps == []


def test_fingerprint_git_tree(tmp_path):
    repo = _make_git_repo(tmp_path / "remote")
    src = _file_source(repo, tmp_path / "cache")

    fp1 = src.fingerprint(repo)
    assert len(fp1) == 64
    fp2 = src.fingerprint(repo)
    assert fp1 == fp2
    # fingerprint строится по HEAD-tree: рабочее дерево без коммита не влияет
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    assert src.fingerprint(repo) == fp1
    # новый коммит меняет HEAD → fingerprint меняется
    _run_git(["-C", str(repo), "add", "."])
    _run_git(["-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "v2"])
    assert src.fingerprint(repo) != fp1


# ── Лимиты (DoS) ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_size_limit_rejects(tmp_path):
    repo = _make_git_repo(tmp_path / "remote", {"big.bin": "0" * 2000})
    src = _file_source(repo, tmp_path / "cache", max_clone_bytes=100)
    with pytest.raises(GitUrlSourceError) as ei:
        await src.resolve()
    assert ei.value.kind == "too_large"


@pytest.mark.asyncio
async def test_file_count_limit_rejects(tmp_path):
    repo = _make_git_repo(
        tmp_path / "remote", {f"f{i}.py": "x\n" for i in range(10)}
    )
    src = _file_source(repo, tmp_path / "cache", max_file_count=5)
    with pytest.raises(GitUrlSourceError) as ei:
        await src.resolve()
    assert ei.value.kind == "too_many_files"


# ── INCONCLUSIVE-путь: несуществующий источник ────────────────────────────

@pytest.mark.asyncio
async def test_nonexistent_repo_is_inconclusive(tmp_path):
    src = GitUrlSource(
        (tmp_path / "no-such-repo").as_uri(),
        tmp_path / "cache",
        allowed_schemes=frozenset({"file"}),
    )
    with pytest.raises(GitUrlSourceError) as ei:
        await src.resolve()
    assert ei.value.kind in ("clone_failed", "clone_error")


@pytest.mark.asyncio
async def test_failed_clone_leaves_no_orphan(tmp_path):
    """Неудачный клон не оставляет orphan-каталог (E-03: clone-in-place + rmtree)."""
    src = GitUrlSource(
        (tmp_path / "no-such-repo").as_uri(),
        tmp_path / "cache",
        allowed_schemes=frozenset({"file"}),
    )
    with pytest.raises(GitUrlSourceError):
        await src.resolve()
    cache_root = tmp_path / "cache"
    leftovers = [p.name for p in cache_root.glob("*") if p.is_dir()] if cache_root.exists() else []
    assert leftovers == []


# ── Кэш: LRU + TTL ────────────────────────────────────────────────────────

def test_cache_lru_eviction(tmp_path):
    cache = GitRepoCache(tmp_path, max_entries=2)
    for i in range(3):
        d = tmp_path / f"repo{i}"
        d.mkdir()
        (d / "f").write_text("x", encoding="utf-8")
        cache.put(f"url{i}", f"h{i}", d, 1)
        time.sleep(0.01)
    assert cache.get("h0") is None  # старейший эвиктирован
    assert cache.get("h1") is not None
    assert cache.get("h2") is not None


def test_cache_ttl_expiry(tmp_path):
    cache = GitRepoCache(tmp_path, ttl_sec=0.0)
    d = tmp_path / "repo"
    d.mkdir()
    (d / "f").write_text("x", encoding="utf-8")
    cache.put("url", "h", d, 1)
    assert cache.get("h") is None  # TTL=0 → сразу протух
