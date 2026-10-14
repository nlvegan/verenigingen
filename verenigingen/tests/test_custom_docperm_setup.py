"""Custom DocPerm handling on install/migrate (#1621, #1622).

When a DocType has ANY Custom DocPerm row, Frappe ignores its stock DocPerm rows
(``frappe/model/meta.py::set_custom_permissions``). ``frappe.permissions.add_permission``
copies the stock rows first; a raw insert (what fixture import does) does not.

Probe shortcuts, stated up front: the "JSON changed" step edits the DocPerm table with
``db.set_value`` as the stand-in for "a new release's JSON was synced by migrate". The
frozen state itself is created through the REAL path (``add_permission``).
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint

PERM_FIELDS = ("read", "write", "create", "delete", "submit", "cancel", "amend", "report",
               "export", "import", "share", "print", "email", "select")


def _effective(doctype):
    frappe.clear_cache(doctype=doctype)
    return frappe.get_meta(doctype).permissions


def _roles(doctype):
    return {p.role for p in _effective(doctype)}


def _run_permission_sync():
    from verenigingen.setup.custom_docperm_setup import apply_custom_permissions

    apply_custom_permissions()


TEST_ROLE = "Test Public Creator 1621"


class TestCustomDocPermSetup(FrappeTestCase):
    def setUp(self):
        super().setUp()
        # Plain FrappeTestCase, deliberately: the Enhanced harness's insert-capture drain
        # resurrects and COMMITS the Role and Custom DocPerm rows these tests insert (measured:
        # one Role and one Custom DocPerm row leaked per run). Nothing here commits, so a
        # rollback per test is a complete cleanup.
        self.addCleanup(self._rollback_and_clear_cache)

    def _rollback_and_clear_cache(self):
        frappe.db.rollback()
        frappe.clear_cache()

    def _drop_custom(self, doctype):
        frappe.db.delete("Custom DocPerm", {"parent": doctype})

    def _raw_custom_row(self, doctype, role, **ptypes):
        frappe.get_doc(
            {"doctype": "Custom DocPerm", "parent": doctype, "parenttype": "DocType",
             "parentfield": "permissions", "role": role, "permlevel": 0, **ptypes}
        ).insert()

    # ---- #1622: core DocTypes -------------------------------------------------

    def test_pristine_doctype_keeps_stock_roles_after_install_steps(self):
        for dt in ("Company", "Account", "Mode of Payment", "Customer"):
            with self.subTest(doctype=dt):
                self._drop_custom(dt)
                stock = set(frappe.get_all("DocPerm", filters={"parent": dt}, pluck="role"))
                self.assertTrue(stock, f"{dt} has no stock DocPerm rows; fixture is meaningless")
                _run_permission_sync()
                effective = _roles(dt)
                self.assertTrue(stock <= effective, f"{dt} lost stock roles {stock - effective}")
                self.assertIn("Verenigingen Webhook User", effective)

    def test_webhook_grant_is_read_only_on_company(self):
        self._drop_custom("Company")
        _run_permission_sync()
        row = [p for p in _effective("Company") if p.role == "Verenigingen Webhook User"]
        self.assertEqual(len(row), 1)
        self.assertEqual(cint(row[0].read), 1)
        self.assertEqual(cint(row[0].write), 0)

    def test_truncated_site_is_repaired(self):
        self._drop_custom("Company")
        # the legacy outcome: fixture rows + the HRMS User Type row, no stock copy
        self._raw_custom_row("Company", "Verenigingen Webhook User", read=1)
        self._raw_custom_row("Company", "Employee Self Service", select=1)
        stock = set(frappe.get_all("DocPerm", filters={"parent": "Company"}, pluck="role"))
        self.assertFalse(stock <= _roles("Company"), "precondition: set is truncated")
        _run_permission_sync()
        self.assertTrue(stock <= _roles("Company"))
        ess = [p for p in _effective("Company") if p.role == "Employee Self Service"]
        self.assertEqual(sum(cint(p.select) for p in ess), 1, "User Type's select row kept")

    def test_admin_curated_set_is_not_repaired(self):
        self._drop_custom("Company")
        # Accounts User is stock; Sales Manager is neither declared nor a user-type role,
        # so this set cannot be the legacy truncation. Stock roles absent from it were
        # deliberately removed.
        self._raw_custom_row("Company", "Accounts User", read=1)
        self._raw_custom_row("Company", "Sales Manager", read=1)
        dropped = set(frappe.get_all("DocPerm", filters={"parent": "Company"}, pluck="role")) - {
            "Accounts User", "Sales Manager"}
        self.assertTrue(dropped)
        _run_permission_sync()
        self.assertFalse(dropped & _roles("Company"), "curated set must not get stock rows back")

    def test_grant_raises_missing_flag_and_keeps_existing_extra_flag(self):
        # An EXISTING (role, 0, 0) row, seeded through the real path (add_permission copies the
        # stock rows first): Customer/Verenigingen Staff has delete=1 (not granted by us) and
        # write=0 (granted). The sync must raise write and must not lower delete.
        from frappe.permissions import add_permission

        self._drop_custom("Customer")
        add_permission("Customer", "Verenigingen Staff", 0, "read")
        name = frappe.db.get_value(
            "Custom DocPerm", {"parent": "Customer", "role": "Verenigingen Staff", "permlevel": 0}
        )
        frappe.db.set_value("Custom DocPerm", name, {"write": 0, "delete": 1})
        _run_permission_sync()
        rows = [p for p in _effective("Customer") if p.role == "Verenigingen Staff"]
        self.assertEqual(len(rows), 1)
        self.assertEqual((cint(rows[0].write), cint(rows[0].create), cint(rows[0].delete)), (1, 1, 1))

    def test_grants_are_idempotent(self):
        self._drop_custom("Company")
        _run_permission_sync()
        first = sorted(frappe.get_all("Custom DocPerm", filters={"parent": "Company"}, pluck="name"))
        _run_permission_sync()
        second = sorted(frappe.get_all("Custom DocPerm", filters={"parent": "Company"}, pluck="name"))
        self.assertEqual(first, second)

    # ---- #1621: own DocTypes --------------------------------------------------

    def _freeze_via_user_type_path(self, doctype):
        from frappe.permissions import add_permission, update_permission_property

        self._drop_custom(doctype)
        add_permission(doctype, "Employee Self Service", 0, "select")
        update_permission_property(doctype, "Employee Self Service", 0, "select", 1, validate=False)

    def _flip_json_write_flags(self, doctype):
        """Stand-in for a release whose JSON changed (probe shortcut, see module doc)."""
        for row in frappe.get_all("DocPerm", filters={"parent": doctype}, fields=["name", "write"]):
            frappe.db.set_value("DocPerm", row.name, "write", 0 if cint(row.write) else 1)
        frappe.clear_cache(doctype=doctype)

    def _assert_effective_matches_json(self, doctype):
        effective = {(p.role, cint(p.permlevel), cint(p.if_owner)): p for p in _effective(doctype)}
        for row in frappe.get_all("DocPerm", filters={"parent": doctype}, fields="*"):
            got = effective[(row.role, cint(row.permlevel), cint(row.if_owner))]
            for f in PERM_FIELDS:
                self.assertEqual(cint(got.get(f)), cint(row.get(f)),
                                 f"{doctype} {row.role} L{row.permlevel} {f}")

    def test_frozen_own_doctype_follows_json_and_keeps_ess(self):
        for dt in ("Chapter", "Team", "Volunteer", "Expense Category"):
            with self.subTest(doctype=dt):
                self._freeze_via_user_type_path(dt)
                self._flip_json_write_flags(dt)
                _run_permission_sync()
                self._assert_effective_matches_json(dt)
                ess = [p for p in _effective(dt) if p.role == "Employee Self Service"]
                self.assertEqual([cint(p.select) for p in ess], [1], "ESS select row must survive")

    def test_reconcile_inserts_json_row_missing_from_custom_set(self):
        self._freeze_via_user_type_path("Team")
        victim = frappe.get_all("DocPerm", filters={"parent": "Team"}, fields=["role", "permlevel"])[0]
        frappe.db.delete("Custom DocPerm", {"parent": "Team", "role": victim.role,
                                            "permlevel": victim.permlevel})
        self.assertFalse(any(p.role == victim.role and cint(p.permlevel) == cint(victim.permlevel)
                             for p in _effective("Team")))
        _run_permission_sync()
        self._assert_effective_matches_json("Team")

    def test_role_not_in_json_survives_reconcile(self):
        # Member is frozen by design by the public document creator setup (add_permission
        # for a role the JSON does not declare). Its grant must outlive the reconcile.
        role = frappe.get_doc({"doctype": "Role", "role_name": TEST_ROLE}).insert()
        from frappe.permissions import add_permission, update_permission_property

        self._drop_custom("Member")
        add_permission("Member", role.name, 0)
        update_permission_property("Member", role.name, 0, "create", 1, validate=False)
        self._flip_json_write_flags("Member")
        _run_permission_sync()
        self._assert_effective_matches_json("Member")
        mine = [p for p in _effective("Member") if p.role == role.name]
        self.assertEqual([(cint(p.read), cint(p.create)) for p in mine], [(1, 1)])

    def test_own_doctype_without_custom_rows_is_left_alone(self):
        self._drop_custom("Membership Type")
        _run_permission_sync()
        self.assertEqual(frappe.db.count("Custom DocPerm", {"parent": "Membership Type"}), 0)

    # ---- #1629: a JSON revocation reaches a frozen own DocType ----------------

    def _migrate_with_json_revocation(self, doctype, revoked_role):
        """Run the real before/after migrate steps around a JSON change.

        Probe shortcut (see module doc): deleting the stock DocPerm row stands in for a
        release whose JSON no longer declares ``revoked_role``; sync_all would do the same.
        """
        from verenigingen.setup.custom_docperm_setup import snapshot_own_declared_permissions

        snapshot_own_declared_permissions()
        frappe.db.delete("DocPerm", {"parent": doctype, "role": revoked_role})
        _run_permission_sync()

    def _a_declared_role(self, doctype):
        roles = frappe.get_all("DocPerm", filters={"parent": doctype, "permlevel": 0}, pluck="role")
        return sorted(set(roles) - {"System Manager", "Administrator"})[0]

    def test_json_revocation_removes_the_frozen_row(self):
        self._freeze_via_user_type_path("Team")
        role = self._a_declared_role("Team")
        self.assertIn(role, _roles("Team"), "precondition: the frozen set carries the role")
        kept = set(frappe.get_all("DocPerm", filters={"parent": "Team"}, pluck="role")) - {role}
        self.assertTrue(kept, "control: other declared roles must exist to be wrongly pruned")
        self._migrate_with_json_revocation("Team", role)
        self.assertNotIn(role, _roles("Team"), "a role the JSON revoked must stop granting")
        self.assertTrue(kept <= _roles("Team"), f"still-declared roles pruned: {kept - _roles('Team')}")
        ess = [p for p in _effective("Team") if p.role == "Employee Self Service"]
        self.assertEqual([cint(p.select) for p in ess], [1], "ESS select row must survive")

    def test_revoking_a_permlevel_row_keeps_the_roles_level_0_row(self):
        # The key is (role, permlevel, if_owner), not the role. Probe shortcut: the extra
        # stock row stands in for a JSON that declared Team Lead at permlevel 1 as well.
        role = "Team Lead"
        frappe.get_doc({"doctype": "DocPerm", "parent": "Team", "parenttype": "DocType",
                        "parentfield": "permissions", "role": role, "permlevel": 1,
                        "read": 1}).db_insert()
        self._freeze_via_user_type_path("Team")
        from verenigingen.setup.custom_docperm_setup import snapshot_own_declared_permissions

        snapshot_own_declared_permissions()
        frappe.db.delete("DocPerm", {"parent": "Team", "role": role, "permlevel": 1})
        _run_permission_sync()
        levels = sorted(cint(p.permlevel) for p in _effective("Team") if p.role == role)
        self.assertEqual(levels, [0], "only the dropped (role, permlevel) key goes")

    def test_admin_edited_row_for_a_revoked_key_survives(self):
        # A row whose flags no longer match what the old JSON declared was changed by
        # someone else after we wrote it, so it is theirs now.
        self._freeze_via_user_type_path("Team")
        role = self._a_declared_role("Team")
        name = frappe.db.get_value("Custom DocPerm", {"parent": "Team", "role": role, "permlevel": 0})
        row = frappe.db.get_value("Custom DocPerm", name, ["export"], as_dict=True)
        frappe.db.set_value("Custom DocPerm", name, "export", 0 if cint(row.export) else 1)
        self._migrate_with_json_revocation("Team", role)
        self.assertIn(role, _roles("Team"))

    def test_role_never_declared_survives_a_revocation_migrate(self):
        role = frappe.get_doc({"doctype": "Role", "role_name": TEST_ROLE}).insert()
        from frappe.permissions import add_permission

        self._drop_custom("Member")
        add_permission("Member", role.name, 0)
        revoked = self._a_declared_role("Member")
        self._migrate_with_json_revocation("Member", revoked)
        self.assertIn(role.name, _roles("Member"))
        self.assertNotIn(revoked, _roles("Member"))

    def test_without_a_snapshot_nothing_is_pruned(self):
        # after_install, or a migrate whose before_migrate never ran: no record of the old
        # JSON, so an undeclared row cannot be told apart from an admin's and is kept.
        self._freeze_via_user_type_path("Team")
        role = self._a_declared_role("Team")
        frappe.db.delete("DocPerm", {"parent": "Team", "role": role})
        _run_permission_sync()
        self.assertIn(role, _roles("Team"))

    def test_snapshot_is_consumed_and_a_pending_one_is_not_overwritten(self):
        from verenigingen.setup import custom_docperm_setup as setup

        self._freeze_via_user_type_path("Team")
        role = self._a_declared_role("Team")
        setup.snapshot_own_declared_permissions()
        frappe.db.delete("DocPerm", {"parent": "Team", "role": role})
        # A migrate that died after sync_all: the next before_migrate must keep the OLD
        # snapshot, or the revocation is forgotten.
        setup.snapshot_own_declared_permissions()
        _run_permission_sync()
        self.assertNotIn(role, _roles("Team"))
        self.assertFalse(frappe.db.get_global(setup.SNAPSHOT_KEY))

    def test_snapshot_runs_before_migrate(self):
        # The tests above call the snapshot directly; without the hook a real migrate prunes
        # nothing. hooks/__init__.py re-exports lifecycle names one by one, so check what
        # Frappe resolves, not the lifecycle list.
        self.assertIn(
            "verenigingen.setup.custom_docperm_setup.snapshot_own_declared_permissions",
            frappe.get_hooks("before_migrate", app_name="verenigingen"),
        )

    # ---- #1642: a CORE_GRANTS removal reaches the core DocType ----------------
    #
    # Probe shortcut: patching ``CORE_GRANTS`` stands in for a release whose tuple list changed
    # (the grants are Python, there is no JSON to edit). Mock justified: it replaces a constant
    # the code under test reads, not any behaviour; every Custom DocPerm row is real.

    def _sync_with(self, grants):
        from unittest import mock

        from verenigingen.setup import custom_docperm_setup as setup

        with mock.patch.object(setup, "CORE_GRANTS", tuple(grants)):
            setup.apply_custom_permissions()

    def _clear_ledger(self):
        from verenigingen.setup import custom_docperm_setup as setup

        frappe.defaults.clear_default(key=setup.CORE_LEDGER_KEY, parent="__global")

    def _core_setup(self, doctype="Customer"):
        self._clear_ledger()
        self._drop_custom(doctype)

    def _row(self, doctype, role, level=0):
        rows = [p for p in _effective(doctype) if p.role == role and cint(p.permlevel) == level]
        return rows[0] if rows else None

    def _stock_row(self, doctype, role):
        rows = frappe.get_all("DocPerm", filters={"parent": doctype, "role": role, "permlevel": 0,
                                                  "if_owner": 0}, fields="*")
        return rows[0] if rows else None

    def test_a_removed_tuple_stops_granting_and_leaves_the_rest(self):
        self._core_setup()
        ours = ("Customer", "Verenigingen Staff", ("read", "write", "create"))
        kept = ("Company", "Verenigingen Webhook User", ("read",))
        self._drop_custom("Company")
        self._sync_with([ours, kept])
        self.assertEqual(cint(self._row("Customer", "Verenigingen Staff").write), 1, "precondition")
        stock = set(frappe.get_all("DocPerm", filters={"parent": "Customer"}, pluck="role"))
        self.assertTrue(stock)
        self._sync_with([kept])
        self.assertIsNone(self._row("Customer", "Verenigingen Staff"), "removed tuple still grants")
        self.assertTrue(stock <= _roles("Customer"), "stock roles must stay")
        self.assertEqual(cint(self._row("Company", "Verenigingen Webhook User").read), 1)

    def test_a_dropped_ptype_is_lowered_and_the_rest_stays(self):
        self._core_setup()
        self._sync_with([("Customer", "Verenigingen Staff", ("read", "write", "create", "report"))])
        self._sync_with([("Customer", "Verenigingen Staff", ("read", "write"))])
        row = self._row("Customer", "Verenigingen Staff")
        self.assertEqual([cint(row.read), cint(row.write), cint(row.create), cint(row.report)],
                         [1, 1, 0, 0])

    def test_an_admin_raised_flag_on_the_same_row_survives_a_removal(self):
        self._core_setup()
        self._sync_with([("Customer", "Verenigingen Staff", ("read", "write", "create"))])
        name = frappe.db.get_value("Custom DocPerm", {"parent": "Customer",
                                                      "role": "Verenigingen Staff", "permlevel": 0})
        frappe.db.set_value("Custom DocPerm", name, "delete", 1)  # Role Permissions Manager edit
        self._sync_with([])
        row = self._row("Customer", "Verenigingen Staff")
        self.assertIsNotNone(row, "a row an admin extended is theirs now")
        self.assertEqual([cint(row.delete), cint(row.write), cint(row.create)], [1, 0, 0])

    def test_an_admin_raised_flag_survives_a_ptype_drop(self):
        self._core_setup()
        self._sync_with([("Customer", "Verenigingen Staff", ("read", "write", "create"))])
        name = frappe.db.get_value("Custom DocPerm", {"parent": "Customer",
                                                      "role": "Verenigingen Staff", "permlevel": 0})
        frappe.db.set_value("Custom DocPerm", name, "submit", 1)
        self._sync_with([("Customer", "Verenigingen Staff", ("read",))])
        row = self._row("Customer", "Verenigingen Staff")
        self.assertEqual([cint(row.submit), cint(row.write), cint(row.create)], [1, 0, 0])

    def test_an_ess_row_on_the_same_doctype_survives(self):
        # The HRMS User Type path freezes the set and adds Employee Self Service rows.
        self._core_setup()
        self._freeze_via_user_type_path("Customer")
        self._sync_with([("Customer", "Verenigingen Staff", ("read", "write", "create"))])
        self._sync_with([])
        ess = [p for p in _effective("Customer") if p.role == "Employee Self Service"]
        self.assertEqual([cint(p.select) for p in ess], [1], "ESS select row must survive")
        self.assertIsNone(self._row("Customer", "Verenigingen Staff"))

    def test_a_flag_the_stock_row_grants_is_not_lowered(self):
        # Declared ptypes include one stock already grants and one it does not. Dropping the
        # tuple must take back only the second. Derived from the stock row, not hardcoded.
        doctype = "Customer"
        stock = next(r for r in frappe.get_all("DocPerm", filters={"parent": doctype, "permlevel": 0,
                                                                   "if_owner": 0}, fields="*")
                     if cint(r.write) and not cint(r.cancel) and r.role not in ("System Manager",))
        self.assertTrue(cint(stock.read) and cint(stock.write), "fixture: stock grants read+write")
        self._core_setup(doctype)
        self._sync_with([(doctype, stock.role, ("read", "write", "cancel"))])
        self.assertEqual(cint(self._row(doctype, stock.role).cancel), 1, "precondition: we raised it")
        self._sync_with([])
        row = self._row(doctype, stock.role)
        self.assertEqual([cint(row.read), cint(row.write), cint(row.cancel)], [1, 1, 0])

    def test_a_flag_stock_starts_granting_later_is_not_lowered(self):
        # A new Frappe/ERPNext release grants a flag we raised. It is stock's now. Probe shortcut:
        # db.set_value on the DocPerm row stands in for the synced JSON.
        doctype = "Customer"
        stock = next(r for r in frappe.get_all("DocPerm", filters={"parent": doctype, "permlevel": 0,
                                                                   "if_owner": 0}, fields="*")
                     if cint(r.write) and not cint(r.cancel) and r.role not in ("System Manager",))
        self._core_setup(doctype)
        self._sync_with([(doctype, stock.role, ("read", "cancel"))])
        self.assertEqual(cint(self._row(doctype, stock.role).cancel), 1, "precondition: we raised it")
        frappe.db.set_value("DocPerm", stock.name, "cancel", 1)
        self._sync_with([])
        self.assertEqual(cint(self._row(doctype, stock.role).cancel), 1)

    def test_a_fixture_era_row_is_revoked_once_the_ledger_has_seen_it(self):
        # Existing sites hold raw-inserted rows and no ledger. The first run adopts them from the
        # current declaration; the removal after that revokes.
        self._core_setup()
        self._raw_custom_row("Customer", "Verenigingen Staff", read=1, write=1, create=1)
        grants = [("Customer", "Verenigingen Staff", ("read", "write", "create"))]
        self._sync_with(grants)
        self._sync_with([])
        self.assertIsNone(self._row("Customer", "Verenigingen Staff"))

    def test_without_a_ledger_a_removal_is_not_guessed(self):
        # History before the ledger is unknowable: a row nothing has declared is kept.
        self._core_setup()
        self._sync_with([("Customer", "Verenigingen Staff", ("read", "write", "create"))])
        self._clear_ledger()
        self._sync_with([])
        self.assertEqual(cint(self._row("Customer", "Verenigingen Staff").write), 1)

    def test_every_duplicate_row_is_lowered(self):
        self._core_setup()
        self._sync_with([("Customer", "Verenigingen Staff", ("read", "write"))])
        self._raw_custom_row("Customer", "Verenigingen Staff", read=1, write=1)
        self._sync_with([])
        self.assertIsNone(self._row("Customer", "Verenigingen Staff"))

    def test_a_still_declared_grant_is_never_revoked(self):
        # Control for the revoke: two syncs of the real CORE_GRANTS must not lower anything.
        from verenigingen.setup.custom_docperm_setup import CORE_GRANTS

        for doctype in sorted({g[0] for g in CORE_GRANTS}):
            self._drop_custom(doctype)
        self._clear_ledger()
        _run_permission_sync()
        _run_permission_sync()
        for doctype, role, ptypes in CORE_GRANTS:
            effective = [p for p in _effective(doctype) if p.role == role and cint(p.permlevel) == 0]
            for ptype in ptypes:
                self.assertTrue(any(cint(p.get(ptype)) for p in effective), f"{doctype} {role} {ptype}")
