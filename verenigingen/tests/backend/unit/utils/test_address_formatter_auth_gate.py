"""#785: `format_member_address`'s permission checks must survive a WARM cache.

Companion to test_chapter_dashboard_page.py's warm-cache test. `format_member_address`
(verenigingen/utils/address_formatter.py) used to run its two `frappe.has_permission`
checks INSIDE the function body that `cache_with_ttl` memoized (#782). #784 closed the
exposure by keying the cache per session user; #785 hoists the checks out instead, so
the formatted-address payload can go back to a shared (`per_user=False`) cache without
reintroducing the bypass -- which only a warm-cache assertion can prove.
"""

from unittest import mock

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles


class TestFormatMemberAddressAuthCheckSurvivesWarmCache(EnhancedTestCase):
    def setUp(self):
        super().setUp()

        self.owner, self.owner_user = self._make_member_with_user("Owner785")
        self.intruder, self.intruder_user = self._make_member_with_user("Intruder785")

        # format_member_address is @high_security_api, which (post audit #2 Rule-5
        # cap) requires an assigned role PROFILE, not just a bare role, to clear
        # HIGH. Grant both test users a profile that clears it -- this affects
        # ONLY the outer @high_security_api gate; the actual authorization under
        # test (own-record access via Member.user / Address Dynamic Link) is
        # role-agnostic, so the intruder is still refused on that check.
        grant_matching_role_profiles(self.owner_user, "Verenigingen Chapter Board Member")
        grant_matching_role_profiles(self.intruder_user, "Verenigingen Chapter Board Member")

        self.address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": self.owner.name,
                "address_type": "Personal",
                "address_line1": "Teststraat 1",
                "city": "Amsterdam",
                "country": "Netherlands",
                "links": [{"link_doctype": "Member", "link_name": self.owner.name}],
            }
        ).insert(ignore_permissions=True)
        self.track_doc("Address", self.address.name)

        self.owner.db_set("primary_address", self.address.name)
        self.owner.reload()

    def _make_member_with_user(self, label):
        email = f"addrfmt785-{label.lower()}-{frappe.generate_hash()[:8]}@example.com"
        member = self.create_test_member(
            first_name=label,
            last_name="Portal",
            email=email,
            birth_date="1985-06-15",
        )
        # The factory may uniquify the email for isolation; read back the real one.
        email = member.email
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": label,
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        member.db_set("user", email)
        member.reload()
        return member, email

    def test_unauthorized_user_is_refused_on_a_warm_shared_cache(self):
        from verenigingen.utils import address_formatter as af

        af._cached_address_payload.cache_clear()

        with mock.patch.object(
            af, "_build_address_payload", wraps=af._build_address_payload
        ) as spy:
            # Cold cache: the owner's call builds and caches the formatted address.
            frappe.set_user(self.owner_user)
            first = af.format_member_address(self.owner.name)
            first_data = first.get("data", first) if isinstance(first, dict) else first
            self.assertTrue(first_data["has_address"])
            self.assertEqual(spy.call_count, 1, "cold cache: the address must be formatted once")

            # Warm cache, same address: because the cache is per_user=False, a
            # second call is served from the shared entry without rebuilding it.
            second = af.format_member_address(self.owner.name)
            second_data = second.get("data", second) if isinstance(second, dict) else second
            self.assertTrue(second_data["has_address"])
            self.assertEqual(
                spy.call_count, 1, "a second call for the same address should hit the shared cache"
            )

            # An unauthorized caller, on this SAME warm cache, must still be
            # refused. Before #785, the has_permission checks ran INSIDE the
            # cached body, so a cache hit returned before they ever executed --
            # this is the regression only a warm-cache assertion can catch.
            frappe.set_user(self.intruder_user)
            refused = af.format_member_address(self.owner.name)

        refused_data = refused.get("data", refused) if isinstance(refused, dict) else refused
        self.assertFalse(
            refused_data["has_address"],
            "an unauthorized caller must be refused, warm cache or not",
        )
        self.assertEqual(
            spy.call_count,
            1,
            "the payload builder must never run for an unauthorized caller -- the "
            "permission checks must gate access, not the cache key",
        )

    def test_owner_still_gets_their_own_address(self):
        """Control: the refusal above is authorization-based, not a blanket failure."""
        from verenigingen.utils import address_formatter as af

        af._cached_address_payload.cache_clear()

        frappe.set_user(self.owner_user)
        result = af.format_member_address(self.owner.name)
        data = result.get("data", result) if isinstance(result, dict) else result

        self.assertTrue(data["has_address"])
        self.assertIn("Teststraat 1", data["formatted_address"])
