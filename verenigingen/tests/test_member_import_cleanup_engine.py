"""
Invariant tests for the shared cleanup engine in scripts/migration/member_import_cleanup.py.

These cover the properties that make a destructive, raw-SQL admin tool safe to
run. Each one pins a bug that actually shipped:

- Administrator/Guest must never be resolved into a delete set (the pre-refactor
  guard was lost when three cleanup engines were merged, and a Member row
  legitimately carries `user = "Administrator"` on the production site).
- The dry-run preview must equal the live run, per bucket. A phase that nulled a
  column before deleting by that same column reported hundreds and deleted none.
- A Contact shared with a live party must survive.
- The orphan sweep must not touch Customers with financial history, Customers a
  live Member still owns, or Customers carrying no test marker at all.
- A live run must not leave NEW broken links behind.

Every test drives the real engine against real rows and rolls back, so nothing
here depends on mocks.
"""

import frappe

from scripts.migration import member_import_cleanup as cleanup
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestCleanupEngineInvariants(EnhancedTestCase):
    """Engine-level invariants, exercised against real records."""

    def setUp(self):
        super().setUp()
        frappe.db.rollback()

    def tearDown(self):
        frappe.db.rollback()
        super().tearDown()

    # -- fixture helpers (factory methods; permission bypass is allowed here) --

    def _make_customer(self, customer_name):
        # Via the factory: it supplies the customer_type/customer_group ERPNext
        # validation requires, and tracks the row for tearDown. EnhancedTestCase
        # proxies create_test_member but not create_test_customer, so go through
        # self.factory directly.
        return self.factory.create_test_customer(customer_name=customer_name)

    def _make_contact(self, first_name, links):
        return frappe.get_doc(
            {
                "doctype": "Contact",
                "first_name": first_name,
                "links": [{"link_doctype": d, "link_name": n} for d, n in links],
            }
        ).insert(ignore_permissions=True)

    def _dangle_customer_member(self, customer_name, ghost="Assoc-Member-GONE-0000"):
        frappe.db.set_value("Customer", customer_name, "member", ghost, update_modified=False)

    # -- protected accounts -------------------------------------------------

    def test_administrator_never_resolved_into_delete_set(self):
        """A Member pointing at Administrator must not put it in the user set."""
        member = self.create_test_member(
            first_name="Protected", last_name="Admin", email="protected.admin@test.invalid"
        )
        frappe.db.set_value("Member", member.name, "user", "Administrator", update_modified=False)

        sets = cleanup._resolve_sets_for_members([member.name])

        self.assertNotIn("Administrator", sets["users"])
        self.assertNotIn("Guest", sets["users"])

    def test_protected_users_constant_covers_both_system_accounts(self):
        self.assertIn("Administrator", cleanup.PROTECTED_USERS)
        self.assertIn("Guest", cleanup.PROTECTED_USERS)

    # -- dry run == live run ------------------------------------------------

    def _assert_dry_matches_live(self, sets, context):
        dry = cleanup._new_cleanup_results(dry_run=True)
        cleanup._run_cleanup_phases(sets, dry, dry_run=True)

        live = cleanup._new_cleanup_results(dry_run=False)
        cleanup._run_cleanup_phases(sets, live, dry_run=False)

        mismatches = {
            bucket: (dry[bucket]["count"], live[bucket]["deleted"])
            for bucket in cleanup.CLEANUP_BUCKETS
            if dry[bucket]["count"] != live[bucket]["deleted"]
        }
        self.assertEqual(
            mismatches, {}, f"{context}: dry count != live deleted for {mismatches} (bucket: (dry, live))"
        )
        return dry

    def test_dry_run_counts_match_live_deletions_per_bucket(self):
        """The preview must not promise deletions the live run does not perform.

        Regression guard: Phase 7 nulled Employee.user_id and then deleted by
        user_id, so the dry run reported N employees and the live run deleted 0.
        """
        member = self.create_test_member(
            first_name="Parity", last_name="Probe", email="parity.probe@test.invalid"
        )
        sets = cleanup._resolve_sets_for_members([member.name])
        dry = self._assert_dry_matches_live(sets, "single member")

        # Guard against the assertion passing because everything was zero.
        self.assertGreater(
            sum(dry[b]["count"] for b in cleanup.CLEANUP_BUCKETS), 0, "fixture deleted nothing"
        )

    def test_dry_run_matches_live_across_full_site_selection(self):
        """Parity over the WHOLE test-data selection, not one synthetic member.

        This is the version that bites. A single-member fixture touches ~5 buckets
        and cannot surface overlap bugs; run against the real selection it caught
        Chapter Member counted by both `member` and `parent`, and Account Creation
        Request counted by both `source_record` and `created_user` -- each inflating
        the preview against the live run.
        """
        self.create_test_member(
            first_name="FullParity", last_name="Probe", email="fullparity.probe@test.invalid"
        )
        sets = cleanup._resolve_test_data_sets()
        self.assertTrue(sets["members"], "expected at least one test member on the site")
        self._assert_dry_matches_live(sets, "full site selection")

    # -- shared parents ------------------------------------------------------

    def test_contact_shared_with_live_party_is_preserved(self):
        """Only Contacts linked EXCLUSIVELY to doomed records may be deleted."""
        member = self.create_test_member(
            first_name="Shared", last_name="Link", email="shared.link@test.invalid"
        )
        live_customer = self._make_customer(f"Live Co {frappe.generate_hash(length=6)}")
        shared = self._make_contact(
            f"SharedC{frappe.generate_hash(length=6)}",
            [("Member", member.name), ("Customer", live_customer.name)],
        )
        exclusive = self._make_contact(f"ExclC{frappe.generate_hash(length=6)}", [("Member", member.name)])

        doomed = {"Member": [member.name], "Customer": [], "Volunteer": []}
        parents = cleanup._exclusively_linked_parents("Contact", doomed)

        self.assertIn(exclusive.name, parents, "Contact linked only to a doomed Member should be doomed")
        self.assertNotIn(shared.name, parents, "Contact also linked to a LIVE Customer must not be deleted")

    # -- orphan sweep guards --------------------------------------------------

    def test_orphan_sweep_skips_customer_owned_by_live_member(self):
        """A Customer a surviving Member points at is never swept."""
        member = self.create_test_member(
            first_name="Owned", last_name="Cust", email="owned.cust@test.invalid"
        )
        customer = member.customer
        self.assertTrue(customer, "factory member should have a customer")

        # Dangle the reverse link while Member.customer still points at it.
        self._dangle_customer_member(customer)

        orphans = cleanup._resolve_orphan_sets([], [])
        self.assertNotIn(customer, orphans["orphaned_customers"])

    def test_orphan_sweep_requires_affirmative_test_marker(self):
        """A dangling Customer with no test marker in its name is left alone.

        Regression guard: the dangling branch had no test predicate, so a button
        labelled "Cleanup ALL Test Data" selected ~9,700 real party records whose
        only sin was pointing at a Member deleted by an earlier run.
        """
        real_looking = self._make_customer(f"Marieke Jansen {frappe.generate_hash(length=4)}")
        self._dangle_customer_member(real_looking.name, "Assoc-Member-GONE-0001")

        orphans = cleanup._resolve_orphan_sets([], [])

        self.assertNotIn(real_looking.name, orphans["orphaned_customers"])
        self.assertGreaterEqual(orphans["skipped_dangling_without_test_marker"], 1)

    def test_orphan_sweep_skips_customer_with_financial_history(self):
        """Anything carrying real bookkeeping is preserved regardless of name."""
        customer = self._make_customer(f"TEST Billed {frappe.generate_hash(length=6)}")
        self._dangle_customer_member(customer.name, "Assoc-Member-GONE-0002")

        before = cleanup._resolve_orphan_sets([], [])
        self.assertIn(customer.name, before["orphaned_customers"], "precondition: sweepable without history")

        frappe.get_doc(
            {
                "doctype": "GL Entry",
                "posting_date": frappe.utils.nowdate(),
                "account": frappe.db.get_value("Account", {"is_group": 0}, "name"),
                "party_type": "Customer",
                "party": customer.name,
                "voucher_type": "Journal Entry",
                "voucher_no": "PROBE-GL-0001",
                "company": frappe.db.get_value("Company", {}, "name"),
            }
        ).db_insert()

        after = cleanup._resolve_orphan_sets([], [])
        self.assertNotIn(customer.name, after["orphaned_customers"])

    # -- selector sanity ------------------------------------------------------

    def test_member_selector_matches_factory_member(self):
        member = self.create_test_member(
            first_name="Selector", last_name="Probe", email="selector.probe@test.invalid"
        )
        clause, params = cleanup._test_member_clause("m")
        selected = {r[0] for r in frappe.db.sql(f"SELECT m.name FROM `tabMember` m WHERE {clause}", params)}
        self.assertIn(member.name, selected)

    def test_user_selector_excludes_system_accounts(self):
        clause, params = cleanup._test_user_clause("u")
        selected = {r[0] for r in frappe.db.sql(f"SELECT u.name FROM `tabUser` u WHERE {clause}", params)}
        self.assertNotIn("Administrator", selected)
        self.assertNotIn("Guest", selected)

    def test_pattern_validation_rejects_match_everything(self):
        for bad in ("%", "%%", "  %  ", "_"):
            with self.assertRaises(frappe.ValidationError, msg=f"pattern {bad!r} should be rejected"):
                cleanup._validate_email_patterns([bad])

    def test_pattern_validation_accepts_specific_pattern(self):
        cleanup._validate_email_patterns(["%@test.invalid"])

    # -- transaction handling -------------------------------------------------

    def test_live_run_works_with_pending_transaction_writes(self):
        """_execute_cleanup must cope with writes already pending.

        Regression guard for the bug that made the live path fail 100% of the time
        from the admin_tools UI: frappe.db.begin() issues START TRANSACTION, which
        Frappe refuses when transaction_writes > 0 -- and the @critical_api
        decorator on every entry point writes an API Audit Log row before the body
        runs. Dry runs never call begin(), so they looked perfectly healthy.
        """
        member = self.create_test_member(
            first_name="TxnProbe", last_name="Pending", email="txnprobe.pending@test.invalid"
        )
        sets = cleanup._resolve_sets_for_members([member.name])
        results = cleanup._new_cleanup_results(dry_run=False)

        # Simulate the decorator's audit write so a transaction is dirty.
        frappe.db.set_value("Member", member.name, "notes", "pending write", update_modified=False)
        self.assertGreater(frappe.db.transaction_writes, 0, "precondition: dirty transaction")

        cleanup._execute_cleanup(sets, results, dry_run=False, label="probe records")

        self.assertFalse(
            results.get("transaction_rolled_back"), f"live run rolled back: {results['summary']}"
        )
        self.assertNotIn("implicit commit", results["summary"].lower())
        self.assertFalse(frappe.db.exists("Member", member.name))

    def test_customer_claimed_by_surviving_member_is_not_selected(self):
        """A duplicate Customer whose `member` points at a doomed member, but which
        a SURVIVING member claims via Member.customer, must not be deleted.

        Regression guard: this shipped and left a live member (evaschout@gmail.com
        on the production dataset) pointing at a deleted customer. The orphan sweep
        had the guard; the member-linked path did not.
        """
        doomed = self.create_test_member(
            first_name="Doomed", last_name="Owner", email="doomed.owner@test.invalid"
        )
        survivor = self.create_test_member(
            first_name="Survivor", last_name="Owner", email="survivor.owner@test.invalid"
        )
        shared = survivor.customer
        self.assertTrue(shared, "factory member should have a customer")

        # Customer.member is UNIQUE, so free the doomed member's slot before
        # pointing the survivor's customer at it.
        frappe.db.sql("UPDATE `tabCustomer` SET member = NULL WHERE member = %s", doomed.name)
        frappe.db.set_value("Customer", shared, "member", doomed.name, update_modified=False)

        # Now: Customer.member -> doomed, while the SURVIVING member claims it.
        sets = cleanup._resolve_sets_for_members([doomed.name])
        self.assertNotIn(shared, sets["customers"], "customer claimed by a surviving member must be spared")

    # -- round trip -----------------------------------------------------------

    def test_live_run_leaves_no_new_broken_links(self):
        """The engine must not manufacture the debris it exists to remove."""
        member = self.create_test_member(
            first_name="RoundTrip", last_name="Probe", email="roundtrip.probe@test.invalid"
        )
        sets = cleanup._resolve_sets_for_members([member.name])

        def broken_for(target):
            total = 0
            for field in cleanup._link_fields_to(target):
                try:
                    total += frappe.db.sql(f"""SELECT COUNT(*) FROM `tab{field.doctype}` src
                            LEFT JOIN `tab{target}` tgt ON src.`{field.fieldname}` = tgt.name
                            WHERE src.`{field.fieldname}` IS NOT NULL
                              AND src.`{field.fieldname}` != '' AND tgt.name IS NULL""")[0][0]
                except Exception:
                    continue
            return total

        targets = ["Member", "Customer", "User", "Chapter"]
        before = {t: broken_for(t) for t in targets}

        results = cleanup._new_cleanup_results(dry_run=False)
        cleanup._run_cleanup_phases(sets, results, dry_run=False)

        after = {t: broken_for(t) for t in targets}
        regressions = {t: (before[t], after[t]) for t in targets if after[t] > before[t]}
        self.assertEqual(
            regressions, {}, f"cleanup created new broken links: {regressions} (target: (before, after))"
        )
