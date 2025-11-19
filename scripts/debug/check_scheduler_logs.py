#!/usr/bin/env python3
"""
Check dues schedule scheduler error logs
"""

from datetime import datetime, timedelta

import frappe


def check_error_logs():
    """Check for dues schedule-related errors in the last 7 days"""

    # Calculate date 7 days ago
    seven_days_ago = datetime.now() - timedelta(days=7)

    print("=== DUES SCHEDULE ERROR LOGS (Last 7 days) ===")
    print(f"Checking errors since: {seven_days_ago.strftime('%Y-%m-%d')}")
    print()

    # Check Error Log for dues schedule-related errors
    error_logs = frappe.get_all(
        "Error Log",
        filters={
            "error": ["like", "%dues schedule%"],
            "creation": [">", seven_days_ago.strftime("%Y-%m-%d")],
        },
        fields=["name", "error", "creation"],
        order_by="creation desc",
        limit=10,
    )

    if error_logs:
        print(f"Found {len(error_logs)} dues schedule-related errors:")
        for i, log in enumerate(error_logs, 1):
            print(f"\n{i}. Error Log: {log.name}")
            print(f"   Created: {log.creation}")
            print(f"   Error: {log.error[:200]}...")  # First 200 chars
    else:
        print("No dues schedule-related errors found in Error Log")

    print("\n" + "=" * 50)

    # Check Scheduled Job Log
    print("=== SCHEDULED JOB LOGS (Last 7 days) ===")

    scheduled_jobs = frappe.get_all(
        "Scheduled Job Log",
        filters={"creation": [">", seven_days_ago.strftime("%Y-%m-%d")]},
        fields=["name", "scheduled_job_type", "status", "creation", "details"],
        order_by="creation desc",
        limit=20,
    )

    dues_schedule_jobs = [job for job in scheduled_jobs if "dues_schedule" in job.scheduled_job_type.lower()]

    if dues_schedule_jobs:
        print(f"Found {len(dues_schedule_jobs)} dues schedule-related scheduled jobs:")
        for i, job in enumerate(dues_schedule_jobs, 1):
            print(f"\n{i}. Job: {job.scheduled_job_type}")
            print(f"   Status: {job.status}")
            print(f"   Created: {job.creation}")
            if job.details:
                print(f"   Details: {job.details[:200]}...")
    else:
        print("No dues schedule-related scheduled jobs found")

    print("\n" + "=" * 50)

    # Check for any errors containing "Current Invoice Start Date"
    print("=== CURRENT INVOICE START DATE ERRORS ===")

    start_date_errors = frappe.get_all(
        "Error Log",
        filters={
            "error": ["like", "%Current Invoice Start Date%"],
            "creation": [">", seven_days_ago.strftime("%Y-%m-%d")],
        },
        fields=["name", "error", "creation"],
        order_by="creation desc",
        limit=5,
    )

    if start_date_errors:
        print(f"Found {len(start_date_errors)} 'Current Invoice Start Date' errors:")
        for i, log in enumerate(start_date_errors, 1):
            print(f"\n{i}. Error Log: {log.name}")
            print(f"   Created: {log.creation}")
            print(f"   Error: {log.error}")
    else:
        print("No 'Current Invoice Start Date' errors found")

    print("\n" + "=" * 50)

    # Check all recent scheduled jobs to see their status
    print("=== ALL RECENT SCHEDULED JOB STATUS ===")

    all_jobs = frappe.get_all(
        "Scheduled Job Log",
        filters={"creation": [">", seven_days_ago.strftime("%Y-%m-%d")]},
        fields=["scheduled_job_type", "status"],
        order_by="creation desc",
        limit=50,
    )

    # Group by job type and status
    job_stats = {}
    for job in all_jobs:
        job_type = job.scheduled_job_type
        status = job.status
        if job_type not in job_stats:
            job_stats[job_type] = {}
        if status not in job_stats[job_type]:
            job_stats[job_type][status] = 0
        job_stats[job_type][status] += 1

    print("Job Status Summary:")
    for job_type, statuses in job_stats.items():
        if "dues_schedule" in job_type.lower() or "process" in job_type.lower():
            print(f"\n{job_type}:")
            for status, count in statuses.items():
                print(f"  {status}: {count}")


if __name__ == "__main__":
    check_error_logs()
