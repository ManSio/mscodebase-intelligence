"""Тесты Фазы 2 Universal Engine: UploadSource (архив → workspace, R-3).

Покрывает: happy-path (zip/tar), path-traversal (../ и абсолютные), symlink-члены,
decompression-bomb (linit объёма), fingerprint (content-hash → skip re-extract),
cache-hit, missing-archive → INCONCLUSIVE.
"""

import asyncio
import tarfile
import zipfile
from io import BytesIO

import pytest

from src.sources.upload import UploadSource, UploadSourceError


def _make_zip(files: dict, traversal: bool = False, symlink: bool = False) -> BytesIO:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
        if traversal:
            zf.writestr("../evil.txt", "pwned")
        if symlink:
            info = zipfile.ZipInfo("link")
            info.external_attr = (0o120777 << 16)  # symlink mode
            zf.writestr(info, "target")
    buf.seek(0)
    return buf


def _make_tar(files: dict, compression: str = "", traversal: bool = False,
              symlink: bool = False) -> BytesIO:
    mode = f"w:{compression}" if compression else "w"
    buf = BytesIO()
    with tarfile.open(fileobj=buf, mode=mode) as tf:
        for name, content in files.items():
            data = content.encode("utf-8")
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, BytesIO(data))
        if traversal:
            ti = tarfile.TarInfo("../../evil.txt")
            ti.size = 5
            tf.addfile(ti, BytesIO(b"pwned"))
        if symlink:
            ti = tarfile.TarInfo("link")
            ti.type = tarfile.SYMTYPE
            ti.linkname = "target"
            tf.addfile(ti)
    buf.seek(0)
    return buf


@pytest.mark.asyncio
async def test_zip_happy_path(tmp_path):
    archive = tmp_path / "a.zip"
    files = {"a.py": "x=1\n", "sub/b.py": "y=2\n"}
    archive.write_bytes(_make_zip(files).read())
    src = UploadSource(archive, tmp_path / "cache")
    extracted = await src.resolve()
    assert (extracted / "a.py").read_text() == "x=1\n"
    assert (extracted / "sub" / "b.py").read_text() == "y=2\n"


@pytest.mark.asyncio
async def test_tar_gz_happy_path(tmp_path):
    archive = tmp_path / "a.tar.gz"
    archive.write_bytes(_make_tar({"README.md": "hi\n"}, compression="gz").read())
    src = UploadSource(archive, tmp_path / "cache")
    extracted = await src.resolve()
    assert (extracted / "README.md").read_text() == "hi\n"


@pytest.mark.asyncio
async def test_path_traversal_zip_rejected(tmp_path):
    archive = tmp_path / "bad.zip"
    archive.write_bytes(_make_zip({"a.py": "x"}, traversal=True).read())
    src = UploadSource(archive, tmp_path / "cache")
    with pytest.raises(UploadSourceError) as ei:
        await src.resolve()
    assert ei.value.kind == "path_traversal"


@pytest.mark.asyncio
async def test_path_traversal_tar_rejected(tmp_path):
    archive = tmp_path / "bad.tar"
    archive.write_bytes(_make_tar({"a.py": "x"}, traversal=True).read())
    src = UploadSource(archive, tmp_path / "cache")
    with pytest.raises(UploadSourceError) as ei:
        await src.resolve()
    assert ei.value.kind == "path_traversal"


@pytest.mark.asyncio
async def test_symlink_member_rejected(tmp_path):
    archive = tmp_path / "symlink.tar"
    archive.write_bytes(_make_tar({"a.py": "x"}, symlink=True).read())
    src = UploadSource(archive, tmp_path / "cache")
    with pytest.raises(UploadSourceError) as ei:
        await src.resolve()
    assert ei.value.kind == "symlink_member"


@pytest.mark.asyncio
async def test_bomb_guard_rejected(tmp_path):
    # decompression-bomb: распакованный объём (файл 1000B) > лимит 100B → отказ
    archive = tmp_path / "bomb.zip"
    archive.write_bytes(_make_zip({"big.bin": "x" * 1000}).read())
    src = UploadSource(archive, tmp_path / "cache", max_extracted_bytes=100)
    with pytest.raises(UploadSourceError) as ei:
        await src.resolve()
    assert ei.value.kind == "too_large_extracted"


def test_fingerprint_stable_and_cache_hit(tmp_path):
    archive = tmp_path / "a.zip"
    archive.write_bytes(_make_zip({"a.py": "x=1\n"}).read())
    cache = tmp_path / "cache"
    src = UploadSource(archive, cache)
    fp1 = src.fingerprint()
    src2 = UploadSource(archive, cache)
    assert fp1 == src2.fingerprint()

    p1 = asyncio.run(src.resolve())
    p2 = asyncio.run(src2.resolve())
    assert p1 == p2  # cache-hit по content-hash, без повторной распаковки
    assert (p1 / "a.py").exists()


@pytest.mark.asyncio
async def test_missing_archive_is_inconclusive(tmp_path):
    src = UploadSource(tmp_path / "nope.zip", tmp_path / "cache")
    with pytest.raises(UploadSourceError) as ei:
        await src.resolve()
    assert ei.value.kind == "missing_archive"


@pytest.mark.asyncio
async def test_unsupported_format(tmp_path):
    archive = tmp_path / "a.7z"
    archive.write_bytes(b"MSC")
    src = UploadSource(archive, tmp_path / "cache")
    with pytest.raises(UploadSourceError) as ei:
        await src.resolve()
    assert ei.value.kind == "unsupported_format"
