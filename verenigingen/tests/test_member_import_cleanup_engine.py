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
        # Security: test-local fixture built entirely from arguments this test
        # supplies; ignore_permissions so the fixture is creatable regardless of
        # the DocPerms on the shared test site. No user input reaches it.
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

    def test_dry_run_counts_rows_reachable_by_volunteer_and_parent_once(self):
        """#2477: a Chapter Board Member / Team Member row is reachable through its
        doomed Volunteer AND its doomed parent Chapter/Team. The dry run counted it
        in both phase 3 and phase 4 (2x) while the live run deletes it in phase 3.

        The fixture seats a doomed volunteer on a doomed chapter and on a doomed team,
        so the overlap exists whatever else the site holds; the expected counts are
        read back from the rows themselves.
        """
        seat = self.create_test_board_member(self.create_test_chapter().name)
        team = self.create_test_team()
        self.create_test_team_member(team.name, seat.volunteer)
        # A second row held by a SURVIVING volunteer: only the parent selector reaches
        # it, so a fix that drops the parent half of the union leaves it uncounted.
        bystander = self.create_test_member(
            first_name="Bystander", last_name="Probe", email="bystander.probe2477@test.invalid"
        )
        bystander_volunteer = self.create_test_volunteer(bystander.name).name
        self.create_test_team_member(team.name, bystander_volunteer)
        # Same for the chapter: a board row held by the bystander (appended to the
        # chapter with the seat's role, as the real flow does, then saved).
        chapter = frappe.get_doc("Chapter", seat.chapter)
        chapter.append(
            "board_members",
            {
                "volunteer": bystander_volunteer,
                "chapter_role": seat.chapter_role,
                "is_active": 1,
                "from_date": frappe.utils.today(),
            },
        )
        chapter.flags.ignore_validate = True
        chapter.save()
        # And the reverse: the doomed volunteer also sits on a SURVIVING chapter, which
        # only the volunteer selector reaches.
        surviving_chapter = self.create_test_chapter()
        surviving_chapter.append(
            "board_members",
            {
                "volunteer": seat.volunteer,
                "chapter_role": seat.chapter_role,
                "is_active": 1,
                "from_date": frappe.utils.today(),
            },
        )
        surviving_chapter.flags.ignore_validate = True
        surviving_chapter.save()
        sets = cleanup._resolve_sets_for_members(
            [seat.member], chapters=[seat.chapter], teams=[team.name]
        )
        board_rows = frappe.db.count("Chapter Board Member", {"parent": seat.chapter}) + frappe.db.count(
            "Chapter Board Member", {"parent": surviving_chapter.name}
        )
        team_rows = frappe.db.count("Team Member", {"parent": team.name})
        self.assertGreaterEqual(board_rows, 3, "fixture lacks the seat, bystander and surviving-chapter rows")
        self.assertGreaterEqual(team_rows, 1, "fixture has no team member row to double count")

        dry = self._assert_dry_matches_live(sets, "volunteer + parent overlap")

        self.assertEqual(dry["chapter_board_members"]["count"], board_rows)
        self.assertEqual(dry["team_members"]["count"], team_rows)
        self.assertEqual(frappe.db.count("Chapter Board Member", {"parent": seat.chapter}), 0)
        self.assertEqual(frappe.db.count("Chapter Board Member", {"parent": surviving_chapter.name}), 0)
        self.assertEqual(frappe.db.count("Team Member", {"parent": team.name}), 0)

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


class TestOrphanedChapterMemberCleanup(EnhancedTestCase):
    """#2469: `orphaned_removed` must count rows that really left the chapter."""

    ORPHAN_SQL = """SELECT COUNT(*) FROM `tabChapter Member` cm
        LEFT JOIN `tabMember` m ON cm.member = m.name
        WHERE cm.parenttype = 'Chapter' AND m.name IS NULL"""

    def setUp(self):
        super().setUp()
        frappe.db.rollback()

    def tearDown(self):
        frappe.db.rollback()
        super().tearDown()

    def _chapter_with_orphan(self, with_dangling_board_link=False, orphans=1):
        chapter = self.create_chapter(chapter_name=f"TEST-Orphan-{frappe.generate_hash()[:8]}")
        ghosts = [f"Assoc-Member-GHOST-{frappe.generate_hash()[:6]}" for _ in range(orphans)]
        # db_insert: the row has to exist the way legacy debris does, which
        # Chapter validation would refuse to create.
        for idx, ghost in enumerate(ghosts, start=1):
            frappe.get_doc(
                {
                    "doctype": "Chapter Member",
                    "parent": chapter.name,
                    "parenttype": "Chapter",
                    "parentfield": "members",
                    "idx": idx,
                    "member": ghost,
                    "status": "Active",
                }
            ).db_insert()
        ghost = ghosts[0]
        if with_dangling_board_link:
            # A real role of our own, so the ONLY dangling link is the volunteer.
            role = self.factory.ensure_chapter_role("Orphan Cleanup Test Role")
            frappe.get_doc(
                {
                    "doctype": "Chapter Board Member",
                    "parent": chapter.name,
                    "parenttype": "Chapter",
                    "parentfield": "board_members",
                    "idx": 1,
                    "volunteer": f"GHOST-VOL-{frappe.generate_hash()[:6]}",
                    "chapter_role": role.name,
                    "from_date": frappe.utils.today(),
                }
            ).db_insert()
        return chapter.name, ghost

    def _run_live(self):
        # Mock justified: the function under test commits at the end of a live
        # run, which would persist this test's rows (and the cleanup of every
        # other chapter on the site). The commit is not what is under test.
        from unittest.mock import patch

        before = frappe.db.sql(self.ORPHAN_SQL)[0][0]
        with patch.object(frappe.db, "commit"):
            results = cleanup.cleanup_orphaned_chapter_members(dry_run=False)
        after = frappe.db.sql(self.ORPHAN_SQL)[0][0]
        return results, before - after

    def _row_exists(self, chapter_name, ghost):
        return bool(frappe.db.exists("Chapter Member", {"parent": chapter_name, "member": ghost}))

    def test_a_removed_orphan_is_counted(self):
        chapter_name, ghost = self._chapter_with_orphan()
        results, really_removed = self._run_live()

        self.assertFalse(self._row_exists(chapter_name, ghost))
        self.assertEqual(results["orphaned_removed"], really_removed)
        self.assertGreaterEqual(results["orphaned_removed"], 1)
        self.assertNotIn(chapter_name, [e.split(":")[0] for e in results["errors"]])

    def test_a_failed_chapter_save_is_not_counted_as_removed(self):
        chapter_name, ghost = self._chapter_with_orphan(with_dangling_board_link=True)
        results, really_removed = self._run_live()

        # Control: the save really failed and the row really stayed.
        self.assertTrue(self._row_exists(chapter_name, ghost))
        errors = [e for e in results["errors"] if e.split(":")[0] == chapter_name]
        self.assertEqual(len(errors), 1)
        # Cause: the dangling board-member volunteer link, not something else.
        self.assertIn("Volunteer", errors[0])
        # The claim: the count equals rows that actually left, here none from this chapter.
        self.assertEqual(results["orphaned_removed"], really_removed)
        self.assertIn(chapter_name, results["chapters_failed"])
        self.assertIn("failed", results["summary"].lower())
        affected = [c["chapter"] for c in results["chapters_affected"]]
        self.assertIn(chapter_name, affected)

    def test_chapters_cleaned_excludes_a_failed_chapter_in_the_same_run(self):
        # Good first: the listing is newest-first, so the failing chapter is visited BEFORE
        # the cleaned one and a running "chapters seen so far" count would be wrong.
        good, good_ghost = self._chapter_with_orphan()
        bad, bad_ghost = self._chapter_with_orphan(with_dangling_board_link=True)
        results, _removed = self._run_live()

        self.assertFalse(self._row_exists(good, good_ghost))
        self.assertTrue(self._row_exists(bad, bad_ghost))
        affected = [c["chapter"] for c in results["chapters_affected"]]
        self.assertIn(bad, affected)
        self.assertIn(good, affected)
        # Derived from what really happened, so other orphan chapters on the site don't matter.
        really_cleaned = [c for c in affected if c not in results["chapters_failed"]]
        self.assertEqual(results["chapters_failed"].count(bad), 1)
        self.assertEqual(results["chapters_cleaned"], len(really_cleaned))
        self.assertLess(results["chapters_cleaned"], len(affected))
        self.assertIn(f"from {len(really_cleaned)} chapter(s)", results["summary"])

    def test_a_lost_transaction_reports_the_deadlock_not_the_missing_savepoint(self):
        from unittest.mock import patch

        import pymysql

        from verenigingen.verenigingen.doctype.chapter.chapter import Chapter

        chapter_name, ghost = self._chapter_with_orphan()

        def save_then_lose_transaction(doc, *args, **kwargs):
            if doc.name != chapter_name:
                return real_save(doc, *args, **kwargs)
            # A 1213 victim: the server has already rolled the whole transaction back.
            frappe.db.rollback()
            raise pymysql.err.OperationalError(1213, "Deadlock found when trying to get lock")

        real_save = Chapter.save
        # Mock justified: reproduces the server-side rollback a deadlock victim suffers.
        with patch.object(Chapter, "save", save_then_lose_transaction):
            results, _removed = self._run_live()

        mine = [e for e in results["errors"] if e.split(":")[0] == chapter_name]
        self.assertEqual(len(mine), 1)
        self.assertIn("1213", mine[0])
        self.assertNotIn("1305", mine[0])
        self.assertIn(chapter_name, results["chapters_failed"])

    def _create_committed_orphan_chapters(self, count):
        """Chapters whose orphan rows are COMMITTED, so a later rollback can only undo the cleanup.

        The fixtures must be durable for the claim under test: a deadlock victim's rollback
        takes every uncommitted row with it, fixtures included, and a fresh connection can
        only see committed ones.
        """
        names = [self._chapter_with_orphan()[0] for _ in range(count)]
        frappe.db.commit()
        self.addCleanup(self._cleanup_committed_chapters, names)
        return names

    def _cleanup_committed_chapters(self, names):
        frappe.db.rollback()
        for name in names:
            frappe.db.delete("Chapter Member", {"parent": name})
            frappe.delete_doc("Chapter", name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def _orphan_rows_on_fresh_connection(self, chapter_name=None):
        """Orphan Chapter Member rows as a SECOND connection sees them (committed state only).

        Site-wide, or for one chapter. The run under test lists every chapter on the site,
        so a claim about what persisted has to be measured site-wide.
        """
        from frappe.database import get_db

        fresh = get_db(
            host=frappe.conf.db_host,
            port=frappe.conf.db_port,
            user=frappe.conf.db_name,
            password=frappe.conf.db_password,
            cur_db_name=frappe.conf.db_name,
        )
        try:
            return fresh.sql(
                self.ORPHAN_SQL + (" AND cm.parent = %s" if chapter_name else ""),
                (chapter_name,) if chapter_name else (),
            )[0][0]
        finally:
            fresh.close()

    def _run_live_with_save_hook(self, save_hook=None):
        """A REAL run (commit not patched); `save_hook(real_save, doc, ...)` replaces Chapter.save."""
        from unittest.mock import patch

        from verenigingen.verenigingen.doctype.chapter.chapter import Chapter

        if save_hook is None:
            return cleanup.cleanup_orphaned_chapter_members(dry_run=False)
        real_save = Chapter.save

        def save(doc, *args, **kwargs):
            return save_hook(real_save, doc, *args, **kwargs)

        # Mock justified: reproduces the server-side rollback a deadlock victim suffers.
        with patch.object(Chapter, "save", save):
            return cleanup.cleanup_orphaned_chapter_members(dry_run=False)

    def _lose_the_transaction(self, error=None):
        import pymysql

        # A 1213 victim: the server rolls the WHOLE transaction back, earlier saves included.
        frappe.db.rollback()
        raise error or pymysql.err.OperationalError(1213, "Deadlock found when trying to get lock")

    def test_a_clean_run_counts_and_persists_every_chapter(self):
        names = self._create_committed_orphan_chapters(2)
        before = self._orphan_rows_on_fresh_connection()
        self.assertGreaterEqual(before, 2)

        results = self._run_live_with_save_hook()

        after = self._orphan_rows_on_fresh_connection()
        self.assertEqual(results["orphaned_removed"], before - after)
        self.assertGreaterEqual(results["chapters_cleaned"], 2)
        self.assertFalse(results.get("aborted"))
        self.assertEqual([self._orphan_rows_on_fresh_connection(n) for n in names], [0, 0])

    def test_a_deadlock_aborts_the_run_and_reports_what_persisted(self):
        # The savepoint is gone after a 1213; the helper logs that and keeps the real error.
        self.expectErrorLog("Orphaned Chapter Cleanup Rollback Error")
        self._create_committed_orphan_chapters(2)
        before = self._orphan_rows_on_fresh_connection()
        saved_for_real = []

        def save_hook(real_save, doc, *args, **kwargs):
            if saved_for_real:
                # The typed error: the raw-driver 1213 form is covered by the stops-the-run test.
                self._lose_the_transaction(frappe.QueryDeadlockError("Deadlock found"))
            saved_for_real.append(doc.name)
            return real_save(doc, *args, **kwargs)

        results = self._run_live_with_save_hook(save_hook)

        # Control: one chapter really was cleaned before the deadlock and then undone.
        self.assertEqual(len(saved_for_real), 1)
        after = self._orphan_rows_on_fresh_connection()
        self.assertEqual(after, before)
        self.assertEqual(results["orphaned_removed"], before - after)
        self.assertEqual(results["chapters_cleaned"], 0)
        self.assertTrue(results["aborted"])
        self.assertIn("ABORTED", results["summary"])
        self.assertNotIn("Removed", results["summary"])
        self.assertEqual(len(results["chapters_failed"]), 1)

    def test_a_deadlock_swallowed_below_save_still_aborts_the_run(self):
        """#2482 F1: Chapter validators swallow a 1213 raised under `save()`.

        `save()` then returns normally, the savepoint is gone, and the release raises 1305.
        """
        from unittest.mock import patch

        self.expectErrorLog("Orphaned Chapter Cleanup Rollback Error")
        self._create_committed_orphan_chapters(3)
        before = self._orphan_rows_on_fresh_connection()
        saves = []
        real_get_single = frappe.get_single
        armed = []

        def get_single(doctype, *args, **kwargs):
            if doctype == "Verenigingen Settings" and armed:
                armed.clear()
                frappe.db.rollback()
                raise frappe.QueryDeadlockError("Deadlock found when trying to get lock")
            return real_get_single(doctype, *args, **kwargs)

        def save_hook(real_save, doc, *args, **kwargs):
            saves.append(doc.name)
            if len(saves) == 2:
                armed.append(True)
            return real_save(doc, *args, **kwargs)

        # Mock justified: injects the deadlock below Chapter.save, where validators swallow it.
        with patch.object(frappe, "get_single", get_single):
            results = self._run_live_with_save_hook(save_hook)

        self.assertFalse(armed, "the injected deadlock never fired")
        self.assertEqual(len(saves), 2)
        after = self._orphan_rows_on_fresh_connection()
        self.assertEqual(after, before)
        self.assertTrue(results["aborted"])
        self.assertEqual(results["orphaned_removed"], 0)
        self.assertEqual(results["chapters_cleaned"], 0)

    def test_a_deadlock_stops_the_run_instead_of_carrying_on(self):
        self.expectErrorLog("Orphaned Chapter Cleanup Rollback Error")
        self._create_committed_orphan_chapters(3)
        visited = []

        def save_hook(real_save, doc, *args, **kwargs):
            visited.append(doc.name)
            if len(visited) == 2:
                self._lose_the_transaction()
            return real_save(doc, *args, **kwargs)

        self._run_live_with_save_hook(save_hook)

        # Carrying on would have visited the third chapter too.
        self.assertEqual(len(visited), 2)

    def test_a_lock_wait_timeout_does_not_abort_the_run(self):
        # Control: 1205 only undoes the failed statement, so the other chapters still count.
        self._create_committed_orphan_chapters(2)
        before = self._orphan_rows_on_fresh_connection()
        refused = []

        def save_hook(real_save, doc, *args, **kwargs):
            if not refused:
                refused.append(doc.name)
                raise frappe.QueryTimeoutError("Lock wait timeout exceeded")
            return real_save(doc, *args, **kwargs)

        results = self._run_live_with_save_hook(save_hook)

        after = self._orphan_rows_on_fresh_connection()
        self.assertFalse(results.get("aborted"))
        self.assertGreaterEqual(results["chapters_cleaned"], 1)
        self.assertEqual(results["orphaned_removed"], before - after)
        self.assertEqual(self._orphan_rows_on_fresh_connection(refused[0]), 1)
        self.assertEqual(results["chapters_failed"], refused)

    def test_removed_count_is_orphan_rows_not_chapters(self):
        chapter_name, ghost = self._chapter_with_orphan(orphans=3)
        results, really_removed = self._run_live()

        self.assertFalse(
            frappe.db.exists("Chapter Member", {"parent": chapter_name, "member": ["like", "Assoc-Member-GHOST-%"]})
        )
        self.assertEqual(results["orphaned_removed"], really_removed)
        self.assertGreaterEqual(results["orphaned_removed"], 3)
        mine = [c for c in results["chapters_affected"] if c["chapter"] == chapter_name][0]
        self.assertEqual(mine["orphaned_count"], 3)
        # Rows, not chapters: this chapter adds 3 rows but only 1 chapter.
        self.assertGreater(results["orphaned_removed"], results["chapters_cleaned"])

    def test_a_chapter_that_cannot_be_loaded_inherits_no_failure_from_its_predecessor(self):
        from unittest.mock import patch

        from verenigingen.verenigingen.doctype.chapter.chapter import Chapter

        # Created first, so the default newest-first listing visits the orphan chapter
        # BEFORE it; asserted below so the ordering premise cannot silently drift.
        unloadable = self.create_chapter(chapter_name=f"TEST-Unloadable-{frappe.generate_hash()[:8]}").name
        with_orphans, ghost = self._chapter_with_orphan(orphans=2)
        listed = [c.name for c in frappe.get_all("Chapter", fields=["name"])]
        self.assertLess(listed.index(with_orphans), listed.index(unloadable))

        real_load = Chapter.load_from_db

        def load_from_db(doc, *args, **kwargs):
            if doc.name == unloadable:
                raise frappe.ValidationError("cannot load")
            return real_load(doc, *args, **kwargs)

        # Mock justified: forces a load failure for one chapter; the cleanup runs for real.
        with patch.object(Chapter, "load_from_db", load_from_db), patch.object(frappe.db, "commit"):
            results = cleanup.cleanup_orphaned_chapter_members(dry_run=False)

        self.assertEqual(results["orphaned_removed"], 2)
        self.assertEqual(results["chapters_cleaned"], 1)
        self.assertEqual(results["chapters_failed"], [])
        self.assertEqual([e.split(":")[0] for e in results["errors"]], [unloadable])
        self.assertNotIn("kept their orphans", results["summary"])

    def test_a_failure_after_the_write_rolls_the_chapter_back(self):
        from unittest.mock import patch

        from verenigingen.verenigingen.doctype.chapter.chapter import Chapter

        chapter_name, ghost = self._chapter_with_orphan()

        def on_update(doc, *args, **kwargs):
            if doc.name == chapter_name:
                raise frappe.ValidationError("boom after write")

        # Mock justified: injects a failure at a real Frappe event, after the child
        # rows have been written; everything else runs for real.
        with patch.object(Chapter, "on_update", on_update, create=True):
            results, really_removed = self._run_live()

        self.assertTrue(self._row_exists(chapter_name, ghost), "failed chapter must roll back")
        self.assertIn(chapter_name, results["chapters_failed"])
        self.assertEqual(results["orphaned_removed"], really_removed)
        self.assertIn("boom after write", " ".join(results["errors"]))
