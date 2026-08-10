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

    def test_handler_with_an_extra_statement_is_flagged(self):
        """Condition (3) used to require a body of ONLY logs and returns.

        One unrelated statement — a cleanup call, an assignment — hid the site
        entirely. The swallow is no less real for having tidied up first.
        """
        self.assertEqual(
            len(
                _flagged(
                    "def f(x):\n"
                    "    try:\n"
                    "        return compute(x)\n"
                    "    except Exception:\n"
                    "        frappe.log_error('boom')\n"
                    "        cleanup()\n"
                    "        return None\n"
                )
            ),
            1,
        )

    def test_poison_cached_failure_is_flagged(self):
        """The live shape this fix was written for (ServiceFieldValidator).

        Caching the falsy value makes ONE transient error permanent for the
        life of the process — strictly worse than returning it once.
        """
        self.assertEqual(
            len(
                _flagged(
                    "def get_meta(self, doctype):\n"
                    "    try:\n"
                    "        meta = frappe.get_meta(doctype)\n"
                    "        self._cache[doctype] = meta\n"
                    "        return meta\n"
                    "    except Exception as e:\n"
                    "        self.logger.warning(f'no meta for {doctype}: {e}')\n"
                    "        self._cache[doctype] = None\n"
                    "        return None\n"
                )
            ),
            1,
        )


class PropagationTest(unittest.TestCase):
    """Condition (2): a handler that propagates is not a swallow.

    Widening (3) makes these reachable for the first time: previously the very
    statement that propagates (a `frappe.throw` call) was also what tripped the
    old "logs and returns only" rule, so they were excluded by accident.
    """

    def test_frappe_throw_is_not_flagged(self):
        """`frappe.throw` raises. 85 live handlers rely on this."""
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception as e:\n"
                "        frappe.log_error('boom')\n"
                "        frappe.throw(_('Could not compute: {0}').format(e))\n"
            ),
            [],
        )

    def test_msgprint_with_raise_exception_is_not_flagged(self):
        """`msgprint` is in LOG_NAMES, but raise_exception=True makes it raise."""
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception:\n"
                "        frappe.msgprint('failed', raise_exception=True)\n"
                "        return None\n"
            ),
            [],
        )

    def test_plain_msgprint_is_still_flagged(self):
        """Without raise_exception it really is just logging."""
        self.assertEqual(
            len(
                _flagged(
                    "def f(x):\n"
                    "    try:\n"
                    "        return compute(x)\n"
                    "    except Exception:\n"
                    "        frappe.msgprint('failed')\n"
                    "        return None\n"
                )
            ),
            1,
        )

    def test_sys_exit_is_not_flagged(self):
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception:\n"
                "        frappe.log_error('boom')\n"
                "        sys.exit(1)\n"
            ),
            [],
        )


class WidenedConditionThreeNegativesTest(unittest.TestCase):
    """The disqualifiers that keep the widened (3) from over-reaching."""

    def test_nested_real_return_is_not_flagged(self):
        """A real value on ANY path means the caller can still get one."""
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception:\n"
                "        frappe.log_error('boom')\n"
                "        if fallback_allowed():\n"
                "            return fallback()\n"
                "        return None\n"
            ),
            [],
        )

    def test_continue_is_not_flagged(self):
        """`continue` resumes the loop; nothing falsy reaches a caller."""
        self.assertEqual(
            _flagged(
                "def f(rows):\n"
                "    out = []\n"
                "    for r in rows:\n"
                "        try:\n"
                "            out.append(compute(r))\n"
                "        except Exception:\n"
                "            frappe.log_error('boom')\n"
                "            failures += 1\n"
                "            continue\n"
                "    return out\n"
            ),
            [],
        )

    def test_nested_function_def_is_not_flagged(self):
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception:\n"
                "        frappe.log_error('boom')\n"
                "        def later():\n"
                "            return real_value()\n"
                "        schedule(later)\n"
                "        return None\n"
            ),
            [],
        )

    def test_handler_with_no_logging_is_not_flagged(self):
        """Out of scope: this rule is about log-AND-swallow, not silent returns."""
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception:\n"
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
