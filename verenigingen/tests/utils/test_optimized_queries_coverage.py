"""Coverage sweep for verenigingen/utils/optimized_queries.py.

Real-DB integration tests. For each optimized (bulk/JOIN) query function the
result is asserted against an INDEPENDENT simple recomputation scoped to the
fixtures created in the test — proving the optimization returns the same answer
as the naive approach, rather than merely exercising the code path.

Also covers the input-validation / SQL-injection guards and the placeholder
helper, which sit on the same module.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.fake_cache import isolate_cache_keys
from verenigingen.utils.optimized_queries import (
    OptimizedChapterQueries,
    OptimizedMemberQueries,
    OptimizedSEPAQueries,
    OptimizedVolunteerQueries,
    QueryCache,
    create_safe_sql_placeholders,
    optimize_member_payment_history_update,
    optimize_volunteer_assignment_loading,
    validate_filters,
    validate_member_names,
)


class TestInputValidationGuards(EnhancedTestCase):
    """validate_member_names / validate_filters / create_safe_sql_placeholders."""

    # --- validate_member_names -------------------------------------------
    def test_member_names_empty_list_rejected(self):
        with self.assertRaises(ValueError):
            validate_member_names([])

    def test_member_names_non_list_rejected(self):
        with self.assertRaises(ValueError):
            validate_member_names("Assoc-Member-2025-0001")

    def test_member_names_too_many_rejected(self):
        with self.assertRaises(ValueError):
            validate_member_names([f"Member-{i}" for i in range(1001)])

    def test_member_names_non_string_element_rejected(self):
        with self.assertRaises(ValueError):
            validate_member_names(["valid-name", 123])

    def test_member_names_blank_element_rejected(self):
        with self.assertRaises(ValueError):
            validate_member_names(["   "])

    def test_member_names_too_long_rejected(self):
        with self.assertRaises(ValueError):
            validate_member_names(["a" * 201])

    def test_member_names_invalid_chars_rejected(self):
        with self.assertRaises(ValueError):
            validate_member_names(["bad$name#here"])

    def test_member_names_sql_keyword_rejected(self):
        # Passes the char pattern but trips the dangerous-keyword scan.
        with self.assertRaises(ValueError):
            validate_member_names(["select something"])

    def test_member_names_valid_accepted(self):
        # The canonical member-name shape: alnum, hyphens, dots, @.
        validate_member_names(["Assoc-Member-2025-0001", "john.doe@example.org"])

    # --- validate_filters -------------------------------------------------
    def test_filters_non_dict_rejected(self):
        with self.assertRaises(ValueError):
            validate_filters(["not", "a", "dict"])

    def test_filters_too_many_keys_rejected(self):
        with self.assertRaises(ValueError):
            validate_filters({f"k{i}": "v" for i in range(51)})

    def test_filters_unknown_key_rejected(self):
        with self.assertRaises(ValueError):
            validate_filters({"not_a_valid_key": "x"})

    def test_filters_limit_coerced_to_int(self):
        out = validate_filters({"limit": "25"})
        self.assertEqual(out["limit"], 25)
        self.assertIsInstance(out["limit"], int)

    def test_filters_limit_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            validate_filters({"limit": 20001})

    def test_filters_limit_non_numeric_rejected(self):
        with self.assertRaises(ValueError):
            validate_filters({"offset": "abc"})

    def test_filters_string_value_too_long_rejected(self):
        with self.assertRaises(ValueError):
            validate_filters({"status": "x" * 101})

    def test_filters_string_value_non_string_rejected(self):
        with self.assertRaises(ValueError):
            validate_filters({"status": 5})

    def test_filters_dangerous_value_rejected(self):
        with self.assertRaises(ValueError):
            validate_filters({"status": "Active'; DROP TABLE"})

    def test_filters_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            validate_filters({"chapter": "../etc/passwd"})

    def test_filters_value_stripped(self):
        out = validate_filters({"status": "  Active  "})
        self.assertEqual(out["status"], "Active")

    def test_filters_none_value_passthrough(self):
        # None values are simply not added to the sanitized dict.
        out = validate_filters({"status": None})
        self.assertNotIn("status", out)

    # --- create_safe_sql_placeholders ------------------------------------
    def test_placeholders_basic(self):
        self.assertEqual(create_safe_sql_placeholders(3), "%s,%s,%s")

    def test_placeholders_zero_rejected(self):
        with self.assertRaises(ValueError):
            create_safe_sql_placeholders(0)

    def test_placeholders_negative_rejected(self):
        with self.assertRaises(ValueError):
            create_safe_sql_placeholders(-1)

    def test_placeholders_too_many_rejected(self):
        with self.assertRaises(ValueError):
            create_safe_sql_placeholders(1001)


class TestOptimizedMemberQueries(EnhancedTestCase):
    """Member bulk/JOIN queries vs independent recomputation."""

    def _member_with_customer(self, **kwargs):
        # EnhancedTestDataFactory.create_member auto-creates the linked Customer.
        member = self.create_test_member(**kwargs)
        member.reload()
        self.assertTrue(member.customer, "Enhanced factory should populate member.customer")
        return member

    def _pay_invoice(self, invoice):
        """Create and submit a Payment Entry fully allocated to `invoice`.

        Used to introduce real Payment Entry rows so the optimized queries'
        ``LEFT JOIN tabPayment Entry`` actually fans out the invoice rows — the
        scenario where a missing ``COUNT(DISTINCT ...)`` / outstanding-SUM bug
        would surface.
        """
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        pe = get_payment_entry("Sales Invoice", invoice.name)
        pe.reference_no = f"REF-{frappe.generate_hash(length=6)}"
        pe.reference_date = today()
        pe.insert()
        pe.submit()
        self.track_doc("Payment Entry", pe.name)
        return pe

    def test_get_members_with_payment_data_aggregates_match(self):
        member = self._member_with_customer()
        # Two submitted invoices (the factory submits unless status="Draft").
        inv1 = self.create_test_sales_invoice(member.name, grand_total=100.0)
        self.create_test_sales_invoice(member.name, grand_total=50.0)
        # Pay one invoice fully -> introduces a Payment Entry row AND clears that
        # invoice's outstanding. The PE join now fans out invoice rows, so a
        # COUNT without DISTINCT (or a mis-scoped outstanding SUM) would diverge
        # from the flat recompute below.
        self._pay_invoice(inv1)
        # A THIRD (paid) invoice gives a SECOND Payment Entry. With >=2 payments the
        # pre-fix invoice-side SUM(outstanding) fans out by payment_count (the unpaid
        # 50.0 invoice would be counted twice -> 100.0), which is exactly what the
        # fan-out fix repairs for get_members_with_payment_data. The unpaid invoice
        # (50.0) still leaves total_outstanding == 50.0 under the correct query.
        inv3 = self.create_test_sales_invoice(member.name, grand_total=70.0)
        self._pay_invoice(inv3)

        rows = OptimizedMemberQueries.get_members_with_payment_data({"customer": member.customer})
        my = [r for r in rows if r["member_name"] == member.name]
        self.assertEqual(len(my), 1, "Exactly one aggregated row for the member")
        row = my[0]

        # Independent recomputation scoped to this customer (flat, no JOIN).
        expected_count = frappe.db.count(
            "Sales Invoice", {"customer": member.customer, "docstatus": 1}
        )
        expected_payment_count = frappe.db.count(
            "Payment Entry",
            {"party": member.customer, "party_type": "Customer", "docstatus": 1},
        )
        expected_outstanding = frappe.db.sql(
            """SELECT COALESCE(SUM(outstanding_amount), 0) FROM `tabSales Invoice`
               WHERE customer=%s AND docstatus=1 AND outstanding_amount > 0""",
            member.customer,
        )[0][0]

        self.assertEqual(row["invoice_count"], expected_count)
        # DISTINCT correctness: invoice_count must stay 3 despite the PE fan-out.
        self.assertEqual(row["invoice_count"], 3)
        self.assertEqual(row["payment_count"], expected_payment_count)
        self.assertEqual(row["payment_count"], 2)
        # Only the unpaid (50.0) invoice contributes to outstanding. With 2 payments,
        # the pre-fix SUM would fan this to 100.0 -> asserting 50.0 guards the fix.
        self.assertEqual(float(row["total_outstanding"] or 0), float(expected_outstanding or 0))
        self.assertEqual(float(row["total_outstanding"] or 0), 50.0)
        self.assertEqual(row["customer_name"], member.customer)

    def test_get_members_with_payment_data_status_filter(self):
        member = self._member_with_customer()
        rows = OptimizedMemberQueries.get_members_with_payment_data({"status": "Active"})
        names = {r["member_name"] for r in rows}
        self.assertIn(member.name, names)
        # All returned rows must satisfy the status filter.
        for r in rows:
            self.assertEqual(r["member_status"], "Active")

    def test_get_member_financial_summary_matches_independent_query(self):
        member = self._member_with_customer()
        # One paid invoice + one unpaid invoice + an active mandate, so every
        # aggregate column in the JOIN is exercised against the flat recompute.
        paid_inv = self.create_test_sales_invoice(member.name, grand_total=80.0)
        self.create_test_sales_invoice(member.name, grand_total=30.0)
        self._pay_invoice(paid_inv)

        from verenigingen.utils.validation.iban_validator import generate_test_iban

        mandate = frappe.new_doc("SEPA Mandate")
        mandate.member = member.name
        mandate.member_name = member.full_name
        mandate.mandate_id = f"M-{frappe.generate_hash(length=8)}"
        mandate.iban = generate_test_iban("TEST")
        mandate.bic = "TESTNL2A"
        mandate.status = "Active"
        mandate.account_holder_name = member.full_name
        mandate.sign_date = today()
        mandate.insert()
        self.track_doc("SEPA Mandate", mandate.name)

        summary = OptimizedMemberQueries.get_member_financial_summary([member.name])
        self.assertIn(member.name, summary)
        data = summary[member.name]

        # Independent (flat) recomputations scoped to this customer.
        expected_total_invoices = frappe.db.count(
            "Sales Invoice", {"customer": member.customer, "docstatus": 1}
        )
        expected_invoiced = frappe.db.sql(
            """SELECT COALESCE(SUM(grand_total),0) FROM `tabSales Invoice`
               WHERE customer=%s AND docstatus=1""",
            member.customer,
        )[0][0]
        expected_paid = frappe.db.sql(
            """SELECT COALESCE(SUM(paid_amount),0) FROM `tabPayment Entry`
               WHERE party=%s AND party_type='Customer' AND docstatus=1""",
            member.customer,
        )[0][0]
        expected_unpaid = frappe.db.count(
            "Sales Invoice",
            {"customer": member.customer, "docstatus": 1, "outstanding_amount": [">", 0]},
        )
        expected_mandates = frappe.db.count(
            "SEPA Mandate", {"member": member.name, "status": "Active"}
        )

        self.assertEqual(data["total_invoices"], expected_total_invoices)
        self.assertEqual(data["total_invoices"], 2)
        self.assertEqual(float(data["total_invoiced"] or 0), float(expected_invoiced or 0))
        self.assertEqual(float(data["total_paid"] or 0), float(expected_paid or 0))
        self.assertEqual(float(data["total_paid"] or 0), 80.0)
        self.assertEqual(data["unpaid_invoices"], expected_unpaid)
        self.assertEqual(data["unpaid_invoices"], 1)
        self.assertEqual(data["active_mandates"], expected_mandates)
        self.assertEqual(data["active_mandates"], 1)

    def test_get_member_financial_summary_empty_returns_empty(self):
        self.assertEqual(OptimizedMemberQueries.get_member_financial_summary([]), {})

    def test_get_member_financial_summary_rejects_injection(self):
        with self.assertRaises(ValueError):
            OptimizedMemberQueries.get_member_financial_summary(["x'; DROP TABLE x; --"])

    def test_bulk_update_payment_history_no_members_found(self):
        # Validation passes (well-formed names) but no such members exist.
        result = OptimizedMemberQueries.bulk_update_payment_history(["Nonexistent-Member-0001"])
        self.assertTrue(result["success"])
        self.assertEqual(result["updated_count"], 0)
        self.assertIn("No valid members", result["message"])

    def test_bulk_update_payment_history_empty_short_circuit(self):
        self.assertEqual(
            OptimizedMemberQueries.bulk_update_payment_history([]),
            {"success": True, "updated_count": 0},
        )

    def test_bulk_update_payment_history_real_member_no_invoices(self):
        member = self._member_with_customer()
        result = OptimizedMemberQueries.bulk_update_payment_history([member.name])
        self.assertTrue(result["success"], result)
        # The member exists, so it is processed (count == 1) even with no invoices.
        self.assertEqual(result["updated_count"], 1)
        # And its payment history child table is emptied (no invoices to rebuild).
        self.assertEqual(
            frappe.db.count("Member Payment History", {"parent": member.name}), 0
        )

    def test_bulk_update_payment_history_builds_history_from_invoice(self):
        member = self._member_with_customer()
        inv = self.create_test_sales_invoice(member.name, grand_total=42.0)

        result = OptimizedMemberQueries.bulk_update_payment_history([member.name])
        self.assertTrue(result["success"], result)
        self.assertEqual(result["updated_count"], 1)

        # The optimized rebuild must produce exactly one history row for the one
        # submitted invoice, referencing that invoice.
        rows = frappe.get_all(
            "Member Payment History",
            filters={"parent": member.name},
            fields=["invoice"],
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["invoice"], inv.name)


class TestOptimizedSEPAQueries(EnhancedTestCase):
    """Active SEPA-mandate bulk loading vs independent query."""

    def _make_mandate(self, member, status="Active"):
        from verenigingen.utils.validation.iban_validator import generate_test_iban

        mandate = frappe.new_doc("SEPA Mandate")
        mandate.member = member.name
        mandate.member_name = member.full_name
        mandate.mandate_id = f"M-{frappe.generate_hash(length=8)}"
        mandate.iban = generate_test_iban("TEST")
        mandate.bic = "TESTNL2A"
        mandate.status = status
        mandate.account_holder_name = member.full_name
        mandate.sign_date = today()
        mandate.insert()
        self.track_doc("SEPA Mandate", mandate.name)
        return mandate

    def test_active_mandates_empty_returns_empty(self):
        self.assertEqual(OptimizedSEPAQueries.get_active_mandates_for_members([]), {})

    def test_active_mandates_match_independent_query(self):
        member = self.create_test_member()
        mandate = self._make_mandate(member, status="Active")

        result = OptimizedSEPAQueries.get_active_mandates_for_members([member.name])
        self.assertIn(member.name, result)
        self.assertEqual(result[member.name]["mandate_name"], mandate.name)
        self.assertEqual(result[member.name]["status"], "Active")

        # Independent: the active mandate for this member.
        expected = frappe.db.get_value(
            "SEPA Mandate", {"member": member.name, "status": "Active"}, "name"
        )
        self.assertEqual(result[member.name]["mandate_name"], expected)

    def test_inactive_mandate_excluded(self):
        member = self.create_test_member()
        self._make_mandate(member, status="Cancelled")
        result = OptimizedSEPAQueries.get_active_mandates_for_members([member.name])
        # No active mandate -> member key absent.
        self.assertNotIn(member.name, result)

    def test_active_mandates_rejects_injection(self):
        with self.assertRaises(ValueError):
            OptimizedSEPAQueries.get_active_mandates_for_members(["x'; DROP --"])


class TestOptimizedVolunteerQueries(EnhancedTestCase):
    """Volunteer assignment UNION query vs independent recomputation."""

    def test_volunteer_assignments_empty_returns_empty(self):
        self.assertEqual(OptimizedVolunteerQueries.get_volunteer_assignments_bulk([]), {})

    def test_volunteer_no_assignments_returns_initialized_empty_list(self):
        member = self.create_test_member()
        volunteer = self.create_test_volunteer(member.name)
        result = OptimizedVolunteerQueries.get_volunteer_assignments_bulk([volunteer.name])
        # Every requested volunteer is keyed, even with zero assignments.
        self.assertIn(volunteer.name, result)
        self.assertEqual(result[volunteer.name], [])

    def test_volunteer_activity_assignment_captured(self):
        member = self.create_test_member()
        volunteer = self.create_test_volunteer(member.name)

        activity = frappe.new_doc("Volunteer Activity")
        activity.volunteer = volunteer.name
        activity.activity_type = "Event"
        activity.role = "Helper"
        activity.status = "Active"
        activity.start_date = today()
        activity.insert()
        self.track_doc("Volunteer Activity", activity.name)

        result = OptimizedVolunteerQueries.get_volunteer_assignments_bulk([volunteer.name])
        assignments = result[volunteer.name]
        activity_rows = [a for a in assignments if a["assignment_type"] == "Activity"]
        self.assertEqual(len(activity_rows), 1)
        self.assertEqual(activity_rows[0]["source_name"], activity.name)
        self.assertEqual(activity_rows[0]["role"], "Helper")
        # Activity rows are flagged editable=1 in the UNION.
        self.assertEqual(activity_rows[0]["editable"], 1)
        # Open-ended (start today, no end) -> active.
        self.assertEqual(activity_rows[0]["is_active"], 1)

    def test_volunteer_assignments_rejects_injection(self):
        with self.assertRaises(ValueError):
            OptimizedVolunteerQueries.get_volunteer_assignments_bulk(["x; DELETE"])


class TestOptimizedChapterQueries(EnhancedTestCase):
    """Postal-code -> chapter assignment matching."""

    def test_empty_postal_codes_returns_empty(self):
        self.assertEqual(OptimizedChapterQueries.get_chapter_assignments_bulk([]), {})

    def test_postal_code_matches_active_chapter(self):
        chapter = self.create_test_chapter()
        # Configure the chapter's postal_codes range to contain a code.
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.status = "Active"
        chapter_doc.postal_codes = "1234"
        chapter_doc.save()

        result = OptimizedChapterQueries.get_chapter_assignments_bulk(["1234"])
        # FIND_IN_SET on the (space-stripped) postal_codes string must match.
        self.assertEqual(result.get("1234"), chapter.name)

    def test_postal_code_no_match_absent(self):
        result = OptimizedChapterQueries.get_chapter_assignments_bulk(["99999"])
        self.assertNotIn("99999", result)


class TestQueryCacheAndDropIns(EnhancedTestCase):
    """QueryCache round-trip + the drop-in replacement helpers."""

    def test_member_data_cache_roundtrip_and_invalidate(self):
        # Route the QueryCache key through an in-process dict so a sibling shard's
        # frappe.clear_cache() (redis FLUSH on the shared CI redis) cannot evict
        # the value between set and get. See tests/fixtures/fake_cache.py.
        with isolate_cache_keys("member_data:"):
            key = f"cachetest-{frappe.generate_hash(length=6)}"
            self.assertIsNone(QueryCache.get_cached_member_data(key))
            QueryCache.set_cached_member_data(key, {"x": 1})
            self.assertEqual(QueryCache.get_cached_member_data(key), {"x": 1})
            QueryCache.invalidate_member_cache(key)
            self.assertIsNone(QueryCache.get_cached_member_data(key))

    def test_volunteer_assignments_cache_roundtrip(self):
        # Flush-proof the set->get round-trip on the shared CI redis.
        with isolate_cache_keys("volunteer_assignments:"):
            key = f"voltest-{frappe.generate_hash(length=6)}"
            self.assertIsNone(QueryCache.get_cached_volunteer_assignments(key))
            QueryCache.set_cached_volunteer_assignments(key, [{"a": 1}])
            self.assertEqual(QueryCache.get_cached_volunteer_assignments(key), [{"a": 1}])

    def test_optimize_volunteer_assignment_loading_caches_result(self):
        member = self.create_test_member()
        volunteer = self.create_test_volunteer(member.name)
        # Flush-proof the production cache slot this exercises so a sibling
        # shard's redis FLUSH cannot evict the cached result between writes/reads.
        with isolate_cache_keys("volunteer_assignments:"):
            # Ensure a clean cache slot.
            frappe.cache().delete_value(f"volunteer_assignments:{volunteer.name}")

            first = optimize_volunteer_assignment_loading(volunteer.name)
            self.assertIsInstance(first, list)
            # Second call must hit the cache and return the same data.
            cached = QueryCache.get_cached_volunteer_assignments(volunteer.name)
            self.assertEqual(cached, first)
            second = optimize_volunteer_assignment_loading(volunteer.name)
            self.assertEqual(second, first)

    def test_optimize_member_payment_history_update_no_members_for_customer(self):
        # Exercise the "no members for customer" branch of the drop-in helper
        # with a real customer Payment Entry whose customer has no linked Member.
        from frappe.utils import nowdate

        company = frappe.get_list("Company", limit=1)[0].name
        cust = frappe.new_doc("Customer")
        cust.customer_name = f"Orphan-{frappe.generate_hash(length=6)}"
        cust.insert()
        self.track_doc("Customer", cust.name)

        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Receive"
        pe.party_type = "Customer"
        pe.party = cust.name
        pe.company = company
        pe.posting_date = nowdate()
        pe.paid_amount = 10
        pe.received_amount = 10
        paid_to = frappe.db.get_value(
            "Account", {"account_type": "Bank", "company": company, "is_group": 0}, "name"
        ) or frappe.db.get_value(
            "Account", {"account_type": "Cash", "company": company, "is_group": 0}, "name"
        )
        pe.paid_to = paid_to
        pe.paid_from = frappe.db.get_value(
            "Company", company, "default_receivable_account"
        )
        pe.reference_no = "X"
        pe.reference_date = nowdate()
        pe.insert()
        self.track_doc("Payment Entry", pe.name)

        result = optimize_member_payment_history_update(pe.name)
        self.assertTrue(result["success"])
        self.assertIn("No members found", result["message"])


class TestBulkUpdateTransactionSafety(EnhancedTestCase):
    """``OptimizedMemberQueries._update_member_payment_history_bulk`` runs inside
    Payment Entry / Sales Invoice submit hooks (via
    ``performance_event_handlers.on_member_payment_update``). On error it must
    scope its own delete/insert in a SAVEPOINT and re-raise — it must never
    ``frappe.db.commit()`` or ``frappe.db.rollback()`` the caller's request
    transaction (that prematurely commits the document submit or wipes it).
    """

    def test_bulk_update_error_does_not_commit_caller_transaction(self):
        from unittest.mock import patch

        member = self.create_test_member(
            first_name="OptTxn",
            last_name="Safety",
            email="opttxn.safety@test.invalid",
        )

        # Uncommitted sibling work in the SAME transaction (stands in for the
        # document submit that this hook runs inside).
        marker = f"OptTxnProbe-{self.uid}"
        frappe.get_doc(
            {
                "doctype": "Item",
                "item_code": marker,
                "item_name": marker,
                "item_group": "All Item Groups",
                "stock_uom": "Nos",
                "is_stock_item": 0,
            }
        ).insert(ignore_permissions=True)
        self.track_doc("Item", marker)
        self.assertTrue(frappe.db.exists("Item", marker), "precondition: marker present")

        # Force an error partway through the bulk update (the builder raises).
        self.expectErrorLog("Payment History Bulk Update Error")
        with patch(
            "verenigingen.utils.payment_history_builder.build_payment_history_entry_from_query",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                OptimizedMemberQueries._update_member_payment_history_bulk(
                    member.name, [{"invoice_name": "INV-IRRELEVANT"}]
                )

        # The bulk update must NOT have committed the caller's transaction on
        # error. Simulate the request rolling back (as a later hook error would):
        frappe.db.rollback()
        self.assertFalse(
            frappe.db.exists("Item", marker),
            "the bulk update committed the caller's transaction on error; it must "
            "scope its own work in a savepoint and never commit/rollback the "
            "request-level transaction",
        )
