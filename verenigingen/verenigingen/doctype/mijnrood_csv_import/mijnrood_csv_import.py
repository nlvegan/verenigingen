# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import csv
import io
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr, flt, getdate, today

from verenigingen.utils.member_account_service import bulk_create_user_accounts

try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


class MijnroodCSVImport(Document):
    """DocType for importing member data from CSV files with validation and preview."""

    def validate(self):
        """Validate the document before saving."""
        # Only do basic validation - no file processing
        if not getattr(self, "import_date", None):
            self.import_date = today()

        # Skip automatic CSV validation - make it manual only
        pass

    def on_submit(self):
        """Process the CSV import when document is submitted."""
        if not self.test_mode:
            self._process_import()
        else:
            frappe.msgprint(_("Import completed in test mode. No records were created."))

    def _validate_and_preview_csv(self):
        """Validate CSV file and prepare preview data."""
        try:
            # Read and parse CSV
            csv_data = self._read_csv_file()
            if not csv_data:
                frappe.throw(_("Could not read CSV file or file is empty"))

            # Validate and map fields
            mapped_data, validation_errors = self._validate_and_map_data(csv_data)

            # Set preview data and status
            if validation_errors:
                self.import_status = "Failed"
                self.error_log = "\\n".join(validation_errors)
                frappe.throw(_("CSV validation failed. Check Error Log for details."))
            else:
                self.import_status = "Ready for Import"
                self.preview_data = json.dumps(mapped_data[:5], indent=2, default=str)  # Show first 5 records
                self.descriptive_name = f"Member Import {self.import_date} ({len(mapped_data)} records)"

        except Exception as e:
            self.import_status = "Failed"
            error_msg = str(e)[:500]  # Limit error message length
            self.error_log = f"Validation Error: {error_msg}"
            # Use shorter log title
            frappe.log_error(error_msg, "CSV Import Failed")
            frappe.throw(_("CSV validation failed: {0}").format(error_msg))

    def _read_csv_file(self) -> List[Dict]:
        """Read CSV file and return parsed data."""
        if not self.csv_file:
            return []

        try:
            filename = self._sanitize_filename()
            file_path, file_content = self._resolve_file_location(filename)
            return self._parse_file_data(file_path, file_content, filename)

        except UnicodeDecodeError:
            frappe.throw(
                _("File encoding error. Please check the encoding setting or try a different encoding.")
            )
        except Exception as e:
            frappe.log_error(f"CSV file reading error: {str(e)}")
            frappe.throw(_("Error reading CSV file: {0}").format(str(e)))

    def _sanitize_filename(self) -> str:
        """Sanitize filename to prevent security issues."""
        raw_filename = self.csv_file.split("/")[-1] if "/" in self.csv_file else self.csv_file
        filename = os.path.basename(raw_filename)  # Prevent path traversal
        filename = re.sub(r"[^\w\-_\.]", "_", filename)  # Sanitize filename

        # Validate file extension for security
        if not filename.lower().endswith((".csv", ".xlsx", ".xls")):
            frappe.throw(_("Only CSV and Excel files are allowed. File: {0}").format(filename))

        return filename

    def _resolve_file_location(self, filename: str) -> Tuple[Optional[str], Optional[bytes]]:
        """Resolve file location using multiple methods."""
        file_path, file_content = self._try_file_document_lookup(filename)

        if not file_path or not os.path.exists(file_path):
            file_path = self._try_direct_path_construction(filename)

        if not file_path and not file_content:
            self._handle_file_not_found(filename)

        return file_path, file_content

    def _try_file_document_lookup(self, filename: str) -> Tuple[Optional[str], Optional[bytes]]:
        """Try to find file via Frappe File document lookup."""
        file_path = None
        file_content = None

        # Method 1: Try to get File document by file_url
        try:
            file_doc = frappe.get_doc("File", {"file_url": self.csv_file})
            if file_doc:
                file_path = file_doc.get_full_path()
                if hasattr(file_doc, "get_content"):
                    file_content = file_doc.get_content()
        except (frappe.DoesNotExistError, Exception):
            pass

        # Method 2: Try to find by sanitized file name
        if not file_path:
            try:
                file_doc = frappe.get_doc("File", {"file_name": filename})
                if file_doc:
                    file_path = file_doc.get_full_path()
                    if hasattr(file_doc, "get_content"):
                        file_content = file_doc.get_content()
            except (frappe.DoesNotExistError, Exception):
                pass

        return file_path, file_content

    def _try_direct_path_construction(self, filename: str) -> Optional[str]:
        """Try to construct file path directly using common locations."""
        possible_paths = [
            frappe.get_site_path("public", "files", filename),
            frappe.get_site_path("private", "files", filename),
            os.path.join(frappe.get_site_path(), "public", "files", filename),
            os.path.join(frappe.get_site_path(), "private", "files", filename),
        ]

        for path in possible_paths:
            if os.path.exists(path) and self._is_safe_file_path(path):
                return path

        return None

    def _handle_file_not_found(self, filename: str):
        """Handle file not found scenario with helpful debug information."""
        files = frappe.get_all(
            "File",
            fields=["name", "file_name", "file_url", "is_private"],
            filters=[["file_name", "like", f"%{filename}%"]],
        )

        debug_info = f"File URL: {self.csv_file}\n"
        debug_info += f"Looking for filename: {filename}\n"
        if files:
            debug_info += f"Found {len(files)} similar files:\n"
            for f in files[:5]:  # Show max 5 files
                debug_info += f"  - {f.file_name} ({f.file_url})\n"
        else:
            debug_info += "No files found in database.\n"

        frappe.throw(_("File not found. {0}").format(debug_info))

    def _parse_file_data(
        self, file_path: Optional[str], file_content: Optional[bytes], filename: str
    ) -> List[Dict]:
        """Parse file data based on available file path or content."""
        if file_path and os.path.exists(file_path):
            return self._read_file_from_path(file_path)
        elif file_content:
            return self._read_file_from_content(file_content, filename)
        else:
            frappe.throw(_("Could not access file content. File path: {0}").format(file_path))

    def _is_safe_file_path(self, file_path: str) -> bool:
        """Check if file path is within allowed directories for security."""
        try:
            # Get absolute path and resolve any symlinks
            abs_path = os.path.abspath(os.path.realpath(file_path))
            site_path = os.path.abspath(frappe.get_site_path())

            # Ensure file is within site directory structure
            return abs_path.startswith(site_path)
        except Exception:
            return False

    def _read_file_from_path(self, file_path: str) -> List[Dict]:
        """Read file from file system path."""
        # Handle Excel files if pandas is available
        if file_path.lower().endswith(".xlsx") or file_path.lower().endswith(".xls"):
            if not PANDAS_AVAILABLE:
                frappe.throw(
                    _(
                        "Excel files require pandas library. Please install pandas or convert to CSV format first."
                    )
                )

            try:
                # Read Excel file using pandas
                df = pd.read_excel(
                    file_path, engine="openpyxl" if file_path.lower().endswith(".xlsx") else None
                )
                # Convert to list of dictionaries and remove empty rows
                records = df.to_dict("records")
                return [
                    record
                    for record in records
                    if any(str(v).strip() for v in record.values() if v is not None)
                ]
            except Exception as e:
                frappe.throw(
                    _("Error reading Excel file: {0}. Please try converting to CSV format.").format(str(e))
                )

        # Read and parse CSV with BOM handling
        try:
            # Try UTF-8 with BOM first
            encodings_to_try = ["utf-8-sig", "utf-8", "iso-8859-1", "windows-1252"]

            for encoding in encodings_to_try:
                try:
                    with open(file_path, "r", encoding=encoding) as csvfile:
                        return self._parse_csv_content(csvfile)
                except UnicodeDecodeError:
                    continue
                except Exception as e:
                    # If it's not an encoding issue, re-raise
                    if "codec" not in str(e).lower():
                        raise
                    continue

            frappe.throw(_("Could not read file with any supported encoding. Please check file format."))

        except Exception as e:
            frappe.throw(_("Error reading CSV file: {0}").format(str(e)))

    def _read_file_from_content(self, file_content: bytes, filename: str) -> List[Dict]:
        """Read file from content bytes."""
        # Handle Excel files if pandas is available
        if filename.lower().endswith(".xlsx") or filename.lower().endswith(".xls"):
            if not PANDAS_AVAILABLE:
                frappe.throw(
                    _(
                        "Excel files require pandas library. Please install pandas or convert to CSV format first."
                    )
                )

            try:
                # Read Excel file using pandas from bytes
                df = pd.read_excel(
                    io.BytesIO(file_content),
                    engine="openpyxl" if filename.lower().endswith(".xlsx") else None,
                )
                # Convert to list of dictionaries
                return df.to_dict("records")
            except Exception as e:
                frappe.throw(
                    _("Error reading Excel file: {0}. Please try converting to CSV format.").format(str(e))
                )

        # Read and parse CSV from content
        try:
            # Decode content to string
            content_str = file_content.decode(self.encoding or "utf-8")
            csvfile = io.StringIO(content_str)
            return self._parse_csv_content(csvfile)
        except UnicodeDecodeError:
            frappe.throw(
                _("File encoding error. Please check the encoding setting or try a different encoding.")
            )

    def _parse_csv_content(self, csvfile) -> List[Dict]:
        """Parse CSV content from file-like object."""
        # Try to detect delimiter, with fallback to common delimiters
        sample = csvfile.read(1024)
        csvfile.seek(0)

        data = []
        reader = None

        # Try to detect delimiter
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            reader = csv.DictReader(csvfile, dialect=dialect)
            data = list(reader)
        except csv.Error:
            # Fallback: try common delimiters one by one
            csvfile.seek(0)
            for delimiter in [",", ";", "\t"]:
                try:
                    csvfile.seek(0)
                    reader = csv.DictReader(csvfile, delimiter=delimiter)
                    # Test if we can read at least one row
                    first_row = next(reader, None)
                    if first_row and len(first_row) > 1:  # At least 2 columns
                        csvfile.seek(0)
                        reader = csv.DictReader(csvfile, delimiter=delimiter)
                        data = [first_row] + list(reader)
                        break
                except Exception:
                    continue

            if not data:
                # If all delimiters fail, throw error
                frappe.throw(
                    _(
                        "Could not determine CSV delimiter. Please ensure your file uses comma (,), semicolon (;), or tab delimiters."
                    )
                )

        # Filter out completely empty rows
        filtered_data = []
        for row in data:
            # Check if row has any meaningful data
            has_data = any(
                value
                and str(value).strip()
                and str(value).strip() != "-"
                and str(value).strip().lower() != "nb"
                for value in row.values()
            )
            if has_data:
                # Clean up the row data
                cleaned_row = {}
                for key, value in row.items():
                    if (
                        value is None
                        or str(value).strip() == ""
                        or str(value).strip() == "-"
                        or str(value).strip().lower() == "nb"
                    ):
                        cleaned_row[key] = None
                    else:
                        cleaned_row[key] = str(value).strip()
                filtered_data.append(cleaned_row)

        return filtered_data

    def _validate_and_map_data(self, csv_data: List[Dict]) -> Tuple[List[Dict], List[str]]:
        """Validate CSV data and map to Member fields."""
        if not csv_data:
            return [], ["CSV file is empty"]

        # Field mapping from Dutch CSV headers to Member fields
        field_mapping = {
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

        mapped_data = []
        validation_errors = []

        # Check for required headers
        csv_headers = [h.lower().strip() for h in csv_data[0].keys()]
        required_fields = ["voornaam", "achternaam"]
        missing_required = [field for field in required_fields if field not in csv_headers]

        if missing_required:
            validation_errors.append(f"Missing required columns: {', '.join(missing_required)}")
            return [], validation_errors

        for row_num, row in enumerate(csv_data, start=2):  # Start at 2 for header row
            try:
                mapped_row = self._map_row_data(row, field_mapping, row_num)
                row_errors = self._validate_row(mapped_row, row_num)

                if row_errors:
                    validation_errors.extend(row_errors)
                else:
                    mapped_data.append(mapped_row)

            except Exception as e:
                validation_errors.append(f"Row {row_num}: Error processing row - {str(e)}")

        return mapped_data, validation_errors[:100]  # Limit errors to prevent overflow

    def _map_row_data(self, row: Dict, field_mapping: Dict, row_num: int) -> Dict:
        """Map a single row from CSV to Member fields."""
        mapped = {"row_number": row_num}

        for csv_field, value in row.items():
            clean_field = csv_field.lower().strip()
            if clean_field in field_mapping:
                target_field = field_mapping[clean_field]
                mapped[target_field] = self._clean_value(value, target_field)

        return mapped

    def _clean_value(self, value: str, field_type: str) -> Any:
        """Clean and convert values based on field type."""
        if not value or value.strip() == "":
            return None

        value = value.strip()

        # Handle common "no data" indicators - convert to None
        if value in ["-", "N/A", "n/a", "N.A.", "n.a.", "NULL", "null", "UNKNOWN", "unknown", "?"]:
            return None

        # SECURITY: Prevent CSV injection attacks - reject dangerous content
        if value.startswith(("=", "+", "@", "\t", "\r")) or (value.startswith("-") and len(value) > 1):
            frappe.throw(
                _(
                    "Security: Field contains potentially dangerous content that could be interpreted as formula: {0}"
                ).format(value[:50])
            )

        # SECURITY: Limit field length to prevent memory issues
        if len(value) > 2000:  # Reasonable limit for most fields
            frappe.throw(_("Field value too long (max 2000 characters): {0}").format(value[:50] + "..."))

        # Date fields
        if field_type in ["birth_date", "member_since"]:
            return self._parse_date(value)

        # Currency fields
        elif field_type in ["dues_rate"]:
            return flt(re.sub(r"[^\d.,]", "", value).replace(",", "."))

        # Boolean fields
        elif field_type in ["privacy_accepted"]:
            return value.lower() in ["ja", "yes", "1", "true", "waar"]

        # IBAN cleaning - FIXED REGEX
        elif field_type == "iban":
            return re.sub(r"\s+", "", value.upper())

        # Email cleaning
        elif field_type == "email":
            return value.lower()

        # Phone number cleaning
        elif field_type == "contact_number":
            return self._clean_phone_number(value)

        # Country code conversion
        elif field_type == "country":
            return self._convert_country_code(value)

        # Membership type conversion
        elif field_type == "membership_type":
            return self._convert_membership_type(value)

        return cstr(value)

    def _convert_country_code(self, country_code: str) -> str:
        """Convert country codes to full country names."""
        country_mapping = {
            "NL": "Netherlands",
            "BE": "Belgium",
            "DE": "Germany",
            "FR": "France",
            "ES": "Spain",
            "IT": "Italy",
            "SE": "Sweden",
            "NO": "Norway",
            "DK": "Denmark",
            "FI": "Finland",
            "AT": "Austria",
            "CH": "Switzerland",
            "LU": "Luxembourg",
            "GB": "United Kingdom",
            "UK": "United Kingdom",
            "US": "United States",
            "CA": "Canada",
            "AU": "Australia",
        }

        code = country_code.upper().strip()
        return country_mapping.get(code, country_code)  # Return original if not found

    def _clean_phone_number(self, phone_number: str) -> str:
        """Clean and normalize phone number format for validation compatibility."""
        if not phone_number:
            return ""

        # Remove extra whitespace
        phone = phone_number.strip()

        # Step 1: Normalize common formats
        if phone.startswith("+"):
            # Remove spaces in international numbers but keep the + prefix
            phone = "+" + "".join(phone[1:].split())
        else:
            # For non-international numbers, just remove spaces and dashes
            phone = "".join(phone.split()).replace("-", "")

        # Step 2: Apply Dutch-specific normalization rules
        if phone.startswith("+316") and len(phone) == 12:  # Dutch mobile
            # Convert to national format for better compatibility
            phone = "0" + phone[3:]  # +31612345678 → 0612345678
        elif phone.startswith("+3120") or phone.startswith("+3130"):  # Dutch landline
            # Convert to national format
            phone = "0" + phone[3:]  # +31201234567 → 0201234567

        # Step 3: Validate length and format for Dutch numbers
        if phone.startswith("06") and len(phone) == 10:  # Dutch mobile
            return phone
        elif phone.startswith("0") and len(phone) >= 9 and len(phone) <= 10:  # Dutch landline
            return phone
        elif phone.startswith("+") and len(phone) >= 10 and len(phone) <= 15:  # International
            return phone
        else:
            # Invalid format - return empty string to skip this field
            frappe.logger().warning(f"Invalid phone number format during CSV import: {phone_number}")
            return ""

    def _convert_membership_type(self, membership_type: str) -> str:
        """Convert Dutch membership types to standardized values."""
        type_mapping = {
            "lid": "Standard",  # Regular member
            "aspirant": "Aspirant",  # Candidate/provisional member
            "uitgeschreven": "Terminated",  # Unsubscribed/left voluntarily
            "opgezegd": "Terminated",  # Cancelled/terminated
            "geroyeerd": "Expelled",  # Expelled/removed for cause
            "geschorst": "Suspended",  # Suspended
        }

        type_value = membership_type.lower().strip() if membership_type else ""
        return type_mapping.get(type_value, membership_type)  # Return original if not found

    def _parse_date(self, date_str: str) -> Optional[str]:
        """Parse date string to YYYY-MM-DD format."""
        if not date_str:
            return None

        # Try different date formats
        formats = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"]

        for fmt in formats:
            try:
                return getdate(date_str).strftime("%Y-%m-%d")
            except:
                continue

        return None

    def _validate_row(self, row: Dict, row_num: int) -> List[str]:
        """Validate a single row of mapped data with comprehensive checks."""
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
                if not self._is_valid_email(email):
                    errors.append(f"Row {row_num}: Invalid email format: {email}")
                elif len(email) > 320:  # RFC standard email length limit
                    errors.append(f"Row {row_num}: Email too long (max 320 characters): {email}")

        # IBAN validation - only validate if provided and not empty
        if row.get("iban"):
            iban = str(row["iban"]).strip()
            if iban and not self._is_valid_iban(iban):
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
                except Exception:
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

    def _is_valid_email(self, email: str) -> bool:
        """Validate email format with comprehensive checks."""
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

    def _is_valid_iban(self, iban: str) -> bool:
        """Enhanced IBAN validation with mod-97 check."""
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

    def _process_import(self):
        """Process the actual import of member data with transaction safety."""
        try:
            # Update status first
            self.import_status = "In Progress"
            self.save()
            frappe.db.commit()

            # Read and validate CSV again
            csv_data = self._read_csv_file()
            mapped_data, validation_errors = self._validate_and_map_data(csv_data)

            if validation_errors:
                self.import_status = "Failed"
                self.error_log = "\\n".join(validation_errors)
                self.save()
                return

            # TRANSACTION SAFETY: Wrap import operations in transaction
            created_count = 0
            updated_count = 0
            skipped_count = 0
            error_log = []
            processed_members = []  # Track successfully processed members for user account creation

            # Process members with proper error isolation
            for row in mapped_data:
                result, member_name = self._process_single_member(row, error_log)
                if result == "created":
                    created_count += 1
                    if member_name:
                        processed_members.append(member_name)
                elif result == "updated":
                    updated_count += 1
                    if member_name:
                        processed_members.append(member_name)
                else:
                    skipped_count += 1

            # Update import results
            self._finalize_import_results(
                created_count, updated_count, skipped_count, error_log, processed_members
            )

        except Exception as e:
            self.import_status = "Failed"
            self.error_log = f"Import failed: {str(e)}"
            self.save()
            frappe.log_error(f"Member CSV Import failed: {str(e)}", "CSV Import System Error")

    def _process_single_member(self, row: Dict, error_log: List[str]) -> tuple:
        """Process a single member with proper error handling and transaction isolation."""
        try:
            # Use Frappe's transaction context for individual member processing
            result, member_name = self._create_or_update_member(row)
            return result, member_name
        except frappe.ValidationError as ve:
            error_log.append(f"Row {row.get('row_number', '?')}: Validation error - {str(ve)}")
            frappe.log_error(f"Import validation error: {str(ve)}", "CSV Import Row Validation")
            return "skipped", None
        except frappe.DuplicateEntryError as de:
            error_log.append(f"Row {row.get('row_number', '?')}: Duplicate entry - {str(de)}")
            frappe.log_error(f"Import duplicate error: {str(de)}", "CSV Import Duplicate")
            return "skipped", None
        except Exception as e:
            error_log.append(f"Row {row.get('row_number', '?')}: Unexpected error - {str(e)}")
            frappe.log_error(f"Import unexpected error: {str(e)}", "CSV Import Unexpected Error")
            return "skipped", None

    def _finalize_import_results(
        self,
        created_count: int,
        updated_count: int,
        skipped_count: int,
        error_log: List[str],
        processed_members: List[str] = None,
    ):
        """Finalize import results and update document status."""
        self.members_created = created_count
        self.members_updated = updated_count
        self.members_skipped = skipped_count

        # Process user account creation if enabled
        user_account_summary = ""
        if self.create_user_accounts and processed_members:
            user_account_summary = self._process_user_account_creation(processed_members)

        # Validate Mollie subscription data preservation
        mollie_validation_summary = ""
        if processed_members:
            mollie_issues = self._validate_mollie_data_preservation(processed_members)
            if mollie_issues:
                mollie_validation_summary = (
                    f". Mollie validation: {len(mollie_issues)} issues found (see Error Log)"
                )
            else:
                mollie_validation_summary = ". Mollie data: preserved correctly"

        self.import_status = "Completed"
        base_summary = f"Import completed successfully. Created: {created_count}, Updated: {updated_count}, Skipped: {skipped_count}"
        self.import_summary = f"{base_summary}{user_account_summary}{mollie_validation_summary}"

        if error_log:
            self.error_log = "\\n".join(error_log[:50])  # Limit error log size

        self.save()

    def _process_user_account_creation(self, processed_members: List[str]) -> str:
        """Create user accounts for successfully imported members"""
        try:
            frappe.logger().info(f"Processing user account creation for {len(processed_members)} members")

            # Use the shared bulk user account creation service
            results = bulk_create_user_accounts(
                member_names=processed_members,
                send_welcome_emails=self.send_welcome_emails,
                continue_on_error=True,
            )

            # Create summary for import results
            summary_parts = []
            if results["success"] > 0:
                summary_parts.append(f"{results['success']} user accounts created")
            if results["failed"] > 0:
                summary_parts.append(f"{results['failed']} user account failures")
            if results["skipped"] > 0:
                summary_parts.append(f"{results['skipped']} user accounts skipped")

            if summary_parts:
                summary = f". User Accounts: {', '.join(summary_parts)}"
            else:
                summary = ". No user accounts processed"

            # Log detailed results for troubleshooting
            frappe.logger().info(f"User account creation results: {results}")

            # Add any critical failures to error log
            critical_failures = [
                detail
                for detail in results["details"]
                if detail["status"] == "failed" and "permission" in detail.get("error", "").lower()
            ]
            if critical_failures:
                frappe.log_error(
                    f"Critical user account creation failures: {critical_failures}",
                    "Mijnrood Import User Account Creation",
                )

            return summary

        except Exception as e:
            error_msg = f"Error during user account creation: {str(e)}"
            frappe.log_error(frappe.get_traceback(), "Mijnrood User Account Creation Error")
            frappe.logger().error(error_msg)
            return f". User account creation failed: {str(e)}"

    def _validate_mollie_data_preservation(self, processed_members: List[str]) -> List[str]:
        """Validate that Mollie subscription data was properly preserved during import"""
        validation_issues = []

        try:
            # Check processed members for Mollie data consistency
            for member_name in processed_members:
                member = frappe.get_doc("Member", member_name)

                # If member has customer with Mollie subscription data, validate it's complete
                if member.customer:
                    customer = frappe.get_doc("Customer", member.customer)
                    if customer.custom_mollie_customer_id or customer.custom_mollie_subscription_id:
                        issues = []

                        # Validate Mollie Customer ID format
                        if customer.custom_mollie_customer_id:
                            if not customer.custom_mollie_customer_id.startswith("cst_"):
                                issues.append(
                                    f"Invalid Mollie Customer ID format: {customer.custom_mollie_customer_id}"
                                )

                        # Validate Mollie Subscription ID format
                        if customer.custom_mollie_subscription_id:
                            if not customer.custom_mollie_subscription_id.startswith("sub_"):
                                issues.append(
                                    f"Invalid Mollie Subscription ID format: {customer.custom_mollie_subscription_id}"
                                )

                        # Check that payment method is set to Mollie if subscription data exists
                        if (
                            customer.custom_mollie_customer_id or customer.custom_mollie_subscription_id
                        ) and member.payment_method != "Mollie":
                            issues.append(
                                f"Payment method should be 'Mollie' when subscription data exists, found: {member.payment_method}"
                            )

                        # Check for incomplete subscription data
                        if customer.custom_mollie_customer_id and not customer.custom_mollie_subscription_id:
                            issues.append("Has Mollie Customer ID but missing Subscription ID")
                        elif (
                            customer.custom_mollie_subscription_id and not customer.custom_mollie_customer_id
                        ):
                            issues.append("Has Mollie Subscription ID but missing Customer ID")

                        if issues:
                            validation_issues.append(f"Member {member_name}: {'; '.join(issues)}")

        except Exception as e:
            frappe.log_error(f"Error validating Mollie data preservation: {str(e)}", "Mollie Data Validation")
            validation_issues.append(f"Validation error: {str(e)}")

        if validation_issues:
            frappe.logger().warning(f"Mollie data validation found {len(validation_issues)} issues")
            # Log issues for review but don't fail the import
            frappe.log_error(
                "Mollie data preservation issues:\n" + "\n".join(validation_issues),
                "Mollie Data Preservation Validation",
            )
        else:
            frappe.logger().info("Mollie data preservation validation passed")

        return validation_issues

    def _create_or_update_member(self, row_data: Dict) -> tuple:
        """Create or update a member record."""
        # Check if member exists by member_id or email
        existing_member = None

        if row_data.get("member_id"):
            existing_member = frappe.db.get_value("Member", {"member_id": row_data["member_id"]}, "name")

        if not existing_member and row_data.get("email"):
            existing_member = frappe.db.get_value("Member", {"email": row_data["email"]}, "name")

        if existing_member:
            # Update existing member
            member = frappe.get_doc("Member", existing_member)
            self._update_member_fields(member, row_data)
            member.save()

            # Update address if address data was provided
            if hasattr(member, "_pending_address_data") and member._pending_address_data:
                self._create_or_update_address(member, member._pending_address_data)
                # Update primary_address field on member if address was created
                if member.primary_address:
                    member.save()

            # Update/create dues schedule and membership if data was provided
            self._create_related_records(member, row_data)

            return "updated", member.name
        else:
            # Create new member
            member = frappe.new_doc("Member")
            self._update_member_fields(member, row_data)

            # Set system flags for CSV import - maintain validation but mark as system operation
            member.flags.ignore_validate = False  # We want validation, but with system flags
            member._csv_import = True  # Mark as CSV import for validation exceptions

            # Check if user has CSV import permissions
            if not self._check_csv_import_permissions():
                frappe.throw(
                    _("You do not have permission to perform CSV imports. Contact your administrator.")
                )

            # Save member with proper validation
            member.insert()

            # Create related records after successful member creation
            self._create_related_records(member, row_data)

            return "created", member.name

    def _update_member_fields(self, member_doc: Document, row_data: Dict):
        """Update member document fields from row data."""

        # FIRST PRIORITY: Set status fields to prevent any workflow issues
        # CSV imported members are backend-created, not application-created
        member_doc.application_id = None  # Explicitly ensure no application ID
        member_doc.application_status = "Approved"  # Backend-created = pre-approved

        # Set status based on membership type
        membership_type = row_data.get("membership_type", "").lower()
        if membership_type in ["lid", "aspirant"]:
            member_doc.status = "Active"
        elif membership_type in ["uitgeschreven", "opgezegd"]:
            member_doc.status = "Terminated"
        elif membership_type == "geroyeerd":
            member_doc.status = "Expelled"
        elif membership_type == "geschorst":
            member_doc.status = "Suspended"
        else:
            member_doc.status = "Active"  # Default for unknown types

        # Set system flags early to ensure they're available during all validations
        member_doc._system_update = True  # Bypass fee override validation
        member_doc._csv_import = True  # Mark as CSV import for other validations
        member_doc.flags.ignore_workflow = True  # Bypass workflow validation
        member_doc._skip_workflow_validation = True

        # Additional system flags to bypass validations
        member_doc.flags.ignore_validate = False  # Still validate but with flags
        member_doc.flags.ignore_mandatory = False  # Don't ignore mandatory fields

        # Phone numbers are cleaned and validated in _clean_phone_number method
        # No need to bypass framework validation

        # Basic member information
        if row_data.get("member_id"):
            member_doc.member_id = row_data["member_id"]
        if row_data.get("first_name"):
            member_doc.first_name = row_data["first_name"]
        if row_data.get("tussenvoegsel"):
            member_doc.tussenvoegsel = row_data["tussenvoegsel"]
        if row_data.get("last_name"):
            member_doc.last_name = row_data["last_name"]
        if row_data.get("birth_date"):
            member_doc.birth_date = row_data["birth_date"]
        if row_data.get("email"):
            member_doc.email = row_data["email"]
        if row_data.get("contact_number"):
            # Clean and normalize the phone number
            cleaned_phone = self._clean_phone_number(row_data["contact_number"])
            if cleaned_phone:  # Only set if cleaning was successful
                member_doc.contact_number = cleaned_phone
            # If cleaning failed, the field will remain empty (logged in _clean_phone_number)
        if row_data.get("member_since"):
            member_doc.member_since = row_data["member_since"]
        # Note: membership_type is set via Membership record creation, not directly on Member
        # The Member.current_membership_type field is read-only and computed from linked Membership

        # Financial information
        if row_data.get("iban"):
            member_doc.iban = row_data["iban"]
            member_doc.payment_method = "SEPA Direct Debit"
        if row_data.get("dues_rate"):
            # Set dues_rate - CSV import flag will handle validation bypass
            member_doc.dues_rate = row_data["dues_rate"]
            # Store data for creating membership dues schedule after member creation
            member_doc._pending_dues_schedule_data = {
                "dues_rate": row_data["dues_rate"],
                "payment_period": row_data.get("payment_period"),
                "override_reason": "Import from mijnrood",
            }

        # Store Mollie information for later - will be set on Customer record
        # Set payment method on Member if Mollie data exists
        if row_data.get("custom_mollie_customer_id") or row_data.get("custom_mollie_subscription_id"):
            member_doc.payment_method = "Mollie"
            # Store Mollie data temporarily for later Customer update
            member_doc._mollie_data = {
                "custom_mollie_customer_id": row_data.get("custom_mollie_customer_id"),
                "custom_mollie_subscription_id": row_data.get("custom_mollie_subscription_id"),
                "custom_subscription_status": "active"
                if row_data.get("custom_mollie_subscription_id")
                else None,
            }

        # Store address information for later creation (after Customer is created)
        member_doc._pending_address_data = (
            row_data
            if any(row_data.get(field) for field in ["address_line1", "city", "postal_code"])
            else None
        )

        # Store termination information for later creation if member is terminated
        if membership_type in ["uitgeschreven", "opgezegd", "geroyeerd", "geschorst"]:
            member_doc._pending_termination_data = {
                "membership_type": membership_type,
                "member_since": row_data.get("member_since"),
                "termination_reason": self._get_termination_reason(membership_type),
            }

        # Handle chapter assignment if chapter is provided
        if row_data.get("chapter"):
            chapter_name = str(row_data["chapter"]).strip()
            # Store chapter information for later creation (after member is saved and has a name)
            member_doc._pending_chapter_assignment = chapter_name

        # Set member_since date (status was already set at the beginning of _update_member_fields)
        member_doc.member_since = row_data.get("member_since") or today()

    def _create_or_update_address(self, member_doc: Document, row_data: Dict):
        """Create or update address for member."""
        # Only create address if we have meaningful address data
        address_line1 = row_data.get("address_line1")
        city = row_data.get("city")

        # Handle None values and clean strings
        if address_line1:
            address_line1 = str(address_line1).strip() if address_line1 else None
        if city:
            city = str(city).strip() if city else None

        # Skip address creation entirely if we don't have meaningful address data
        # Don't create placeholder addresses with fake data
        if not address_line1 or not city:
            frappe.logger().info(
                f"Skipping address creation for member {member_doc.name} - insufficient address data"
            )
            return

        address_data = {
            "address_title": f"{member_doc.first_name} {member_doc.last_name}",
            "address_type": "Personal",
            "address_line1": address_line1,
            "city": city,
            "pincode": (row_data.get("postal_code") or "").strip() or None,
            "country": self._convert_country_code(row_data.get("country", "NL"))
            if row_data.get("country")
            else "Netherlands",
            "links": [
                {
                    "link_doctype": "Member",
                    "link_name": member_doc.name,
                    "link_title": member_doc.full_name or f"{member_doc.first_name} {member_doc.last_name}",
                }
            ],
        }

        # Add Customer link if Customer record exists
        if member_doc.customer:
            address_data["links"].append(
                {
                    "link_doctype": "Customer",
                    "link_name": member_doc.customer,
                    "link_title": f"{member_doc.first_name} {member_doc.last_name}",
                }
            )

        # Check if address already exists
        if member_doc.primary_address:
            address = frappe.get_doc("Address", member_doc.primary_address)
            for field, value in address_data.items():
                if field != "links" and value:
                    setattr(address, field, value)
            address.save()
        else:
            address = frappe.get_doc({"doctype": "Address", **address_data})
            address.insert()
            member_doc.primary_address = address.name

    def _get_termination_reason(self, membership_type: str) -> str:
        """Get human-readable termination reason from membership type."""
        reason_mapping = {
            "uitgeschreven": "Voluntarily left membership",
            "opgezegd": "Membership cancelled/terminated",
            "geroyeerd": "Expelled from organization",
            "geschorst": "Membership suspended",
        }
        return reason_mapping.get(membership_type, f"Terminated ({membership_type})")

    def _check_csv_import_permissions(self) -> bool:
        """Check if current user has permission to perform CSV imports."""
        user_roles = frappe.get_roles(frappe.session.user)
        # Define roles that can perform CSV imports
        authorized_roles = ["System Manager", "Verenigingen Administrator", "Verenigingen Manager"]

        return any(role in user_roles for role in authorized_roles)

    def _update_customer_mollie_data(self, member_doc: Document, mollie_data: dict):
        """Update the Customer record with Mollie subscription data."""
        try:
            # Validate Mollie data before processing
            from verenigingen.utils.mollie_data_validator import get_mollie_validator

            validator = get_mollie_validator()
            is_valid, errors, warnings = validator.validate_customer_data(mollie_data)

            if not is_valid:
                frappe.throw(f"Invalid Mollie data in CSV import: {'; '.join(errors)}")

            # Log warnings
            for warning in warnings:
                frappe.logger().warning(f"CSV import Mollie data warning: {warning}")

            # First ensure customer exists (create if needed)
            if not member_doc.customer:
                # Create customer using Member's create_customer method
                member_doc._suppress_customer_messages = True  # Suppress message during import
                customer_name = member_doc.create_customer()
                member_doc.customer = customer_name

            # Update the Customer with Mollie data
            if member_doc.customer:
                customer = frappe.get_doc("Customer", member_doc.customer)

                # Update Mollie fields
                if mollie_data.get("custom_mollie_customer_id"):
                    customer.custom_mollie_customer_id = mollie_data["custom_mollie_customer_id"]
                if mollie_data.get("custom_mollie_subscription_id"):
                    customer.custom_mollie_subscription_id = mollie_data["custom_mollie_subscription_id"]
                if mollie_data.get("subscription_status"):
                    customer.custom_subscription_status = mollie_data["custom_subscription_status"]

                # Save customer with Mollie data
                customer.save()

                frappe.logger().info(
                    f"Updated Customer {customer.name} with Mollie data for Member {member_doc.name}"
                )

        except Exception as e:
            frappe.logger().error(
                f"Failed to update Customer with Mollie data for Member {member_doc.name}: {str(e)}"
            )

    def _create_related_records(self, member_doc: Document, row_data: Dict = None):
        """Create related records (address, termination) after successful member creation."""
        try:
            # Update Customer with Mollie data if present
            if hasattr(member_doc, "_mollie_data") and member_doc._mollie_data:
                self._update_customer_mollie_data(member_doc, member_doc._mollie_data)

            # Create address if address data was provided
            if hasattr(member_doc, "_pending_address_data") and member_doc._pending_address_data:
                self._create_or_update_address(member_doc, member_doc._pending_address_data)
                # Update primary_address field on member if address was created
                if member_doc.primary_address:
                    member_doc.save()

            # Create membership termination record if needed
            if hasattr(member_doc, "_pending_termination_data"):
                self._create_termination_record(member_doc, member_doc._pending_termination_data)

            # Create chapter assignment if chapter was provided
            if hasattr(member_doc, "_pending_chapter_assignment"):
                self._assign_member_to_chapter(member_doc, member_doc._pending_chapter_assignment)

            # Create dues schedule if dues data was provided
            if hasattr(member_doc, "_pending_dues_schedule_data"):
                self._create_dues_schedule_from_import(member_doc, member_doc._pending_dues_schedule_data)

            # Create membership record with appropriate type
            if row_data and (row_data.get("payment_period") or row_data.get("membership_type")):
                self._create_membership_from_import(member_doc, row_data)

        except Exception as e:
            # Log error but don't fail the entire member creation for related record issues
            frappe.logger().error(f"Failed to create related records for member {member_doc.name}: {str(e)}")

    def _create_termination_record(self, member_doc: Document, termination_data: dict):
        """Create a membership termination record for historical accuracy."""
        try:
            # Check if Member Termination Request DocType exists
            if not frappe.db.exists("DocType", "Membership Termination Request"):
                frappe.logger().info(
                    "Membership Termination Request DocType not found, skipping termination record creation"
                )
                return

            termination_doc = frappe.new_doc("Membership Termination Request")
            termination_doc.member = member_doc.name
            termination_doc.termination_reason = termination_data["termination_reason"]
            termination_doc.termination_date = termination_data.get("member_since") or today()
            termination_doc.notes = (
                f"Imported from CSV - Original type: {termination_data['membership_type']}"
            )
            termination_doc.status = "Approved"  # Historical data is pre-approved

            # Set flags to bypass workflow for historical data
            termination_doc._csv_import = True

            # Insert termination record with proper permissions
            termination_doc.insert()
            frappe.logger().info(f"Created termination record for member {member_doc.name}")

        except Exception as e:
            frappe.logger().error(f"Failed to create termination record for {member_doc.name}: {str(e)}")
            # Don't fail the entire import for termination record issues

    def _assign_member_to_chapter(self, member_doc: Document, chapter_name: str):
        """Assign member to chapter based on chapter name from CSV, with optional auto-creation."""
        try:
            # Check if the chapter exists
            if not frappe.db.exists("Chapter", chapter_name):
                if self.auto_create_chapters:
                    # Try to create the chapter automatically
                    created_chapter = self._create_chapter_if_not_exists(chapter_name)
                    if not created_chapter:
                        frappe.logger().error(
                            f"Failed to auto-create chapter '{chapter_name}'. Skipping chapter assignment for member {member_doc.name}"
                        )
                        return
                    frappe.logger().info(
                        f"Auto-created chapter '{chapter_name}' and assigning member {member_doc.name}"
                    )
                else:
                    # Original behavior: log warning and skip
                    frappe.logger().warning(
                        f"Chapter '{chapter_name}' does not exist. Skipping chapter assignment for member {member_doc.name}"
                    )
                    return

            # Create chapter membership using proper parent.append() pattern
            # Get chapter document and add member to its members child table
            try:
                chapter_doc = frappe.get_doc("Chapter", chapter_name)
                
                # Check if member is already in the chapter
                existing_membership = False
                for existing_member in chapter_doc.members:
                    if existing_member.member == member_doc.name and existing_member.enabled:
                        existing_membership = True
                        break
                
                if not existing_membership:
                    # Add member to chapter's members child table
                    chapter_doc.append("members", {
                        "member": member_doc.name,
                        "enabled": 1,
                        "status": "Active",
                        "chapter_join_date": member_doc.member_since or today()
                    })
                    chapter_doc.save(ignore_permissions=True)
                    frappe.logger().info(
                        f"Successfully assigned member {member_doc.name} to chapter {chapter_name}"
                    )
                else:
                    frappe.logger().info(f"Member {member_doc.name} already exists in chapter {chapter_name}")
            except Exception as e:
                frappe.logger().warning(f"Could not assign member {member_doc.name} to chapter {chapter_name}: {str(e)}")
            else:
                frappe.logger().info(
                    f"Member {member_doc.name} is already assigned to chapter {chapter_name}"
                )

        except Exception as e:
            frappe.logger().error(
                f"Failed to assign member {member_doc.name} to chapter {chapter_name}: {str(e)}"
            )
            # Don't fail the entire import for chapter assignment issues

    def _create_dues_schedule_from_import(self, member_doc: Document, dues_data: dict):
        """Create a membership dues schedule from CSV import data."""
        try:
            # Map payment period to billing frequency
            billing_frequency = self._map_payment_period_to_frequency(dues_data.get("payment_period"))

            # Create dues schedule
            dues_schedule = frappe.new_doc("Membership Dues Schedule")
            dues_schedule.member = member_doc.name
            dues_schedule.member_name = (
                member_doc.full_name or f"{member_doc.first_name} {member_doc.last_name}"
            )
            # Get membership type from the row data context
            membership_type_name = self._determine_membership_type(row_data) or "Standard"
            dues_schedule.membership_type = membership_type_name
            dues_schedule.dues_rate = dues_data["dues_rate"]
            dues_schedule.billing_frequency = billing_frequency
            dues_schedule.status = "Active"
            dues_schedule.is_active = 1
            dues_schedule.uses_custom_amount = 1
            dues_schedule.custom_amount_reason = dues_data["override_reason"]
            dues_schedule.custom_amount_approved = 1
            dues_schedule.custom_amount_approved_by = frappe.session.user
            dues_schedule.custom_amount_approved_date = today()

            # Set next invoice date based on member_since date and billing frequency
            if member_doc.member_since:
                dues_schedule.next_invoice_date = self._calculate_next_invoice_date(
                    getdate(member_doc.member_since), billing_frequency
                )
            else:
                dues_schedule.next_invoice_date = today()

            # Set CSV import flag
            dues_schedule._csv_import = True
            dues_schedule.flags.ignore_workflow = True

            dues_schedule.insert()

            # Update member's current dues schedule reference
            member_doc.current_dues_schedule = dues_schedule.name
            member_doc.next_invoice_date = dues_schedule.next_invoice_date
            member_doc.save()

            frappe.logger().info(f"Created dues schedule {dues_schedule.name} for member {member_doc.name}")

        except Exception as e:
            frappe.logger().error(f"Failed to create dues schedule for {member_doc.name}: {str(e)}")
            # Don't fail the entire import for dues schedule issues

    def _create_membership_from_import(self, member_doc: Document, row_data: dict):
        """Create a membership record from CSV import data."""
        try:
            # Determine membership type from payment period or existing membership_type
            membership_type_name = self._determine_membership_type(row_data)

            # Create membership record
            membership = frappe.new_doc("Membership")
            membership.member = member_doc.name
            membership.member_name = member_doc.full_name or f"{member_doc.first_name} {member_doc.last_name}"
            membership.membership_type = membership_type_name
            membership.start_date = row_data.get("member_since") or today()
            membership.status = "Current"

            # Set end date based on membership type billing period
            if membership_type_name:
                membership_type_doc = frappe.get_doc("Membership Type", membership_type_name)
                if (
                    hasattr(membership_type_doc, "billing_period_in_months")
                    and membership_type_doc.billing_period_in_months
                ):
                    from dateutil.relativedelta import relativedelta

                    start_date = getdate(membership.start_date)
                    membership.renewal_date = start_date + relativedelta(
                        months=membership_type_doc.billing_period_in_months
                    )

            # Set CSV import flag
            membership._csv_import = True
            membership.flags.ignore_workflow = True

            membership.insert()
            membership.submit()

            # Update member's current membership reference
            # Note: These fields are fetch fields and will be updated automatically from the membership record
            member_doc.current_membership_details = membership.name
            member_doc.save()

            frappe.logger().info(f"Created membership {membership.name} for member {member_doc.name}")

        except Exception as e:
            frappe.logger().error(f"Failed to create membership for {member_doc.name}: {str(e)}")
            # Don't fail the entire import for membership creation issues

    def _map_payment_period_to_frequency(self, payment_period: str) -> str:
        """Map Dutch payment period terms to billing frequencies."""
        if not payment_period:
            return "Annual"

        period_mapping = {
            "maandelijks": "Monthly",
            "monthly": "Monthly",
            "per maand": "Monthly",
            "kwartaal": "Quarterly",
            "quarterly": "Quarterly",
            "per kwartaal": "Quarterly",
            "driemaandelijks": "Quarterly",
            "halfjaar": "Semi-Annual",
            "halfjaarlijks": "Semi-Annual",
            "semi-annual": "Semi-Annual",
            "per halfjaar": "Semi-Annual",
            "jaar": "Annual",
            "jaarlijks": "Annual",
            "annual": "Annual",
            "per jaar": "Annual",
            "yearly": "Annual",
        }

        period_lower = payment_period.lower().strip()
        return period_mapping.get(period_lower, "Annual")

    def _determine_membership_type(self, row_data: dict) -> str:
        """Determine membership type from CSV data."""
        # First check if membership_type was explicitly provided
        if row_data.get("membership_type"):
            membership_type = row_data["membership_type"]
            if self._validate_membership_type_exists(membership_type):
                return membership_type

        # Map payment periods to likely membership types
        payment_period = row_data.get("payment_period", "").lower().strip()

        # Check if we have specific membership types that match the payment period
        period_type_mapping = {
            "maandelijks": "Standard",
            "monthly": "Standard",
            "kwartaal": "Quarterly",
            "quarterly": "Quarterly",
            "halfjaar": "Semi-Annual",
            "semi-annual": "Semi-Annual",
            "jaar": "Annual",
            "annual": "Annual",
            "jaarlijks": "Annual",
        }

        suggested_type = period_type_mapping.get(payment_period)
        if suggested_type and self._validate_membership_type_exists(suggested_type):
            return suggested_type

        # Default to Standard if available, otherwise first active membership type
        if self._validate_membership_type_exists("Standard"):
            return "Standard"

        # Fallback: get any active membership type
        active_types = frappe.get_all("Membership Type", filters={"is_active": 1}, fields=["name"], limit=1)

        return active_types[0].name if active_types else "Standard"

    def _calculate_next_invoice_date(self, start_date: "datetime.date", billing_frequency: str) -> str:
        """Calculate next invoice date based on start date and billing frequency."""
        from dateutil.relativedelta import relativedelta

        if billing_frequency == "Monthly":
            next_date = start_date + relativedelta(months=1)
        elif billing_frequency == "Quarterly":
            next_date = start_date + relativedelta(months=3)
        elif billing_frequency == "Semi-Annual":
            next_date = start_date + relativedelta(months=6)
        elif billing_frequency == "Annual":
            next_date = start_date + relativedelta(months=12)
        else:
            # Default to annual
            next_date = start_date + relativedelta(months=12)

        return next_date.strftime("%Y-%m-%d")

    def _validate_membership_type_exists(self, membership_type: str) -> bool:
        """Validate that a membership type exists before using it."""
        try:
            return frappe.db.exists("Membership Type", membership_type) is not None
        except Exception as e:
            frappe.logger().error(f"Error validating membership type '{membership_type}': {str(e)}")
            return False

    def _validate_doctype_field(self, doctype: str, fieldname: str) -> bool:
        """Validate that a field exists on a DocType before trying to set it."""
        try:
            meta = frappe.get_meta(doctype)
            return meta.has_field(fieldname)
        except Exception as e:
            frappe.logger().error(f"Error validating field '{fieldname}' on DocType '{doctype}': {str(e)}")
            return False

    def _ensure_nl_region_exists(self) -> str:
        """Ensure the Netherlands region exists and return its name."""
        try:
            # Check if NL region already exists
            nl_region = frappe.db.get_value("Region", {"region_code": "NL"})
            if nl_region:
                return nl_region

            # Create basic Netherlands region
            region = frappe.new_doc("Region")
            region.update(
                {
                    "region_name": "Netherlands",
                    "region_code": "NL",
                    "country": "Netherlands",
                    "is_active": 1,
                    "preferred_language": "Dutch",
                    "time_zone": "Europe/Amsterdam",
                    "membership_fee_adjustment": 1.0,
                    "description": "Auto-created Netherlands region during CSV import",
                }
            )

            # Set CSV import flags
            region._csv_import = True
            region.flags.ignore_workflow = True

            region.insert()

            frappe.logger().info("Auto-created Netherlands region during CSV import")
            return region.name

        except Exception as e:
            frappe.logger().error(f"Failed to create Netherlands region: {str(e)}")
            # Return None to indicate failure
            return None

    def _create_chapter_if_not_exists(self, chapter_name: str) -> str:
        """Create a new chapter with Netherlands region if it doesn't exist."""
        try:
            # Ensure Netherlands region exists
            nl_region = self._ensure_nl_region_exists()
            if not nl_region:
                frappe.logger().error(
                    f"Cannot create chapter '{chapter_name}' - Netherlands region creation failed"
                )
                return None

            # Create new chapter
            chapter = frappe.new_doc("Chapter")
            chapter.update(
                {
                    "name": chapter_name,
                    "status": "Active",
                    "region": nl_region,
                    "introduction": f"Auto-created chapter '{chapter_name}' during CSV import. Please update with proper details.",
                }
            )

            # Set CSV import flags
            chapter._csv_import = True
            chapter.flags.ignore_workflow = True

            chapter.insert()

            frappe.logger().info(
                f"Auto-created chapter '{chapter_name}' with Netherlands region during CSV import"
            )
            return chapter.name

        except Exception as e:
            frappe.logger().error(f"Failed to create chapter '{chapter_name}': {str(e)}")
            return None


@frappe.whitelist()
def validate_import_file(import_doc_name):
    """Manually validate an import file."""
    try:
        doc = frappe.get_doc("Member CSV Import", import_doc_name)

        # Skip validation if no file
        if not doc.csv_file:
            return {"status": "error", "message": "Please upload a CSV or Excel file first"}

        # Set status to validating
        doc.import_status = "Validating"
        doc.save()
        frappe.db.commit()

        # Perform validation
        try:
            csv_data = doc._read_csv_file()
            if not csv_data:
                doc.import_status = "Failed"
                doc.error_log = "CSV file is empty or unreadable"
                doc.save()
                return {"status": "error", "message": "CSV file is empty or unreadable"}

            # Validate and map data
            mapped_data, validation_errors = doc._validate_and_map_data(csv_data)

            if validation_errors:
                doc.import_status = "Failed"
                doc.error_log = "\\n".join(validation_errors[:10])  # Show first 10 errors
                doc.save()
                return {
                    "status": "error",
                    "message": f"Validation failed: {len(validation_errors)} errors found. Check Error Log.",
                }
            else:
                doc.import_status = "Ready for Import"
                doc.preview_data = json.dumps(mapped_data[:5], indent=2, default=str)
                doc.descriptive_name = f"Member Import {doc.import_date} ({len(mapped_data)} records)"
                doc.save()
                return {
                    "status": "success",
                    "message": f"File validated successfully. Ready to import {len(mapped_data)} records.",
                }

        except (FileNotFoundError, PermissionError) as fe:
            error_msg = f"File access error: {str(fe)[:200]}"
            doc.import_status = "Failed"
            doc.error_log = error_msg
            doc.save()
            return {"status": "error", "message": error_msg}
        except frappe.ValidationError as ve:
            error_msg = f"Data validation error: {str(ve)[:200]}"
            doc.import_status = "Failed"
            doc.error_log = error_msg
            doc.save()
            return {"status": "error", "message": error_msg}
        except Exception as ve:
            error_msg = f"Unexpected error: {str(ve)[:200]}"
            doc.import_status = "Failed"
            doc.error_log = error_msg
            doc.save()
            frappe.log_error(f"Unexpected validation error: {str(ve)}", "CSV Import Validation")
            return {"status": "error", "message": error_msg}

    except (frappe.DoesNotExistError, frappe.PermissionError) as pe:
        frappe.log_error(f"Permission/access error in CSV import: {str(pe)}", "CSV Import Access")
        return {"status": "error", "message": f"Access denied: {str(pe)[:200]}"}
    except Exception as e:
        frappe.log_error(f"Manual validation failed: {str(e)}", "CSV Import Manual Validation")
        return {"status": "error", "message": f"System error: {str(e)[:200]}"}


@frappe.whitelist()
def get_import_template():
    """Generate a CSV template for member import."""
    headers = [
        "Lidnr.",
        "Voornaam",
        "Tussenvoegsel",
        "Achternaam",
        "Geboortedatum",
        "Inschrijfdataum",
        "Groep",
        "E-mailadres",
        "Telefoonnr.",
        "Adres",
        "Plaats",
        "Postcode",
        "Landcode",
        "IBAN",
        "Contributiebedrag",
        "Betaalperiode",
        "Betaald",
        "Mollie CID",
        "Mollie SID",
        "Privacybeleid geaccepteerd",
        "Lidmaatschapstype",
    ]

    sample_data = [
        "12345",
        "Jan",
        "van der",
        "Berg",
        "1990-01-15",
        "2024-01-01",
        "Amsterdam",
        "jan.jansen@example.com",
        "+31612345678",
        "Hoofdstraat 123",
        "Amsterdam",
        "1000 AA",
        "NL",
        "NL91ABNA0417164300",
        "25.00",
        "Maandelijks",
        "Ja",
        "cst_example123",
        "sub_example456",
        "Ja",
        "Standard",
    ]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerow(sample_data)

    return {"filename": "member_import_template.csv", "content": output.getvalue()}
