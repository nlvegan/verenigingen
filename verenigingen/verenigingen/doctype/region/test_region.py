# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import random

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestRegion(EnhancedTestCase):
    """Focused test suite for Region doctype - tests actual functionality, not implementation details"""

    def setUp(self):
        """Set up test data"""
        super().setUp()

    @staticmethod
    def get_unique_suffix():
        """Generate unique suffix using timestamp + random to avoid collisions"""
        import time

        timestamp = str(int(time.time() * 1000000) % 1000000)
        rand_suffix = random.randint(100, 999)
        return f"{timestamp}-{rand_suffix}"

    # ------------------------------------------------------------------
    # Helpers (privileged creation lives here, never in test bodies)
    # ------------------------------------------------------------------
    def _make_region(self, save=True, **overrides):
        """Build (and optionally save) a Region with a guaranteed-unique
        name + code. Overrides win over the generated defaults."""
        suffix = self.get_unique_suffix()
        data = {
            "doctype": "Region",
            "region_name": f"Test Region {suffix}",
            # region_code must be 2-5 [A-Z0-9]; take 4 digits of the suffix
            "region_code": f"R{suffix.replace('-', '')[:4]}",
            "country": "Netherlands",
        }
        data.update(overrides)
        region = frappe.get_doc(data)
        if save:
            region.insert(ignore_permissions=True)
            self.track_doc("Region", region.name)
        return region

    def _make_chapter_in_region(self, region_name, **overrides):
        """Create a Chapter linked to the given region."""
        return self.create_test_chapter(region=region_name, **overrides)

    # ------------------------------------------------------------------
    # validate_required_fields
    # ------------------------------------------------------------------
    def test_missing_region_name_rejected(self):
        """region_name is required; absence must throw."""
        region = frappe.get_doc({"doctype": "Region", "region_code": "ABCD"})
        with self.assertRaises(frappe.ValidationError):
            region.insert(ignore_permissions=True)

    def test_missing_region_code_rejected(self):
        """region_code is required; absence must throw."""
        suffix = self.get_unique_suffix()
        region = frappe.get_doc({"doctype": "Region", "region_name": f"NoCode {suffix}"})
        with self.assertRaises(frappe.ValidationError):
            region.insert(ignore_permissions=True)

    # ------------------------------------------------------------------
    # validate_region_code
    # ------------------------------------------------------------------
    def test_region_code_is_uppercased_and_stripped(self):
        """Lowercase/whitespace region codes are normalised to upper+strip."""
        region = self._make_region(save=False, region_code="  zh1 ")
        region.insert(ignore_permissions=True)
        self.track_doc("Region", region.name)
        self.assertEqual(region.region_code, "ZH1")

    def test_region_code_too_short_rejected(self):
        """A 1-char code violates the 2-5 length rule."""
        region = self._make_region(save=False, region_code="A")
        with self.assertRaises(frappe.ValidationError):
            region.insert(ignore_permissions=True)

    def test_region_code_too_long_rejected(self):
        """A 6-char code exceeds the 5-char maximum."""
        region = self._make_region(save=False, region_code="ABCDEF")
        with self.assertRaises(frappe.ValidationError):
            region.insert(ignore_permissions=True)

    def test_region_code_invalid_chars_rejected(self):
        """Codes with non-alphanumeric chars are rejected."""
        region = self._make_region(save=False, region_code="A-B")
        with self.assertRaises(frappe.ValidationError):
            region.insert(ignore_permissions=True)

    def test_region_code_uniqueness_case_insensitive(self):
        """Because the code is upper-cased before the uniqueness check, a
        lowercase duplicate must still collide with an existing upper code."""
        base = self._make_region(region_code="UNQ1")
        dup = self._make_region(save=False, region_code="unq1")
        with self.assertRaises(frappe.ValidationError):
            dup.insert(ignore_permissions=True)

    # ------------------------------------------------------------------
    # validate_coordinators
    # ------------------------------------------------------------------
    def test_nonexistent_coordinator_rejected(self):
        """A regional_coordinator that is not a real Member must throw."""
        region = self._make_region(save=False, regional_coordinator="NOT-A-REAL-MEMBER-xyz")
        with self.assertRaises(frappe.ValidationError):
            region.insert(ignore_permissions=True)

    def test_nonexistent_backup_coordinator_rejected(self):
        """A backup_coordinator that is not a real Member must throw."""
        region = self._make_region(save=False, backup_coordinator="NOT-A-REAL-MEMBER-xyz")
        with self.assertRaises(frappe.ValidationError):
            region.insert(ignore_permissions=True)

    def test_backup_cannot_equal_main_coordinator(self):
        """Backup and main coordinator must differ."""
        coordinator = self.create_test_member()
        region = self._make_region(
            save=False,
            regional_coordinator=coordinator.name,
            backup_coordinator=coordinator.name,
        )
        with self.assertRaises(frappe.ValidationError):
            region.insert(ignore_permissions=True)

    def test_distinct_coordinators_accepted(self):
        """Two distinct, existing members are valid coordinators."""
        main = self.create_test_member()
        backup = self.create_test_member()
        region = self._make_region(regional_coordinator=main.name, backup_coordinator=backup.name)
        self.assertEqual(region.regional_coordinator, main.name)
        self.assertEqual(region.backup_coordinator, backup.name)

    # ------------------------------------------------------------------
    # validate_contact_info
    # ------------------------------------------------------------------
    def test_invalid_email_rejected(self):
        """A malformed regional_email must throw."""
        region = self._make_region(save=False, regional_email="not-an-email")
        with self.assertRaises(frappe.ValidationError):
            region.insert(ignore_permissions=True)

    def test_valid_email_accepted(self):
        region = self._make_region(regional_email="region@example.com")
        self.assertEqual(region.regional_email, "region@example.com")

    def test_website_url_gets_https_prefix(self):
        """A bare domain is normalised to https:// during validation."""
        region = self._make_region(website_url="example.org")
        self.assertEqual(region.website_url, "https://example.org")

    def test_website_url_leading_slash_stripped_before_prefix(self):
        """Leading slashes are stripped before the https:// prefix is added."""
        region = self._make_region(website_url="//example.org/path")
        self.assertEqual(region.website_url, "https://example.org/path")

    def test_website_url_http_preserved(self):
        """An already-schemed URL is left untouched."""
        region = self._make_region(website_url="http://example.org")
        self.assertEqual(region.website_url, "http://example.org")

    # ------------------------------------------------------------------
    # validate_membership_fee_adjustment
    # ------------------------------------------------------------------
    def test_fee_adjustment_below_minimum_rejected(self):
        region = self._make_region(save=False, membership_fee_adjustment=0.05)
        with self.assertRaises(frappe.ValidationError):
            region.insert(ignore_permissions=True)

    def test_fee_adjustment_above_maximum_rejected(self):
        region = self._make_region(save=False, membership_fee_adjustment=2.5)
        with self.assertRaises(frappe.ValidationError):
            region.insert(ignore_permissions=True)

    def test_fee_adjustment_within_range_accepted(self):
        region = self._make_region(membership_fee_adjustment=1.5)
        self.assertEqual(region.membership_fee_adjustment, 1.5)

    def test_fee_adjustment_boundaries_accepted(self):
        """0.1 and 2.0 are inclusive boundaries."""
        low = self._make_region(membership_fee_adjustment=0.1)
        high = self._make_region(membership_fee_adjustment=2.0)
        self.assertEqual(low.membership_fee_adjustment, 0.1)
        self.assertEqual(high.membership_fee_adjustment, 2.0)

    # ------------------------------------------------------------------
    # update_route / before_save
    # ------------------------------------------------------------------
    def test_route_is_generated_from_region_name(self):
        """before_save -> update_route should slug the region name into a route."""
        region = self._make_region(region_name="North Holland Test 42")
        self.assertTrue(region.route.startswith("regions/"))
        self.assertEqual(region.route, f"regions/{region.scrub('North Holland Test 42')}")

    # ------------------------------------------------------------------
    # parse_postal_code_patterns
    # ------------------------------------------------------------------
    def test_parse_postal_code_patterns_strips_and_drops_empties(self):
        region = self._make_region(postal_code_patterns="1000-1999,  2500 , , 3*")
        self.assertEqual(region.parse_postal_code_patterns(), ["1000-1999", "2500", "3*"])

    def test_parse_postal_code_patterns_empty_returns_empty_list(self):
        region = self._make_region()
        self.assertEqual(region.parse_postal_code_patterns(), [])

    # ------------------------------------------------------------------
    # matches_postal_code / _postal_code_matches_pattern
    # ------------------------------------------------------------------
    def test_matches_postal_code_range(self):
        region = self._make_region(postal_code_patterns="1000-1999")
        self.assertTrue(region.matches_postal_code("1000"))
        self.assertTrue(region.matches_postal_code("1500"))
        self.assertTrue(region.matches_postal_code("1999"))
        self.assertFalse(region.matches_postal_code("0999"))
        self.assertFalse(region.matches_postal_code("2000"))

    def test_matches_postal_code_wildcard(self):
        region = self._make_region(postal_code_patterns="3*")
        self.assertTrue(region.matches_postal_code("3000"))
        self.assertTrue(region.matches_postal_code("3999"))
        self.assertFalse(region.matches_postal_code("4000"))

    def test_matches_postal_code_exact_prefix(self):
        region = self._make_region(postal_code_patterns="2500")
        self.assertTrue(region.matches_postal_code("2500"))
        # exact pattern uses startswith semantics
        self.assertTrue(region.matches_postal_code("25001"))
        self.assertFalse(region.matches_postal_code("2600"))

    def test_matches_postal_code_normalises_spaces(self):
        """Dutch postal codes like '1000 AB' are normalised before matching."""
        region = self._make_region(postal_code_patterns="1000-1999")
        self.assertTrue(region.matches_postal_code("1000 AB"))

    def test_matches_postal_code_multi_pattern(self):
        region = self._make_region(postal_code_patterns="1000-1999, 2500, 3*")
        self.assertTrue(region.matches_postal_code("1500"))
        self.assertTrue(region.matches_postal_code("2500"))
        self.assertTrue(region.matches_postal_code("3123"))
        self.assertFalse(region.matches_postal_code("9999"))

    def test_matches_postal_code_empty_inputs(self):
        region_no_patterns = self._make_region()
        self.assertFalse(region_no_patterns.matches_postal_code("1000"))
        region = self._make_region(postal_code_patterns="1000-1999")
        self.assertFalse(region.matches_postal_code(""))

    def test_matches_postal_code_malformed_range_no_crash(self):
        """A non-numeric range must not raise; it simply does not match."""
        region = self._make_region(postal_code_patterns="AB-CD")
        # validation only msgprints (warns) on odd patterns, it does not block;
        # matching must degrade gracefully to False, not raise.
        self.assertFalse(region.matches_postal_code("1000"))

    # ------------------------------------------------------------------
    # get_region_chapters / get_region_statistics
    # ------------------------------------------------------------------
    def test_get_region_chapters_lists_linked_chapters(self):
        region = self._make_region()
        chapter = self._make_chapter_in_region(region.name)
        chapter_names = [c["name"] for c in region.get_region_chapters()]
        self.assertIn(chapter.name, chapter_names)

    def test_get_region_chapters_empty_for_new_region(self):
        region = self._make_region()
        self.assertEqual(region.get_region_chapters(), [])

    def test_get_region_statistics_counts_chapters(self):
        region = self._make_region()
        self._make_chapter_in_region(region.name)
        self._make_chapter_in_region(region.name)
        stats = region.get_region_statistics()
        self.assertEqual(stats["total_chapters"], 2)
        self.assertIn("published_chapters", stats)
        self.assertIn("total_members", stats)

    def test_get_region_statistics_zero_for_empty_region(self):
        region = self._make_region()
        stats = region.get_region_statistics()
        self.assertEqual(stats["total_chapters"], 0)
        self.assertEqual(stats["total_members"], 0)

    # ------------------------------------------------------------------
    # get_context (dict + object forms)
    # ------------------------------------------------------------------
    def test_get_context_dict_form(self):
        region = self._make_region()
        self._make_chapter_in_region(region.name)
        context = {}
        region.get_context(context)
        self.assertEqual(context["no_cache"], 1)
        self.assertTrue(context["show_sidebar"])
        self.assertEqual(len(context["chapters"]), 1)
        self.assertEqual(context["stats"]["total_chapters"], 1)
        # No coordinator -> key absent
        self.assertNotIn("coordinator", context)

    def test_get_context_object_form_with_coordinator(self):
        import types

        coordinator = self.create_test_member()
        region = self._make_region(regional_coordinator=coordinator.name)
        context = types.SimpleNamespace()
        region.get_context(context)
        self.assertEqual(context.no_cache, 1)
        self.assertTrue(context.show_sidebar)
        self.assertEqual(context.coordinator.name, coordinator.name)

    # ------------------------------------------------------------------
    # Whitelisted utility: get_regions_for_dropdown
    # ------------------------------------------------------------------
    def test_get_regions_for_dropdown_returns_active_only(self):
        from verenigingen.verenigingen.doctype.region.region import (
            get_regions_for_dropdown,
        )

        active = self._make_region(is_active=1)
        inactive = self._make_region(is_active=0)
        names = [r["name"] for r in get_regions_for_dropdown()]
        self.assertIn(active.name, names)
        self.assertNotIn(inactive.name, names)

    # ------------------------------------------------------------------
    # Whitelisted utility: find_region_by_postal_code
    # ------------------------------------------------------------------
    def test_find_region_by_postal_code_matches(self):
        from verenigingen.verenigingen.doctype.region.region import (
            find_region_by_postal_code,
        )

        region = self._make_region(is_active=1, postal_code_patterns="7000-7999")
        # Use a pattern unlikely to collide with seed data; assert our region
        # is the one returned for a code inside its (narrow) range.
        result = find_region_by_postal_code("7500")
        self.assertEqual(result, region.name)

    def test_find_region_by_postal_code_no_match_returns_none(self):
        from verenigingen.verenigingen.doctype.region.region import (
            find_region_by_postal_code,
        )

        self._make_region(is_active=1, postal_code_patterns="7000-7999")
        self.assertIsNone(find_region_by_postal_code("0001"))

    def test_find_region_by_postal_code_empty_returns_none(self):
        from verenigingen.verenigingen.doctype.region.region import (
            find_region_by_postal_code,
        )

        self.assertIsNone(find_region_by_postal_code(""))

    # ------------------------------------------------------------------
    # Whitelisted utility: get_regional_coordinator
    # ------------------------------------------------------------------
    def test_get_regional_coordinator_returns_both_coordinators(self):
        from verenigingen.verenigingen.doctype.region.region import (
            get_regional_coordinator,
        )

        main = self.create_test_member()
        backup = self.create_test_member()
        region = self._make_region(regional_coordinator=main.name, backup_coordinator=backup.name)
        result = get_regional_coordinator(region.name)
        self.assertEqual(result["regional_coordinator"], main.name)
        self.assertEqual(result["backup_coordinator"], backup.name)

    def test_get_regional_coordinator_empty_returns_none(self):
        from verenigingen.verenigingen.doctype.region.region import (
            get_regional_coordinator,
        )

        self.assertIsNone(get_regional_coordinator(""))

    # ------------------------------------------------------------------
    # Whitelisted utility: validate_postal_code_patterns
    # ------------------------------------------------------------------
    def test_validate_postal_code_patterns_valid(self):
        from verenigingen.verenigingen.doctype.region.region import (
            validate_postal_code_patterns,
        )

        result = validate_postal_code_patterns("1000-1999, 2500, 3*")
        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])

    def test_validate_postal_code_patterns_empty_is_valid(self):
        from verenigingen.verenigingen.doctype.region.region import (
            validate_postal_code_patterns,
        )

        self.assertTrue(validate_postal_code_patterns("")["valid"])

    def test_validate_postal_code_patterns_bad_chars(self):
        from verenigingen.verenigingen.doctype.region.region import (
            validate_postal_code_patterns,
        )

        result = validate_postal_code_patterns("ABCD")
        self.assertFalse(result["valid"])
        self.assertTrue(any("Invalid pattern" in e for e in result["errors"]))

    def test_validate_postal_code_patterns_inverted_range(self):
        from verenigingen.verenigingen.doctype.region.region import (
            validate_postal_code_patterns,
        )

        result = validate_postal_code_patterns("2000-1000")
        self.assertFalse(result["valid"])
        self.assertTrue(any("Invalid range" in e for e in result["errors"]))

    def test_validate_postal_code_patterns_equal_range_rejected(self):
        from verenigingen.verenigingen.doctype.region.region import (
            validate_postal_code_patterns,
        )

        # start >= end means 1000-1000 is also flagged invalid
        result = validate_postal_code_patterns("1000-1000")
        self.assertFalse(result["valid"])

    def test_region_creation(self):
        """Test basic region creation with required fields"""
        unique_suffix = self.get_unique_suffix()

        region = frappe.get_doc(
            {
                "doctype": "Region",
                "region_name": f"Test Region {unique_suffix}",
                "region_code": f"TR{unique_suffix[:3]}",
                "country": "Netherlands",
            }
        )
        # EnhancedTestCase runs with frappe.flags.in_import=True, which suppresses
        # JSON field defaults (so is_active would be None). Temporarily clear the
        # flag for this insert to verify the real production default (is_active=1).
        prev_in_import = frappe.flags.in_import
        frappe.flags.in_import = False
        try:
            region.save()
        finally:
            frappe.flags.in_import = prev_in_import

        # Verify region was created
        self.assertIsNotNone(region.name)
        self.assertTrue(region.is_active)
        self.assertEqual(region.country, "Netherlands")

    def test_region_code_uniqueness(self):
        """Test that duplicate region codes are prevented"""
        unique_suffix = self.get_unique_suffix()
        # Region code must be 2-5 chars, use first 2 digits of timestamp
        code = f"D{unique_suffix[:1]}"

        # Create first region
        region1 = frappe.get_doc(
            {
                "doctype": "Region",
                "region_name": f"Region One {unique_suffix}",
                "region_code": code,
            }
        )
        region1.save()

        # Try to create second region with same code
        region2 = frappe.get_doc(
            {
                "doctype": "Region",
                "region_name": f"Region Two {unique_suffix}",
                "region_code": code,
            }
        )

        # Should fail due to duplicate code
        with self.assertRaises(frappe.ValidationError):
            region2.save()

    def test_postal_code_patterns(self):
        """Test postal code pattern matching functionality"""
        unique_suffix = self.get_unique_suffix()

        region = frappe.get_doc(
            {
                "doctype": "Region",
                "region_name": f"Postal Test Region {unique_suffix}",
                "region_code": f"PT{unique_suffix[:3]}",
                "postal_code_patterns": "1000-1999, 2500, 3000-3099",
            }
        )
        region.save()

        # Verify patterns are stored
        self.assertEqual(region.postal_code_patterns, "1000-1999, 2500, 3000-3099")

    def test_region_coordinator_assignment(self):
        """Test assigning regional coordinator (Member link)"""
        unique_suffix = self.get_unique_suffix()

        # Create a member to be coordinator
        coordinator = self.create_test_member()

        region = frappe.get_doc(
            {
                "doctype": "Region",
                "region_name": f"Coordinator Region {unique_suffix}",
                "region_code": f"CR{unique_suffix[:3]}",
                "regional_coordinator": coordinator.name,
            }
        )
        region.save()

        # Verify coordinator assignment
        self.assertEqual(region.regional_coordinator, coordinator.name)
