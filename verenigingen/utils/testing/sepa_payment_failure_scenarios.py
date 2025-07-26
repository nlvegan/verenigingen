"""
SEPA Payment Failure Scenarios for Testing

This module provides comprehensive payment failure scenarios with proper SEPA error codes
for testing payment processing, retry logic, and error handling.
"""

import frappe
from frappe import _

# Official SEPA Error Codes (ISO 20022)
SEPA_ERROR_CODES = {
    # Account Errors
    "AC01": {
        "name": "Incorrect Account Number",
        "description": "Account number incorrect (i.e. invalid IBAN)",
        "category": "account",
        "retry_eligible": False,
        "customer_action_required": True,
        "severity": "high",
    },
    "AC04": {
        "name": "Closed Account",
        "description": "Account closed",
        "category": "account",
        "retry_eligible": False,
        "customer_action_required": True,
        "severity": "high",
    },
    "AC06": {
        "name": "Blocked Account",
        "description": "Account blocked",
        "category": "account",
        "retry_eligible": False,
        "customer_action_required": True,
        "severity": "high",
    },
    # Amount/Balance Errors
    "AM04": {
        "name": "Insufficient Funds",
        "description": "Insufficient funds",
        "category": "balance",
        "retry_eligible": True,
        "retry_days": 3,
        "customer_action_required": False,
        "severity": "medium",
    },
    "AM05": {
        "name": "Duplicate Collection",
        "description": "Duplicate collection",
        "category": "duplicate",
        "retry_eligible": False,
        "customer_action_required": False,
        "severity": "low",
    },
    # Mandate Errors
    "AM02": {
        "name": "No Valid Mandate",
        "description": "No valid mandate",
        "category": "mandate",
        "retry_eligible": False,
        "customer_action_required": True,
        "severity": "high",
    },
    "AM09": {
        "name": "Wrong Amount",
        "description": "Wrong amount",
        "category": "mandate",
        "retry_eligible": False,
        "customer_action_required": True,
        "severity": "medium",
    },
    # Bank/System Errors
    "AB03": {
        "name": "Invalid Creditor Bank",
        "description": "Invalid creditor bank",
        "category": "system",
        "retry_eligible": True,
        "retry_days": 1,
        "customer_action_required": False,
        "severity": "medium",
    },
    "AB09": {
        "name": "Invalid File Format",
        "description": "Invalid file format",
        "category": "system",
        "retry_eligible": True,
        "retry_days": 1,
        "customer_action_required": False,
        "severity": "low",
    },
    # Refusal/Rejection Errors
    "RC01": {
        "name": "Bank Identifier Incorrect",
        "description": "Bank identifier incorrect",
        "category": "system",
        "retry_eligible": False,
        "customer_action_required": False,
        "severity": "medium",
    },
    "SL01": {
        "name": "Due to Specific Service",
        "description": "Due to specific service offered by the Debtor Bank",
        "category": "service",
        "retry_eligible": False,
        "customer_action_required": True,
        "severity": "medium",
    },
}


@frappe.whitelist()
def create_payment_failure_scenario(failure_type="insufficient_funds", **kwargs):
    """
    Create test scenarios for payment failures with official SEPA error codes

    Args:
        failure_type: Type of failure scenario
                     - "insufficient_funds": Most common retry-eligible failure
                     - "account_closed": Account permanently closed
                     - "invalid_mandate": Mandate issues
                     - "blocked_account": Account restrictions
                     - "wrong_amount": Amount validation failures
                     - "bank_error": System/bank issues
                     - "duplicate": Duplicate payment attempts
                     - "custom": Custom error with override parameters

    Returns:
        dict with failure scenario details including error codes, retry logic, and customer actions
    """
    failure_scenarios = {
        "insufficient_funds": {
            "error_code": "AM04",
            "error_message": "Insufficient funds available",
            "retry_eligible": True,
            "retry_days": 3,
            "max_retries": 2,
            "customer_action_required": False,
            "customer_notification": "Your payment failed due to insufficient funds. Please ensure sufficient balance.",
            "internal_note": "Standard insufficient funds - retry in 3 days",
            "severity": "medium",
            "category": "balance",
        },
        "account_closed": {
            "error_code": "AC04",
            "error_message": "Account has been closed",
            "retry_eligible": False,
            "retry_days": 0,
            "max_retries": 0,
            "customer_action_required": True,
            "customer_notification": "Your account appears to be closed. Please update your payment details.",
            "internal_note": "Account closed - require new mandate",
            "severity": "high",
            "category": "account",
        },
        "invalid_mandate": {
            "error_code": "AM02",
            "error_message": "No valid mandate found",
            "retry_eligible": False,
            "retry_days": 0,
            "max_retries": 0,
            "customer_action_required": True,
            "customer_notification": "There is an issue with your payment authorization. Please contact support.",
            "internal_note": "Mandate validation failed - check mandate status",
            "severity": "high",
            "category": "mandate",
        },
        "blocked_account": {
            "error_code": "AC06",
            "error_message": "Account is blocked or restricted",
            "retry_eligible": False,
            "retry_days": 0,
            "max_retries": 0,
            "customer_action_required": True,
            "customer_notification": "Your account appears to be restricted. Please contact your bank.",
            "internal_note": "Account blocked - customer must resolve with bank",
            "severity": "high",
            "category": "account",
        },
        "wrong_amount": {
            "error_code": "AM09",
            "error_message": "Payment amount exceeds mandate limit",
            "retry_eligible": False,
            "retry_days": 0,
            "max_retries": 0,
            "customer_action_required": True,
            "customer_notification": "Payment amount exceeds your authorization limit. Please update your mandate.",
            "internal_note": "Amount validation failed - check mandate limits",
            "severity": "medium",
            "category": "mandate",
        },
        "bank_error": {
            "error_code": "AB03",
            "error_message": "Technical issue at creditor bank",
            "retry_eligible": True,
            "retry_days": 1,
            "max_retries": 3,
            "customer_action_required": False,
            "customer_notification": "Payment temporarily failed due to technical issues. We will retry automatically.",
            "internal_note": "Bank system error - retry tomorrow",
            "severity": "medium",
            "category": "system",
        },
        "duplicate": {
            "error_code": "AM05",
            "error_message": "Duplicate payment detected",
            "retry_eligible": False,
            "retry_days": 0,
            "max_retries": 0,
            "customer_action_required": False,
            "customer_notification": "Duplicate payment detected - no action required.",
            "internal_note": "Duplicate payment - investigate collection process",
            "severity": "low",
            "category": "duplicate",
        },
    }

    # Get base scenario
    scenario = failure_scenarios.get(failure_type, failure_scenarios["insufficient_funds"])

    # Apply custom overrides
    scenario.update(kwargs)

    # Add SEPA error code details if available
    error_code = scenario.get("error_code")
    if error_code in SEPA_ERROR_CODES:
        sepa_details = SEPA_ERROR_CODES[error_code]
        scenario.update(
            {
                "sepa_error_name": sepa_details["name"],
                "sepa_error_description": sepa_details["description"],
                "sepa_category": sepa_details["category"],
            }
        )

    # Add metadata
    scenario.update(
        {"created_at": frappe.utils.now(), "scenario_type": failure_type, "is_test_scenario": True}
    )

    return scenario


@frappe.whitelist()
def simulate_payment_failure_sequence(member_name, failure_types=None):
    """
    Simulate a sequence of payment failures for comprehensive testing

    Args:
        member_name: Member to simulate failures for
        failure_types: List of failure types to simulate in sequence

    Returns:
        List of failure scenarios with realistic timing and progression
    """
    if not failure_types:
        # Default realistic failure sequence
        failure_types = ["insufficient_funds", "insufficient_funds", "account_closed"]

    sequence = []
    base_date = frappe.utils.today()

    for i, failure_type in enumerate(failure_types):
        scenario = create_payment_failure_scenario(failure_type)

        # Add sequence-specific details
        scenario.update(
            {
                "member": member_name,
                "sequence_number": i + 1,
                "attempted_date": frappe.utils.add_days(base_date, i * 3),  # 3 days apart
                "total_failures": len(failure_types),
                "is_final_attempt": i == len(failure_types) - 1,
            }
        )

        sequence.append(scenario)

    return sequence


@frappe.whitelist()
def get_retry_schedule(error_code, initial_failure_date=None):
    """
    Generate retry schedule based on SEPA error code

    Args:
        error_code: SEPA error code (e.g., "AM04")
        initial_failure_date: Date of initial failure (defaults to today)

    Returns:
        List of retry dates with decreasing frequency
    """
    if not initial_failure_date:
        initial_failure_date = frappe.utils.today()

    if error_code not in SEPA_ERROR_CODES:
        return []

    error_info = SEPA_ERROR_CODES[error_code]

    if not error_info.get("retry_eligible", False):
        return []

    retry_days = error_info.get("retry_days", 3)
    retry_schedule = []

    # Standard retry pattern: immediate interval, then exponential backoff
    retry_intervals = [retry_days, retry_days * 2, retry_days * 4]  # e.g., 3, 6, 12 days

    for i, interval in enumerate(retry_intervals):
        retry_date = frappe.utils.add_days(initial_failure_date, interval)
        retry_schedule.append(
            {
                "retry_number": i + 1,
                "retry_date": retry_date,
                "days_since_failure": interval,
                "retry_reason": f"Automatic retry #{i + 1} for {error_code}",
            }
        )

    return retry_schedule


@frappe.whitelist()
def validate_payment_recovery_scenario(scenario_data):
    """
    Validate if a payment failure scenario allows for recovery

    Args:
        scenario_data: Payment failure scenario dict

    Returns:
        dict with recovery analysis and recommendations
    """
    error_code = scenario_data.get("error_code")
    severity = scenario_data.get("severity", "medium")
    retry_eligible = scenario_data.get("retry_eligible", False)
    customer_action_required = scenario_data.get("customer_action_required", False)

    recovery_analysis = {
        "can_recover": False,
        "recovery_method": None,
        "timeline": None,
        "confidence": "low",
        "recommendations": [],
    }

    if retry_eligible and not customer_action_required:
        # Automatic recovery possible
        recovery_analysis.update(
            {
                "can_recover": True,
                "recovery_method": "automatic_retry",
                "timeline": f"{scenario_data.get('retry_days', 3)} days",
                "confidence": "high",
                "recommendations": [
                    "Implement automatic retry logic",
                    "Monitor retry success rates",
                    "Set maximum retry limits",
                ],
            }
        )
    elif customer_action_required and severity != "high":
        # Customer-driven recovery possible
        recovery_analysis.update(
            {
                "can_recover": True,
                "recovery_method": "customer_action",
                "timeline": "1-7 days (customer dependent)",
                "confidence": "medium",
                "recommendations": [
                    "Send customer notification immediately",
                    "Provide clear action steps",
                    "Follow up if no response within 7 days",
                ],
            }
        )
    elif severity == "high":
        # Recovery unlikely without significant intervention
        recovery_analysis.update(
            {
                "can_recover": False,
                "recovery_method": "manual_intervention",
                "timeline": "7-30 days",
                "confidence": "low",
                "recommendations": [
                    "Contact customer directly",
                    "Request new payment method",
                    "Consider alternative collection methods",
                    "Review account status",
                ],
            }
        )

    return recovery_analysis
