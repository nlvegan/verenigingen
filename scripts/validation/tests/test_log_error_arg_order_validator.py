#!/usr/bin/env python3
"""Unit tests for scripts/validation/log_error_arg_order_validator.py.

Pure-Python (no bench/site needed): each case is a source snippet written to a temp
file and run through scan_file(). Run with:  python -m pytest this_file.py
or plain:  python scripts/validation/tests/test_log_error_arg_order_validator.py
"""
import importlib.util
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "log_error_arg_order_validator.py"
_spec = importlib.util.spec_from_file_location("log_error_arg_order_validator", _MOD_PATH)
lev = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = lev
_spec.loader.exec_module(lev)


def _scan(src: str):
    """Return (findings, bad_pragmas) for a snippet."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "snippet.py"
        p.write_text(src)
        return lev.scan_file(p)


def _flagged(src: str) -> list:
    return _scan(src)[0]


class PlantedViolationTest(unittest.TestCase):
    """The validator must reject the exact shape #602 describes."""

    def test_fstring_message_then_literal_title_is_flagged(self):
        """The flagship shape from the issue body itself."""
        findings = _flagged(
            "def process(tracker_name, e):\n"
            "    try:\n"
            "        pass\n"
            "    except Exception:\n"
            "        frappe.log_error(f'Error processing retry queue for "
            "{tracker_name}: {e}', 'Retry Queue Processing Error')\n"
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0][0], "process")

    def test_concatenation_message_then_literal_title_is_flagged(self):
        findings = _flagged(
            "def f(e):\n"
            "    try:\n"
            "        pass\n"
            "    except Exception:\n"
            "        frappe.log_error('Failed: ' + str(e), 'Batch Error')\n"
        )
        self.assertEqual(len(findings), 1)

    def test_str_call_message_then_literal_title_is_flagged(self):
        findings = _flagged(
            "def f(e):\n"
            "    try:\n"
            "        pass\n"
            "    except Exception as e:\n"
            "        frappe.log_error(str(e), 'Payment Error')\n"
        )
        self.assertEqual(len(findings), 1)

    def test_bare_name_call_is_flagged(self):
        """`log_error(...)` without the `frappe.` prefix is still matched by name."""
        findings = _flagged(
            "def f(e):\n"
            "    try:\n"
            "        pass\n"
            "    except Exception as e:\n"
            "        log_error(f'boom {e}', 'Title')\n"
        )
        self.assertEqual(len(findings), 1)

    def test_three_positional_args_on_frappe_log_error_is_flagged(self):
        """The real #602 site this shape exists for: sepa_memory_optimizer.py's
        `frappe.log_error(f"...", "SEPA Memory Alert", alert_data)` -- a third
        positional argument (reference_doctype in frappe's real signature) does
        not change that this is still title-and-message swapped."""
        findings = _flagged(
            "def f(alert_data):\n"
            "    frappe.log_error(f'High memory: {alert_data}', 'SEPA Memory Alert', alert_data)\n"
        )
        self.assertEqual(len(findings), 1)


class AcceptsCorrectCallTest(unittest.TestCase):
    """The validator must NOT flag calls already in the right order."""

    def test_literal_title_then_fstring_message_is_not_flagged(self):
        """The correct (title, message) order -- this must go quiet."""
        findings = _flagged(
            "def f(e):\n"
            "    try:\n"
            "        pass\n"
            "    except Exception as e:\n"
            "        frappe.log_error('Payment Error', f'Failed: {e}')\n"
        )
        self.assertEqual(findings, [])

    def test_keyword_call_is_not_flagged(self):
        """Already self-documenting -- explicit keywords can't be re-inverted."""
        findings = _flagged(
            "def f(e):\n"
            "    try:\n"
            "        pass\n"
            "    except Exception as e:\n"
            "        frappe.log_error(title='Payment Error', message=f'Failed: {e}')\n"
        )
        self.assertEqual(findings, [])

    def test_single_argument_call_is_not_flagged(self):
        findings = _flagged(
            "def f(e):\n"
            "    try:\n"
            "        pass\n"
            "    except Exception as e:\n"
            "        frappe.log_error(f'Failed: {e}')\n"
        )
        self.assertEqual(findings, [])

    def test_both_literal_strings_is_not_flagged(self):
        """Two plain literals give no static evidence of a swap either way."""
        findings = _flagged(
            "def f():\n"
            "    frappe.log_error('Some message', 'Some Title')\n"
        )
        self.assertEqual(findings, [])

    def test_bare_variable_first_argument_is_not_flagged(self):
        """A Name/Attribute gives no static shape evidence -- deliberately out of
        scope, to avoid guessing at `log_error(title_var, message_var)` calls that
        are already correct."""
        findings = _flagged(
            "def f(msg):\n"
            "    frappe.log_error(msg, 'Some Title')\n"
        )
        self.assertEqual(findings, [])

    def test_three_positional_args_on_local_method_is_not_flagged(self):
        """This repo has several same-named LOCAL methods with a genuinely
        different 3-argument convention -- log_error(message, record_type,
        record_data) -- that happen to produce the identical (message-shaped,
        literal) AST shape on 3 real sites (account_migration_service.py,
        e_boekhouden_migration.py). A 3rd positional argument is only trusted
        as a swap when the receiver unambiguously names frappe's own function;
        `self.log_error` (or any other non-`frappe.` receiver) is not."""
        findings = _flagged(
            "class Svc:\n"
            "    def f(self, e, data):\n"
            "        self.log_error(f'Failed: {e}', 'account', data)\n"
        )
        self.assertEqual(findings, [])

    def test_both_dynamic_arguments_is_not_flagged(self):
        """No literal-title shape on either side -- nothing to say which is which."""
        findings = _flagged(
            "def f(e):\n"
            "    frappe.log_error(f'context {e}', get_title())\n"
        )
        self.assertEqual(findings, [])

    def test_unrelated_dotted_call_named_log_error_is_matched_by_name(self):
        """Matched by NAME only (documented limit): a non-frappe receiver with the
        same method name and the swapped 2-arg shape is STILL flagged -- this is
        exactly the false-positive risk an author marks with the pragma (see
        SuppressionMarkerTest), not something the detector filters out on its own."""
        findings = _flagged(
            "def f(e):\n"
            "    tracker.log_error(f'boom {e}', 'Title')\n"
        )
        self.assertEqual(len(findings), 1)


class SuppressionMarkerTest(unittest.TestCase):
    def test_valid_reason_suppresses(self):
        findings, bad = _scan(
            "def f(e):\n"
            "    frappe.log_error(f'boom {e}', 'Title')  # log-error-args-ok: false-positive\n"
        )
        self.assertEqual(findings, [])
        self.assertEqual(bad, [])

    def test_invalid_reason_is_reported_but_still_suppressed(self):
        findings, bad = _scan(
            "def f(e):\n"
            "    frappe.log_error(f'boom {e}', 'Title')  # log-error-args-ok: because-reasons\n"
        )
        self.assertEqual(findings, [])
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0][1], "because-reasons")


class ModuleLevelAndNestingTest(unittest.TestCase):
    def test_module_level_call_is_flagged_once(self):
        findings = _flagged("frappe.log_error(f'boom {1}', 'Title')\n")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0][0], "<module>")

    def test_call_inside_method_is_attributed_to_the_method(self):
        findings = _flagged(
            "class Foo:\n"
            "    def bar(self, e):\n"
            "        frappe.log_error(f'boom {e}', 'Title')\n"
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0][0], "Foo.bar")

    def test_call_is_not_double_counted_between_function_and_module_scope(self):
        findings = _flagged(
            "def outer(e):\n"
            "    frappe.log_error(f'boom {e}', 'Title')\n"
            "\n"
            "frappe.log_error(f'boom {2}', 'Other Title')\n"
        )
        self.assertEqual(len(findings), 2)
        quals = sorted(q for q, _ in findings)
        self.assertEqual(quals, ["<module>", "outer"])


class RatchetTest(unittest.TestCase):
    """Exercises the ACTUAL comparison main() runs (`new_findings`), not a second
    copy of it -- a copy here would stay green even if `new_findings`'s `>`
    silently became `>=` and started reporting sites that never grew."""

    def test_counts_below_or_equal_baseline_are_not_new(self):
        counts = Counter({"a.py::f": 1})
        baseline = {"a.py::f": 1}
        self.assertEqual(lev.new_findings(counts, baseline), {})

    def test_counts_above_baseline_are_new(self):
        counts = Counter({"a.py::f": 2})
        baseline = {"a.py::f": 1}
        self.assertEqual(lev.new_findings(counts, baseline), {"a.py::f": 2})

    def test_key_absent_from_baseline_is_new(self):
        counts = Counter({"a.py::f": 1})
        self.assertEqual(lev.new_findings(counts, {}), {"a.py::f": 1})

    def test_load_and_write_baseline_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "baseline.txt"
            counts = Counter({"a.py::f": 2, "b.py::<module>": 1})
            lev.write_baseline(path, counts)
            loaded = lev.load_baseline(path)
            self.assertEqual(loaded, dict(counts))


class SweptDirectoriesAreCleanTest(unittest.TestCase):
    """The three directories #602 swept manually must have introduced zero new
    swapped sites -- this is the sweep's own correctness check, run as a test so
    a future edit to those directories cannot silently reintroduce the shape."""

    def test_no_swapped_calls_remain_in_swept_directories(self):
        repo_root = lev.REPO_ROOT
        swept = [
            repo_root / "verenigingen" / "verenigingen_payments" / "services",
            repo_root / "verenigingen" / "verenigingen_payments" / "mollie" / "services",
            repo_root / "verenigingen" / "e_boekhouden" / "utils",
        ]
        offenders = []
        for root in swept:
            self.assertTrue(root.exists(), f"swept directory moved or was deleted: {root}")
            for path in root.rglob("*.py"):
                findings, _ = lev.scan_file(path)
                for qualname, lineno in findings:
                    offenders.append(f"{path}:{lineno} {qualname}")
        self.assertEqual(offenders, [], f"new swapped log_error sites: {offenders}")


class ShrinkExplainerTest(unittest.TestCase):
    """explain_shrink() must catch a pragma hiding a baselined site -- the abuse
    that defeats the growth check, which only ever sees NEW sites appear."""

    def setUp(self):
        # A real file under REPO_ROOT, not tempfile.TemporaryDirectory(): explain_shrink
        # resolves baseline keys as REPO_ROOT / rel, so it has to be a real repo-relative
        # path to be found at all.
        self.probe_dir = lev.REPO_ROOT / "scripts" / "validation" / "tests" / "_shrink_probe"
        self.probe_dir.mkdir(exist_ok=True)
        self.probe_file = self.probe_dir / "probe_mod.py"
        self.rel = str(self.probe_file.relative_to(lev.REPO_ROOT))

    def tearDown(self):
        self.probe_file.unlink(missing_ok=True)
        self.probe_dir.rmdir()

    def _write(self, source: str):
        self.probe_file.write_text(source)

    def test_pragma_added_on_baselined_site_is_reported_as_suppressed(self):
        self._write("def f(e):\n    frappe.log_error(f'boom {e}', 'Title')  # log-error-args-ok: false-positive\n")
        baseline = {f"{self.rel}::f": 1}
        unexplained = lev.explain_shrink(baseline, [str(lev.REPO_ROOT / "scripts")])
        self.assertEqual(len(unexplained), 1)
        self.assertEqual(unexplained[0].reason, "suppressed")

    def test_genuine_fix_is_not_reported(self):
        self._write("def f(e):\n    frappe.log_error(title='Title', message=f'boom {e}')\n")
        baseline = {f"{self.rel}::f": 1}
        unexplained = lev.explain_shrink(baseline, [str(lev.REPO_ROOT / "scripts")])
        self.assertEqual(unexplained, [])

    def test_deleted_file_is_not_reported(self):
        baseline = {f"{self.rel}::f": 1}
        # File never written this test -- simulates deletion.
        unexplained = lev.explain_shrink(baseline, [str(lev.REPO_ROOT / "scripts")])
        self.assertEqual(unexplained, [])


class ScanFileAllTest(unittest.TestCase):
    """scan_file_all sees a suppressed site that scan_file excludes -- the whole
    reason it exists as a separate function for explain_shrink to use."""

    def test_suppressed_site_is_still_returned(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "snippet.py"
            p.write_text(
                "def f(e):\n"
                "    frappe.log_error(f'boom {e}', 'Title')  # log-error-args-ok: false-positive\n"
            )
            self.assertEqual(lev.scan_file(p)[0], [])  # ordinary scan: suppressed, invisible
            self.assertEqual(lev.scan_file_all(p), [("f", 2)])  # scan_file_all: still sees it


if __name__ == "__main__":
    unittest.main()
