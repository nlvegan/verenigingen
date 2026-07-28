"""
Access-control and address-tab tests for the personal-details portal page
(verenigingen.templates.pages.personal_details).

``personal_details.get_context`` renders an "address" tab alongside the personal
data. Before it loads ``Member.primary_address`` it re-verifies ownership through
the Address -> Dynamic Link -> Member chain (personal_details.py:36-50), because
``Member.primary_address`` is a plain Link field that a staff edit, a data import
or an external sync can point at any Address in the system.

This module pins that guard from both sides -- the owner sees their address, a
different member sees nothing -- plus the two ``update_personal_details`` branches
that no existing test reaches: the genuine "no changes submitted" redirect and
profile-image removal.

The sibling module test_page_personal_details_coverage.py covers the validators,
the parameter-tampering guard and the field-change happy paths.
"""

import json

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPagePersonalDetailsAddressTabAccess(EnhancedTestCase):
    """The address tab must only ever show an address linked to the caller."""

    def setUp(self):
        super().setUp()
        self._original_dev_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1

        self.victim, self.victim_user = self._make_member_with_user("Victim")
        self.intruder, self.intruder_user = self._make_member_with_user("Intruder")

        # Build the victim's address through the real portal endpoint so the
        # Address <-> Member Dynamic Link is wired the way production wires it.
        self.victim_address = self._create_own_address(
            self.victim_user,
            address_line1="Slachtofferstraat 5",
            city="Groningen",
            pincode="9711 AA",
            phone="+31 50 1234567",
        )
        self.victim.reload()

    def tearDown(self):
        if self._original_dev_mode is None:
            frappe.conf.pop("developer_mode", None)
        else:
            frappe.conf["developer_mode"] = self._original_dev_mode
        super().tearDown()

    # ------------------------------------------------------------------ helpers

    def _make_member_with_user(self, label):
        email = f"pdacl-{label.lower()}-{frappe.generate_hash()[:8]}@example.com"
        member = self.create_test_member(
            first_name=label,
            last_name="Portal",
            email=email,
            birth_date="1985-06-15",
        )
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

    def _create_own_address(self, user, **fields):
        from verenigingen.templates.pages.address_change import update_member_address

        payload = {"country": "Netherlands"}
        payload.update(fields)
        with self.as_user(user):
            result = update_member_address(payload)
        self.assertTrue(result["success"])
        self.track_doc("Address", result["address_name"])
        return result["address_name"]

    # ------------------------------------------------------- ownership boundary

    def test_context_hides_an_address_linked_to_another_member(self):
        """A primary_address pointing at someone else's Address must not render.

        If the Dynamic Link check at personal_details.py:36-50 were dropped, the
        page would load and display the other member's street, city, postcode and
        phone number.
        """
        from verenigingen.templates.pages.personal_details import get_context

        self.intruder.db_set("primary_address", self.victim_address)
        self.intruder.reload()

        with self.as_user(self.intruder_user):
            context = frappe._dict()
            get_context(context)

        self.assertIsNone(context.current_address)
        self.assertEqual(context.address_data["address_line1"], "")
        self.assertEqual(context.address_data["city"], "")
        self.assertEqual(context.address_data["pincode"], "")
        self.assertEqual(context.address_data["phone"], "")
        # The unmodified default for the empty form, not the victim's country.
        self.assertEqual(context.address_data["country"], "Netherlands")
        # Nothing leaks through the JSON blob handed to the page's JavaScript.
        self.assertNotIn("Slachtofferstraat", context.address_data_json)
        self.assertNotIn("Groningen", context.address_data_json)

    def test_context_exposes_the_members_own_linked_address(self):
        """Control for the test above: the owner does get their address back, so
        the guard is an ownership check rather than a blanket refusal."""
        from verenigingen.templates.pages.personal_details import get_context

        with self.as_user(self.victim_user):
            context = frappe._dict()
            get_context(context)

        self.assertIsNotNone(context.current_address)
        self.assertEqual(context.current_address.name, self.victim_address)
        self.assertEqual(context.address_data["address_line1"], "Slachtofferstraat 5")
        self.assertEqual(context.address_data["city"], "Groningen")
        self.assertEqual(context.address_data["pincode"], "9711 AA")
        self.assertEqual(json.loads(context.address_data_json), context.address_data)

    def test_context_falls_back_to_empty_form_when_the_link_row_is_removed(self):
        """Dropping the Address -> Member link revokes access to that address.

        This isolates the Dynamic Link row as the thing being checked: the Address
        document and Member.primary_address both still exist and are unchanged.
        """
        from verenigingen.templates.pages.personal_details import get_context

        self._unlink_address_from_member(self.victim_address, self.victim.name)

        with self.as_user(self.victim_user):
            context = frappe._dict()
            get_context(context)

        self.assertIsNone(context.current_address)
        self.assertEqual(context.address_data["city"], "")
        # The Address itself was not touched, only the ownership link.
        self.assertTrue(frappe.db.exists("Address", self.victim_address))
        self.assertEqual(
            frappe.db.get_value("Member", self.victim.name, "primary_address"), self.victim_address
        )

    def _unlink_address_from_member(self, address_name, member_name):
        address = frappe.get_doc("Address", address_name)
        address.links = [
            row
            for row in address.links
            if not (row.link_doctype == "Member" and row.link_name == member_name)
        ]
        # Runs as Administrator (the base class's default session user), so no
        # permission bypass is needed to drop the link row.
        address.save()


class TestPagePersonalDetailsUpdateBranches(EnhancedTestCase):
    """update_personal_details branches not reached by the coverage module."""

    def setUp(self):
        super().setUp()
        self._original_dev_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1

        email = f"pdupd-{frappe.generate_hash()[:8]}@example.com"
        self.member = self.create_test_member(
            first_name="Pieter",
            last_name="Vandenberg",
            email=email,
            birth_date="1988-03-04",
        )
        self.user = self._ensure_user(self.member.email)
        self.member.db_set("user", self.user)
        # The factory uniquifies last_name with a digit suffix; validate_name_format
        # rejects digits, so force clean alpha names the form can echo back.
        self.member.db_set("first_name", "Pieter")
        self.member.db_set("last_name", "Vandenberg")
        # A member editing their own portal profile is already onboarded; align the
        # workflow state so the self-save is a no-op transition.
        self.member.db_set("application_status", "Active")
        self.member.reload()

    def tearDown(self):
        frappe.local.form_dict = frappe._dict()
        if self._original_dev_mode is None:
            frappe.conf.pop("developer_mode", None)
        else:
            frappe.conf["developer_mode"] = self._original_dev_mode
        super().tearDown()

    def _ensure_user(self, email):
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Pieter",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        return email

    def _submit(self, form_data):
        from verenigingen.templates.pages.personal_details import update_personal_details

        with self.as_user(self.user):
            frappe.local.form_dict = frappe._dict(form_data)
            try:
                update_personal_details()
            finally:
                frappe.local.form_dict = frappe._dict()

    def test_resubmitting_identical_values_records_no_change(self):
        """Echoing the stored values back must be detected as "no changes".

        Submitting only first/last name looks unchanged but is NOT: the form's
        absent birth_date is compared against the stored one and registers as a
        diff. A genuine no-op therefore has to echo birth_date too -- and then the
        member document must not be written at all.
        """
        modified_before = frappe.db.get_value("Member", self.member.name, "modified")
        frappe.session.pop("personal_details_success", None)

        self._submit(
            {
                "first_name": "Pieter",
                "last_name": "Vandenberg",
                "birth_date": "1988-03-04",
            }
        )

        self.assertEqual(frappe.local.response.get("type"), "redirect")
        self.assertEqual(frappe.local.response.get("location"), "/personal_details")
        # No success message is stored, because nothing was applied ...
        self.assertIsNone(frappe.session.get("personal_details_success"))
        # ... and the Member document was never saved.
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "modified"), modified_before)

    def test_omitting_birth_date_rewrites_it_rather_than_being_a_no_op(self):
        """Guards the asymmetry that makes the test above necessary.

        A form that leaves birth_date empty is treated as an explicit change to
        empty, so the stored birth date is cleared. If this ever becomes a no-op
        the sibling "no changes" test would stop testing what it claims to.
        """
        self._submit({"first_name": "Pieter", "last_name": "Vandenberg"})

        self.member.reload()
        self.assertIsNone(self.member.birth_date)
        self.assertTrue(frappe.session.get("personal_details_success"))

    def test_remove_image_clears_the_profile_picture(self):
        self.member.db_set("image", "/files/pdupd-profile.png")
        self.member.reload()
        frappe.session.pop("personal_details_success", None)

        self._submit(
            {
                "first_name": "Pieter",
                "last_name": "Vandenberg",
                "birth_date": "1988-03-04",
                "remove_image": "1",
            }
        )

        self.member.reload()
        self.assertIsNone(self.member.image)
        self.assertIn("Your profile image has been removed", frappe.session.get("personal_details_success"))

    def test_remove_image_is_ignored_when_there_is_no_image(self):
        """remove_image on a member without a picture is not a change."""
        modified_before = frappe.db.get_value("Member", self.member.name, "modified")

        self._submit(
            {
                "first_name": "Pieter",
                "last_name": "Vandenberg",
                "birth_date": "1988-03-04",
                "remove_image": "1",
            }
        )

        self.assertEqual(frappe.db.get_value("Member", self.member.name, "modified"), modified_before)
