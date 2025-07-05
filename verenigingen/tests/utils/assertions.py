# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Custom assertion utilities for Verenigingen tests
Provides enhanced assertions for complex test scenarios
"""

from datetime import datetime

import frappe
from frappe.utils import flt


class AssertionHelpers:
    """Helper class providing custom assertions for Verenigingen tests"""

    @staticmethod
    def assert_workflow_transition(doc, from_status, to_status, message=None):
        """Assert that a document transitioned from one status to another"""
        if not message:
            message = f"Expected {doc.doctype} to transition from {from_status} to {to_status}"

        # Check document log for status transitions
        transitions = frappe.get_all(
            "Version",
            filters={"ref_doctype": doc.doctype, "docname": doc.name},
            fields=["data"],
            order_by="creation desc",
        )

        for transition in transitions:
            if from_status in str(transition.data) and to_status in str(transition.data):
                return True

        raise AssertionError(message)

    @staticmethod
    def assert_email_sent(to_email, subject_contains=None, body_contains=None):
        """Assert that an email was sent to the specified recipient"""
        emails = frappe.get_all(
            "Email Queue",
            filters={"recipients": ["like", f"%{to_email}%"]},
            fields=["subject", "message"],
            order_by="creation desc",
            limit=10,
        )

        if not emails:
            raise AssertionError(f"No email found for recipient {to_email}")

        if subject_contains:
            for email in emails:
                if subject_contains in email.subject:
                    if body_contains and body_contains not in email.message:
                        continue
                    return True
            raise AssertionError(f"No email with subject containing '{subject_contains}' found")

        if body_contains:
            for email in emails:
                if body_contains in email.message:
                    return True
            raise AssertionError(f"No email with body containing '{body_contains}' found")

        return True

    @staticmethod
    def assert_payment_created(member_name, amount, payment_type="Membership Fee"):
        """Assert that a payment entry was created for the member"""
        payments = frappe.get_all(
            "Payment Entry",
            filters={
                "party_type": "Customer",
                "references": [["Payment Entry Reference", "reference_doctype", "=", "Sales Invoice"]],
            },
            fields=["name", "paid_amount", "party"],
        )

        # Get member's customer
        customer = frappe.db.get_value("Member", member_name, "customer")
        if not customer:
            raise AssertionError(f"Member {member_name} has no linked customer")

        for payment in payments:
            if payment.party == customer and flt(payment.paid_amount) == flt(amount):
                return True

        raise AssertionError(f"No payment of {amount} found for member {member_name}")

    @staticmethod
    def assert_child_table_contains(parent_doc, child_table_field, filters):
        """Assert that a child table contains a row matching the filters"""
        child_table = parent_doc.get(child_table_field, [])

        for row in child_table:
            match = True
            for key, value in filters.items():
                if row.get(key) != value:
                    match = False
                    break
            if match:
                return True

        raise AssertionError(f"No row in {parent_doc.doctype}.{child_table_field} matches filters {filters}")

    @staticmethod
    def assert_permission_denied(func, *args, **kwargs):
        """Assert that a function call raises a permission error"""
        try:
            func(*args, **kwargs)
            raise AssertionError("Expected PermissionError but none was raised")
        except frappe.PermissionError:
            return True
        except Exception as e:
            raise AssertionError(f"Expected PermissionError but got {type(e).__name__}: {e}")

    @staticmethod
    def assert_date_between(date_value, start_date, end_date, message=None):
        """Assert that a date is between two dates (inclusive)"""
        if isinstance(date_value, str):
            date_value = datetime.strptime(date_value, "%Y-%m-%d").date()
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

        if not (start_date <= date_value <= end_date):
            if not message:
                message = f"Expected date {date_value} to be between {start_date} and {end_date}"
            raise AssertionError(message)

    @staticmethod
    def assert_subscription_active(member_name):
        """Assert that a member has an active subscription"""
        subscriptions = frappe.get_all(
            "Subscription",
            filters={
                "reference_doctype": "Member",
                "reference_document": member_name,
                "status": ["in", ["Active", "Trialing"]],
            },
        )

        if not subscriptions:
            raise AssertionError(f"No active subscription found for member {member_name}")

        return True

    @staticmethod
    def assert_sepa_mandate_active(member_name, iban=None):
        """Assert that a member has an active SEPA mandate"""
        frappe.get_doc("Member", member_name)

        filters = {"member": member_name, "status": "Active"}

        if iban:
            filters["iban"] = iban

        mandates = frappe.get_all("SEPA Mandate", filters=filters)

        if not mandates:
            raise AssertionError(f"No active SEPA mandate found for member {member_name}")

        return True

    @staticmethod
    def assert_volunteer_assignment_active(volunteer_name, team_name):
        """Assert that a volunteer is actively assigned to a team"""
        team = frappe.get_doc("Team", team_name)

        for member in team.team_members:
            if member.volunteer == volunteer_name and member.is_active:
                return True

        raise AssertionError(f"Volunteer {volunteer_name} is not actively assigned to team {team_name}")

    @staticmethod
    def assert_expense_approved(expense_name):
        """Assert that a volunteer expense is approved"""
        expense = frappe.get_doc("Volunteer_Expense", expense_name)

        if expense.status != "Approved":
            raise AssertionError(f"Expense {expense_name} is not approved (status: {expense.status})")

        return True

    @staticmethod
    def assert_termination_completed(member_name):
        """Assert that a member termination is completed"""
        member = frappe.get_doc("Member", member_name)

        if member.status != "Terminated":
            raise AssertionError(f"Member {member_name} is not terminated (status: {member.status})")

        # Check for termination audit entry
        audit_entries = frappe.get_all("Termination Audit Entry", filters={"member": member_name})

        if not audit_entries:
            raise AssertionError(f"No termination audit entry found for member {member_name}")

        return True

    @staticmethod
    def assert_chapter_member_count(chapter_name, expected_count, status="Active"):
        """Assert that a chapter has the expected number of members"""
        chapter = frappe.get_doc("Chapter", chapter_name)

        active_members = [m for m in chapter.chapter_members if m.status == status]
        actual_count = len(active_members)

        if actual_count != expected_count:
            raise AssertionError(
                f"Expected {expected_count} {status} members in chapter {chapter_name}, "
                f"but found {actual_count}"
            )

        return True

    @staticmethod
    def assert_history_recorded(doctype, docname, field_name, old_value, new_value):
        """Assert that a field change was recorded in history"""
        # This would check Version or custom history tracking
        versions = frappe.get_all(
            "Version",
            filters={"ref_doctype": doctype, "docname": docname},
            fields=["data"],
            order_by="creation desc",
        )

        for version in versions:
            if field_name in str(version.data):
                if str(old_value) in str(version.data) and str(new_value) in str(version.data):
                    return True

        raise AssertionError(
            f"No history found for {doctype} {docname} field {field_name} "
            f"changing from {old_value} to {new_value}"
        )
