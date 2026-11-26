"""#1935 residuals: process-wide in-memory caches must carry the site in their key.

One gunicorn/RQ worker can serve several sites, and a module-level dict outlives
the request, so a key built from the arguments alone (an Address name, a
Chapter name) serves site A's row to site B whenever both sites hold a row with
that name. The lru_cache meta caches were fixed in #2805; these are the two
dict caches it left open:

* ``address_formatter._cached_address_payload`` (``cache_with_ttl``, a formatted
  address, i.e. PII, ``per_user=False``)
* ``user_role_profile_calculator._profile_config_cache`` (chapter/team profile
  configuration, which decides which role profiles a user is granted)

SITE SWAP (stated, not hidden): the suite has one database connection, so
"site B" is simulated by (1) relabelling ``frappe.local.site``, which is what
both cache keys read, and (2) rewriting the row the two sites share a name for,
so a stale answer is distinguishable from a fresh one. This proves the key
carries the site; it does not prove a real second connection.
"""

import frappe

from verenigingen.services.member.account import user_role_profile_calculator as calc
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils import address_formatter as af
from verenigingen.utils.error_handling import cache_with_ttl

SITE_A = "site-a-1935.example"
SITE_B = "site-b-1935.example"


class _SiteSwapMixin:
    def _as_site(self, site):
        # Mock justified: execution-context assignment; both caches key on
        # frappe.local.site and the suite owns a single DB connection.
        frappe.local.site = site

    def _remember_site(self):
        original = frappe.local.site
        self.addCleanup(setattr, frappe.local, "site", original)


class TestAddressPayloadCacheIsSiteScoped(_SiteSwapMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._remember_site()
        af._cached_address_payload.cache_clear()
        self.addCleanup(af._cached_address_payload.cache_clear)
        self.address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": f"Addr1935-{frappe.generate_hash(length=6)}",
                "address_type": "Personal",
                "address_line1": "Siteastraat 1",
                "city": "Amsterdam",
                "country": "Netherlands",
            }
        ).insert(ignore_permissions=True)
        self.track_doc("Address", self.address.name)

    def test_site_b_does_not_read_site_a_address(self):
        self._as_site(SITE_A)
        first = af._cached_address_payload(self.address.name)
        self.assertIn("Siteastraat 1", first["formatted_address"])

        # Site B holds an Address with the SAME name but different content.
        frappe.db.set_value("Address", self.address.name, "address_line1", "Sitebstraat 99")
        self._as_site(SITE_B)
        second = af._cached_address_payload(self.address.name)
        self.assertIn(
            "Sitebstraat 99",
            second["formatted_address"],
            "site B was served site A's cached address: the key carries no site",
        )

    def test_same_site_still_hits_the_cache(self):
        """Control: scoping by site must not turn the cache off."""
        self._as_site(SITE_A)
        af._cached_address_payload(self.address.name)
        frappe.db.set_value("Address", self.address.name, "address_line1", "Veranderd 5")
        again = af._cached_address_payload(self.address.name)
        self.assertIn("Siteastraat 1", again["formatted_address"], "same-site call must be cached")

    def test_cache_clear_clears_every_site(self):
        """cache_clear, called from another site, must still empty site A's entry."""
        self._as_site(SITE_A)
        af._cached_address_payload(self.address.name)
        self._as_site(SITE_B)
        af._cached_address_payload.cache_clear()
        frappe.db.set_value("Address", self.address.name, "address_line1", "Nacleaar 7")
        self._as_site(SITE_A)
        again = af._cached_address_payload(self.address.name)
        self.assertIn("Nacleaar 7", again["formatted_address"])

    def test_decorator_scopes_per_user_false_by_site(self):
        """The decorator itself, not only this call site: any per_user=False cache."""
        calls = []

        @cache_with_ttl(ttl=300, per_user=False)
        def reference_list_1935():
            calls.append(frappe.local.site)
            return [frappe.local.site]

        self._as_site(SITE_A)
        self.assertEqual(reference_list_1935(), [SITE_A])
        self._as_site(SITE_B)
        self.assertEqual(reference_list_1935(), [SITE_B])
        self._as_site(SITE_A)
        self.assertEqual(reference_list_1935(), [SITE_A])
        self.assertEqual(calls, [SITE_A, SITE_B], "A's entry must survive B's and be reused")


class TestProfileConfigCacheIsSiteScoped(_SiteSwapMixin, EnhancedTestCase):
    PROFILE_A = "Verenigingen Chapter Board Member"
    PROFILE_B = "Verenigingen Member"

    def setUp(self):
        super().setUp()
        self._remember_site()
        calc.invalidate_profile_config_cache()
        self.addCleanup(calc.invalidate_profile_config_cache)
        for profile in (self.PROFILE_A, self.PROFILE_B):
            self.assertTrue(frappe.db.exists("Role Profile", profile), f"fixture: {profile} missing")
        self.chapter = self.create_test_chapter()

    def _set_default_profile(self, profile):
        # Probe shortcut (stated): db.set_value stands in for "site B's chapter of
        # the same name is configured differently"; no hook is exercised here.
        frappe.db.set_value("Chapter", self.chapter.name, "default_board_role_profile", profile)
        frappe.clear_document_cache("Chapter", self.chapter.name)

    def test_site_b_does_not_read_site_a_chapter_profile_config(self):
        self._set_default_profile(self.PROFILE_A)
        self._as_site(SITE_A)
        first = calc._get_cached_chapter_profile_config(self.chapter.name)
        self.assertEqual(first["default_profile"], self.PROFILE_A)

        self._set_default_profile(self.PROFILE_B)
        self._as_site(SITE_B)
        second = calc._get_cached_chapter_profile_config(self.chapter.name)
        self.assertEqual(
            second["default_profile"],
            self.PROFILE_B,
            "site B was served site A's cached chapter profile config",
        )

    def test_site_b_does_not_read_site_a_team_profile_config(self):
        team = self.create_test_team()
        frappe.db.set_value("Team", team.name, "default_role_profile", self.PROFILE_A)
        frappe.clear_document_cache("Team", team.name)
        self._as_site(SITE_A)
        self.assertEqual(calc._get_cached_team_profile_config(team.name)["default_profile"], self.PROFILE_A)

        frappe.db.set_value("Team", team.name, "default_role_profile", self.PROFILE_B)
        frappe.clear_document_cache("Team", team.name)
        self._as_site(SITE_B)
        self.assertEqual(
            calc._get_cached_team_profile_config(team.name)["default_profile"],
            self.PROFILE_B,
            "site B was served site A's cached team profile config",
        )

    def test_same_site_still_hits_the_cache(self):
        """Control: the cache must still cache within one site."""
        self._set_default_profile(self.PROFILE_A)
        self._as_site(SITE_A)
        calc._get_cached_chapter_profile_config(self.chapter.name)
        self._set_default_profile(self.PROFILE_B)
        again = calc._get_cached_chapter_profile_config(self.chapter.name)
        self.assertEqual(again["default_profile"], self.PROFILE_A, "same-site call must be cached")

    def test_invalidation_still_evicts_the_site_keyed_entry(self):
        """Per-entity, per-type and global eviction must find the site-prefixed keys."""
        for kwargs in (
            {"entity_type": "chapter", "entity_name": None},
            {"entity_type": "chapter", "entity_name": "__name__"},
            {},
        ):
            with self.subTest(kwargs=kwargs):
                self._set_default_profile(self.PROFILE_A)
                self._as_site(SITE_A)
                calc._get_cached_chapter_profile_config(self.chapter.name)
                self._set_default_profile(self.PROFILE_B)
                kw = dict(kwargs)
                if kw.get("entity_name") == "__name__":
                    kw["entity_name"] = self.chapter.name
                calc.invalidate_profile_config_cache(**kw)
                self.assertEqual(
                    calc._get_cached_chapter_profile_config(self.chapter.name)["default_profile"],
                    self.PROFILE_B,
                    f"invalidate_profile_config_cache({kw}) left the entry in place",
                )
