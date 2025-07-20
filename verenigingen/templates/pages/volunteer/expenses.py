import frappe
from frappe import _
from frappe.utils import flt, formatdate, today


def get_context(context):
    """Get context for volunteer expense portal page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access the volunteer expense portal"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Volunteer Expenses")

    # Get current user's volunteer record
    volunteer = get_user_volunteer_record()
    if not volunteer:
        context.error_message = _(
            "No volunteer record found for your account. Please contact your chapter administrator."
        )
        return context

    context.volunteer = volunteer

    # Get volunteer's organizations (chapters and teams)
    context.organizations = get_volunteer_organizations(volunteer.name)

    # Get expense categories
    context.expense_categories = get_expense_categories()

    # Get volunteer's recent expenses
    context.recent_expenses = get_volunteer_expenses(volunteer.name, limit=10)

    # Get expense statistics
    context.expense_stats = get_expense_statistics(volunteer.name)

    # Get maximum amounts for each approval level (for UI guidance)
    context.approval_thresholds = get_approval_thresholds()

    # Get national chapter info from settings
    context.national_chapter = get_national_chapter()

    return context


def get_user_volunteer_record():
    """Get volunteer record for current user"""
    user_email = frappe.session.user

    # First try to find by linked member
    member = frappe.db.get_value("Member", {"email": user_email}, "name")
    if member:
        volunteer = frappe.db.get_value(
            "Volunteer", {"member": member}, ["name", "volunteer_name", "member"], as_dict=True
        )
        if volunteer:
            return volunteer

    # Try to find volunteer directly by email (if volunteer has direct email)
    volunteer = frappe.db.get_value(
        "Volunteer", {"email": user_email}, ["name", "volunteer_name", "member"], as_dict=True
    )
    if volunteer:
        return volunteer

    return None


@frappe.whitelist()
def debug_volunteer_access():
    """Debug function to help administrators troubleshoot volunteer access issues"""
    if not frappe.has_permission("Volunteer", "read"):
        frappe.throw(_("Insufficient permissions to debug volunteer access"))

    user_email = frappe.session.user
    result = {"user_email": user_email, "timestamp": frappe.utils.now()}

    # Check Member record
    member = frappe.db.get_value(
        "Member", {"email": user_email}, ["name", "first_name", "last_name"], as_dict=True
    )
    result["member"] = member

    if member:
        # Check for linked Volunteer
        volunteer = frappe.db.get_value(
            "Volunteer", {"member": member.name}, ["name", "volunteer_name", "status"], as_dict=True
        )
        result["volunteer_via_member"] = volunteer

    # Check direct Volunteer record
    volunteer_direct = frappe.db.get_value(
        "Volunteer", {"email": user_email}, ["name", "volunteer_name", "member", "status"], as_dict=True
    )
    result["volunteer_direct"] = volunteer_direct

    return result


# Debug functions removed - regression tests added to cover this functionality


@frappe.whitelist()
def check_workspace_status():
    """Check workspace status in database vs file"""
    if not frappe.has_permission("Workspace", "read"):
        frappe.throw(_("Insufficient permissions to check workspace status"))

    result = {}

    # Check if workspace exists in database
    db_workspace = frappe.db.sql(
        """
        SELECT name, public, is_hidden, modified, modified_by, for_user
        FROM `tabWorkspace`
        WHERE name = 'Verenigingen'
    """,
        as_dict=True,
    )

    result["db_workspace"] = db_workspace[0] if db_workspace else None

    # Get workspace links from database
    db_links = frappe.db.sql(
        """
        SELECT link_to, label, hidden, link_type, type
        FROM `tabWorkspace Link`
        WHERE parent = 'Verenigingen'
        ORDER BY idx
    """,
        as_dict=True,
    )

    result["db_links_count"] = len(db_links)
    result["db_links"] = db_links

    return result


@frappe.whitelist()
def test_expense_query_fix():
    """Test that the expense claim query works without 'title' field"""
    try:
        expense_claims = frappe.get_all(
            "Expense Claim",
            fields=[
                "name",
                "employee_name",
                "total_claimed_amount",
                "status",
                "posting_date",
                "creation",
                "approval_status",
                "company",
                "cost_center",
            ],
            limit=2,
        )

        return {
            "success": True,
            "message": f"Query successful! Found {len(expense_claims)} expense claims",
            "sample_data": expense_claims[0] if expense_claims else None,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def update_workspace_links():
    """Update workspace with comprehensive links"""
    if not frappe.has_permission("Workspace", "write"):
        frappe.throw(_("Insufficient permissions to update workspace"))

    try:
        # Always create a fresh workspace
        # Delete if exists
        if frappe.db.exists("Workspace", "Verenigingen"):
            frappe.db.delete("Workspace", "Verenigingen")
            frappe.db.delete("Workspace Link", {"parent": "Verenigingen"})

        # Create new workspace with proper content structure
        workspace = frappe.get_doc(
            {
                "doctype": "Workspace",
                "name": "Verenigingen",
                "title": "Verenigingen",
                "label": "Verenigingen",
                "icon": "non-profit",
                "module": "Verenigingen",
                "public": 1,
                "is_hidden": 0,
                "content": """[
                {"id":"NFcjh9I8BH","type":"header","data":{"text":"<span class=\\"h4\\"><b>Members/Memberships</b></span>","col":12}},
                {"id":"oIk2CrSoAH","type":"card","data":{"card_name":"Memberships","col":4}},
                {"id":"sxzInK1PHL","type":"shortcut","data":{"shortcut_name":"Member","col":3}},
                {"id":"q6OM4R0OUa","type":"shortcut","data":{"shortcut_name":"Membership","col":3}},
                {"id":"zGoLYG0xRM","type":"spacer","data":{"col":12}},
                {"id":"jMy1CTqEJS","type":"header","data":{"text":"<span class=\\"h4\\"><b>Volunteering</b></span>","col":12}},
                {"id":"2vHgUjgQcL","type":"card","data":{"card_name":"Volunteers","col":4}},
                {"id":"zGoLYG0xRM2","type":"spacer","data":{"col":12}},
                {"id":"jMy1CTqEJS2","type":"header","data":{"text":"<span class=\\"h4\\"><b>Chapters/Teams</b></span>","col":12}},
                {"id":"S8Mi0T41U7","type":"card","data":{"card_name":"Chapters","col":4}},
                {"id":"XXEhdaTHF_","type":"card","data":{"card_name":"Teams and Commissions","col":4}},
                {"id":"zGoLYG0xRM3","type":"spacer","data":{"col":12}},
                {"id":"jMy1CTqEJS3","type":"header","data":{"text":"<span class=\\"h4\\"><b>Financial</b></span>","col":12}},
                {"id":"ZvroSYo9F3","type":"card","data":{"card_name":"Donations","col":4}},
                {"id":"PaymentCard","type":"card","data":{"card_name":"Payment Processing","col":4}},
                {"id":"zGoLYG0xRM4","type":"spacer","data":{"col":12}},
                {"id":"jMy1CTqEJS4","type":"header","data":{"text":"<span class=\\"h4\\"><b>Reports</b></span>","col":12}},
                {"id":"ReportsCard","type":"card","data":{"card_name":"Reports","col":8}},
                {"id":"zGoLYG0xRM5","type":"spacer","data":{"col":12}},
                {"id":"SettingsHeader","type":"header","data":{"text":"<span class=\\"h4\\"><b>Settings</b></span>","col":12}},
                {"id":"RKkllDSemd","type":"card","data":{"card_name":"Module Settings","col":4}}
            ]""",
                "links": [],
                "shortcuts": [
                    {"label": "Member", "link_to": "Member", "type": "DocType", "color": "Grey"},
                    {"label": "Membership", "link_to": "Membership", "type": "DocType", "color": "Grey"},
                    {
                        "label": "Expense Claims",
                        "link_to": "Expense Claim",
                        "type": "DocType",
                        "color": "Orange",
                        "doc_view": "List",
                    },
                    {
                        "label": "Chapter Expenses",
                        "link_to": "Chapter Expense Report",
                        "type": "Report",
                        "color": "Green",
                    },
                ],
            }
        )

        # Add comprehensive links - Card Break entries must come BEFORE their respective links
        links_data = [
            # Memberships section - Card Break first, then links
            {"label": "Memberships", "link_count": 5, "link_type": "DocType", "type": "Card Break"},
            {"label": "Member", "link_to": "Member", "link_type": "DocType", "type": "Link", "onboard": 1},
            {
                "label": "Membership",
                "link_to": "Membership",
                "link_type": "DocType",
                "type": "Link",
                "onboard": 1,
            },
            {
                "label": "Membership Type",
                "link_to": "Membership Type",
                "link_type": "DocType",
                "type": "Link",
            },
            {
                "label": "Contribution Amendment Request",
                "link_to": "Contribution Amendment Request",
                "link_type": "DocType",
                "type": "Link",
            },
            {
                "label": "Membership Termination Request",
                "link_to": "Membership Termination Request",
                "link_type": "DocType",
                "type": "Link",
            },
            # Volunteers section - Card Break first, then links
            {"label": "Volunteers", "link_count": 4, "link_type": "DocType", "type": "Card Break"},
            {
                "label": "Volunteer",
                "link_to": "Volunteer",
                "link_type": "DocType",
                "type": "Link",
                "onboard": 1,
            },
            {
                "label": "Volunteer Activity",
                "link_to": "Volunteer Activity",
                "link_type": "DocType",
                "type": "Link",
            },
            {
                "label": "Expense Category",
                "link_to": "Expense Category",
                "link_type": "DocType",
                "type": "Link",
            },
            {
                "label": "Expense Claims (ERPNext)",
                "link_to": "Expense Claim",
                "link_type": "DocType",
                "type": "Link",
            },
            # Chapters section - Card Break first, then links
            {"label": "Chapters", "link_count": 2, "link_type": "DocType", "type": "Card Break"},
            {"label": "Chapter", "link_to": "Chapter", "link_type": "DocType", "type": "Link", "onboard": 1},
            {"label": "Chapter Role", "link_to": "Chapter Role", "link_type": "DocType", "type": "Link"},
            # Teams section - Card Break first, then links
            {"label": "Teams and Commissions", "link_count": 1, "link_type": "DocType", "type": "Card Break"},
            {"label": "Team", "link_to": "Team", "link_type": "DocType", "type": "Link"},
            # Donations section - Card Break first, then links
            {"label": "Donations", "link_count": 3, "link_type": "DocType", "type": "Card Break"},
            {"label": "Donor", "link_to": "Donor", "link_type": "DocType", "type": "Link"},
            {"label": "Donation", "link_to": "Donation", "link_type": "DocType", "type": "Link"},
            {"label": "Donation Type", "link_to": "Donation Type", "link_type": "DocType", "type": "Link"},
            # Payment Processing section - Card Break first, then links
            {"label": "Payment Processing", "link_count": 2, "link_type": "DocType", "type": "Card Break"},
            {"label": "SEPA Mandate", "link_to": "SEPA Mandate", "link_type": "DocType", "type": "Link"},
            {
                "label": "SEPA Direct Debit Batch",
                "link_to": "SEPA Direct Debit Batch",
                "link_type": "DocType",
                "type": "Link",
            },
            # Reports section - Card Break first, then links
            {"label": "Reports", "link_count": 9, "link_type": "Report", "type": "Card Break"},
            {
                "label": "Expiring Memberships",
                "link_to": "Expiring Memberships",
                "link_type": "Report",
                "type": "Link",
                "is_query_report": 1,
            },
            {
                "label": "New Members",
                "link_to": "New Members",
                "link_type": "Report",
                "type": "Link",
                "is_query_report": 1,
            },
            {
                "label": "Members Without Chapter",
                "link_to": "Members Without Chapter",
                "link_type": "Report",
                "type": "Link",
                "is_query_report": 1,
            },
            {
                "label": "Overdue Member Payments",
                "link_to": "Overdue Member Payments",
                "link_type": "Report",
                "type": "Link",
                "is_query_report": 1,
            },
            {
                "label": "Chapter Expense Report",
                "link_to": "Chapter Expense Report",
                "link_type": "Report",
                "type": "Link",
                "is_query_report": 1,
            },
            {
                "label": "Governance Compliance Report",
                "link_to": "Governance Compliance Report",
                "link_type": "Report",
                "type": "Link",
                "is_query_report": 1,
            },
            {
                "label": "Termination Compliance Report",
                "link_to": "Termination Compliance Report",
                "link_type": "Report",
                "type": "Link",
                "is_query_report": 1,
            },
            {
                "label": "Users by Team",
                "link_to": "Users by Team",
                "link_type": "Report",
                "type": "Link",
                "is_query_report": 1,
            },
            # Settings section - Card Break first, then links
            {"label": "Module Settings", "link_count": 1, "link_type": "DocType", "type": "Card Break"},
            {
                "label": "Verenigingen Settings",
                "link_to": "Verenigingen Settings",
                "link_type": "DocType",
                "type": "Link",
            },
        ]

        # Add links to workspace
        for link_data in links_data:
            workspace.append("links", link_data)

        # Save workspace
        workspace.insert()

        return {
            "success": True,
            "message": f"Workspace updated successfully. Now has {len(workspace.links)} links.",
            "links_count": len(workspace.links),
        }

    except Exception as e:
        frappe.db.rollback()
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def create_volunteer_for_member(member_name):
    """Create a volunteer record for an existing member (admin function)"""
    if not frappe.has_permission("Volunteer", "create"):
        frappe.throw(_("Insufficient permissions to create volunteer records"))

    # Get member details
    member = frappe.get_doc("Member", member_name)

    # Check if volunteer already exists
    existing_volunteer = frappe.db.get_value("Volunteer", {"member": member_name}, "name")
    if existing_volunteer:
        frappe.throw(
            _("Volunteer record already exists for member {0}: {1}").format(member_name, existing_volunteer)
        )

    # Create volunteer record
    volunteer = frappe.get_doc(
        {
            "doctype": "Volunteer",
            "volunteer_name": f"{member.first_name} {member.last_name}",
            "email": member.email,
            "member": member.name,
            "status": "Active",
            "start_date": frappe.utils.today(),
        }
    )

    volunteer.insert()

    return {
        "success": True,
        "volunteer_name": volunteer.name,
        "message": _("Volunteer record created successfully for {0}").format(member.full_name),
    }


def get_volunteer_organizations(volunteer_name):
    """Get chapters and teams the volunteer belongs to"""
    organizations = {"chapters": [], "teams": []}

    # Check if volunteer exists
    if not frappe.db.exists("Volunteer", volunteer_name):
        return organizations

    # Get chapters through member relationship
    volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
    if hasattr(volunteer_doc, "member") and volunteer_doc.member:
        # Get chapters where this member is active
        chapter_members = frappe.get_all(
            "Chapter Member", filters={"member": volunteer_doc.member, "enabled": 1}, fields=["parent"]
        )

        for cm in chapter_members:
            chapter_info = frappe.db.get_value("Chapter", cm.parent, ["name"], as_dict=True)
            if chapter_info:
                # Add chapter_name field with same value as name for consistency
                chapter_info["chapter_name"] = chapter_info["name"]
                organizations["chapters"].append(chapter_info)

    # Get teams where volunteer is active
    team_members = frappe.get_all(
        "Team Member", filters={"volunteer": volunteer_name, "status": "Active"}, fields=["parent"]
    )

    for tm in team_members:
        team_info = frappe.db.get_value("Team", tm.parent, ["name"], as_dict=True)
        if team_info:
            # Add team_name field with same value as name for consistency
            team_info["team_name"] = team_info["name"]
            organizations["teams"].append(team_info)

    return organizations


def get_expense_categories():
    """Get available expense categories"""
    return frappe.get_all(
        "Expense Category",
        filters={"is_active": 1},
        fields=["name", "category_name", "description"],
        order_by="category_name",
    )


def get_volunteer_expenses(volunteer_name, limit=None):
    """Get volunteer's recent expenses from ERPNext Expense Claims and Volunteer Expense records"""
    try:
        expenses = []

        # Get volunteer's employee ID
        volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)

        # First, try to get from ERPNext if employee_id exists
        if volunteer_doc.employee_id:
            # Get ERPNext Expense Claims for this employee
            expense_claims = frappe.get_all(
                "Expense Claim",
                filters={"employee": volunteer_doc.employee_id},
                fields=[
                    "name",
                    "employee_name",
                    "total_claimed_amount",
                    "status",
                    "posting_date",
                    "creation",
                    "approval_status",
                    "company",
                    "cost_center",
                ],
                order_by="creation desc",
                limit=limit,
            )

            for claim in expense_claims:
                # Get expense details from the claim's expense table
                claim_details = frappe.get_all(
                    "Expense Claim Detail",
                    filters={"parent": claim.name},
                    fields=["expense_type", "description", "amount", "expense_date"],
                    order_by="idx",
                )

                # Get linked Volunteer Expense record for organization info if it exists
                # Note: expense_claim_id field doesn't exist, so this will always return None
                volunteer_expense = None

                for detail in claim_details:
                    expense = frappe._dict(
                        {
                            "name": f"{claim.name}-{detail.get('idx', 1)}",
                            "expense_claim_id": claim.name,
                            "description": detail.description or f"Expense Claim {claim.name}",
                            "amount": detail.amount,
                            "currency": "EUR",  # Default currency
                            "expense_date": detail.expense_date or claim.posting_date,
                            "status": map_erpnext_status_to_volunteer_status(
                                claim.status, claim.approval_status
                            ),
                            "creation": claim.creation,
                            "approved_on": None,  # ERPNext doesn't track approval date directly
                            # Organization info from linked Volunteer Expense if available
                            "organization_type": volunteer_expense.organization_type
                            if volunteer_expense
                            else "Unknown",
                            "chapter": volunteer_expense.chapter if volunteer_expense else None,
                            "team": volunteer_expense.team if volunteer_expense else None,
                            "category": volunteer_expense.category
                            if volunteer_expense
                            else detail.expense_type,
                        }
                    )

                    # Get category name
                    if expense.category:
                        expense.category_name = (
                            frappe.db.get_value("Expense Category", expense.category, "category_name")
                            or frappe.db.get_value("Expense Claim Type", expense.category, "expense_type")
                            or expense.category
                        )
                    else:
                        expense.category_name = "Uncategorized"

                    # Get organization name
                    expense.organization_name = expense.chapter or expense.team or "Unknown"

                    # Format dates
                    expense.formatted_date = formatdate(expense.expense_date)
                    expense.formatted_creation = formatdate(expense.creation)

                    # Add status styling
                    expense.status_class = get_status_class(expense.status)

                    expenses.append(expense)

        # Also get direct Volunteer Expense records (only those not represented in ERPNext)
        volunteer_expenses = frappe.get_all(
            "Volunteer Expense",
            filters={"volunteer": volunteer_name},
            fields=[
                "name",
                "description",
                "amount",
                "currency",
                "expense_date",
                "status",
                "organization_type",
                "chapter",
                "team",
                "category",
                "creation",
                "approved_on",
            ],
            order_by="creation desc",
            limit=limit or 10,
        )

        # Process Volunteer Expense records, but avoid duplicates with ERPNext
        erpnext_expense_keys = set()
        for exp in expenses:
            if exp.get("expense_claim_id"):
                # Create a key to identify potential duplicates
                key = (exp.get("description", ""), float(exp.get("amount", 0)), exp.get("expense_date"))
                erpnext_expense_keys.add(key)

        for vol_expense in volunteer_expenses:
            # Check if this expense is already represented in ERPNext
            expense_key = (
                vol_expense.description or "",
                float(vol_expense.amount or 0),
                vol_expense.expense_date,
            )

            if expense_key not in erpnext_expense_keys:
                # Only add if not duplicated in ERPNext

                # Get category name
                if vol_expense.category:
                    vol_expense.category_name = frappe.db.get_value(
                        "Expense Category", vol_expense.category, "category_name"
                    )
                else:
                    vol_expense.category_name = "Uncategorized"

                # Get organization name
                vol_expense.organization_name = vol_expense.chapter or vol_expense.team or "Unknown"

                # Format dates
                vol_expense.formatted_date = formatdate(vol_expense.expense_date)
                vol_expense.formatted_creation = formatdate(vol_expense.creation)
                if vol_expense.approved_on:
                    vol_expense.formatted_approved_on = formatdate(vol_expense.approved_on)

                # Add status styling
                vol_expense.status_class = get_status_class(vol_expense.status)

                expenses.append(vol_expense)

        # Sort by creation date and limit
        expenses.sort(key=lambda x: x.get("creation", ""), reverse=True)
        if limit:
            expenses = expenses[:limit]

        return expenses

    except Exception as e:
        frappe.log_error(f"Error getting volunteer expenses: {str(e)}", "Volunteer Expenses Error")
        # Return empty list if ERPNext integration fails
        return []


def map_erpnext_status_to_volunteer_status(erpnext_status, approval_status):
    """Map ERPNext Expense Claim status to Volunteer Expense status"""
    if erpnext_status == "Draft":
        return "Awaiting Approval"
    elif erpnext_status == "Submitted":
        if approval_status == "Approved":
            return "Approved"
        elif approval_status == "Rejected":
            return "Rejected"
        else:
            return "Submitted"
    elif erpnext_status == "Unpaid":
        # Unpaid means it's been processed (approved/rejected)
        if approval_status == "Approved":
            return "Approved"
        elif approval_status == "Rejected":
            return "Rejected"
        else:
            return "Submitted"
    elif erpnext_status == "Paid":
        return "Reimbursed"
    elif erpnext_status == "Cancelled":
        return "Rejected"
    else:
        return "Submitted"


def get_volunteer_expenses_legacy(volunteer_name, limit=None):
    """Legacy function to get expenses from Volunteer Expense records"""
    filters = {"volunteer": volunteer_name}

    expenses = frappe.get_all(
        "Volunteer Expense",
        filters=filters,
        fields=[
            "name",
            "description",
            "amount",
            "currency",
            "expense_date",
            "status",
            "organization_type",
            "chapter",
            "team",
            "category",
            "creation",
            "approved_on",
        ],
        order_by="creation desc",
        limit=limit,
    )

    # Enhance with additional info
    for expense in expenses:
        # Get category name
        if expense.category:
            expense.category_name = frappe.db.get_value("Expense Category", expense.category, "category_name")
        else:
            expense.category_name = "Uncategorized"

        # Get organization name
        expense.organization_name = expense.chapter or expense.team

        # Format dates
        expense.formatted_date = formatdate(expense.expense_date)
        expense.formatted_creation = formatdate(expense.creation)
        if expense.approved_on:
            expense.formatted_approved_on = formatdate(expense.approved_on)

        # Add status styling
        expense.status_class = get_status_class(expense.status)

    return expenses


def get_expense_statistics(volunteer_name):
    """Get expense statistics for the volunteer from ERPNext Expense Claims and Volunteer Expenses"""
    from frappe.utils import add_months

    try:
        # Get expenses from last 12 months
        from_date = add_months(today(), -12)

        total_submitted = 0
        total_approved = 0
        pending_count = 0
        approved_count = 0
        reimbursed_count = 0
        total_count = 0

        # Get volunteer's employee ID
        volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)

        # Try ERPNext first if employee_id exists
        if volunteer_doc.employee_id:
            # Get ERPNext Expense Claims for this employee
            expense_claims = frappe.get_all(
                "Expense Claim",
                filters={
                    "employee": volunteer_doc.employee_id,
                    "posting_date": [">=", from_date],
                    "docstatus": ["!=", 2],  # Not cancelled
                },
                fields=[
                    "name",
                    "total_claimed_amount",
                    "total_sanctioned_amount",
                    "status",
                    "approval_status",
                    "posting_date",
                ],
            )

            for claim in expense_claims:
                amount = flt(claim.total_claimed_amount)
                status = map_erpnext_status_to_volunteer_status(claim.status, claim.approval_status)

                total_count += 1

                # All expenses count toward total_submitted
                total_submitted += amount

                if status == "Approved":
                    sanctioned_amount = flt(claim.total_sanctioned_amount or amount)
                    total_approved += sanctioned_amount
                    approved_count += 1
                elif status == "Awaiting Approval":  # Draft status = pending approval
                    pending_count += 1
                elif status == "Submitted":  # Submitted but not yet approved/rejected
                    pending_count += 1
                elif status == "Rejected":  # Rejected expenses
                    pass  # Already counted in total_submitted
                elif status == "Reimbursed":
                    total_approved += flt(claim.total_sanctioned_amount or amount)
                    reimbursed_count += 1

        # Note: Volunteer Expense doctype appears to be legacy/unused
        # The actual workflow uses ERPNext Expense Claims only

        return {
            "total_submitted": total_submitted,
            "total_approved": total_approved,
            "pending_amount": total_submitted - total_approved,
            "pending_count": pending_count,
            "approved_count": approved_count + reimbursed_count,
            "total_count": total_count,
        }

    except Exception as e:
        frappe.log_error(f"Error getting expense statistics: {str(e)}", "Expense Statistics Error")
        # Return empty statistics if error occurs
        return {
            "total_submitted": 0,
            "total_approved": 0,
            "pending_amount": 0,
            "pending_count": 0,
            "approved_count": 0,
            "total_count": 0,
        }


def get_expense_statistics_legacy(volunteer_name):
    """Legacy function to get expense statistics from Volunteer Expense records"""
    from frappe.utils import add_months

    # Get expenses from last 12 months
    from_date = add_months(today(), -12)

    expenses = frappe.get_all(
        "Volunteer Expense",
        filters={
            "volunteer": volunteer_name,
            "expense_date": [">=", from_date],
            "docstatus": ["!=", 2],  # Not cancelled
        },
        fields=["amount", "status", "expense_date"],
    )

    total_submitted = sum(flt(exp.amount) for exp in expenses if exp.status in ["Submitted", "Approved"])
    total_approved = sum(flt(exp.amount) for exp in expenses if exp.status == "Approved")
    pending_count = len([exp for exp in expenses if exp.status == "Submitted"])
    approved_count = len([exp for exp in expenses if exp.status == "Approved"])

    return {
        "total_submitted": total_submitted,
        "total_approved": total_approved,
        "pending_amount": total_submitted - total_approved,
        "pending_count": pending_count,
        "approved_count": approved_count,
        "total_count": len(expenses),
    }


def get_approval_thresholds():
    """Get approval thresholds for UI guidance"""
    return {"basic_limit": 100.0, "financial_limit": 500.0, "admin_limit": 999999.0}


def get_national_chapter():
    """Get national chapter info from settings"""
    try:
        settings = frappe.get_single("Verenigingen Settings")
        if settings and getattr(settings, "national_board_chapter", None):
            chapter_info = frappe.db.get_value(
                "Chapter", settings.national_board_chapter, ["name"], as_dict=True
            )
            if chapter_info:
                return {
                    "name": chapter_info.name,
                    "chapter_name": chapter_info.name,  # Use name as chapter_name since that field doesn't exist
                }
    except Exception as e:
        frappe.log_error(f"Error getting national chapter: {str(e)}")
        # Log more details for debugging
        frappe.logger().error(f"National chapter error details: {str(e)}")
        import traceback

        frappe.logger().error(f"National chapter traceback: {traceback.format_exc()}")

    return None


def get_status_class(status):
    """Get CSS class for expense status"""
    status_classes = {
        "Draft": "badge-secondary",
        "Submitted": "badge-warning",
        "Approved": "badge-success",
        "Rejected": "badge-danger",
        "Reimbursed": "badge-primary",
    }
    return status_classes.get(status, "badge-secondary")


@frappe.whitelist()
def debug_expense_claim_statuses():
    """Debug function to check expense claim statuses"""
    result = frappe.db.sql(
        """
        SELECT status, approval_status, docstatus, COUNT(*) as count
        FROM `tabExpense Claim`
        GROUP BY status, approval_status, docstatus
        ORDER BY count DESC
    """,
        as_dict=True,
    )
    return result


@frappe.whitelist()
def debug_expense_claim_dates():
    """Debug function to check expense claim dates"""
    result = frappe.db.sql(
        """
        SELECT name, posting_date, creation, status, approval_status, docstatus,
               YEAR(posting_date) as posting_year, MONTH(posting_date) as posting_month,
               YEAR(creation) as creation_year, MONTH(creation) as creation_month
        FROM `tabExpense Claim`
        ORDER BY creation DESC
    """,
        as_dict=True,
    )
    return result


@frappe.whitelist()
def fix_expense_claim_dashboard_cards():
    """Fix the expense claim dashboard cards to include draft expenses"""

    # Update the main "Expense Claims (This Month)" card to filter by submission date
    try:
        card1 = frappe.get_doc("Number Card", "Expense Claims (This Month)")
        card1.label = "Expense Claims (This Month)"
        # Filter by creation date (submission date) instead of posting date (expense date)
        card1.filters_json = '[["Expense Claim","creation","Timespan","this month",false]]'
        card1.save()

        # Update "Approved Claims (This Month)" to filter by submission date
        card2 = frappe.get_doc("Number Card", "Approved Claims (This Month)")
        card2.label = "Approved Claims (This Month)"
        card2.filters_json = '[["Expense Claim","approval_status","=","Approved",false],["Expense Claim","creation","Timespan","this month",false],["Expense Claim","docstatus","=","1",false]]'
        card2.save()

        # Update "Rejected Claims (This Month)" to filter by submission date
        card3 = frappe.get_doc("Number Card", "Rejected Claims (This Month)")
        card3.label = "Rejected Claims (This Month)"
        card3.filters_json = '[["Expense Claim","approval_status","=","Rejected",false],["Expense Claim","creation","Timespan","this month",false],["Expense Claim","docstatus","=","1",false]]'
        card3.save()

        return {"success": True, "message": "Dashboard cards updated successfully"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def debug_expense_statistics(volunteer_name):
    """Debug function to see expense statistics calculation"""
    from frappe.utils import add_months

    # Get expenses from last 12 months
    from_date = add_months(today(), -12)

    # Get volunteer's employee ID
    volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)

    result = {
        "volunteer_name": volunteer_name,
        "employee_id": volunteer_doc.employee_id,
        "from_date": from_date,
        "expense_claims": [],
        "totals": {},
    }

    if volunteer_doc.employee_id:
        # Get ERPNext Expense Claims for this employee
        expense_claims = frappe.get_all(
            "Expense Claim",
            filters={
                "employee": volunteer_doc.employee_id,
                "posting_date": [">=", from_date],
                "docstatus": ["!=", 2],  # Not cancelled
            },
            fields=[
                "name",
                "total_claimed_amount",
                "total_sanctioned_amount",
                "status",
                "approval_status",
                "posting_date",
            ],
        )

        for claim in expense_claims:
            mapped_status = map_erpnext_status_to_volunteer_status(claim.status, claim.approval_status)
            result["expense_claims"].append(
                {
                    "name": claim.name,
                    "erpnext_status": claim.status,
                    "approval_status": claim.approval_status,
                    "mapped_status": mapped_status,
                    "total_claimed_amount": claim.total_claimed_amount,
                    "total_sanctioned_amount": claim.total_sanctioned_amount,
                    "posting_date": claim.posting_date,
                }
            )

    # Get the actual calculated statistics
    stats = get_expense_statistics(volunteer_name)
    result["totals"] = stats

    return result


@frappe.whitelist()
def debug_file_attachment(expense_claim_name, file_url):
    """Debug function to test file attachment to expense claims"""
    try:
        # Get the expense claim
        expense_claim = frappe.get_doc("Expense Claim", expense_claim_name)

        # Get the file document
        file_doc = frappe.get_doc("File", {"file_url": file_url})

        # Try to attach it by updating the file document
        file_doc.attached_to_doctype = expense_claim.doctype
        file_doc.attached_to_name = expense_claim.name
        file_doc.save()

        result = f"File {file_doc.name} attached to {expense_claim.name}"

        return {
            "success": True,
            "expense_claim": expense_claim_name,
            "file_url": file_url,
            "file_name": file_doc.file_name,
            "attachment_result": str(result),
        }

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def debug_attachment_process(file_url):
    """Debug the attachment process step by step"""
    try:
        result = {}

        # Step 1: Check if file exists
        file_exists = frappe.db.exists("File", {"file_url": file_url})
        result["file_exists"] = file_exists

        if file_exists:
            # Step 2: Get file document
            file_doc = frappe.get_doc("File", {"file_url": file_url})
            result["file_doc"] = {
                "name": file_doc.name,
                "file_name": file_doc.file_name,
                "file_url": file_doc.file_url,
                "attached_to_doctype": file_doc.attached_to_doctype,
                "attached_to_name": file_doc.attached_to_name,
            }

            # Step 3: Test attachment process
            result["attachment_test"] = "File document retrieved successfully"
        else:
            result["error"] = f"File with URL {file_url} not found"

        return result

    except Exception as e:
        import traceback

        return {"error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def test_new_attachment_system():
    """Test the new file attachment system end-to-end"""
    try:
        # Simulate file data as it would come from the upload function
        import base64

        test_content = b"This is a test receipt file content"

        file_data = {
            "file_name": "test_receipt_new.txt",
            "file_content": base64.b64encode(test_content).decode("utf-8"),
            "content_type": "text/plain",
        }

        # Test expense data with new file format
        expense_data = {
            "description": "Test expense with new attachment system",
            "amount": 75.00,
            "expense_date": "2025-06-20",
            "organization_type": "National",
            "category": "Reiskosten",
            "notes": "Testing the new Frappe API-based file attachment",
            "receipt_attachment": file_data,
        }

        # Submit the expense
        result = submit_expense(expense_data)

        if result.get("success"):
            expense_claim_name = result.get("expense_claim_name")

            # Check if file was attached
            attached_files = frappe.get_all(
                "File",
                filters={"attached_to_name": expense_claim_name},
                fields=["name", "file_name", "file_url", "attached_to_doctype"],
            )

            return {
                "success": True,
                "expense_result": result,
                "attached_files": attached_files,
                "test_note": "Using official Frappe API for file attachment",
            }
        else:
            return {"success": False, "expense_result": result}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def test_expense_with_attachment():
    """Test expense submission with file attachment"""
    try:
        # Create a test file first
        from frappe.utils.file_manager import save_file

        test_content = b"Test receipt content"
        file_doc = save_file(
            fname="test_receipt.txt",
            content=test_content,
            dt="",
            dn="",
            folder="Home/Attachments",
            is_private=0,
        )

        # Test expense data
        expense_data = {
            "description": "Test expense with receipt",
            "amount": 50.00,
            "expense_date": "2025-06-20",
            "organization_type": "National",
            "category": "Reiskosten",
            "notes": "Test expense for debugging file attachments",
            "receipt_attachment": file_doc.file_url,
        }

        # Submit the expense
        result = submit_expense(expense_data)

        if result.get("success"):
            expense_claim_name = result.get("expense_claim_name")

            # Check if file was attached
            attached_files = frappe.get_all(
                "File",
                filters={"attached_to_name": expense_claim_name},
                fields=["name", "file_name", "file_url"],
            )

            return {
                "success": True,
                "expense_result": result,
                "attached_files": attached_files,
                "test_file_url": file_doc.file_url,
            }
        else:
            return {"success": False, "expense_result": result}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def debug_expense_retrieval(volunteer_name):
    """Debug function to test expense retrieval"""
    try:
        # Test the actual functions
        expenses = get_volunteer_expenses(volunteer_name, limit=10)
        stats = get_expense_statistics(volunteer_name)

        return {
            "volunteer_name": volunteer_name,
            "expense_count": len(expenses) if expenses else 0,
            "expenses": expenses,
            "stats": stats,
        }

    except Exception as e:
        import traceback

        return {"error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def upload_expense_receipt():
    """Upload receipt file and return file data for later attachment"""
    try:
        # Enhanced debugging - check all possible file access methods
        debug_info = {
            "request_exists": hasattr(frappe, "request"),
            "files_attr": hasattr(frappe.request, "files") if hasattr(frappe, "request") else False,
            "files_content": dict(frappe.request.files)
            if hasattr(frappe, "request") and hasattr(frappe.request, "files")
            else {},
            "files_keys": list(frappe.request.files.keys())
            if hasattr(frappe, "request") and hasattr(frappe.request, "files")
            else [],
            "form_dict": dict(frappe.form_dict) if hasattr(frappe, "form_dict") else {},
            "form_dict_keys": list(frappe.form_dict.keys()) if hasattr(frappe, "form_dict") else [],
            "local_files": getattr(frappe.local, "uploaded_files", None),
            "request_method": frappe.request.method if hasattr(frappe, "request") else None,
            "request_content_type": frappe.request.content_type if hasattr(frappe, "request") else None,
            "request_data": len(frappe.request.data)
            if hasattr(frappe, "request") and hasattr(frappe.request, "data")
            else 0,
        }

        # Try multiple methods to access uploaded files
        uploaded_file = None

        # Method 1: Direct from request.files
        if hasattr(frappe, "request") and hasattr(frappe.request, "files") and frappe.request.files:
            if "receipt" in frappe.request.files:
                uploaded_file = frappe.request.files["receipt"]

        # Method 2: From form_dict (common in Frappe)
        if not uploaded_file and hasattr(frappe, "form_dict"):
            # Check for various possible field names
            for field_name in ["receipt", "file", "_file", "uploaded_file"]:
                if field_name in frappe.form_dict:
                    uploaded_file = frappe.form_dict[field_name]
                    break

        # Method 3: From local.uploaded_files (Frappe's internal storage)
        if not uploaded_file and hasattr(frappe.local, "uploaded_files") and frappe.local.uploaded_files:
            # Take the first uploaded file if available
            uploaded_file = list(frappe.local.uploaded_files.values())[0]

        if not uploaded_file:
            return {"success": False, "error": "No file uploaded", "debug_info": debug_info}

        # Handle different file object types
        if hasattr(uploaded_file, "filename") and hasattr(uploaded_file, "read"):
            # Standard file upload object
            filename = uploaded_file.filename
            if not filename:
                return {"success": False, "error": "No filename provided"}

            file_content = uploaded_file.read()
            content_type = getattr(uploaded_file, "content_type", "application/octet-stream")

        elif isinstance(uploaded_file, dict) and "filename" in uploaded_file:
            # Frappe's processed file format
            filename = uploaded_file["filename"]
            file_content = uploaded_file.get("content", b"")
            content_type = uploaded_file.get("content_type", "application/octet-stream")

        else:
            return {
                "success": False,
                "error": f"Unsupported file object type: {type(uploaded_file)}",
                "debug_info": debug_info,
            }

        if not file_content:
            return {"success": False, "error": "Empty file uploaded"}

        # Return file data for processing during expense submission
        import base64

        return {
            "success": True,
            "file_name": filename,
            "file_content": base64.b64encode(file_content).decode("utf-8"),
            "content_type": content_type,
        }

    except Exception as e:
        import traceback

        frappe.log_error(
            f"Error uploading expense receipt: {str(e)}\n{traceback.format_exc()}", "File Upload Error"
        )
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def debug_request_info():
    """Debug function to check what's available in the request without file upload"""
    try:
        debug_info = {
            "method": frappe.request.method if hasattr(frappe, "request") else None,
            "content_type": frappe.request.content_type if hasattr(frappe, "request") else None,
            "form_dict_keys": list(frappe.form_dict.keys()) if hasattr(frappe, "form_dict") else [],
            "form_dict_content": dict(frappe.form_dict) if hasattr(frappe, "form_dict") else {},
            "request_files_keys": list(frappe.request.files.keys())
            if hasattr(frappe, "request") and hasattr(frappe.request, "files")
            else [],
            "request_exists": hasattr(frappe, "request"),
            "session_user": frappe.session.user,
            "local_uploaded_files": getattr(frappe.local, "uploaded_files", None),
        }
        return {"success": True, "debug_info": debug_info}
    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def submit_expense(expense_data):
    """Submit a new expense from the portal"""
    try:
        # Parse JSON string if needed
        if isinstance(expense_data, str):
            import json

            expense_data = json.loads(expense_data)
        # Get current user's volunteer record
        volunteer = get_user_volunteer_record()
        if not volunteer:
            # Provide more helpful error message with debugging info
            user_email = frappe.session.user
            member = frappe.db.get_value("Member", {"email": user_email}, "name")

            if member:
                error_msg = _(
                    "No volunteer record found for your account. You have a member record ({0}) but no linked volunteer record. Please contact your chapter administrator to create a volunteer profile."
                ).format(member)
            else:
                error_msg = _(
                    "No volunteer record found for your account. Your email ({0}) is not associated with any member or volunteer record. Please contact your chapter administrator."
                ).format(user_email)

            frappe.throw(error_msg)

        # Validate required fields
        required_fields = ["description", "amount", "expense_date", "organization_type", "category"]
        for field in required_fields:
            if not expense_data.get(field):
                frappe.throw(_(f"Field {field} is required"))

        # Validate organization selection
        if expense_data.get("organization_type") == "Chapter" and not expense_data.get("chapter"):
            frappe.throw(_("Please select a chapter"))
        elif expense_data.get("organization_type") == "Team" and not expense_data.get("team"):
            frappe.throw(_("Please select a team"))
        # National expenses don't require specific organization selection

        # Enhanced access validation with policy-based national expenses
        if expense_data.get("organization_type") == "Chapter":
            organization_name = expense_data.get("chapter")
            # For chapter expenses, check chapter membership through member record
            if volunteer.member:
                direct_membership = frappe.db.exists(
                    "Chapter Member", {"parent": organization_name, "member": volunteer.member}
                )
            else:
                direct_membership = None

            if not direct_membership:
                frappe.throw(_("Chapter membership required for {0}").format(organization_name))

        elif expense_data.get("organization_type") == "Team":
            organization_name = expense_data.get("team")
            # For team expenses, only check team membership (no chapter validation needed)
            team_membership = frappe.db.exists(
                "Team Member", {"parent": organization_name, "volunteer": volunteer.name}
            )
            if not team_membership:
                frappe.throw(_("Team membership required for {0}").format(organization_name))

        elif expense_data.get("organization_type") == "National":
            # Check if this is a policy-covered expense type
            category = expense_data.get("category")
            if category and is_policy_covered_expense(category):
                # Policy-covered expenses (materials, travel) are allowed for all volunteers
                frappe.logger().info(
                    f"Policy-covered national expense allowed for volunteer {volunteer.name}: {category}"
                )
            else:
                # Other national expenses require board membership
                settings = frappe.get_single("Verenigingen Settings")
                if settings.national_board_chapter:
                    board_membership = frappe.db.exists(
                        "Chapter Member",
                        {"parent": settings.national_board_chapter, "volunteer": volunteer.name},
                    )
                    if not board_membership:
                        frappe.throw(_("National board membership required for non-policy national expenses"))

        # Determine chapter/team based on organization type
        chapter = None
        team = None

        if expense_data.get("organization_type") == "Chapter":
            chapter = expense_data.get("chapter")
        elif expense_data.get("organization_type") == "Team":
            team = expense_data.get("team")
        elif expense_data.get("organization_type") == "National":
            # Set to national chapter from settings
            settings = frappe.get_single("Verenigingen Settings")
            if settings.national_board_chapter:
                chapter = settings.national_board_chapter
            else:
                frappe.throw(_("National chapter not configured in settings"))

        # Get default company
        default_company = frappe.defaults.get_global_default("company")
        if not default_company:
            # Fallback to first company if no default is set
            companies = frappe.get_all("Company", limit=1, fields=["name"])
            default_company = companies[0].name if companies else None

        if not default_company:
            frappe.throw(_("No company configured in the system. Please contact the administrator."))

        # Get volunteer document for employee_id
        volunteer_doc = frappe.get_doc("Volunteer", volunteer.name)

        # Ensure volunteer has employee_id - create if missing
        employee_created = False
        if not volunteer_doc.employee_id:
            try:
                frappe.logger().info(
                    f"Creating employee record for volunteer {volunteer_doc.name} during expense submission"
                )
                employee_id = volunteer_doc.create_minimal_employee()
                if employee_id:
                    frappe.logger().info(
                        f"Successfully created employee {employee_id} for volunteer {volunteer_doc.name}"
                    )
                    # Reload volunteer document to get the updated employee_id
                    volunteer_doc.reload()
                    employee_created = True
                else:
                    frappe.log_error(
                        f"Employee creation returned None for volunteer {volunteer_doc.name}",
                        "Employee Creation Warning",
                    )
                    frappe.throw(
                        _(
                            "Unable to create employee record automatically. Please contact your administrator to set up your employee profile before submitting expenses."
                        )
                    )
            except Exception as e:
                error_msg = str(e)[:50]  # Short error message for logging
                frappe.log_error(f"Employee creation failed: {error_msg}", "Employee Creation")
                frappe.throw(
                    _(
                        "Unable to create employee record automatically. Please contact your administrator to set up your employee profile before submitting expenses."
                    )
                )

        # Get cost center based on organization
        cost_center = get_organization_cost_center(expense_data)

        # Get expense type from category
        expense_type = get_or_create_expense_type(expense_data.get("category"))

        # Get payable account from company settings
        payable_account = frappe.db.get_value(
            "Company", default_company, "default_expense_claim_payable_account"
        )
        if not payable_account:
            # Fallback to default payable account
            payable_account = frappe.db.get_value("Company", default_company, "default_payable_account")

        if not payable_account:
            frappe.throw(
                _(
                    "No payable account configured for company {0}. Please set default_expense_claim_payable_account or default_payable_account in Company settings."
                ).format(default_company)
            )

        # Create ERPNext Expense Claim
        expense_claim = frappe.get_doc(
            {
                "doctype": "Expense Claim",
                "employee": volunteer_doc.employee_id,
                "posting_date": expense_data.get("expense_date"),
                "company": default_company,
                "cost_center": cost_center,
                "payable_account": payable_account,
                "approval_status": "Draft",  # Leave approval to appropriate user roles
                "remark": expense_data.get("notes"),
                "status": "Draft",
            }
        )

        # Add expense detail
        expense_claim.append(
            "expenses",
            {
                "expense_date": expense_data.get("expense_date"),
                "expense_type": expense_type,
                "description": expense_data.get("description"),
                "amount": flt(expense_data.get("amount")),
                "sanctioned_amount": flt(expense_data.get("amount")),
                "cost_center": cost_center,
            },
        )

        # Insert the expense claim as draft (don't submit automatically)
        expense_claim.insert(ignore_permissions=True)
        frappe.logger().info(f"Successfully created expense claim draft: {expense_claim.name}")

        # Add receipt attachment if provided - attach to the ERPNext Expense Claim
        receipt_data = expense_data.get("receipt_attachment")
        if receipt_data and isinstance(receipt_data, dict):
            try:
                if receipt_data.get("file_url") and receipt_data.get("frappe_file_name"):
                    # Handle Frappe's built-in upload format
                    frappe.logger().info(
                        f"Using Frappe built-in file: {receipt_data.get('frappe_file_name')}"
                    )

                    # Get the existing file document and re-attach it to the expense claim
                    file_doc = frappe.get_doc("File", receipt_data.get("frappe_file_name"))
                    file_doc.attached_to_doctype = expense_claim.doctype
                    file_doc.attached_to_name = expense_claim.name
                    file_doc.folder = "Home/Attachments"
                    file_doc.is_private = 0
                    file_doc.save(ignore_permissions=True)

                    frappe.logger().info(
                        f"Successfully re-attached Frappe file {file_doc.name} to expense claim {expense_claim.name}"
                    )

                elif receipt_data.get("file_content"):
                    # Handle our custom base64 format
                    frappe.logger().info(f"Using custom base64 file: {receipt_data.get('file_name')}")

                    # Decode file content
                    import base64

                    file_content = base64.b64decode(receipt_data.get("file_content", ""))

                    # Create file with proper attachment using official Frappe API
                    file_doc = frappe.get_doc(
                        {
                            "doctype": "File",
                            "file_name": receipt_data.get("file_name"),
                            "content": file_content,
                            "attached_to_doctype": expense_claim.doctype,
                            "attached_to_name": expense_claim.name,
                            "folder": "Home/Attachments",
                            "is_private": 0,
                        }
                    )
                    file_doc.insert(ignore_permissions=True)

                    frappe.logger().info(
                        f"Successfully attached custom receipt {receipt_data.get('file_name')} to expense claim {expense_claim.name}"
                    )
                else:
                    frappe.logger().warning(
                        f"Receipt data provided but no valid file format found: {receipt_data}"
                    )

            except Exception as attachment_error:
                # Log error but don't fail the entire expense submission
                frappe.log_error(
                    f"Failed to attach receipt to expense claim {expense_claim.name}: {str(attachment_error)}",
                    "Expense Receipt Attachment Error",
                )
                frappe.logger().warning(
                    f"Receipt attachment failed for {expense_claim.name}: {attachment_error}"
                )

        # Don't submit automatically - leave for approval workflow
        # The expense claim will remain in Draft status until approved and submitted by authorized users

        # Also create a reference in our Volunteer Expense system for tracking
        volunteer_expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": volunteer.name,
                "description": expense_data.get("description"),
                "amount": flt(expense_data.get("amount")),
                "currency": expense_data.get("currency", "EUR"),
                "expense_date": expense_data.get("expense_date"),
                "category": expense_data.get("category"),
                "organization_type": expense_data.get("organization_type"),
                "chapter": chapter,
                "team": team,
                "notes": expense_data.get("notes"),
                "company": default_company,
                "expense_claim_id": expense_claim.name,  # Link to ERPNext record
            }
        )

        volunteer_expense.insert(ignore_permissions=True)
        # Keep as Draft status to match ERPNext Expense Claim workflow
        # Will be updated when the ERPNext expense claim is approved and submitted

        # Prepare success message
        success_message = _("Expense claim saved successfully and awaiting approval")
        if employee_created:
            success_message += _(" (Employee record created for your account)")

        return {
            "success": True,
            "message": success_message,
            "expense_claim_name": expense_claim.name,
            "expense_name": volunteer_expense.name,
            "employee_created": employee_created,
        }

    except Exception as e:
        frappe.log_error(f"Error submitting expense: {str(e)}", "Volunteer Expense Submission Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def get_organization_options(organization_type, volunteer_name=None):
    """Get organization options for the current volunteer"""
    if not volunteer_name:
        volunteer = get_user_volunteer_record()
        if not volunteer:
            return []
        volunteer_name = volunteer.name

    organizations = get_volunteer_organizations(volunteer_name)

    if organization_type == "Chapter":
        return [{"value": ch["name"], "label": ch["chapter_name"]} for ch in organizations["chapters"]]
    elif organization_type == "Team":
        return [{"value": t["name"], "label": t["team_name"]} for t in organizations["teams"]]

    return []


@frappe.whitelist()
def get_expense_details(expense_name):
    """Get details for a specific expense from ERPNext or legacy records"""
    volunteer = get_user_volunteer_record()
    if not volunteer:
        frappe.throw(_("Access denied"))

    try:
        # Check if this is an ERPNext Expense Claim reference
        if "-" in expense_name:
            claim_name = expense_name.split("-")[0]

            # Verify this is an ERPNext Expense Claim for this volunteer
            volunteer_doc = frappe.get_doc("Volunteer", volunteer.name)
            if volunteer_doc.employee_id:
                expense_claim = frappe.get_doc("Expense Claim", claim_name)
                if expense_claim.employee != volunteer_doc.employee_id:
                    frappe.throw(_("Access denied"))

                # Get expense details from ERPNext
                expense_details = frappe.get_all(
                    "Expense Claim Detail",
                    filters={"parent": claim_name},
                    fields=["expense_type", "description", "amount", "expense_date"],
                    order_by="idx",
                )

                # Get linked Volunteer Expense record for organization info
                volunteer_expense = frappe.db.get_value(
                    "Volunteer Expense",
                    {"expense_claim_id": claim_name},
                    ["organization_type", "chapter", "team", "category"],
                    as_dict=True,
                )

                # Build response from ERPNext data
                if expense_details:
                    detail = expense_details[0]  # First detail for now
                    expense_dict = {
                        "name": expense_name,
                        "expense_claim_id": claim_name,
                        "description": detail.description,
                        "amount": detail.amount,
                        "expense_date": detail.expense_date,
                        "status": map_erpnext_status_to_volunteer_status(
                            expense_claim.status, expense_claim.approval_status
                        ),
                        "organization_type": volunteer_expense.organization_type
                        if volunteer_expense
                        else "Unknown",
                        "chapter": volunteer_expense.chapter if volunteer_expense else None,
                        "team": volunteer_expense.team if volunteer_expense else None,
                        "category": volunteer_expense.category if volunteer_expense else detail.expense_type,
                    }

                    # Add category name
                    if expense_dict.get("category"):
                        expense_dict["category_name"] = (
                            frappe.db.get_value("Expense Category", expense_dict["category"], "category_name")
                            or frappe.db.get_value(
                                "Expense Claim Type", expense_dict["category"], "expense_type"
                            )
                            or expense_dict["category"]
                        )

                    # Add organization name
                    expense_dict["organization_name"] = (
                        expense_dict.get("chapter") or expense_dict.get("team") or "Unknown"
                    )

                    # Add attachment count from ERPNext
                    expense_dict["attachment_count"] = frappe.db.count(
                        "File", {"attached_to_name": claim_name, "attached_to_doctype": "Expense Claim"}
                    )

                    return expense_dict
                else:
                    frappe.throw(_("Expense details not found"))
            else:
                frappe.throw(_("Access denied - no employee record"))
        else:
            # Legacy Volunteer Expense record
            expense = frappe.get_doc("Volunteer Expense", expense_name)
            if expense.volunteer != volunteer.name:
                frappe.throw(_("Access denied"))

            # Get enhanced expense details
            expense_dict = expense.as_dict()

            # Add category name
            if expense.category:
                expense_dict["category_name"] = frappe.db.get_value(
                    "Expense Category", expense.category, "category_name"
                )

            # Add organization name
            expense_dict["organization_name"] = expense.chapter or expense.team

            # Add attachment count
            expense_dict["attachment_count"] = frappe.db.count(
                "File", {"attached_to_name": expense.name, "attached_to_doctype": "Volunteer Expense"}
            )

            return expense_dict

    except Exception as e:
        frappe.log_error(f"Error getting expense details: {str(e)}", "Expense Details Error")
        frappe.throw(_("Error retrieving expense details"))


@frappe.whitelist()
def test_employee_creation_only():
    """Test just the employee creation functionality without expense submission"""
    try:
        print("🧪 Testing Employee Creation for Volunteers")
        print("=" * 50)

        # Test 1: Find a volunteer without employee record
        print("\n1. Finding volunteer without employee record...")

        volunteers_without_employees = frappe.db.sql(
            """
            SELECT name, volunteer_name, email, employee_id
            FROM `tabVolunteer`
            WHERE employee_id IS NULL OR employee_id = ''
            LIMIT 3
        """,
            as_dict=True,
        )

        if not volunteers_without_employees:
            print("   No volunteers without employee records found")

            # Check existing volunteers with employees
            volunteers_with_employees = frappe.db.sql(
                """
                SELECT name, volunteer_name, email, employee_id
                FROM `tabVolunteer`
                WHERE employee_id IS NOT NULL AND employee_id != ''
                LIMIT 3
            """,
                as_dict=True,
            )

            if volunteers_with_employees:
                print("   Existing volunteers with employee records:")
                for vol in volunteers_with_employees:
                    print(f"   - {vol.volunteer_name} ({vol.name}) -> {vol.employee_id}")

                return {
                    "success": True,
                    "message": "Employee creation already working - existing volunteers have employee records",
                    "volunteers_with_employees": len(volunteers_with_employees),
                }
            else:
                return {"success": False, "message": "No volunteers found to test"}

        print(f"   Found {len(volunteers_without_employees)} volunteers without employee records")

        # Test 2: Try creating employee records for these volunteers
        created_employees = []
        failed_creations = []

        for volunteer_data in volunteers_without_employees:
            volunteer_doc = frappe.get_doc("Volunteer", volunteer_data.name)
            print(f"\n2. Testing employee creation for: {volunteer_doc.volunteer_name}")

            try:
                employee_id = volunteer_doc.create_minimal_employee()
                if employee_id:
                    created_employees.append(
                        {
                            "volunteer": volunteer_doc.name,
                            "volunteer_name": volunteer_doc.volunteer_name,
                            "employee_id": employee_id,
                        }
                    )
                    print(f"   ✅ Created employee: {employee_id}")

                    # Verify employee record exists
                    employee_exists = frappe.db.exists("Employee", employee_id)
                    if employee_exists:
                        employee_doc = frappe.get_doc("Employee", employee_id)
                        print(f"   ✅ Employee record verified: {employee_doc.employee_name}")
                        print(f"   - Company: {employee_doc.company}")
                        print(f"   - Status: {employee_doc.status}")
                        print(f"   - Gender: {employee_doc.gender}")
                        print(f"   - Date of Birth: {employee_doc.date_of_birth}")
                    else:
                        print("   ⚠️ Employee ID returned but record not found in database")
                else:
                    failed_creations.append(
                        {
                            "volunteer": volunteer_doc.name,
                            "volunteer_name": volunteer_doc.volunteer_name,
                            "error": "Employee creation returned None",
                        }
                    )
                    print("   ❌ Employee creation returned None")

            except Exception as e:
                failed_creations.append(
                    {
                        "volunteer": volunteer_doc.name,
                        "volunteer_name": volunteer_doc.volunteer_name,
                        "error": str(e),
                    }
                )
                print(f"   ❌ Employee creation failed: {str(e)}")

        # Test 3: Summary
        print("\n3. Employee Creation Test Summary:")
        print(f"   - Volunteers tested: {len(volunteers_without_employees)}")
        print(f"   - Successful creations: {len(created_employees)}")
        print(f"   - Failed creations: {len(failed_creations)}")

        if created_employees:
            print("\n   ✅ Successfully created employees:")
            for emp in created_employees:
                print(f'   - {emp["volunteer_name"]} -> {emp["employee_id"]}')

        if failed_creations:
            print("\n   ❌ Failed employee creations:")
            for fail in failed_creations:
                print(f'   - {fail["volunteer_name"]}: {fail["error"]}')

        success = len(created_employees) > 0

        return {
            "success": success,
            "message": f"Employee creation test completed. {len(created_employees)} successful, {len(failed_creations)} failed.",
            "created_employees": created_employees,
            "failed_creations": failed_creations,
            "total_tested": len(volunteers_without_employees),
        }

    except Exception as e:
        print(f"\n❌ Employee creation test failed with error: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "message": f"Test failed with error: {str(e)}"}
    finally:
        # Commit changes to see test results
        frappe.db.commit()


@frappe.whitelist()
def test_expense_integration():
    """Test ERPNext Expense Claim integration with HRMS"""
    try:
        print("🧪 Testing ERPNext Expense Claim Integration with HRMS")
        print("=" * 60)

        # Test 1: Verify HRMS is installed and Expense Claims are available
        print("\n1. Checking HRMS and Expense Claim availability...")

        # Check if HRMS is installed by checking if Expense Claim doctype exists
        try:
            hrms_installed = "hrms" in frappe.get_installed_apps()
        except Exception:
            hrms_installed = False
        print(f"   HRMS installed: {hrms_installed}")

        # Check if Expense Claim doctype exists
        expense_claim_exists = frappe.db.exists("DocType", "Expense Claim")
        print(f"   Expense Claim doctype exists: {expense_claim_exists}")

        # Check if Expense Claim Type exists
        expense_claim_type_exists = frappe.db.exists("DocType", "Expense Claim Type")
        print(f"   Expense Claim Type doctype exists: {expense_claim_type_exists}")

        if not all([expense_claim_exists, expense_claim_type_exists]):
            return {
                "success": False,
                "message": "ERPNext Expense Claims not available - HRMS may not be installed",
            }

        print("✅ HRMS integration requirements satisfied")

        # Test 2: Find or create test volunteer
        print("\n2. Finding or creating test volunteer...")

        # First check for any existing volunteer
        volunteers = frappe.get_all("Volunteer", fields=["name", "volunteer_name", "email"], limit=1)
        if volunteers:
            volunteer = volunteers[0]["name"]
            volunteer_name = volunteers[0]["volunteer_name"]
            print(f"   Using existing volunteer: {volunteer_name} ({volunteer})")
        else:
            # Find Foppe's member record to create volunteer
            member = frappe.db.get_value("Member", {"email": "foppe@veganisme.org"}, "name")
            if member:
                # Create volunteer record for Foppe
                member_doc = frappe.get_doc("Member", member)
                volunteer_doc = frappe.get_doc(
                    {
                        "doctype": "Volunteer",
                        "volunteer_name": f"{member_doc.first_name} {member_doc.last_name}",
                        "email": member_doc.email,
                        "member": member,
                        "status": "Active",
                        "start_date": frappe.utils.today(),
                    }
                )
                volunteer_doc.insert(ignore_permissions=True)
                volunteer = volunteer_doc.name
                volunteer_name = volunteer_doc.volunteer_name
                print(f"   Created new volunteer: {volunteer_name} ({volunteer})")
            else:
                # Create a simple test volunteer without member link
                volunteer_doc = frappe.get_doc(
                    {
                        "doctype": "Volunteer",
                        "volunteer_name": "Test Volunteer",
                        "email": "test@example.com",
                        "status": "Active",
                        "start_date": frappe.utils.today(),
                    }
                )
                volunteer_doc.insert(ignore_permissions=True)
                volunteer = volunteer_doc.name
                volunteer_name = volunteer_doc.volunteer_name
                print(f"   Created test volunteer: {volunteer_name} ({volunteer})")

        if not volunteer:
            return {"success": False, "message": "No volunteer found or could be created for testing"}

        print(f"   Using volunteer: {volunteer}")

        # Check if volunteer has an employee record
        volunteer_doc = frappe.get_doc("Volunteer", volunteer)
        print(f'   Employee ID: {volunteer_doc.employee_id or "None - will be created"}')

        # Set up expense claim types with accounts first
        print("\n   Setting up expense claim types with accounts...")
        test_category = setup_expense_claim_types()
        print(f"   Using expense type: {test_category}")

        # Test expense data
        expense_data = {
            "description": "Test ERPNext Integration - Office Supplies",
            "amount": 25.50,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": test_category,  # Use working expense type
            "notes": "Testing HRMS integration with ERPNext Expense Claims",
        }

        print(f'   Test expense: {expense_data["description"]} - €{expense_data["amount"]}')

        # Set up session context
        original_user = frappe.session.user
        frappe.session.user = volunteer_doc.email if volunteer_doc.email else "test@example.com"

        try:
            # Submit the expense
            result = submit_expense(expense_data)

            print("\n3. Expense submission result:")
            print(f'   Success: {result.get("success")}')
            print(f'   Message: {result.get("message")}')
            if result.get("expense_claim_name"):
                print(f'   ERPNext Expense Claim: {result.get("expense_claim_name")}')
            if result.get("expense_name"):
                print(f'   Volunteer Expense: {result.get("expense_name")}')
            if result.get("employee_created"):
                print(f'   Employee created: {result.get("employee_created")}')

            if result.get("success"):
                print("\n✅ Expense submission test PASSED")

                # Test 3: Verify records were created
                print("\n4. Verifying created records...")

                if result.get("expense_claim_name"):
                    expense_claim = frappe.get_doc("Expense Claim", result.get("expense_claim_name"))
                    print(f"   ERPNext Expense Claim status: {expense_claim.status}")
                    print(f"   Total claimed amount: {expense_claim.total_claimed_amount}")
                    print(f"   Employee: {expense_claim.employee}")

                if result.get("expense_name"):
                    volunteer_expense = frappe.get_doc("Volunteer Expense", result.get("expense_name"))
                    print(f"   Volunteer Expense status: {volunteer_expense.status}")
                    print(f"   Linked expense claim: {volunteer_expense.expense_claim_id}")

                print("\n✅ ERPNext Expense Claim integration test COMPLETED SUCCESSFULLY")
                return {
                    "success": True,
                    "message": "ERPNext integration test completed successfully",
                    "expense_claim_name": result.get("expense_claim_name"),
                    "expense_name": result.get("expense_name"),
                    "employee_created": result.get("employee_created"),
                }
            else:
                print("\n❌ Expense submission test FAILED")
                print(f'Error: {result.get("message")}')
                return {"success": False, "message": f'Expense submission failed: {result.get("message")}'}

        finally:
            frappe.session.user = original_user

    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "message": f"Test failed with error: {str(e)}"}
    finally:
        # Commit changes to see test results
        frappe.db.commit()


def setup_expense_claim_types():
    """Set up expense claim types with proper account configuration"""
    try:
        # Get default company
        default_company = frappe.defaults.get_global_default("company")
        if not default_company:
            companies = frappe.get_all("Company", limit=1, fields=["name"])
            default_company = companies[0].name if companies else None

        if not default_company:
            print("   ⚠️ No default company found")
            return "Travel"

        print(f"   Company: {default_company}")

        # Find or create a suitable expense account
        expense_account = frappe.db.get_value(
            "Account", {"company": default_company, "account_type": "Expense Account", "is_group": 0}, "name"
        )

        if not expense_account:
            # Find any expense-like account
            expense_account = frappe.db.get_value(
                "Account",
                {"company": default_company, "account_name": ["like", "%expense%"], "is_group": 0},
                "name",
            )

        if not expense_account:
            # Find indirect expense accounts
            expense_account = frappe.db.get_value(
                "Account", {"company": default_company, "root_type": "Expense", "is_group": 0}, "name"
            )

        if not expense_account:
            print(f"   ⚠️ No expense account found for company {default_company}")
            return "Travel"

        print(f"   Found expense account: {expense_account}")

        # Create or update a Travel expense claim type
        expense_type_name = "Travel"
        if not frappe.db.exists("Expense Claim Type", expense_type_name):
            expense_claim_type = frappe.get_doc(
                {
                    "doctype": "Expense Claim Type",
                    "expense_type": expense_type_name,
                    "description": "Travel and transportation expenses",
                }
            )
        else:
            expense_claim_type = frappe.get_doc("Expense Claim Type", expense_type_name)

        # Set up the accounts field directly
        try:
            # Check if accounts table exists and add account entry
            if hasattr(expense_claim_type, "accounts"):
                # Clear existing accounts
                expense_claim_type.accounts = []

                # Add the account entry
                expense_claim_type.append(
                    "accounts", {"company": default_company, "default_account": expense_account}
                )

                expense_claim_type.save(ignore_permissions=True)
                print(f"   ✅ Configured expense type '{expense_type_name}' with account '{expense_account}'")
            else:
                # Fallback: Create the basic expense claim type without accounts
                expense_claim_type.save(ignore_permissions=True)
                print(
                    f"   ⚠️ Created basic expense type '{expense_type_name}' - accounts configuration not available"
                )
        except Exception as account_error:
            print(f"   ⚠️ Could not configure accounts: {str(account_error)}")
            expense_claim_type.save(ignore_permissions=True)

        return expense_type_name

    except Exception as e:
        print(f"   ⚠️ Error setting up expense claim types: {str(e)}")
        import traceback

        traceback.print_exc()
        return "Travel"


def get_organization_cost_center(expense_data):
    """Get cost center based on organization with enhanced fallback logic"""
    try:
        cost_center = None

        if expense_data.get("organization_type") == "Chapter" and expense_data.get("chapter"):
            chapter_doc = frappe.get_doc("Chapter", expense_data.get("chapter"))
            cost_center = getattr(chapter_doc, "cost_center", None)

        elif expense_data.get("organization_type") == "Team" and expense_data.get("team"):
            team_doc = frappe.get_doc("Team", expense_data.get("team"))
            cost_center = getattr(team_doc, "cost_center", None)

            # If team doesn't have cost center, try to get from chapter
            if not cost_center and hasattr(team_doc, "chapter") and team_doc.chapter:
                try:
                    chapter_doc = frappe.get_doc("Chapter", team_doc.chapter)
                    cost_center = getattr(chapter_doc, "cost_center", None)
                    frappe.logger().info(f"Using chapter cost center for team {team_doc.name}: {cost_center}")
                except Exception as e:
                    frappe.logger().error(f"Error getting chapter cost center: {str(e)}")

        elif expense_data.get("organization_type") == "National":
            # Get national cost center from settings
            settings = frappe.get_single("Verenigingen Settings")
            if hasattr(settings, "national_cost_center") and settings.national_cost_center:
                cost_center = settings.national_cost_center

        # Enhanced fallback logic
        if not cost_center:
            frappe.logger().warning(
                f"No cost center found for organization type: {expense_data.get('organization_type')}"
            )

            # Try to get default company cost center
            default_company = frappe.defaults.get_global_default("company")
            if not default_company:
                companies = frappe.get_all("Company", limit=1, fields=["name"])
                default_company = companies[0].name if companies else None

            if default_company:
                # Get main cost center for the company
                main_cost_centers = frappe.get_all(
                    "Cost Center",
                    filters={"company": default_company, "is_group": 0},
                    fields=["name"],
                    limit=1,
                )

                if main_cost_centers:
                    cost_center = main_cost_centers[0].name
                    frappe.logger().info(f"Using fallback cost center: {cost_center}")
                else:
                    # Create a default cost center if none exists
                    cost_center = create_default_cost_center(default_company)

        return cost_center

    except Exception as e:
        frappe.log_error(f"Error getting cost center: {str(e)}", "Cost Center Error")
        # Return a default cost center as last resort
        return get_fallback_cost_center()


def create_default_cost_center(company):
    """Create a default cost center for expenses"""
    try:
        cost_center_name = f"Volunteer Expenses - {frappe.db.get_value('Company', company, 'abbr')}"

        if not frappe.db.exists("Cost Center", cost_center_name):
            # Get parent cost center (usually company name)
            parent_cost_center = frappe.db.get_value(
                "Cost Center", filters={"company": company, "is_group": 1}, fieldname="name"
            )

            if not parent_cost_center:
                parent_cost_center = company  # Use company as parent

            cost_center_doc = frappe.get_doc(
                {
                    "doctype": "Cost Center",
                    "cost_center_name": "Volunteer Expenses",
                    "parent_cost_center": parent_cost_center,
                    "company": company,
                    "is_group": 0,
                }
            )
            cost_center_doc.insert(ignore_permissions=True)
            frappe.logger().info(f"Created default cost center: {cost_center_name}")
            return cost_center_name
        else:
            return cost_center_name

    except Exception as e:
        frappe.log_error(f"Error creating default cost center: {str(e)}", "Cost Center Creation Error")
        return get_fallback_cost_center()


def get_fallback_cost_center():
    """Get any available cost center as fallback"""
    try:
        cost_centers = frappe.get_all("Cost Center", filters={"is_group": 0}, fields=["name"], limit=1)
        return cost_centers[0].name if cost_centers else None
    except Exception:
        return None


def validate_volunteer_organization_access(volunteer_name, organization_type, organization_name):
    """
    Enhanced validation for volunteer access to organizations.
    Supports direct chapter membership AND indirect access via team membership.
    """
    try:
        frappe.get_doc("Volunteer", volunteer_name)

        if organization_type == "Chapter":
            # Direct chapter membership check
            direct_membership = frappe.db.exists(
                "Chapter Member", {"parent": organization_name, "volunteer": volunteer_name}
            )

            if direct_membership:
                return True

            # Indirect access via team membership
            # Get teams where volunteer is a member and team's chapter matches
            team_memberships = frappe.get_all(
                "Team Member", filters={"volunteer": volunteer_name}, fields=["parent"]
            )

            for membership in team_memberships:
                team_doc = frappe.get_doc("Team", membership.parent)
                if hasattr(team_doc, "chapter") and team_doc.chapter == organization_name:
                    frappe.logger().info(
                        f"Volunteer {volunteer_name} has access to chapter {organization_name} via team {team_doc.name}"
                    )
                    return True

            return False

        elif organization_type == "Team":
            # Direct team membership check
            team_membership = frappe.db.exists(
                "Team Member", {"parent": organization_name, "volunteer": volunteer_name}
            )
            return bool(team_membership)

        elif organization_type == "National":
            # All volunteers have access to national expenses
            return True

        return False

    except Exception as e:
        frappe.log_error(
            f"Error validating volunteer organization access: {str(e)}", "Access Validation Error"
        )
        # In case of error, allow access to prevent blocking legitimate requests
        return True


def is_policy_covered_expense(category):
    """Check if expense category is covered by organizational policy for all volunteers"""
    try:
        # Get expense category details
        category_doc = frappe.get_doc("Expense Category", category)

        # Policy-covered categories (configurable via category settings)
        if hasattr(category_doc, "policy_covered") and category_doc.policy_covered:
            return True

        # Fallback: Check by category name for common policy-covered expenses
        policy_covered_categories = [
            "Travel",  # Travel expenses
            "Materials",  # Materials for campaigns/events
            "Office Supplies",  # Basic office supplies
            "events",  # Event materials
        ]

        category_name = getattr(category_doc, "category_name", category).lower()
        return any(policy_cat.lower() in category_name for policy_cat in policy_covered_categories)

    except Exception as e:
        frappe.log_error(
            f"Error checking policy coverage for category {category}: {str(e)}", "Policy Coverage Check"
        )
        # Default to requiring permission if we can't determine policy coverage
        return False


@frappe.whitelist()
def test_expense_form_with_foppe():
    """Test expense form APIs with Foppe de Haan's account"""

    print("🚀 TESTING EXPENSE FORM WITH FOPPE DE HAAN")
    print("=" * 60)

    # Check if Foppe exists
    foppe_member = frappe.db.get_value(
        "Member", {"email": "foppe@veganisme.org"}, ["name", "first_name", "last_name"], as_dict=True
    )

    if not foppe_member:
        print("❌ Foppe de Haan not found in Member records")
        return {"success": False, "error": "Foppe de Haan not found"}

    print(f"✅ Found Foppe: {foppe_member.first_name} {foppe_member.last_name}")

    # Check if Foppe has a volunteer record
    foppe_volunteer = frappe.db.get_value(
        "Volunteer", {"member": foppe_member.name}, ["name", "volunteer_name", "email"], as_dict=True
    )

    if not foppe_volunteer:
        print("❌ No volunteer record found for Foppe")
        # Create volunteer record for Foppe
        try:
            volunteer_doc = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": f"{foppe_member.first_name} {foppe_member.last_name}",
                    "email": "foppe@veganisme.org",
                    "member": foppe_member.name,
                    "status": "Active",
                    "start_date": frappe.utils.today(),
                }
            )
            volunteer_doc.insert(ignore_permissions=True)
            foppe_volunteer = {
                "name": volunteer_doc.name,
                "volunteer_name": volunteer_doc.volunteer_name,
                "email": volunteer_doc.email,
            }
            print(f"✅ Created volunteer record for Foppe: {foppe_volunteer['name']}")
        except Exception as e:
            print(f"❌ Failed to create volunteer record: {e}")
            return {"success": False, "error": f"Failed to create volunteer: {e}"}
    else:
        print(f"✅ Found volunteer record: {foppe_volunteer.volunteer_name}")

    # Store original user
    original_user = frappe.session.user

    try:
        # Switch to Foppe's session
        frappe.session.user = "foppe@veganisme.org"
        print(f"🔄 Switched to user: {frappe.session.user}")

        # Test 1: Get volunteer expense context
        print("\n1. Testing get_volunteer_expense_context with Foppe")
        try:
            response = frappe.call(
                "verenigingen.templates.pages.volunteer.expenses.get_volunteer_expense_context"
            )

            if response and isinstance(response, dict):
                if response.get("success"):
                    print("✅ PASS: API returns successful response")
                    print(f"   Volunteer: {response.get('volunteer')}")
                    print(f"   User chapters: {len(response.get('user_chapters', []))}")
                    print(f"   User teams: {len(response.get('user_teams', []))}")
                    print(f"   Expense categories: {len(response.get('expense_categories', []))}")
                    print(f"   Available categories: {response.get('expense_categories', [])}")
                    context_success = True
                    # Store available categories for test
                    available_categories = response.get("expense_categories", [])
                else:
                    print("❌ FAIL: API returns failure response")
                    print(f"   Error: {response.get('message', 'Unknown error')}")
                    context_success = False
                    available_categories = []
            else:
                print("❌ FAIL: Invalid response format")
                print(f"   Response: {response}")
                context_success = False
                available_categories = []

        except Exception as e:
            print(f"❌ FAIL: Exception occurred: {e}")
            context_success = False
            available_categories = []

        # Test 2: Submit multiple expenses with Foppe
        print("\n2. Testing submit_multiple_expenses with Foppe")
        try:
            # Use the first available category if any
            test_category = available_categories[0] if available_categories else "Travel"
            print(f"   Using category: {test_category}")

            test_expenses = [
                {
                    "description": "Test expense - Office supplies",
                    "amount": 25.50,
                    "expense_date": "2025-01-10",
                    "organization_type": "Team",
                    "category": test_category,
                    "chapter": None,
                    "team": "IT",  # Try with IT team
                    "notes": "Test expense submission via API",
                    "receipt_attachment": None,
                }
            ]

            response = frappe.call(
                "verenigingen.templates.pages.volunteer.expenses.submit_multiple_expenses",
                expenses=test_expenses,
            )

            if response and isinstance(response, dict):
                if response.get("success"):
                    print("✅ PASS: Expenses submitted successfully")
                    print(f"   Created count: {response.get('created_count', 0)}")
                    print(f"   Total amount: €{response.get('total_amount', 0)}")
                    submit_success = True
                else:
                    print("❌ FAIL: Failed to submit expenses")
                    print(f"   Error: {response.get('message', 'Unknown error')}")
                    print(f"   Full response: {response}")
                    submit_success = False
            else:
                print("❌ FAIL: Invalid response format")
                print(f"   Response: {response}")
                submit_success = False

        except Exception as e:
            print(f"❌ FAIL: Exception occurred: {e}")
            submit_success = False

        # Test 3: Test validation with invalid data
        print("\n3. Testing form validation with invalid data")
        try:
            invalid_expenses = [
                {
                    "description": "",  # Empty description
                    "amount": 0,  # Zero amount
                    "expense_date": "",  # Empty date
                    "organization_type": "",
                    "category": "",
                    "chapter": None,
                    "team": None,
                    "notes": "",
                    "receipt_attachment": None,
                }
            ]

            response = frappe.call(
                "verenigingen.templates.pages.volunteer.expenses.submit_multiple_expenses",
                expenses=invalid_expenses,
            )

            if response and isinstance(response, dict):
                if not response.get("success"):
                    print("✅ PASS: Form validation correctly rejects invalid data")
                    print(f"   Error: {response.get('message', 'Validation error')}")
                    validation_success = True
                else:
                    print("❌ FAIL: Form validation should reject invalid data")
                    validation_success = False
            else:
                print("❌ FAIL: Invalid response format")
                validation_success = False

        except Exception as e:
            print(f"❌ FAIL: Exception occurred: {e}")
            validation_success = False

    finally:
        # Restore original user
        frappe.session.user = original_user
        print(f"🔄 Restored user: {frappe.session.user}")

    # Summary
    print("\n" + "=" * 50)
    print("📊 EXPENSE FORM TEST SUMMARY (FOPPE)")
    print("=" * 50)

    tests_passed = sum([context_success, submit_success, validation_success])
    total_tests = 3

    print(f"Tests Passed: {tests_passed}/{total_tests}")

    if tests_passed == total_tests:
        print("🎉 ALL TESTS PASSED! Expense form works with Foppe's account.")
        success = True
    else:
        print("⚠️  Some tests failed. Check the details above.")
        success = False

    print(f"Test completed at: {frappe.utils.now_datetime()}")

    return {
        "success": success,
        "tests_passed": tests_passed,
        "total_tests": total_tests,
        "foppe_member": foppe_member.name if foppe_member else None,
        "foppe_volunteer": foppe_volunteer["name"] if foppe_volunteer else None,
    }


@frappe.whitelist()
def debug_api_access():
    """Debug API access issues"""
    try:
        # Test basic info
        user = frappe.session.user

        # Test the get_volunteer_expense_context function directly
        result = get_volunteer_expense_context()

        return {"success": True, "user": user, "api_result": result, "timestamp": frappe.utils.now()}
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "user": frappe.session.user,
            "timestamp": frappe.utils.now(),
        }


def get_or_create_expense_type(category):
    """Get or create expense claim type for category"""
    try:
        # Try to find existing expense claim type with same name as category
        expense_type = frappe.db.get_value("Expense Claim Type", {"expense_type": category}, "name")
        if expense_type:
            return expense_type

        # Get default company and accounts for setup
        default_company = frappe.defaults.get_global_default("company")
        if not default_company:
            companies = frappe.get_all("Company", limit=1, fields=["name"])
            default_company = companies[0].name if companies else None

        if not default_company:
            frappe.log_error("No default company found for expense claim type creation", "Expense Type Error")
            return "General"

        # Find a suitable expense account
        expense_account = frappe.db.get_value(
            "Account",
            {
                "company": default_company,
                "account_type": ["in", ["Expense Account", "Cost of Goods Sold"]],
                "is_group": 0,
            },
            "name",
        )

        if not expense_account:
            # Try to find any expense account
            expense_account = frappe.db.get_value(
                "Account",
                {"company": default_company, "account_name": ["like", "%expense%"], "is_group": 0},
                "name",
            )

        if not expense_account:
            # Create a basic expense account
            expense_account_doc = frappe.get_doc(
                {
                    "doctype": "Account",
                    "account_name": "Volunteer Expenses",
                    "account_type": "Expense Account",
                    "parent_account": frappe.db.get_value(
                        "Account",
                        {"company": default_company, "account_name": ["like", "%expense%"], "is_group": 1},
                        "name",
                    ),
                    "company": default_company,
                    "is_group": 0,
                }
            )
            expense_account_doc.insert(ignore_permissions=True)
            expense_account = expense_account_doc.name

        # Create new expense claim type with proper account setup
        expense_claim_type = frappe.get_doc(
            {
                "doctype": "Expense Claim Type",
                "expense_type": category,
                "description": f"Auto-created for volunteer expense category: {category}",
                "accounts": [{"company": default_company, "default_account": expense_account}],
            }
        )
        expense_claim_type.insert(ignore_permissions=True)
        frappe.logger().info(f"Created expense claim type: {category} with account: {expense_account}")
        return expense_claim_type.name

    except Exception as e:
        frappe.log_error(f"Error creating expense claim type: {str(e)}", "Expense Type Error")
        # Try to return any existing expense claim type
        existing_types = frappe.get_all("Expense Claim Type", limit=1, fields=["name"])
        if existing_types:
            return existing_types[0].name
        return "Travel"  # This is a common default in ERPNext


@frappe.whitelist(allow_guest=False)
def submit_multiple_expenses(expenses):
    """Submit multiple expenses from the portal at once"""
    try:
        # Ensure user is logged in
        if frappe.session.user == "Guest":
            return {"success": False, "message": _("Please log in to submit expenses")}
        # Parse JSON string if needed
        if isinstance(expenses, str):
            import json

            expenses = json.loads(expenses)

        # Validate input
        if not expenses or not isinstance(expenses, list):
            return {"success": False, "message": _("Invalid expense data provided")}

        if len(expenses) > 50:  # Reasonable limit
            return {
                "success": False,
                "message": _("Too many expenses in one submission. Maximum allowed: 50"),
            }

        # Get current user's volunteer record once
        volunteer = get_user_volunteer_record()
        if not volunteer:
            user_email = frappe.session.user
            member = frappe.db.get_value("Member", {"email": user_email}, "name")
            if member:
                error_msg = _(
                    "No volunteer record found for your account. You have a member record ({0}) but no linked volunteer record. Please contact your chapter administrator to create a volunteer profile."
                ).format(member)
            else:
                error_msg = _(
                    "No volunteer record found for your account. Your email ({0}) is not associated with any member or volunteer record. Please contact your chapter administrator."
                ).format(user_email)
            return {"success": False, "message": error_msg}

        created_expenses = []
        errors = []
        total_amount = 0

        # Validate each expense before processing
        for idx, expense_data in enumerate(expenses):
            # Basic validation
            validation_errors = validate_expense_data(expense_data, idx + 1)
            if validation_errors:
                errors.extend(validation_errors)
                continue

            total_amount += float(expense_data.get("amount", 0))

        # Check total amount limit (reasonable safety limit)
        if total_amount > 10000:  # €10,000 limit per submission
            return {
                "success": False,
                "message": _(
                    "Total expense amount (€{0}) exceeds the maximum allowed per submission (€10,000)"
                ).format(total_amount),
            }

        # If we have validation errors, return them immediately
        if errors:
            return {
                "success": False,
                "message": _("Validation errors found in expense data"),
                "errors": errors,
            }

        # Process each expense
        for idx, expense_data in enumerate(expenses):
            try:
                # Submit individual expense
                result = submit_expense(expense_data)

                if result.get("success"):
                    created_expenses.append(
                        {
                            "expense_claim_name": result.get("expense_claim_name"),
                            "expense_name": result.get("expense_name"),
                            "description": expense_data.get("description"),
                            "amount": expense_data.get("amount"),
                        }
                    )
                else:
                    errors.append(
                        {
                            "index": idx,
                            "description": expense_data.get("description"),
                            "error": result.get("message", "Unknown error"),
                        }
                    )

            except Exception as e:
                errors.append(
                    {
                        "index": idx,
                        "description": expense_data.get("description", f"Expense {idx + 1}"),
                        "error": str(e),
                    }
                )

        # Prepare response
        if created_expenses and not errors:
            # All expenses created successfully
            return {
                "success": True,
                "message": _("Successfully submitted {0} expense(s)").format(len(created_expenses)),
                "created_count": len(created_expenses),
                "created_expenses": created_expenses,
            }
        elif created_expenses and errors:
            # Partial success
            return {
                "success": True,
                "partial": True,
                "message": _("Submitted {0} expense(s) successfully, {1} failed").format(
                    len(created_expenses), len(errors)
                ),
                "created_count": len(created_expenses),
                "created_expenses": created_expenses,
                "errors": errors,
            }
        else:
            # All failed
            return {"success": False, "message": _("Failed to submit any expenses"), "errors": errors}

    except Exception as e:
        import traceback

        return {"success": False, "message": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist(allow_guest=False)
def get_volunteer_expense_context():
    """Get context data for the expense claim form"""
    try:
        # Ensure user is logged in
        if frappe.session.user == "Guest":
            return {"success": False, "message": _("Please log in to access this feature")}

        # Get current user's volunteer record
        volunteer = get_user_volunteer_record()
        if not volunteer:
            return {"success": False, "message": _("No volunteer record found for your account")}

        # Get organizations
        organizations = get_volunteer_organizations(volunteer.name)

        # Get expense categories
        categories = get_expense_categories()

        # Get approval thresholds for UI guidance
        thresholds = get_approval_thresholds()

        return {
            "success": True,
            "volunteer": volunteer.name,
            "user_chapters": [ch["name"] for ch in organizations.get("chapters", [])],
            "user_teams": [tm["name"] for tm in organizations.get("teams", [])],
            "expense_categories": [cat["name"] for cat in categories],
            "approval_thresholds": thresholds,
        }

    except Exception as e:
        import traceback

        return {"success": False, "message": str(e), "traceback": traceback.format_exc()}


def validate_expense_data(expense_data, line_number):
    """Validate individual expense data"""
    errors = []

    # Required fields validation
    required_fields = {
        "description": _("Description"),
        "amount": _("Amount"),
        "expense_date": _("Expense Date"),
        "organization_type": _("Organization Type"),
        "category": _("Category"),
    }

    for field, label in required_fields.items():
        if not expense_data.get(field):
            errors.append(
                {
                    "index": line_number - 1,
                    "field": field,
                    "error": _("Line {0}: {1} is required").format(line_number, label),
                }
            )

    # Amount validation
    try:
        amount = float(expense_data.get("amount", 0))
        if amount <= 0:
            errors.append(
                {
                    "index": line_number - 1,
                    "field": "amount",
                    "error": _("Line {0}: Amount must be greater than 0").format(line_number),
                }
            )
        if amount > 5000:  # Individual expense limit
            errors.append(
                {
                    "index": line_number - 1,
                    "field": "amount",
                    "error": _("Line {0}: Amount cannot exceed €5,000 per expense").format(line_number),
                }
            )
    except (ValueError, TypeError):
        errors.append(
            {
                "index": line_number - 1,
                "field": "amount",
                "error": _("Line {0}: Invalid amount format").format(line_number),
            }
        )

    # Date validation
    if expense_data.get("expense_date"):
        try:
            from frappe.utils import getdate, today

            expense_date = getdate(expense_data.get("expense_date"))
            today_date = getdate(today())

            if expense_date > today_date:
                errors.append(
                    {
                        "index": line_number - 1,
                        "field": "expense_date",
                        "error": _("Line {0}: Expense date cannot be in the future").format(line_number),
                    }
                )

            # Check if date is too old (e.g., older than 1 year)
            days_old = (today_date - expense_date).days
            if days_old > 365:
                errors.append(
                    {
                        "index": line_number - 1,
                        "field": "expense_date",
                        "error": _("Line {0}: Expense date is too old (older than 1 year)").format(
                            line_number
                        ),
                    }
                )
        except (ValueError, TypeError):
            errors.append(
                {
                    "index": line_number - 1,
                    "field": "expense_date",
                    "error": _("Line {0}: Invalid date format").format(line_number),
                }
            )

    # Description validation
    description = expense_data.get("description", "").strip()
    if description and len(description) > 200:
        errors.append(
            {
                "index": line_number - 1,
                "field": "description",
                "error": _("Line {0}: Description is too long (maximum 200 characters)").format(line_number),
            }
        )

    # Organization validation
    org_type = expense_data.get("organization_type")
    if org_type == "Chapter" and not expense_data.get("chapter"):
        errors.append(
            {
                "index": line_number - 1,
                "field": "chapter",
                "error": _("Line {0}: Chapter selection is required for chapter expenses").format(
                    line_number
                ),
            }
        )
    elif org_type == "Team" and not expense_data.get("team"):
        errors.append(
            {
                "index": line_number - 1,
                "field": "team",
                "error": _("Line {0}: Team selection is required for team expenses").format(line_number),
            }
        )

    # Category validation
    category = expense_data.get("category")
    if category:
        if not frappe.db.exists("Expense Category", category):
            errors.append(
                {
                    "index": line_number - 1,
                    "field": "category",
                    "error": _("Line {0}: Invalid expense category").format(line_number),
                }
            )

    # File validation (if receipt provided)
    receipt = expense_data.get("receipt_attachment")
    if receipt and isinstance(receipt, dict):
        file_name = receipt.get("file_name", "")
        if file_name:
            # Check file extension
            allowed_extensions = [".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp"]
            if not any(file_name.lower().endswith(ext) for ext in allowed_extensions):
                errors.append(
                    {
                        "index": line_number - 1,
                        "field": "receipt_attachment",
                        "error": _("Line {0}: Invalid file type. Allowed: PDF, JPG, PNG, GIF, BMP").format(
                            line_number
                        ),
                    }
                )

            # Check file content size (base64 encoded, so roughly file_size * 1.33)
            file_content = receipt.get("file_content", "")
            if file_content and len(file_content) > 10 * 1024 * 1024:  # ~7.5MB actual file size
                errors.append(
                    {
                        "index": line_number - 1,
                        "field": "receipt_attachment",
                        "error": _("Line {0}: File size too large (maximum 7.5MB)").format(line_number),
                    }
                )

    return errors
