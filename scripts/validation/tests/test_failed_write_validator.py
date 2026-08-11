#!/usr/bin/env python3
"""Unit tests for scripts/validation/failed_write_validator.py.

Pure-Python (no bench/site needed): each case is a source snippet written to a temp
file and run through scan_file(). Run with:  python -m pytest this_file.py
or plain:  python scripts/validation/tests/test_failed_write_validator.py
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "failed_write_validator.py"
_spec = importlib.util.spec_from_file_location("failed_write_validator", _MOD_PATH)
fwv = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = fwv
_spec.loader.exec_module(fwv)


def _scan(src: str):
    """Return (findings, bad_pragmas) for a snippet."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "snippet.py"
        p.write_text(src)
        return fwv.scan_file(p)


def _flagged(src: str) -> list:
    return _scan(src)[0]


def _outcomes(src: str) -> list:
    return [f[2] for f in _flagged(src)]


class WriteDetectionTest(unittest.TestCase):
    """(1) the try body must actually persist something."""

    def test_insert_is_a_write(self):
        self.assertEqual(
            _outcomes(
                "def f(rows):\n"
                "    for r in rows:\n"
                "        try:\n"
                "            frappe.get_doc(r).insert()\n"
                "        except Exception as e:\n"
                "            frappe.log_error(str(e))\n"
                "    return done()\n"
            ),
            ["FALLS_THROUGH"],
        )

    def test_read_only_try_is_not_flagged(self):
        """A failed SELECT loses no row; that is the sibling validator's problem."""
        self.assertEqual(
            _flagged(
                "def f(name):\n"
                "    try:\n"
                "        doc = frappe.get_doc('Member', name)\n"
                "    except Exception as e:\n"
                "        frappe.log_error(str(e))\n"
                "    return summarize()\n"
            ),
            [],
        )

    def test_select_sql_is_not_a_write(self):
        self.assertEqual(
            _flagged(
                "def f(name):\n"
                "    try:\n"
                "        frappe.db.sql('SELECT name FROM tabMember')\n"
                "    except Exception as e:\n"
                "        frappe.log_error(str(e))\n"
                "    return summarize()\n"
            ),
            [],
        )

    def test_update_sql_is_a_write(self):
        self.assertEqual(
            _outcomes(
                "def f(name):\n"
                "    try:\n"
                "        frappe.db.sql('UPDATE tabMember SET x=1')\n"
                "    except Exception as e:\n"
                "        frappe.log_error(str(e))\n"
                "    return summarize()\n"
            ),
            ["FALLS_THROUGH"],
        )

    def test_redis_delete_is_not_a_write(self):
        """`cache.delete(lock_key)` releases a lock; it loses no row.

        Two of the prototype's 139 findings were exactly this (a Redis lock
        release in sepa_duplicate_prevention and invoice_generation_orchestrator).
        """
        self.assertEqual(
            _flagged(
                "def release(self, key):\n"
                "    try:\n"
                "        cache.delete(key)\n"
                "    except Exception as e:\n"
                "        frappe.log_error(str(e))\n"
                "    return self.state\n"
            ),
            [],
        )


class OutcomeClassTest(unittest.TestCase):
    """(5) how the handler exits decides the class -- and whether it is reported."""

    def test_claims_success_after_failed_save(self):
        """The worst case: the caller is told in so many words that it worked."""
        self.assertEqual(
            _outcomes(
                "def f(doc):\n"
                "    try:\n"
                "        doc.save()\n"
                "    except Exception as e:\n"
                "        frappe.log_error(str(e))\n"
                "        return {'success': True}\n"
                "    return {'success': True}\n"
            ),
            ["CLAIMS_SUCCESS"],
        )

    def test_loop_continue_after_failed_save(self):
        """The dropped ROW is the bug. error_swallow_validator skips this shape."""
        self.assertEqual(
            _outcomes(
                "def f(rows):\n"
                "    n = 0\n"
                "    for r in rows:\n"
                "        try:\n"
                "            r.save()\n"
                "            n += 1\n"
                "        except Exception as e:\n"
                "            frappe.log_error(str(e))\n"
                "            continue\n"
                "    return {'migrated': n}\n"
            ),
            ["LOOP_CONTINUES"],
        )

    def test_break_out_of_a_retry_loop_is_not_flagged(self):
        """`break` abandons the loop and lands in the post-loop failure path.

        SEPADistributedLock._acquire_lock_internal breaks out of its retry loop
        straight into "Failed to acquire lock" -- flagging it is noise.
        """
        self.assertEqual(
            _flagged(
                "def acquire(self, resource):\n"
                "    for attempt in range(3):\n"
                "        try:\n"
                "            frappe.db.sql('INSERT INTO tabLock VALUES (1)')\n"
                "        except Exception as e:\n"
                "            frappe.logger().error(str(e))\n"
                "            break\n"
                "    return self._fail(resource)\n"
            ),
            [],
        )

    def test_falls_through_mid_function(self):
        """Execution resumes as if the write had happened."""
        self.assertEqual(
            _outcomes(
                "def f(doc):\n"
                "    try:\n"
                "        doc.insert()\n"
                "    except Exception as e:\n"
                "        frappe.log_error(str(e))\n"
                "    notify(doc)\n"
                "    return doc.name\n"
            ),
            ["FALLS_THROUGH"],
        )

    def test_falsy_return_is_left_to_the_sibling_validator(self):
        """error_swallow_validator owns this shape; reporting it twice is noise."""
        self.assertEqual(
            _flagged(
                "def f(doc):\n"
                "    try:\n"
                "        doc.insert()\n"
                "        return doc.name\n"
                "    except Exception as e:\n"
                "        frappe.log_error(str(e))\n"
                "        return None\n"
            ),
            [],
        )

    def test_trailing_handler_with_no_return_is_left_to_the_sibling(self):
        """Falling off the tail handler is an implicit `return None` -- its turf."""
        self.assertEqual(
            _flagged(
                "def f(doc):\n"
                "    try:\n"
                "        doc.insert()\n"
                "        return doc.name\n"
                "    except Exception as e:\n"
                "        frappe.log_error(str(e))\n"
            ),
            [],
        )


class ErrorReportCalibrationTest(unittest.TestCase):
    """Calibration (a): a truthy value that REPORTS the failure is not a swallow.

    Counting these collapsed the useful signal -- 239 sites became 19 once they
    were excluded.
    """

    def test_success_false_dict_is_not_flagged(self):
        self.assertEqual(
            _flagged(
                "def f(doc):\n"
                "    try:\n"
                "        doc.insert()\n"
                "        return {'success': True}\n"
                "    except Exception as e:\n"
                "        frappe.log_error(str(e))\n"
                "        return {'success': False, 'error': str(e)}\n"
            ),
            [],
        )

    def test_operation_result_fail_is_not_flagged(self):
        self.assertEqual(
            _flagged(
                "def f(doc):\n"
                "    try:\n"
                "        doc.insert()\n"
                "        return OperationResult(success=True)\n"
                "    except Exception as e:\n"
                "        frappe.log_error(str(e))\n"
                "        return OperationResult(success=False, errors=[str(e)])\n"
            ),
            [],
        )

    def test_action_error_dict_is_not_flagged(self):
        """`return {'action': 'error', ...}` -- sepa_batch_notifications' shape."""
        self.assertEqual(
            _flagged(
                "def f(batch):\n"
                "    try:\n"
                "        batch.save()\n"
                "        return {'action': 'processed'}\n"
                "    except Exception as e:\n"
                "        frappe.log_error(str(e))\n"
                "        return {'action': 'error', 'requires_intervention': True}\n"
            ),
            [],
        )

    def test_false_error_tuple_is_not_flagged(self):
        """`return False, error_msg` -- AccountCreationService's (ok, error) tuple."""
        self.assertEqual(
            _flagged(
                "def f(self, member):\n"
                "    try:\n"
                "        frappe.db.set_value('Member', member.name, 'user', 'u')\n"
                "        return True, None\n"
                "    except Exception as e:\n"
                "        self.logger.error(str(e))\n"
                "        return False, 'Failed to link user'\n"
            ),
            [],
        )

    def test_unrelated_truthy_return_is_flagged(self):
        """A fallback value the caller cannot distinguish from the real thing.

        MemberIDManager.get_next_member_id returns a timestamp-derived id after the
        counter UPDATE failed -- the counter never advanced and nobody is told.
        """
        self.assertEqual(
            _outcomes(
                "def next_id():\n"
                "    try:\n"
                "        frappe.db.sql('UPDATE tabSingles SET value = 1')\n"
                "        return real_id\n"
                "    except Exception as e:\n"
                "        frappe.log_error(str(e))\n"
                "        return fallback_id()\n"
            ),
            ["RETURNS_TRUTHY"],
        )


class RecordsFailureCalibrationTest(unittest.TestCase):
    """Calibration (b): recording the failure for the caller is not a swallow.

    And calibration (c): it is checked FIRST, so a `return True` that MEANS
    "the save failed" is never misread as a success claim.
    """

    def test_appending_to_an_errors_list_is_not_flagged(self):
        self.assertEqual(
            _flagged(
                "def f(rows, results):\n"
                "    for r in rows:\n"
                "        try:\n"
                "            r.save()\n"
                "        except Exception as e:\n"
                "            frappe.log_error(str(e))\n"
                "            results['errors'].append(str(e))\n"
                "            continue\n"
                "    return results\n"
            ),
            [],
        )

    def test_flipping_a_success_flag_false_is_not_flagged(self):
        self.assertEqual(
            _flagged(
                "def f(rows, results):\n"
                "    for r in rows:\n"
                "        try:\n"
                "            r.save()\n"
                "        except Exception as e:\n"
                "            frappe.log_error(str(e))\n"
                "            results[r.name]['success'] = False\n"
                "    return results\n"
            ),
            [],
        )

    def test_return_true_meaning_failure_is_not_flagged(self):
        """_step_save_history_changes returns True to signal "the save failed".

        Calibration (c). It marks every result failed on the way out, so (b)
        clears it -- which only works because (b) is checked before any return
        value is read.
        """
        self.assertEqual(
            _flagged(
                "def _step_save_history_changes(self, member_doc, results):\n"
                "    try:\n"
                "        member_doc.save()\n"
                "        return False\n"
                "    except Exception as e:\n"
                "        log_operation_error('HIST_007', member_doc.name, e)\n"
                "        for key in results:\n"
                "            results[key]['success'] = False\n"
                "            results[key]['error'] = f'Save failed: {e}'\n"
                "        return True\n"
            ),
            [],
        )

    def test_error_counter_is_not_flagged(self):
        """`error_count += 1` in a batch loop IS the report the caller reads."""
        self.assertEqual(
            _flagged(
                "def f(rows):\n"
                "    error_count = 0\n"
                "    for r in rows:\n"
                "        try:\n"
                "            r.save()\n"
                "        except Exception as e:\n"
                "            error_count += 1\n"
                "            frappe.log_error(str(e))\n"
                "    return error_count\n"
            ),
            [],
        )

    def test_unrelated_bookkeeping_is_still_flagged(self):
        """The prototype's blanket "any attribute assign counts" hid real findings.

        `self.retry_count += 1` says nothing to the caller about the lost row.
        """
        self.assertEqual(
            _outcomes(
                "def f(self, doc):\n"
                "    try:\n"
                "        doc.insert()\n"
                "    except Exception as e:\n"
                "        self.retry_count += 1\n"
                "        frappe.log_error(str(e))\n"
                "    return doc.name\n"
            ),
            ["FALLS_THROUGH"],
        )


class PropagationTest(unittest.TestCase):
    """(3) a handler that propagates is not a swallow."""

    def test_reraise_is_not_flagged(self):
        self.assertEqual(
            _flagged(
                "def f(doc):\n"
                "    try:\n"
                "        doc.insert()\n"
                "    except Exception as e:\n"
                "        frappe.log_error(str(e))\n"
                "        raise\n"
                "    return doc.name\n"
            ),
            [],
        )

    def test_frappe_throw_is_not_flagged(self):
        self.assertEqual(
            _flagged(
                "def f(doc):\n"
                "    try:\n"
                "        doc.insert()\n"
                "    except Exception as e:\n"
                "        frappe.throw(_('Could not save: {0}').format(e))\n"
                "    return doc.name\n"
            ),
            [],
        )

    def test_narrow_except_is_not_flagged(self):
        self.assertEqual(
            _flagged(
                "def f(doc):\n"
                "    try:\n"
                "        doc.insert()\n"
                "    except frappe.DuplicateEntryError as e:\n"
                "        frappe.log_error(str(e))\n"
                "    return doc.name\n"
            ),
            [],
        )


class SilentHandlerTest(unittest.TestCase):
    """Unlike the sibling rule, a handler that logs NOTHING is still reported.

    The sibling excludes silent handlers to keep its own message focused. Here the
    write is gone either way, and a `pass` over a lost row is strictly worse than
    a logged one.
    """

    def test_bare_pass_handler_is_flagged(self):
        self.assertEqual(
            _outcomes(
                "def f(doc):\n"
                "    try:\n"
                "        doc.insert()\n"
                "    except Exception:\n"
                "        pass\n"
                "    return doc.name\n"
            ),
            ["FALLS_THROUGH"],
        )


class NestedScopeTest(unittest.TestCase):
    def test_a_handler_in_a_nested_def_is_reported_once(self):
        """_qualnames yields the inner function separately.

        If _own_nodes descended into it as well, the same handler would be counted
        twice — and the baseline would carry a phantom site under the outer name.
        """
        findings = _flagged(
            "def outer(doc):\n"
            "    def inner():\n"
            "        try:\n"
            "            doc.insert()\n"
            "        except Exception as e:\n"
            "            frappe.log_error(str(e))\n"
            "        return doc.name\n"
            "    return inner\n"
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0][0], "outer.inner")


class PragmaTest(unittest.TestCase):
    def test_valid_pragma_suppresses(self):
        findings, bad = _scan(
            "def f(doc):\n"
            "    try:\n"
            "        doc.insert()\n"
            "    except Exception as e:  # failed-write-ok: best-effort\n"
            "        frappe.log_error(str(e))\n"
            "    return doc.name\n"
        )
        self.assertEqual(findings, [])
        self.assertEqual(bad, [])

    def test_invalid_pragma_reason_is_reported(self):
        findings, bad = _scan(
            "def f(doc):\n"
            "    try:\n"
            "        doc.insert()\n"
            "    except Exception as e:  # failed-write-ok: because-i-said-so\n"
            "        frappe.log_error(str(e))\n"
            "    return doc.name\n"
        )
        self.assertEqual(findings, [])
        self.assertEqual(len(bad), 1)


class BaselineTest(unittest.TestCase):
    def test_baseline_parses_and_is_non_empty(self):
        loaded = fwv.load_baseline(fwv.DEFAULT_BASELINE)
        self.assertGreater(len(loaded), 0)
        self.assertTrue(all(isinstance(v, int) and v > 0 for v in loaded.values()))

    def test_repo_is_at_or_below_its_baseline(self):
        """The ratchet holds: nothing in the tree exceeds what is recorded."""
        counts, _outcomes_, _details, problems = fwv._counts(
            [str(fwv.REPO_ROOT / root) for root in fwv.SCAN_ROOTS]
        )
        baseline = fwv.load_baseline(fwv.DEFAULT_BASELINE)
        over = {k: v for k, v in counts.items() if v > baseline.get(k, 0)}
        self.assertEqual(over, {})
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
