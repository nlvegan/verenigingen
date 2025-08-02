# Copyright (c) 2025, Veganisme Nederland and contributors
# For license information, please see license.txt

"""
Billing Frequency Transition Audit DocType

This module provides comprehensive audit trail functionality for tracking changes to member
billing frequencies. It ensures compliance with financial audit requirements and provides
detailed logging of all billing frequency transitions.

Key Features:
- Complete audit trail for billing frequency changes
- Validation of frequency transitions and member data
- Financial adjustment tracking and reconciliation
- Status tracking with automatic logging
- Integration with membership dues scheduling system

Business Context:
The Verenigingen association management system supports flexible billing frequencies
(Monthly, Quarterly, Semi-Annual, Annual) for membership dues. When members request
changes to their billing frequency, this audit system ensures:
- All changes are properly tracked and logged
- Financial adjustments are calculated and recorded
- Schedule transitions are coordinated between old and new frequencies
- Compliance requirements are met for audit purposes

Architecture:
This DocType integrates with:
- Member DocType for member validation
- Membership Dues Schedule system for schedule coordination
- Financial adjustment systems for pro-rata calculations
- User and session management for audit trail completeness

Data Model:
- Member information and transition details
- Old and new frequency specifications with validation
- Financial impact tracking (schedules, adjustments)
- Processing metadata (who, when, status)
- Complete audit trail with status change logging

Compliance Features:
- Immutable audit records once created
- Complete change history with timestamps
- User attribution for all changes
- Status transition logging with detailed metadata
- Integration with broader audit and compliance framework

Author: Development Team
Date: 2025-07-25
Version: 1.0
"""

import frappe
from frappe.model.document import Document


class BillingFrequencyTransitionAudit(Document):
    """
    Audit trail document for tracking billing frequency transitions.

    This DocType provides a comprehensive audit trail for changes to member billing
    frequencies, ensuring compliance with financial audit requirements and providing
    detailed tracking of all transitions.

    Key Responsibilities:
    - Track billing frequency changes with complete audit trail
    - Validate transition data and ensure business rule compliance
    - Record financial impacts and schedule coordination
    - Provide status tracking with automatic logging
    - Maintain immutable audit records for compliance

    Business Process Integration:
    - Integrates with membership dues scheduling system
    - Coordinates with financial adjustment calculations
    - Provides audit data for compliance reporting
    - Supports billing frequency transition workflows

    Data Integrity:
    - Validates member existence and frequency values
    - Ensures meaningful transitions (different frequencies)
    - Maintains complete audit trail with timestamps
    - Tracks processing status and financial impacts

    Usage Example:
        ```python
        # Create audit record for billing frequency transition
        audit = frappe.new_doc("Billing Frequency Transition Audit")
        audit.member = "MEM-001"
        audit.old_frequency = "Monthly"
        audit.new_frequency = "Annual"
        audit.effective_date = "2025-01-01"
        audit.reason = "Member request for annual billing"
        audit.transition_status = "Pending"
        audit.save()
        ```

    Security Model:
    - System Manager: Full access for system administration
    - Verenigingen Administrator: Read access for audit review
    - Verenigingen Member Manager: Read access for operational oversight

    Performance Considerations:
    - Indexed on member and effective_date for efficient querying
    - Status change logging uses efficient frappe.log_info
    - Validation queries are optimized for member existence checks
    """

    def before_insert(self):
        """
        Set audit fields before document insertion.

        Automatically populates audit tracking fields with current user and timestamp
        to ensure complete audit trail from record creation.

        Fields Set:
        - created_by: Current session user for attribution
        - creation_time: Current timestamp for audit trail

        Notes:
        - Only sets fields if not already populated (allows manual override)
        - Uses frappe.session.user for current authenticated user
        - Uses frappe.utils.now() for consistent timestamp formatting
        """
        if not self.created_by:
            self.created_by = frappe.session.user
        if not self.creation_time:
            self.creation_time = frappe.utils.now()

    def validate(self):
        """
        Comprehensive validation of billing frequency transition audit data.

        Validates:
        - Member existence in the system
        - Frequency values against supported options
        - Meaningful transition (different frequencies)

        Business Rules:
        - Member must exist in Member DocType
        - Frequencies must be from supported list: Monthly, Quarterly, Semi-Annual, Annual
        - Old and new frequencies must be different (no redundant transitions)

        Raises:
        - frappe.ValidationError: If member doesn't exist
        - frappe.ValidationError: If frequency values are invalid
        - frappe.ValidationError: If old and new frequencies are identical

        Performance:
        - Uses frappe.db.exists() for efficient member validation
        - Frequency validation uses in-memory list comparison
        """
        # Ensure member exists - critical for audit trail integrity
        if not frappe.db.exists("Member", self.member):
            frappe.throw(f"Member {self.member} does not exist")

        # Validate frequency values against supported options
        valid_frequencies = ["Monthly", "Quarterly", "Semi-Annual", "Annual"]
        if self.old_frequency not in valid_frequencies:
            frappe.throw(f"Invalid old frequency: {self.old_frequency}")
        if self.new_frequency not in valid_frequencies:
            frappe.throw(f"Invalid new frequency: {self.new_frequency}")

        # Ensure transition is meaningful - no redundant audit records
        if self.old_frequency == self.new_frequency:
            frappe.throw("Old and new frequencies cannot be the same")

    def on_update(self):
        """
        Log significant updates to the audit record for complete change tracking.

        Specifically monitors and logs changes to transition_status field, which is
        critical for tracking the progress of billing frequency transitions.

        Logged Information:
        - audit_record: Document name for reference
        - member: Member ID for cross-reference
        - status_change: Old -> New status transition
        - updated_by: User making the change
        - timestamp: When the change occurred

        Implementation:
        - Uses has_value_changed() to detect actual changes
        - Logs to "Billing Transition Status Update" category
        - Uses frappe.log_info for structured logging
        - Includes complete audit context for compliance

        Notes:
        - Only logs when transition_status actually changes
        - Provides before/after values for complete audit trail
        - Integrates with Frappe's logging infrastructure
        """
        if self.has_value_changed("transition_status"):
            frappe.log_info(
                {
                    "audit_record": self.name,
                    "member": self.member,
                    "status_change": f"{self.get_db_value('transition_status')} -> {self.transition_status}",
                    "updated_by": frappe.session.user,
                    "timestamp": frappe.utils.now(),
                },
                "Billing Transition Status Update",
            )
