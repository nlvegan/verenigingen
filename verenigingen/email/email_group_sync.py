#!/usr/bin/env python3
"""
Email Group Synchronization
Phase 2 Implementation - Email Group Management

This module handles the creation and synchronization of Email Groups
for newsletter distribution to various member segments.
"""

from typing import Dict, List, Optional

import frappe
from frappe import _


def create_initial_email_groups():
    """
    Create basic email group structure for the organization
    This should be run during initial setup or migration
    """
    created_groups = []

    # Organization-wide groups
    org_groups = [
        ("verenigingen-all-members", "All Organization Members", "All members of the organization"),
        ("verenigingen-active", "Active Members", "Currently active members"),
        ("verenigingen-volunteers", "All Volunteers", "All registered volunteers"),
        ("verenigingen-board", "All Board Members", "Board members across all chapters"),
        ("verenigingen-donors", "Donors", "All donors and supporters"),
    ]

    for group_name, title, description in org_groups:
        if not frappe.db.exists("Email Group", {"title": title}):
            try:
                email_group = frappe.get_doc(
                    {
                        "doctype": "Email Group",
                        "title": title,
                        "email_group": group_name,
                        "description": description,
                        "confirmation_email_template": None,  # No confirmation needed for internal groups
                        "welcome_email_template": None,
                    }
                )
                email_group.insert(ignore_permissions=True)
                created_groups.append(title)
                print(f"✅ Created email group: {title}")
            except Exception as e:
                print(f"❌ Error creating group {title}: {str(e)}")

    # Create chapter-specific groups
    chapters = frappe.get_all("Chapter", fields=["name"])
    for chapter in chapters:
        chapter_name = chapter.name  # Chapter uses 'name' field as the display name
        chapter_groups = [
            (
                f"chapter-{chapter.name.lower().replace(' ', '-')}-members",
                f"{chapter_name} - All Members",
                f"All members of {chapter_name}",
            ),
            (
                f"chapter-{chapter.name.lower().replace(' ', '-')}-board",
                f"{chapter_name} - Board",
                f"Board members of {chapter_name}",
            ),
            (
                f"chapter-{chapter.name.lower().replace(' ', '-')}-volunteers",
                f"{chapter_name} - Volunteers",
                f"Volunteers of {chapter_name}",
            ),
        ]

        for group_name, title, description in chapter_groups:
            if not frappe.db.exists("Email Group", {"title": title}):
                try:
                    email_group = frappe.get_doc(
                        {
                            "doctype": "Email Group",
                            "title": title,
                            "email_group": group_name,
                            "description": description,
                            "confirmation_email_template": None,
                            "welcome_email_template": None,
                        }
                    )
                    email_group.insert(ignore_permissions=True)
                    created_groups.append(title)
                    print(f"✅ Created email group: {title}")
                except Exception as e:
                    print(f"❌ Error creating group {title}: {str(e)}")

    frappe.db.commit()

    return {"success": True, "created_count": len(created_groups), "created_groups": created_groups}


@frappe.whitelist()
def sync_email_groups_manually():
    """
    Manual sync that can be triggered by admins
    Synchronizes member data with email groups
    """
    # Check permissions
    if not ("System Manager" in frappe.get_roles() or "Verenigingen Manager" in frappe.get_roles()):
        frappe.throw(_("You don't have permission to sync email groups"))

    sync_stats = {"added": 0, "removed": 0, "errors": []}

    # Sync all active members to the active members group
    try:
        active_group = frappe.get_doc("Email Group", {"title": "Active Members"})

        # Get current group members
        current_members = frappe.db.sql_list(
            """
            SELECT email FROM `tabEmail Group Member`
            WHERE email_group = %s
        """,
            active_group.name,
        )

        # Get active members from database
        active_members = frappe.db.sql_list(
            """
            SELECT DISTINCT email FROM `tabMember`
            WHERE status = 'Active'
                AND email IS NOT NULL
                AND email != ''
                AND COALESCE(opt_out_optional_emails, 0) = 0
        """
        )

        # Add new members
        for email in active_members:
            if email not in current_members:
                add_to_email_group(email, active_group.name)
                sync_stats["added"] += 1

        # Remove inactive members
        for email in current_members:
            if email not in active_members:
                remove_from_email_group(email, active_group.name)
                sync_stats["removed"] += 1

    except Exception as e:
        sync_stats["errors"].append(f"Active Members group: {str(e)}")

    # Sync chapter members
    chapters = frappe.get_all("Chapter", fields=["name"])
    for chapter in chapters:
        try:
            # Sync chapter members
            group_title = f"{chapter.name} - All Members"
            if frappe.db.exists("Email Group", {"title": group_title}):
                chapter_group = frappe.get_doc("Email Group", {"title": group_title})

                # Get current group members
                current_members = frappe.db.sql_list(
                    """
                    SELECT email FROM `tabEmail Group Member`
                    WHERE email_group = %s
                """,
                    chapter_group.name,
                )

                # Get chapter members
                chapter_members = frappe.db.sql_list(
                    """
                    SELECT DISTINCT m.email
                    FROM `tabChapter Member` cm
                    INNER JOIN `tabMember` m ON cm.member = m.name
                    WHERE cm.parent = %s
                        AND cm.enabled = 1
                        AND m.status = 'Active'
                        AND m.email IS NOT NULL
                        AND m.email != ''
                        AND COALESCE(m.opt_out_optional_emails, 0) = 0
                """,
                    chapter.name,
                )

                # Add new members
                for email in chapter_members:
                    if email not in current_members:
                        add_to_email_group(email, chapter_group.name)
                        sync_stats["added"] += 1

                # Remove inactive members
                for email in current_members:
                    if email not in chapter_members:
                        remove_from_email_group(email, chapter_group.name)
                        sync_stats["removed"] += 1

        except Exception as e:
            sync_stats["errors"].append(f"{chapter.name}: {str(e)}")

    # Sync volunteers
    try:
        volunteer_group = frappe.get_doc("Email Group", {"title": "All Volunteers"})

        # Get current group members
        current_members = frappe.db.sql_list(
            """
            SELECT email FROM `tabEmail Group Member`
            WHERE email_group = %s
        """,
            volunteer_group.name,
        )

        # Get all volunteers
        volunteers = frappe.db.sql_list(
            """
            SELECT DISTINCT m.email
            FROM `tabVolunteer` v
            INNER JOIN `tabMember` m ON v.member = m.name
            WHERE v.status = 'Active'
                AND m.email IS NOT NULL
                AND m.email != ''
                AND COALESCE(m.opt_out_optional_emails, 0) = 0
        """
        )

        # Add new volunteers
        for email in volunteers:
            if email not in current_members:
                add_to_email_group(email, volunteer_group.name)
                sync_stats["added"] += 1

        # Remove inactive volunteers
        for email in current_members:
            if email not in volunteers:
                remove_from_email_group(email, volunteer_group.name)
                sync_stats["removed"] += 1

    except Exception as e:
        sync_stats["errors"].append(f"Volunteers group: {str(e)}")

    frappe.db.commit()

    return {
        "success": len(sync_stats["errors"]) == 0,
        "added": sync_stats["added"],
        "removed": sync_stats["removed"],
        "errors": sync_stats["errors"],
        "message": f"Added {sync_stats['added']} members, removed {sync_stats['removed']} members",
    }


def add_to_email_group(email: str, email_group: str):
    """
    Add an email to an email group if not already present

    Args:
        email: Email address to add
        email_group: Name of the email group
    """
    if not frappe.db.exists("Email Group Member", {"email": email, "email_group": email_group}):
        try:
            member = frappe.get_doc(
                {
                    "doctype": "Email Group Member",
                    "email": email,
                    "email_group": email_group,
                    "unsubscribed": 0,
                }
            )
            member.insert(ignore_permissions=True)
        except Exception as e:
            # Log but don't fail the whole sync
            frappe.log_error(f"Error adding {email} to {email_group}: {str(e)}", "Email Group Sync")


def remove_from_email_group(email: str, email_group: str):
    """
    Remove an email from an email group

    Args:
        email: Email address to remove
        email_group: Name of the email group
    """
    try:
        member = frappe.db.get_value("Email Group Member", {"email": email, "email_group": email_group})
        if member:
            frappe.delete_doc("Email Group Member", member, ignore_permissions=True)
    except Exception as e:
        # Log but don't fail the whole sync
        frappe.log_error(f"Error removing {email} from {email_group}: {str(e)}", "Email Group Sync")


@frappe.whitelist()
def get_email_group_stats():
    """
    Get statistics about email groups

    Returns:
        Dict with group statistics
    """
    # Check permissions
    if not frappe.has_permission("Email Group", "read"):
        frappe.throw(_("You don't have permission to view email group statistics"))

    stats = []

    # Get all email groups
    groups = frappe.get_all("Email Group", fields=["name", "title", "description"])

    for group in groups:
        # Count members
        member_count = frappe.db.count("Email Group Member", {"email_group": group.name, "unsubscribed": 0})

        # Count unsubscribed
        unsubscribed_count = frappe.db.count(
            "Email Group Member", {"email_group": group.name, "unsubscribed": 1}
        )

        stats.append(
            {
                "name": group.name,
                "title": group.title,
                "description": group.description,
                "member_count": member_count,
                "unsubscribed_count": unsubscribed_count,
                "total_count": member_count + unsubscribed_count,
            }
        )

    return {"success": True, "groups": stats, "total_groups": len(stats)}


def sync_member_on_change(doc, method=None):
    """
    Sync a specific member's email group memberships when their data changes
    Called from Member DocType hooks

    Args:
        doc: The Member document object
        method: The hook method name (optional)
    """
    try:
        member = doc

        if not member.email:
            return {"success": True, "message": "No email address"}

        # Check if member should be in active group
        if member.status == "Active" and not member.get("opt_out_optional_emails"):
            # Add to active members group
            active_group = frappe.db.get_value("Email Group", {"title": "Active Members"}, "name")
            if active_group:
                add_to_email_group(member.email, active_group)
        else:
            # Remove from active members group
            active_group = frappe.db.get_value("Email Group", {"title": "Active Members"}, "name")
            if active_group:
                remove_from_email_group(member.email, active_group)

        # Sync chapter memberships
        chapter_memberships = frappe.get_all(
            "Chapter Member", filters={"member": member.name, "enabled": 1}, fields=["parent"]
        )

        for membership in chapter_memberships:
            chapter = frappe.get_doc("Chapter", membership.parent)
            group_title = f"{chapter.name} - All Members"

            if frappe.db.exists("Email Group", {"title": group_title}):
                chapter_group = frappe.db.get_value("Email Group", {"title": group_title}, "name")

                if member.status == "Active" and not member.get("opt_out_optional_emails"):
                    add_to_email_group(member.email, chapter_group)
                else:
                    remove_from_email_group(member.email, chapter_group)

        return {"success": True, "message": "Email groups updated"}

    except Exception as e:
        frappe.log_error(f"Error syncing member {member.name}: {str(e)}", "Email Group Sync")
        return {"success": False, "error": str(e)}


# Scheduled job for automatic sync
def scheduled_email_group_sync():
    """
    Scheduled job to sync email groups
    Add this to hooks.py scheduler_events
    """
    # Only run if feature is enabled
    if frappe.db.get_single_value("Verenigingen Settings", "enable_email_group_sync"):
        sync_email_groups_manually()
