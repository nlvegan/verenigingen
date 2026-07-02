"""
Coverage tests for the Mollie www portal pages:
- verenigingen/www/mollie_subscription_audit.py
- verenigingen/www/mollie_member_reconciliation.py

Both pages are financial-admin gated. get_context() enforces a battery of
has_permission() checks; the @critical_api whitelisted endpoints additionally
gate on Verenigingen-Staff/Administrator roles (mollie_subscription_audit) or
Member write permission (mollie_member_reconciliation).

The reconciliation/audit data endpoints require a live Mollie API key which the
test site does not have, so those endpoints return a serialized failure
OperationResult (which logs). We assert the failure shape + that the log is the
expected, intentional one (expectErrorLog). The member-field-update endpoint
needs no Mollie connectivity and is driven against real Member records, asserting
the field changes actually persist.

Permission paths use REAL users + roles via set_user(); no business-logic mocking.
External Mollie connectivity is NOT mocked -- we test the real "no key" branch.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.www import mollie_member_reconciliation as mmr, mollie_subscription_audit as msa


class TestMollieWwwPagesCoverage(VereningingenTestCase):
    """Real-data tests for the Mollie audit + reconciliation portal pages."""

    def setUp(self):
        super().setUp()
        # Financial-admin user. System Manager grants the Member / Mollie Settings
        # / Payment Entry / Verenigingen Payments Settings read+write the page
        # gates require, and is also one of MollieWebhookService.ALLOWED_ROLES.
        self.admin_email = f"mollie-admin-{frappe.generate_hash()[:8]}@example.com"
        self.admin_user = self._make_user(
            self.admin_email,
            roles=["Verenigingen Administrator", "System Manager"],
        )

        # A plain member user without financial-admin permissions.
        self.plain_email = f"mollie-plain-{frappe.generate_hash()[:8]}@example.com"
        self.plain_user = self._make_user(self.plain_email, roles=["Verenigingen Member"])

    def _make_user(self, email, roles):
        if not frappe.db.exists("User", email):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": email.split("@")[0],
                    "send_welcome_email": 0,
                    "roles": [{"role": r} for r in roles],
                }
            )
            user.insert(ignore_permissions=True)
            self.track_doc("User", user.name)

        # Post the Rule-5 cap, HIGH/CRITICAL access needs an assigned role PROFILE.
        # Assign the profile matching each role so the admin user clears the page
        # endpoints' gate; Member maps to LOW and stays correctly denied.
        from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles

        grant_matching_role_profiles(email, roles)
        return email

    # ===== mollie_subscription_audit.get_context =====

    def test_audit_get_context_sets_page_flags_for_admin(self):
        # Administrator is a real user that satisfies every has_permission gate
        # (Member / Mollie Settings / Payment Entry read) -- exercises the pass path.
        with self.set_user("Administrator"):
            with self.assertNoErrorLog():
                context = frappe._dict()
                msa.get_context(context)
        self.assertEqual(context.no_cache, 1)
        self.assertFalse(context.show_sidebar)

    def test_audit_get_context_denies_plain_user(self):
        """A member without Payment Entry/Mollie Settings read is blocked."""
        with self.set_user(self.plain_email):
            with self.assertRaises(frappe.PermissionError):
                msa.get_context(frappe._dict())

    # ===== mollie_subscription_audit endpoints: role gating =====

    def test_audit_get_default_webhook_url_denied_for_plain_user(self):
        """The @critical_api decorator denies a non-admin before the body runs."""
        with self.set_user(self.plain_email):
            with self.assertRaises(frappe.PermissionError):
                msa.get_default_webhook_url()

    def test_audit_get_active_subscriptions_denied_for_plain_user(self):
        with self.set_user(self.plain_email):
            with self.assertRaises(frappe.PermissionError):
                msa.get_active_subscriptions_with_webhooks()

    def test_audit_bulk_update_denied_for_plain_user(self):
        with self.set_user(self.plain_email):
            with self.assertRaises(frappe.PermissionError):
                msa.bulk_update_subscription_webhooks("[]", "https://x/webhook")

    def test_audit_bulk_update_invalid_json_for_admin(self):
        """Admin passes the role gate but malformed JSON fails cleanly."""
        with self.set_user(self.admin_email):
            result = msa.bulk_update_subscription_webhooks("{not json", "https://x/webhook")
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))
        # Must be the JSON-format failure, not a permission denial.
        self.assertNotIn("permission_denied", str(result))

    def test_audit_run_audit_no_mollie_key_returns_failure(self):
        """Without a live Mollie key the audit fails gracefully and logs once."""
        with self.set_user(self.admin_email):
            self.expectErrorLog("Subscription Audit Error")
            result = msa.run_audit()
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))

    def test_audit_get_default_webhook_url_admin_path(self):
        """Admin passes the gate; result is a success OR a clean handled failure."""
        with self.set_user(self.admin_email):
            self.expectErrorLog("Failed to get default webhook URL")
            result = msa.get_default_webhook_url()
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        if result.get("success"):
            data = result.get("data") or {}
            self.assertIn("mode_label", data)

    # ===== mollie_member_reconciliation.get_context =====

    def test_recon_get_context_sets_page_flags_for_admin(self):
        with self.set_user(self.admin_email):
            with self.assertNoErrorLog():
                context = frappe._dict()
                mmr.get_context(context)
        self.assertEqual(context.no_cache, 1)
        self.assertFalse(context.show_sidebar)

    def test_recon_get_context_denies_plain_user(self):
        with self.set_user(self.plain_email):
            with self.assertRaises(frappe.PermissionError):
                mmr.get_context(frappe._dict())

    # ===== get_member_reconciliation_data (no Mollie key) =====

    def test_recon_data_no_mollie_key_returns_failure(self):
        with self.set_user(self.admin_email):
            self.expectErrorLog("Member Reconciliation Error")
            result = mmr.get_member_reconciliation_data()
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))

    # ===== update_member_mollie_fields (real Member, no Mollie needed) =====

    def _make_member(self):
        member = self.create_test_member(
            first_name="Recon",
            last_name="Member",
            email=f"recon-{frappe.generate_hash()[:8]}@example.com",
            birth_date="1988-03-03",
        )
        return member

    def test_update_member_fields_persists_changes(self):
        """Updating Mollie fields really writes them to the Member record."""
        member = self._make_member()
        with self.set_user(self.admin_email):
            with self.assertNoErrorLog():
                result = mmr.update_member_mollie_fields(
                    member_id=member.name,
                    mollie_subscription_id="sub_TEST123",
                    subscription_status="active",
                )
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("success"), msg=result)

        data = result.get("data") or {}
        self.assertIn("mollie_subscription_id", data.get("updated_fields", []))
        self.assertIn("subscription_status", data.get("updated_fields", []))

        # Verify persistence in the DB, not just the return payload.
        member.reload()
        self.assertEqual(member.mollie_subscription_id, "sub_TEST123")
        self.assertEqual(member.subscription_status, "active")

    def test_update_member_fields_clear_subscription_id(self):
        """Passing an empty subscription id clears the field (set to None)."""
        member = self._make_member()
        member.db_set("mollie_subscription_id", "sub_OLD")
        frappe.db.commit()

        with self.set_user(self.admin_email):
            with self.assertNoErrorLog():
                result = mmr.update_member_mollie_fields(
                    member_id=member.name,
                    mollie_subscription_id="",  # explicit clear
                )
        self.assertTrue(result.get("success"), msg=result)
        member.reload()
        self.assertIn(member.mollie_subscription_id, (None, ""))

    def test_update_member_fields_no_fields_provided(self):
        """With no updatable values supplied the endpoint reports a clean failure."""
        member = self._make_member()
        with self.set_user(self.admin_email):
            with self.assertNoErrorLog():
                result = mmr.update_member_mollie_fields(member_id=member.name)
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))
        self.assertIn("No fields", str(result))

    def test_update_member_fields_missing_member_returns_failure(self):
        """A non-existent member id produces a handled failure (logged once)."""
        with self.set_user(self.admin_email):
            self.expectErrorLog("Member Reconciliation Update Error")
            result = mmr.update_member_mollie_fields(
                member_id="NONEXISTENT-MEMBER-XYZ",
                subscription_status="active",
            )
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))
