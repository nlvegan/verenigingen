"""
Integration tests for verenigingen/utils/cache_invalidation.py.

Exercises CacheInvalidationManager against the REAL frappe.cache() (shared
Redis) and real Member/Volunteer/SEPA Mandate documents created via the
factory. Cache assertions follow the set-then-get / invalidate-then-miss
pattern and operate ONLY on keys derived from this test's own freshly
created records, so no other suite's namespace is touched.

The stats-tracking key ("cache_invalidation_stats") is global; tests that
exercise it snapshot and restore the prior value in tearDown to avoid
polluting other suites.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.cache_invalidation import (
    CacheInvalidationManager,
    on_document_cancel,
    on_document_submit,
    on_document_update,
)
from verenigingen.utils.optimized_queries import QueryCache

STATS_KEY = "cache_invalidation_stats"


class TestCacheInvalidationManager(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member()
        # Snapshot the global stats key so we can restore it after tests
        # that mutate it (avoids cross-suite pollution).
        self._stats_backup = frappe.cache().get_value(STATS_KEY)

    def tearDown(self):
        # Restore the global stats key to its pre-test value.
        if self._stats_backup is None:
            frappe.cache().delete_value(STATS_KEY)
        else:
            frappe.cache().set_value(STATS_KEY, self._stats_backup)
        super().tearDown()

    # ---- direct member cache invalidation -------------------------------

    def test_invalidate_member_cache_removes_cached_data(self):
        QueryCache.set_cached_member_data(self.member.name, {"hello": "world"})
        self.assertIsNotNone(QueryCache.get_cached_member_data(self.member.name))

        CacheInvalidationManager._invalidate_member_cache(self.member.name)

        self.assertIsNone(
            QueryCache.get_cached_member_data(self.member.name),
            "member cache should miss after invalidation",
        )

    def test_invalidate_volunteer_assignments_cache(self):
        key = f"volunteer_assignments:{self.member.name}"
        frappe.cache().set_value(key, [{"a": 1}])
        self.assertIsNotNone(frappe.cache().get_value(key))

        CacheInvalidationManager._invalidate_volunteer_assignments_cache(self.member.name)

        self.assertIsNone(frappe.cache().get_value(key))

    # ---- document-change dispatch ---------------------------------------

    def test_member_update_invalidates_member_cache(self):
        QueryCache.set_cached_member_data(self.member.name, {"cached": True})

        member_doc = frappe.get_doc("Member", self.member.name)
        with self.assertNoErrorLog():
            CacheInvalidationManager.invalidate_on_document_change(member_doc, "on_update")

        self.assertIsNone(
            QueryCache.get_cached_member_data(self.member.name),
            "Member on_update must invalidate that member's data cache",
        )

    def test_unmapped_doctype_is_noop(self):
        # A doctype not present in CACHE_DEPENDENCIES must return early.
        QueryCache.set_cached_member_data(self.member.name, {"cached": True})

        # "User" is not in CACHE_DEPENDENCIES; pass any real document.
        user_doc = frappe.get_doc("User", "Administrator")
        with self.assertNoErrorLog():
            CacheInvalidationManager.invalidate_on_document_change(user_doc, "on_update")

        # Member cache untouched because dispatch returned early.
        self.assertEqual(
            QueryCache.get_cached_member_data(self.member.name), {"cached": True}
        )

    def test_member_update_clears_financial_summary_caches(self):
        # Member is in CACHE_DEPENDENCIES with invalidate_financial=True.
        keys = [
            f"member_financial_summary:{self.member.name}",
            f"member_payment_history:{self.member.name}",
            f"member_outstanding_balance:{self.member.name}",
        ]
        for k in keys:
            frappe.cache().set_value(k, {"x": 1})
        for k in keys:
            self.assertIsNotNone(frappe.cache().get_value(k))

        member_doc = frappe.get_doc("Member", self.member.name)
        CacheInvalidationManager.invalidate_on_document_change(member_doc, "on_update")

        for k in keys:
            self.assertIsNone(
                frappe.cache().get_value(k),
                f"financial cache {k} should be cleared on member change",
            )

    # ---- affected-member resolution -------------------------------------

    def test_get_affected_members_for_member(self):
        member_doc = frappe.get_doc("Member", self.member.name)
        affected = CacheInvalidationManager._get_affected_members(member_doc)
        self.assertEqual(affected, [self.member.name])

    def test_get_affected_members_for_customer(self):
        # The member created by the factory has a linked Customer; a Customer
        # change must resolve back to that member via the customer link.
        member_doc = frappe.get_doc("Member", self.member.name)
        customer = member_doc.customer
        self.assertTrue(customer, "factory member should have a linked customer")

        customer_doc = frappe.get_doc("Customer", customer)
        affected = CacheInvalidationManager._get_affected_members(customer_doc)
        self.assertIn(self.member.name, affected)

    def test_customer_change_invalidates_linked_member_cache(self):
        member_doc = frappe.get_doc("Member", self.member.name)
        customer = member_doc.customer
        QueryCache.set_cached_member_data(self.member.name, {"cached": True})

        customer_doc = frappe.get_doc("Customer", customer)
        CacheInvalidationManager.invalidate_on_document_change(customer_doc, "on_update")

        self.assertIsNone(
            QueryCache.get_cached_member_data(self.member.name),
            "Customer change must cascade to the linked member's data cache",
        )

    # ---- stats tracking --------------------------------------------------

    def test_tracking_increments_total_and_per_doctype(self):
        # Start from a clean stats baseline for a deterministic assertion.
        frappe.cache().delete_value(STATS_KEY)

        member_doc = frappe.get_doc("Member", self.member.name)
        CacheInvalidationManager.invalidate_on_document_change(member_doc, "on_update")
        CacheInvalidationManager.invalidate_on_document_change(member_doc, "on_update")

        stats = CacheInvalidationManager.get_cache_invalidation_stats()
        self.assertEqual(stats.get("total_invalidations"), 2)
        self.assertEqual(stats.get("Member_on_update"), 2)
        self.assertIn("last_invalidation", stats)

    def test_get_stats_returns_dict_when_empty(self):
        frappe.cache().delete_value(STATS_KEY)
        self.assertEqual(CacheInvalidationManager.get_cache_invalidation_stats(), {})

    # ---- hook handler wrappers ------------------------------------------

    def test_hook_handlers_dispatch_with_correct_method(self):
        frappe.cache().delete_value(STATS_KEY)
        member_doc = frappe.get_doc("Member", self.member.name)

        on_document_update(member_doc, "on_update")
        on_document_submit(member_doc, "on_submit")
        on_document_cancel(member_doc, "on_cancel")

        stats = CacheInvalidationManager.get_cache_invalidation_stats()
        self.assertEqual(stats.get("total_invalidations"), 3)
        self.assertEqual(stats.get("Member_on_update"), 1)
        self.assertEqual(stats.get("Member_on_submit"), 1)
        self.assertEqual(stats.get("Member_on_cancel"), 1)

    # ---- cache warming ---------------------------------------------------

    def test_warm_cache_for_member_populates_member_data(self):
        # Ensure a clean slate, then warm and confirm the member data is cached.
        QueryCache.invalidate_member_cache(self.member.name)
        self.assertIsNone(QueryCache.get_cached_member_data(self.member.name))

        with self.assertNoErrorLog():
            CacheInvalidationManager.warm_cache_for_member(self.member.name)

        cached = QueryCache.get_cached_member_data(self.member.name)
        self.assertIsNotNone(cached, "warming should populate member data cache")
        self.assertEqual(cached.get("name"), self.member.name)

    def test_warm_cache_for_nonexistent_member_does_not_raise(self):
        # warm_cache_for_member swallows errors (logs them); confirm no raise.
        # We expect an error log here because the member does not exist, so we
        # mark the cache-warming failure title as expected for the tearDown check.
        self.expectErrorLog("Cache warming failed")
        # Must not raise even though the underlying get_doc fails.
        CacheInvalidationManager.warm_cache_for_member("NON-EXISTENT-MEMBER-XYZ")

    # ---- bulk pattern invalidation --------------------------------------

    def test_bulk_invalidate_member_pattern_clears_stat_counters(self):
        # _bulk_invalidate_member_caches deletes the cache_stats:hits/misses keys.
        frappe.cache().set_value("cache_stats:hits", 5)
        frappe.cache().set_value("cache_stats:misses", 3)

        CacheInvalidationManager.bulk_invalidate_pattern("member_*")

        self.assertIsNone(frappe.cache().get_value("cache_stats:hits"))
        self.assertIsNone(frappe.cache().get_value("cache_stats:misses"))

    def test_bulk_invalidate_unknown_pattern_is_noop(self):
        # An unrecognized pattern must not raise.
        with self.assertNoErrorLog():
            CacheInvalidationManager.bulk_invalidate_pattern("totally_unknown_*")
