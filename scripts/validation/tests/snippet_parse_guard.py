"""Shared guard for validator test suites that feed Python source snippets to a scanner (#1181).

Most validators under scripts/validation deliberately swallow ``SyntaxError``
from ``ast.parse`` and report "nothing found": correct for a tree scan (one
unparseable repo file must not crash the gate), but it means a typo in a test
snippet silently satisfies any "this must NOT be flagged" assertion without the
validator having examined anything (#1140, #944).

Write every Python snippet a suite hands to a validator through
``write_py_snippet`` so an unparseable one fails the test loudly. A snippet that
is *meant* to be unparseable (testing the scanner's own error path) must say so
with ``write_py_snippet(path, src, intentionally_invalid=True)``.
"""
import ast
from pathlib import Path


def assert_snippet_parses(src: str, label: str = "snippet") -> None:
    try:
        ast.parse(src)
    except SyntaxError as exc:
        raise AssertionError(
            f"test {label} does not parse, so it proves nothing about the validator under test: {exc}"
        ) from exc


def write_py_snippet(path, src: str, *, intentionally_invalid: bool = False, **write_kwargs) -> None:
    if not intentionally_invalid:
        assert_snippet_parses(src, label=f"snippet {Path(path).name}")
    else:
        # A "fixed" intentionally-invalid snippet would silently stop testing the
        # scanner's skip-unparseable path, so the opt-out must name a real failure.
        try:
            ast.parse(src)
        except SyntaxError:
            pass
        else:
            raise AssertionError(
                f"snippet {Path(path).name} is marked intentionally_invalid but parses"
            )
    Path(path).write_text(src, **write_kwargs)
