# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

from datetime import datetime

import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate, now_datetime


class MembershipGoal(Document):
    def validate(self):
        """Validate goal settings"""
        # Ensure end date is after start date
        if getdate(self.end_date) < getdate(self.start_date):
            frappe.throw("End date must be after start date")

        # Set year based on start date if not set
        if not self.goal_year:
            self.goal_year = getdate(self.start_date).year

        # Update current value and achievement
        self.update_achievement()

    def update_achievement(self):
        """Calculate current value and achievement percentage"""
        self.current_value = self.calculate_current_value()

        if self.target_value and self.target_value > 0:
            self.achievement_percentage = (flt(self.current_value) / flt(self.target_value)) * 100
        else:
            self.achievement_percentage = 0

        self.last_updated = now_datetime()

        # Update status based on achievement and dates
        self.update_status()

    def calculate_current_value(self):
        """Calculate the current value based on goal type"""
        if self.goal_type == "Member Count Growth":
            return self.calculate_member_growth()
        elif self.goal_type == "Revenue Growth":
            return self.calculate_revenue_growth()
        elif self.goal_type == "Retention Rate":
            return self.calculate_retention_rate()
        elif self.goal_type == "New Member Acquisition":
            return self.calculate_new_members()
        elif self.goal_type == "Churn Reduction":
            return self.calculate_churn_rate()
        elif self.goal_type == "Chapter Expansion":
            return self.calculate_chapter_expansion()
        else:
            return 0

    def calculate_member_growth(self):
        """Calculate net member growth"""
        filters = {"member_since": ["between", [self.start_date, self.end_date]]}

        # Apply scope filters
        if not self.applies_to_all_chapters and self.chapter:
            filters["current_chapter_display"] = self.chapter

        # New members
        new_members = frappe.db.count("Member", filters=filters)

        # Lost members (terminated)
        termination_filters = {
            "termination_date": ["between", [self.start_date, self.end_date]],
            "status": "Completed",
        }

        if not self.applies_to_all_chapters and self.chapter:
            # Get members who were in this chapter when terminated
            termination_filters["member"] = [
                "in",
                frappe.db.get_list("Member", filters={"current_chapter_display": self.chapter}, pluck="name"),
            ]

        lost_members = frappe.db.count("Membership Termination Request", filters=termination_filters)

        return new_members - lost_members

    def calculate_revenue_growth(self):
        """Calculate revenue growth"""
        # Get revenue from memberships
        if not self.applies_to_all_types and self.membership_type:
            membership_filters = {"membership_type": self.membership_type}
        else:
            membership_filters = {}

        # Calculate projected annual revenue
        active_memberships = frappe.get_all(
            "Membership",
            filters={"status": "Active", **membership_filters},
            fields=["name", "membership_type"],
        )

        total_revenue = 0
        for membership in active_memberships:
            # Get the membership fee
            member = frappe.db.get_value("Membership", membership.name, "member")
            if member:
                fee_override = frappe.db.get_value("Member", member, "membership_fee_override")
                if fee_override:
                    total_revenue += fee_override
                else:
                    # Get standard fee from membership type
                    membership_fee = (
                        frappe.db.get_value("Membership Type", membership.membership_type, "amount") or 0
                    )
                    total_revenue += membership_fee

        return total_revenue

    def calculate_retention_rate(self):
        """Calculate member retention rate as percentage"""
        # Get members at start of period
        start_members = frappe.db.count(
            "Member", filters={"member_since": ["<", self.start_date], "status": ["!=", "Terminated"]}
        )

        if start_members == 0:
            return 0

        # Get members who were terminated during period
        terminated = frappe.db.count(
            "Membership Termination Request",
            filters={
                "termination_date": ["between", [self.start_date, self.end_date]],
                "status": "Completed",
            },
        )

        retention_rate = ((start_members - terminated) / start_members) * 100
        return max(0, retention_rate)  # Ensure non-negative

    def calculate_new_members(self):
        """Calculate new member acquisitions"""
        filters = {
            "member_since": ["between", [self.start_date, self.end_date]],
            "status": ["!=", "Rejected"],
        }

        if not self.applies_to_all_chapters and self.chapter:
            filters["current_chapter_display"] = self.chapter

        return frappe.db.count("Member", filters=filters)

    def calculate_churn_rate(self):
        """Calculate churn rate as percentage"""
        # Total active members at start
        total_members = frappe.db.count(
            "Member", filters={"status": "Active", "member_since": ["<", self.start_date]}
        )

        if total_members == 0:
            return 0

        # Members lost during period
        churned = frappe.db.count(
            "Membership Termination Request",
            filters={
                "termination_date": ["between", [self.start_date, self.end_date]],
                "status": "Completed",
            },
        )

        churn_rate = (churned / total_members) * 100
        return churn_rate

    def calculate_chapter_expansion(self):
        """Calculate number of new chapters with active members"""
        # This would need to track chapter creation/activation
        # For now, return count of chapters with new members
        new_chapters = frappe.db.sql(
            """
            SELECT COUNT(DISTINCT current_chapter_display)
            FROM `tabMember`
            WHERE member_since BETWEEN %s AND %s
            AND current_chapter_display IS NOT NULL
        """,
            (self.start_date, self.end_date),
        )[0][0]

        return new_chapters or 0

    def update_status(self):
        """Update goal status based on achievement and dates"""
        today = getdate()

        if self.status == "Draft":
            return

        if today > getdate(self.end_date):
            # Goal period has ended
            if self.achievement_percentage >= 100:
                self.status = "Achieved"
            else:
                self.status = "Missed"
        elif today >= getdate(self.start_date):
            # Goal period is active
            if self.achievement_percentage >= 100:
                self.status = "Achieved"
            else:
                self.status = "In Progress"
        else:
            # Goal hasn't started yet
            self.status = "Active"


@frappe.whitelist()
def update_all_goals():
    """Update achievement for all active goals"""
    goals = frappe.get_all("Membership Goal", filters={"status": ["in", ["Active", "In Progress"]]})

    for goal in goals:
        doc = frappe.get_doc("Membership Goal", goal.name)
        doc.update_achievement()
        doc.save(ignore_permissions=True)

    frappe.db.commit()
    return f"Updated {len(goals)} goals"
