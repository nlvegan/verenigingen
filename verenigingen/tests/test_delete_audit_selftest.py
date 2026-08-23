"""Controls for the delete-resurrection auditor.

The auditor's whole claim is that it can tell a delete that stuck from one that was
undone. A run reporting zero survivors is worthless unless a planted resurrection reads
non-zero, so both directions are planted here.

**These tests strand rows on purpose and are skipped unless the recorder is active.**
`test_1` leaves a resurrected Territory behind and `test_4` leaves a recreated one,
because the checker runs in a separate process afterwards and can only see COMMITTED
state -- cleaning up here would leave nothing for it to read, and the control would pass
for the wrong reason. Left ungated, an ordinary CI shard containing this module would
strand two Territory rows every run and hand the leak ratchet a real leak.

`DELETE_AUDIT_LOG` is the gate because it is exactly the variable that turns the recorder
on: set, the run is a self-test and `selftest.sh` sweeps the rows afterwards; unset, these
controls have nothing to prove and are skipped.
"""

import os
import unittest

import frappe

# One copy of this fixture, not two -- the duplicate-helper guard is right that a second
# `_territory` is a copy-paste, and this module exists because three throwaway probes were
# not shared either.
from verenigingen.tests.test_harness_leak_attribution import _territory

AUDIT_LOG_ENV_VAR = "DELETE_AUDIT_LOG"


@unittest.skipUnless(
    os.environ.get(AUDIT_LOG_ENV_VAR),
    f"{AUDIT_LOG_ENV_VAR} is unset, so the recorder is off and these controls would only "
    "strand rows. Run them through scripts/testing/delete_audit/selftest.sh.",
)
class DeleteAuditControl(unittest.TestCase):
    def test_1_positive_a_delete_undone_by_rollback_must_be_reported(self):
        victim = _territory("zzaudit-positive")
        frappe.db.commit()
        frappe.delete_doc("Territory", victim.name, force=True, ignore_permissions=True)
        self.assertFalse(frappe.db.exists("Territory", victim.name))
        # The defect in one line: the delete is uncommitted, so the next rollback puts
        # the row back and the delete's own success report is a lie.
        frappe.db.rollback()
        self.assertTrue(frappe.db.exists("Territory", victim.name))
        print(f"CONTROL-POSITIVE Territory::{victim.name}")

    def test_2_negative_a_delete_that_stuck_must_not_be_reported(self):
        victim = _territory("zzaudit-negative")
        frappe.db.commit()
        frappe.delete_doc("Territory", victim.name, force=True, ignore_permissions=True)
        frappe.db.commit()
        self.assertFalse(frappe.db.exists("Territory", victim.name))
        print(f"CONTROL-NEGATIVE Territory::{victim.name}")

    def test_3_negative_an_already_gone_row_is_not_a_delete(self):
        """`delete_doc` returns False for a row that was already gone.

        Recording that as a delete would make every cleanup walking past a missing row
        look like a resurrection -- the auditor would drown in its own false positives.
        """
        victim = _territory("zzaudit-absent")
        frappe.db.commit()
        frappe.delete_doc("Territory", victim.name, force=True, ignore_permissions=True)
        frappe.db.commit()
        frappe.delete_doc("Territory", victim.name, force=True, ignore_permissions=True)
        print(f"CONTROL-ALREADY-GONE Territory::{victim.name}")

    def test_4_negative_a_fixture_recreated_on_a_fixed_name_is_not_a_resurrection(self):
        """The auditor's own false-positive mode, planted.

        Several fixtures here are get-or-create on a FIXED docname
        (`Test Amsterdam Chapter`). A later test recreating one looks exactly like a
        resurrection to anything that only remembers the name -- and that is what the
        first census run reported. It must come back RECREATED, not SURVIVED.
        """
        fixed = f"zzaudit-fixedname-{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Territory", "territory_name": fixed, "parent_territory": "All Territories"}
        ).insert()
        frappe.db.commit()
        frappe.delete_doc("Territory", fixed, force=True, ignore_permissions=True)
        frappe.db.commit()
        # Same name, new row -- exactly what a get-or-create fixture does next run.
        frappe.get_doc(
            {"doctype": "Territory", "territory_name": fixed, "parent_territory": "All Territories"}
        ).insert()
        frappe.db.commit()
        # Deliberately NOT cleaned up here: the recreated row has to still be present
        # when the checker runs, or this control never reaches the branch it exists to
        # exercise -- it just reads as "gone" and passes for the wrong reason. Removed
        # by hand after the check.
        print(f"CONTROL-RECREATED Territory::{fixed}")
