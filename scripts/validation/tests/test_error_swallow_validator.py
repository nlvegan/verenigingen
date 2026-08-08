#!/usr/bin/env python3
"""Unit tests for scripts/validation/error_swallow_validator.py.

Pure-Python (no bench/site needed): each case is a source snippet written to a temp
file and run through scan_file(). Run with:  python -m pytest this_file.py
or plain:  python scripts/validation/tests/test_error_swallow_validator.py
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "error_swallow_validator.py"
_spec = importlib.util.spec_from_file_location("error_swallow_validator", _MOD_PATH)
esv = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = esv
_spec.loader.exec_module(esv)


def _scan(src: str):
    """Return (findings, bad_pragmas) for a snippet."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "snippet.py"
        p.write_text(src)
        return esv.scan_file(p)


def _flagged(src: str) -> list:
    return _scan(src)[0]


class FalsyReturnTest(unittest.TestCase):
    """Condition (4): which returns count as 'swallowed into a falsy value'."""

    def test_return_none_is_flagged(self):
        """The plain shape the validator was written for."""
        self.assertEqual(
            len(
                _flagged(
                    "def f(x):\n"
                    "    try:\n"
                    "        return compute(x)\n"
                    "    except Exception:\n"
                    "        frappe.log_error('boom')\n"
                    "        return None\n"
                )
            ),
            1,
        )

    def test_return_empty_string_is_flagged(self):
        """`return ""` is the PR's own flagship incident.

        get_project_permission_query_conditions returned "" on failure, which
        ERPNext reads as UNRESTRICTED rather than "no access" -- board members got
        org-wide project access (PR #191). A validator motivated by that incident
        has to catch its return value.
        """
        self.assertEqual(
            len(
                _flagged(
                    "def get_conditions(user):\n"
                    "    try:\n"
                    "        return build_condition(user)\n"
                    "    except Exception:\n"
                    "        frappe.log_error('boom')\n"
                    "        return ''\n"
                )
            ),
            1,
        )

    def test_return_zero_is_flagged(self):
        """0 is a falsy swallow; a caller reading it as an amount cannot tell."""
        self.assertEqual(
            len(
                _flagged(
                    "def total(x):\n"
                    "    try:\n"
                    "        return compute(x)\n"
                    "    except Exception:\n"
                    "        frappe.log_error('boom')\n"
                    "        return 0\n"
                )
            ),
            1,
        )

    def test_return_empty_bytes_is_flagged(self):
        self.assertEqual(
            len(
                _flagged(
                    "def payload(x):\n"
                    "    try:\n"
                    "        return compute(x)\n"
                    "    except Exception:\n"
                    "        frappe.log_error('boom')\n"
                    "        return b''\n"
                )
            ),
            1,
        )

    def test_truthy_return_is_not_flagged(self):
        """Returning a real value from the handler is not a swallow."""
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception:\n"
                "        frappe.log_error('boom')\n"
                "        return {'error': 'failed'}\n"
            ),
            [],
        )

    def test_nonempty_string_return_is_not_flagged(self):
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception:\n"
                "        frappe.log_error('boom')\n"
                "        return 'failed'\n"
            ),
            [],
        )


class ImplicitNoneTest(unittest.TestCase):
    """A handler that logs and falls off the end returns None just as loudly."""

    def test_handler_falling_off_end_is_flagged(self):
        """No `return` statement, but the function still hands the caller None."""
        self.assertEqual(
            len(
                _flagged(
                    "def f(x):\n"
                    "    try:\n"
                    "        return compute(x)\n"
                    "    except Exception:\n"
                    "        frappe.log_error('boom')\n"
                )
            ),
            1,
        )

    def test_handler_that_is_not_the_last_statement_is_not_flagged(self):
        """Falling off a mid-function handler RESUMES the function; not a swallow.

        Here the caller still gets compute2()'s value, so nothing was destroyed
        into None -- flagging this would be a false positive.
        """
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        first = compute(x)\n"
                "    except Exception:\n"
                "        frappe.log_error('boom')\n"
                "    return compute2(x)\n"
            ),
            [],
        )

    def test_handler_inside_loop_is_not_flagged(self):
        """Same reasoning: falling off continues the loop, it does not return."""
        self.assertEqual(
            _flagged(
                "def f(rows):\n"
                "    out = []\n"
                "    for r in rows:\n"
                "        try:\n"
                "            out.append(compute(r))\n"
                "        except Exception:\n"
                "            frappe.log_error('boom')\n"
                "    return out\n"
            ),
            [],
        )


class ExistingConditionsTest(unittest.TestCase):
    """Regression guard on conditions (1), (2), (3) and (5)."""

    def test_narrow_except_is_not_flagged(self):
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except ValueError:\n"
                "        frappe.log_error('boom')\n"
                "        return None\n"
            ),
            [],
        )

    def test_reraise_is_not_flagged(self):
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception:\n"
                "        frappe.log_error('boom')\n"
                "        raise\n"
            ),
            [],
        )

    def test_function_with_no_real_return_is_not_flagged(self):
        """Condition (5): fire-and-forget work; no caller can branch on it."""
        self.assertEqual(
            _flagged(
                "def invalidate(x):\n"
                "    try:\n"
                "        cache.delete(x)\n"
                "    except Exception:\n"
                "        frappe.log_error('boom')\n"
                "        return None\n"
            ),
            [],
        )

    def test_handler_with_real_work_is_not_flagged(self):
        """Condition (3): a handler that does more than log is out of scope.

        This is a KNOWN false negative, pinned deliberately so the gap stays
        visible rather than being rediscovered.
        """
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception:\n"
                "        frappe.log_error('boom')\n"
                "        cleanup()\n"
                "        return None\n"
            ),
            [],
        )


class PragmaTest(unittest.TestCase):
    def test_valid_pragma_suppresses(self):
        findings, bad = _scan(
            "def f(x):\n"
            "    try:\n"
            "        return compute(x)\n"
            "    except Exception:  # swallow-ok: best-effort\n"
            "        frappe.log_error('boom')\n"
            "        return None\n"
        )
        self.assertEqual(findings, [])
        self.assertEqual(bad, [])

    def test_invalid_pragma_reason_is_reported(self):
        findings, bad = _scan(
            "def f(x):\n"
            "    try:\n"
            "        return compute(x)\n"
            "    except Exception:  # swallow-ok: because-i-said-so\n"
            "        frappe.log_error('boom')\n"
            "        return None\n"
        )
        self.assertEqual(findings, [])
        self.assertEqual(len(bad), 1)

    def test_pragma_suppresses_implicit_none_too(self):
        findings, _ = _scan(
            "def f(x):\n"
            "    try:\n"
            "        return compute(x)\n"
            "    except Exception:  # swallow-ok: best-effort\n"
            "        frappe.log_error('boom')\n"
        )
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
