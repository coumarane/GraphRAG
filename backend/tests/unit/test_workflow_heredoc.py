"""Python heredocs in workflows close with the token that opened them."""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_OPEN = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")


def python_heredoc_mismatches(text: str) -> list[str]:
    """Return opener tokens whose closer is missing or is a different token."""
    lines = text.splitlines()
    mismatches: list[str] = []
    index = 0
    while index < len(lines):
        if "python" not in lines[index]:
            index += 1
            continue
        opened = _OPEN.search(lines[index])
        if opened is None:
            index += 1
            continue
        token = opened.group(1)
        closer = next(
            (cursor for cursor in range(index + 1, len(lines)) if lines[cursor].strip() == token),
            None,
        )
        if closer is None:
            mismatches.append(token)
            index += 1
            continue
        index = closer + 1
    return mismatches


def test_workflow_python_heredocs_close_with_their_opener() -> None:
    workflows = sorted((_REPO / ".github" / "workflows").glob("*.yml"))
    assert workflows
    mismatches = {
        path.name: python_heredoc_mismatches(path.read_text())
        for path in workflows
        if python_heredoc_mismatches(path.read_text())
    }
    assert mismatches == {}


def test_fixture_opened_with_chk_and_closed_with_py_fails() -> None:
    script = "python - <<'CHK'\nprint(1)\nPY\n"
    assert python_heredoc_mismatches(script) == ["CHK"]
