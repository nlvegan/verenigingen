"""
Validation script to demonstrate that the event-driven architecture fixes
the payment history validation blocking issue
"""

import frappe
from frappe.utils import add_days, today

# Import security framework
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def validate_architectural_fix():
    """
    Demonstrate that invoice submission no longer depends on payment history validation
    """
    results = {"test_name": "Event-Driven Architecture Validation", "test_steps": [], "conclusion": ""}

    try:
        # Step 1: Check current hooks configuration
        from verenigingen.hooks import doc_events

        invoice_hooks = doc_events.get("Sales Invoice", {})
        on_submit_hook = invoice_hooks.get("on_submit", "")

        results["test_steps"].append(
            {
                "step": "Check hooks.py configuration",
                "expected": "verenigingen.events.invoice_events.emit_invoice_submitted",
                "actual": on_submit_hook,
                "passed": "emit_invoice_submitted" in on_submit_hook,
            }
        )

        # Step 2: Verify old synchronous function is NOT called
        old_function = "update_member_payment_history_from_invoice"
        using_old_system = old_function in on_submit_hook

        results["test_steps"].append(
            {
                "step": "Verify old synchronous function removed",
                "expected": "Should NOT contain update_member_payment_history_from_invoice",
                "actual": f"Contains {old_function}: {using_old_system}",
                "passed": not using_old_system,
            }
        )

        # Step 3: Test that invoice submission works
        # Find a test member
        member = frappe.get_all(
            "Member", filters={"customer": ["!=", ""]}, fields=["name", "customer"], limit=1
        )

        if member:
            member = member[0]

            # Create test invoice
            invoice = frappe.new_doc("Sales Invoice")
            invoice.customer = member.customer
            invoice.posting_date = today()
            invoice.due_date = add_days(today(), 30)

            invoice.append(
                "items",
                {
                    "item_code": "Membership Dues - Daily",
                    "qty": 1,
                    "rate": 1.0,
                    "description": "Architecture validation test",
                },
            )

            invoice.insert()

            # The critical test: Can we submit?
            try:
                invoice.submit()
                submission_success = True
                submission_error = None
            except Exception as e:
                submission_success = False
                submission_error = str(e)

            results["test_steps"].append(
                {
                    "step": "Test invoice submission",
                    "expected": "Invoice should submit without payment history validation errors",
                    "actual": f"Submission {'succeeded' if submission_success else 'failed'}",
                    "passed": submission_success,
                    "error": submission_error,
                }
            )

            # Cleanup
            if invoice.docstatus == 1:
                invoice.cancel()
            invoice.delete()

        # Step 4: Verify event system is configured
        try:
            from verenigingen.events.invoice_events import _get_event_subscribers

            subscribers = _get_event_subscribers("invoice_submitted")
            has_subscribers = len(subscribers) > 0

            results["test_steps"].append(
                {
                    "step": "Verify event subscribers configured",
                    "expected": "At least one subscriber for invoice_submitted event",
                    "actual": f"Found {len(subscribers)} subscribers",
                    "passed": has_subscribers,
                }
            )
        except Exception as e:
            results["test_steps"].append(
                {
                    "step": "Verify event subscribers configured",
                    "expected": "Event system should be importable",
                    "actual": f"Error: {str(e)}",
                    "passed": False,
                }
            )

        # Determine overall result
        all_passed = all(step.get("passed", False) for step in results["test_steps"])

        if all_passed:
            results[
                "conclusion"
            ] = "✅ SUCCESS: Event-driven architecture is properly configured. Invoice submission is decoupled from payment history validation."
            results["status"] = "success"
        else:
            results["conclusion"] = "❌ FAILURE: Some tests failed. Check the individual test steps."
            results["status"] = "failure"

    except Exception as e:
        results["error"] = str(e)
        results["conclusion"] = f"❌ ERROR: Validation failed with error: {str(e)}"
        results["status"] = "error"

    return results


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def compare_architectures():
    """
    Compare the old synchronous approach vs new event-driven approach
    """
    return {
        "old_architecture": {
            "name": "Synchronous Payment History Update",
            "flow": [
                "1. Invoice.submit() called",
                "2. on_submit hook triggered",
                "3. update_member_payment_history_from_invoice() called SYNCHRONOUSLY",
                "4. Member document loaded",
                "5. Payment history reloaded",
                "6. Member.save() called",
                "7. Validation runs on ALL Member fields including payment_history",
                "8. If validation fails → Invoice submission BLOCKED ❌",
                "9. Transaction rolled back",
            ],
            "problems": [
                "Tight coupling between invoice and member",
                "Payment history validation can block invoice submission",
                "Single point of failure",
                "Performance impact on every invoice",
                "Difficult to debug when failures occur",
            ],
        },
        "new_architecture": {
            "name": "Event-Driven Payment History Update",
            "flow": [
                "1. Invoice.submit() called",
                "2. on_submit hook triggered",
                "3. emit_invoice_submitted() called",
                "4. Event data prepared",
                "5. Background job queued for each subscriber",
                "6. Invoice submission COMPLETES ✅",
                "7. --- Async boundary ---",
                "8. Background job processes event",
                "9. Payment history updated with retry logic",
                "10. Failures logged but don't affect invoice",
            ],
            "benefits": [
                "Loose coupling - invoice doesn't know about payment history",
                "Invoice submission always succeeds",
                "Multiple subscribers can react to events",
                "Better performance - async processing",
                "Robust error handling with retries",
                "Easy to add new event subscribers",
            ],
        },
        "summary": "The event-driven architecture prevents validation errors in unrelated doctypes from blocking core business operations.",
    }
