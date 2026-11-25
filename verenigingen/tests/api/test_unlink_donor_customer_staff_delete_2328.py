"""
#2328: donor-managing staff may remove the linked Customer (maintainer ruling 2026-11-25, (a)).

``unlink_donor_customer(remove_customer=1)`` ends in ``Customer.delete()`` as the session user,
and Customer delete was granted only to Sales Master Manager, which no Role Profile carries. The
grant is ``Verenigingen Staff`` + ``delete`` in ``custom_docperm_setup.CORE_GRANTS``: that is the
role whose Donor rows already carry delete, and it is on the Staff profile. Driven through the
real WSGI app as a user holding the ``Verenigingen Staff`` role profile (not Administrator).

Donors/Customers are committed because the WSGI child is another DB connection; removed afterwards.

Usage:
    bench --site test_site_1 run-tests --app verenigingen \
        --module verenigingen.tests.api.test_unlink_donor_customer_staff_delete_2328
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.wsgi_http_session import (
    CommittedLoginUsersMixin,
    api_path,
    operation_result,
    run_wsgi_cases,
)

ENDPOINT = api_path("verenigingen.api.donor_customer_management.unlink_donor_customer")


class TestUnlinkDonorCustomerStaffDelete2328(CommittedLoginUsersMixin, EnhancedTestCase):
    CRITICAL_PROFILES = (
        "Verenigingen Administrator",
        "Verenigingen System Administrator",
    )
    # Pass the endpoint's CRITICAL tier but lack Contact delete, which Customer.on_trash needs.
    # Pinned as refused (and not half-unlinked) until the maintainer rules on widening Contact delete.
    REFUSED_PROFILES = ("Verenigingen Treasurer", "Verenigingen National Board Member")

    def setUp(self):
        super().setUp()
        # One call: each call replaces the cleanup list of the previous one.
        profiles = self.CRITICAL_PROFILES + self.REFUSED_PROFILES
        labels = {f"p{i}": profile for i, profile in enumerate(profiles)}
        users = self._create_login_users(member="Verenigingen Member", **labels)
        self.member_user = users["member"]
        self.profile_users = {profile: users[f"p{i}"] for i, profile in enumerate(profiles)}
        self._donors = []
        self.addCleanup(self._cleanup_donors)

    def _cleanup_donors(self):
        frappe.db.rollback()
        for donor, customer in self._donors:
            for doctype, name in (("Donor", donor), ("Customer", customer)):
                if name and frappe.db.exists(doctype, name):
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def _create_linked_donor(self):
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Staff2328 {frappe.generate_hash(length=6)}"
        donor.donor_type = "Individual"
        donor.donor_email = f"s{frappe.generate_hash(length=6)}@example.com"
        donor.flags.enable_customer_sync_in_test = True  # sync is gated off in tests otherwise
        donor.save()
        donor.reload()
        customer = donor.customer
        self.assertTrue(customer, "Donor.save is expected to create and link a Customer")
        self._donors.append((donor.name, customer))
        frappe.db.set_value("Customer", customer, "donor", donor.name)
        frappe.db.commit()
        return donor.name, customer

    def test_administrator_profiles_can_delete_the_customer(self):
        """Real WSGI flow as each admin profile (not the Administrator user)."""
        for profile in self.CRITICAL_PROFILES:
            with self.subTest(profile=profile):
                donor, customer = self._create_linked_donor()
                user = self.profile_users[profile]
                case = {
                    "name": "c",
                    "endpoint": ENDPOINT,
                    "login": {"usr": user, "pwd": self.password},
                    "csrf": "valid",
                    "json": {"donor_name": donor, "remove_customer": "1"},
                }
                result = operation_result(run_wsgi_cases(case)["c"])
                self.assertTrue(result["success"], (profile, result))
                self.assertTrue(result["data"]["customer_deleted"], (profile, result))
                frappe.db.rollback()  # fresh snapshot of what the child committed
                self.assertFalse(frappe.db.exists("Customer", customer), profile)
                self.assertFalse(frappe.db.get_value("Donor", donor, "customer"), profile)

    def test_profiles_without_contact_delete_are_refused_and_rolled_back(self):
        for profile in self.REFUSED_PROFILES:
            with self.subTest(profile=profile):
                donor, customer = self._create_linked_donor()
                self.expectErrorLog("Donor Customer Unlink Error")
                case = {
                    "name": "c",
                    "endpoint": ENDPOINT,
                    "login": {"usr": self.profile_users[profile], "pwd": self.password},
                    "csrf": "valid",
                    "json": {"donor_name": donor, "remove_customer": "1"},
                }
                result = operation_result(run_wsgi_cases(case)["c"])
                self.assertFalse(result["success"], (profile, result))
                self.assertEqual(result["error"]["code"], "DONOR_CUSTOMER_UNLINK_ERROR")
                frappe.db.rollback()
                self.assertTrue(frappe.db.exists("Customer", customer), profile)
                self.assertEqual(frappe.db.get_value("Donor", donor, "customer"), customer, profile)

    def test_grant_is_not_given_to_a_member_and_keeps_the_existing_customer_permissions(self):
        """Control: a plain member profile still cannot delete; nothing existing was stripped."""
        with self.set_user(self.member_user):
            self.assertFalse(frappe.has_permission("Customer", "delete"))
        # Whole-set check: any Custom DocPerm row replaces the stock set, so a grant that
        # stripped these would silently remove them.
        grants = {
            (r.role, r.permlevel): r
            for r in frappe.get_all("Custom DocPerm", filters={"parent": "Customer"}, fields="*")
        }
        self.assertTrue(grants[("Sales Master Manager", 0)].delete)
        self.assertTrue(grants[("Accounts Manager", 0)].read)
        self.assertTrue(grants[("Verenigingen Webhook User", 0)].write)
        self.assertFalse(grants[("Verenigingen Webhook User", 0)].delete)
        self.assertTrue(grants[("Verenigingen Administrator", 0)].delete)
        self.assertFalse(grants[("Verenigingen Staff", 0)].delete)
        for ptype in ("read", "write", "create"):
            self.assertTrue(grants[("Verenigingen Staff", 0)][ptype], ptype)
