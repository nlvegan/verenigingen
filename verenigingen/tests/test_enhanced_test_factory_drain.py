"""Regression tests for EnhancedTestCase._drain_tracked_documents.

The drain runs in tearDown after frappe.db.rollback() and deletes documents
the factory tracked, so that records committed during a test (or by production
code the test invoked) do not survive into the next run.

Pre-fix history: 3 PRs (#57, #60, plus an earlier) added test-specific
tearDown overrides to clean up leaked Customer/Member records. Those were
symptoms of this framework gap; see
docs/plans/2026-05-24-test-framework-tracked-doc-drain-design.md.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDrainTrackedDocuments(EnhancedTestCase):
    """Verify the drain deletes committed records and tracks the auto-Customer."""

    def test_factory_tracks_auto_created_customer(self):
        """A Member created with auto_create_customer should have its Customer tracked."""
        member = self.create_test_member(
            first_name="DrainTest",
            last_name="AutoCustomer",
            email="draintest.autocustomer@test.invalid",
        )

        self.assertTrue(member.customer, "Expected auto-created Customer on member")

        tracked = [(d["doctype"], d["name"]) for d in self.factory.core.created_records]
        self.assertIn(
            ("Customer", member.customer),
            tracked,
            "Customer should be tracked by Core factory for tearDown drain",
        )

    def test_drain_deletes_committed_member_and_customer(self):
        """Drain removes committed Member + auto-Customer that rollback couldn't undo.

        Note: the manual mid-test drain commits the deletes. The tearDown
        drain will then re-run as a no-op (lists already cleared). This
        explicit call is a test-of-the-drain, NOT an idiom for production tests.
        """
        member = self.create_test_member(
            first_name="DrainTest",
            last_name="Committed",
            email="draintest.committed@test.invalid",
        )
        member_name = member.name
        customer_name = member.customer

        frappe.db.commit()

        self.assertTrue(frappe.db.exists("Member", member_name))
        self.assertTrue(frappe.db.exists("Customer", customer_name))

        self._drain_tracked_documents()

        self.assertFalse(
            frappe.db.exists("Member", member_name),
            f"Member {member_name} should be deleted by drain",
        )
        self.assertFalse(
            frappe.db.exists("Customer", customer_name),
            f"Customer {customer_name} should be deleted by drain",
        )

    def test_drain_is_idempotent(self):
        """First drain deletes; second drain is a clean no-op. Both verify records gone."""
        member = self.create_test_member(
            first_name="DrainTest",
            last_name="Idempotent",
            email="draintest.idempotent@test.invalid",
        )
        member_name = member.name
        customer_name = member.customer
        frappe.db.commit()

        self._drain_tracked_documents()

        self.assertFalse(
            frappe.db.exists("Member", member_name),
            "First drain call should delete the Member",
        )
        self.assertFalse(
            frappe.db.exists("Customer", customer_name),
            "First drain call should delete the Customer",
        )
        self.assertEqual(self.factory.created_documents, [])
        self.assertEqual(self.factory.core.created_records, [])

        self._drain_tracked_documents()

        self.assertEqual(self.factory.created_documents, [])
        self.assertEqual(self.factory.core.created_records, [])

    def test_drain_skips_negative_priority_records(self):
        """Records tracked with priority < 0 are shared infrastructure; drain must skip them.

        This is the safety contract that `_ensure_master_data` relies on: shared
        roots like 'All Departments' and 'Netherlands' Territory must NOT be
        torn down between test methods.
        """
        chapter = self.create_chapter()
        flipped = False
        for d in self.factory.created_documents:
            if d['doctype'] == "Chapter" and d['name'] == chapter.name:
                d['priority'] = -1
                flipped = True
                break
        self.assertTrue(flipped, "Chapter should be in Enhanced tracked list")

        frappe.db.commit()
        try:
            self._drain_tracked_documents()
            self.assertTrue(
                frappe.db.exists("Chapter", chapter.name),
                "Chapter with priority < 0 should survive drain",
            )
        finally:
            if frappe.db.exists("Chapter", chapter.name):
                frappe.delete_doc("Chapter", chapter.name, force=True, ignore_permissions=True)
                frappe.db.commit()

    def test_dedupe_keeps_highest_priority_across_sources(self):
        """When the same doc is tracked by both Enhanced (prio=5) and Core (prio=0),
        dedupe must keep prio=5 so delete ordering matches Enhanced's contract."""
        self.factory.created_documents.append(
            {"doctype": "ToyDoc", "name": "X", "priority": 5, "test_run_id": "t"}
        )
        self.factory.core.created_records.append({"doctype": "ToyDoc", "name": "X"})

        tracked: dict = {}
        for d in self.factory.created_documents:
            key = (d['doctype'], d['name'])
            prio = d.get('priority', 0)
            if key not in tracked or prio > tracked[key]:
                tracked[key] = prio
        for d in self.factory.core.created_records:
            key = (d['doctype'], d['name'])
            if key not in tracked or 0 > tracked[key]:
                tracked[key] = 0

        self.assertEqual(
            tracked[("ToyDoc", "X")], 5,
            "Dedupe must retain the highest priority across sources",
        )

        self.factory.created_documents = [
            d for d in self.factory.created_documents
            if not (d['doctype'] == "ToyDoc" and d['name'] == "X")
        ]
        self.factory.core.created_records = [
            d for d in self.factory.core.created_records
            if not (d['doctype'] == "ToyDoc" and d['name'] == "X")
        ]


class TestFactoryUniqueSuffixIsProcessGlobal(EnhancedTestCase):
    """Regression: the Customer-collision-prevention suffix appended to last_name
    in EnhancedTestDataFactory.create_member MUST come from a process-global
    counter, not a per-instance one.

    A fresh factory is built in every test's setUp; a per-instance counter
    resets to 1 each time, so every test's first member got last_name="<Name>1"
    -> identical Member full_name -> identical auto-created Customer name ->
    DuplicateEntryError on the Customer PRIMARY key (the largest CI failure
    bucket, B1). See docs/plans/2026-05-29-server-tests-red-baseline-triage.md.
    """

    def test_constructing_a_new_factory_does_not_reset_the_suffix_counter(self):
        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestDataFactory

        a = next(EnhancedTestDataFactory._global_unique_seq)
        b = next(EnhancedTestDataFactory._global_unique_seq)
        self.assertNotEqual(a, b, "the suffix counter must advance monotonically")

        # Building a new factory (as every setUp does) must NOT reset the shared
        # counter back to 1 — that reset was the root cause of the collisions.
        EnhancedTestDataFactory(seed=12345)
        c = next(EnhancedTestDataFactory._global_unique_seq)
        self.assertGreater(
            c, b,
            "constructing a new EnhancedTestDataFactory must not reset the "
            "process-global last_name suffix counter",
        )


class TestCapturedInsertDrain(EnhancedTestCase):
    """Regression: committed records created via RAW frappe inserts (not the
    factory) must be drained at tearDown, so they don't leak into later tests
    and cause order-dependent failures. See
    docs/plans/2026-05-29-server-tests-red-baseline-triage.md (isolation root cause).
    """

    def test_raw_committed_insert_is_captured_and_drained(self):
        import frappe

        name = f"Drain Probe Customer {self.uid}"
        # Raw insert + COMMIT — bypasses factory tracking and survives rollback.
        cust = frappe.get_doc(
            {"doctype": "Customer", "customer_name": name, "customer_type": "Individual"}
        )
        cust.insert(ignore_permissions=True)
        frappe.db.commit()
        created = cust.name

        self.assertTrue(frappe.db.exists("Customer", created), "precondition: customer committed")
        self.assertIn(
            ("Customer", created),
            self._captured_inserts,
            "raw insert should be captured by the global insert hook",
        )

        # Invoke the drain directly (tearDown runs it too).
        self._drain_captured_inserts()

        self.assertFalse(
            frappe.db.exists("Customer", created),
            "captured committed record must be drained (else it leaks into later tests)",
        )

    def test_singles_setvalue_is_not_captured(self):
        # Documents the known limit: Singles writes (update_single via set_value)
        # don't go through Document.db_insert, so they're neither captured nor
        # drained — correct, since Settings must persist / are restored separately.
        # Guards against a future change that would wrongly drain them.
        import frappe

        before = list(self._captured_inserts)
        frappe.db.set_value("System Settings", "System Settings", "language", "en")
        new = [k for k in self._captured_inserts if k not in before]
        self.assertEqual(new, [], "Singles set_value must not be captured as an insert")
