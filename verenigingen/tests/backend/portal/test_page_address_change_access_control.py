"""
Cross-member access-control tests for the address-change portal page
(verenigingen.templates.pages.address_change).

The sibling modules (test_page_address_change_coverage.py, test_page_portal_cluster.py)
cover the happy path and the input-validation throws for a member editing their OWN
address. This module pins the guards that matter on a member-facing portal: what
happens when ``Member.primary_address`` points at an Address that belongs to a
DIFFERENT member.

That situation is reachable in production because ``Member.primary_address`` is a
plain Link field with no ownership validation on the Member DocType -- a staff edit,
a data import or an eBoekhouden/Procurios sync can point it anywhere. Both
whitelisted endpoints therefore re-verify ownership through the Address ->
Dynamic Link -> Member chain before reading or writing:

  * get_current_address()     -> address_change.py:357-369
  * update_member_address()   -> address_change.py:195-207

Each denial test is paired with the same call made by the real owner, so the test
fails if the guard is replaced by a blanket failure instead of an ownership check.

``get_context`` -- the path a browser actually hits -- does NOT re-verify ownership
and currently leaks the foreign address. That is pinned as an expectedFailure below.
"""

import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPageAddressChangeAccessControl(EnhancedTestCase):
    """A member must not be able to read or overwrite another member's address."""

    def setUp(self):
        super().setUp()
        # update_member_address / get_current_address are @self_service_api (HIGH
        # security) endpoints gated to the DEVELOPMENT environment via
        # frappe.conf.developer_mode. A sibling shard test can leave that shared,
        # non-transactional flag off -> production-environment PermissionError.
        self._original_dev_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1

        self.victim, self.victim_user = self._make_member_with_user("Victim")
        self.intruder, self.intruder_user = self._make_member_with_user("Intruder")

        # Create the victim's address through the portal endpoint itself so the
        # Address <-> Member Dynamic Link is wired exactly as production wires it.
        self.victim_address = self._create_own_address(
            self.victim_user,
            address_line1="Slachtofferstraat 5",
            city="Groningen",
            pincode="9711 AA",
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
        email = f"addracl-{label.lower()}-{frappe.generate_hash()[:8]}@example.com"
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

    def _create_own_address(self, user, **fields):
        from verenigingen.templates.pages.address_change import update_member_address

        payload = {"country": "Netherlands"}
        payload.update(fields)
        with self.as_user(user):
            result = update_member_address(payload)
        self.assertTrue(result["success"])
        self.track_doc("Address", result["address_name"])
        return result["address_name"]

    def _point_primary_address_at(self, member, address_name):
        """Simulate the corrupt/hostile state: a member whose primary_address
        references an Address owned by someone else."""
        member.db_set("primary_address", address_name)
        member.reload()

    # ------------------------------------------------ get_current_address guard

    def test_get_current_address_denies_another_members_address(self):
        """Reading a foreign address must be refused, not silently returned."""
        from verenigingen.templates.pages.address_change import get_current_address

        self._point_primary_address_at(self.intruder, self.victim_address)

        with self.as_user(self.intruder_user):
            with self.assertRaises(frappe.PermissionError) as raised:
                get_current_address()

        self.assertIn("does not belong", str(raised.exception))

    def test_get_current_address_still_returns_the_owners_own_address(self):
        """Control for the test above: the guard is ownership-based, not a
        blanket refusal -- the real owner still gets their address back."""
        from verenigingen.templates.pages.address_change import get_current_address

        with self.as_user(self.victim_user):
            result = get_current_address()

        self.assertIsNotNone(result["address"])
        self.assertEqual(result["address"]["name"], self.victim_address)
        self.assertEqual(result["address"]["city"], "Groningen")
        self.assertEqual(result["address"]["address_line1"], "Slachtofferstraat 5")

    # ------------------------------------------------------- get_context guard

    @unittest.expectedFailure
    def test_get_context_hides_an_address_linked_to_another_member(self):
        """EXPECTED FAILURE - PRODUCTION BUG: /address_change leaks a foreign address.

        The two whitelisted endpoints above are guarded, but ``get_context`` is the
        path a browser actually hits at /address_change, and it has no live ownership
        check. address_change.py:48-65 puts the Dynamic Link verification INSIDE
        ``except frappe.PermissionError:`` around ``frappe.get_doc("Address", ...)``
        -- but frappe.get_doc performs no permission check unless check_permission= is
        passed (frappe/model/document.py:122), so the except never fires and the guard
        is dead code. The intruder is handed the victim's street, city and postcode.

        personal_details.py:37-46 performs the SAME check OUTSIDE the try and is
        correct; test_page_personal_details_access_control.py pins that. Without this
        test, two green "portal access control" modules would imply both pages are
        covered when only one is.

        Fix: hoist the Dynamic Link check out of the except in address_change.py,
        mirroring personal_details.py. This test then passes.
        """
        from verenigingen.templates.pages.address_change import get_context

        self._point_primary_address_at(self.intruder, self.victim_address)

        with self.as_user(self.intruder_user):
            context = frappe._dict()
            get_context(context)

        self.assertIsNone(
            context.get("current_address"),
            "/address_change rendered an Address belonging to another member",
        )

    # ---------------------------------------------- update_member_address guard

    def test_update_member_address_cannot_overwrite_another_members_address(self):
        """The write path must refuse AND leave the victim's record untouched.

        This is the assertion that actually protects the data: if the Dynamic Link
        ownership check at address_change.py:195-207 were removed, the intruder's
        payload would be written straight onto the victim's Address document.
        """
        from verenigingen.templates.pages.address_change import update_member_address

        self._point_primary_address_at(self.intruder, self.victim_address)
        # The ownership PermissionError is raised inside the endpoint's own
        # try/except, which logs it and re-throws a generic ValidationError.
        self.expectErrorLog("Address Update Error")

        with self.as_user(self.intruder_user):
            with self.assertRaises(frappe.ValidationError):
                update_member_address(
                    {
                        "address_line1": "Overgenomen 99",
                        "city": "Amsterdam",
                        "country": "Netherlands",
                        "pincode": "1011 AB",
                        "phone": "+31 20 0000000",
                    }
                )

        victim_address = frappe.get_doc("Address", self.victim_address)
        self.assertEqual(victim_address.address_line1, "Slachtofferstraat 5")
        self.assertEqual(victim_address.city, "Groningen")
        self.assertEqual(victim_address.pincode, "9711 AA")

    def test_update_member_address_still_updates_the_owners_own_address(self):
        """Control: the same call by the owner succeeds and mutates the record."""
        from verenigingen.templates.pages.address_change import update_member_address

        with self.as_user(self.victim_user):
            result = update_member_address(
                {
                    "address_line1": "Nieuwe Ebbingestraat 12",
                    "city": "Groningen",
                    "country": "Netherlands",
                    "pincode": "9712 NA",
                }
            )

        self.assertEqual(result["action"], "updated")
        self.assertEqual(result["address_name"], self.victim_address)
        victim_address = frappe.get_doc("Address", self.victim_address)
        self.assertEqual(victim_address.address_line1, "Nieuwe Ebbingestraat 12")

    # ------------------------------------------------------ stale-link handling

    def test_get_context_clears_primary_address_when_the_address_is_gone(self):
        """A dangling primary_address must be cleared, not rendered as an error."""
        from verenigingen.templates.pages.address_change import get_context

        self._delete_address(self.victim_address)

        with self.as_user(self.victim_user):
            context = frappe._dict()
            get_context(context)

        self.assertIsNone(context.current_address)
        self.assertEqual(context.address_data["address_line1"], "")
        self.assertEqual(context.address_data["country"], "Netherlands")
        # The dangling reference is repaired on the Member record itself.
        self.assertFalse(frappe.db.get_value("Member", self.victim.name, "primary_address"))

    def _delete_address(self, address_name):
        frappe.delete_doc("Address", address_name, force=True, ignore_permissions=True)
