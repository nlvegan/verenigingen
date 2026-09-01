#!/usr/bin/env python3
"""Unit tests for scripts/validation/error_swallow_validator.py.

Pure-Python (no bench/site needed): each case is a source snippet written to a temp
file and run through scan_file(). Run with:  python -m pytest this_file.py
or plain:  python scripts/validation/tests/test_error_swallow_validator.py
"""
import ast
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


class ProjectLoggingHelpersTest(unittest.TestCase):
    """`LOG_NAMES` has to know THIS repo's error helpers, not just Frappe's.

    A handler that records the failure through `safe_log_error` or a service's
    `handle_error` is a log-and-swallow exactly like one calling
    `frappe.log_error` -- but it was invisible, because the validator only
    recognised the framework's own names.
    """

    def test_safe_log_error_counts_as_logging(self):
        self.assertEqual(
            len(
                _flagged(
                    "def f(x):\n"
                    "    try:\n"
                    "        return compute(x)\n"
                    "    except Exception as e:\n"
                    "        safe_log_error(f'boom: {e}')\n"
                    "        return None\n"
                )
            ),
            1,
        )

    def test_log_action_counts_as_logging(self):
        self.assertEqual(
            len(
                _flagged(
                    "def f(self, x):\n"
                    "    try:\n"
                    "        return compute(x)\n"
                    "    except Exception as e:\n"
                    "        self.log_action('failed', {'error': str(e)}, level='error')\n"
                    "        return None\n"
                )
            ),
            1,
        )

    def test_log_error_with_traceback_counts_as_logging(self):
        self.assertEqual(
            len(
                _flagged(
                    "def f(x):\n"
                    "    try:\n"
                    "        return compute(x)\n"
                    "    except Exception as e:\n"
                    "        _log_error_with_traceback('Title', str(e))\n"
                    "        return None\n"
                )
            ),
            1,
        )

    def test_handle_error_with_raise_error_false_is_flagged(self):
        """Explicitly told NOT to raise, so the failure really is swallowed."""
        self.assertEqual(
            len(
                _flagged(
                    "def f(self, x):\n"
                    "    try:\n"
                    "        return compute(x)\n"
                    "    except Exception as e:\n"
                    "        self.handle_error(e, 'op', {}, raise_error=False)\n"
                    "        return None\n"
                )
            ),
            1,
        )

    def test_handle_error_without_raise_error_is_NOT_flagged(self):
        """`handle_service_error(raise_error=True)` is the DEFAULT, so a bare
        `self.handle_error(e, 'op')` re-raises. Treating the name as pure logging
        would invent a swallow where the failure actually propagates -- the same
        trap `frappe.throw` set for condition (2)."""
        self.assertEqual(
            _flagged(
                "def f(self, x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception as e:\n"
                "        self.handle_error(e, 'op')\n"
                "        return None\n"
            ),
            [],
        )

    def test_handle_service_error_default_is_NOT_flagged(self):
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception as e:\n"
                "        handle_service_error(e, 'svc', 'op')\n"
                "        return None\n"
            ),
            [],
        )

    def test_handle_error_with_non_literal_raise_error_is_NOT_flagged(self):
        """`raise_error=flag` cannot be resolved statically; assume it raises."""
        self.assertEqual(
            _flagged(
                "def f(self, x, flag):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception as e:\n"
                "        self.handle_error(e, 'op', raise_error=flag)\n"
                "        return None\n"
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


class SentinelObjectReturnTest(unittest.TestCase):
    """Condition (4) beyond literals: a falsy-MEANING sentinel (#586).

    PR #585 changed one handler from `return None` to `return InvoiceChoice(None, 0)`
    -- no behavioural change at all -- and the site DROPPED OUT of the baseline,
    because every branch of `_is_falsy_return` matched only a literal. A swallow that
    leaves the baseline reads as progress, and the printed remedy is
    `--update-baseline`, so the default action converts a guarded site into an
    unguarded one.

    Measured across `verenigingen/` and `scripts/`: handlers whose every return is a
    call with at least one argument, all of them falsy literals -- ONE, the site
    above. So this is a narrow widening, not a class; the tests below pin the two
    shapes that must NOT be swept in with it.
    """

    def test_call_with_all_falsy_args_is_flagged(self):
        """The #585 shape: a result object carrying no information at all."""
        self.assertEqual(
            len(
                _flagged(
                    "def f(x):\n"
                    "    try:\n"
                    "        return Choice(compute(x), 1)\n"
                    "    except Exception:\n"
                    "        frappe.log_error('boom')\n"
                    "        return Choice(None, 0)\n"
                )
            ),
            1,
        )

    def test_zero_argument_call_is_not_flagged(self):
        """The issue's own suggested rule -- "all arguments are falsy" -- is wrong.

        `all([])` is True, so a call with NO arguments satisfies it vacuously. That
        rule was measured against the tree: 1 true positive and 10 false positives,
        every one of them a real fallback or an explicit error return --
        `get_fallback_cost_center()`, `_get_empty_statistics()`,
        `self._load_payment_history_original()`, and three
        `OperationResult.fail(...).to_dict()` chains whose OUTER call is `to_dict()`.
        """
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception:\n"
                "        frappe.log_error('boom')\n"
                "        return get_fallback_cost_center()\n"
            ),
            [],
        )

    def test_a_bare_mention_of_the_exception_does_not_count_as_carrying_it(self):
        """`_returns_the_cause` must not be satisfied by a one-token bypass.

        477 of the 489 broad handlers in baselined functions bind `e`, so a predicate
        that matched the name ANYWHERE in a return was doing far too much work to be
        that loose: `return Choice(None, 0) if e else Choice(None, 0)` mentions `e` and
        hands the caller nothing.
        """
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp).resolve()
            (d / "mod.py").write_text(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception as e:\n"
                "        frappe.log_error('boom')\n"
                "        return Choice(None, 0) if e else Choice(None, 0)\n"
            )
            original = esv.REPO_ROOT
            esv.REPO_ROOT = d
            try:
                reported = esv.explain_shrink({"mod.py::f": 1}, [str(d)])
            finally:
                esv.REPO_ROOT = original
        self.assertEqual([u.reason for u in reported], ["unrecognised"])

    def test_call_carrying_the_cause_is_not_flagged(self):
        """An explicit error return is the remedy this validator ASKS for.

        `Result(False, str(e))` hands the caller the cause, so it is not a swallow --
        the same reason a dict with a real value in it is not (`DictOfFalsyValuesTest`
        below: a dict of ZEROS is flagged, an error report is not).
        """
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception as e:\n"
                "        frappe.log_error('boom')\n"
                "        return Result(False, str(e))\n"
            ),
            [],
        )


class FalsySequenceReturnTest(unittest.TestCase):
    """A sequence holding nothing but falsy literals carries no more than an empty one.

    `MT940Import.get_transaction_date_range` returns `None, None` from its handler --
    and an identical `return None, None` sits FOUR LINES ABOVE it (149 vs 153) as the
    legitimate "no transactions in range" answer. The caller cannot tell them apart, which is this bug class
    exactly. Measured: extending the branch adds 3 sites tree-wide and removes none.
    """

    def test_tuple_of_falsy_literals_is_flagged(self):
        self.assertEqual(
            len(
                _flagged(
                    "def f(x):\n"
                    "    try:\n"
                    "        return compute(x), other(x)\n"
                    "    except Exception:\n"
                    "        frappe.log_error('boom')\n"
                    "        return None, None\n"
                )
            ),
            1,
        )

    def test_tuple_carrying_a_real_element_is_not_flagged(self):
        """`return False, "no mandate"` tells the caller which failure it got."""
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        return True, compute(x)\n"
                "    except Exception:\n"
                "        frappe.log_error('boom')\n"
                "        return False, 'lookup failed'\n"
            ),
            [],
        )


class DictOfFalsyValuesTest(unittest.TestCase):
    """A non-empty dict whose every value is a falsy literal carries no cause (#589).

    This reverses an exclusion the validator made on purpose from the day it was
    written: `{"success": False, "error": str(e)}` is the remedy it PRINTS, and the
    project's own notes record that shape as truthy-but-CORRECT. The distinction the
    branch draws is not "empty vs non-empty" but "is there anywhere the cause could
    be" -- `{"today": 0, "week": 0}` has nowhere, `{"error": str(e)}` has one.

    Measured over both SCAN_ROOTS against the shipped rule, in BOTH directions: adds
    exactly 8 sites, removes 0. The negative tests here are anchored by the positive
    ones above them, so a predicate that simply stopped matching dicts would fail.
    """

    def test_dict_of_zeros_is_flagged(self):
        """The dashboard-fallback shape: 7 of the 8 sites this adds."""
        self.assertEqual(
            len(
                _flagged(
                    "def f(x):\n"
                    "    try:\n"
                    "        return compute(x)\n"
                    "    except Exception as e:\n"
                    "        frappe.log_error('boom')\n"
                    "        return {'today': 0, 'week': 0, 'daily_average': 0}\n"
                )
            ),
            1,
        )

    def test_dict_of_all_false_permissions_is_flagged(self):
        """The 8th site, and the one worth reading first.

        `ChapterQueryService.get_user_permissions_optimized` hands back an all-falsy
        permission dict (`is_board_member=False`, `board_role=None`, ...) when the roles
        query raises. Read off the VALUE that direction is fail-closed, so it is not PR
        #191 repeating -- there a permission hook returned `""`, which ERPNext reads as
        UNRESTRICTED. That is as far as the claim goes: the only in-repo consumer is
        `Chapter.get_user_permissions_optimized` (chapter.py:577), which has no callers
        at all, so there is nothing to check the direction against. The swallow is the
        same either way -- a caller could not tell "no rights" from "the query blew up".
        """
        self.assertEqual(
            len(
                _flagged(
                    "def get_user_permissions_optimized(user):\n"
                    "    try:\n"
                    "        return build_permissions(user)\n"
                    "    except Exception as e:\n"
                    "        frappe.log_error('boom')\n"
                    "        return {'can_edit': False, 'can_delete': False}\n"
                )
            ),
            1,
        )

    def test_empty_dict_is_still_flagged(self):
        """The arm that existed before this one; it must survive the widening."""
        self.assertEqual(
            len(
                _flagged(
                    "def f(x):\n"
                    "    try:\n"
                    "        return compute(x)\n"
                    "    except Exception:\n"
                    "        frappe.log_error('boom')\n"
                    "        return {}\n"
                )
            ),
            1,
        )

    def test_dict_carrying_the_cause_is_not_flagged(self):
        """The load-bearing negative: this is the remedy the validator prints.

        Flagging `{"success": False, "error": str(e)}` would make the guard demand a
        change it has no better answer for, and would redden a shape the project uses
        deliberately.
        """
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception as e:\n"
                "        frappe.log_error('boom')\n"
                "        return {'success': False, 'error': str(e)}\n"
            ),
            [],
        )

    def test_one_real_value_keeps_the_whole_dict_unflagged(self):
        """`all()` over the VALUES, not any(): one informative entry is enough."""
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception:\n"
                "        frappe.log_error('boom')\n"
                "        return {'count': 0, 'message': 'lookup failed'}\n"
            ),
            [],
        )

    def test_a_non_literal_value_is_not_a_falsy_literal(self):
        """`{**defaults}` and `{'rows': []}` hold expressions, not falsy CONSTANTS.

        The arm deliberately matches `ast.Constant` only, exactly like the sequence
        arm beside it. A nested empty container is a known limit, not an oversight:
        widening to it is a separate measurement.
        """
        for value in ("{**defaults}", "{'rows': []}", "{'n': count}"):
            with self.subTest(value=value):
                self.assertEqual(
                    _flagged(
                        "def f(x):\n"
                        "    try:\n"
                        "        return compute(x)\n"
                        "    except Exception:\n"
                        "        frappe.log_error('boom')\n"
                        f"        return {value}\n"
                    ),
                    [],
                )

    def test_widening_can_REMOVE_a_finding_through_condition_5(self):
        """The hazard that makes the measurement two-directional, pinned as behaviour.

        `_is_falsy_return` also feeds condition (5) -- "the enclosing function
        elsewhere returns a real value". So a function whose ONLY non-handler return
        is now recognised as falsy stops qualifying, and its swallow LEAVES the
        report. That is how a previous widening deleted 6 genuine findings while
        adding 7 false ones.

        Measured on this tree the widening removes 0, because no such function exists
        today -- this test is the construction that would have been removed, so the
        mechanism is documented rather than merely asserted absent.
        """
        src = (
            "def f(x):\n"
            "    if x:\n"
            "        return {'total': 0}\n"
            "    try:\n"
            "        return {'total': compute(x)}\n"
            "    except Exception:\n"
            "        frappe.log_error('boom')\n"
            "        return None\n"
        )
        # The `try` branch returns a REAL dict, so (5) still holds and the site stands.
        self.assertEqual(len(_flagged(src)), 1)
        # Make every non-handler return a dict of zeros and (5) fails: nothing reported.
        self.assertEqual(_flagged(src.replace("compute(x)", "0")), [])


    def test_the_shrink_explainer_inherits_the_widening(self):
        """Widening the falsy test widens the gate that guards its own removals.

        The arm has a knowingly crude exemption -- ANY non-falsy value lets the dict
        through, a hard-coded string included. For an already-baselined site that is
        not a free bypass: dropping out of the count sends the entry to
        `explain_shrink`, which asks a DIFFERENT question (`_returns_the_cause`), and a
        truthy-but-uninformative value fails it. The third case is the control: a fix
        that really does carry the cause must NOT be accused.
        """
        cases = {
            "{'today': 0, 'status': 'error'}": ["unrecognised"],  # evasion: reported
            "{'today': 0, 'error': str(e)}": [],  # a real fix: silent
            "{'today': 0}": [],  # still falsy, so still COUNTED: never a shrink
        }
        for ret, expected in cases.items():
            with self.subTest(ret=ret):
                with tempfile.TemporaryDirectory() as tmp:
                    d = Path(tmp).resolve()
                    (d / "mod.py").write_text(
                        "def f(x):\n"
                        "    try:\n"
                        "        return compute(x)\n"
                        "    except Exception as e:\n"
                        "        frappe.log_error('boom')\n"
                        f"        return {ret}\n"
                    )
                    original = esv.REPO_ROOT
                    esv.REPO_ROOT = d
                    try:
                        reported = esv.explain_shrink({"mod.py::f": 1}, [str(d)])
                    finally:
                        esv.REPO_ROOT = original
                self.assertEqual([u.reason for u in reported], expected)


class EmptyFStringReturnTest(unittest.TestCase):
    """`return f""` is `return ""`, but it parses as `ast.JoinedStr` (#589).

    0 occurrences in the tree today. It is closed anyway because `""` is this
    validator's flagship incident -- a permission hook returning it gave board members
    org-wide project access (PR #191) -- and an f-string is a one-character edit away
    from a plain string literal.
    """

    def test_empty_fstring_is_flagged(self):
        self.assertEqual(
            len(
                _flagged(
                    "def get_conditions(user):\n"
                    "    try:\n"
                    "        return build_condition(user)\n"
                    "    except Exception:\n"
                    "        frappe.log_error('boom')\n"
                    '        return f""\n'
                )
            ),
            1,
        )

    def test_fstring_interpolating_the_cause_is_not_flagged(self):
        """`f"{e}"` has a FormattedValue part, so it is not an empty string."""
        self.assertEqual(
            _flagged(
                "def get_conditions(user):\n"
                "    try:\n"
                "        return build_condition(user)\n"
                "    except Exception as e:\n"
                "        frappe.log_error('boom')\n"
                '        return f"failed: {e}"\n'
            ),
            [],
        )

    def test_a_nonempty_fstring_literal_is_not_flagged(self):
        self.assertEqual(
            _flagged(
                "def get_conditions(user):\n"
                "    try:\n"
                "        return build_condition(user)\n"
                "    except Exception:\n"
                "        frappe.log_error('boom')\n"
                '        return f"1=0"\n'
            ),
            [],
        )


class EmptyConstructorReturnTest(unittest.TestCase):
    """`dict()` IS `{}`, but `all([])` is True so the >=1-argument guard excludes it.

    The guard cannot be relaxed -- measured, dropping it adds 7 false findings and
    removes 6 real ones -- so these are reached by NAME instead. 0 occurrences in the
    tree today; the negative tests below are what keep the allowlist from becoming the
    relaxation it exists to avoid.

    `str()` is in the set for the same reason `EmptyFStringReturnTest` exists: it IS
    `""`, the value ERPNext reads as UNRESTRICTED from a permission hook. Closing the
    f-string shape on that reasoning while leaving `str()` open would have been
    inconsistent with it. Adding the remaining argument-less builtins was measured at
    0 added / 0 removed.
    """

    def test_empty_constructors_are_flagged(self):
        for ctor in (
            "dict()", "list()", "tuple()", "set()", "frappe._dict()", "_dict()",
            "str()", "bytes()", "bytearray()", "frozenset()",
            "bool()", "int()", "float()", "complex()",
        ):
            with self.subTest(ctor=ctor):
                self.assertEqual(
                    len(
                        _flagged(
                            "def f(x):\n"
                            "    try:\n"
                            "        return compute(x)\n"
                            "    except Exception:\n"
                            "        frappe.log_error('boom')\n"
                            f"        return {ctor}\n"
                        )
                    ),
                    1,
                )

    def test_the_seven_false_positives_the_guard_exists_to_drop_stay_dropped(self):
        """Every zero-argument call in the tree's broad handlers is one of these.

        Measured over both SCAN_ROOTS: 11 distinct zero-argument calls are returned
        from inside a broad `except`, all of them fallbacks, retries or
        `OperationResult.fail(...).to_dict()` chains, and NOT ONE is an allowlisted
        name. The allowlist is therefore additive by construction.
        """
        for call in (
            "get_fallback_cost_center()",
            "_get_empty_statistics()",
            "get_empty_coverage_analysis()",
            "self._load_payment_history_original()",
            "OperationResult.fail('boom', errors=[], user=None).to_dict()",
        ):
            with self.subTest(call=call):
                self.assertEqual(
                    _flagged(
                        "def f(x):\n"
                        "    try:\n"
                        "        return compute(x)\n"
                        "    except Exception:\n"
                        "        frappe.log_error('boom')\n"
                        f"        return {call}\n"
                    ),
                    [],
                )

    def test_the_allowlist_matches_the_DOTTED_name_not_the_last_attribute(self):
        """`self.dict()` is a method call, not the builtin; `x.list()` likewise."""
        for call in ("self.dict()", "response.list()", "cache.set()"):
            with self.subTest(call=call):
                self.assertEqual(
                    _flagged(
                        "def f(x):\n"
                        "    try:\n"
                        "        return compute(x)\n"
                        "    except Exception:\n"
                        "        frappe.log_error('boom')\n"
                        f"        return {call}\n"
                    ),
                    [],
                )


class ReturnsTheCauseTest(unittest.TestCase):
    """Each of the three ways a return can carry the cause needs its own test.

    `_returns_the_cause` advertises "as a call argument, through an attribute, or
    interpolated into an f-string". Two of those three had no test at all, and the
    keyword-argument half of the first had none either -- all three mutants survived.
    These are negative assertions, so they are anchored by
    `test_a_bare_mention_of_the_exception_does_not_count_as_carrying_it`, which proves
    the reporter fires when the cause is genuinely absent.
    """

    def _shrink(self, ret: str):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp).resolve()
            (d / "mod.py").write_text(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception as e:\n"
                "        frappe.log_error('boom')\n"
                f"        return {ret}\n"
            )
            original = esv.REPO_ROOT
            esv.REPO_ROOT = d
            try:
                return esv.explain_shrink({"mod.py::f": 1}, [str(d)])
            finally:
                esv.REPO_ROOT = original

    def test_the_cause_through_an_attribute(self):
        self.assertEqual(self._shrink("Result(False, e.args)"), [])

    def test_the_cause_interpolated_into_an_fstring(self):
        self.assertEqual(self._shrink('f"lookup failed: {e}"'), [])

    def test_the_cause_as_a_keyword_argument(self):
        self.assertEqual(self._shrink("Result(ok=False, err=e)"), [])

    def test_a_DIFFERENT_name_is_not_the_bound_exception(self):
        """`_is_bound_name` must compare the name, not merely be an `ast.Name`.

        Without the comparison any name in a return would read as "carries the cause",
        which is every non-falsy return there is.
        """
        self.assertEqual(
            [u.reason for u in self._shrink("Choice(fallback, 0)")], ["unrecognised"]
        )


class StructuralDisqualifierTest(unittest.TestCase):
    """Target the disqualifiers in `_is_structural_swallow` DIRECTLY.

    The pre-existing tests for these two exercised something else: the nested-`def`
    case was excluded because `ast.walk` reached the nested real return, and the
    `continue` case because its handler had no return and its `try` was not last. Both
    mutants survived. These snippets fail on the disqualifier and nothing else.
    """

    def test_a_nested_def_disqualifies_even_with_only_a_falsy_return(self):
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception:\n"
                "        def _cleanup():\n"
                "            pass\n"
                "        frappe.log_error('boom')\n"
                "        return None\n"
            ),
            [],
        )

    def test_a_continue_disqualifies_even_alongside_a_falsy_return(self):
        self.assertEqual(
            _flagged(
                "def f(items):\n"
                "    for i in items:\n"
                "        try:\n"
                "            return compute(i)\n"
                "        except Exception:\n"
                "            frappe.log_error('boom')\n"
                "            if i:\n"
                "                continue\n"
                "            return None\n"
                "    return fallback()\n"
            ),
            [],
        )


class SymlinkedModuleTest(unittest.TestCase):
    """A symlinked module must be counted ONCE (#588).

    `_iter_py` walks with os.walk, which yields a symlink and its target as two
    files, and `_rel` keys the finding by `path.resolve()` -- which collapses them
    onto the same baseline key. `verenigingen/templates/pages/me.py` is a symlink to
    `member_portal.py`, so all four of that file's swallow sites were recorded as
    `::2`, and the ratchet fires only on `count > baseline`. Four free slots.

    Neither of the guard's CI gates can see it: "baseline is in sync" regenerates and
    the doubling is deterministic, and "baseline did not grow" compares totals that
    were already inflated on both sides.
    """

    def _tree(self, d: Path) -> None:
        pkg = d / "pkg"
        pkg.mkdir()
        (pkg / "mod.py").write_text(
            "def f(x):\n"
            "    try:\n"
            "        return compute(x)\n"
            "    except Exception:\n"
            "        frappe.log_error('boom')\n"
            "        return None\n"
        )
        (pkg / "alias.py").symlink_to("mod.py")

    def test_iter_py_yields_each_file_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self._tree(d)
            found = sorted(p.name for p in esv._iter_py([str(d)]))
            self.assertEqual(found, ["mod.py"])

    def test_symlinked_module_is_counted_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp).resolve()
            self._tree(d)
            original = esv.REPO_ROOT
            esv.REPO_ROOT = d
            try:
                counts, _ = esv._counts([str(d)])
            finally:
                esv.REPO_ROOT = original
            self.assertEqual(dict(counts), {"pkg/mod.py::f": 1})


class ShrinkExplanationTest(unittest.TestCase):
    """A baseline entry that LEAVES must say why (#586).

    The gate is the point of the issue: nothing in the guard distinguishes "this
    swallow was fixed" from "this swallow became unrecognisable", and a diff showing
    a REMOVED line reads as good news either way. Only the shrunken keys are
    examined, so the discriminator does not need to be right across the whole tree --
    only on the handful of entries a PR actually removes.
    """

    def _shrink_src(self, src: str, baseline: dict):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp).resolve()
            (d / "mod.py").write_text(src)
            original = esv.REPO_ROOT
            esv.REPO_ROOT = d
            try:
                return esv.explain_shrink(baseline, [str(d)])
            finally:
                esv.REPO_ROOT = original

    def _shrink(self, src: str, key: str):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp).resolve()
            (d / "mod.py").write_text(src)
            original = esv.REPO_ROOT
            esv.REPO_ROOT = d
            try:
                return esv.explain_shrink({key: 1}, [str(d)])
            finally:
                esv.REPO_ROOT = original

    def test_unrecognised_shape_is_reported(self):
        """The #585 incident, with the widening reverted -- an enum member."""
        unexplained = self._shrink(
            "def f(x):\n"
            "    try:\n"
            "        return compute(x)\n"
            "    except Exception:\n"
            "        frappe.log_error('boom')\n"
            "        return State.NOT_FOUND\n",
            "mod.py::f",
        )
        self.assertEqual([u.key for u in unexplained], ["mod.py::f"])

    def test_a_reraise_explains_the_shrink(self):
        """The failure now leaves the handler: a real fix, reported as one."""
        self.assertEqual(
            self._shrink(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception:\n"
                "        frappe.log_error('boom')\n"
                "        raise\n",
                "mod.py::f",
            ),
            [],
        )

    def test_a_return_carrying_the_cause_explains_the_shrink(self):
        """The remedy the validator prints: hand the caller an explicit error."""
        self.assertEqual(
            self._shrink(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception as e:\n"
                "        frappe.log_error('boom')\n"
                "        return {'success': False, 'error': str(e)}\n",
                "mod.py::f",
            ),
            [],
        )

    def test_a_deleted_function_explains_the_shrink(self):
        """The commonest legitimate shrink of all: the code is gone."""
        self.assertEqual(self._shrink("def g(x):\n    return x\n", "mod.py::f"), [])

    def test_fixing_one_of_two_swallows_does_not_report_the_survivor(self):
        """The false alarm a find-first rule produced, pinned.

        A function may hold several swallows. Fixing one leaves the other still
        counted, and asking "is there STILL a swallow-shaped handler here" answers
        yes -- which reported four `member_portal.py` survivors as unexplained when
        the symlink double-count was removed. Only `missing - still counted` entries
        can possibly have become unrecognisable.
        """
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp).resolve()
            (d / "mod.py").write_text(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception:\n"
                "        frappe.log_error('one')\n"
                "        raise\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception:\n"
                "        frappe.log_error('two')\n"
                "        return None\n"
            )
            original = esv.REPO_ROOT
            esv.REPO_ROOT = d
            try:
                # the baseline knew TWO; one now re-raises, the other is still counted
                self.assertEqual(esv.explain_shrink({"mod.py::f": 2}, [str(d)]), [])
            finally:
                esv.REPO_ROOT = original

    def test_a_pragma_explains_the_shrink(self):
        """A `swallow-ok` marker is a deliberate, reviewable exit from the baseline.

        The return must be an UNRECOGNISED one. With `return None` the handler is
        excluded for still being recognised, so `_suppressed` is never reached and the
        test passes for the wrong reason -- mutating that branch away left it green.
        """
        self.assertEqual(
            self._shrink(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception:  # swallow-ok: best-effort\n"
                "        frappe.log_error('boom')\n"
                "        return State.NOT_FOUND\n",
                "mod.py::f",
            ),
            [],
        )

    def test_the_report_is_capped_at_what_actually_went_missing(self):
        """Two unrecognised handlers, but the baseline only ever knew about one."""
        src = (
            "def f(x):\n"
            "    try:\n"
            "        return compute(x)\n"
            "    except Exception:\n"
            "        frappe.log_error('one')\n"
            "        return State.NOT_FOUND\n"
            "    try:\n"
            "        return compute(x)\n"
            "    except Exception:\n"
            "        frappe.log_error('two')\n"
            "        return State.NOT_FOUND\n"
        )
        self.assertEqual(len(self._shrink_src(src, {"mod.py::f": 1})), 1)
        self.assertEqual(len(self._shrink_src(src, {"mod.py::f": 2})), 2)

    LOGGED = (
        "def f(x):\n"
        "    try:\n"
        "        return compute(x)\n"
        "    except Exception:\n"
        "        frappe.log_error('boom')\n"
        "        return None\n"
    )
    SILENCED = (
        "def f(x):\n"
        "    try:\n"
        "        return compute(x)\n"
        "    except Exception:\n"
        "        cleanup()\n"
        "        return None\n"
    )

    def _shrink_pair(self, head_src: str, base_src: str, baseline: dict):
        """Run the explainer with a BASE TREE beside the head tree."""
        with tempfile.TemporaryDirectory() as tmp:
            head, base = Path(tmp).resolve() / "head", Path(tmp).resolve() / "base"
            head.mkdir()
            base.mkdir()
            (head / "mod.py").write_text(head_src)
            (base / "mod.py").write_text(base_src)
            original = esv.REPO_ROOT
            esv.REPO_ROOT = head
            try:
                return esv.explain_shrink(baseline, [str(head)], base_root=base)
            finally:
                esv.REPO_ROOT = original

    def test_deleting_the_logging_call_is_reported_as_a_silent_swallow(self):
        """#586's failure mode one door along.

        The detector deliberately skips a handler that logs nothing -- a silent
        swallow is a different and worse bug class, and reporting it there would bury
        this one. That exemption made DELETING the log an accepted "fix": the entry
        leaves the baseline, every gate goes green, and the code is now worse than the
        swallow that was recorded.
        """
        reported = self._shrink_pair(self.SILENCED, self.LOGGED, {"mod.py::f": 1})
        self.assertEqual([(u.reason, u.lineno) for u in reported], [("silent", 4)])

    def test_a_PRE_EXISTING_silent_sibling_is_not_reported(self):
        """The false alarm the first draft of the silent arm produced.

        `_shrink_causes` sees every handler in the function, not only ones that were
        counted -- so a function that has ALWAYS had a never-logging falsy handler had
        it reported as `silent` the moment any sibling was fixed, under a message
        asserting a deletion that never happened. Measured: 2 of 443 baselined
        functions carry such a sibling, and the report fired on the CORRECT fix.

        The base tree is what distinguishes them, and it is why `base_root` is
        required rather than optional.
        """
        both = (
            "def f(x):\n"
            "    try:\n"
            "        return compute(x)\n"
            "    except Exception:\n"
            "        cleanup()\n"          # silent in BOTH trees
            "        return None\n"
            "    try:\n"
            "        return compute(x)\n"
            "    except Exception:\n"
            "        frappe.log_error('two')\n"
            "        raise\n"              # head: this one was properly FIXED
        )
        base = both.replace("        raise\n", "        return None\n")
        self.assertEqual(self._shrink_pair(both, base, {"mod.py::f": 2}), [])

    def test_a_function_with_no_real_return_is_exempt_from_the_explainer(self):
        """Condition (5) again: a falsy return nobody can branch on is not a swallow.

        Reached through the `silent` arm -- via `unrecognised` the guard is unreachable,
        because an unrecognised return is itself a real one.
        """
        allfalsy = (
            "def f(x):\n"
            "    try:\n"
            "        return None\n"
            "    except Exception:\n"
            "        cleanup()\n"
            "        return None\n"
        )
        self.assertEqual(
            self._shrink_pair(allfalsy, allfalsy.replace("cleanup()", "frappe.log_error('b')"),
                              {"mod.py::f": 1}),
            [],
        )

    def test_only_the_NEWLY_silent_handler_is_reported(self):
        """A mixed shrink: one swallow properly fixed, one silenced, two always silent.

        Reporting by POSITION gets the count right and the handler wrong. The
        always-silent handlers deliberately sit FIRST and LAST in source order, so
        neither end of a positional slice can land on the right one by luck --
        `_own_nodes` walks a stack it pops from the end, so "first" is not the order a
        reader would guess. The match is on the handler's exception type and its
        returns, which do not move when the lines above them do.
        """
        head = (
            "def f(x):\n"
            "    try:\n"                       # 2
            "        return compute(x)\n"
            "    except Exception:\n"          # 4  always silent
            "        cleanup()\n"
            "        return ()\n"
            "    try:\n"                       # 7
            "        return compute(x)\n"
            "    except Exception:\n"          # 9  log DELETED in head
            "        cleanup()\n"
            "        return False\n"
            "    try:\n"                       # 12
            "        return compute(x)\n"
            "    except Exception:\n"          # 14 always silent
            "        cleanup()\n"
            "        return None\n"
            "    try:\n"                       # 17
            "        return compute(x)\n"
            "    except Exception:\n"          # 19 properly FIXED in head
            "        frappe.log_error('d')\n"
            "        raise\n"
        )
        base = head.replace(
            "        cleanup()\n        return False\n",
            "        frappe.log_error('b')\n        return False\n",
        ).replace("        raise\n", "        return {}\n")
        reported = self._shrink_pair(head, base, {"mod.py::f": 2})
        self.assertEqual([(u.reason, u.lineno) for u in reported], [("silent", 9)])

    def test_without_a_base_tree_the_silent_arm_does_not_accuse(self):
        """No base tree means the two cases above are indistinguishable.

        Refusing to report beats reporting a reason that may be false.
        """
        self.assertEqual(self._shrink_src(self.SILENCED, {"mod.py::f": 1}), [])

    def test_a_still_logging_falsy_handler_is_not_a_shrink_cause(self):
        """The control for the test above: still recognised AND still logging.

        Such a handler is still being counted, so it cannot be why an entry left.
        Reporting it would fire on every partial shrink.
        """
        self.assertEqual(
            self._shrink_src(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception:\n"
                "        frappe.log_error('boom')\n"
                "        return None\n",
                {"mod.py::f": 2},
            ),
            [],
        )

    def test_a_mid_function_handler_that_neither_logs_nor_returns_is_not_reported(self):
        """Falling off a handler in the MIDDLE of a function resumes it.

        Nothing falsy reaches the caller, so this was never a swallow -- and without
        the trailing-`try` guard it would be reported as a silent one.
        """
        self.assertEqual(
            self._shrink_src(
                "def f(x):\n"
                "    try:\n"
                "        prepare(x)\n"
                "    except Exception:\n"
                "        cleanup()\n"
                "    return compute(x)\n",
                {"mod.py::f": 1},
            ),
            [],
        )

    def test_a_file_leaving_the_SCAN_is_reported_as_unscanned(self):
        """The entry left because the walk stopped visiting the file (#586 H2).

        Narrowing SCAN_ROOTS, or adding a directory to `_iter_py`'s exclusions, drops
        every baselined entry beneath it while the handler is untouched. Measured on
        the real tree: excluding `templates/` drops 10 entries and dropping the
        `scripts` root drops 33, and before this both reported ZERO.
        """
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp).resolve()
            (d / "mod.py").write_text(
                "def f(x):\n"
                "    try:\n"
                "        return compute(x)\n"
                "    except Exception:\n"
                "        frappe.log_error('boom')\n"
                "        return None\n"
            )
            original_root, original_iter = esv.REPO_ROOT, esv._iter_py
            esv.REPO_ROOT = d
            esv._iter_py = lambda paths: iter(())  # the file stops being visited
            try:
                reported = esv.explain_shrink({"mod.py::f": 1}, [str(d)])
            finally:
                esv.REPO_ROOT, esv._iter_py = original_root, original_iter
        self.assertEqual([(u.reason, u.lineno) for u in reported], [("unscanned", 4)])


class AssignSwallowTest(unittest.TestCase):
    """Condition (4)'s ASSIGN arm (#601): a handler that assigns a falsy value
    instead of returning it is the same swallow, invisible to every arm above --
    all of which are reached only from an `ast.Return` node.

    The real defect this closes: `chapter_dashboard.get_chapter_key_metrics` zeroed
    `member_stats` into a variable, sitting directly above `get_basic_expense_stats`,
    whose byte-identical zero dict WAS caught because it returned it (#593). Only one
    of the two was ever findable before this arm.
    """

    def test_the_601_shape_is_flagged(self):
        """The real defect, reconstructed: a local variable zeroed on failure and
        later folded into the function's real return value.

        Confirmed as the RED case against the PRE-#601 validator (git HEAD before
        this change): scanning this exact shape found only `get_basic_expense_stats`
        -- `get_chapter_key_metrics` was invisible. This test is the GREEN half.
        """
        self.assertEqual(
            len(
                _flagged(
                    "def get_chapter_key_metrics(chapter_name):\n"
                    "    try:\n"
                    "        members = compute(chapter_name)\n"
                    "        member_stats = {'total_members': len(members), 'active_members': 3}\n"
                    "    except Exception as e:\n"
                    "        frappe.log_error(f'boom: {e}')\n"
                    "        member_stats = {'total_members': 0, 'active_members': 0}\n"
                    "\n"
                    "    expense_stats = get_basic_expense_stats(chapter_name)\n"
                    "    return {'members': member_stats, 'expenses': expense_stats}\n"
                )
            ),
            1,
        )

    def test_empty_list_assign_is_flagged(self):
        """The other container shape the census found: `= []`, not just `= {...}`."""
        self.assertEqual(
            len(
                _flagged(
                    "def f(x):\n"
                    "    try:\n"
                    "        recent_members = compute(x)\n"
                    "    except Exception:\n"
                    "        frappe.log_error('boom')\n"
                    "        recent_members = []\n"
                    "    return {'recent_members': recent_members}\n"
                )
            ),
            1,
        )

    def test_the_volunteer_dashboard_shape_stays_clean_unmarked(self):
        """The control (#601's whole point): a handler that ALSO sets an error flag
        beside the falsy assign is a legitimate degrade, not a swallow, and must
        NOT be flagged -- with no `# swallow-ok:` marker needed.

        This is `volunteer/dashboard.py:66` verbatim in shape: `context.data_warning`
        is what lets the template tell "no expenses" from "the query blew up".
        """
        self.assertEqual(
            _flagged(
                "def get_context(context):\n"
                "    try:\n"
                "        context.expense_summary = compute(context)\n"
                "    except Exception as e:\n"
                "        frappe.log_error(f'boom: {e}')\n"
                "        context.expense_summary = {'total_submitted': 0, 'pending_count': 0}\n"
                "        context.data_warning = _('Some data could not be loaded.')\n"
                "    return context\n"
            ),
            [],
        )

    def test_a_falsy_scalar_assign_is_flagged_too(self):
        """The heuristic is not restricted to containers: a lone falsy scalar
        assign that sets nothing else is the same shape, one step smaller
        (`stats['recent_count'] = 0`-style sites the census also found).
        """
        self.assertEqual(
            len(
                _flagged(
                    "def f(x):\n"
                    "    stats = compute_base(x)\n"
                    "    try:\n"
                    "        stats['recent_count'] = compute_recent(x)\n"
                    "    except Exception:\n"
                    "        frappe.log_error('boom')\n"
                    "        stats['recent_count'] = 0\n"
                    "    return stats\n"
                )
            ),
            1,
        )

    def test_an_assign_carrying_the_cause_is_not_flagged(self):
        """The same escape as the return arm: a non-falsy value anywhere among the
        handler's assigns means the caller CAN learn something, so nothing is
        flagged -- not just the falsy assign beside it.
        """
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        result = compute(x)\n"
                "    except Exception as e:\n"
                "        frappe.log_error('boom')\n"
                "        result = {'total': 0}\n"
                "        result_error = str(e)\n"
                "    return {'result': result}\n"
            ),
            [],
        )

    def test_an_assign_only_handler_still_needs_a_real_return_elsewhere(self):
        """Condition (5): a function that never returns anything meaningful cannot
        have a load-bearing assign-swallow either -- fire-and-forget work stays
        unflagged the same way it does for the return arm.
        """
        self.assertEqual(
            _flagged(
                "def invalidate(x):\n"
                "    try:\n"
                "        cache[x] = compute(x)\n"
                "    except Exception:\n"
                "        frappe.log_error('boom')\n"
                "        cache[x] = None\n"
            ),
            [],
        )

    def test_an_assign_only_handler_still_needs_the_structural_disqualifiers(self):
        """Conditions (1)-(3) apply to the assign arm exactly as they do to returns:
        a `continue` here means nothing falsy actually reaches the caller."""
        self.assertEqual(
            _flagged(
                "def f(rows):\n"
                "    out = []\n"
                "    for r in rows:\n"
                "        stats = {}\n"
                "        try:\n"
                "            stats = compute(r)\n"
                "        except Exception:\n"
                "            frappe.log_error('boom')\n"
                "            stats = {}\n"
                "            continue\n"
                "        out.append(stats)\n"
                "    return out\n"
            ),
            [],
        )

    def test_an_assign_only_handler_with_no_logging_is_not_flagged(self):
        """Out of scope for the DETECTOR (silent swallow is a different bug class),
        same as the return arm -- but see `AssignShrinkExplanationTest` for why the
        shrink explainer must still see it."""
        self.assertEqual(
            _flagged(
                "def f(x):\n"
                "    try:\n"
                "        stats = compute(x)\n"
                "    except Exception:\n"
                "        stats = {}\n"
                "    return stats\n"
            ),
            [],
        )

    def test_a_pragma_suppresses_an_assign_swallow(self):
        findings, bad = _scan(
            "def f(x):\n"
            "    try:\n"
            "        stats = compute(x)\n"
            "    except Exception:  # swallow-ok: best-effort\n"
            "        frappe.log_error('boom')\n"
            "        stats = {}\n"
            "    return stats\n"
        )
        self.assertEqual(findings, [])
        self.assertEqual(bad, [])

    def test_a_lone_false_flag_is_flagged_not_exempted(self):
        """The 'set a failure flag' idiom (`all_valid = False`, `released =
        False`) is 11 of the 35 sites this arm found tree-wide, and is left
        flagged ON PURPOSE (skeptical review). A falsy BOOLEAN is exactly as
        capable of being the caller's real signal as a falsy dict is of being a
        legitimate empty result -- this syntactic test cannot tell "the flag
        correctly says it failed" from "the flag is false because the check that
        would have set it never ran", and exempting the shape by name would also
        exempt a genuine swallow wearing it.
        """
        self.assertEqual(
            len(
                _flagged(
                    "def f(x):\n"
                    "    try:\n"
                    "        released = try_release(x)\n"
                    "    except Exception:\n"
                    "        frappe.log_error('boom')\n"
                    "        released = False\n"
                    "    return {'released': released}\n"
                )
            ),
            1,
        )


class AssignShrinkExplanationTest(unittest.TestCase):
    """The shrink explainer must stay in step with the assign arm (#601), the same
    'must not carry two copies of the ladder' hazard the module docstring already
    names for the return arm.
    """

    def _shrink(self, src: str, baseline: dict, base_root=None):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp).resolve() / "head"
            d.mkdir()
            (d / "mod.py").write_text(src)
            original = esv.REPO_ROOT
            esv.REPO_ROOT = d
            try:
                return esv.explain_shrink(baseline, [str(d)], base_root=base_root)
            finally:
                esv.REPO_ROOT = original

    def test_a_real_fix_explains_the_shrink(self):
        """The assign now carries the cause: a real fix, reported as one."""
        self.assertEqual(
            self._shrink(
                "def f(x):\n"
                "    try:\n"
                "        stats = compute(x)\n"
                "    except Exception as e:\n"
                "        frappe.log_error('boom')\n"
                "        stats = {'total': 0, 'error': str(e)}\n"
                "    return stats\n",
                {"mod.py::f": 1},
            ),
            [],
        )

    def test_an_unrecognised_assign_shape_is_reported(self):
        """The assign-side version of the #585 enum-member evasion: `stats =
        State.NOT_FOUND` still swallows, but `_is_falsy_value` does not recognise an
        `ast.Attribute` as falsy, so this must be reported rather than accepted
        silently."""
        unexplained = self._shrink(
            "def f(x):\n"
            "    try:\n"
            "        stats = compute(x)\n"
            "    except Exception:\n"
            "        frappe.log_error('boom')\n"
            "        stats = State.NOT_FOUND\n"
            "    return stats\n",
            {"mod.py::f": 1},
        )
        self.assertEqual([u.reason for u in unexplained], ["unrecognised"])

    def test_deleting_the_logging_call_on_an_assign_swallow_is_reported_as_silent(self):
        """#586's failure mode, on the assign arm: deleting the log takes the entry
        out of the baseline while making the code worse, and needs a base tree to
        tell that apart from a pre-existing silent sibling."""
        head = (
            "def f(x):\n"
            "    try:\n"
            "        stats = compute(x)\n"
            "    except Exception:\n"
            "        stats = {}\n"
            "    return stats\n"
        )
        base = head.replace("        stats = {}\n", "        frappe.log_error('boom')\n        stats = {}\n")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            headdir, basedir = root / "head", root / "base"
            headdir.mkdir()
            basedir.mkdir()
            (headdir / "mod.py").write_text(head)
            (basedir / "mod.py").write_text(base)
            original = esv.REPO_ROOT
            esv.REPO_ROOT = headdir
            try:
                reported = esv.explain_shrink({"mod.py::f": 1}, [str(headdir)], base_root=basedir)
            finally:
                esv.REPO_ROOT = original
        self.assertEqual([(u.reason, u.lineno) for u in reported], [("silent", 4)])

    def test_a_deleted_function_explains_an_assign_shrink(self):
        self.assertEqual(self._shrink("def g(x):\n    return x\n", {"mod.py::f": 1}), [])

    def test_a_legitimate_sibling_is_not_accused_when_another_handler_is_fixed(self):
        """Skeptical review C1: `_shrink_causes` iterates EVERY handler in the
        function, not only the one that dropped out of the count. A handler with
        TWO own-scope assigns -- one falsy, one an informative flag -- was NEVER
        counted by `_falsy_only_assigns` (which requires ALL assigns falsy). It
        must not become "unrecognised" collateral damage the moment a sibling
        handler in the SAME function is legitimately fixed and the function's
        total count drops.

        This is `volunteer/dashboard.py`'s exact shape, verbatim: `expense_summary`
        zeroed beside `data_warning` set, neither line touched, while `result` two
        handlers below is fixed to carry the cause.
        """
        self.assertEqual(
            self._shrink(
                "def get_context(context):\n"
                "    try:\n"
                "        context.expense_summary = compute(context)\n"
                "    except Exception as e:\n"
                "        frappe.log_error(f'boom: {e}')\n"
                "        context.expense_summary = {'total': 0}\n"
                "        context.data_warning = _('Some data could not be loaded.')\n"
                "\n"
                "    try:\n"
                "        result = compute2(context)\n"
                "    except Exception as e:\n"
                "        frappe.log_error(f'boom2: {e}')\n"
                "        result = {'ok': False, 'error': str(e)}\n"
                "\n"
                "    return context\n",
                {"mod.py::get_context": 2},
            ),
            [],
        )

    def test_a_lone_assign_evasion_is_still_reported_beside_a_fixed_sibling(self):
        """The control for the test above: a handler with exactly ONE own-scope
        assign that changed shape WITHOUT carrying the cause is still a plausible
        descendant of a counted swallow, and must still be reported."""
        unexplained = self._shrink(
            "def f(x):\n"
            "    try:\n"
            "        stats = compute(x)\n"
            "    except Exception:\n"
            "        frappe.log_error('boom')\n"
            "        stats = State.NOT_FOUND\n"
            "\n"
            "    try:\n"
            "        result = compute2(x)\n"
            "    except Exception as e:\n"
            "        frappe.log_error('boom2')\n"
            "        result = {'ok': False, 'error': str(e)}\n"
            "\n"
            "    return {'stats': stats, 'result': result}\n",
            {"mod.py::f": 2},
        )
        self.assertEqual([(u.reason, u.lineno) for u in unexplained], [("unrecognised", 4)])


class HandlerFingerprintTest(unittest.TestCase):
    """`_handler_fingerprint` must identify a handler by what it hands back, not
    by the source text of the assignment (skeptical review C2).
    """

    def test_two_assign_only_handlers_in_one_function_get_different_fingerprints(self):
        """The collision `_handler_fingerprint`'s assigns segment was added to
        prevent: two DIFFERENT assign-only handlers in the same function must not
        share a fingerprint, or the base-tree comparison in `_silent_census`
        cannot tell them apart."""
        src = (
            "def f(x):\n"
            "    try:\n"
            "        a = compute(x)\n"
            "    except Exception:\n"
            "        a = {}\n"
            "\n"
            "    try:\n"
            "        b = compute2(x)\n"
            "    except Exception:\n"
            "        b = []\n"
        )
        tree = ast.parse(src)
        handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
        self.assertEqual(len(handlers), 2)
        fingerprints = {esv._handler_fingerprint(h) for h in handlers}
        self.assertEqual(len(fingerprints), 2)

    def test_renaming_the_assigned_target_does_not_change_the_fingerprint(self):
        """A pure variable rename is not a behavioural change: fingerprinting the
        whole statement (target included) made this read as a brand-new
        fingerprint, so a rename anywhere in the function could make a
        PRE-EXISTING silent sibling look newly silent."""
        before = ast.parse(
            "def f(x):\n"
            "    try:\n"
            "        b = compute(x)\n"
            "    except Exception:\n"
            "        b = []\n"
        )
        after = ast.parse(
            "def f(x):\n"
            "    try:\n"
            "        rows = compute(x)\n"
            "    except Exception:\n"
            "        rows = []\n"
        )
        h1 = next(n for n in ast.walk(before) if isinstance(n, ast.ExceptHandler))
        h2 = next(n for n in ast.walk(after) if isinstance(n, ast.ExceptHandler))
        self.assertEqual(esv._handler_fingerprint(h1), esv._handler_fingerprint(h2))

    def test_renaming_elsewhere_does_not_make_a_silent_sibling_look_new(self):
        """The end-to-end regression this was actually caught by: a rename in ONE
        handler must not make an UNRELATED, always-silent sibling handler in the
        same function get reported as newly silent."""
        base = (
            "def f(x):\n"
            "    try:\n"
            "        a = compute(x)\n"
            "    except Exception:\n"
            "        b = []\n"
            "\n"
            "    try:\n"
            "        c = compute2(x)\n"
            "    except Exception as e:\n"
            "        frappe.log_error('boom')\n"
            "        c = {'x': 0}\n"
            "\n"
            "    return {'a': a, 'c': c}\n"
        )
        head = base.replace("        b = []\n", "        rows = []\n").replace(
            "        c = {'x': 0}\n", "        c = {'ok': False, 'error': str(e)}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            headdir, basedir = root / "head", root / "base"
            headdir.mkdir()
            basedir.mkdir()
            (headdir / "mod.py").write_text(head)
            (basedir / "mod.py").write_text(base)
            original = esv.REPO_ROOT
            esv.REPO_ROOT = headdir
            try:
                reported = esv.explain_shrink({"mod.py::f": 2}, [str(headdir)], base_root=basedir)
            finally:
                esv.REPO_ROOT = original
        self.assertEqual(reported, [])


if __name__ == "__main__":
    unittest.main()
