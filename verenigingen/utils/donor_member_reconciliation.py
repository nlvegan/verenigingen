# Donor-Member Reconciliation Utilities
#
# Provides robust mapping between Donor and Member records,
# handling duplicates, ambiguous matches, and missing links.

from typing import List, Optional, Tuple

import frappe

from verenigingen.utils.error_codes import log_operation_error


def get_donor_for_member(member_doc) -> Optional[str]:
    """
    Get canonical donor for a member with proper handling of duplicates.

    Priority:
    1. Explicit donor field on member (if set and valid)
    2. Single donor matching by email
    3. Most recent donor if multiple matches (with warning logged)
    4. None if no matches

    Args:
        member_doc: Member document object (must have email field)

    Returns:
        Donor name if found, None otherwise
    """
    # Check explicit link first (if the field exists)
    explicit_donor = getattr(member_doc, "donor", None)
    if explicit_donor:
        if frappe.db.exists("Donor", explicit_donor):
            return explicit_donor
        else:
            frappe.logger("verenigingen.donor_mapping").warning(
                f"Member {member_doc.name} has invalid donor link: {explicit_donor}"
            )

    # No email means no lookup possible
    if not member_doc.email:
        return None

    # Lookup by email with duplicate detection
    donors = frappe.get_all(
        "Donor",
        filters={"donor_email": member_doc.email},
        fields=["name", "creation"],
        order_by="creation desc",
    )

    if len(donors) == 0:
        return None
    elif len(donors) == 1:
        return donors[0].name
    else:
        # Multiple donors found - log warning and return most recent
        donor_names = [d.name for d in donors]
        frappe.logger("verenigingen.donor_mapping").warning(
            f"Multiple donors ({len(donors)}) found for member {member_doc.name} "
            f"with email {member_doc.email}. Using most recent: {donors[0].name}. "
            f"Consider reconciling: {donor_names}"
        )

        # Log to error log for admin review
        log_operation_error(
            "DONOR_001",
            f"member {member_doc.name}",
            additional_info={
                "email": member_doc.email,
                "matching_donors": donor_names,
                "selected_donor": donors[0].name,
            },
        )

        return donors[0].name


def get_all_donors_for_email(email: str) -> List[dict]:
    """
    Get all donors matching an email address.

    Args:
        email: Email address to search

    Returns:
        List of donor dicts with name, creation, and donation counts
    """
    if not email:
        return []

    donors = frappe.get_all(
        "Donor",
        filters={"donor_email": email},
        fields=["name", "creation", "donor_name"],
        order_by="creation desc",
    )

    # Enrich with donation counts
    for donor in donors:
        donor["donation_count"] = frappe.db.count("Donation", filters={"donor": donor["name"]})

    return donors


def get_volunteer_for_employee(employee_id: str, member_name: str = None) -> Optional[str]:
    """
    Get volunteer record for an employee with proper handling of duplicates.

    Priority:
    1. Volunteer linked to both employee AND the specified member
    2. Any volunteer linked to the employee
    3. None if no matches

    Args:
        employee_id: Employee ID to search
        member_name: Optional member name to prefer matching volunteer

    Returns:
        Volunteer name if found, None otherwise
    """
    if not employee_id:
        return None

    # Build filters
    base_filters = {"employee_id": employee_id}

    # First try to find volunteer linked to this member specifically
    if member_name:
        volunteer_with_member = frappe.db.get_value(
            "Volunteer",
            {"employee_id": employee_id, "member": member_name},
            "name",
        )
        if volunteer_with_member:
            return volunteer_with_member

    # Fallback: any volunteer with this employee_id
    volunteers = frappe.get_all(
        "Volunteer",
        filters=base_filters,
        fields=["name", "member", "creation"],
        order_by="creation desc",
    )

    if len(volunteers) == 0:
        return None
    elif len(volunteers) == 1:
        return volunteers[0].name
    else:
        # Multiple volunteers - log warning
        volunteer_names = [v.name for v in volunteers]
        frappe.logger("verenigingen.volunteer_mapping").warning(
            f"Multiple volunteers ({len(volunteers)}) found for employee {employee_id}. "
            f"Using most recent: {volunteers[0].name}. "
            f"Consider reconciling: {volunteer_names}"
        )

        log_operation_error(
            "VOL_003",
            f"employee {employee_id}",
            additional_info={
                "employee_id": employee_id,
                "member_filter": member_name,
                "matching_volunteers": volunteer_names,
                "selected_volunteer": volunteers[0].name,
            },
        )

        return volunteers[0].name


def check_donor_member_consistency(member_name: str) -> dict:
    """
    Check if donor-member mapping is consistent.

    Returns a report of any inconsistencies.

    Args:
        member_name: Member name to check

    Returns:
        Dict with:
        - consistent (bool): Whether mapping is consistent
        - issues (list): List of issues found
        - recommendations (list): Suggested fixes
    """
    result = {
        "consistent": True,
        "issues": [],
        "recommendations": [],
    }

    member = frappe.get_doc("Member", member_name)

    # Check if member has explicit donor link
    explicit_donor = getattr(member, "donor", None)

    # Find donors by email
    donors_by_email = get_all_donors_for_email(member.email)

    if not explicit_donor and not donors_by_email:
        # No donor anywhere - that's fine
        return result

    if explicit_donor:
        # Has explicit link - verify it's valid
        if not frappe.db.exists("Donor", explicit_donor):
            result["consistent"] = False
            result["issues"].append(f"Explicit donor link '{explicit_donor}' does not exist")
            result["recommendations"].append("Clear the invalid donor link")

        # Check if explicit donor email matches
        explicit_donor_email = frappe.db.get_value("Donor", explicit_donor, "donor_email")
        if explicit_donor_email and explicit_donor_email != member.email:
            result["consistent"] = False
            result["issues"].append(
                f"Explicit donor email '{explicit_donor_email}' doesn't match member email '{member.email}'"
            )
            result["recommendations"].append("Verify which email is correct")

    if len(donors_by_email) > 1:
        result["consistent"] = False
        result["issues"].append(
            f"Multiple donors ({len(donors_by_email)}) found for email {member.email}: "
            f"{[d['name'] for d in donors_by_email]}"
        )
        result["recommendations"].append("Consider merging duplicate donors or updating email addresses")

    if explicit_donor and donors_by_email:
        # Check if explicit donor is in the email matches
        email_donor_names = [d["name"] for d in donors_by_email]
        if explicit_donor not in email_donor_names:
            result["consistent"] = False
            result["issues"].append(
                f"Explicit donor '{explicit_donor}' not in donors matching member email: {email_donor_names}"
            )
            result["recommendations"].append("Update explicit donor link or verify email addresses")

    return result


def reconcile_donor_duplicates(email: str, primary_donor: str = None) -> dict:
    """
    Reconcile duplicate donors for an email address.

    Merges donation records from secondary donors into the primary donor.

    Args:
        email: Email address with duplicates
        primary_donor: Name of donor to keep (uses most recent if not specified)

    Returns:
        Dict with merge results
    """
    donors = get_all_donors_for_email(email)

    if len(donors) <= 1:
        return {"merged": 0, "message": "No duplicates to merge"}

    # Determine primary
    if not primary_donor:
        primary_donor = donors[0]["name"]  # Most recent

    if primary_donor not in [d["name"] for d in donors]:
        return {"error": f"Primary donor {primary_donor} not found for email {email}"}

    secondary_donors = [d["name"] for d in donors if d["name"] != primary_donor]

    # Merge donations from secondary to primary
    merged_count = 0
    for secondary in secondary_donors:
        donations = frappe.get_all(
            "Donation",
            filters={"donor": secondary},
            pluck="name",
        )

        for donation_name in donations:
            frappe.db.set_value("Donation", donation_name, "donor", primary_donor)
            merged_count += 1

    frappe.db.commit()

    return {
        "merged": merged_count,
        "primary_donor": primary_donor,
        "secondary_donors": secondary_donors,
        "message": f"Merged {merged_count} donations from {len(secondary_donors)} donors into {primary_donor}",
    }
