"""#3240: MemberFinancialHistoryManager._trim_history must keep the NEWEST rows.

It used to keep the first `max_entries` rows of the in-memory list. New rows are
inserted at index 0 and existing rows are updated in place, so which invoices
survived depended on drain order, not on invoice date. These tests drive the real
manager (real Member, real Sales Invoices, real child-table save) and read the
persisted rows back.
"""

import random

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.invoice_payments import build_eur_membership_invoice
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.utils.member_financial_history_manager import get_payment_history_manager


class TestHistoryTrimKeepsNewest(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        get_eur_test_company()
        self._ensure_test_item("TEST-MEMBERSHIP")

    def _member_3240(self, suffix):
        member = self.create_test_member(
            first_name=f"Trim{suffix}", last_name="Newest", email=f"trim3240.{suffix}@example.com"
        )
        member.reload()
        if not member.customer:
            member.create_customer()
            member.reload()
        return member

    def _invoices(self, member, days_ago):
        """One submitted invoice per entry of `days_ago`, in that order."""
        return [
            build_eur_membership_invoice(self, member.customer, 10.0, add_days(today(), -d))
            for d in days_ago
        ]

    def _drain(self, manager, member, invoices):
        for inv in invoices:
            ok = manager.add_or_update_entry(
                inv.name, lambda inv=inv: member._build_payment_history_entry(inv), "invoice"
            )
            self.assertTrue(ok, f"history write for {inv.name} failed; nothing below is meaningful")

    def _persisted(self, member):
        return frappe.get_all(
            "Member Payment History",
            filters={"parent": member.name, "parenttype": "Member"},
            fields=["invoice", "posting_date"],
            order_by="idx asc",
        )

    def _assert_newest_first_contiguous(self, member, expected_names):
        rows = frappe.get_all(
            "Member Payment History",
            filters={"parent": member.name, "parenttype": "Member"},
            fields=["invoice", "idx"],
            order_by="idx asc",
        )
        self.assertEqual([r.idx for r in rows], list(range(1, len(expected_names) + 1)), "idx unique+contiguous")
        self.assertEqual([r.invoice for r in rows], expected_names, "persisted order is newest first")

    def test_shuffled_drain_keeps_newest_and_persists_newest_first_with_unique_idx(self):
        member = self._member_3240("shuf")
        invoices = self._invoices(member, list(range(9)))  # [0] newest
        manager = get_payment_history_manager(member)
        manager.max_entries = 6
        shuffled = list(invoices)
        random.Random(3240).shuffle(shuffled)
        self._drain(manager, member, shuffled)
        self._assert_newest_first_contiguous(member, [i.name for i in invoices[:6]])

    def test_at_the_real_cap_the_newest_30_of_34_survive_whatever_the_drain_order(self):
        member = self._member_3240("cap")
        invoices = self._invoices(member, list(range(34)))  # invoices[0] newest, [33] oldest
        # Oldest first, then newest last: the newest row is what the old trim dropped.
        drain_order = list(reversed(invoices))
        self._drain(get_payment_history_manager(member), member, drain_order)

        rows = self._persisted(member)
        self.assertEqual(
            sorted(r.invoice for r in rows),
            sorted(i.name for i in invoices[:30]),
            "expected exactly the 30 newest invoices by posting_date",
        )
        self._assert_newest_first_contiguous(member, [i.name for i in invoices[:30]])

    def test_the_oldest_invoice_arriving_last_at_a_full_history_is_the_one_dropped(self):
        member = self._member_3240("edge")
        invoices = self._invoices(member, list(range(31)))  # [0] newest, [30] oldest
        manager = get_payment_history_manager(member)
        self._drain(manager, member, invoices[:30])  # newest first: 30 rows, exactly the cap
        self.assertEqual(len(self._persisted(member)), 30, "nothing is trimmed at exactly the cap")
        self._drain(manager, member, invoices[30:])  # the oldest arrives last
        kept = [r.invoice for r in self._persisted(member)]
        self.assertEqual(len(kept), 30)
        self.assertIn(invoices[0].name, kept, "the newest invoice, drained first, must survive")
        self.assertNotIn(invoices[30].name, kept, "the oldest invoice is the one that goes")

    def test_a_posting_date_tie_at_the_boundary_is_broken_by_invoice_name_not_drain_order(self):
        # cap 3, dates (days ago): 9, 5, 5, 2, 1 -> keep 1, 2 and ONE of the two 5s.
        days = [9, 5, 5, 2, 1]
        kept_sets = []
        for suffix, order in (("tie_a", [0, 1, 2, 3, 4]), ("tie_b", [0, 2, 1, 3, 4])):
            member = self._member_3240(suffix)
            invoices = self._invoices(member, days)
            manager = get_payment_history_manager(member)
            manager.max_entries = 3
            self._drain(manager, member, [invoices[i] for i in order])
            names = [r.invoice for r in self._persisted(member)]
            self.assertEqual(len(names), 3)
            tied = sorted([invoices[1].name, invoices[2].name])
            self.assertEqual(
                sorted(names),
                sorted([invoices[4].name, invoices[3].name, tied[-1]]),
                "the two newest plus the higher-named of the tied pair",
            )
            position = {i.name: n for n, i in enumerate(invoices)}
            kept_sets.append(sorted(position[n] for n in names))
        self.assertEqual(kept_sets[0], kept_sets[1], "drain order changed which tied invoice survived")
