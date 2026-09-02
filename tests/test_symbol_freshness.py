"""Freshness layer (issue #21/#22, commit B) for symbol-anchor verification.

A symbol anchor can only REFUTE honestly when the index it was verified
against provably reflects the current codebase: the index's recorded
``build_head`` must equal the live HEAD and the working tree must be clean.
Any other state (mismatched HEAD, legacy index without a build_head, a
non-git repo, or a dirty tree) means freshness is *unverifiable*, and the
verifier must fall back to INCONCLUSIVE — never VERIFIED, never REFUTED.
"""

from pathlib import Path

from src.core.graph import PropertyGraph
from src.core.intelligence.verify_on_read import (
    evaluate_freshness,
    resolve_head_dirty,
)

# =====================================================================
# PURE: evaluate_freshness(build_head, current_head, dirty) -> bool
# =====================================================================


def test_freshness_same_head_clean_allows_refute():
    """Index built on current HEAD, clean tree -> safe to REFUTE a missing
    symbol (resolver may honestly return False)."""
    assert evaluate_freshness("abc123", "abc123", dirty=False) is True


def test_freshness_head_mismatch_is_inconclusive():
    """Index built on an OLDER HEAD than the live one -> cannot prove absence
    -> INCONCLUSIVE (must NOT allow REFUTE)."""
    assert evaluate_freshness("old00", "new00", dirty=False) is False


def test_freshness_legacy_index_without_build_head_is_inconclusive():
    """Migration case: an index built by pre-B code records no build_head.
    Freshness is unknown -> INCONCLUSIVE, not a crash, not VERIFIED/REFUTED."""
    assert evaluate_freshness(None, "abc123", dirty=False) is False


def test_freshness_dirty_tree_is_inconclusive():
    """Even a HEAD match is meaningless while the tree is dirty (uncommitted
    edits may already redefine/remove the symbol) -> INCONCLUSIVE."""
    assert evaluate_freshness("abc123", "abc123", dirty=True) is False


def test_freshness_unidentifiable_current_head_is_inconclusive():
    """Non-git repo / git failure -> no current HEAD -> INCONCLUSIVE."""
    assert evaluate_freshness("abc123", None, dirty=False) is False


# =====================================================================
# INTEGRATION: resolve_head_dirty(root) -> Optional[(head, dirty)]
# =====================================================================


def test_resolve_head_dirty_returns_none_for_non_git(tmp_path: Path):
    """A directory that is not a git repo yields no HEAD -> INCONCLUSIVE."""
    root = tmp_path / "not_a_git"
    root.mkdir(parents=True, exist_ok=True)
    (root / "plain.txt").write_text("x", encoding="utf-8")
    assert resolve_head_dirty(root) is None


# =====================================================================
# CHARACTERIZATION: recording build_head into graph meta
# =====================================================================


def test_propertygraph_build_head_roundtrip(tmp_path: Path):
    """The graph meta table must round-trip a build_head (the substrate the
    resolver reads): set during a successful build, read back at verify time."""
    g = PropertyGraph(tmp_path / "g.db")
    assert g.get_meta("build_head") is None
    g.set_meta("build_head", "deadbeef")
    assert g.get_meta("build_head") == "deadbeef"
    g.close()
