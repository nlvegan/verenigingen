"""#1188: ``StatefulService.rollback_transaction`` must not mask the error it cleans up after.

A 1213 deadlock (and any nested commit) destroys the service's savepoint, so the bare
``frappe.db.rollback(save_point=...)`` in ``rollback_transaction`` raised 1305 out of the
caller's ``except`` block and replaced the real failure. ``bulk_operation`` additionally
swallowed a deadlock as "one bad batch" and carried on against a dead transaction.

Fault injection: the operation itself issues ``RELEASE SAVEPOINT`` on the service's own
real savepoint and then raises. That leaves exactly the server state a 1213 leaves (the
savepoint is gone, the driver raises a real 1305 on ROLLBACK TO) without a ROLLBACK that
would take the test's own fixtures with it. The deadlock itself is the real exception
class, as frappe raises it. The injection point is the operation callable, i.e. the layer
``execute_with_transaction`` / ``bulk_operation`` really wrap.
"""

import frappe

from verenigingen.services.infrastructure.base_service import DataService, StatefulService
from verenigingen.tests.support.non_resumable_errors import deadlock, lock_wait_timeout
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.service_error_handler import ServiceError
from verenigingen.utils.transaction_errors import DATABASE_ERROR


def _svc_1188(tag):
    return StatefulService(f"svc_1188_{tag}")


def _data_svc_1188(tag):
    # bulk_operation lives on DataService, not StatefulService.
    return DataService(f"svc_1188_{tag}")


def _destroy_savepoint_then_raise_1188(svc, error):
    """Leave what a 1213 leaves: no savepoint, and the error in flight."""
    frappe.db.sql(f"RELEASE SAVEPOINT {svc._savepoint_name}")
    raise error


class TestBaseServiceRollbackMasking1188(VereningingenTestCase):
    def test_a_deadlock_with_a_destroyed_savepoint_reaches_the_caller_as_a_deadlock(self):
        svc = _svc_1188("exec_deadlock")
        err = deadlock()

        def op():
            _destroy_savepoint_then_raise_1188(svc, err)

        with self.assertRaises(frappe.QueryDeadlockError) as ctx:
            svc.execute_with_transaction(op)
        self.assertIs(ctx.exception, err)
        self.assertFalse(svc._transaction_active)

    def test_an_ordinary_error_with_a_destroyed_savepoint_is_still_the_error_reported(self):
        self.expectErrorLog("svc_1188_exec_ordinary Error")
        svc = _svc_1188("exec_ordinary")
        boom = ValueError("the real failure")

        def op():
            _destroy_savepoint_then_raise_1188(svc, boom)

        with self.assertRaises(ServiceError) as ctx:
            svc.execute_with_transaction(op)
        self.assertIs(ctx.exception.original_error, boom)
        self.assertFalse(svc._transaction_active)

    def test_a_skipped_rollback_is_recorded_not_silently_swallowed(self):
        """Pins the difference from a bare ``except Exception: pass`` around the rollback.

        expectErrorLog only suppresses; this asserts the row exists. Error Log is MyISAM,
        so it is matched by the unique savepoint name in the message, not by count of
        the title alone.
        """
        self.expectErrorLog("svc_1188_skip_logged Error")
        svc = _svc_1188("skip_logged")
        seen = {}

        def op():
            seen["name"] = svc._savepoint_name
            _destroy_savepoint_then_raise_1188(svc, ValueError("boom"))

        with self.assertRaises(ServiceError):
            svc.execute_with_transaction(op)
        rows = frappe.get_all(
            "Error Log",
            filters={"method": "Savepoint rollback skipped", "error": ["like", f"%{seen['name']}%"]},
        )
        self.assertEqual(len(rows), 1)

    def test_a_rollback_failure_that_is_not_a_missing_savepoint_propagates(self):
        """Real driver error, no mock: an invalid savepoint name is a MariaDB 1064."""
        svc = _svc_1188("non_1305")

        def op():
            svc._savepoint_name = "not-a-valid-name"
            raise ValueError("original")

        with self.assertRaises(DATABASE_ERROR) as ctx:
            svc.execute_with_transaction(op)
        self.assertNotEqual(ctx.exception.args[0], 1305)

    def test_control_with_the_savepoint_intact_the_write_is_really_rolled_back(self):
        """Control: the fix must not turn rollback into a no-op."""
        self.expectErrorLog("svc_1188_exec_control Error")
        svc = _svc_1188("exec_control")
        description = f"svc-1188-{frappe.generate_hash(length=8)}"

        def op():
            frappe.get_doc({"doctype": "ToDo", "description": description}).insert()
            raise ValueError("fail after the write")

        with self.assertRaises(ServiceError):
            svc.execute_with_transaction(op)
        self.assertFalse(frappe.db.exists("ToDo", {"description": description}))

    def test_bulk_operation_survives_a_destroyed_savepoint_and_continues(self):
        self.expectErrorLog("Savepoint rollback skipped")
        svc = _data_svc_1188("bulk_ordinary")
        seen = []

        def op(item):
            seen.append(item)
            if item == "bad":
                _destroy_savepoint_then_raise_1188(svc, ValueError("bad item"))

        result = svc.bulk_operation(op, ["bad", "good"], batch_size=1)

        self.assertEqual(seen, ["bad", "good"], "the second batch still ran")
        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["processed"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("Batch 1 failed: bad item", result["errors"][0])
        self.assertFalse(svc._transaction_active)

    def test_bulk_operation_propagates_a_non_resumable_error_instead_of_swallowing_it(self):
        for name, make in (("deadlock", deadlock), ("lock_wait", lock_wait_timeout)):
            with self.subTest(fault=name):
                svc = _data_svc_1188(f"bulk_{name}")
                err = make()
                seen = []

                def op(item, svc=svc, err=err, seen=seen):
                    seen.append(item)
                    if item == "bad":
                        _destroy_savepoint_then_raise_1188(svc, err)

                with self.assertRaises(type(err)) as ctx:
                    svc.bulk_operation(op, ["bad", "never"], batch_size=1)
                self.assertIs(ctx.exception, err)
                self.assertEqual(seen, ["bad"], "no batch runs after the transaction is gone")
                self.assertFalse(svc._transaction_active)
