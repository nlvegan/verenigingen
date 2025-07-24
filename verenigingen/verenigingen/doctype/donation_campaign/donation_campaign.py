# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate


class DonationCampaign(Document):
    def validate(self):
        self.validate_dates()
        self.validate_goals()
        self.update_progress()

    def validate_dates(self):
        """Validate campaign dates"""
        if self.end_date and self.start_date:
            if getdate(self.end_date) < getdate(self.start_date):
                frappe.throw(_("End date cannot be before start date"))

    def validate_goals(self):
        """Validate campaign goals"""
        if self.monetary_goal and self.monetary_goal < 0:
            frappe.throw(_("Monetary goal must be positive"))

        if self.donor_goal and self.donor_goal < 0:
            frappe.throw(_("Donor goal must be positive"))

    def update_progress(self):
        """Update campaign progress from linked donations"""
        if self.name and not self.is_new():
            # Get all paid donations for this campaign
            donations = frappe.get_all(
                "Donation",
                filters={"campaign": self.name, "paid": 1, "docstatus": 1},
                fields=["name", "amount", "donor"],
            )

            # Calculate totals
            self.total_donations = len(donations)
            self.total_raised = sum(d.amount for d in donations)

            # Count unique donors
            unique_donors = set()
            for d in donations:
                if not d.anonymous:
                    unique_donors.add(d.donor)
            self.total_donors = len(unique_donors)

            # Calculate average
            if self.total_donations > 0:
                self.average_donation_amount = flt(self.total_raised / self.total_donations, 2)
            else:
                self.average_donation_amount = 0

            # Calculate progress percentages
            if self.monetary_goal and self.monetary_goal > 0:
                self.monetary_progress = flt((self.total_raised / self.monetary_goal) * 100, 2)
            else:
                self.monetary_progress = 0

            if self.donor_goal and self.donor_goal > 0:
                self.donor_progress = flt((self.total_donors / self.donor_goal) * 100, 2)
            else:
                self.donor_progress = 0

    def on_update(self):
        """Update progress after save"""
        if not self.is_new():
            # Update progress in database directly to avoid recursion
            frappe.db.sql(
                """
                UPDATE `tabDonation Campaign`
                SET total_raised = %s,
                    total_donors = %s,
                    total_donations = %s,
                    monetary_progress = %s,
                    donor_progress = %s,
                    average_donation_amount = %s
                WHERE name = %s
            """,
                (
                    self.total_raised,
                    self.total_donors,
                    self.total_donations,
                    self.monetary_progress,
                    self.donor_progress,
                    self.average_donation_amount,
                    self.name,
                ),
            )

    @frappe.whitelist()
    def get_recent_donations(self, limit=10):
        """Get recent donations for this campaign"""
        donations = frappe.get_all(
            "Donation",
            filters={"campaign": self.name, "paid": 1, "docstatus": 1},
            fields=["name", "donor", "amount", "donation_date"],
            order_by="donation_date desc",
            limit=limit,
        )

        # Anonymize donor names if needed
        for donation in donations:
            if donation.anonymous:
                donation.donor_name = _("Anonymous")
                donation.donor = None

        return donations

    @frappe.whitelist()
    def get_top_donors(self, limit=10):
        """Get top donors for this campaign"""
        if not self.show_donor_list:
            return []

        top_donors = frappe.db.sql(
            """
            SELECT
                d.donor,
                dn.donor_name,
                SUM(d.amount) as total_amount,
                COUNT(d.name) as donation_count
            FROM `tabDonation` d
            INNER JOIN `tabDonor` dn ON d.donor = dn.name
            WHERE d.donation_campaign = %s
                AND d.paid = 1
                AND d.docstatus = 1
                AND d.anonymous = 0
            GROUP BY d.donor
            ORDER BY total_amount DESC
            LIMIT %s
        """,
            (self.name, limit),
            as_dict=True,
        )

        return top_donors

    def get_campaign_url(self):
        """Get public URL for this campaign"""
        if self.is_public and self.show_on_website:
            return f"/campaign/{self.name}"
        return None

    @staticmethod
    def get_active_campaigns():
        """Get all active public campaigns"""
        return frappe.get_all(
            "Donation Campaign",
            filters={"status": "Active", "is_public": 1, "show_on_website": 1},
            fields=[
                "name",
                "campaign_name",
                "campaign_type",
                "description",
                "monetary_goal",
                "total_raised",
                "monetary_progress",
                "start_date",
                "end_date",
                "campaign_image",
            ],
            order_by="start_date desc",
        )


def update_campaign_progress(campaign_name):
    """Update campaign progress (called from donation hooks)"""
    try:
        campaign = frappe.get_doc("Donation Campaign", campaign_name)
        campaign.update_progress()
        campaign.db_update()
    except Exception as e:
        frappe.log_error(f"Failed to update campaign progress: {str(e)}", "Donation Campaign Update Error")
