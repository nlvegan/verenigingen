"""
#2675 (maintainer ruling 2026-11-25, option a): a comma-separated ``mollie_customer_id`` list is
supported. Payment attribution AND the shared-id refusal work per individual id.

Surfaces covered: the single classifier (Member and Donor), the batch classifier, the
MemberPaymentMatcher, and the admin CSV check (``validate_csv_members``).

Probe shortcut, stated: lists are put on rows with ``db.set_value`` (as the #1497/#2576 modules
do); no writer in the app is driven here.

Run with:
    PYTHONPATH=<worktree> scripts/testing/run_without_credentials.sh test_site_8 \\
        verenigingen.tests.payment.test_mollie_multi_id_customer_lists_2675
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.payment.test_mollie_classification_ambiguous_party_1497 import _purge
from verenigingen.tests.payment.test_mollie_shared_id_lookups_2576 import SharedIdBase
from verenigingen.verenigingen_payments.mollie.domain.payment_classification import (
    MEMBER_LOG_TITLE,
    PaymentClassifier,
    PaymentType,
)
from verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher import (
    MemberPaymentMatcher,
)
from verenigingen.verenigingen_payments.utils.mollie_customer_id_list import (
    split_mollie_customer_ids,
)


class TestSplitHelper(SharedIdBase):
    def test_whitespace_empties_and_duplicates_are_normalised(self):
        self.assertEqual(split_mollie_customer_ids(" cst_a ,, cst_b,cst_a , "), ["cst_a", "cst_b"])
        self.assertEqual(split_mollie_customer_ids(None), [])
        self.assertEqual(split_mollie_customer_ids(""), [])
        self.assertEqual(split_mollie_customer_ids("cst_12"), ["cst_12"])


class MultiIdBase(SharedIdBase):
    def setUp(self):
        super().setUp()
        h = frappe.generate_hash(length=8)
        self.id_a, self.id_b, self.id_c = f"cst_a{h}", f"cst_b{h}", f"cst_c{h}"

    def _list_on(self, row, *ids, doctype="Member", sep=", "):
        self._set(doctype, row.name, "mollie_customer_id", sep.join(ids))


class TestAttributionPerId(MultiIdBase):
    def test_second_id_of_a_list_attributes_to_the_member(self):
        self._list_on(self.members[0], self.id_a, self.id_b)
        for cid in (self.id_a, self.id_b):
            result = PaymentClassifier().classify(self.payment(customer_id=cid))
            self.assertEqual(result.payment_type, PaymentType.DUES, cid)
            self.assertEqual(result.member_id, self.members[0].name, cid)

    def test_batch_classifier_matches_each_id_of_a_list(self):
        self._list_on(self.members[0], self.id_a, self.id_b, sep=" , ")
        payments = [
            self.payment(id=f"{self.payment_id}a", customer_id=self.id_a),
            self.payment(id=f"{self.payment_id}b", customer_id=self.id_b),
        ]
        self.addCleanup(_purge, [p.id for p in payments])
        results = PaymentClassifier().classify_batch(payments)
        self.assertEqual([r.member_id for r in results], [self.members[0].name] * 2)

    def test_donor_list_attributes_a_donation(self):
        self._list_on(self.donors[0], self.id_a, self.id_b, doctype="Donor")
        result = PaymentClassifier().classify(self.payment(customer_id=self.id_b))
        self.assertEqual(result.payment_type, PaymentType.DONATION)
        self.assertEqual(result.donor_id, self.donors[0].name)

    def test_matcher_resolves_each_id_of_a_list(self):
        self._list_on(self.members[0], self.id_a, self.id_b)
        matcher = MemberPaymentMatcher()
        for cid in (self.id_a, self.id_b):
            found = matcher.find_member_for_payment(self.payment(customer_id=cid))
            self.assertEqual(found["name"], self.members[0].name, cid)
            self.assertTrue(matcher.is_customer_id_known(cid))

    def test_csv_check_resolves_each_id_of_a_list(self):
        self._list_on(self.members[0], self.id_a, self.id_b)
        self._act_as_admin()
        from verenigingen.templates.pages.mollie_bulk_payment_creation import validate_csv_members

        csv_content = f"customer_id,amount,charge_date\n{self.id_b},10.00,{add_days(today(), 5)}\n"
        (row,) = validate_csv_members(csv_content)["results"]
        self.assertEqual(row["member_id"], self.members[0].name)


class TestSharedIdRefusalPerId(MultiIdBase):
    """Member 0 lists (a, b); Member 1 lists (b, c): b is shared, a and c are unique."""

    def setUp(self):
        super().setUp()
        self._list_on(self.members[0], self.id_a, self.id_b)
        self._list_on(self.members[1], self.id_b, self.id_c)

    def test_classifier_refuses_the_shared_id_and_names_both_members(self):
        result = PaymentClassifier().classify(self.payment(customer_id=self.id_b))
        self.assertEqual(result.payment_type, PaymentType.AMBIGUOUS)
        self.assertIsNone(result.member_id)
        (row,) = self._error_rows(MEMBER_LOG_TITLE)
        for member in self.members:
            self.assertIn(member.name, row)

    def test_batch_classifier_refuses_the_shared_id(self):
        (result,) = PaymentClassifier().classify_batch([self.payment(customer_id=self.id_b)])
        self.assertEqual(result.payment_type, PaymentType.AMBIGUOUS)

    def test_unique_ids_of_the_same_lists_still_attribute(self):
        self.assertEqual(
            PaymentClassifier().classify(self.payment(customer_id=self.id_a)).member_id,
            self.members[0].name,
        )
        self.assertEqual(
            PaymentClassifier().classify(self.payment(customer_id=self.id_c)).member_id,
            self.members[1].name,
        )

    def test_matcher_refuses_the_shared_id_but_resolves_the_unique_ones(self):
        matcher = MemberPaymentMatcher()
        self.assertIsNone(matcher.find_member_for_payment(self.payment(customer_id=self.id_b)))
        self.assertTrue(matcher.is_customer_id_known(self.id_b))
        self.assertEqual(
            matcher.find_member_for_payment(self.payment(customer_id=self.id_c))["name"],
            self.members[1].name,
        )

    def test_csv_check_refuses_the_shared_id(self):
        self._act_as_admin()
        from verenigingen.templates.pages.mollie_bulk_payment_creation import validate_csv_members

        csv_content = f"customer_id,amount,charge_date\n{self.id_b},10.00,{add_days(today(), 5)}\n"
        (row,) = validate_csv_members(csv_content)["results"]
        self.assertEqual(row["status"], "error")
        self.assertIsNone(row["member_id"])


class TestControls(MultiIdBase):
    def test_a_single_id_still_works(self):
        self._set("Member", self.members[0].name, "mollie_customer_id", self.id_a)
        self.assertEqual(
            PaymentClassifier().classify(self.payment(customer_id=self.id_a)).member_id,
            self.members[0].name,
        )
        self.assertEqual(
            MemberPaymentMatcher().find_member_for_payment(self.payment(customer_id=self.id_a))["name"],
            self.members[0].name,
        )

    def test_a_substring_id_does_not_match_a_longer_id(self):
        longer = f"{self.id_a}9"
        self._list_on(self.members[0], longer, self.id_b)
        for payment_id in (self.id_a,):
            result = PaymentClassifier().classify(self.payment(customer_id=payment_id))
            self.assertNotEqual(result.member_id, self.members[0].name, "prefix id matched a longer id")
            (classified_in_bulk,) = PaymentClassifier().classify_batch([self.payment(customer_id=payment_id)])
            self.assertNotEqual(classified_in_bulk.member_id, self.members[0].name)
            self.assertIsNone(
                MemberPaymentMatcher().find_member_for_payment(self.payment(customer_id=payment_id))
            )
        # control: the longer id itself does match, so the fixture holds a real candidate
        self.assertEqual(
            PaymentClassifier().classify(self.payment(customer_id=longer)).member_id, self.members[0].name
        )

    def test_a_substring_of_the_list_text_does_not_match(self):
        self._list_on(self.members[0], self.id_a, self.id_b, sep=",")
        glued = f"{self.id_a},{self.id_b}"
        self.assertNotEqual(
            PaymentClassifier().classify(self.payment(customer_id=f"{self.id_a},")).member_id,
            self.members[0].name,
        )
        self.assertIsNotNone(glued)


class TestDuplicateAndCaseControls(MultiIdBase):
    def test_a_member_listing_the_same_id_twice_is_not_ambiguous(self):
        """One Member, "a, a": the id belongs to ONE Member, so it attributes (no-dedupe mutant: refused)."""
        self._list_on(self.members[0], self.id_a, self.id_a)
        single = PaymentClassifier().classify(self.payment(customer_id=self.id_a))
        self.assertEqual((single.payment_type, single.member_id), (PaymentType.DUES, self.members[0].name))
        (classified_in_bulk,) = PaymentClassifier().classify_batch([self.payment(customer_id=self.id_a)])
        self.assertEqual((classified_in_bulk.payment_type, classified_in_bulk.member_id), (PaymentType.DUES, self.members[0].name))
        found = MemberPaymentMatcher().find_member_for_payment(self.payment(customer_id=self.id_a))
        self.assertEqual(found["name"], self.members[0].name)
        self.assertEqual(self._error_rows(MEMBER_LOG_TITLE), [])

    def test_matching_is_case_sensitive(self):
        """Pinned: Mollie ids are case-sensitive. MariaDB's LIKE is not, so the per-token test decides."""
        self._list_on(self.members[0], self.id_a, self.id_b)
        upper = self.id_a.upper()
        self.assertNotEqual(upper, self.id_a)
        self.assertNotEqual(
            PaymentClassifier().classify(self.payment(customer_id=upper)).member_id, self.members[0].name
        )
        self.assertIsNone(MemberPaymentMatcher().find_member_for_payment(self.payment(customer_id=upper)))


class TestOtherReaders(MultiIdBase):
    """F1 (review round 2): the remaining readers that compared the whole field."""

    def _sub(self, **kw):
        return {
            "id": f"sub_{frappe.generate_hash(length=10)}",
            "customerId": self.id_b,
            "status": "active",
            "amount": {"value": "10.00", "currency": "EUR"},
            "interval": "1 year",
            "description": "x",
            **kw,
        }

    def test_reconciliation_gathers_subscriptions_of_every_listed_id(self):
        from verenigingen.services.payment.mollie_reconciliation_service import (
            MollieReconciliationService,
        )

        sub = self._sub()
        member = {
            "name": self.members[0].name,
            "full_name": "x",
            "status": "Active",
            "subscription_status": "active",
            "mollie_customer_id": f"{self.id_a}, {self.id_b}",
            "mollie_subscription_id": sub["id"],
        }
        service = object.__new__(MollieReconciliationService)
        (row,) = service.build_member_reconciliation([member], [{**sub, "customerId": self.id_b}])
        self.assertEqual([s["subscription_id"] for s in row["active_subscriptions"]], [sub["id"]])

    def _audit(self):
        from verenigingen.utils.admin_utilities.subscription_audit import SubscriptionAudit

        audit = object.__new__(SubscriptionAudit)  # __init__ builds a real Mollie client
        audit.issues = {
            k: []
            for k in (
                "subscription_no_member_match",
                "subscription_customer_no_member",
                "subscription_for_deleted_member",
                "subscription_status_mismatch",
            )
        }
        return audit

    def test_audit_finds_a_member_by_a_listed_customer_id(self):
        self._list_on(self.members[0], self.id_a, self.id_b)
        audit = self._audit()
        sub = self._sub()
        audit._cross_reference_with_members([sub])
        self.assertEqual(audit.issues["subscription_no_member_match"], [])
        (issue,) = audit.issues["subscription_customer_no_member"]
        self.assertEqual(issue["member_id"], self.members[0].name)

    def test_audit_customer_id_mismatch_respects_the_list(self):
        self._list_on(self.members[0], self.id_a, self.id_b)
        sub = self._sub()
        self._set("Member", self.members[0].name, "mollie_subscription_id", sub["id"])
        self._set("Member", self.members[0].name, "subscription_status", "active")
        audit = self._audit()
        audit._cross_reference_with_members([sub, {**self._sub(), "id": sub["id"], "customerId": self.id_c}])
        mismatches = [
            i for i in audit.issues["subscription_status_mismatch"] if i.get("issue") == "customer_id_mismatch"
        ]
        # control: the listed id (b) is no mismatch; the unlisted one (c) still is
        self.assertEqual([i["customer_id"] for i in mismatches], [self.id_c])

    def test_sync_updates_a_member_listing_the_customer_id(self):
        from verenigingen.verenigingen_payments.mollie.api.sync import _update_local_subscription_records

        self._list_on(self.members[0], self.id_a, self.id_b)
        sub = self._sub()
        self._set("Member", self.members[0].name, "mollie_subscription_id", sub["id"])
        updates = _update_local_subscription_records(
            {"id": sub["id"], "customer_id": self.id_b, "status": "suspended", "next_payment_date": None}
        )
        self.assertEqual(updates["errors"], [])
        self.assertEqual(updates["updated_records"], 1)

    def test_manage_donations_calls_mollie_with_individual_ids(self):
        from unittest.mock import patch

        from verenigingen.templates.pages.manage_donations import get_mollie_subscription_info

        sub = self._sub()
        self._list_on(self.members[0], self.id_a, self.id_b)
        self._set("Member", self.members[0].name, "mollie_subscription_id", sub["id"])
        asked = []

        class _Customers:
            def get(_self, customer_id):
                asked.append(customer_id)
                if customer_id != self.id_b:
                    raise RuntimeError("not this customer's subscription")
                found = type("S", (), {"status": "active", "amount": {"value": "5.00"}})()
                return type("C", (), {"subscriptions": type("Subs", (), {"get": lambda *a: found})()})()

        gateway = type("G", (), {"client": type("Cl", (), {"customers": _Customers()})()})()
        # Mock justified: the Mollie API is the external boundary; only the ids it is asked for matter.
        with patch(
            "verenigingen.verenigingen_payments.utils.payment_gateways.PaymentGatewayFactory.get_gateway",
            return_value=gateway,
        ):
            info = get_mollie_subscription_info(sub["id"])
        self.assertEqual(asked, [self.id_a, self.id_b])
        self.assertEqual(info["subscription_status"], "active")

    def _bulk_checker(self, per_id):
        """A BulkPaymentChecker whose per-customer Mollie call is replaced by ``per_id[customer_id]``."""
        from verenigingen.verenigingen_payments.mollie.services.bulk_payment_checker import (
            BulkPaymentChecker,
        )

        checker = object.__new__(BulkPaymentChecker)
        asked = []

        def _fake(customer_id, member_name, from_date=None, limit=250):
            asked.append(customer_id)
            return {"customer_id": customer_id, "member": member_name, **per_id[customer_id]}

        # Mock justified: the per-customer Mollie API call is the boundary; the per-id fan-out is the subject.
        checker.check_payments_for_customer = _fake
        return checker, asked

    @staticmethod
    def _part(pid, total, new, by_date, by_dup, error=None):
        return {
            "payments": [{"id": pid}],
            "total_found": total,
            "new_payments": new,
            "filtered_by_date": by_date,
            "filtered_by_duplicate": by_dup,
            "error": error,
        }

    def test_bulk_checker_checks_each_listed_customer_and_merges_every_counter(self):
        # distinct values per counter so a dropped or doubled counter cannot cancel out
        per_id = {
            self.id_a: self._part("pay_a", 1, 2, 4, 8),
            self.id_b: self._part("pay_b", 16, 32, 64, 128),
        }
        checker, asked = self._bulk_checker(per_id)
        field = f"{self.id_a}, {self.id_b}"
        merged = checker.check_payments_for_member(field, self.members[0].name)
        self.assertEqual(asked, [self.id_a, self.id_b])
        self.assertEqual(merged["customer_id"], field)
        self.assertEqual([p["id"] for p in merged["payments"]], ["pay_a", "pay_b"])
        self.assertEqual(merged["total_found"], 17)
        self.assertEqual(merged["new_payments"], 34)
        self.assertEqual(merged["filtered_by_date"], 68)
        self.assertEqual(merged["filtered_by_duplicate"], 136)
        self.assertIsNone(merged["error"])

    def test_bulk_checker_keeps_the_first_error_and_the_healthy_ids_payments(self):
        per_id = {
            self.id_a: self._part("pay_a", 1, 1, 0, 0, error="first failure"),
            self.id_b: self._part("pay_b", 5, 5, 0, 0),
            self.id_c: self._part("pay_c", 7, 7, 0, 0, error="second failure"),
        }
        checker, asked = self._bulk_checker(per_id)
        merged = checker.check_payments_for_member(
            f"{self.id_a}, {self.id_b}, {self.id_c}", self.members[0].name
        )
        self.assertEqual(asked, [self.id_a, self.id_b, self.id_c], "a failing id must not stop the rest")
        self.assertEqual(merged["error"], "first failure")
        self.assertEqual(merged["total_found"], 13)

    def test_bulk_checker_error_on_a_later_id_is_not_lost(self):
        per_id = {
            self.id_a: self._part("pay_a", 1, 1, 0, 0),
            self.id_b: self._part("pay_b", 1, 1, 0, 0, error="late failure"),
        }
        checker, _asked = self._bulk_checker(per_id)
        merged = checker.check_payments_for_member(f"{self.id_a}, {self.id_b}", self.members[0].name)
        self.assertEqual(merged["error"], "late failure")

    def test_bulk_checker_single_id_is_passed_through_unmerged(self):
        per_id = {self.id_a: self._part("pay_a", 3, 2, 1, 0)}
        checker, asked = self._bulk_checker(per_id)
        result = checker.check_payments_for_member(f" {self.id_a} ", self.members[0].name)
        self.assertEqual(asked, [self.id_a], "the stripped id, not the raw field")
        self.assertEqual(result["customer_id"], self.id_a)
        self.assertEqual(result["total_found"], 3)

    def test_bulk_run_over_a_listing_member_checks_each_id_and_aggregates(self):
        """Drives check_all_customers_for_new_payments (members stubbed), not just the per-member helper."""
        per_id = {
            self.id_a: self._part("pay_a", 1, 2, 4, 8),
            self.id_b: self._part("pay_b", 16, 32, 64, 128, error="b failed"),
        }
        checker, asked = self._bulk_checker(per_id)
        field = f"{self.id_a}, {self.id_b}"
        # Mock justified: the member query is not the subject; the listing member is the fixture.
        checker.get_members_with_mollie_customers = lambda limit=None: {
            "members": [{"name": self.members[0].name, "full_name": "x", "mollie_customer_id": field}],
            "total_count": 1,
        }
        result = checker.check_all_customers_for_new_payments(days_back=7)
        self.assertEqual(asked, [self.id_a, self.id_b])
        self.assertEqual(result["members_checked"], 1)
        self.assertEqual(result["total_payments_found"], 17)
        self.assertEqual(result["total_new_payments"], 34)
        self.assertEqual(result["total_filtered_by_date"], 68)
        self.assertEqual(result["total_filtered_by_duplicate"], 136)
        self.assertEqual(result["total_payments_after_filtering"], 2)
        self.assertEqual(result["errors"], 1, "one member with a failing id counts as ONE error")
        self.assertEqual(result["error_details"][0]["error"], "b failed")

    def test_debug_lookup_finds_rows_listing_the_id(self):
        from verenigingen.services.mollie_debug_service import MollieDebugService

        self._list_on(self.members[0], self.id_a, self.id_b)
        self._list_on(self.donors[0], self.id_b, self.id_c, doctype="Donor")

        class _Client:
            def is_test_mode(_self):
                return True

        service = object.__new__(MollieDebugService)
        service.mollie_client = _Client()  # API half fails and is recorded; the DB half is the subject
        result = service.debug_customer(self.id_b)
        self.assertEqual([m["name"] for m in result["database_records"]["members"]], [self.members[0].name])
        self.assertEqual([d["name"] for d in result["database_records"]["donors"]], [self.donors[0].name])


class TestWebhookDonorUpdateKeepsTheList(MultiIdBase):
    def test_a_listed_webhook_id_does_not_overwrite_the_donor_list(self):
        from types import SimpleNamespace

        from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
            UnifiedWebhookWrapperService,
        )

        value = f"{self.id_a}, {self.id_b}"
        self._set("Donor", self.donors[0].name, "mollie_customer_id", value)
        UnifiedWebhookWrapperService()._update_donor_record(
            SimpleNamespace(donor=self.donors[0].name, name="DON-2675", amount=5),
            {"id": "tr_2675", "customer_id": self.id_b, "metadata": {}, "amount": {"value": "5.00", "currency": "EUR"}},
        )
        self.assertEqual(frappe.db.get_value("Donor", self.donors[0].name, "mollie_customer_id"), value)

    def test_an_unlisted_webhook_id_is_appended_to_the_donor_list(self):
        from types import SimpleNamespace

        from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
            UnifiedWebhookWrapperService,
        )

        self._set("Donor", self.donors[0].name, "mollie_customer_id", f"{self.id_a}, {self.id_b}")
        UnifiedWebhookWrapperService()._update_donor_record(
            SimpleNamespace(donor=self.donors[0].name, name="DON-2675", amount=5),
            {"id": "tr_2675", "customer_id": self.id_c, "metadata": {}, "amount": {"value": "5.00", "currency": "EUR"}},
        )
        stored = frappe.db.get_value("Donor", self.donors[0].name, "mollie_customer_id")
        self.assertEqual(split_mollie_customer_ids(stored), [self.id_a, self.id_b, self.id_c])

    def test_a_single_id_donor_gets_the_unlisted_webhook_id_appended(self):
        """Control: a one-id value is a list of one; the new id joins it rather than replacing it."""
        from types import SimpleNamespace

        from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
            UnifiedWebhookWrapperService,
        )

        self._set("Donor", self.donors[0].name, "mollie_customer_id", self.id_a)
        UnifiedWebhookWrapperService()._update_donor_record(
            SimpleNamespace(donor=self.donors[0].name, name="DON-2675", amount=5),
            {"id": "tr_2675", "customer_id": self.id_c, "metadata": {}, "amount": {"value": "5.00", "currency": "EUR"}},
        )
        stored = frappe.db.get_value("Donor", self.donors[0].name, "mollie_customer_id")
        self.assertEqual(split_mollie_customer_ids(stored), [self.id_a, self.id_c])


class TestDebugCopiesUseTheSharedHelper(MultiIdBase):
    """F4/F2: the debug_customer copies in core/client.py and mollie/utils/test_helpers.py."""

    def setUp(self):
        super().setUp()
        self._list_on(self.members[0], self.id_a, self.id_b)
        self._list_on(self.donors[0], self.id_b, self.id_c, doctype="Donor")

    def test_core_client_debug_customer_finds_rows_listing_the_id(self):
        from types import SimpleNamespace

        from verenigingen.verenigingen_payments.mollie.core.client import MollieClient

        client = object.__new__(MollieClient)
        subs = SimpleNamespace(list=lambda: [])
        raw = SimpleNamespace(customers=SimpleNamespace(get=lambda _id: SimpleNamespace(subscriptions=subs)))
        # Mock justified: the Mollie API is the boundary; the DB lookup of rows listing the id is the subject.
        client.is_test_mode = lambda: True
        client.get_customer = lambda _id: SimpleNamespace(id=_id, name="n", email="e", created_at="c", mode="test")
        client._get_mollie_client = lambda: raw
        client.list_mandates = lambda _id: []
        result = MollieClient.debug_customer(client, self.id_b)
        self.assertEqual([m["name"] for m in result["database_records"]["members"]], [self.members[0].name])
        self.assertEqual([d["name"] for d in result["database_records"]["donors"]], [self.donors[0].name])

    def test_dev_helper_debug_customer_finds_rows_listing_the_id(self):
        from unittest.mock import patch

        from verenigingen.verenigingen_payments.mollie.utils import test_helpers

        class _FailingClient:
            def is_test_mode(_self):
                return True

            def get_customer(_self, _id):
                raise RuntimeError("API half fails and is recorded; the DB half is the subject")

        fn = test_helpers.debug_mollie_customer
        while hasattr(fn, "__wrapped__"):  # strip the dev-only/audit decorators
            fn = fn.__wrapped__
        # Mock justified: the Mollie API is the boundary.
        with patch("verenigingen.verenigingen_payments.mollie.core.client.MollieClient", _FailingClient):
            result = fn(self.id_b)
        self.assertEqual(result["database_records"]["member"]["name"], self.members[0].name)
        self.assertEqual(result["database_records"]["donor"]["name"], self.donors[0].name)


class TestWebhookServiceListingAsksEachId(MultiIdBase):
    def test_subscription_listing_tries_each_listed_id_and_reports_the_one_that_answered(self):
        from verenigingen.services.payment.mollie_webhook_service import MollieWebhookService

        sub_id = f"sub_{frappe.generate_hash(length=10)}"
        self._list_on(self.members[0], self.id_a, self.id_b)
        self._set("Member", self.members[0].name, "mollie_subscription_id", sub_id)
        self._set("Member", self.members[0].name, "subscription_status", "Active")
        asked = []

        class _Debug:
            def debug_subscription(_self, subscription_id, customer_id):
                asked.append(customer_id)
                if customer_id != self.id_b:
                    return {"subscription_found": False, "error": "404"}
                return {"subscription_found": True, "subscription_data": {"status": "active"}}

        service = object.__new__(MollieWebhookService)
        service._debug_service = _Debug()
        service.get_default_webhook_url = lambda: {"webhook_url": "u", "test_mode": True}
        service._report_progress = lambda *a, **k: None
        result = service.get_active_subscriptions_with_webhooks()
        rows = [r for r in result["subscriptions"] if r["member_id"] == self.members[0].name]
        self.assertEqual(asked.count(self.id_a), 1)
        self.assertEqual(asked.count(self.id_b), 1)
        self.assertEqual([r["customer_id"] for r in rows], [self.id_b])
