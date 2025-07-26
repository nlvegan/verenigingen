"""
Billing Frequency Transition Manager

Handles complex billing frequency transitions with proper validation,
prorated calculations, and audit trails.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import add_months, flt, get_datetime, getdate, today


class BillingFrequencyTransitionManager:
    """Manages complex billing frequency transitions with business rule validation"""

    def __init__(self):
        self.supported_frequencies = ["Monthly", "Quarterly", "Semi-Annual", "Annual"]
        self.frequency_months = {"Monthly": 1, "Quarterly": 3, "Semi-Annual": 6, "Annual": 12}

    def validate_transition(
        self, member: str, old_frequency: str, new_frequency: str, effective_date: str
    ) -> Dict[str, Any]:
        """
        Validate billing frequency transition parameters and business rules

        Returns:
            Dict with 'valid' boolean and details about validation
        """
        validation_result = {"valid": True, "issues": [], "warnings": [], "calculations": {}}

        try:
            # Validate frequencies
            if old_frequency not in self.supported_frequencies:
                validation_result["valid"] = False
                validation_result["issues"].append(f"Unsupported old frequency: {old_frequency}")

            if new_frequency not in self.supported_frequencies:
                validation_result["valid"] = False
                validation_result["issues"].append(f"Unsupported new frequency: {new_frequency}")

            # Validate member exists
            if not frappe.db.exists("Member", member):
                validation_result["valid"] = False
                validation_result["issues"].append(f"Member not found: {member}")
                return validation_result

            # Validate effective date
            effective_date_obj = getdate(effective_date)
            if effective_date_obj < getdate(today()):
                validation_result["valid"] = False
                validation_result["issues"].append("Effective date cannot be in the past")

            # Get active schedules for member
            active_schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={"member": member, "status": "Active", "billing_frequency": old_frequency},
                fields=[
                    "name",
                    "dues_rate",
                    "next_billing_period_start_date",
                    "next_billing_period_end_date",
                    "billing_frequency",
                    "next_invoice_date",
                ],
                order_by="creation desc",
            )

            if not active_schedules:
                validation_result["warnings"].append(f"No active {old_frequency} schedules found for member")
                return validation_result

            # Check for overlapping schedules with new frequency
            overlapping_schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={
                    "member": member,
                    "status": "Active",
                    "billing_frequency": new_frequency,
                    "next_billing_period_start_date": ["<=", effective_date],
                    "next_billing_period_end_date": [">=", effective_date],
                },
                fields=[
                    "name",
                    "billing_frequency",
                    "next_billing_period_start_date",
                    "next_billing_period_end_date",
                ],
            )

            if overlapping_schedules:
                validation_result["valid"] = False
                schedule_names = [s.name for s in overlapping_schedules]
                validation_result["issues"].append(
                    f"Overlapping {new_frequency} schedules found: {', '.join(schedule_names)}"
                )

            # Calculate prorated amounts
            if validation_result["valid"] and active_schedules:
                calculations = self._calculate_prorated_amounts(
                    active_schedules[0], old_frequency, new_frequency, effective_date_obj
                )
                validation_result["calculations"] = calculations

                # Add business rule warnings
                if calculations.get("refund_due", 0) > 0:
                    validation_result["warnings"].append(
                        f"Transition will result in refund of {calculations['refund_due']:.2f}"
                    )
                elif calculations.get("additional_charge", 0) > 0:
                    validation_result["warnings"].append(
                        f"Transition will result in additional charge of {calculations['additional_charge']:.2f}"
                    )

            return validation_result

        except Exception as e:
            frappe.log_error(
                f"Error validating billing transition: {str(e)}", "Billing Transition Validation"
            )
            validation_result["valid"] = False
            validation_result["issues"].append(f"Validation error: {str(e)}")
            return validation_result

    def _calculate_prorated_amounts(
        self, schedule: Dict, old_frequency: str, new_frequency: str, effective_date: date
    ) -> Dict[str, float]:
        """Calculate prorated amounts for billing frequency transition"""

        calculations = {
            "old_monthly_rate": 0.0,
            "new_monthly_rate": 0.0,
            "unused_period_months": 0.0,
            "remaining_period_months": 0.0,
            "refund_due": 0.0,
            "additional_charge": 0.0,
            "net_adjustment": 0.0,
        }

        try:
            # Calculate monthly rates
            old_months = self.frequency_months[old_frequency]
            new_months = self.frequency_months[new_frequency]

            calculations["old_monthly_rate"] = flt(schedule["dues_rate"]) / old_months

            # For new frequency, we need to determine the equivalent rate
            # This could be based on membership type settings or calculated proportionally
            calculations["new_monthly_rate"] = calculations["old_monthly_rate"]  # Keep same monthly rate

            # Calculate remaining period from effective date
            next_due = getdate(schedule.get("next_due_date", effective_date))
            if next_due > effective_date:
                # Calculate unused months in current period
                days_unused = (next_due - effective_date).days
                calculations["unused_period_months"] = days_unused / 30.44  # Average month length

                # Calculate remaining months in new period
                calculations["remaining_period_months"] = new_months

                # Calculate financial adjustments
                unused_amount = calculations["unused_period_months"] * calculations["old_monthly_rate"]
                new_period_amount = calculations["remaining_period_months"] * calculations["new_monthly_rate"]

                calculations["net_adjustment"] = new_period_amount - unused_amount

                if calculations["net_adjustment"] > 0:
                    calculations["additional_charge"] = calculations["net_adjustment"]
                else:
                    calculations["refund_due"] = abs(calculations["net_adjustment"])

            return calculations

        except Exception as e:
            frappe.log_error(
                f"Error calculating prorated amounts: {str(e)}", "Billing Transition Calculation"
            )
            return calculations

    def execute_transition(self, member: str, transition_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute billing frequency transition with rollback support

        Args:
            member: Member name
            transition_params: Dict containing:
                - old_frequency: Current frequency
                - new_frequency: Target frequency
                - effective_date: When transition takes effect
                - new_rate: Optional new rate (if changing)
                - reason: Reason for transition

        Returns:
            Dict with success status and details
        """
        result = {
            "success": False,
            "message": "",
            "created_schedules": [],
            "cancelled_schedules": [],
            "adjustments_made": [],
            "audit_trail": [],
        }

        # Validate transition first
        validation = self.validate_transition(
            member,
            transition_params["old_frequency"],
            transition_params["new_frequency"],
            transition_params["effective_date"],
        )

        if not validation["valid"]:
            result["message"] = f"Validation failed: {'; '.join(validation['issues'])}"
            return result

        # Start database transaction
        frappe.db.begin()

        try:
            # Get active schedules to cancel
            old_schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={
                    "member": member,
                    "status": "Active",
                    "billing_frequency": transition_params["old_frequency"],
                },
                fields=[
                    "name",
                    "dues_rate",
                    "next_billing_period_start_date",
                    "next_billing_period_end_date",
                    "next_invoice_date",
                ],
            )

            effective_date = getdate(transition_params["effective_date"])

            # Cancel old schedules
            for schedule_data in old_schedules:
                schedule_doc = frappe.get_doc("Membership Dues Schedule", schedule_data["name"])

                # Update end date to effective date
                schedule_doc.end_date = effective_date
                schedule_doc.status = "Cancelled"
                schedule_doc.add_comment(
                    "Comment",
                    f"Cancelled due to frequency transition to {transition_params['new_frequency']}",
                )
                schedule_doc.save()

                result["cancelled_schedules"].append(schedule_data["name"])
                result["audit_trail"].append(
                    {
                        "action": "cancelled_schedule",
                        "schedule": schedule_data["name"],
                        "reason": "frequency_transition",
                        "timestamp": frappe.utils.now(),
                    }
                )

            # Create new schedule
            new_schedule = frappe.new_doc("Membership Dues Schedule")
            new_schedule.update(
                {
                    "schedule_name": f"Transition-{member}-{transition_params['new_frequency']}-{frappe.utils.now()}",
                    "member": member,
                    "billing_frequency": transition_params["new_frequency"],
                    "dues_rate": transition_params.get("new_rate")
                    or (
                        validation["calculations"].get("new_monthly_rate", 0)
                        * self.frequency_months[transition_params["new_frequency"]]
                    ),
                    "start_date": effective_date,
                    "status": "Active",
                    "payment_method": "SEPA Direct Debit",  # Default, can be overridden
                    "created_by_transition": True,
                }
            )

            # Set end date based on frequency
            if transition_params["new_frequency"] == "Annual":
                new_schedule.end_date = add_months(effective_date, 12)
            elif transition_params["new_frequency"] == "Semi-Annual":
                new_schedule.end_date = add_months(effective_date, 6)
            elif transition_params["new_frequency"] == "Quarterly":
                new_schedule.end_date = add_months(effective_date, 3)
            else:  # Monthly
                new_schedule.end_date = add_months(effective_date, 1)

            new_schedule.insert()

            result["created_schedules"].append(new_schedule.name)
            result["audit_trail"].append(
                {
                    "action": "created_schedule",
                    "schedule": new_schedule.name,
                    "frequency": transition_params["new_frequency"],
                    "rate": new_schedule.dues_rate,
                    "timestamp": frappe.utils.now(),
                }
            )

            # Handle financial adjustments if needed
            calculations = validation.get("calculations", {})
            if calculations.get("refund_due", 0) > 0 or calculations.get("additional_charge", 0) > 0:
                adjustment_result = self._create_financial_adjustment(member, calculations, transition_params)
                result["adjustments_made"].append(adjustment_result)

            # Create audit record
            audit_doc = frappe.new_doc("Billing Frequency Transition Audit")
            audit_doc.update(
                {
                    "member": member,
                    "old_frequency": transition_params["old_frequency"],
                    "new_frequency": transition_params["new_frequency"],
                    "effective_date": effective_date,
                    "reason": transition_params.get("reason", "Member request"),
                    "old_schedules_cancelled": len(result["cancelled_schedules"]),
                    "new_schedules_created": len(result["created_schedules"]),
                    "financial_adjustment": calculations.get("net_adjustment", 0),
                    "transition_status": "Completed",
                    "processed_by": frappe.session.user,
                    "processed_at": frappe.utils.now(),
                }
            )
            audit_doc.insert()

            result["audit_trail"].append(
                {
                    "action": "audit_record_created",
                    "audit_record": audit_doc.name,
                    "timestamp": frappe.utils.now(),
                }
            )

            # Commit transaction
            frappe.db.commit()

            result["success"] = True
            result[
                "message"
            ] = f"Successfully transitioned from {transition_params['old_frequency']} to {transition_params['new_frequency']} billing"

            return result

        except Exception as e:
            # Rollback on error
            frappe.db.rollback()
            frappe.log_error(f"Error executing billing transition: {str(e)}", "Billing Transition Execution")

            result["message"] = f"Transition failed: {str(e)}"
            return result

    def _create_financial_adjustment(
        self, member: str, calculations: Dict, transition_params: Dict
    ) -> Dict[str, Any]:
        """Create financial adjustment entry for prorated amounts"""

        adjustment_result = {"type": "", "amount": 0.0, "reference": "", "status": "created"}

        try:
            net_adjustment = calculations.get("net_adjustment", 0)

            if abs(net_adjustment) < 0.01:  # No significant adjustment needed
                adjustment_result["type"] = "none"
                return adjustment_result

            # Create adjustment entry (this would integrate with ERPNext financial system)
            if net_adjustment > 0:
                # Additional charge needed
                adjustment_result["type"] = "additional_charge"
                adjustment_result["amount"] = net_adjustment

                # Would create a sales invoice or journal entry here
                # For now, just log the requirement
                frappe.log_info(
                    {
                        "member": member,
                        "adjustment_type": "additional_charge",
                        "amount": net_adjustment,
                        "reason": "billing_frequency_transition",
                    },
                    "Billing Adjustment Required",
                )

            else:
                # Refund due
                adjustment_result["type"] = "refund"
                adjustment_result["amount"] = abs(net_adjustment)

                # Would create a credit note or refund entry here
                frappe.log_info(
                    {
                        "member": member,
                        "adjustment_type": "refund",
                        "amount": abs(net_adjustment),
                        "reason": "billing_frequency_transition",
                    },
                    "Billing Refund Required",
                )

            return adjustment_result

        except Exception as e:
            frappe.log_error(f"Error creating financial adjustment: {str(e)}", "Billing Financial Adjustment")
            adjustment_result["status"] = "error"
            adjustment_result["error"] = str(e)
            return adjustment_result

    def get_transition_preview(
        self, member: str, old_frequency: str, new_frequency: str, effective_date: str
    ) -> Dict[str, Any]:
        """
        Get preview of what would happen in a billing frequency transition
        without actually executing it
        """
        preview = {
            "valid": False,
            "member_info": {},
            "current_schedules": [],
            "proposed_changes": {},
            "financial_impact": {},
            "warnings": [],
            "next_steps": [],
        }

        try:
            # Get member info
            member_doc = frappe.get_doc("Member", member)
            preview["member_info"] = {
                "name": member_doc.name,
                "full_name": member_doc.full_name,
                "email": member_doc.email,
            }

            # Validate transition
            validation = self.validate_transition(member, old_frequency, new_frequency, effective_date)
            preview["valid"] = validation["valid"]
            preview["warnings"] = validation.get("warnings", [])

            if validation.get("issues"):
                preview["issues"] = validation["issues"]
                return preview

            # Get current schedules
            current_schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={"member": member, "status": "Active", "billing_frequency": old_frequency},
                fields=[
                    "name",
                    "billing_frequency",
                    "dues_rate",
                    "next_billing_period_start_date",
                    "next_billing_period_end_date",
                    "next_invoice_date",
                ],
            )
            preview["current_schedules"] = current_schedules

            # Proposed changes
            preview["proposed_changes"] = {
                "schedules_to_cancel": len(current_schedules),
                "new_schedule_frequency": new_frequency,
                "effective_date": effective_date,
                "estimated_new_rate": validation["calculations"].get("new_monthly_rate", 0)
                * self.frequency_months[new_frequency],
            }

            # Financial impact
            preview["financial_impact"] = validation.get("calculations", {})

            # Next steps
            preview["next_steps"] = [
                "Review financial impact and warnings",
                "Confirm transition parameters",
                "Execute transition",
                "Monitor first billing cycle",
            ]

            return preview

        except Exception as e:
            frappe.log_error(f"Error generating transition preview: {str(e)}", "Billing Transition Preview")
            preview["error"] = str(e)
            return preview


# API Functions for external use
@frappe.whitelist()
def validate_billing_frequency_transition(member, old_frequency, new_frequency, effective_date):
    """API endpoint to validate billing frequency transition"""
    manager = BillingFrequencyTransitionManager()
    return manager.validate_transition(member, old_frequency, new_frequency, effective_date)


@frappe.whitelist()
def execute_billing_frequency_transition(
    member, old_frequency, new_frequency, effective_date, new_rate=None, reason=None
):
    """API endpoint to execute billing frequency transition"""
    manager = BillingFrequencyTransitionManager()

    transition_params = {
        "old_frequency": old_frequency,
        "new_frequency": new_frequency,
        "effective_date": effective_date,
        "reason": reason or "Member request",
    }

    if new_rate:
        transition_params["new_rate"] = float(new_rate)

    return manager.execute_transition(member, transition_params)


@frappe.whitelist()
def get_billing_transition_preview(member, old_frequency, new_frequency, effective_date):
    """API endpoint to get billing frequency transition preview"""
    manager = BillingFrequencyTransitionManager()
    return manager.get_transition_preview(member, old_frequency, new_frequency, effective_date)
