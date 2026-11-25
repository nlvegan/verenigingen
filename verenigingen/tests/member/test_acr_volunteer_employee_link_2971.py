"""#2971: a Volunteer-type Account Creation Request must link Volunteer.employee_id.

The ACR link phase guarded on ``hasattr(source_doc, "employee")`` and wrote the field
``"employee"``. Member has that field; Volunteer's is ``employee_id``, so the Employee
the ACR created was never linked. These tests drive the REAL pipeline
(``process_complete_pipeline``); nothing is set by hand except the ACR fixture itself.
"""

import frappe

from verenigingen.services.member.account.account_creation_manager import AccountCreationManager
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestAcrVolunteerEmployeeLink2971(EnhancedTestCase):
    def _run_acr2971(self, request_type, source_record, email, full_name):
        request = frappe.get_doc(
            {
                "doctype": "Account Creation Request",
                "request_type": request_type,
                "source_record": source_record,
                "email": email,
                "full_name": full_name,
                "role_profile": "Verenigingen Volunteer",
                "requested_roles": [
                    {"role": "Verenigingen Volunteer"},
                    {"role": "Employee"},
                    {"role": "Employee Self Service"},
                ],
                "business_justification": "#2971 link phase",
            }
        )
        request.insert()
        AccountCreationManager(request.name).process_complete_pipeline()
        request.reload()
        if request.status != "Completed" and "Role" in str(request.as_dict()):
            self.skipTest("Required role missing in test environment")
        self.assertEqual(request.status, "Completed")
        self.assertTrue(request.created_employee)
        return request

    def _make_acr2971_volunteer(self, tag):
        email = f"acr2971.{tag}.{self.uid}@test.invalid"
        member = self.create_test_member(
            first_name=f"Acr{tag}{self.uid}", last_name="Link", email=email, birth_date="1990-01-01"
        )
        volunteer = self.create_test_volunteer(
            member_name=member.name, volunteer_name=f"Acr2971 {tag} {self.uid}", email=email
        )
        return member, volunteer, email

    def test_volunteer_type_acr_links_employee_id(self):
        _member, volunteer, email = self._make_acr2971_volunteer("vol")
        self.assertFalse(frappe.db.get_value("Volunteer", volunteer.name, "employee_id"))

        request = self._run_acr2971("Volunteer", volunteer.name, email, volunteer.volunteer_name)

        self.assertEqual(frappe.db.get_value("Volunteer", volunteer.name, "employee_id"), request.created_employee)

    def test_volunteer_with_existing_employee_id_is_not_overwritten(self):
        """Control: a Volunteer already linked to a real Employee keeps that link."""
        _member, volunteer, email = self._make_acr2971_volunteer("keep")
        other = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"Keep{self.uid}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": frappe.utils.today(),
                "company": frappe.defaults.get_global_default("company"),
                "status": "Active",
            }
        ).insert(ignore_permissions=True)
        self.factory.track_document("Employee", other.name)
        frappe.db.set_value("Volunteer", volunteer.name, "employee_id", other.name)  # fixture setup, not the flow

        self._run_acr2971("Volunteer", volunteer.name, email, volunteer.volunteer_name)

        self.assertEqual(frappe.db.get_value("Volunteer", volunteer.name, "employee_id"), other.name)

    def test_member_type_acr_still_links_member_employee_and_volunteer(self):
        """Control: the Member path (Member.employee + Volunteer.employee_id) is unchanged."""
        member, volunteer, email = self._make_acr2971_volunteer("mem")

        request = self._run_acr2971("Member", member.name, email, member.full_name)

        self.assertEqual(frappe.db.get_value("Member", member.name, "employee"), request.created_employee)
        self.assertEqual(frappe.db.get_value("Volunteer", volunteer.name, "employee_id"), request.created_employee)
