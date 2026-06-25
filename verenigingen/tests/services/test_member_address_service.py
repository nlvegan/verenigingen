# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Integration tests for member_address_service (core).

Covers relationship inference (guess_relationship) heuristics, address-field
normalization/clearing, co-located member discovery against real shared
Addresses, and the safe wrapper helpers.
"""

import unittest

import frappe
from frappe.utils import add_years, today
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

from verenigingen.services.member.core.member_address_service import (
    MemberAddressService,
    get_member_address_service,
)


class TestGuessRelationship(EnhancedTestCase):
    """guess_relationship heuristics - pure name/age logic, dict inputs."""

    def setUp(self):
        super().setUp()
        self.service = MemberAddressService()

    def _person(self, full_name, birth_date=None):
        return {"full_name": full_name, "birth_date": birth_date}

    def test_no_names_household_member(self):
        rel = self.service.guess_relationship(self._person(None), self._person("Jan Bakker"))
        self.assertEqual(rel, "Household Member")

    def test_same_last_small_age_diff_spouse(self):
        rel = self.service.guess_relationship(
            self._person("Jan Bakker", "1980-01-01"),
            self._person("Anna Bakker", "1982-06-01"),
        )
        self.assertEqual(rel, "Spouse/Partner")

    def test_same_last_large_age_diff_parent_child(self):
        rel = self.service.guess_relationship(
            self._person("Jan Bakker", "1960-01-01"),
            self._person("Tom Bakker", "1995-01-01"),
        )
        self.assertEqual(rel, "Parent/Child")

    def test_same_last_mid_age_diff_sibling(self):
        rel = self.service.guess_relationship(
            self._person("Jan Bakker", "1980-01-01"),
            self._person("Kees Bakker", "1990-01-01"),
        )
        self.assertEqual(rel, "Sibling")

    def test_same_last_no_dates_family_member(self):
        rel = self.service.guess_relationship(
            self._person("Jan Bakker"),
            self._person("Anna Bakker"),
        )
        self.assertEqual(rel, "Family Member")

    def test_different_last_partner_spouse(self):
        rel = self.service.guess_relationship(
            self._person("Jan Bakker", "1980-01-01"),
            self._person("Anna Jansen", "1981-01-01"),
        )
        self.assertEqual(rel, "Partner/Spouse")

    def test_invalid_dates_fall_through_to_family(self):
        rel = self.service.guess_relationship(
            self._person("Jan Bakker", "not-a-date"),
            self._person("Anna Bakker", "also-bad"),
        )
        # Bad dates -> exception caught -> "Family Member"
        self.assertEqual(rel, "Family Member")


class TestAddressFieldUpdate(EnhancedTestCase):
    """update_member_address_fields normalization and clearing."""

    def setUp(self):
        super().setUp()
        self.service = MemberAddressService()

    def test_no_primary_address_clears_fields(self):
        member = self.create_test_member(
            first_name="Addr",
            last_name="None",
            email="addr.none@example.com",
        )
        member.primary_address = None
        member.address_fingerprint = "STALE"
        result = self.service.update_member_address_fields(member)
        self.assertTrue(result.success)
        self.assertTrue(result.metadata.get("cleared"))
        self.assertIsNone(member.address_fingerprint)
        self.assertIsNone(member.normalized_address_line)

    def test_address_produces_fingerprint(self):
        member = self.create_test_member(
            first_name="Addr",
            last_name="Norm",
            email="addr.norm@example.com",
            address_line1="Prinsengracht 263",
            city="Amsterdam",
            postal_code="1016 GV",
        )
        member.reload()
        self.assertTrue(member.primary_address)
        result = self.service.update_member_address_fields(member)
        self.assertTrue(result.success)
        self.assertTrue(member.address_fingerprint)
        self.assertTrue(member.normalized_city)
        # fingerprint returned as data
        self.assertEqual(result.data, member.address_fingerprint)


class TestColocatedMembers(EnhancedTestCase):
    """get_colocated_members against members sharing a real Address."""

    def setUp(self):
        super().setUp()
        self.service = get_member_address_service()

    def test_no_address_returns_empty(self):
        member = self.create_test_member(
            first_name="Colo",
            last_name="NoAddr",
            email="colo.noaddr@example.com",
        )
        member.primary_address = None
        result = self.service.get_colocated_members(member)
        self.assertTrue(result.success)
        self.assertEqual(result.data, [])
        self.assertTrue(result.metadata.get("no_address"))

    def test_shared_address_discovers_other_member(self):
        """Two members at the same Address see each other as co-located."""
        m1 = self.create_test_member(
            first_name="Colo",
            last_name="Shared",
            email="colo.shared1@example.com",
            address_line1="Damrak 70",
            city="Amsterdam",
            postal_code="1012 LM",
            birth_date=add_years(today(), -40),
        )
        m1.reload()
        address = m1.primary_address
        self.assertTrue(address)

        m2 = self.create_test_member(
            first_name="Other",
            last_name="Shared",
            email="colo.shared2@example.com",
            birth_date=add_years(today(), -38),
        )
        # Link m2 to the same address + run normalization so the matcher finds it
        frappe.db.set_value("Member", m2.name, "primary_address", address)
        m2.reload()
        self.service.update_member_address_fields(m1)
        self.service.update_member_address_fields(m2)
        m1.save()
        m2.save()

        m1.reload()
        result = self.service.get_colocated_members(m1)
        self.assertTrue(result.success)
        names = [r["name"] for r in result.data]
        self.assertIn(m2.name, names)

    def test_safe_wrapper_returns_list(self):
        member = self.create_test_member(
            first_name="Colo",
            last_name="Safe",
            email="colo.safe@example.com",
        )
        member.primary_address = None
        out = self.service.get_other_members_at_address_safe(member)
        self.assertEqual(out, [])


class TestAddressDisplayHtml(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = get_member_address_service()

    def test_empty_when_no_colocated(self):
        member = self.create_test_member(
            first_name="Html",
            last_name="Empty",
            email="html.empty@example.com",
        )
        member.primary_address = None
        result = self.service.generate_address_display_html(member)
        self.assertTrue(result.success)
        self.assertEqual(result.data, "")
        self.assertTrue(result.metadata.get("empty"))


if __name__ == "__main__":
    unittest.main()
