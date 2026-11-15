"""Tests for the workflow supply-chain gate (`scripts/check_workflow_pins.py`).

The gate exists because all ten `uses:` in this repository were tag-pinned on
2026-11-14: a moved tag would run foreign code in CI with the workflow token.
Half of these tests are negative controls on synthetic YAML, the rest are
positive controls on the real files — a guard that cannot fail is decoration.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import check_workflow_pins as guard  # noqa: E402

SHA = "fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09"


def workflow(step: str) -> str:
    return (
        "name: CI\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        f"{step}"
    )


def test_tag_pin_is_rejected():
    text = workflow("      - uses: actions/checkout@v5  # v5.1.0\n")
    problems, uses, _ = guard.scan_text(text)
    assert uses == 1
    assert any("not pinned to a 40-character commit SHA" in p for p in problems)


def test_pinned_action_with_version_comment_is_accepted():
    text = workflow(f"      - uses: actions/setup-python@{SHA}  # v5.6.0\n")
    problems, uses, checkouts = guard.scan_text(text)
    assert problems == []
    assert (uses, checkouts) == (1, 0)


def test_pinned_action_without_version_comment_is_rejected():
    text = workflow(f"      - uses: actions/setup-python@{SHA}\n")
    problems, _, _ = guard.scan_text(text)
    assert any("no version comment" in p for p in problems)


def test_checkout_without_persist_credentials_is_rejected():
    text = workflow(
        f"      - uses: actions/checkout@{SHA}  # v5.1.0\n"
        "        with:\n"
        "          fetch-depth: 0\n"
    )
    problems, _, checkouts = guard.scan_text(text)
    assert checkouts == 1
    assert any("persist-credentials: false" in p for p in problems)


def test_checkout_with_persist_credentials_false_is_accepted():
    text = workflow(
        f"      - uses: actions/checkout@{SHA}  # v5.1.0\n"
        "        with:\n"
        "          persist-credentials: false\n"
        "          fetch-depth: 0\n"
    )
    problems, _, checkouts = guard.scan_text(text)
    assert problems == []
    assert checkouts == 1


def test_persist_credentials_true_is_rejected():
    text = workflow(
        f"      - uses: actions/checkout@{SHA}  # v5.1.0\n"
        "        with:\n"
        "          persist-credentials: true\n"
    )
    problems, _, _ = guard.scan_text(text)
    assert any("persist-credentials: false" in p for p in problems)


def test_checkout_followed_by_another_step_cannot_borrow_its_with_block():
    text = workflow(
        f"      - uses: actions/checkout@{SHA}  # v5.1.0\n"
        f"      - uses: actions/setup-python@{SHA}  # v5.6.0\n"
        "        with:\n"
        "          persist-credentials: false\n"
    )
    problems, _, _ = guard.scan_text(text)
    assert any("checkout does not set" in p for p in problems)


def test_local_and_docker_references_are_skipped():
    text = workflow(
        "      - uses: ./.github/actions/local\n"
        "      - uses: docker://alpine:3.20\n"
    )
    problems, uses, _ = guard.scan_text(text)
    assert (problems, uses) == ([], 0)


def test_every_action_in_this_repository_is_pinned():
    """Positive control on the real tree: the files must satisfy their own gate."""
    workflows = sorted((REPO / ".github" / "workflows").glob("*.yml"))
    assert workflows, "no workflows found — the gate would be vacuous"
    total = 0
    for wf in workflows:
        problems, uses, _ = guard.scan_text(wf.read_text(encoding="utf-8"))
        total += uses
        assert problems == [], f"{wf.name}: {problems}"
    assert total >= 10, f"expected the repo to use at least 10 actions, saw {total}"


def test_scan_of_an_empty_file_finds_nothing_and_that_is_visible():
    problems, uses, checkouts = guard.scan_text("")
    assert (problems, uses, checkouts) == ([], 0, 0)
