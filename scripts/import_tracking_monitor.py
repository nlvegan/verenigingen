#!/usr/bin/env python3
"""
Import Tracking Monitor for Verenigingen Member Imports

Provides comprehensive monitoring and status tracking for CSV member imports.
Tracks import progress at multiple levels:
- Member-level: Individual member import status
- Request-level: Account creation request status
- Batch-level: Bulk operation batch progress

Usage:
    # From bench directory
    bench --site dev.veganisme.net execute verenigingen.scripts.import_tracking_monitor.print_import_summary

    bench --site dev.veganisme.net execute verenigingen.scripts.import_tracking_monitor.print_detailed_status --kwargs "{'import_start_time': '2025-10-24 10:00:00'}"

    bench --site dev.veganisme.net execute verenigingen.scripts.import_tracking_monitor.export_import_report --kwargs "{'import_start_time': '2025-10-24 10:00:00', 'output_file': '/tmp/import_report.json'}"

Author: Verenigingen Development Team
"""

import json
from datetime import datetime
from typing import Dict, List, Optional

import frappe
from frappe.utils import now_datetime


def get_import_summary(import_start_time: Optional[str] = None) -> Dict:
    """
    Get high-level summary of import status.

    Args:
        import_start_time: Optional filter for imports after this time (format: 'YYYY-MM-DD HH:MM:SS')

    Returns:
        Dict with summary statistics
    """
    # Default to last 24 hours if not specified
    if not import_start_time:
        import_start_time = frappe.utils.add_to_date(now_datetime(), hours=-24, as_datetime=False)

    # Member statistics
    total_members = frappe.db.count(
        "Member", filters={"creation": [">=", import_start_time]}
    )

    members_with_users = frappe.db.sql(
        """
        SELECT COUNT(DISTINCT m.name)
        FROM `tabMember` m
        INNER JOIN `tabUser` u ON m.email = u.name
        WHERE m.creation >= %(start_time)s
        """,
        {"start_time": import_start_time},
    )[0][0]

    # Account Creation Request statistics
    acr_stats = frappe.db.sql(
        """
        SELECT
            status,
            COUNT(*) as count,
            SUM(retry_count) as total_retries
        FROM `tabAccount Creation Request`
        WHERE creation >= %(start_time)s
        GROUP BY status
        """,
        {"start_time": import_start_time},
        as_dict=True,
    )

    # Bulk Operation Tracker statistics
    bulk_ops = frappe.db.sql(
        """
        SELECT
            name,
            operation_type,
            status,
            total_records,
            processed_records,
            successful_records,
            failed_records,
            processing_rate_per_minute,
            estimated_completion
        FROM `tabBulk Operation Tracker`
        WHERE creation >= %(start_time)s
        ORDER BY creation DESC
        """,
        {"start_time": import_start_time},
        as_dict=True,
    )

    return {
        "import_period": {
            "start_time": import_start_time,
            "current_time": now_datetime(),
        },
        "member_summary": {
            "total_members_imported": total_members,
            "members_with_user_accounts": members_with_users,
            "members_without_user_accounts": total_members - members_with_users,
            "account_creation_percentage": (
                (members_with_users / total_members * 100) if total_members > 0 else 0
            ),
        },
        "account_creation_requests": {
            stat["status"]: {
                "count": stat["count"],
                "total_retries": stat.get("total_retries") or 0,
            }
            for stat in acr_stats
        },
        "bulk_operations": bulk_ops,
    }


def get_members_without_accounts(import_start_time: Optional[str] = None) -> List[Dict]:
    """
    Get list of members who don't have user accounts yet.

    Args:
        import_start_time: Optional filter for imports after this time

    Returns:
        List of member records without accounts
    """
    if not import_start_time:
        import_start_time = frappe.utils.add_to_date(now_datetime(), hours=-24, as_datetime=False)

    members = frappe.db.sql(
        """
        SELECT
            m.name,
            m.full_name,
            m.email,
            m.status as member_status,
            m.creation
        FROM `tabMember` m
        LEFT JOIN `tabUser` u ON m.email = u.name
        WHERE m.creation >= %(start_time)s
        AND u.name IS NULL
        ORDER BY m.creation DESC
        """,
        {"start_time": import_start_time},
        as_dict=True,
    )

    return members


def get_failed_account_creation_requests(import_start_time: Optional[str] = None) -> List[Dict]:
    """
    Get detailed information about failed account creation requests.

    Args:
        import_start_time: Optional filter for imports after this time

    Returns:
        List of failed ACR records with details
    """
    if not import_start_time:
        import_start_time = frappe.utils.add_to_date(now_datetime(), hours=-24, as_datetime=False)

    failed_acrs = frappe.db.sql(
        """
        SELECT
            name,
            source_record,
            email,
            full_name,
            status,
            pipeline_stage,
            failure_reason,
            retry_count,
            creation,
            processing_started_at
        FROM `tabAccount Creation Request`
        WHERE creation >= %(start_time)s
        AND status = 'Failed'
        ORDER BY creation DESC
        """,
        {"start_time": import_start_time},
        as_dict=True,
    )

    return failed_acrs


def get_stuck_account_creation_requests(hours_threshold: int = 2) -> List[Dict]:
    """
    Get ACRs that are stuck in processing/queued state for too long.

    Args:
        hours_threshold: Number of hours before considering a request stuck

    Returns:
        List of potentially stuck ACR records
    """
    threshold_time = frappe.utils.add_to_date(now_datetime(), hours=-hours_threshold, as_datetime=False)

    stuck_acrs = frappe.db.sql(
        """
        SELECT
            name,
            source_record,
            email,
            full_name,
            status,
            pipeline_stage,
            creation,
            processing_started_at,
            TIMESTAMPDIFF(HOUR, processing_started_at, NOW()) as hours_processing
        FROM `tabAccount Creation Request`
        WHERE status IN ('Processing', 'Queued')
        AND creation < %(threshold)s
        ORDER BY creation ASC
        """,
        {"threshold": threshold_time},
        as_dict=True,
    )

    return stuck_acrs


def get_member_acr_mapping(member_name: str) -> Optional[Dict]:
    """
    Get Account Creation Request details for a specific member.

    Args:
        member_name: Member ID to look up

    Returns:
        Dict with member and ACR details, or None if not found
    """
    # Get member details
    member = frappe.db.get_value(
        "Member",
        member_name,
        ["name", "full_name", "email_address", "status", "creation"],
        as_dict=True,
    )

    if not member:
        return None

    # Get associated ACR
    acr = frappe.db.get_value(
        "Account Creation Request",
        {"source_record": member_name},
        [
            "name",
            "status",
            "pipeline_stage",
            "created_user",
            "created_employee",
            "failure_reason",
            "retry_count",
            "creation",
            "completed_at",
        ],
        as_dict=True,
    )

    # Check if user exists
    user_exists = frappe.db.exists("User", member.email) if member.email else False

    return {
        "member": member,
        "account_creation_request": acr,
        "user_exists": bool(user_exists),
    }


def print_import_summary(import_start_time: Optional[str] = None):
    """
    Print formatted import summary to console.

    Args:
        import_start_time: Optional filter for imports after this time
    """
    summary = get_import_summary(import_start_time)

    print("\n" + "=" * 80)
    print(" IMPORT STATUS SUMMARY")
    print("=" * 80)

    print(f"\nImport Period: {summary['import_period']['start_time']} to {summary['import_period']['current_time']}")

    print("\n--- Member Summary ---")
    ms = summary["member_summary"]
    print(f"  Total Members Imported: {ms['total_members_imported']}")
    print(f"  Members with User Accounts: {ms['members_with_user_accounts']}")
    print(f"  Members WITHOUT User Accounts: {ms['members_without_user_accounts']}")
    print(f"  Account Creation Success Rate: {ms['account_creation_percentage']:.1f}%")

    print("\n--- Account Creation Requests ---")
    acr_stats = summary["account_creation_requests"]
    for status, data in acr_stats.items():
        print(f"  {status}: {data['count']} requests (Total retries: {data['total_retries']})")

    if summary["bulk_operations"]:
        print("\n--- Bulk Operations ---")
        for op in summary["bulk_operations"]:
            progress_pct = (
                (op["processed_records"] / op["total_records"] * 100) if op["total_records"] > 0 else 0
            )
            print(f"\n  Operation: {op['name']}")
            print(f"    Type: {op['operation_type']}")
            print(f"    Status: {op['status']}")
            print(
                f"    Progress: {op['processed_records']}/{op['total_records']} ({progress_pct:.1f}%)"
            )
            print(f"    Successful: {op['successful_records']}")
            print(f"    Failed: {op['failed_records']}")
            if op.get("processing_rate_per_minute"):
                print(f"    Processing Rate: {op['processing_rate_per_minute']:.1f} records/min")
            if op.get("estimated_completion"):
                print(f"    Estimated Completion: {op['estimated_completion']}")

    print("\n" + "=" * 80 + "\n")


def print_detailed_status(import_start_time: Optional[str] = None):
    """
    Print detailed status including failed and stuck requests.

    Args:
        import_start_time: Optional filter for imports after this time
    """
    print_import_summary(import_start_time)

    # Members without accounts
    members_no_accounts = get_members_without_accounts(import_start_time)
    if members_no_accounts:
        print(f"\n--- Members Without User Accounts ({len(members_no_accounts)}) ---")
        for member in members_no_accounts[:10]:  # Show first 10
            print(f"  {member['name']}: {member['full_name']} ({member['email_address']})")
        if len(members_no_accounts) > 10:
            print(f"  ... and {len(members_no_accounts) - 10} more")

    # Failed ACRs
    failed_acrs = get_failed_account_creation_requests(import_start_time)
    if failed_acrs:
        print(f"\n--- Failed Account Creation Requests ({len(failed_acrs)}) ---")
        for acr in failed_acrs[:10]:  # Show first 10
            print(f"\n  {acr['name']} (Member: {acr['source_record']})")
            print(f"    Email: {acr['email']}")
            print(f"    Stage: {acr['pipeline_stage']}")
            print(f"    Retries: {acr['retry_count']}")
            print(f"    Reason: {acr['failure_reason'][:100]}")
        if len(failed_acrs) > 10:
            print(f"\n  ... and {len(failed_acrs) - 10} more failed requests")

    # Stuck ACRs
    stuck_acrs = get_stuck_account_creation_requests()
    if stuck_acrs:
        print(f"\n--- Potentially Stuck Requests ({len(stuck_acrs)}) ---")
        for acr in stuck_acrs:
            print(f"\n  {acr['name']} (Member: {acr['source_record']})")
            print(f"    Status: {acr['status']}")
            print(f"    Stage: {acr['pipeline_stage']}")
            print(f"    Hours Processing: {acr['hours_processing']}")

    print("\n" + "=" * 80 + "\n")


def export_import_report(
    import_start_time: Optional[str] = None, output_file: str = "/tmp/import_report.json"
):
    """
    Export comprehensive import report to JSON file.

    Args:
        import_start_time: Optional filter for imports after this time
        output_file: Path to output JSON file
    """
    report = {
        "generated_at": str(now_datetime()),
        "summary": get_import_summary(import_start_time),
        "members_without_accounts": get_members_without_accounts(import_start_time),
        "failed_requests": get_failed_account_creation_requests(import_start_time),
        "stuck_requests": get_stuck_account_creation_requests(),
    }

    with open(output_file, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\nImport report exported to: {output_file}")
    print(f"Total records: {len(report['members_without_accounts'])} without accounts, ")
    print(f"{len(report['failed_requests'])} failed, {len(report['stuck_requests'])} stuck\n")


def check_member_status(member_name: str):
    """
    Check and print the status of a specific member's import.

    Args:
        member_name: Member ID to check
    """
    mapping = get_member_acr_mapping(member_name)

    if not mapping:
        print(f"\nMember {member_name} not found\n")
        return

    print("\n" + "=" * 80)
    print(f" MEMBER STATUS: {member_name}")
    print("=" * 80)

    member = mapping["member"]
    print(f"\nMember: {member['full_name']}")
    print(f"Email: {member['email_address']}")
    print(f"Status: {member['status']}")
    print(f"Created: {member['creation']}")

    print(f"\nUser Account Exists: {'✓ Yes' if mapping['user_exists'] else '✗ No'}")

    if mapping["account_creation_request"]:
        acr = mapping["account_creation_request"]
        print(f"\nAccount Creation Request: {acr['name']}")
        print(f"  Status: {acr['status']}")
        print(f"  Pipeline Stage: {acr['pipeline_stage']}")
        print(f"  Retry Count: {acr['retry_count']}")
        if acr.get("created_user"):
            print(f"  Created User: {acr['created_user']}")
        if acr.get("created_employee"):
            print(f"  Created Employee: {acr['created_employee']}")
        if acr.get("failure_reason"):
            print(f"  Failure Reason: {acr['failure_reason']}")
        if acr.get("completed_at"):
            print(f"  Completed At: {acr['completed_at']}")
    else:
        print("\nNo Account Creation Request found for this member")

    print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    # When run directly, print summary
    print_import_summary()
