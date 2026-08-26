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
        the same reason a non-empty dict has never been flagged.
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
    and `return None, None` sits TWO LINES ABOVE it as the legitimate "no transactions
    in range" answer. The caller cannot tell them apart, which is this bug class
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

    def test_deleting_the_logging_call_is_reported_as_a_silent_swallow(self):
        """#586's failure mode one door along.

        The detector deliberately skips a handler that logs nothing -- a silent
        swallow is a different and worse bug class, and reporting it there would bury
        this one. That exemption made DELETING the log an accepted "fix": the entry
        leaves the baseline, every gate goes green, and the code is now worse than the
        swallow that was recorded.
        """
        reported = self._shrink_src(
            "def f(x):\n"
            "    try:\n"
            "        return compute(x)\n"
            "    except Exception:\n"
            "        cleanup()\n"
            "        return None\n",
            {"mod.py::f": 1},
        )
        self.assertEqual([(u.reason, u.lineno) for u in reported], [("silent", 4)])

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


if __name__ == "__main__":
    unittest.main()
