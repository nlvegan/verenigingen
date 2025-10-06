"""
CSV Data Validator

Business rule validation for CSV import data. Validates email formats, IBAN checksums,
birth dates, and other member data before import processing.

Extracted from MijnroodCSVImport to improve testability and reusability.
"""

import re
from typing import Any, Dict, List, Tuple

import frappe
from frappe.utils import getdate, today

from verenigingen.utils.csv.data_transformers import clean_value


class CSVDataValidator:
    """
    Validates CSV data against business rules before import.

    Features:
    - Field mapping from Dutch CSV headers to Member DocType fields
    - RFC-compliant email validation
    - MOD-97 IBAN checksum validation
    - Birth date reasonableness checks
    - Mollie ID format validation
    - Comprehensive error reporting with row numbers
    """

    # Field mapping from Dutch CSV headers to Member DocType fields
    FIELD_MAPPING = {
        "lidnr.": "member_id",
        "lidnr": "member_id",
        "voornaam": "first_name",
        "tussenvoegsel": "tussenvoegsel",
        "middle_name": "tussenvoegsel",  # Import middle_name as tussenvoegsel
        "achternaam": "last_name",
        "geboortedatum": "birth_date",
        "inschrijfdataum": "member_since",
        "groep": "chapter",
        "e-mailadres": "email",
        "email": "email",
        "telefoonnr.": "contact_number",
        "telefoon": "contact_number",
        "adres": "address_line1",
        "plaats": "city",
        "postcode": "postal_code",
        "landcode": "country",
        "iban": "iban",
        "contributiebedrag": "dues_rate",
        "betaalperiode": "payment_period",
        "betaald": "payment_status",
        "mollie cid": "custom_mollie_customer_id",
        "mollie sid": "custom_mollie_subscription_id",
        "privacybeleid geaccepteerd": "privacy_accepted",
        "lidmaatschapstype": "membership_type",
    }

    REQUIRED_FIELDS = ["voornaam", "achternaam"]

    def validate_and_map_data(self, csv_data: List[Dict]) -> Tuple[List[Dict], List[str]]:
        """
        Validate CSV data and map to Member fields.

        Args:
            csv_data: List of dictionaries from CSV parser

        Returns:
            Tuple of (mapped_data, validation_errors)
            - mapped_data: List of validated and mapped rows
            - validation_errors: List of error messages (limited to 100)

        Raises:
            None - all errors are returned in validation_errors list
        """
        if not csv_data:
            return [], ["CSV file is empty"]

        mapped_data = []
        validation_errors = []

        # Check for required headers
        csv_headers = [h.lower().strip() for h in csv_data[0].keys()]
        missing_required = [field for field in self.REQUIRED_FIELDS if field not in csv_headers]

        if missing_required:
            validation_errors.append(f"Missing required columns: {', '.join(missing_required)}")
            return [], validation_errors

        for row_num, row in enumerate(csv_data, start=2):  # Start at 2 for header row
            try:
                mapped_row = self.map_row_data(row, row_num)
                row_errors = self.validate_row(mapped_row, row_num)

                if row_errors:
                    validation_errors.extend(row_errors)
                else:
                    mapped_data.append(mapped_row)

            except Exception as e:
                validation_errors.append(f"Row {row_num}: Error processing row - {str(e)}")

        return mapped_data, validation_errors[:100]  # Limit errors to prevent overflow

    def map_row_data(self, row: Dict, row_num: int) -> Dict:
        """
        Map a single row from CSV to Member fields.

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
                mapped[target_field] = clean_value(value, target_field)

        return mapped

    def validate_row(self, row: Dict, row_num: int) -> List[str]:
        """
        Validate a single row of mapped data with comprehensive checks.

        Args:
            row: Mapped row data
            row_num: Row number for error reporting

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Required fields - be lenient, only check if they exist and are not empty
        if not row.get("first_name") or not str(row.get("first_name", "")).strip():
            errors.append(f"Row {row_num}: First name is required")
        if not row.get("last_name") or not str(row.get("last_name", "")).strip():
            errors.append(f"Row {row_num}: Last name is required")

        # Name length validation
        if row.get("first_name") and len(str(row["first_name"])) > 100:
            errors.append(f"Row {row_num}: First name too long (max 100 characters)")
        if row.get("last_name") and len(str(row["last_name"])) > 100:
            errors.append(f"Row {row_num}: Last name too long (max 100 characters)")

        # Email validation - only validate if provided
        if row.get("email"):
            email = str(row["email"]).strip()
            if email:
                if not self.validate_email(email):
                    errors.append(f"Row {row_num}: Invalid email format: {email}")
                elif len(email) > 320:  # RFC standard email length limit
                    errors.append(f"Row {row_num}: Email too long (max 320 characters): {email}")

        # IBAN validation - only validate if provided and not empty
        if row.get("iban"):
            iban = str(row["iban"]).strip()
            if iban and not self.validate_iban(iban):
                errors.append(f"Row {row_num}: Invalid IBAN format: {iban}")

        # Birth date validation - only validate if provided
        if row.get("birth_date"):
            birth_date_str = str(row["birth_date"]).strip()
            if birth_date_str:
                try:
                    birth_date = getdate(birth_date_str)
                    if birth_date > getdate(today()):
                        errors.append(f"Row {row_num}: Birth date cannot be in the future: {birth_date_str}")
                    # Check for reasonable minimum age (e.g., not over 150 years old)
                    from dateutil.relativedelta import relativedelta

                    age = relativedelta(getdate(today()), birth_date).years
                    if age > 150:
                        errors.append(
                            f"Row {row_num}: Birth date seems unrealistic (age {age}): {birth_date_str}"
                        )
                except (ValueError, TypeError, frappe.ValidationError):
                    errors.append(f"Row {row_num}: Invalid birth date format: {birth_date_str}")

        # Contact number validation
        if row.get("contact_number"):
            contact = str(row["contact_number"]).strip()
            if contact and len(contact) > 50:
                errors.append(f"Row {row_num}: Contact number too long (max 50 characters)")

        # Dues rate validation
        if row.get("dues_rate"):
            try:
                dues = float(row["dues_rate"])
                if dues < 0:
                    errors.append(f"Row {row_num}: Dues rate cannot be negative: {dues}")
                elif dues > 10000:  # Reasonable maximum
                    errors.append(f"Row {row_num}: Dues rate seems unrealistic (over €10,000): {dues}")
            except (ValueError, TypeError):
                errors.append(f"Row {row_num}: Invalid dues rate format: {row['dues_rate']}")

        # Mollie ID format validation
        if row.get("custom_mollie_customer_id"):
            mollie_cid = str(row["custom_mollie_customer_id"]).strip()
            if mollie_cid and not mollie_cid.startswith("cst_"):
                errors.append(f"Row {row_num}: Mollie Customer ID should start with 'cst_': {mollie_cid}")

        if row.get("custom_mollie_subscription_id"):
            mollie_sid = str(row["custom_mollie_subscription_id"]).strip()
            if mollie_sid and not mollie_sid.startswith("sub_"):
                errors.append(f"Row {row_num}: Mollie Subscription ID should start with 'sub_': {mollie_sid}")

        return errors

    def validate_email(self, email: str) -> bool:
        """
        Validate email format with comprehensive RFC-compliant checks.

        Args:
            email: Email address to validate

        Returns:
            True if valid, False otherwise

        Validation Rules:
        - Maximum 320 characters total (RFC 5321)
        - Local part maximum 64 characters
        - Domain part maximum 255 characters
        - No consecutive dots
        - Valid domain structure (at least 2 parts)
        - Each DNS label maximum 63 characters
        """
        if not email or len(email) > 320:  # RFC 5321 limit
            return False

        # Enhanced email pattern
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"

        # Basic pattern check
        if not re.match(email_pattern, email):
            return False

        # Additional validations
        local_part, domain = email.rsplit("@", 1)

        # Local part validation
        if len(local_part) > 64:  # RFC 5321 limit
            return False

        # Domain part validation
        if len(domain) > 255:  # RFC 5321 limit
            return False

        # Check for consecutive dots
        if ".." in email:
            return False

        # Check for valid domain structure
        domain_parts = domain.split(".")
        if len(domain_parts) < 2:
            return False

        for part in domain_parts:
            if not part or len(part) > 63:  # DNS label limit
                return False

        return True

    def validate_iban(self, iban: str) -> bool:
        """
        Enhanced IBAN validation with MOD-97 checksum (ISO 13616).

        Args:
            iban: IBAN number to validate

        Returns:
            True if valid IBAN with correct checksum, False otherwise

        Validation Rules:
        - Length between 15-34 characters
        - Starts with 2-letter country code
        - Positions 3-4 are check digits
        - Remaining characters are alphanumeric
        - MOD-97 checksum must equal 1

        Example:
            NL91ABNA0417164300 → True (valid Dutch IBAN)
            NL00ABNA0417164300 → False (invalid checksum)
        """
        if not iban:
            return False

        # Remove spaces and convert to uppercase
        iban = re.sub(r"\s+", "", iban.upper())

        # Check length (minimum 15, maximum 34)
        if len(iban) < 15 or len(iban) > 34:
            return False

        # Check if starts with country code (2 letters)
        if not iban[:2].isalpha():
            return False

        # Check if positions 3-4 are digits (check digits)
        if not iban[2:4].isdigit():
            return False

        # Check remaining characters are alphanumeric
        if not iban[4:].isalnum():
            return False

        # Perform MOD-97 validation (ISO 13616)
        try:
            # Move first 4 characters to end
            rearranged = iban[4:] + iban[:4]

            # Replace letters with numbers (A=10, B=11, ..., Z=35)
            numeric_string = ""
            for char in rearranged:
                if char.isdigit():
                    numeric_string += char
                else:
                    numeric_string += str(ord(char) - ord("A") + 10)

            # Check if MOD 97 equals 1
            return int(numeric_string) % 97 == 1
        except (ValueError, OverflowError):
            return False
