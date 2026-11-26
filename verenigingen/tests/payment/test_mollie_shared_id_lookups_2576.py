"""
#2576: siblings of #1497. Lookups that resolve a Member by a Mollie customer/subscription id
must refuse a shared id instead of acting on one arbitrary row.

Reachability (traced on develop, not assumed):
* ``MemberPaymentMatcher`` (customer id): the webhook's dues booking
  (``process_dues_payment`` -> ``find_member_for_payment``) books to whoever the matcher returns.
  A payment classified DUES through a UNIQUE subscription id whose customer id is shared reaches
  it, so the classifier's refusal (#1497) does not cover it. Bulk/admin/debug callers are read-only.
* ``get_member_by_subscription_id``: whitelisted ``cancel_mollie_subscription_by_id`` and
  ``update_mollie_subscription_amount`` act on the returned Member.
* ``validate_csv_members``: whitelisted admin CSV check validated against the last row of a shared id.
Not fixed (no production caller; deleted in #2676): ``payment_webhook.find_member_for_payment``,
``get_member_by_customer_id``.

Probe shortcut, stated: shared ids are put on Members with ``db.set_value`` (as the #1497 module
does); the real writer that duplicates them is covered there.

Run with:
    PYTHONPATH=<worktree> scripts/testing/run_without_credentials.sh test_site_5 \\
        verenigingen.tests.payment.test_mollie_shared_id_lookups_2576
"""

from types import SimpleNamespace

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.payment.test_mollie_classification_ambiguous_party_1497 import (
    AmbiguousPartyBase,
    _purge,
)
from verenigingen.verenigingen_payments.mollie.domain.payment_classification import (
    MEMBER_LOG_TITLE,
    PaymentClassifier,
    PaymentType,
)
from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
    DuesPaymentProcessor,
)
from verenigingen.verenigingen_payments.mollie.services.payment_type_router import PaymentTypeRouter
from verenigingen.verenigingen_payments.mollie.utils.common_helpers import get_member_by_subscription_id
from verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher import (
    MemberPaymentMatcher,
    get_member_payment_matcher,
    reset_member_payment_matcher,
)

SUB_LOG_TITLE = "Mollie subscription id shared by several Members"


class SharedIdBase(AmbiguousPartyBase):
    def setUp(self):
        super().setUp()
        self.expectErrorLog(SUB_LOG_TITLE)
        # The module-level matcher caches Members by (count, max(modified)); set_value with
        # update_modified=False is invisible to that fingerprint.
        reset_member_payment_matcher()
        self.addCleanup(reset_member_payment_matcher)
        self.addCleanup(lambda: frappe.db.delete("Error Log", {"method": SUB_LOG_TITLE}))

    def _act_as_admin(self):
        """The factory's admin user (Verenigingen Administrator role AND profile: the CRITICAL gate
        wants the profile), not the Administrator account that bypasses permission checks."""
        admin = self.ensure_test_admin_user()
        frappe.set_user(admin.name)
        self.addCleanup(frappe.set_user, "Administrator")

    def _third_member(self, field, prefix):
        value = f"{prefix}_{frappe.generate_hash(length=10)}"
        third = self.create_test_member(
            first_name="Amb3",
            last_name="Member",
            email=f"amb2576.m3.{frappe.generate_hash(length=6)}@example.com",
        )
        self._set("Member", third.name, field, value)
        return third, value

    def _sub_unique_customer_shared(self):
        """Member 0 alone holds the subscription id; both Members hold the customer id."""
        cust = self._share("Member", "mollie_customer_id", self.members)
        sub = f"sub_{frappe.generate_hash(length=10)}"
        self._set("Member", self.members[0].name, "mollie_subscription_id", sub)
        return cust, sub


class TestMatcherRefusesASharedCustomerId(SharedIdBase):
    def test_a_shared_customer_id_matches_nobody(self):
        cust = self._share("Member", "mollie_customer_id", self.members)
        found = MemberPaymentMatcher().find_member_for_payment(self.payment(customer_id=cust))
        self.assertIsNone(found, "the matcher picked one of the Members sharing the id")
        rows = self._error_rows(MEMBER_LOG_TITLE)
        self.assertEqual(len(rows), 1)
        for member in self.members:
            self.assertIn(member.name, rows[0])
        self.assertEqual(self._alert_events(), [], "a read-only caller raised the staff alert")

    def test_the_description_does_not_rescue_a_shared_customer_id(self):
        cust = self._share("Member", "mollie_customer_id", self.members)
        description = f"Contributie {self.members[0].name}"
        self.assertTrue(
            MemberPaymentMatcher.MEMBER_ID_PATTERN.search(description),
            "fixture precondition: the description must carry a parsable member id",
        )
        found = MemberPaymentMatcher().find_member_for_payment(
            self.payment(customer_id=cust, description=description)
        )
        self.assertIsNone(found)

    def test_a_unique_customer_id_still_resolves_beside_a_shared_one(self):
        self._share("Member", "mollie_customer_id", self.members)
        third, unique = self._third_member("mollie_customer_id", "cst")
        found = MemberPaymentMatcher().find_member_for_payment(self.payment(customer_id=unique))
        self.assertEqual(found["name"], third.name)
        self.assertEqual(self._error_rows(MEMBER_LOG_TITLE), [])

    def test_a_shared_id_is_still_known_but_not_matched(self):
        cust = self._share("Member", "mollie_customer_id", self.members)
        matcher = MemberPaymentMatcher()
        self.assertTrue(matcher.is_customer_id_known(cust))
        self.assertIsNone(matcher.find_member_name_for_payment(self.payment(customer_id=cust)))


class TestAlertOnlyOnADeliveryPath(SharedIdBase):
    def test_alert_staff_raises_one_alert_across_two_deliveries(self):
        self._staff_recipient()
        cust = self._share("Member", "mollie_customer_id", self.members)
        for _ in range(2):
            self.assertIsNone(
                MemberPaymentMatcher().find_member_for_payment(self.payment(customer_id=cust), alert_staff=True)
            )
        events = self._alert_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(len(self._error_rows(MEMBER_LOG_TITLE)), 1)

    def test_dues_processor_is_quiet_by_default_and_alerts_when_asked(self):
        self._staff_recipient()
        cust = self._share("Member", "mollie_customer_id", self.members)
        payment = self.payment(customer_id=cust)
        self.assertIsNone(DuesPaymentProcessor.find_member_for_payment(None, payment))
        self.assertEqual(self._alert_events(), [])
        self.assertIsNone(DuesPaymentProcessor.find_member_for_payment(None, payment, alert_staff=True))
        self.assertEqual(len(self._alert_events()), 1)


class _DuesSeamRouter:
    """The real classify/route code and the real dues processor; the Mollie fetch is the only seam."""

    def __init__(self, payment):
        self._payment = payment
        self.classifier = PaymentClassifier()
        self.dues_processor = DuesPaymentProcessor()

    def fetch_payment(self, payment_id):
        return self._payment

    classify_payment = PaymentTypeRouter.classify_payment
    route_payment = PaymentTypeRouter.route_payment


class TestTheDuesBookingPathRefuses(SharedIdBase):
    """A payment the classifier calls DUES through its unique subscription id must not be booked to
    whichever Member the shared customer id happens to resolve to."""

    def _paid(self, **kwargs):
        return self.payment(status="paid", amount={"value": "10.00", "currency": "EUR"}, **kwargs)

    def test_the_fixture_reaches_the_matcher_through_a_dues_classification(self):
        cust, sub = self._sub_unique_customer_shared()
        result = PaymentClassifier().classify(self._paid(customer_id=cust, subscription_id=sub))
        self.assertEqual(result.payment_type, PaymentType.DUES)
        self.assertEqual(result.member_id, self.members[0].name)

    def test_process_dues_payment_books_nothing_for_a_shared_customer_id(self):
        cust, sub = self._sub_unique_customer_shared()
        payment = self._paid(customer_id=cust, subscription_id=sub)
        result = DuesPaymentProcessor().process_dues_payment(self.payment_id, payment)
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["member"])
        self.assertIsNone(result["payment_entry"])
        self.assertIsNone(result["bank_transaction"])
        self.assertEqual(len(self._error_rows(MEMBER_LOG_TITLE)), 1)
        self.assertEqual(self._alert_events(), [])

    def test_route_payment_threads_alert_staff_to_the_member_match(self):
        self._staff_recipient()
        cust, sub = self._sub_unique_customer_shared()
        payment = self._paid(customer_id=cust, subscription_id=sub)
        quiet = _DuesSeamRouter(payment).route_payment(self.payment_id, payment)
        self.assertEqual(quiet["status"], "error")
        self.assertEqual(self._alert_events(), [], "route_payment alerted without being asked")
        loud = _DuesSeamRouter(payment).route_payment(self.payment_id, payment, alert_staff=True)
        self.assertEqual(loud["status"], "error")
        self.assertEqual(len(self._alert_events()), 1)

    def test_a_unique_customer_id_still_resolves_for_dues(self):
        third, unique = self._third_member("mollie_customer_id", "cst")
        found = DuesPaymentProcessor.find_member_for_payment(None, self._paid(customer_id=unique))
        self.assertEqual(found, third.name)


class TestSubscriptionHelperRefusesASharedId(SharedIdBase):
    def test_a_shared_subscription_id_raises(self):
        sub = self._share("Member", "mollie_subscription_id", self.members)
        with self.assertRaises(frappe.ValidationError) as ctx:
            get_member_by_subscription_id(sub, fields=["name"])
        self.assertIn("More than one member", str(ctx.exception))
        for member in self.members:
            self.assertNotIn(member.name, str(ctx.exception), "the caller's message names other members")
        rows = frappe.get_all(
            "Error Log", filters={"method": SUB_LOG_TITLE, "error": ["like", f"%{sub}%"]}, pluck="error"
        )
        self.assertEqual(len(rows), 1)
        for member in self.members:
            self.assertIn(member.name, rows[0])

    def test_a_unique_subscription_id_still_resolves_with_the_requested_fields(self):
        self._share("Member", "mollie_subscription_id", self.members)
        third, unique = self._third_member("mollie_subscription_id", "sub")
        self._set("Member", third.name, "mollie_customer_id", "cst_ctl2576abc")
        found = get_member_by_subscription_id(unique, fields=["name", "mollie_customer_id"])
        self.assertEqual(found["name"], third.name)
        self.assertEqual(found["mollie_customer_id"], "cst_ctl2576abc")

    def test_an_unknown_subscription_id_is_still_none(self):
        self.assertIsNone(get_member_by_subscription_id(f"sub_{frappe.generate_hash(length=10)}"))

    def test_cancel_by_subscription_id_refuses_and_changes_nothing(self):
        from verenigingen.verenigingen_payments.utils.payment_gateways import (
            cancel_mollie_subscription_by_id,
        )

        sub = self._share("Member", "mollie_subscription_id", self.members)
        before = [frappe.db.get_value("Member", m.name, "subscription_status") for m in self.members]
        self._act_as_admin()
        result = cancel_mollie_subscription_by_id(sub)
        self.assertFalse(result.get("success", False), result)
        self.assertIn("More than one member", str(result))
        after = [frappe.db.get_value("Member", m.name, "subscription_status") for m in self.members]
        self.assertEqual(before, after)
        frappe.local.message_log = []


class TestBulkPaymentCsvValidation(SharedIdBase):
    def _validate(self, customer_id):
        from verenigingen.templates.pages.mollie_bulk_payment_creation import validate_csv_members

        self._act_as_admin()
        csv_content = f"customer_id,amount,charge_date\n{customer_id},10.00,{add_days(today(), 5)}\n"
        return validate_csv_members(csv_content)

    def test_a_shared_customer_id_row_is_an_error_naming_no_member_status(self):
        cust = self._share("Member", "mollie_customer_id", self.members)
        result = self._validate(cust)
        (row,) = result["results"]
        self.assertEqual(row["status"], "error")
        self.assertIsNone(row["member_id"], "the row was validated against one of the Members")
        self.assertTrue(any("more than one member" in issue for issue in row["issues"]), row["issues"])

    def test_a_unique_customer_id_row_still_resolves_beside_a_shared_one(self):
        self._share("Member", "mollie_customer_id", self.members)
        third, unique = self._third_member("mollie_customer_id", "cst")
        result = self._validate(unique)
        (row,) = result["results"]
        self.assertEqual(row["member_id"], third.name)
        self.assertFalse(any("more than one member" in issue for issue in row["issues"]), row["issues"])


class TestSubscriptionWebhookRefusesASharedId(SharedIdBase):
    """``_find_member_for_subscription`` feeds a live write (db_set of subscription_status) from the
    whitelisted subscription webhook, a delivery path: the staff alert is raised.

    Probe shortcut, stated: the Customer link and the subscription id are set with ``db.set_value``."""

    def setUp(self):
        super().setUp()
        self.sub = f"sub_{frappe.generate_hash(length=10)}"

    def _insert_customer_2576(self):
        return frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": f"TEST 2576 {frappe.generate_hash(length=8)}",
                "customer_type": "Individual",
                "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
            }
        ).insert(ignore_permissions=True)

    def _customer(self, member):
        customer = self._insert_customer_2576()
        frappe.db.set_value(
            "Customer",
            customer.name,
            {"custom_mollie_subscription_id": self.sub, "custom_mollie_customer_id": f"cst_{customer.name[-6:]}"},
        )
        frappe.db.set_value("Member", member.name, "customer", customer.name)
        return customer

    def _find(self):
        from verenigingen.verenigingen_payments.utils.payment_gateways import _find_member_for_subscription

        return _find_member_for_subscription(self.sub, self.payment_id)

    def assertRefused(self, result):
        self.assertEqual(result, (None, None, None), "the webhook picked one of the Members")
        rows = [r for r in self._error_rows(MEMBER_LOG_TITLE)]
        self.assertEqual(len(rows), 1)
        for member in self.members:
            self.assertIn(member.name, rows[0])
        self.assertEqual(len(self._alert_events()), 1, "a delivery path must raise the staff alert once")

    def test_two_customers_carrying_the_subscription_id_for_different_members(self):
        self._staff_recipient()
        for member in self.members:
            self._customer(member)
        self.assertRefused(self._find())

    def test_one_customer_with_two_members(self):
        self._staff_recipient()
        customer = self._customer(self.members[0])
        frappe.db.set_value("Member", self.members[1].name, "customer", customer.name)
        self.assertRefused(self._find())

    def test_a_redelivery_does_not_alert_or_log_again(self):
        self._staff_recipient()
        for member in self.members:
            self._customer(member)
        self._find()
        self.assertEqual(self._find(), (None, None, None))
        self.assertEqual(len(self._error_rows(MEMBER_LOG_TITLE)), 1)
        self.assertEqual(len(self._alert_events()), 1)

    def test_one_customer_one_member_still_resolves(self):
        customer = self._customer(self.members[0])
        found = self._find()
        self.assertEqual(found, (self.members[0].name, customer.name, f"cst_{customer.name[-6:]}"))
        self.assertEqual(self._error_rows(MEMBER_LOG_TITLE), [])

    def test_two_customers_of_the_same_member_still_resolve(self):
        """Control with a real second row: duplicate Customers of ONE Member are not ambiguous."""
        first = self._customer(self.members[0])
        second = self._insert_customer_2576()
        frappe.db.set_value("Customer", second.name, "custom_mollie_subscription_id", self.sub)
        frappe.db.set_value("Member", self.members[0].name, "customer", first.name)
        name, _customer_name, _cid = self._find()
        self.assertEqual(name, self.members[0].name)
        self.assertEqual(self._error_rows(MEMBER_LOG_TITLE), [])
