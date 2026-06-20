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

    # ----- singleton accessor -----

    def test_singleton_accessor_returns_service(self):
        """get_member_address_display_service returns a usable service instance."""
        svc = get_member_address_display_service()
        self.assertIsInstance(svc, MemberAddressDisplayService)
