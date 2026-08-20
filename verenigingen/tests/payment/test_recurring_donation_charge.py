"""Booking a recurring Mollie donation charge — issue #345 part A.

Mollie charges a recurring donor every period and posts the subscription's
webhookUrl with a NEW payment id. Nothing matched that id to a donation, so
every charge after the first went unbooked. A charge now gets its own Donation,
carrying payment_id = the charge's id, and the existing webhook pipeline books
it from there.

Run with:
    cd ~/frappe-bench && PYTHONPATH=<worktree> bench --site test_site_1 \\
      run-tests --app verenigingen \\
      --module verenigingen.tests.payment.test_recurring_donation_charge
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from mollie.api.error import RequestError

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase, shared_fixture
from verenigingen.verenigingen.doctype.periodic_donation_agreement.periodic_donation_agreement import (
    PeriodicDonationAgreement,
)
from verenigingen.verenigingen_payments.mollie.services.recurring_donation_charge import (
    RecurringChargeOriginMissing,
    ensure_donation_for_recurring_charge,
)
from verenigingen.verenigingen_payments.mollie.services.unified_idempotency_manager import (
    UnifiedIdempotencyManager,
)
from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
    UnifiedWebhookWrapperService,
)

_SERVICE = "verenigingen.verenigingen_payments.mollie.services.recurring_donation_charge"

# EUR company: the donation Journal Entry posts single-currency, and ERPNext's
# JE / Bank Transaction validation requires the account currency to match the
# company currency. Matches test_donation_subscription_activation.py, whose
# setUpClass/setUp arrangement the wiring class below copies.
COMPANY = "_Test Company 2"

# `None` is a meaningful subscription_id in _charge() -- it is how "this payment
# has no subscription" is expressed -- so the default cannot be None.
_UNSET = object()


class TestChargeDonationEmails(EnhancedTestCase):
    """A charge must not re-thank the donor for donating."""

    def _create_donor(self):
        # self.factory.create_test_donor() does not exist on EnhancedTestCase's
        # factory (EnhancedTestDataFactory) -- confirmed by an AttributeError at
        # runtime, not by reading. Build the donor the same way
        # test_donation_subscription_activation.py does instead of inventing a
        # new shared fixture helper.
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Charge Donor {frappe.generate_hash(length=6)}"
        donor.donor_email = f"charge.{frappe.generate_hash(length=6)}@example.org"
        donor.donor_type = "Individual"
        donor.preferred_communication_method = "Email"
        donor.flags.ignore_validate = True
        donor.insert(ignore_permissions=True)
        self.track_test_record("Donor", donor.name)
        return donor.name

    def _donation(self, **overrides):
        donor_name = self._create_donor()
        values = {
            "doctype": "Donation",
            "donor": donor_name,
            "donation_date": frappe.utils.nowdate(),
            "amount": 25,
            "mode_of_payment": "Mollie",
            "paid": 0,
            "status": "One-time",
        }
        values.update(overrides)
        return frappe.get_doc(values)

    def test_recurring_origin_donation_field_exists(self):
        meta = frappe.get_meta("Donation")
        field = meta.get_field("recurring_origin_donation")
        self.assertIsNotNone(field, "Donation.recurring_origin_donation is missing")
        self.assertEqual(field.fieldtype, "Link")
        self.assertEqual(field.options, "Donation")

    def test_origin_donation_sends_the_donation_confirmation(self):
        # Control. Without this, the next test passes even if the email was
        # never sent for any donation at all.
        with patch("frappe.enqueue") as enqueued:
            self._donation().insert()
        methods = [c.args[0] if c.args else c.kwargs.get("method") for c in enqueued.call_args_list]
        self.assertIn(
            "verenigingen.verenigingen.doctype.donation.donation.send_donation_confirmation_email",
            methods,
        )

    def test_charge_donation_does_not_send_the_donation_confirmation(self):
        origin = self._donation().insert()
        with patch("frappe.enqueue") as enqueued:
            self._donation(recurring_origin_donation=origin.name, status="Recurring").insert()
        methods = [c.args[0] if c.args else c.kwargs.get("method") for c in enqueued.call_args_list]
        self.assertNotIn(
            "verenigingen.verenigingen.doctype.donation.donation.send_donation_confirmation_email",
            methods,
        )

    def test_charge_donation_still_sends_the_payment_confirmation(self):
        # The donor keeps a receipt per period; only the "welcome" mail is dropped.
        origin = self._donation().insert()
        with patch("frappe.enqueue") as enqueued:
            self._donation(recurring_origin_donation=origin.name, status="Recurring", paid=1).insert()
        methods = [c.args[0] if c.args else c.kwargs.get("method") for c in enqueued.call_args_list]
        self.assertIn(
            "verenigingen.verenigingen.doctype.donation.donation.send_payment_confirmation_email",
            methods,
        )


class TestEnsureDonationForRecurringCharge(EnhancedTestCase):
    """The service that gives a subscription charge a Donation of its own."""

    def setUp(self):
        super().setUp()
        # "Mollie" and "iDEAL" are not app fixtures; "SEPA Direct Debit" is the
        # mode the charge is expected to land on. Seed all three so the class
        # passes in isolation rather than on shard ordering.
        self.ensure_mode_of_payment("iDEAL")
        self.ensure_mode_of_payment("SEPA Direct Debit")
        # Every Mollie id in this class carries a per-test suffix. payment_id is
        # UNIQUE, so a leftover row from an interrupted run would make a fixed
        # literal fail forever on that site, and the subscription-id fallback
        # would join to it.
        self.tag = frappe.generate_hash(length=8)
        self.subscription_id = f"sub_book_{self.tag}"
        self.first_payment_id = f"tr_the_first_one_{self.tag}"

    # --- fixtures -------------------------------------------------------------------

    def _setup_donor(self):
        # self.factory.create_test_donor() does not exist on EnhancedTestCase's
        # factory (EnhancedTestDataFactory); build the donor the way
        # test_donation_subscription_activation.py does.
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Charge Donor {frappe.generate_hash(length=6)}"
        donor.donor_email = f"charge.{frappe.generate_hash(length=6)}@example.org"
        donor.donor_type = "Individual"
        donor.preferred_communication_method = "Email"
        donor.flags.ignore_validate = True
        donor.insert(ignore_permissions=True)
        self.track_test_record("Donor", donor.name)
        return donor.name

    def _setup_origin(self, donor=None, **overrides):
        values = {
            "doctype": "Donation",
            "donor": donor or self._setup_donor(),
            "donation_date": "2026-07-01",
            "amount": 25,
            "mode_of_payment": "iDEAL",
            "status": "Recurring",
            "paid": 1,
            "payment_id": self.first_payment_id,
            "mollie_subscription_id": self.subscription_id,
            "mollie_customer_id": "cst_book",
            "recurring_frequency": "Monthly",
        }
        values.update(overrides)
        origin = frappe.get_doc(values).insert()
        self.track_test_record("Donation", origin.name)
        return origin

    def _setup_agreement(self, donor):
        """An Active pledge agreement for `donor`.

        A non-ANBI duration keeps ANBIValidationService (BSN, consent, one
        active ANBI agreement per donor) out of the fixture. It is inserted as
        Draft and promoted with db.set_value so the Active-only after_insert /
        on_update notification paths never run.
        """
        agreement = frappe.get_doc(
            {
                "doctype": "Periodic Donation Agreement",
                "donor": donor,
                "agreement_type": "Private Written",
                "agreement_date": "2026-07-01",
                "start_date": "2026-07-01",
                "agreement_duration_years": "1 Year (Pledge - No ANBI benefits)",
                "anbi_eligible": 0,
                "annual_amount": 300,
                "payment_frequency": "Monthly",
                "payment_method": "SEPA Direct Debit",
                "status": "Draft",
            }
        ).insert(ignore_permissions=True)
        self.track_test_record("Periodic Donation Agreement", agreement.name)
        frappe.db.set_value("Periodic Donation Agreement", agreement.name, "status", "Active")
        agreement.reload()
        return agreement

    def _charge(self, origin_name=None, subscription_id=_UNSET, payment_id=None, **overrides):
        """A recurring charge in the shape Mollie actually sends.

        Measured on a real subscription payment: sequenceType 'recurring',
        subscriptionId, customerId, mandateId, method 'directdebit', and the
        subscription's metadata copied verbatim -- metadata.payment_id being the
        FIRST payment's id, not this charge's.
        """
        if subscription_id is _UNSET:
            subscription_id = self.subscription_id
        payload = {
            "id": payment_id or f"tr_charge_{frappe.generate_hash(length=8)}",
            "status": "paid",
            "sequenceType": "recurring",
            "subscriptionId": subscription_id,
            "customerId": "cst_book",
            "mandateId": "mdt_book",
            "method": "directdebit",
            "description": "Recurring donation",
            "amount": {"value": "25.00", "currency": "EUR"},
            "createdAt": "2026-08-01T00:10:00+00:00",
            "paidAt": "2026-08-03T09:00:00+00:00",
            "metadata": {"donation_id": origin_name, "payment_id": self.first_payment_id}
            if origin_name
            else None,
        }
        payload.update(overrides)
        return payload

    def _audit_rows(self, event_type, payment_id):
        """Audit rows of `event_type` naming THIS charge.

        Filtering on the description prefix _audit() writes matters: payment_id
        is per-test unique, so a leftover row from another test or an earlier
        run cannot satisfy the assertion. A bare count of the table would.
        """
        return frappe.get_all(
            "Mollie Audit Log",
            filters={"event_type": event_type, "description": ["like", f"[{payment_id}]%"]},
            pluck="name",
        )

    def _normalised(self, payload):
        """`payload` put through the REAL _fetch_payment_from_mollie.

        Not a hand-copied snake_case dict: the point is that whatever the
        normaliser emits is what the webhook hands the service, so the two have
        to be exercised together or they drift. Only the HTTP boundary is faked.
        """
        from mollie.api.objects.payment import Payment

        service = object.__new__(UnifiedWebhookWrapperService)
        service.logger = frappe.logger("test_recurring_donation_charge")
        service._debug_mode = False
        client = SimpleNamespace(
            payments=SimpleNamespace(get=lambda payment_id: Payment(dict(payload), None))
        )
        with patch(
            "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings."
            "MollieSettings.get_mollie_client",
            return_value=client,
        ):
            return service._fetch_payment_from_mollie(payload["id"])

    # --- what it declines to touch -------------------------------------------------

    def test_first_payment_is_not_a_charge(self):
        self.assertIsNone(ensure_donation_for_recurring_charge(self._charge(sequenceType="first")))

    def test_payment_without_a_subscription_is_not_a_charge(self):
        self.assertIsNone(ensure_donation_for_recurring_charge(self._charge(subscription_id=None)))

    def test_unpaid_charge_creates_nothing(self):
        # Charges are created 'pending' and settle days later; only a paid one books.
        origin = self._setup_origin()
        charge = self._charge(origin.name, status="pending")
        self.assertIsNone(ensure_donation_for_recurring_charge(charge))
        self.assertFalse(frappe.db.exists("Donation", {"payment_id": charge["id"]}))
        # CONTROL for the next test: 'pending' is the normal case and must NOT
        # audit, or "a failed charge is audited" would be true of every charge.
        self.assertEqual(self._audit_rows("recurring_charge_not_paid", charge["id"]), [])

    def test_failed_charge_creates_nothing_but_is_audited(self):
        origin = self._setup_origin()
        charge = self._charge(origin.name, status="failed")
        self.assertIsNone(ensure_donation_for_recurring_charge(charge))
        self.assertFalse(frappe.db.exists("Donation", {"payment_id": charge["id"]}))
        self.assertEqual(
            len(self._audit_rows("recurring_charge_not_paid", charge["id"])),
            1,
            "a failed charge must leave a trace naming that charge",
        )

    # --- the happy path -------------------------------------------------------------

    def test_creates_a_donation_for_the_charge(self):
        origin = self._setup_origin()
        payload = self._charge(origin.name)
        charge = frappe.get_doc("Donation", ensure_donation_for_recurring_charge(payload))
        self.assertEqual(charge.payment_id, payload["id"])
        self.assertEqual(charge.recurring_origin_donation, origin.name)
        self.assertEqual(charge.donor, origin.donor)
        self.assertEqual(float(charge.amount), 25.00)
        self.assertEqual(str(charge.donation_date), "2026-08-03")
        self.assertEqual(charge.status, "Recurring")
        self.assertEqual(charge.mollie_subscription_id, self.subscription_id)

    def test_mode_of_payment_reflects_the_charge_not_the_origin(self):
        # The origin was iDEAL; the charge is always a direct debit.
        origin = self._setup_origin(mode_of_payment="iDEAL")
        payload = self._charge(origin.name)
        charge = frappe.get_doc("Donation", ensure_donation_for_recurring_charge(payload))
        self.assertEqual(charge.mode_of_payment, "SEPA Direct Debit")
        # CONTROL for the fallback test below.
        self.assertEqual(
            self._audit_rows("recurring_charge_mode_of_payment_missing", payload["id"]), []
        )

    def test_a_missing_mode_of_payment_falls_back_but_says_so(self):
        """The fallback is right, its silence was not.

        If the mapped Mode of Payment is absent from a site, every charge is
        labelled with the origin's method -- iDEAL or a card -- when it was a
        direct debit. Booking anyway beats refusing money already collected, but
        mislabelling every charge forever with no trace does not.
        """
        origin = self._setup_origin(mode_of_payment="iDEAL")
        payload = self._charge(origin.name)
        with patch.dict(
            f"{_SERVICE}._METHOD_TO_MODE_OF_PAYMENT",
            {"directdebit": f"Absent Mode {frappe.generate_hash(length=6)}"},
            clear=True,
        ):
            charge = frappe.get_doc("Donation", ensure_donation_for_recurring_charge(payload))
        self.assertEqual(charge.mode_of_payment, "iDEAL", "must still book, labelled from the origin")
        self.assertEqual(
            len(self._audit_rows("recurring_charge_mode_of_payment_missing", payload["id"])), 1
        )

    def test_an_unmapped_mollie_method_falls_back_but_says_so(self):
        """The likelier half of the same fallback, and the one that was silent.

        _METHOD_TO_MODE_OF_PAYMENT only knows 'directdebit'. A card mandate
        charges 'creditcard', so it never reaches the mapping at all -- and the
        audit used to fire only when the mapping HAD matched, which is the case
        that needs a missing Mode of Payment on top. So the commonest
        mislabelling was the one nothing recorded.
        """
        origin = self._setup_origin(mode_of_payment="iDEAL")
        payload = self._charge(origin.name, method="creditcard")
        charge = frappe.get_doc("Donation", ensure_donation_for_recurring_charge(payload))
        self.assertEqual(charge.mode_of_payment, "iDEAL", "must still book, labelled from the origin")
        rows = self._audit_rows("recurring_charge_mode_of_payment_missing", payload["id"])
        self.assertEqual(len(rows), 1)
        self.assertIn(
            "creditcard",
            frappe.db.get_value("Mollie Audit Log", rows[0], "description"),
            "the row has to name the method, or it cannot be acted on",
        )

    def test_designation_fields_are_carried_over(self):
        origin = self._setup_origin(
            donation_purpose_type="Chapter",
            chapter_reference=self.factory.create_test_chapter().name,
            fund_designation="Sanctuary fund",
            donation_purpose="Feed the residents",
        )
        charge = frappe.get_doc(
            "Donation", ensure_donation_for_recurring_charge(self._charge(origin.name))
        )
        self.assertEqual(charge.donation_purpose_type, "Chapter")
        self.assertEqual(charge.chapter_reference, origin.chapter_reference)
        self.assertEqual(charge.fund_designation, "Sanctuary fund")
        # donation_history_manager copies this into the donor's history entry,
        # so a charge that drops it shows a blank purpose beside its origin.
        self.assertEqual(charge.donation_purpose, "Feed the residents")

    def test_campaign_recorded_only_in_notes_still_validates(self):
        # validate_donation_purpose accepts purpose_type Campaign without a
        # campaign link only when "Campaign:" appears in the notes. Dropping
        # donation_notes would make every charge of such a donation throw.
        origin = self._setup_origin(
            donation_purpose_type="Campaign", donation_notes="Campaign: Zomeractie 2026"
        )
        charge = frappe.get_doc(
            "Donation", ensure_donation_for_recurring_charge(self._charge(origin.name))
        )
        self.assertIn("Campaign:", charge.donation_notes)

    def test_resolves_the_origin_by_subscription_when_metadata_is_null(self):
        origin = self._setup_origin()
        name = ensure_donation_for_recurring_charge(self._charge(origin_name=None))
        self.assertEqual(frappe.get_doc("Donation", name).recurring_origin_donation, origin.name)

    def test_the_shape_the_webhook_actually_hands_over_carries_the_mandate(self):
        """Every other test here uses raw camelCase. The webhook does not.

        It normalises through _fetch_payment_from_mollie first, and that
        hand-written whitelist emitted no mandate_id at all -- so
        mollie_mandate_id was None on every charge booked in production while
        this suite was green. Driving the real normaliser is what closes it.
        """
        origin = self._setup_origin()
        normalised = self._normalised(self._charge(origin.name))
        self.assertIn(
            "mandate_id", normalised, "CONTROL: the normaliser does not emit the key at all"
        )
        charge = frappe.get_doc("Donation", ensure_donation_for_recurring_charge(normalised))
        self.assertEqual(charge.mollie_mandate_id, "mdt_book")
        self.assertEqual(charge.mollie_customer_id, "cst_book")
        self.assertEqual(charge.mollie_subscription_id, self.subscription_id)
        self.assertEqual(charge.recurring_origin_donation, origin.name)

    # --- idempotency ----------------------------------------------------------------

    def test_redelivery_does_not_create_a_second_donation(self):
        origin = self._setup_origin()
        payload = self._charge(origin.name)
        first = ensure_donation_for_recurring_charge(payload)
        second = ensure_donation_for_recurring_charge(payload)
        self.assertEqual(first, second)
        self.assertEqual(frappe.db.count("Donation", {"payment_id": payload["id"]}), 1)

    def test_a_lost_race_adopts_the_winner(self):
        # Simulates the interleaving the unique constraint exists for: the
        # existence check passes, then another worker inserts before we do.
        origin = self._setup_origin()
        payload = self._charge(origin.name)
        winner = ensure_donation_for_recurring_charge(payload)
        with patch(
            "verenigingen.verenigingen_payments.mollie.services.recurring_donation_charge"
            "._donation_for_charge",
            return_value=None,
        ):
            adopted = ensure_donation_for_recurring_charge(payload)
        self.assertEqual(adopted, winner)
        self.assertEqual(frappe.db.count("Donation", {"payment_id": payload["id"]}), 1)

    # --- failures -------------------------------------------------------------------

    def test_unknown_subscription_raises_so_mollie_retries(self):
        # severity="error" makes MollieAuditLogger mirror the row into Error Log.
        self.expectErrorLog("recurring_charge_origin_missing")
        with self.assertRaises(RecurringChargeOriginMissing):
            ensure_donation_for_recurring_charge(
                self._charge(subscription_id=f"sub_nobody_knows_{self.tag}")
            )

    def test_cancelled_agreement_does_not_block_the_booking(self):
        # validate_periodic_donation_agreement throws for a non-Active agreement.
        # A donor who cancels the agreement while Mollie keeps charging must not
        # turn every charge into an unbooked retry loop.
        donor = self._setup_donor()
        agreement = self._setup_agreement(donor)
        origin = self._setup_origin(donor=donor, periodic_donation_agreement=agreement.name)
        frappe.db.set_value("Periodic Donation Agreement", agreement.name, "status", "Cancelled")
        payload = self._charge(origin.name)
        charge = frappe.get_doc("Donation", ensure_donation_for_recurring_charge(payload))
        self.assertFalse(charge.periodic_donation_agreement)
        self.assertEqual(
            len(self._audit_rows("recurring_charge_agreement_inactive", payload["id"])),
            1,
            "dropping the link silently is the failure mode; it must be recorded",
        )

    def test_a_failed_agreement_link_is_audited_and_keeps_the_booking(self):
        """A linkage failure must never cost us a charge already collected.

        The realistic production cause is the rate limiter: the whitelisted
        link_donation carries @high_security_api(FINANCIAL), capped by Critical
        Operation Rule at 100 calls / 3600s scoped per_user, and a monthly
        billing run arrives as one service user. The service calls the
        undecorated add_donation_link precisely to stay out of that bucket --
        which cannot be asserted here, because rate_limit_engine returns allowed
        unconditionally under frappe.flags.in_test. What IS asserted is the
        behaviour when the append fails for any reason at all.
        """
        donor = self._setup_donor()
        agreement = self._setup_agreement(donor)
        origin = self._setup_origin(donor=donor, periodic_donation_agreement=agreement.name)
        payload = self._charge(origin.name)

        # severity="error" mirrors the audit row into Error Log.
        self.expectErrorLog("recurring_charge_agreement_link")
        with patch.object(
            PeriodicDonationAgreement,
            "add_donation_link",
            side_effect=frappe.PermissionError("Rate limit exceeded"),
        ):
            name = ensure_donation_for_recurring_charge(payload)

        charge = frappe.get_doc("Donation", name)
        self.assertEqual(charge.payment_id, payload["id"], "the charge is still booked")
        self.assertEqual(charge.paid, 1)
        self.assertEqual(
            len(self._audit_rows("recurring_charge_agreement_link_error", payload["id"])),
            1,
            "a lost link is silent otherwise -- total_donated just stops moving",
        )

    def test_the_service_does_not_go_through_the_rate_limited_entry_point(self):
        """link_donation is whitelisted, decorated and rate-limited; the plain
        method beside it is not. Reaching the agreement through the decorated
        spelling would consume an interactive per_user bucket on a server-side
        path, so pin which one the service calls.
        """
        donor = self._setup_donor()
        agreement = self._setup_agreement(donor)
        origin = self._setup_origin(donor=donor, periodic_donation_agreement=agreement.name)

        with patch.object(
            PeriodicDonationAgreement, "link_donation", autospec=True
        ) as decorated, patch.object(
            PeriodicDonationAgreement, "add_donation_link", autospec=True
        ) as plain:
            ensure_donation_for_recurring_charge(self._charge(origin.name))

        self.assertEqual(plain.call_count, 1)
        decorated.assert_not_called()

    def test_the_two_entry_points_keep_the_decorators_that_make_them_different(self):
        """The property, not the call-site spelling.

        The test above pins WHICH method the service calls. It stays green if
        someone puts @high_security_api on add_donation_link, or adds a Critical
        Operation Rule row named after it -- reintroducing the bug at the other
        end. This pins the two halves that actually matter.

        `x in frappe.whitelisted` is not a proxy for the property: it is
        literally the membership test frappe.is_whitelisted() performs before
        dispatch.

        It is NOT a decorator-ORDER assertion, though it looks like one.
        Measured: swapping link_donation to @high_security_api outermost leaves
        this test green, because
        security.frappe_whitelist_adapter.register_wrapper_in_whitelist() adds
        the security wrapper to frappe.whitelisted whenever the function it
        wrapped was already whitelisted. That adapter exists precisely to defuse
        the "Method Not Allowed" trap, and for this decorator family it does. So
        do not read a green run here as proof the order is right -- read it as
        proof link_donation is still reachable over HTTP at all. The control for
        that is deleting @frappe.whitelist(), which does turn this red.
        """
        self.assertIn(
            PeriodicDonationAgreement.link_donation,
            frappe.whitelisted,
            "link_donation is no longer dispatchable over HTTP, and both the desk button "
            "(periodic_donation_agreement.js posts method: 'link_donation') and "
            "api.periodic_donation_operations.link_donation_to_agreement reach it that way. "
            "Extracting add_donation_link must not cost the interactive entry point its "
            "@frappe.whitelist().",
        )
        self.assertNotIn(
            PeriodicDonationAgreement.add_donation_link,
            frappe.whitelisted,
            "add_donation_link must NOT be whitelisted: it exists so a server-side caller can "
            "append to the agreement without an interactive rate-limit bucket or the COR's "
            "required_roles.",
        )
        self.assertFalse(
            hasattr(PeriodicDonationAgreement.add_donation_link, "__wrapped__"),
            "add_donation_link is wrapped by a decorator. It must stay undecorated -- a wrapper "
            "here is how the rate limit and the role gate come back. (Control: link_donation IS "
            f"wrapped: {hasattr(PeriodicDonationAgreement.link_donation, '__wrapped__')}.)",
        )

    # --- the agreement total, which is the whole reason for Donation-per-charge ---

    def test_each_charge_is_counted_in_the_agreement_total(self):
        """The justification for the data model, asserted rather than assumed.

        update_donation_tracking sums the agreement's `donations` child table,
        and appending to that table is the only thing that moves it -- setting
        Donation.periodic_donation_agreement does not. So if the service does
        not append, this number never moves and a Donation per charge buys
        nothing over a payment child row.
        """
        donor = self._setup_donor()
        agreement = self._setup_agreement(donor)
        origin = self._setup_origin(donor=donor, periodic_donation_agreement=agreement.name)
        frappe.get_doc("Periodic Donation Agreement", agreement.name).link_donation(origin.name)

        ensure_donation_for_recurring_charge(self._charge(origin.name, payment_id=f"tr_c1_{self.tag}"))
        ensure_donation_for_recurring_charge(self._charge(origin.name, payment_id=f"tr_c2_{self.tag}"))

        agreement.reload()
        self.assertEqual(agreement.donations_count, 3, "origin plus two charges")
        self.assertEqual(float(agreement.total_donated), 75.00)

    def test_a_failed_link_is_repaired_by_the_next_delivery(self):
        """A lost link must not be permanent.

        _link_to_agreement records rather than raises -- correctly, the money is
        already booked. But the charge Donation exists from that moment, so the
        early return would find it on every redelivery and one transient failure
        (the webhook user lacking write, a deadlock, the rate limiter) would
        leave total_donated short forever with only an audit row. total_donated
        staying correct is the entire reason a charge gets its own Donation
        rather than a payment child row, so a permanent miss is not a small one.
        """
        donor = self._setup_donor()
        agreement = self._setup_agreement(donor)
        origin = self._setup_origin(donor=donor, periodic_donation_agreement=agreement.name)
        payload = self._charge(origin.name)

        self.expectErrorLog("recurring_charge_agreement_link")
        with patch.object(
            PeriodicDonationAgreement,
            "add_donation_link",
            side_effect=frappe.PermissionError("Rate limit exceeded"),
        ):
            name = ensure_donation_for_recurring_charge(payload)

        # Precondition: the link really is missing, so the repair has something
        # to repair. Without this the test would pass on a charge that was
        # linked all along.
        self.assertFalse(
            frappe.db.get_value("Donation", name, "periodic_donation_agreement"),
            "precondition: the first delivery's link failed",
        )
        agreement.reload()
        self.assertEqual(float(agreement.total_donated), 0.0, "precondition: the total did not move")

        self.assertEqual(
            ensure_donation_for_recurring_charge(payload), name, "and still no second donation"
        )

        self.assertEqual(
            frappe.db.get_value("Donation", name, "periodic_donation_agreement"),
            agreement.name,
            "the redelivery must re-attempt the link the first delivery lost",
        )
        agreement.reload()
        self.assertEqual(agreement.donations_count, 1)
        self.assertEqual(float(agreement.total_donated), 25.00)

    def test_an_ordinary_redelivery_does_not_re_link(self):
        """CONTROL for the repair above: it must fire only on a MISSING link.

        add_donation_link throws "Donation is already linked" for a charge
        already in the child table, and _link_to_agreement records that as a
        link error -- so a repair that ran on every redelivery would manufacture
        the audit row it exists to prevent.
        """
        donor = self._setup_donor()
        agreement = self._setup_agreement(donor)
        origin = self._setup_origin(donor=donor, periodic_donation_agreement=agreement.name)
        payload = self._charge(origin.name)

        name = ensure_donation_for_recurring_charge(payload)
        self.assertEqual(
            frappe.db.get_value("Donation", name, "periodic_donation_agreement"), agreement.name
        )

        with patch.object(PeriodicDonationAgreement, "add_donation_link", autospec=True) as link:
            ensure_donation_for_recurring_charge(payload)

        link.assert_not_called()
        self.assertEqual(
            self._audit_rows("recurring_charge_agreement_link_error", payload["id"]),
            [],
            "a re-link on the normal path would log the failure it caused",
        )

    def test_a_redelivered_charge_is_not_counted_twice(self):
        donor = self._setup_donor()
        agreement = self._setup_agreement(donor)
        origin = self._setup_origin(donor=donor, periodic_donation_agreement=agreement.name)

        payload = self._charge(origin.name)
        ensure_donation_for_recurring_charge(payload)
        ensure_donation_for_recurring_charge(payload)

        agreement.reload()
        self.assertEqual(agreement.donations_count, 1)
        self.assertEqual(float(agreement.total_donated), 25.00)


class _FakeRecurringPayment(dict):
    """A subscription charge in the shape a real one arrives in.

    A real ``mollie.api.objects.Payment`` subclasses dict with camelCase keys,
    and ``_fetch_payment_from_mollie`` branches on ``isinstance(payment, dict)``
    -- so production takes the camelCase branch. A plain object would exercise
    the branch production never takes and leave the camelCase key names covered
    by nothing. Attributes are kept too, because the classifier and the
    idempotency manager read by attribute.
    """

    def __init__(
        self, payment_id, origin_name, subscription_id, first_payment_id, customer_id, mandate_id, refunds=()
    ):
        metadata = {"donation_id": origin_name, "payment_id": first_payment_id}
        super().__init__(
            {
                "id": payment_id,
                "status": "paid",
                "amount": {"value": "25.00", "currency": "EUR"},
                "description": f"Recurring donation {origin_name}",
                "createdAt": "2026-08-01T00:10:00+00:00",
                "paidAt": "2026-08-03T09:00:00+00:00",
                "method": "directdebit",
                "metadata": metadata,
                "sequenceType": "recurring",
                "customerId": customer_id,
                "mandateId": mandate_id,
                "subscriptionId": subscription_id,
            }
        )
        self.id = payment_id
        self.status = "paid"
        self.amount = {"value": "25.00", "currency": "EUR"}
        self.description = f"Recurring donation {origin_name}"
        self.created_at = "2026-08-01T00:10:00+00:00"
        self.paid_at = "2026-08-03T09:00:00+00:00"
        self.method = "directdebit"
        self.metadata = metadata
        self.sequence_type = "recurring"
        self.customer_id = customer_id
        self.mandate_id = mandate_id
        self.subscription_id = subscription_id
        self.refunds = SimpleNamespace(list=lambda: {"_embedded": {"refunds": list(refunds)}})
        self.chargebacks = SimpleNamespace(list=lambda: [])


class _FakeClient:
    def __init__(self, payment):
        self.payments = SimpleNamespace(get=lambda pid: payment)

    def set_api_key(self, _key):
        return None


class _UnreachableClient:
    """Mollie is down: every payments.get raises, as the SDK does on an outage.

    Faked at the SDK boundary rather than by patching
    ``_fetch_payment_from_mollie``, so the real normaliser is what converts the
    failure into MolliePaymentError and the real STEP 1 is what has to survive
    it.
    """

    def __init__(self, error_message="Mollie is unreachable"):
        self._error_message = error_message
        self.payments = SimpleNamespace(get=self._boom)

    def _boom(self, _payment_id):
        raise RequestError(self._error_message)

    def set_api_key(self, _key):
        return None


class TestRecurringChargeWebhookWiring(EnhancedTestCase):
    """The charge must book AND keep the refund discovery it falls through to."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._orig_company = frappe.db.get_single_value("Verenigingen Settings", "company")
        cls._orig_donation_account = frappe.db.get_single_value(
            "Verenigingen Settings", "unrestricted_donation_account"
        )
        cls._orig_ms_clearing = frappe.db.get_single_value("Mollie Settings", "mollie_clearing_account")
        cls._orig_ms_bank = frappe.db.get_single_value("Mollie Settings", "mollie_bank_account")
        # setUp forces test_mode=1; without capturing it here the flag leaks to
        # every co-tenant class in the same CI shard.
        cls._orig_ms_test_mode = frappe.db.get_single_value("Mollie Settings", "test_mode")

    @classmethod
    def tearDownClass(cls):
        frappe.db.set_single_value(
            "Verenigingen Settings", "unrestricted_donation_account", cls._orig_donation_account
        )
        frappe.db.set_single_value("Verenigingen Settings", "company", cls._orig_company)
        frappe.db.set_single_value("Mollie Settings", "mollie_clearing_account", cls._orig_ms_clearing)
        frappe.db.set_single_value("Mollie Settings", "mollie_bank_account", cls._orig_ms_bank)
        frappe.db.set_single_value("Mollie Settings", "test_mode", cls._orig_ms_test_mode)
        frappe.db.commit()
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
            MollieConfigurationService,
        )

        MollieConfigurationService.clear_cache()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        frappe.db.set_single_value("Verenigingen Settings", "company", COMPANY)
        clearing_account = self._setup_mollie_clearing_account()
        self._setup_mollie_bank_account(clearing_account)
        self._setup_donation_income_account()
        self._setup_mollie_settings(clearing_account)
        self.ensure_mode_of_payment("iDEAL")
        self.ensure_mode_of_payment("SEPA Direct Debit")
        # payment_id is UNIQUE on Donation, so a fixed literal left behind by an
        # interrupted run would make this class fail forever on that site. Every
        # Mollie id below carries a per-test suffix, and the subscription id does
        # too so the subscription fallback cannot join to another test's origin.
        self.tag = frappe.generate_hash(length=8)
        self.subscription_id = f"sub_wire_{self.tag}"
        self.first_payment_id = f"tr_the_first_one_{self.tag}"
        self.customer_id = f"cst_wire_{self.tag}"
        self.mandate_id = f"mdt_wire_{self.tag}"

    # --- fixtures -------------------------------------------------------------------

    @shared_fixture
    def _setup_mollie_clearing_account(self):
        name = frappe.get_value(
            "Account", {"company": COMPANY, "account_name": "Mollie Clearing Subact Test"}, "name"
        )
        if name:
            return name
        parent = frappe.get_value(
            "Account", {"company": COMPANY, "account_type": "Bank", "is_group": 1}, "name"
        ) or frappe.get_value("Account", {"company": COMPANY, "is_group": 1}, "name")
        acct = frappe.new_doc("Account")
        acct.account_name = "Mollie Clearing Subact Test"
        acct.company = COMPANY
        acct.parent_account = parent
        acct.account_type = "Bank"
        acct.account_currency = frappe.get_value("Company", COMPANY, "default_currency")
        acct.insert(ignore_permissions=True)
        return acct.name

    @shared_fixture
    def _setup_mollie_bank_account(self, gl_account):
        existing = frappe.get_value("Bank Account", {"account": gl_account}, "name")
        if existing:
            return existing
        bank_name = frappe.get_value("Bank", {}, "name")
        if not bank_name:
            bank = frappe.new_doc("Bank")
            bank.bank_name = "Subact Test Bank"
            bank.insert(ignore_permissions=True)
            bank_name = bank.name
        ba = frappe.new_doc("Bank Account")
        ba.account_name = "Mollie Subact Test"
        ba.bank = bank_name
        ba.account = gl_account
        ba.company = COMPANY
        ba.is_company_account = 1
        ba.insert(ignore_permissions=True)
        return ba.name

    @shared_fixture
    def _setup_donation_income_account(self):
        name = frappe.get_value(
            "Account", {"company": COMPANY, "account_name": "Donation Income Subact Test"}, "name"
        )
        if not name:
            parent = frappe.get_value(
                "Account", {"company": COMPANY, "root_type": "Income", "is_group": 1}, "name"
            )
            acct = frappe.new_doc("Account")
            acct.account_name = "Donation Income Subact Test"
            acct.company = COMPANY
            acct.parent_account = parent
            acct.account_type = "Income Account"
            acct.account_currency = frappe.get_value("Company", COMPANY, "default_currency")
            acct.insert(ignore_permissions=True)
            name = acct.name
        frappe.db.set_single_value("Verenigingen Settings", "unrestricted_donation_account", name)
        return name

    def _setup_mollie_settings(self, clearing_account):
        frappe.db.set_single_value("Mollie Settings", "mollie_clearing_account", clearing_account)
        frappe.db.set_single_value("Mollie Settings", "mollie_bank_account", clearing_account)
        frappe.db.set_single_value("Mollie Settings", "test_mode", 1)
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
            MollieConfigurationService,
        )

        MollieConfigurationService.clear_cache()

    def _setup_donor(self):
        # self.factory.create_test_donor() does not exist on EnhancedTestCase's
        # factory (EnhancedTestDataFactory); build the donor the way the classes
        # above and test_donation_subscription_activation.py do.
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Wire Donor {frappe.generate_hash(length=6)}"
        donor.donor_email = f"wire.{frappe.generate_hash(length=6)}@example.org"
        donor.donor_type = "Individual"
        donor.preferred_communication_method = "Email"
        donor.flags.ignore_validate = True
        donor.insert(ignore_permissions=True)
        self.track_test_record("Donor", donor.name)
        return donor.name

    def _setup_origin(self):
        origin = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": self._setup_donor(),
                "company": COMPANY,
                "donation_date": "2026-07-01",
                "amount": 25,
                "mode_of_payment": "iDEAL",
                "status": "Recurring",
                "paid": 1,
                "payment_id": self.first_payment_id,
                "mollie_subscription_id": self.subscription_id,
                "mollie_customer_id": self.customer_id,
                "recurring_frequency": "Monthly",
            }
        ).insert()
        self.track_test_record("Donation", origin.name)
        return origin

    def _charge(self, payment_id, origin_name, subscription_id=None, refunds=()):
        return _FakeRecurringPayment(
            payment_id,
            origin_name,
            subscription_id or self.subscription_id,
            self.first_payment_id,
            self.customer_id,
            self.mandate_id,
            refunds=refunds,
        )

    def _deliver(self, payment):
        """Drive the real webhook service with Mollie faked at the HTTP boundary."""
        return self._deliver_with_client(_FakeClient(payment), payment["id"])

    def _deliver_with_client(self, client, payment_id):
        with patch(
            "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings"
            ".MollieSettings.get_mollie_client",
            return_value=client,
        ), patch(
            "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings"
            ".MollieSettings.get_api_key",
            return_value="test_dummy_key_for_tests",
        ), patch("mollie.api.client.Client", return_value=client), patch(
            "verenigingen.verenigingen_payments.mollie.core.client.MollieClient.sdk_client",
            new_callable=lambda: property(lambda self: client),
        ):
            with self.set_user("Administrator"):
                return UnifiedWebhookWrapperService().process_payment_webhook(payment_id, {})

    # --- tests ------------------------------------------------------------------------

    def test_an_unreachable_mollie_keeps_the_503_degradation(self):
        """The charge fetch must not pre-empt STEP 1's designed degradation.

        The fetch feeding ensure_donation_for_recurring_charge is UNCONDITIONAL
        -- its argument is evaluated before the service can decline -- so it
        runs on every donation / unknown / classification-failed webhook, not
        only on charges. Letting MolliePaymentError escape it therefore turned
        the whole webhook's Mollie-outage behaviour from `service_unavailable`
        + HTTP 503 + Retry-After (webhook_wrapper_service_unified.py's block
        labelled "CRITICAL FIX") into a bare 500 with a generic message, for
        every payment. Mollie backs off on a 503; a 500 it just retries.

        This is the sibling invariants module's defect class 5, "unconditional
        network calls on paths that do not need them", one level above where
        TestFullyProcessedPathDoesNotFetch guards.
        """
        payment_id = f"tr_outage_{self.tag}"
        result = self._deliver_with_client(_UnreachableClient(), payment_id)

        self.assertEqual(
            result["status"],
            "service_unavailable",
            f"the Mollie outage must reach STEP 1's 503 branch, not the outer handler: {result}",
        )
        self.assertEqual(frappe.local.response.http_status_code, 503)
        self.assertEqual(frappe.local.response["Retry-After"], "60")

    def test_a_recurring_charge_books_end_to_end(self):
        origin = self._setup_origin()
        charge_payment_id = f"tr_wire_1_{self.tag}"
        result = self._deliver(self._charge(charge_payment_id, origin.name))

        self.assertEqual(result["status"], "success", result.get("message"))
        charge_name = frappe.db.get_value("Donation", {"payment_id": charge_payment_id}, "name")
        self.assertTrue(charge_name, "the charge produced no Donation")
        charge = frappe.get_doc("Donation", charge_name)
        self.assertEqual(charge.recurring_origin_donation, origin.name)
        self.assertTrue(charge.journal_entry, "the charge produced no Journal Entry")

    def test_the_charge_branch_does_not_skip_the_refund_check(self):
        """The regression this task exists to prevent.

        check_payment_processing_state is the ONLY discovery of pending refunds
        and chargebacks on this webhook. Returning from the charge branch would
        strand every refund of every recurring charge. What is asserted is that
        the refund was SEEN -- the refund id has to come back out of the state
        object -- not merely that the manager was called: the latter is a claim
        about the call, and this task is about what the call discovers.
        """
        origin = self._setup_origin()
        refund_id = f"re_wire_{self.tag}"
        payment = self._charge(
            f"tr_wire_2_{self.tag}",
            origin.name,
            refunds=[
                {
                    "id": refund_id,
                    "status": "refunded",
                    "amount": {"value": "25.00", "currency": "EUR"},
                    "createdAt": "2026-08-05T09:00:00+00:00",
                }
            ],
        )

        seen = {}
        real_check = UnifiedIdempotencyManager().check_payment_processing_state

        def _spy(payment_id, **kwargs):
            state = real_check(payment_id, **kwargs)
            seen["pending_refunds"] = list(state.pending_refunds)
            return state

        with patch.object(
            UnifiedIdempotencyManager,
            "check_payment_processing_state",
            side_effect=lambda payment_id, **kw: _spy(payment_id, **kw),
            autospec=False,
        ):
            self._deliver(payment)

        self.assertIn("pending_refunds", seen, "control never reached the refund/chargeback discovery")
        self.assertIn(
            refund_id,
            [r.get("refund_id") for r in seen["pending_refunds"]],
            "the charge's refund was never discovered -- an early return would strand it",
        )

    def test_an_unattributable_charge_returns_an_error_so_mollie_retries(self):
        # No origin donation exists for this subscription.
        orphan_subscription = f"sub_orphan_{self.tag}"
        # severity="error" makes MollieAuditLogger mirror the row into Error Log.
        self.expectErrorLog("recurring_charge_origin_missing")
        result = self._deliver(
            self._charge(
                f"tr_wire_3_{self.tag}",
                "Assoc-Dnt-nope",
                subscription_id=orphan_subscription,
            )
        )
        self.assertEqual(result["status"], "error")
        # The EXACT message, not a substring. Deleting the `except
        # RecurringChargeOriginMissing` clause lets the outer handler produce
        # "Webhook processing failed: No donation found for Mollie subscription
        # sub_orphan_...", which satisfies both a status check and a substring
        # check -- so a looser assertion here would pass through the removal of
        # the very clause this test exists to pin.
        self.assertEqual(
            result["message"],
            f"No donation found for Mollie subscription {orphan_subscription}",
        )

    def test_a_first_payment_is_untouched_by_the_new_branch(self):
        """Control: the sequence_type guard, and nothing else, must stop this.

        Arranged so that guard is the ONLY thing standing between the payment
        and a spurious charge donation:

        - the id is NOT any Donation's payment_id, so the service's
          `_donation_for_charge()` short-circuit cannot return early on its
          behalf (the earlier version of this test reused the origin's own
          payment_id and was defeated by exactly that);
        - `subscriptionId` is left SET, so the `if not subscription_id` guard
          cannot cover for a deleted `sequence_type` guard either;
        - `metadata.donation_id` still names the origin, so if the branch did
          run it would find an origin and successfully book a charge.

        Delete `if read_payment_field(...) != "recurring": return None` from the
        service and this goes red on both assertions.
        """
        origin = self._setup_origin()
        unbooked = f"tr_first_unbooked_{self.tag}"
        first = self._charge(unbooked, origin.name)
        first["sequenceType"] = "first"
        first.sequence_type = "first"

        result = self._deliver(first)

        # The specific outcome, not merely "not an error": the payment falls
        # through to the pre-existing donation path, which looks up Donation by
        # payment_id, finds none, and says so. That message belongs to the #346
        # path -- the new branch never produces it. `assertNotEqual(status,
        # "error")` was satisfied by "skipped" too, and so said very little.
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], f"No donation found for payment {unbooked}")
        self.assertFalse(
            frappe.db.exists("Donation", {"recurring_origin_donation": origin.name}),
            "a first payment must not spawn a charge donation",
        )

    # --- a half-booking must not report success --------------------------------------

    def test_a_journal_entry_failure_is_not_reported_as_success(self):
        """A Bank Transaction with no Journal Entry is half a booking.

        _create_donation_financial_entries returns a TRUTHY dict for it, so the
        `if not financial_result` guard lets it through. Mollie would get a 200
        and never re-deliver, leaving the donor debited against half an entry.
        """
        origin = self._setup_origin()
        partial = {
            "bank_transaction_name": "BT-partial",
            "journal_entry_name": None,
            "partial_success": True,
        }
        with patch.object(
            UnifiedWebhookWrapperService, "_create_donation_financial_entries", return_value=partial
        ):
            result = self._deliver(self._charge(f"tr_wire_4_{self.tag}", origin.name))

        self.assertEqual(result["status"], "error", "a missing Journal Entry must fail the webhook")
        self.assertIn("journal", result["message"].lower())

    def test_a_complete_booking_is_still_reported_as_success(self):
        """Control. Without it the assertion above passes even if every webhook
        started returning an error."""
        origin = self._setup_origin()
        result = self._deliver(self._charge(f"tr_wire_5_{self.tag}", origin.name))
        self.assertEqual(result["status"], "success", result.get("message"))

    def test_redelivery_after_a_journal_entry_failure_completes_the_booking(self):
        """The other half of the guarantee: the error must be recoverable.

        Failing the first delivery is only correct if the retry finishes the job.
        The charge donation already exists by then, so this exercises the path
        that must resume rather than create -- and asserts on the Journal Entry,
        not on the status, because 'no second donation' and 'the ledger is whole'
        are different claims.
        """
        origin = self._setup_origin()
        payment_id = f"tr_wire_6_{self.tag}"
        payment = self._charge(payment_id, origin.name)
        partial = {
            "bank_transaction_name": "BT-partial",
            "journal_entry_name": None,
            "partial_success": True,
        }

        with patch.object(
            UnifiedWebhookWrapperService, "_create_donation_financial_entries", return_value=partial
        ):
            self._deliver(payment)

        charge_name = frappe.db.get_value("Donation", {"payment_id": payment_id}, "name")
        self.assertTrue(charge_name)
        self.assertFalse(frappe.db.get_value("Donation", charge_name, "journal_entry"))

        self._deliver(payment)  # Mollie re-delivers; nothing is faked this time

        self.assertEqual(
            frappe.db.count("Donation", {"payment_id": payment_id}),
            1,
            "the retry created a second donation",
        )
        self.assertTrue(
            frappe.db.get_value("Donation", charge_name, "journal_entry"),
            "the retry did not complete the Journal Entry",
        )


class TestDonorPortalRecurringList(EnhancedTestCase):
    """Keep charge donations out of the donor portal's subscription list.

    Charge donations carry status='Recurring' too (they are what STEP 3/4 of
    #345 books), so without a discriminator between an origin donation and the
    charges it spawned, the donor portal would accumulate one identical row --
    each with its own Cancel button -- per charge, and make two live Mollie
    calls per row for what is a single subscription.

    get_donation_summary's active_recurring count has the identical defect:
    it also iterates every status='Recurring' row and would show "4 Active
    Recurring" directly above a list (fixed by the same change) showing only
    one subscription card. Both are covered here.
    """

    def setUp(self):
        super().setUp()
        # "iDEAL" and "SEPA Direct Debit" are not app fixtures; Donation.mode_of_payment
        # is a required Link, so a site without them fails these inserts outright.
        self.ensure_mode_of_payment("iDEAL")
        self.ensure_mode_of_payment("SEPA Direct Debit")
        # payment_id is UNIQUE on Donation; every id below carries a per-test
        # suffix so a leftover row from an interrupted run cannot collide.
        self.tag = frappe.generate_hash(length=8)

    # --- fixtures -------------------------------------------------------------------

    def _setup_donor(self, email):
        # self.factory.create_test_donor() does not exist on EnhancedTestCase's
        # factory (EnhancedTestDataFactory); build the donor the way the classes
        # above and test_donation_subscription_activation.py do.
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Portal Donor {frappe.generate_hash(length=6)}"
        donor.donor_email = email
        donor.donor_type = "Individual"
        donor.preferred_communication_method = "Email"
        donor.flags.ignore_validate = True
        donor.insert(ignore_permissions=True)
        self.track_test_record("Donor", donor.name)
        return donor.name

    def _setup_member(self):
        email = f"portalrec.{frappe.generate_hash(length=8)}@example.com"
        member = self.create_test_member(first_name="Portal", last_name="Recurring", email=email)
        # The factory may uniquify the email for isolation; read the stored
        # value back so the donor built below matches what get_recurring_donations
        # and get_donation_summary query by (donor_email == member.email).
        return frappe.get_doc("Member", member.name)

    def _setup_origin_and_charges(self, member_email, charge_count=3):
        """One subscription: an origin donation plus `charge_count` charges."""
        donor_name = self._setup_donor(member_email)
        origin = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": donor_name,
                "donor_email": member_email,
                "donation_date": "2026-06-01",
                "amount": 25,
                "mode_of_payment": "iDEAL",
                "status": "Recurring",
                "paid": 1,
                "payment_id": f"tr_portal_origin_{self.tag}",
                "mollie_subscription_id": f"sub_portal_{self.tag}",
            }
        ).insert()
        self.track_test_record("Donation", origin.name)
        for i in range(charge_count):
            charge = frappe.get_doc(
                {
                    "doctype": "Donation",
                    "donor": donor_name,
                    "donor_email": member_email,
                    "donation_date": f"2026-{7 + i:02d}-01",
                    "amount": 25,
                    "mode_of_payment": "SEPA Direct Debit",
                    "status": "Recurring",
                    "paid": 1,
                    "payment_id": f"tr_portal_charge_{i}_{self.tag}",
                    "mollie_subscription_id": f"sub_portal_{self.tag}",
                    "recurring_origin_donation": origin.name,
                }
            ).insert()
            self.track_test_record("Donation", charge.name)
        return origin

    # --- tests ------------------------------------------------------------------------

    def test_three_charges_show_as_one_recurring_donation(self):
        from verenigingen.templates.pages.manage_donations import get_recurring_donations

        member = self._setup_member()
        origin = self._setup_origin_and_charges(member.email)

        # get_recurring_donations calls Mollie per row (directly, and again via
        # get_recurring_donation_state); patch that boundary so this does not
        # depend on the gateway.
        with patch(
            "verenigingen.templates.pages.manage_donations.get_mollie_subscription_info",
            return_value={
                "subscription_status": "active",
                "next_payment_date": None,
                "cancelled_date": None,
            },
        ):
            rows = get_recurring_donations(member.name)

        self.assertEqual(
            [r["name"] for r in rows],
            [origin.name],
            "the portal must show the subscription once, not once per charge",
        )

    def test_summary_counts_the_subscription_once_too(self):
        from verenigingen.templates.pages.manage_donations import get_donation_summary

        member = self._setup_member()
        self._setup_origin_and_charges(member.email)

        with patch(
            "verenigingen.templates.pages.manage_donations.get_mollie_subscription_info",
            return_value={
                "subscription_status": "active",
                "next_payment_date": None,
                "cancelled_date": None,
            },
        ):
            summary = get_donation_summary(member.name)

        self.assertEqual(
            summary["active_recurring"],
            1,
            "one subscription, not one row per charge",
        )
        # Every charge is still a real gift: total_donations/total_donated
        # must count all four rows (origin + 3 charges), not collapse them --
        # this discriminator is only for the "how many subscriptions" count.
        self.assertEqual(summary["total_donations"], 4)
        self.assertEqual(summary["total_donated"], 100.0)
