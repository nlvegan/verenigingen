"""#2436: Address permissions must not resolve the caller through Contact.email_id.

Maintainer ruling (#2205, 2026-11-11): own-record identity is Member.user only. The
Address doc-level check and list query still ended in a standard-ERPNext tail that
matched ``Contact.email_id == user`` and granted every Address sharing a Dynamic Link
with that Contact, so a login that merely equals the email of a Contact linked to a
Member read that Member's Address.

The fixture links the caller's own Contact (auto-created with the User, email_id ==
login) to the Member, which is what a real Member Contact looks like. Controls: the
Member.user owner keeps access on both paths, and an unknown Address and a forbidden one
are refused identically on every channel the caller can observe.
"""

import frappe

from verenigingen import permissions as perms
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestAddressContactIdentity2436(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        token = frappe.generate_hash(length=6)
        self.owner_user = self.create_test_user_with_roles(
            email=f"addr2436-owner-{token}0@example.com", roles=["Verenigingen Member"]
        ).name
        self.contact_user = self.create_test_user_with_roles(
            email=f"addr2436-contact-{token}0@example.com", roles=["Verenigingen Member"]
        ).name
        for user in (self.owner_user, self.contact_user):
            frappe.clear_cache(user=user)

        self.member = self.create_test_member(email=f"m-addr2436-{token}0@example.com")
        frappe.db.set_value("Member", self.member.name, "user", self.owner_user, update_modified=False)
        self.address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": f"Addr2436 {token}",
                "address_type": "Personal",
                "address_line1": "Teststraat 1",
                "city": "Amsterdam",
                "country": "Netherlands",
                "links": [{"link_doctype": "Member", "link_name": self.member.name}],
            }
        ).insert()
        self.track_doc("Address", self.address.name)
        self._link_callers_contact_to_member(self.contact_user)

        # Preconditions: the caller really is not the Member's user, and the Contact
        # that matches the caller's login really shares a link with the Address.
        self.assertFalse(frappe.db.exists("Member", {"user": self.contact_user}))
        contact = frappe.get_doc("Contact", frappe.db.get_value("Contact", {"email_id": self.contact_user}))
        self.assertTrue(contact.has_common_link(self.address))

    def _link_callers_contact_to_member(self, user):
        name = frappe.db.get_value("Contact", {"email_id": user}, "name")
        if name:
            contact = frappe.get_doc("Contact", name)
        else:
            contact = frappe.get_doc(
                {"doctype": "Contact", "first_name": "Addr2436", "email_ids": [{"email_id": user, "is_primary": 1}]}
            )
        contact.append("links", {"link_doctype": "Member", "link_name": self.member.name})
        contact.save()
        self.track_doc("Contact", contact.name)

    def _contact_linked_address(self, user):
        """An Address whose own Dynamic Link points at the caller's Contact: the shape the
        list query's Contact branch matched (the Member-linked Address above is only
        reached by the doc-level common-link check)."""
        contact_name = frappe.db.get_value("Contact", {"email_id": user}, "name")
        address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": f"Addr2436c {frappe.generate_hash(length=6)}",
                "address_type": "Personal",
                "address_line1": "Teststraat 2",
                "city": "Amsterdam",
                "country": "Netherlands",
                "links": [{"link_doctype": "Contact", "link_name": contact_name}],
            }
        ).insert()
        self.track_doc("Address", address.name)
        return address

    def _listed(self, user, address=None):
        address = address or self.address
        condition = perms.get_address_permission_query(user)
        if condition == "":
            return True
        rows = frappe.db.sql(f"SELECT name FROM `tabAddress` WHERE name = %s AND ({condition})", address.name)
        return bool(rows)

    def test_contact_email_caller_is_refused_doc_level(self):
        self.assertFalse(perms.has_address_permission(self.address.name, self.contact_user, "read"))
        self.assertFalse(perms.has_address_permission(self.address, self.contact_user, "read"))

    def test_contact_email_caller_does_not_list_the_address(self):
        self.assertFalse(self._listed(self.contact_user))

    def test_contact_email_caller_does_not_list_a_contact_linked_address(self):
        address = self._contact_linked_address(self.contact_user)
        self.assertFalse(self._listed(self.contact_user, address))
        self.assertFalse(perms.has_address_permission(address.name, self.contact_user, "read"))

    def test_contact_email_caller_gets_nothing_through_get_list(self):
        address = self._contact_linked_address(self.contact_user)
        names = frappe.get_list(
            "Address",
            filters={"name": ["in", [self.address.name, address.name]]},
            pluck="name",
            user=self.contact_user,
        )
        self.assertEqual(names, [])

    def test_member_user_keeps_own_address_on_both_paths(self):
        self.assertTrue(perms.has_address_permission(self.address.name, self.owner_user, "read"))
        self.assertTrue(self._listed(self.owner_user))

    def test_unknown_and_forbidden_address_are_refused_identically(self):
        """Compare the caller-visible channels for a real-but-forbidden Address and a
        name that does not exist: return value, message_log growth, Error Log growth."""
        outcome = {}
        for label, name in (("forbidden", self.address.name), ("unknown", f"no-such-address-{self.address.name}")):
            log_len = len(frappe.local.message_log)
            errors_before = frappe.db.count("Error Log")
            outcome[label] = (
                perms.has_address_permission(name, self.contact_user, "read")
                if label == "forbidden"
                else self._unknown_address_result(name),
                len(frappe.local.message_log) - log_len,
                frappe.db.count("Error Log") - errors_before,
            )
        self.assertEqual(outcome["forbidden"], outcome["unknown"])

    def _unknown_address_result(self, name):
        try:
            return perms.has_address_permission(name, self.contact_user, "read")
        except Exception as exc:  # the refusal shape is the thing being compared
            return type(exc).__name__
