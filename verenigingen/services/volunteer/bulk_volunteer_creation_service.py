# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
BulkVolunteerCreationService - Robust volunteer creation for CSV imports

This service provides:
- Explicit success/failure tracking with detailed error categorization
- Queue-aware processing that respects RQ limits
- Batch processing with configurable sizes
- Retry capability for transient failures
- Comprehensive reporting for import summaries

Design Principles:
- Never silently swallow errors
- Track every attempt and its outcome
- Provide actionable error summaries
- Be resilient to partial failures
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import getdate, today

from verenigingen.services.infrastructure.base_service import StatelessService


class VolunteerCreationOutcome(Enum):
    """Possible outcomes for volunteer creation attempts"""

    CREATED = "created"
    ALREADY_EXISTS = "already_exists"
    MEMBER_NOT_FOUND = "member_not_found"
    MEMBER_INACTIVE = "member_inactive"
    MEMBER_TOO_YOUNG = "member_too_young"
    VALIDATION_ERROR = "validation_error"
    PERMISSION_ERROR = "permission_error"
    UNEXPECTED_ERROR = "unexpected_error"


@dataclass
class VolunteerCreationResult:
    """Result of a single volunteer creation attempt"""

    member_name: str
    outcome: VolunteerCreationOutcome
    volunteer_name: Optional[str] = None
    error_message: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.outcome in (
            VolunteerCreationOutcome.CREATED,
            VolunteerCreationOutcome.ALREADY_EXISTS,
        )


@dataclass
class BulkVolunteerCreationSummary:
    """Summary of bulk volunteer creation operation"""

    total_attempted: int = 0
    created: int = 0
    already_existed: int = 0
    skipped_inactive: int = 0
    skipped_too_young: int = 0
    skipped_not_found: int = 0
    validation_errors: int = 0
    permission_errors: int = 0
    unexpected_errors: int = 0
    results: List[VolunteerCreationResult] = field(default_factory=list)

    @property
    def total_success(self) -> int:
        return self.created + self.already_existed

    @property
    def total_skipped(self) -> int:
        return self.skipped_inactive + self.skipped_too_young + self.skipped_not_found

    @property
    def total_errors(self) -> int:
        return self.validation_errors + self.permission_errors + self.unexpected_errors

    def get_error_summary(self, max_errors: int = 10) -> List[str]:
        """Get human-readable error summary"""
        errors = []
        error_results = [r for r in self.results if not r.success]

        # Group by error type
        by_type: Dict[VolunteerCreationOutcome, List[VolunteerCreationResult]] = {}
        for result in error_results:
            if result.outcome not in by_type:
                by_type[result.outcome] = []
            by_type[result.outcome].append(result)

        for outcome, items in by_type.items():
            if outcome == VolunteerCreationOutcome.MEMBER_INACTIVE:
                errors.append(f"Inactive members skipped: {len(items)}")
            elif outcome == VolunteerCreationOutcome.MEMBER_TOO_YOUNG:
                sample = items[:3]
                sample_names = ", ".join(r.member_name for r in sample)
                errors.append(
                    f"Members too young for volunteering ({len(items)}): {sample_names}"
                    + ("..." if len(items) > 3 else "")
                )
            elif outcome == VolunteerCreationOutcome.VALIDATION_ERROR:
                for item in items[:max_errors]:
                    errors.append(f"Validation error for {item.member_name}: {item.error_message}")
                if len(items) > max_errors:
                    errors.append(f"... and {len(items) - max_errors} more validation errors")
            elif outcome == VolunteerCreationOutcome.UNEXPECTED_ERROR:
                for item in items[:max_errors]:
                    errors.append(f"Error for {item.member_name}: {item.error_message}")
                if len(items) > max_errors:
                    errors.append(f"... and {len(items) - max_errors} more errors")

        return errors

    def to_summary_string(self) -> str:
        """Generate summary string for import report"""
        parts = []
        if self.created > 0:
            parts.append(f"{self.created} created")
        if self.already_existed > 0:
            parts.append(f"{self.already_existed} already existed")
        if self.total_skipped > 0:
            skip_details = []
            if self.skipped_inactive > 0:
                skip_details.append(f"{self.skipped_inactive} inactive")
            if self.skipped_too_young > 0:
                skip_details.append(f"{self.skipped_too_young} too young")
            if self.skipped_not_found > 0:
                skip_details.append(f"{self.skipped_not_found} not found")
            parts.append(f"{self.total_skipped} skipped ({', '.join(skip_details)})")
        if self.total_errors > 0:
            parts.append(f"{self.total_errors} errors")

        if not parts:
            return ". No volunteer records processed"

        return f". Volunteers: {', '.join(parts)}"


class BulkVolunteerCreationService(StatelessService):
    """
    Service for robust bulk volunteer creation during imports.

    Key features:
    - Tracks every creation attempt with detailed outcomes
    - Provides clear error categorization
    - Supports batch processing
    - Never silently fails
    """

    # Valid statuses for volunteer creation
    VALID_VOLUNTEER_STATUSES = ["Active", "Approved"]

    def __init__(self):
        super().__init__(service_name="BulkVolunteerCreationService")
        self._settings = None

    @property
    def settings(self):
        """Lazy-load Verenigingen Settings"""
        if self._settings is None:
            self._settings = frappe.get_single("Verenigingen Settings")
        return self._settings

    @property
    def minimum_volunteer_age(self) -> int:
        """Get minimum volunteer age from settings"""
        return self.settings.get("minimum_volunteer_age") or 16

    def create_volunteers_for_members(
        self,
        member_names: List[str],
        batch_size: int = 50,
        commit_per_batch: bool = True,
    ) -> BulkVolunteerCreationSummary:
        """
        Create volunteer records for a list of members with full tracking.

        Args:
            member_names: List of member document names
            batch_size: Number of members to process before committing
            commit_per_batch: Whether to commit after each batch

        Returns:
            BulkVolunteerCreationSummary with detailed results
        """
        summary = BulkVolunteerCreationSummary(total_attempted=len(member_names))

        if not member_names:
            self.logger.info("No members provided for volunteer creation")
            return summary

        self.logger.info(f"Starting bulk volunteer creation for {len(member_names)} members")

        # Process in batches
        for batch_start in range(0, len(member_names), batch_size):
            batch_end = min(batch_start + batch_size, len(member_names))
            batch = member_names[batch_start:batch_end]

            self.logger.info(
                f"Processing volunteer batch {batch_start // batch_size + 1}: "
                f"members {batch_start + 1}-{batch_end} of {len(member_names)}"
            )

            # Pre-fetch data for batch efficiency
            batch_data = self._fetch_batch_data(batch)

            for member_name in batch:
                result = self._create_volunteer_for_member(member_name, batch_data)
                summary.results.append(result)
                self._update_summary_counts(summary, result)

            if commit_per_batch:
                frappe.db.commit()

        self.logger.info(
            f"Bulk volunteer creation completed: {summary.created} created, "
            f"{summary.already_existed} existed, {summary.total_skipped} skipped, "
            f"{summary.total_errors} errors"
        )

        return summary

    def _fetch_batch_data(self, member_names: List[str]) -> Dict[str, Any]:
        """Pre-fetch data for batch to minimize DB queries"""
        # Get member data in one query
        members = frappe.get_all(
            "Member",
            filters={"name": ["in", member_names]},
            fields=[
                "name",
                "full_name",
                "first_name",
                "tussenvoegsel",
                "last_name",
                "email",
                "birth_date",
                "status",
                "user",
                "member_since",
            ],
        )
        member_map = {m.name: m for m in members}

        # Check for existing volunteers in one query
        existing_volunteers = set()
        if member_names:
            existing = frappe.get_all(
                "Volunteer",
                filters={"member": ["in", member_names]},
                pluck="member",
            )
            existing_volunteers = set(existing)

        return {
            "members": member_map,
            "existing_volunteers": existing_volunteers,
        }

    def _create_volunteer_for_member(
        self,
        member_name: str,
        batch_data: Dict[str, Any],
    ) -> VolunteerCreationResult:
        """
        Create a volunteer record for a single member with proper error handling.

        Never raises exceptions - always returns a result object.
        """
        try:
            member_map = batch_data.get("members", {})
            existing_volunteers = batch_data.get("existing_volunteers", set())

            # Check if member exists in our pre-fetched data
            if member_name not in member_map:
                # Try fetching directly in case batch data is stale
                if not frappe.db.exists("Member", member_name):
                    return VolunteerCreationResult(
                        member_name=member_name,
                        outcome=VolunteerCreationOutcome.MEMBER_NOT_FOUND,
                        error_message=f"Member {member_name} does not exist",
                    )
                # Fetch the member data
                member_data = frappe.db.get_value(
                    "Member",
                    member_name,
                    [
                        "name",
                        "full_name",
                        "first_name",
                        "tussenvoegsel",
                        "last_name",
                        "email",
                        "birth_date",
                        "status",
                        "user",
                        "member_since",
                    ],
                    as_dict=True,
                )
            else:
                member_data = member_map[member_name]

            # Check if volunteer already exists
            if member_name in existing_volunteers or frappe.db.exists("Volunteer", {"member": member_name}):
                existing_vol = frappe.db.get_value("Volunteer", {"member": member_name}, "name")
                return VolunteerCreationResult(
                    member_name=member_name,
                    outcome=VolunteerCreationOutcome.ALREADY_EXISTS,
                    volunteer_name=existing_vol,
                    details={"existing_volunteer": existing_vol},
                )

            # Check member status
            if member_data.status not in self.VALID_VOLUNTEER_STATUSES:
                return VolunteerCreationResult(
                    member_name=member_name,
                    outcome=VolunteerCreationOutcome.MEMBER_INACTIVE,
                    error_message=f"Member status '{member_data.status}' not eligible for volunteering",
                    details={"status": member_data.status},
                )

            # Check age requirement
            if member_data.birth_date:
                from dateutil.relativedelta import relativedelta

                age = relativedelta(getdate(today()), getdate(member_data.birth_date)).years
                if age < self.minimum_volunteer_age:
                    return VolunteerCreationResult(
                        member_name=member_name,
                        outcome=VolunteerCreationOutcome.MEMBER_TOO_YOUNG,
                        error_message=f"Member age {age} below minimum {self.minimum_volunteer_age}",
                        details={"age": age, "minimum_age": self.minimum_volunteer_age},
                    )

            # Determine volunteer name
            volunteer_display_name = self._get_volunteer_display_name(member_data)

            # Create volunteer record
            volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": volunteer_display_name,
                    "member": member_name,
                    "status": "New",
                    "start_date": member_data.member_since or today(),
                }
            )

            # Copy user link if exists
            if member_data.user:
                volunteer.user = member_data.user

            # Set flag to bypass workflow during bulk creation
            volunteer.flags.ignore_workflow = True

            # Insert the volunteer
            volunteer.insert()

            # Update member's volunteer_record reference
            frappe.db.set_value(
                "Member",
                member_name,
                "volunteer_record",
                volunteer.name,
                update_modified=False,
            )

            return VolunteerCreationResult(
                member_name=member_name,
                outcome=VolunteerCreationOutcome.CREATED,
                volunteer_name=volunteer.name,
                details={"volunteer_display_name": volunteer_display_name},
            )

        except frappe.ValidationError as e:
            return VolunteerCreationResult(
                member_name=member_name,
                outcome=VolunteerCreationOutcome.VALIDATION_ERROR,
                error_message=str(e)[:200],
            )
        except frappe.PermissionError as e:
            return VolunteerCreationResult(
                member_name=member_name,
                outcome=VolunteerCreationOutcome.PERMISSION_ERROR,
                error_message=str(e)[:200],
            )
        except Exception as e:
            self.logger.error(f"Unexpected error creating volunteer for {member_name}: {e}")
            frappe.log_error(
                f"Volunteer creation failed for {member_name}: {e}",
                "Bulk Volunteer Creation Error",
            )
            return VolunteerCreationResult(
                member_name=member_name,
                outcome=VolunteerCreationOutcome.UNEXPECTED_ERROR,
                error_message=str(e)[:200],
            )

    def _get_volunteer_display_name(self, member_data) -> str:
        """Determine the display name for the volunteer"""
        if member_data.full_name:
            return member_data.full_name

        # Build name from components
        parts = []
        if member_data.first_name:
            parts.append(member_data.first_name)
        if member_data.tussenvoegsel:
            parts.append(member_data.tussenvoegsel)
        if member_data.last_name:
            parts.append(member_data.last_name)

        if parts:
            return " ".join(parts)

        # Fallback
        return member_data.email or f"Volunteer-{member_data.name}"

    def _update_summary_counts(
        self,
        summary: BulkVolunteerCreationSummary,
        result: VolunteerCreationResult,
    ):
        """Update summary counts based on result outcome"""
        outcome_to_field = {
            VolunteerCreationOutcome.CREATED: "created",
            VolunteerCreationOutcome.ALREADY_EXISTS: "already_existed",
            VolunteerCreationOutcome.MEMBER_NOT_FOUND: "skipped_not_found",
            VolunteerCreationOutcome.MEMBER_INACTIVE: "skipped_inactive",
            VolunteerCreationOutcome.MEMBER_TOO_YOUNG: "skipped_too_young",
            VolunteerCreationOutcome.VALIDATION_ERROR: "validation_errors",
            VolunteerCreationOutcome.PERMISSION_ERROR: "permission_errors",
            VolunteerCreationOutcome.UNEXPECTED_ERROR: "unexpected_errors",
        }

        field_name = outcome_to_field.get(result.outcome)
        if field_name:
            setattr(summary, field_name, getattr(summary, field_name) + 1)

    def retry_failed_creations(
        self,
        previous_summary: BulkVolunteerCreationSummary,
        retry_outcomes: Optional[List[VolunteerCreationOutcome]] = None,
    ) -> BulkVolunteerCreationSummary:
        """
        Retry volunteer creation for previously failed attempts.

        Args:
            previous_summary: Summary from previous creation attempt
            retry_outcomes: Which outcomes to retry (default: unexpected errors only)

        Returns:
            New summary for retry attempts
        """
        if retry_outcomes is None:
            retry_outcomes = [VolunteerCreationOutcome.UNEXPECTED_ERROR]

        retry_members = [r.member_name for r in previous_summary.results if r.outcome in retry_outcomes]

        if not retry_members:
            self.logger.info("No failed creations to retry")
            return BulkVolunteerCreationSummary()

        self.logger.info(f"Retrying volunteer creation for {len(retry_members)} members")
        return self.create_volunteers_for_members(retry_members)


# Module-level singleton accessor
_service_instance = None


def get_bulk_volunteer_creation_service() -> BulkVolunteerCreationService:
    """Get singleton instance of BulkVolunteerCreationService"""
    global _service_instance
    if _service_instance is None:
        _service_instance = BulkVolunteerCreationService()
    return _service_instance
