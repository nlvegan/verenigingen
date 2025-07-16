import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now, today


class ExpulsionReportEntry(Document):
    def validate(self):
        self.validate_member_details()
        self.validate_dates()
        self.set_chapter_from_member()

    def before_save(self):
        self.update_status_based_on_appeals()

    def after_insert(self):
        self.notify_governance_team()

    def validate_member_details(self):
        """Validate member exists and details are consistent"""
        if not frappe.db.exists("Member", self.member_id):
            frappe.throw(_("Member {0} does not exist").format(self.member_id))

        # Ensure member name matches
        actual_member_name = frappe.db.get_value("Member", self.member_id, "full_name")
        if actual_member_name != self.member_name:
            self.member_name = actual_member_name

    def validate_dates(self):
        """Validate expulsion date is reasonable"""
        if self.expulsion_date and getdate(self.expulsion_date) > getdate(today()):
            frappe.throw(_("Expulsion date cannot be in the future"))

        if self.reversal_date and self.expulsion_date:
            if getdate(self.reversal_date) < getdate(self.expulsion_date):
                frappe.throw(_("Reversal date cannot be before expulsion date"))

    def set_chapter_from_member(self):
        """Auto-set chapter from member's primary chapter if not provided"""
        if not self.chapter_involved and self.member_id:
            # Get primary chapter from Chapter Member table
            member_chapters = frappe.get_all(
                "Chapter Member",
                filters={"member": self.member_id, "enabled": 1},
                fields=["parent"],
                order_by="chapter_join_date desc",
                limit=1,
                ignore_permissions=True,
            )
            if member_chapters:
                self.chapter_involved = member_chapters[0].parent

    def update_status_based_on_appeals(self):
        """Update status based on any active appeals"""
        if self.name:  # Only for existing records
            # Check for active appeals
            active_appeals = frappe.get_all(
                "Termination Appeals Process",
                filters={
                    "expulsion_entry": self.name,
                    "appeal_status": ["in", ["Submitted", "Under Review", "Pending Decision"]],
                },
            )

            if active_appeals and self.status != "Under Appeal":
                self.status = "Under Appeal"
                self.under_appeal = 1

    def notify_governance_team(self):
        """Send notification to governance team about new expulsion entry"""
        # Get governance team emails (Verenigingen Administrators)
        governance_users = frappe.get_all(
            "Has Role", filters={"role": "Verenigingen Administrator"}, fields=["parent"]
        )

        governance_emails = []
        for user_role in governance_users:
            email = frappe.db.get_value("User", user_role.parent, "email")
            if email and email != "Administrator":
                governance_emails.append(email)

        if not governance_emails:
            return

        subject = f"New Expulsion Report Entry - {self.member_name}"

        message = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px;">
            <div style="background-color: #f8d7da; padding: 20px; border-radius: 8px; margin-bottom: 20px; border-left: 4px solid #dc3545;">
                <h2 style="color: #721c24; margin: 0;">New Expulsion Report Entry</h2>
                <p style="color: #6c757d; margin: 5px 0 0 0;">Governance Oversight Required</p>
            </div>

            <p>A new expulsion has been recorded in the system:</p>

            <div style="background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <h3>Expulsion Details</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr><td style="padding: 5px;"><strong>Member:</strong></td><td style="padding: 5px;">{self.member_name}</td></tr>
                    <tr><td style="padding: 5px;"><strong>Member ID:</strong></td><td style="padding: 5px;">{self.member_id}</td></tr>
                    <tr><td style="padding: 5px;"><strong>Expulsion Type:</strong></td><td style="padding: 5px;">{self.expulsion_type}</td></tr>
                    <tr><td style="padding: 5px;"><strong>Expulsion Date:</strong></td><td style="padding: 5px;">{frappe.format_date(self.expulsion_date)}</td></tr>
                    <tr><td style="padding: 5px;"><strong>Chapter:</strong></td><td style="padding: 5px;">{self.chapter_involved or 'Not specified'}</td></tr>
                    <tr><td style="padding: 5px;"><strong>Initiated By:</strong></td><td style="padding: 5px;">{self.initiated_by}</td></tr>
                    <tr><td style="padding: 5px;"><strong>Approved By:</strong></td><td style="padding: 5px;">{self.approved_by}</td></tr>
                </table>
            </div>

            <div style="background: #e3f2fd; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <h3 style="margin-top: 0; color: #1976d2;">Required Actions</h3>
                <ul>
                    <li>Review expulsion documentation for completeness</li>
                    <li>Verify proper procedures were followed</li>
                    <li>Monitor for potential appeals (30-day window)</li>
                    <li>Ensure compliance with governance requirements</li>
                </ul>
            </div>

            <div style="text-align: center; margin: 30px 0;">
                <a href="{frappe.utils.get_url()}/app/expulsion-report-entry/{self.name}"
                   style="background-color: #dc3545; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; font-weight: bold;">
                    Review Expulsion Entry
                </a>
            </div>

            <p>Best regards,<br>Governance System</p>
        </div>
        """

        try:
            frappe.sendmail(
                recipients=governance_emails,
                subject=subject,
                message=message,
                reference_doctype=self.doctype,
                reference_name=self.name,
                header=["New Expulsion Entry", "red"],
            )

        except Exception as e:
            frappe.log_error(
                f"Failed to send expulsion notification: {str(e)}", "Expulsion Notification Error"
            )

    @frappe.whitelist()
    def reverse_expulsion(self, reversal_reason):
        """Reverse the expulsion entry"""
        if self.status == "Reversed":
            frappe.throw(_("Expulsion has already been reversed"))

        self.status = "Reversed"
        self.reversal_date = today()
        self.reversal_reason = reversal_reason
        self.under_appeal = 0

        self.save()

        # Notify about reversal
        self.send_reversal_notification()

        return True

    def send_reversal_notification(self):
        """Send notification when expulsion is reversed"""
        # Get governance team emails
        governance_users = frappe.get_all(
            "Has Role", filters={"role": "Verenigingen Administrator"}, fields=["parent"]
        )

        governance_emails = []
        for user_role in governance_users:
            email = frappe.db.get_value("User", user_role.parent, "email")
            if email and email != "Administrator":
                governance_emails.append(email)

        if not governance_emails:
            return

        subject = f"Expulsion Reversed - {self.member_name}"

        message = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px;">
            <div style="background-color: #d4edda; padding: 20px; border-radius: 8px; margin-bottom: 20px; border-left: 4px solid #28a745;">
                <h2 style="color: #155724; margin: 0;">Expulsion Reversed</h2>
                <p style="color: #6c757d; margin: 5px 0 0 0;">Governance Update</p>
            </div>

            <p>An expulsion has been reversed:</p>

            <div style="background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <h3>Reversal Details</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr><td style="padding: 5px;"><strong>Member:</strong></td><td style="padding: 5px;">{self.member_name}</td></tr>
                    <tr><td style="padding: 5px;"><strong>Original Expulsion Date:</strong></td><td style="padding: 5px;">{frappe.format_date(self.expulsion_date)}</td></tr>
                    <tr><td style="padding: 5px;"><strong>Reversal Date:</strong></td><td style="padding: 5px;">{frappe.format_date(self.reversal_date)}</td></tr>
                    <tr><td style="padding: 5px;"><strong>Reversal Reason:</strong></td><td style="padding: 5px;">{self.reversal_reason}</td></tr>
                </table>
            </div>

            <p>Please review any associated member records and ensure appropriate follow-up actions are taken.</p>

            <p>Best regards,<br>Governance System</p>
        </div>
        """

        try:
            frappe.sendmail(
                recipients=governance_emails,
                subject=subject,
                message=message,
                reference_doctype=self.doctype,
                reference_name=self.name,
                header=["Expulsion Reversed", "green"],
            )

        except Exception as e:
            frappe.log_error(
                f"Failed to send reversal notification: {str(e)}", "Expulsion Reversal Notification Error"
            )


# Server-side methods
@frappe.whitelist()
def get_expulsion_statistics(filters=None):
    """Get statistics about expulsions for reporting"""

    conditions = []
    values = {}

    if filters:
        if filters.get("from_date"):
            conditions.append("expulsion_date >= %(from_date)s")
            values["from_date"] = filters["from_date"]

        if filters.get("to_date"):
            conditions.append("expulsion_date <= %(to_date)s")
            values["to_date"] = filters["to_date"]

        if filters.get("chapter"):
            conditions.append("chapter_involved = %(chapter)s")
            values["chapter"] = filters["chapter"]

        if filters.get("expulsion_type"):
            conditions.append("expulsion_type = %(expulsion_type)s")
            values["expulsion_type"] = filters["expulsion_type"]

    if conditions:
        "WHERE " + " AND ".join(conditions)

    # Get basic counts
    query = f"""
        SELECT
            COUNT(*) as total_expulsions,
            COUNT(CASE WHEN status = 'Active' THEN 1 END) as active_expulsions,
            COUNT(CASE WHEN status = 'Reversed' THEN 1 END) as reversed_expulsions,
            COUNT(CASE WHEN under_appeal = 1 THEN 1 END) as under_appeal,
            COUNT(CASE WHEN expulsion_type = 'Policy Violation' THEN 1 END) as policy_violations,
            COUNT(CASE WHEN expulsion_type = 'Disciplinary Action' THEN 1 END) as disciplinary_actions,
            COUNT(CASE WHEN expulsion_type = 'Expulsion' THEN 1 END) as formal_expulsions
        FROM `tabExpulsion Report Entry`
        {where_clause}
    """

    result = frappe.db.sql(query, values, as_dict=True)[0]

    # Get chapter breakdown
    chapter_query = f"""
        SELECT
            chapter_involved,
            COUNT(*) as count
        FROM `tabExpulsion Report Entry`
        {where_clause}
        AND chapter_involved IS NOT NULL
        GROUP BY chapter_involved
        ORDER BY count DESC
    """

    chapter_breakdown = frappe.db.sql(chapter_query, values, as_dict=True)

    # Get monthly trend (last 12 months)
    trend_query = """
        SELECT
            DATE_FORMAT(expulsion_date, '%Y-%m') as month,
            COUNT(*) as count
        FROM `tabExpulsion Report Entry`
        WHERE expulsion_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
        {('AND ' + ' AND '.join(conditions)) if conditions else ''}
        GROUP BY DATE_FORMAT(expulsion_date, '%Y-%m')
        ORDER BY month
    """

    monthly_trend = frappe.db.sql(trend_query, values, as_dict=True)

    return {"summary": result, "chapter_breakdown": chapter_breakdown, "monthly_trend": monthly_trend}


@frappe.whitelist()
def generate_expulsion_governance_report(date_range=None, chapter=None):
    """Generate comprehensive governance report for expulsions"""

    filters = {}
    if date_range:
        start_date, end_date = date_range.split(",")
        filters["from_date"] = start_date
        filters["to_date"] = end_date
    if chapter:
        filters["chapter"] = chapter

    # Get statistics
    stats = get_expulsion_statistics(filters)

    # Get detailed expulsion list
    conditions = []
    values = {}

    if filters.get("from_date"):
        conditions.append("ere.expulsion_date >= %(from_date)s")
        values["from_date"] = filters["from_date"]

    if filters.get("to_date"):
        conditions.append("ere.expulsion_date <= %(to_date)s")
        values["to_date"] = filters["to_date"]

    if filters.get("chapter"):
        conditions.append("ere.chapter_involved = %(chapter)s")
        values["chapter"] = filters["chapter"]

    if conditions:
        "WHERE " + " AND ".join(conditions)

    detailed_query = f"""
        SELECT
            ere.name,
            ere.member_name,
            ere.member_id,
            ere.expulsion_date,
            ere.expulsion_type,
            ere.chapter_involved,
            ere.initiated_by,
            ere.approved_by,
            ere.status,
            ere.under_appeal,
            ere.appeal_date,
            ere.reversal_date,
            ere.reversal_reason,
            CASE
                WHEN tap.name IS NOT NULL THEN 'Yes'
                ELSE 'No'
            END as has_appeal,
            tap.appeal_status,
            tap.decision_outcome
        FROM `tabExpulsion Report Entry` ere
        LEFT JOIN `tabTermination Appeals Process` tap ON ere.name = tap.expulsion_entry
        {where_clause}
        ORDER BY ere.expulsion_date DESC
    """

    detailed_data = frappe.db.sql(detailed_query, values, as_dict=True)

    # Generate compliance analysis
    compliance_issues = []

    # Check for expulsions without proper documentation
    missing_docs = frappe.db.sql(
        """
        SELECT COUNT(*) as count
        FROM `tabExpulsion Report Entry` ere
        LEFT JOIN `tabMembership Termination Request` mtr ON ere.member_id = mtr.member
        {where_clause}
        AND mtr.disciplinary_documentation IS NULL
    """,
        values,
    )[0][0]

    if missing_docs > 0:
        compliance_issues.append(
            {"issue": "Missing Documentation", "count": missing_docs, "severity": "High"}
        )

    # Check for overdue appeals
    overdue_appeals = frappe.db.count(
        "Termination Appeals Process",
        {"appeal_status": ["in", ["Under Review", "Pending Decision"]], "review_deadline": ["<", today()]},
    )

    if overdue_appeals > 0:
        compliance_issues.append(
            {"issue": "Overdue Appeal Reviews", "count": overdue_appeals, "severity": "Critical"}
        )

    return {
        "summary": stats["summary"],
        "chapter_breakdown": stats["chapter_breakdown"],
        "monthly_trend": stats["monthly_trend"],
        "expulsions": detailed_data,
        "compliance_issues": compliance_issues,
        "report_generated": now(),
        "report_period": f"{filters.get('from_date', 'All time')} to {filters.get('to_date', 'Present')}",
    }


@frappe.whitelist()
def reverse_expulsion_entry(expulsion_entry_name, reversal_reason):
    """Server method to reverse an expulsion entry"""

    expulsion_doc = frappe.get_doc("Expulsion Report Entry", expulsion_entry_name)
    return expulsion_doc.reverse_expulsion(reversal_reason)


@frappe.whitelist()
def get_member_expulsion_history(member_id):
    """Get expulsion history for a specific member"""

    history = frappe.get_all(
        "Expulsion Report Entry",
        filters={"member_id": member_id},
        fields=[
            "name",
            "expulsion_date",
            "expulsion_type",
            "status",
            "under_appeal",
            "reversal_date",
            "reversal_reason",
            "initiated_by",
            "approved_by",
            "chapter_involved",
        ],
        order_by="expulsion_date desc",
    )

    # Enhance with appeal information
    for record in history:
        appeals = frappe.get_all(
            "Termination Appeals Process",
            filters={"expulsion_entry": record.name},
            fields=["name", "appeal_status", "decision_outcome", "appeal_date"],
        )
        record["appeals"] = appeals

    return history
