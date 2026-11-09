# -*- coding: utf-8 -*-
"""
#1778: Frappe dispatches every doc-level ``has_permission`` hook through
``frappe.call(method, doc=doc, ptype=ptype, user=user, debug=debug)``, and
``frappe.call`` drops any keyword the hook does not declare. Nine of this app's
hooks named the parameter ``permission_type`` (or had a ``"read"`` default), so
they never saw the real ptype and every check ran as ``read``.

The only hook branch that reads the ptype is the service-account (webhook)
DocPerm deferral in ``_check_service_account_permission``; the others ignore it,
so for them the rename is behaviour-neutral and is pinned structurally.
"""

import inspect

import frappe
from frappe.permissions import has_controller_permissions

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.constants import Roles

SERVICE_DOCTYPES = ("Member", "Donor", "Donation", "Volunteer")


class TestPermissionHookReceivesPtype(EnhancedTestCase):
    def _webhook_rights(self, doctype):
        """Rights the webhook role holds in the standard DocPerm table (what the
        service-account branch consults), read from the DB, not hardcoded."""
        row = frappe.db.get_value(
            "DocPerm",
            {"parent": doctype, "role": Roles.WEBHOOK_USER, "permlevel": 0},
            ["read", "write", "create", "delete", "submit"],
            as_dict=True,
        )
        self.assertTrue(row, f"fixture assumption: webhook role has a DocPerm row on {doctype}")
        return row

    def _webhook_user(self):
        return self.create_test_user(
            email="ptype-1778-webhook@test.com", roles=[Roles.WEBHOOK_USER]
        ).name

    def test_every_registered_hook_receives_the_real_ptype(self):
        """Census over the RUNTIME registry (frappe.get_hooks), this app's handlers only,
        through frappe.get_newargs (what frappe.call uses to drop undeclared keywords)."""
        hooks = {
            dt: [p for p in paths if p.startswith("verenigingen.")]
            for dt, paths in (frappe.get_hooks("has_permission") or {}).items()
        }
        hooks = {dt: paths for dt, paths in hooks.items() if paths}
        self.assertGreaterEqual(len(hooks), 15)
        for doctype, paths in hooks.items():
            for dotted in paths:
                received = frappe.get_newargs(
                    frappe.get_attr(dotted), {"doc": None, "ptype": "write", "user": "x", "debug": False}
                )
                self.assertIn("ptype", received, f"{doctype} hook {dotted} never receives the ptype")

    def test_dues_schedule_hook_default_is_read(self):
        """The hook's own default (used when no ptype is supplied) stays read."""
        from verenigingen.verenigingen.doctype.membership_dues_schedule import (
            membership_dues_schedule as mod,
        )

        self.assertEqual(inspect.signature(mod.has_permission).parameters["ptype"].default, "read")

    def test_service_account_is_denied_a_right_its_docperm_lacks(self):
        user = self._webhook_user()
        for doctype in SERVICE_DOCTYPES:
            rights = self._webhook_rights(doctype)
            missing = [r for r in ("delete", "submit") if not rights[r]]
            self.assertTrue(missing, f"fixture assumption: webhook lacks delete/submit on {doctype}")
            for ptype in missing:
                self.assertFalse(
                    has_controller_permissions(frappe.new_doc(doctype), ptype, user=user),
                    f"{doctype}: webhook has no {ptype} DocPerm but the hook still allowed it",
                )

    def test_service_account_keeps_a_right_its_docperm_grants(self):
        """Control: the fix must not refuse what the DocPerm row grants."""
        user = self._webhook_user()
        for doctype in SERVICE_DOCTYPES:
            rights = self._webhook_rights(doctype)
            granted = [r for r in ("read", "write", "create") if rights[r]]
            self.assertTrue(granted)
            for ptype in granted:
                self.assertTrue(
                    has_controller_permissions(frappe.new_doc(doctype), ptype, user=user),
                    f"{doctype}: webhook holds {ptype} DocPerm but the hook refused it",
                )

    def test_service_account_unknown_ptype_fails_closed_without_raising(self):
        """CONTROL, not a red test: a ptype that is not a DocPerm column is refused
        by frappe.db.exists' missing-column handling (measured: the test passes with
        no explicit guard in the code). It pins that the now-reachable custom-ptype
        case cannot raise."""
        user = self._webhook_user()
        self.assertFalse(has_controller_permissions(frappe.new_doc("Member"), "not_a_right", user=user))
