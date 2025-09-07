#!/usr/bin/env python3

import frappe
from frappe.utils import now_datetime


@frappe.whitelist()
def test_donation_controller_cleanup():
    """Test the cleaned donation controller for errors"""

    # Check recent error logs
    error_logs = frappe.get_all(
        "Error Log",
        filters={"creation": [">", "2025-01-06 20:00:00"]},
        fields=["name", "creation", "method", "error"],
        order_by="creation desc",
        limit=20,
    )

    donation_errors = []
    for log in error_logs:
        if "donation" in log.get("method", "").lower() or "donation" in log.get("error", "").lower():
            donation_errors.append(
                {
                    "time": log["creation"],
                    "method": log["method"],
                    "error": log["error"][:300] + "..." if len(log["error"]) > 300 else log["error"],
                }
            )

    # Test basic donation creation
    test_results = []
    try:
        # Try to get a test donor
        donors = frappe.get_all("Donor", limit=1)
        if donors:
            donor_name = donors[0]["name"]

            # Test basic donation document creation (don't save)
            donation = frappe.new_doc("Donation")
            donation.update(
                {
                    "donor": donor_name,
                    "amount": 25.00,
                    "donation_purpose_type": "General",
                    "donation_date": now_datetime().date(),
                }
            )

            # Test validation
            try:
                donation.validate()
                test_results.append({"test": "validation", "status": "success"})
            except Exception as e:
                test_results.append({"test": "validation", "status": "error", "error": str(e)})

            # Test get_earmarking_summary (should still exist)
            try:
                summary = donation.get_earmarking_summary()
                test_results.append({"test": "earmarking_summary", "status": "success", "result": summary})
            except Exception as e:
                test_results.append({"test": "earmarking_summary", "status": "error", "error": str(e)})

        else:
            test_results.append({"test": "setup", "status": "error", "error": "No donors found for testing"})

    except Exception as e:
        test_results.append({"test": "setup", "status": "error", "error": str(e)})

    return {
        "donation_errors": donation_errors,
        "test_results": test_results,
        "total_recent_errors": len(error_logs),
        "donation_related_errors": len(donation_errors),
    }
