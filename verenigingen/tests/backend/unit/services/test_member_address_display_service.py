# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Coverage tests for MemberAddressDisplayService.

This service is presentation-only (HTML generation). The tests pin:
- get_address_members_html: no-address empty state, address-with-no-others state
- update_address_display: no-address empty string, formatted HTML for a real Address
- update_other_members_at_address_display: no-address empty string

Real Member and Address documents are used (no mocks).
"""

import frappe

from verenigingen.services.member.display.member_address_display_service import (
    MemberAddressDisplayService,
    get_member_address_display_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberAddressDisplayService(EnhancedTestCase):
    """Tests for the address display HTML service."""

    def setUp(self):
        super().setUp()
        self.service = MemberAddressDisplayService()

    def _member_with_address(self, **address_kwargs):
        """Create a member linked to a freshly created primary Address."""
        member = self.create_test_member(first_name="Addr", last_name="Display")
        address = self.factory.create_address(link_doctype="Member", link_name=member.name, **address_kwargs)
        member.primary_address = address.name
        member.save()
        return member, address

    def _colocated_pair(self, other_birth_date="1990-01-01", **member_kwargs):
        """Create two Active members sharing the same address_line1 + city.

        member.save() triggers before_save address normalization which populates
        address_fingerprint (a content-hash of normalized line1+city). Both members
        therefore get the SAME fingerprint, and the matcher's fingerprint path
        (SimpleOptimizedAddressMatcher, WHERE address_fingerprint = ...) finds them
        as co-located. Matching is by deterministic content-hash, not site
        sparseness, so this is robust on populated sites; a false positive would
        require a pre-existing member at the exact random "Shared Straat <hash>".

        ``other`` gets an explicit adult birth_date so its age_group is stably
        'Adult' regardless of factory RNG draw order. Returns (primary, other).
        """
        line1 = f"Shared Straat {frappe.generate_hash(length=6)}"
        city = "Amsterdam"

        primary = self.create_test_member(first_name="Primary", last_name="Resident")
        addr_primary = self.factory.create_address(
            address_line1=line1, city=city, link_doctype="Member", link_name=primary.name
        )
        primary.primary_address = addr_primary.name
        primary.save()

        other = self.create_test_member(
            first_name="Other", last_name="Resident", birth_date=other_birth_date, **member_kwargs
        )
        addr_other = self.factory.create_address(
            address_line1=line1, city=city, link_doctype="Member", link_name=other.name
        )
        other.primary_address = addr_other.name
        other.save()

        return primary, other

    # ----- get_address_members_html -----

    def test_get_address_members_html_no_address_returns_empty_state(self):
        """A member with no primary address yields the 'No address selected' empty state."""
        member = self.create_test_member(first_name="NoAddr", last_name="Display")
        html = self.service.get_address_members_html(member)
        self.assertIn("No address selected", html)
        self.assertIn("fa-home", html)

    def test_get_address_members_html_address_no_others(self):
        """A member alone at an address gets the 'No other members found' message."""
        member, _address = self._member_with_address()
        with self.assertNoErrorLog():
            html = self.service.get_address_members_html(member)
        self.assertIn("No other members found at this address", html)

    def test_get_address_members_html_lists_other_member(self):
        """When another member shares the address, a member card is rendered."""
        primary, other = self._colocated_pair()
        with self.assertNoErrorLog():
            html = self.service.get_address_members_html(primary)
        self.assertIn("Other Members at This Address (1 found):", html)
        self.assertIn("member-card", html)
        self.assertIn(other.full_name, html)
        self.assertIn(other.name, html)
        # demographic / status fields the card renders for each co-resident
        self.assertIn("Adult", html)  # age_group
        self.assertIn("Active", html)  # status

    # ----- update_address_display -----

    def test_update_address_display_no_address_returns_empty_string(self):
        """No primary address produces an empty string (nothing to render)."""
        member = self.create_test_member(first_name="NoAddr2", last_name="Display")
        self.assertEqual(self.service.update_address_display(member), "")

    def test_update_address_display_renders_address_parts(self):
        """A real address renders line1, city, pincode and country into the HTML block."""
        member, _address = self._member_with_address(
            address_line1="Keizersgracht 100", city="Amsterdam", pincode="1015 CX"
        )
        with self.assertNoErrorLog():
            html = self.service.update_address_display(member)
        self.assertIn("Keizersgracht 100", html)
        self.assertIn("Amsterdam", html)
        self.assertIn("1015 CX", html)
        self.assertIn("Netherlands", html)
        self.assertIn("address-display", html)

    def test_update_address_display_renders_line2_and_state(self):
        """address_line2 and state branches render when those fields are populated."""
        member, address = self._member_with_address(
            address_line1="Damrak 1", city="Amsterdam", pincode="1012 LG"
        )
        address.address_line2 = "Floor 3"
        address.state = "Noord-Holland"
        address.save()
        member.reload()

        with self.assertNoErrorLog():
            html = self.service.update_address_display(member)

        self.assertIn("Floor 3", html)
        self.assertIn("Noord-Holland", html)
        self.assertIn("Damrak 1", html)

    def test_update_address_display_missing_address_returns_error_html(self):
        """A dangling primary_address (Address deleted) yields the error fallback."""
        member, address = self._member_with_address()
        # Point primary_address at a non-existent Address so get_doc raises inside
        # the try-block -> the except branch returns the styled error message.
        frappe.db.set_value("Member", member.name, "primary_address", "NONEXISTENT-ADDRESS-XYZ")
        member.reload()

        # The except branch logs via self.logger.error (not frappe.log_error), so
        # no Error Log doc is created -> assertNoErrorLog still holds.
        with self.assertNoErrorLog():
            html = self.service.update_address_display(member)

        self.assertIn("Error loading address information", html)

    # ----- update_other_members_at_address_display -----

    def test_update_other_members_no_address_returns_empty_string(self):
        """No primary address => empty string for the other-members panel."""
        member = self.create_test_member(first_name="NoAddr3", last_name="Display")
        self.assertEqual(self.service.update_other_members_at_address_display(member), "")

    def test_update_other_members_alone_returns_empty_string(self):
        """A member alone at an address has no panel content (empty string)."""
        member, _address = self._member_with_address()
        with self.assertNoErrorLog():
            html = self.service.update_other_members_at_address_display(member)
        self.assertEqual(html, "")

    def test_update_other_members_renders_card_for_coresident(self):
        """A co-resident produces a member card with link, status badge and age."""
        primary, other = self._colocated_pair()
        with self.assertNoErrorLog():
            html = self.service.update_other_members_at_address_display(primary)

        self.assertIn("Other Members at Same Address (1)", html)
        self.assertIn("member-card", html)
        # link to the co-resident's member form (HTML-escaped name == plain here)
        self.assertIn(f"/app/member/{other.name}", html)
        self.assertIn(other.full_name, html)
        # Active members render the success badge
        self.assertIn("badge-success", html)
        # age is derived from birth_date (factory members have a birth_date)
        self.assertIn("years old", html)

    def test_update_other_members_renders_member_since(self):
        """When the co-resident has member_since, it is shown in the card."""
        primary, other = self._colocated_pair()
        # member_since drives the optional "Member since:" fragment. No commit: the
        # display service reads it in the same transaction and the factory-tracked
        # member rolls back at test end (keep isolation rollback-based).
        frappe.db.set_value("Member", other.name, "member_since", "2020-01-15")

        with self.assertNoErrorLog():
            html = self.service.update_other_members_at_address_display(primary)

        self.assertIn("Member since:", html)
        self.assertIn("2020-01-15", html)

    # ----- singleton accessor -----

    def test_singleton_accessor_returns_service(self):
        """get_member_address_display_service returns a usable service instance."""
        svc = get_member_address_display_service()
        self.assertIsInstance(svc, MemberAddressDisplayService)
