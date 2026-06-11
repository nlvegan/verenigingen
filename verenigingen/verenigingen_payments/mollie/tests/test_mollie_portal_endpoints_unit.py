"""
Unit coverage for the member-portal Mollie endpoints — no Mollie key, no network.

These run in CI (unlike the live suites test_mollie_portal_endpoints_live.py /
test_subscription_service_live.py) and cover the two paths the live tests cannot
reach reliably:

- update_mollie_bank_account input validation (pure-Python early returns, before
  any member resolution or Mollie call): missing IBAN, missing / over-long holder
  name, malformed IBAN.
- update_mollie_bank_account rollback: when the subscription PATCH fails after the
  new mandate was created, the just-created mandate must be revoked and the Member
  record left unchanged. The PATCH failure is fault-injected (you cannot make a real
  Mollie PATCH fail mid-flight), and the Mollie SDK boundary is mocked — only the
  external HTTP client, not any app business logic.

The endpoints are still invoked as a logged-in plain member so the @self_service_api
tier gate is exercised exactly as in production.
"""

from unittest.mock import MagicMock, patch

import frappe

from verenigingen.api import mollie_payment
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.validation.iban_validator import generate_test_iban

# Path where update_mollie_bank_account imports SubscriptionService at call time;
# patching here swaps the class the endpoint instantiates.
_SUBSCRIPTION_SERVICE = (
    "verenigingen.verenigingen_payments.mollie.services.subscription_service.SubscriptionService"
)


class TestMolliePortalEndpointsUnit(EnhancedTestCase):
    """Member-portal Mollie endpoint validation + rollback, without touching Mollie."""

    # --- session / user helpers (mirror test_member_portal_self_service.py) ---

    def _link_member_to_user(self, **mollie_fields):
        """A Member linked to a plain-member User (LOW tier), optionally carrying
        Mollie id fields so the endpoint clears its 'no subscription' guard."""
        member = self.create_test_member(birth_date="1990-01-01")
        user = self.factory.create_user_with_roles(
            email=f"mollie-unit-{member.name}-{self.uid}@example.com",
            roles=["Verenigingen Member"],
        )
        user.reload()
        user.set("role_profiles", [{"role_profile": "Verenigingen Member"}])
        user.save(ignore_permissions=True)

        member.reload()
        member.user = user.name
        member.email = user.name
        member.save(ignore_permissions=True)

        if mollie_fields:
            frappe.db.set_value("Member", member.name, mollie_fields)
            member.reload()
        return member, user

    def _as_user(self, user_name):
        class _Switcher:
            def __enter__(self):
                self.original = frappe.session.user
                frappe.set_user(user_name)
                return self

            def __exit__(self, *_):
                frappe.set_user(self.original)

        return _Switcher()

    # --- input validation ----------------------------------------------------

    def test_update_bank_account_rejects_missing_iban(self):
        _, user = self._link_member_to_user()
        with self._as_user(user.name):
            result = mollie_payment.update_mollie_bank_account(iban="", account_holder_name="Jan Jansen")
        self.assertEqual(result["status"], "error")
        self.assertIn("iban is required", result["message"].lower())

    def test_update_bank_account_rejects_missing_holder_name(self):
        _, user = self._link_member_to_user()
        with self._as_user(user.name):
            result = mollie_payment.update_mollie_bank_account(
                iban=generate_test_iban(), account_holder_name=""
            )
        self.assertEqual(result["status"], "error")
        self.assertIn("account holder name is required", result["message"].lower())

    def test_update_bank_account_rejects_overlong_holder_name(self):
        _, user = self._link_member_to_user()
        with self._as_user(user.name):
            result = mollie_payment.update_mollie_bank_account(
                iban=generate_test_iban(), account_holder_name="A" * 71
            )
        self.assertEqual(result["status"], "error")
        self.assertIn("70 characters", result["message"].lower())

    def test_update_bank_account_rejects_malformed_iban(self):
        _, user = self._link_member_to_user()
        with self._as_user(user.name):
            result = mollie_payment.update_mollie_bank_account(
                iban="NOT-AN-IBAN", account_holder_name="Jan Jansen"
            )
        self.assertEqual(result["status"], "error")
        self.assertIn("iban", result["message"].lower())

    # --- rollback on PATCH failure -------------------------------------------

    def test_update_bank_account_revokes_new_mandate_when_patch_fails(self):
        """When update_subscription_mandate raises after the new mandate is created,
        the endpoint revokes that new mandate and leaves the Member record untouched."""
        member, user = self._link_member_to_user(
            mollie_customer_id="cst_aaaaaaaaaa",
            mollie_subscription_id="sub_aaaaaaaaaa",
            mollie_mandate_id="mdt_originalaa",
        )

        with patch(_SUBSCRIPTION_SERVICE) as MockService:
            service = MockService.return_value
            customer_obj = service.client.sdk_client.customers.get.return_value
            # Active subscription so the endpoint proceeds past its status guard.
            customer_obj.subscriptions.get.return_value.status = "active"
            # The new mandate the endpoint creates...
            new_mandate = MagicMock()
            new_mandate.id = "mdt_newrollbackk"
            customer_obj.mandates.create.return_value = new_mandate
            # ...and the PATCH that fails, triggering rollback.
            service.update_subscription_mandate.side_effect = Exception("simulated PATCH failure")

            with self._as_user(user.name):
                result = mollie_payment.update_mollie_bank_account(
                    iban=generate_test_iban(), account_holder_name="Jan Jansen"
                )

            # The newly-created mandate was revoked as part of the rollback.
            customer_obj.mandates.delete.assert_called_once_with("mdt_newrollbackk")

        self.assertEqual(result["status"], "error")
        # The Member record was not advanced to the new (now-revoked) mandate.
        member.reload()
        self.assertEqual(member.mollie_mandate_id, "mdt_originalaa")
