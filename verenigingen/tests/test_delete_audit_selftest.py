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

`DELETE_AUDIT_SELFTEST` is the gate, and deliberately NOT `DELETE_AUDIT_LOG`. Gating on
the recorder variable looked tidier and was wrong: the tool's own next step is a
suite-wide census, which sets `DELETE_AUDIT_LOG` over the whole app -- and that would
re-arm these two stranded rows with no `selftest.sh` to sweep them. Only `selftest.sh`
sets `DELETE_AUDIT_SELFTEST`.
"""

import os
import unittest

import frappe

SELFTEST_ENV_VAR = "DELETE_AUDIT_SELFTEST"


def _territory(prefix):
    """One implementation, imported LAZILY.

    One implementation because the duplicate-helper guard is right that a second
    `_territory` is a copy-paste, and this module exists because three throwaway probes
    were not shared either.

    Lazily because importing that module at collection time costs 8.1s and ~2070 modules
    -- it pulls `erpnext.tests.utils`, whose module body runs `BootStrapTestData()`, and
    `enhanced_test_factory`, which calls `disable_workflow_action_emails()` unwrapped.
    These tests skip unless the gate is set, and a gated-off module must not pay for --
    let alone fail collection on -- an import it never uses.
    """
    from verenigingen.tests.test_harness_leak_attribution import _territory as impl

    return impl(prefix)


@unittest.skipUnless(
    os.environ.get(SELFTEST_ENV_VAR),
    f"{SELFTEST_ENV_VAR} is unset. These controls strand rows on purpose; run them "
    "through scripts/testing/delete_audit/selftest.sh, which sweeps afterwards.",
)
class DeleteAuditControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Seed the Territory root locally, so this class does not depend on a helper.

        Belt-and-braces, and deliberately so. The `_territory` this module delegates
        to ALREADY calls `ensure_root_territory()` when the parent is
        "All Territories" (`test_harness_leak_attribution`), so at runtime this call
        is redundant -- `ensure_root_territory` is `db.exists`-gated and idempotent,
        so the cost is one query.

        It is here because the source guard in `test_harness_territory_root` is
        per-file and cannot follow a lazy import into another module: it sees a
        `unittest.TestCase` naming "All Territories" with no seeder in sight and
        flags it, correctly by its own rules. Making the dependency local is cheaper
        than teaching the guard to resolve cross-module delegation, and it keeps this
        class correct if `_territory` ever stops seeding.

        Imported inside `setUpClass` for the same reason the `_territory` import is
        lazy: a class skipped by the gate above runs no `setUpClass`, so a gated-off
        run still pays nothing for it.
        """
        super().setUpClass()
        from verenigingen.tests.setup import ensure_root_territory

        ensure_root_territory()

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

    def test_5_negative_a_failed_pre_delete_read_is_unverifiable(self):
        """`creation` unknown must read UNVERIFIABLE, never SURVIVED.

        The recorder reads `creation` BEFORE the delete. When that read raises it has no
        identity to compare against, and the honest verdict is "cannot tell" -- reporting
        it as a resurrection would let one broken read manufacture a finding. Planted by
        breaking the read for the duration of one delete, which is the only way to reach
        the branch: the sentinel exists precisely for a case no ordinary delete produces.
        """
        victim = _territory("zzaudit-unverifiable")
        frappe.db.commit()

        real_get_value = frappe.db.get_value

        def exploding_get_value(*a, **kw):
            if len(a) >= 3 and a[2] == "creation" and a[1] == victim.name:
                raise RuntimeError("planted: creation read failed")
            return real_get_value(*a, **kw)

        frappe.db.get_value = exploding_get_value
        try:
            frappe.delete_doc("Territory", victim.name, force=True, ignore_permissions=True)
        finally:
            frappe.db.get_value = real_get_value

        # Rolled back, so the row comes back and the checker has something to verdict on.
        frappe.db.rollback()
        self.assertTrue(frappe.db.exists("Territory", victim.name))
        print(f"CONTROL-UNVERIFIABLE Territory::{victim.name}")
