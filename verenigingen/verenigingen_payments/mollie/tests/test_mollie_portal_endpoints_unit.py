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

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.api import mollie_payment
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.portal_self_service_mixin import PortalSelfServiceTestMixin
from verenigingen.utils.validation.iban_validator import generate_test_iban

# Path where update_mollie_bank_account imports SubscriptionService at call time;
# patching here swaps the class the endpoint instantiates.
_SUBSCRIPTION_SERVICE = (
    "verenigingen.verenigingen_payments.mollie.services.subscription_service.SubscriptionService"
)


class TestMolliePortalEndpointsUnit(PortalSelfServiceTestMixin, EnhancedTestCase):
    """Member-portal Mollie endpoint validation + rollback, without touching Mollie."""

    def _member_with_mollie(self, **mollie_fields):
        """A Member linked to a plain-member User (via the mixin), optionally
        carrying Mollie id fields so the endpoint clears its 'no subscription'
        guard. Returns (member, user)."""
        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member)
        if mollie_fields:
            frappe.db.set_value("Member", member.name, mollie_fields)
            member.reload()
        return member, user

    # --- input validation ----------------------------------------------------

    def test_update_bank_account_rejects_missing_iban(self):
        _, user = self._member_with_mollie()
        with self._as_user(user.name):
            result = mollie_payment.update_mollie_bank_account(iban="", account_holder_name="Jan Jansen")
        self.assertEqual(result["status"], "error")
        self.assertIn("iban is required", result["message"].lower())

    def test_update_bank_account_rejects_missing_holder_name(self):
        _, user = self._member_with_mollie()
        with self._as_user(user.name):
            result = mollie_payment.update_mollie_bank_account(
                iban=generate_test_iban(), account_holder_name=""
            )
        self.assertEqual(result["status"], "error")
        self.assertIn("account holder name is required", result["message"].lower())

    def test_update_bank_account_rejects_overlong_holder_name(self):
        _, user = self._member_with_mollie()
        with self._as_user(user.name):
            result = mollie_payment.update_mollie_bank_account(
                iban=generate_test_iban(), account_holder_name="A" * 71
            )
        self.assertEqual(result["status"], "error")
        self.assertIn("70 characters", result["message"].lower())

    def test_update_bank_account_rejects_malformed_iban(self):
        _, user = self._member_with_mollie()
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
        member, user = self._member_with_mollie(
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

    # --- old-mandate revocation ------------------------------------------------

    def _successful_update_mocks(self, MockService, subscription_mandate_id):
        """Wire the SDK mocks for a happy-path bank update: active subscription
        carrying `subscription_mandate_id`, new mandate created, PATCH succeeds.
        Returns the customer mock for assertions."""
        service = MockService.return_value
        customer_obj = service.client.sdk_client.customers.get.return_value
        subscription = customer_obj.subscriptions.get.return_value
        subscription.status = "active"
        subscription.mandate_id = subscription_mandate_id
        customer_obj.mandates.create.return_value = MagicMock(id="mdt_newsuccess1")
        service.update_subscription_mandate.return_value = {"status": "success"}
        return customer_obj

    def test_update_bank_account_revokes_old_mandate_from_subscription(self):
        """The old mandate to revoke comes from the subscription itself, so the
        revoke works even when Member.mollie_mandate_id was never populated
        (true for every member onboarded before this endpoint existed)."""
        member, user = self._member_with_mollie(
            mollie_customer_id="cst_aaaaaaaaaa",
            mollie_subscription_id="sub_aaaaaaaaaa",
            # mollie_mandate_id deliberately left empty
        )

        with patch(_SUBSCRIPTION_SERVICE) as MockService:
            customer_obj = self._successful_update_mocks(MockService, "mdt_oldfromsub1")
            with self._as_user(user.name):
                result = mollie_payment.update_mollie_bank_account(
                    iban=generate_test_iban(), account_holder_name="Jan Jansen"
                )
            customer_obj.mandates.delete.assert_called_once_with("mdt_oldfromsub1")

        self.assertEqual(result["status"], "success")
        member.reload()
        self.assertEqual(member.mollie_mandate_id, "mdt_newsuccess1")

    def test_update_bank_account_prefers_subscription_mandate_over_member_field(self):
        """When the Member field and the subscription disagree, the subscription
        is authoritative - it is what Mollie is actually charging."""
        _, user = self._member_with_mollie(
            mollie_customer_id="cst_aaaaaaaaaa",
            mollie_subscription_id="sub_aaaaaaaaaa",
            mollie_mandate_id="mdt_stalefield1",
        )

        with patch(_SUBSCRIPTION_SERVICE) as MockService:
            customer_obj = self._successful_update_mocks(MockService, "mdt_subauthorit")
            with self._as_user(user.name):
                result = mollie_payment.update_mollie_bank_account(
                    iban=generate_test_iban(), account_holder_name="Jan Jansen"
                )
            customer_obj.mandates.delete.assert_called_once_with("mdt_subauthorit")

        self.assertEqual(result["status"], "success")

    def test_update_bank_account_falls_back_to_member_field_for_old_mandate(self):
        """A subscription without a mandateId (defensive: Mollie always sets one
        on active SEPA subscriptions) falls back to the Member field."""
        _, user = self._member_with_mollie(
            mollie_customer_id="cst_aaaaaaaaaa",
            mollie_subscription_id="sub_aaaaaaaaaa",
            mollie_mandate_id="mdt_fieldfallbk",
        )

        with patch(_SUBSCRIPTION_SERVICE) as MockService:
            customer_obj = self._successful_update_mocks(MockService, None)
            with self._as_user(user.name):
                result = mollie_payment.update_mollie_bank_account(
                    iban=generate_test_iban(), account_holder_name="Jan Jansen"
                )
            customer_obj.mandates.delete.assert_called_once_with("mdt_fieldfallbk")

        self.assertEqual(result["status"], "success")

    # --- signature date regression -------------------------------------------

    def test_update_bank_account_sends_utc_signature_date(self):
        """The mandate is created with a UTC signatureDate, never site-local today().

        Pins the regression the production fix targets: Mollie 422s a future-dated
        signature, which site-local today() produces east of Mollie's clock. Asserts
        the exact value passed to Mollie's mandate-create call.
        """
        _, user = self._member_with_mollie(
            mollie_customer_id="cst_aaaaaaaaaa",
            mollie_subscription_id="sub_aaaaaaaaaa",
            mollie_mandate_id="mdt_originalaa",
        )

        with patch(_SUBSCRIPTION_SERVICE) as MockService:
            service = MockService.return_value
            customer_obj = service.client.sdk_client.customers.get.return_value
            customer_obj.subscriptions.get.return_value.status = "active"
            customer_obj.mandates.create.return_value = MagicMock(id="mdt_newsuccess0")
            # PATCH succeeds -> endpoint completes the happy path.
            service.update_subscription_mandate.return_value = {"status": "success"}

            date_before = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            with self._as_user(user.name):
                result = mollie_payment.update_mollie_bank_account(
                    iban=generate_test_iban(), account_holder_name="Jan Jansen"
                )
            date_after = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            self.assertEqual(result["status"], "success")
            mandate_data = customer_obj.mandates.create.call_args.args[0]

        # The UTC date at call time (tolerating a UTC-midnight rollover during the test).
        self.assertIn(mandate_data["signatureDate"], {date_before, date_after})
