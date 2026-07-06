"""
VIP Data Validator

Business rule validation for Volunteer Information Portal (VIP) CSV imports.
Validates and maps VIP export data to Volunteer and Member fields.

VIP is a custom Django application managing Google Workspace accounts and volunteer data.
This validator handles one-time imports before API bridging is established.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from frappe.utils import getdate, today

from verenigingen.utils.csv.data_transformers import clean_phone_number, parse_date


class VIPDataValidator:
    """
    Validates and maps VIP CSV data for volunteer import.

    Features:
    - Field mapping from VIP export columns to Volunteer/Member fields
    - Status mapping from VIP statuses to Volunteer statuses
    - Delegated account detection (shared inboxes to skip)
    - Email format validation
    - Comprehensive error reporting with row numbers
    """

    # Field mapping from VIP CSV columns to internal fields
    # Keys are lowercase for case-insensitive matching
    FIELD_MAPPING = {
        # Primary identifiers
        "id": "vip_user_id",
        "google_account_ref": "google_workspace_id",
        "nvv_relatie_nummer": "member_id",
        "procurios_id": "procurios_id",  # Alternate member ID source
        # Emails
        "email": "organization_email",
        "private_email": "personal_email",
        # Names
        "first_name": "first_name",
        "last_name": "last_name",
        "username": "username",  # Stored but not used directly
        # Contact
        "phone_number": "phone_number",
        "mobile_number": "mobile_number",
        # Dates and status
        "date_joined": "start_date",
        "status": "vip_status",
        "status_notes": "status_notes",
        "is_active": "is_active",
        # Notes
        "notes": "notes",
        # Flags (for filtering, not direct mapping)
        "is_delegated_account": "is_delegated_account",
        "is_board_member": "is_board_member",
        "is_employee": "is_employee",
        "is_staff": "is_staff",
        # Skipped fields (mapped but not used)
        "groups": "groups",
        "user_permissions": "user_permissions",
        "welcome_email_sent": "welcome_email_sent",
    }

    # Status mapping from VIP status values to Volunteer status
    STATUS_MAPPING = {
        "available": "Active",
        "holiday": "Inactive",
        "break": "Inactive",
        "unavailable": "Retired",
        "quit": "Retired",
    }

    # Fields that are required for a valid import row
    REQUIRED_FIELDS = []  # VIP imports are lenient - we match existing records

    # Fields that indicate the row should be skipped
    SKIP_INDICATORS = ["is_delegated_account"]

    def validate_and_map_data(
        self, csv_data: List[Dict], skip_delegated: bool = True
    ) -> Tuple[List[Dict], List[str], List[str]]:
        """
        Validate CSV data and map to internal fields.

        Args:
            csv_data: List of dictionaries from CSV parser
            skip_delegated: If True, skip rows where is_delegated_account is truthy

        Returns:
            Tuple of (mapped_data, validation_errors, skipped_reasons)
            - mapped_data: List of validated and mapped rows
            - validation_errors: List of error messages (limited to 100)
            - skipped_reasons: List of reasons rows were skipped (limited to 100)
        """
        if not csv_data:
            return [], ["CSV file is empty"], []

        mapped_data = []
        validation_errors = []
        skipped_reasons = []

        for row_num, row in enumerate(csv_data, start=2):  # Start at 2 for header row
            try:
                mapped_row = self.map_row_data(row, row_num)

                # Check for delegated accounts (shared inboxes)
                if skip_delegated and self._is_delegated_account(mapped_row):
                    skipped_reasons.append(
                        f"Row {row_num}: Skipped delegated account "
                        f"({mapped_row.get('organization_email', 'unknown')})"
                    )
                    continue

                # Validate the row
                row_errors = self.validate_row(mapped_row, row_num)

                if row_errors:
                    validation_errors.extend(row_errors)
                else:
                    # Map status from VIP to Volunteer status
                    mapped_row["volunteer_status"] = self.map_status(
                        mapped_row.get("vip_status"), mapped_row.get("is_active")
                    )

                    # Determine preferred phone number (mobile > landline)
                    mapped_row["contact_number"] = self._get_preferred_phone(mapped_row)

                    mapped_data.append(mapped_row)

            except Exception as e:
                validation_errors.append(f"Row {row_num}: Error processing row - {str(e)}")

        return (
            mapped_data,
            validation_errors[:100],
            skipped_reasons[:100],
        )

    def map_row_data(self, row: Dict, row_num: int) -> Dict:
        """
        Map a single row from CSV to internal field names.

        Args:
            row: Dictionary of CSV row data
            row_num: Row number for error reporting

        Returns:
            Dictionary with mapped field names and cleaned values
        """
        mapped = {"row_number": row_num}

        for csv_field, value in row.items():
            clean_field = csv_field.lower().strip()
            if clean_field in self.FIELD_MAPPING:
                target_field = self.FIELD_MAPPING[clean_field]
                mapped[target_field] = self._clean_value(value, target_field)

        return mapped

    def _clean_value(self, value: Any, field_name: str) -> Any:
        """
        Clean and normalize a value based on field type.

        Args:
            value: Raw value from CSV
            field_name: Target field name for type-specific cleaning

        Returns:
            Cleaned value
        """
        if value is None:
            return None

        # Convert to string and strip whitespace
        str_value = str(value).strip()
        if not str_value:
            return None

        # Boolean fields
        if field_name in [
            "is_delegated_account",
            "is_board_member",
            "is_employee",
            "is_staff",
            "is_active",
            "welcome_email_sent",
        ]:
            return self._parse_boolean(str_value)

        # Phone number fields
        if field_name in ["phone_number", "mobile_number"]:
            return clean_phone_number(str_value)

        # Date fields
        if field_name == "start_date":
            return self._parse_date(str_value)

        # Email fields - lowercase
        if field_name in ["organization_email", "personal_email"]:
            return str_value.lower()

        # Status field - lowercase for mapping
        if field_name == "vip_status":
            return str_value.lower()

        return str_value

    def _parse_boolean(self, value: str) -> bool:
        """Parse boolean value from various string representations."""
        if not value:
            return False
        return value.lower() in ["true", "1", "yes", "ja", "t", "y"]

    def _parse_date(self, value: str) -> Optional[str]:
        """
        Parse a VIP date to YYYY-MM-DD format.

        Delegates to the shared parse_date helper so VIP dates parse
        identically to the other CSV importers: getdate handles ISO,
        slash- and dot-separated formats, and ambiguous DD-MM values are
        read day-first (European). Previously this method had its own
        getdate-then-strptime fallback that defaulted ambiguous dates to
        month-first (e.g. "12-03-1965" -> 3 December instead of 12 March).

        Args:
            value: Date string in various formats

        Returns:
            Date string in YYYY-MM-DD format or None if invalid
        """
        return parse_date(value)

    def _is_delegated_account(self, row: Dict) -> bool:
        """
        Check if row represents a delegated/shared account.

        Args:
            row: Mapped row data

        Returns:
            True if this is a delegated account that should be skipped
        """
        return bool(row.get("is_delegated_account"))

    def map_status(self, vip_status: Optional[str], is_active: Optional[bool] = None) -> str:
        """
        Map VIP status to Volunteer status.

        Args:
            vip_status: Status value from VIP (available/holiday/break/unavailable/quit)
            is_active: Optional is_active flag (used as fallback)

        Returns:
            Volunteer status string (New/Onboarding/Active/Inactive/Retired)
        """
        if vip_status:
            status = vip_status.lower().strip()
            if status in self.STATUS_MAPPING:
                return self.STATUS_MAPPING[status]

        # Fallback to is_active flag
        if is_active is not None:
            return "Active" if is_active else "Inactive"

        # Default to Active if no status information
        return "Active"

    def _get_preferred_phone(self, row: Dict) -> Optional[str]:
        """
        Get preferred phone number (mobile preferred over landline).

        Args:
            row: Mapped row data

        Returns:
            Best available phone number or None
        """
        return row.get("mobile_number") or row.get("phone_number")

    def validate_row(self, row: Dict, row_num: int) -> List[str]:
        """
        Validate a single row of mapped data.

        Args:
            row: Mapped row data
            row_num: Row number for error reporting

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Check for at least one identifier (member_id or email)
        has_member_id = bool(row.get("member_id"))
        has_org_email = bool(row.get("organization_email"))
        has_personal_email = bool(row.get("personal_email"))

        if not has_member_id and not has_org_email and not has_personal_email:
            errors.append(f"Row {row_num}: No identifier found - need member_id, email, or private_email")

        # Validate organization email format if provided
        if row.get("organization_email"):
            email = row["organization_email"]
            if not self._validate_email(email):
                errors.append(f"Row {row_num}: Invalid organization email format: {email}")

        # Validate personal email format if provided
        if row.get("personal_email"):
            email = row["personal_email"]
            if not self._validate_email(email):
                errors.append(f"Row {row_num}: Invalid personal email format: {email}")

        # Validate start_date is not in the future
        if row.get("start_date"):
            try:
                start_date = getdate(row["start_date"])
                if start_date > getdate(today()):
                    errors.append(f"Row {row_num}: Start date cannot be in the future: {row['start_date']}")
            except Exception:
                errors.append(f"Row {row_num}: Invalid start date format: {row['start_date']}")

        # Validate VIP status is recognized
        if row.get("vip_status"):
            status = row["vip_status"].lower().strip()
            if status and status not in self.STATUS_MAPPING:
                # Just a warning, not an error - we'll default to Active
                pass  # Silently use default

        return errors

    def _validate_email(self, email: str) -> bool:
        """
        Validate email format using Frappe's built-in validation.

        Args:
            email: Email address to validate

        Returns:
            True if valid, False otherwise
        """
        if not email or len(email) > 320:
            return False

        try:
            # Use Frappe's built-in email validation
            from frappe.utils import validate_email_address

            return validate_email_address(email, throw=False)
        except Exception:
            # Fallback to basic regex if Frappe validation unavailable
            email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
            if not re.match(email_pattern, email):
                return False
            if ".." in email:
                return False
            return True

    def get_preview_summary(self, csv_data: List[Dict]) -> Dict[str, Any]:
        """
        Generate a preview summary of the import data.

        Args:
            csv_data: Raw CSV data

        Returns:
            Dictionary with summary statistics
        """
        mapped_data, errors, skipped = self.validate_and_map_data(csv_data)

        # Count by status
        status_counts = {}
        for row in mapped_data:
            status = row.get("volunteer_status", "Unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

        # Count identifiers
        with_member_id = sum(1 for r in mapped_data if r.get("member_id"))
        with_org_email = sum(1 for r in mapped_data if r.get("organization_email"))
        with_personal_email = sum(1 for r in mapped_data if r.get("personal_email"))

        return {
            "total_rows": len(csv_data),
            "valid_rows": len(mapped_data),
            "error_rows": len(errors),
            "skipped_rows": len(skipped),
            "status_breakdown": status_counts,
            "with_member_id": with_member_id,
            "with_organization_email": with_org_email,
            "with_personal_email": with_personal_email,
            "sample_errors": errors[:5],
            "sample_skipped": skipped[:5],
        }
