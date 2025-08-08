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
        self.set_accounting_dimension_value()
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

    def set_accounting_dimension_value(self):
        """Auto-generate accounting dimension value if not provided"""
        if not self.accounting_dimension_value and self.campaign_name:
            # Create a clean dimension value from campaign name
            import re

            clean_name = self.campaign_name.strip().upper().replace(" ", "_")
            dimension_value = re.sub(r"[^A-Z0-9\-_]", "", clean_name)
            dimension_value = dimension_value[:50].strip("_")  # Remove trailing underscores

            # Ensure it doesn't start with number (some accounting systems don't like this)
            if dimension_value and dimension_value[0].isdigit():
                dimension_value = "CAMP_" + dimension_value[:46]

            # Ensure minimum length and provide fallback
            if not dimension_value or len(dimension_value) < 3:
                dimension_value = f"CAMP_{frappe.generate_hash(length=8)}"

            # Ensure uniqueness
            base_value = dimension_value
            counter = 1
            while frappe.db.exists(
                "Donation Campaign",
                {"accounting_dimension_value": dimension_value, "name": ["!=", self.name or ""]},
            ):
                suffix = f"_{counter}"
                max_base_len = 50 - len(suffix)
                dimension_value = f"{base_value[:max_base_len]}{suffix}"
                counter += 1

                # Prevent infinite loop
                if counter > 999:
                    dimension_value = f"CAMP_{frappe.generate_hash(length=8)}"
                    break

            self.accounting_dimension_value = dimension_value

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
                if d.donor:  # Only count if donor is specified
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
        """Update progress after save - progress updates are handled by donation hooks"""
        # Removed direct SQL update - progress is now updated via background job
        # when donations are created/updated to avoid recursion and maintain data integrity
        pass

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

        # Note: Anonymity is handled at the donor level
        # Donations with anonymous donors will have donor = None or "Anonymous"
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
            WHERE d.campaign = %s
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

    @frappe.whitelist()
    def create_project(self, project_name=None):
        """Create a project for this campaign"""
        if self.project:
            frappe.throw(_("Campaign already has a project linked"))

        if not project_name:
            project_name = f"Campaign: {self.campaign_name}"

        # Validate project name uniqueness
        if frappe.db.exists("Project", {"project_name": project_name}):
            frappe.throw(_("Project with name '{0}' already exists").format(project_name))

        # Validate required fields exist
        if not self.start_date:
            frappe.throw(_("Campaign must have a start date before creating a project"))

        try:
            project = frappe.get_doc(
                {
                    "doctype": "Project",
                    "project_name": project_name,
                    "expected_start_date": self.start_date,
                    "expected_end_date": self.end_date,
                    "project_type": "External",
                    "status": "Open",
                }
            )

            # Add custom field if it exists
            if hasattr(project, "custom_donation_campaign"):
                project.custom_donation_campaign = self.name

            project.insert()

            # Link back to campaign
            self.project = project.name
            self.save()

            return project

        except Exception as e:
            frappe.log_error(f"Failed to create project for campaign {self.name}: {str(e)}")
            frappe.throw(
                _("Failed to create project. Please check if Project DocType is properly configured.")
            )

    @frappe.whitelist()
    def get_project_summary(self):
        """Get project summary if campaign has a linked project"""
        if not self.project:
            return None

        project = frappe.get_doc("Project", self.project)

        # Get project tasks
        tasks = frappe.get_all(
            "Task",
            filters={"project": self.project},
            fields=["name", "subject", "status", "progress"],
        )

        # Get project expenses (if any)
        expenses = frappe.get_all(
            "Expense Claim",
            filters={"project": self.project, "docstatus": 1},
            fields=["name", "total_claimed_amount", "posting_date"],
        )

        return {
            "project": project,
            "tasks": tasks,
            "expenses": expenses,
            "total_expenses": sum(e.total_claimed_amount or 0 for e in expenses),
            "task_completion": (sum(1 for t in tasks if t.status == "Completed") / len(tasks) * 100)
            if tasks
            else 0,
        }

    def get_accounting_entries(self, from_date=None, to_date=None):
        """Get all GL entries related to this campaign"""
        filters = {}

        if self.accounting_dimension_value:
            # If using accounting dimensions, filter by dimension
            filters["custom_campaign_dimension"] = self.accounting_dimension_value

        if self.project:
            # Also include project-related entries
            filters["project"] = self.project

        if from_date and to_date:
            filters["posting_date"] = ["between", [from_date, to_date]]

        # Get GL entries
        gl_entries = frappe.get_all(
            "GL Entry",
            filters=filters,
            fields=["account", "debit", "credit", "posting_date", "voucher_type", "voucher_no"],
            order_by="posting_date desc",
        )

        # Also get donations for this campaign
        donation_filters = {"campaign": self.name, "docstatus": 1, "paid": 1}
        if from_date and to_date:
            donation_filters["donation_date"] = ["between", [from_date, to_date]]

        donations = frappe.get_all(
            "Donation",
            filters=donation_filters,
            fields=["name", "amount", "donation_date", "donor"],
            order_by="donation_date desc",
        )

        return {
            "gl_entries": gl_entries,
            "donations": donations,
            "total_income": sum(d.amount for d in donations),
            "total_expenses": sum(gl.debit for gl in gl_entries if gl.debit),
        }

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

    @staticmethod
    @frappe.whitelist()
    def test_enhancements():
        """Test donation campaign enhancements"""
        from frappe.utils import getdate

        results = []

        # Test 1: Create campaign with auto-dimension generation
        try:
            campaign = frappe.new_doc("Donation Campaign")
            campaign.campaign_name = "Test Enhancement Campaign"
            campaign.campaign_type = "Project Funding"
            campaign.start_date = getdate()
            campaign.status = "Draft"
            campaign.monetary_goal = 5000

            campaign.insert()

            results.append(
                {
                    "test": "Campaign Creation",
                    "status": "PASS",
                    "details": f"Created campaign {campaign.name} with dimension value {campaign.accounting_dimension_value}",
                }
            )

            # Test project creation
            project = campaign.create_project()
            results.append(
                {"test": "Project Creation", "status": "PASS", "details": f"Created project {project.name}"}
            )

            # Clean up
            campaign.delete()

        except Exception as e:
            results.append({"test": "Campaign Creation", "status": "FAIL", "details": str(e)})

        return results


def update_campaign_progress(campaign_name):
    """Update campaign progress (called from donation hooks)"""
    try:
        campaign = frappe.get_doc("Donation Campaign", campaign_name)

        # Use the optimized progress calculation to avoid loading all donations
        if campaign.name:
            summary = frappe.db.sql(
                """
                SELECT
                    COUNT(*) as total_donations,
                    SUM(amount) as total_raised,
                    COUNT(DISTINCT CASE WHEN anonymous = 0 THEN donor END) as total_donors,
                    AVG(amount) as average_donation_amount
                FROM `tabDonation`
                WHERE campaign = %s AND paid = 1 AND docstatus = 1
            """,
                campaign.name,
                as_dict=True,
            )

            if summary and summary[0]:
                data = summary[0]

                # Update calculated fields
                campaign.total_donations = data.total_donations or 0
                campaign.total_raised = data.total_raised or 0
                campaign.total_donors = data.total_donors or 0
                campaign.average_donation_amount = flt(data.average_donation_amount or 0, 2)

                # Calculate progress percentages
                if campaign.monetary_goal and campaign.monetary_goal > 0:
                    campaign.monetary_progress = flt(
                        (campaign.total_raised / campaign.monetary_goal) * 100, 2
                    )
                else:
                    campaign.monetary_progress = 0

                if campaign.donor_goal and campaign.donor_goal > 0:
                    campaign.donor_progress = flt((campaign.total_donors / campaign.donor_goal) * 100, 2)
                else:
                    campaign.donor_progress = 0

                # Use db_update to avoid triggering validation hooks
                campaign.db_update()

    except Exception as e:
        frappe.log_error(
            f"Failed to update campaign progress for {campaign_name}: {str(e)}",
            "Donation Campaign Update Error",
        )
