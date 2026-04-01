# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

import re
from typing import Any, Dict, List, Tuple

from verenigingen.utils.csv.data_transformers import clean_phone_number, parse_date


class ProcuriosDataValidator:
    """Validates and maps Procurios CSV data to Member fields.

    Maps known fields to native Member fields and stores everything else
    in a key-value list for the procurios_data child table.
    """

    # Procurios column name (case-insensitive) -> Member field name
    NATIVE_FIELD_MAPPING = {
        "systeem id": "member_id",
        "voornaam": "first_name",
        "tussenvoegsel": "tussenvoegsel",
        "e-mailadres": "email",
        "geboortedatum": "birth_date",
        "bankrekening": "iban",
        "aanmaakdatum": "member_since",
        "mobiel": "contact_number",
    }

    # Fields used for name derivation but not directly mapped
    NAME_FIELDS = {"volledige naam", "naam"}

    # Address prefixes and their subfield suffixes
    ADDRESS_TYPES = ("Standaardadres", "Postadres", "Factuuradres")
    ADDRESS_SUBFIELDS = {
        "Straat": "street",
        "Nummer met toevoeging": "house_number",
        "Postcode": "pincode",
        "Plaats": "city",
        "Landnaam": "country",
        "Geadresseerde": "addressee",
    }

    # Geslacht -> gender value mapping
    GENDER_MAPPING = {
        "man": "Male",
        "m": "Male",
        "vrouw": "Female",
        "v": "Female",
        "anders": "Other",
        "x": "Other",
        "onbekend": "Prefer not to say",
    }

    # Category detection patterns (checked in order, first match wins)
    CATEGORY_PATTERNS = [
        (
            "Financial",
            re.compile(
                r"contributi|bankrekening|machtiging|factuu?r|bedrag|totaal|€|openstaande",
                re.IGNORECASE,
            ),
        ),
        (
            "Subscription",
            re.compile(
                r"vegan\s*magazine|abonne|nieuwsbrief",
                re.IGNORECASE,
            ),
        ),
        (
            "Survey",
            re.compile(
                r"jour_|waarom|wat moeten|thema",
                re.IGNORECASE,
            ),
        ),
        (
            "Campaign",
            re.compile(
                r"campagne|actie|binnengekomen via|welkomstcadeau|aanmeldcode",
                re.IGNORECASE,
            ),
        ),
        (
            "Personal",
            re.compile(
                r"^naam$|voornaam|titel|geslacht|geboortedatum|voorkeurstaal|voorletters|tenaamstelling",
                re.IGNORECASE,
            ),
        ),
    ]

    def __init__(self, import_gender: bool = False):
        self.import_gender = import_gender

    def validate_and_map_data(self, csv_data: List[Dict]) -> Tuple[List[Dict], List[str]]:
        """Validate and map CSV rows. Returns (mapped_data, errors)."""
        mapped_data = []
        errors = []

        for i, row in enumerate(csv_data):
            row_num = i + 2  # 1-indexed + header row
            mapped = self.map_row_data(row, row_num)
            row_errors = self.validate_row(mapped, row_num)

            if row_errors:
                errors.extend(row_errors)
            else:
                mapped_data.append(mapped)

            if len(errors) >= 100:
                break

        return mapped_data, errors[:100]

    def map_row_data(self, row: Dict, row_num: int) -> Dict:
        """Map a single CSV row to Member fields + procurios_data list."""
        mapped = {"row_number": row_num, "procurios_data": [], "addresses": []}

        # Collect address fields grouped by type
        address_data: Dict[str, Dict[str, str]] = {}

        for original_key, value in row.items():
            if not value or not str(value).strip():
                continue

            value = str(value).strip()
            key_lower = original_key.strip().lower()

            # Check native field mapping
            if key_lower in self.NATIVE_FIELD_MAPPING:
                member_field = self.NATIVE_FIELD_MAPPING[key_lower]
                mapped[member_field] = self._clean_native_field(member_field, value)
                continue

            # Check name derivation fields
            if key_lower in self.NAME_FIELDS:
                mapped[f"_raw_{key_lower.replace(' ', '_')}"] = value
                continue

            # Check gender field
            if key_lower == "geslacht":
                if self.import_gender:
                    mapped["gender"] = self.GENDER_MAPPING.get(value.lower(), "Other")
                else:
                    mapped["procurios_data"].append(
                        {
                            "field_label": original_key.strip(),
                            "field_value": value,
                            "field_category": self.categorize_field(original_key.strip()),
                        }
                    )
                continue

            # Check address fields
            address_matched = False
            for addr_type in self.ADDRESS_TYPES:
                for suffix, field_name in self.ADDRESS_SUBFIELDS.items():
                    if original_key.strip() == f"{addr_type}: {suffix}":
                        if addr_type not in address_data:
                            address_data[addr_type] = {"address_type": addr_type}
                        address_data[addr_type][field_name] = value
                        address_matched = True
                        break
                if address_matched:
                    break
            if address_matched:
                continue

            # Everything else goes to procurios_data
            mapped["procurios_data"].append(
                {
                    "field_label": original_key.strip(),
                    "field_value": value,
                    "field_category": self.categorize_field(original_key.strip()),
                }
            )

        # Derive last_name from full name
        mapped["last_name"] = self._derive_last_name(mapped)

        # Convert address dicts to list (skip empty ones)
        for addr in address_data.values():
            has_data = any(v for k, v in addr.items() if k != "address_type" and v and str(v).strip())
            if has_data:
                mapped["addresses"].append(addr)

        # Clean up internal raw fields
        for key in list(mapped.keys()):
            if key.startswith("_raw_"):
                del mapped[key]

        return mapped

    def validate_row(self, row: Dict, row_num: int) -> List[str]:
        """Validate a mapped row. Returns list of error messages."""
        errors = []

        if not row.get("member_id"):
            errors.append(f"Row {row_num}: Missing required field Systeem ID (member_id)")

        if not row.get("first_name") and not row.get("last_name"):
            errors.append(f"Row {row_num}: At least one name field (Voornaam or last name) is required")

        email = row.get("email")
        if email and not self._validate_email(email):
            errors.append(f"Row {row_num}: Invalid email format")

        iban = row.get("iban")
        if iban and not self._validate_iban(iban):
            errors.append(f"Row {row_num}: Invalid IBAN")

        return errors

    def categorize_field(self, field_label: str) -> str:
        """Categorize a Procurios field label for the child table."""
        for category, pattern in self.CATEGORY_PATTERNS:
            if pattern.search(field_label):
                return category
        return "Other"

    def _derive_last_name(self, mapped: Dict) -> str:
        """Derive last_name from full name minus first_name and tussenvoegsel."""
        full_name = mapped.get("_raw_volledige_naam") or mapped.get("_raw_naam") or ""
        first_name = mapped.get("first_name", "")
        tussenvoegsel = mapped.get("tussenvoegsel", "")

        if not full_name:
            return ""

        remainder = full_name
        if first_name and remainder.startswith(first_name):
            remainder = remainder[len(first_name) :].strip()
        if tussenvoegsel and remainder.startswith(tussenvoegsel):
            remainder = remainder[len(tussenvoegsel) :].strip()

        return remainder

    def _clean_native_field(self, field_name: str, value: str) -> Any:
        """Clean a value for a native Member field."""
        if field_name in ("birth_date", "member_since"):
            return parse_date(value) or value
        if field_name == "iban":
            return value.upper().replace(" ", "")
        if field_name == "email":
            return value.lower().strip()
        if field_name == "contact_number":
            return clean_phone_number(value) or value
        return value.strip()

    def _validate_email(self, email: str) -> bool:
        """Basic email format validation."""
        if not email or len(email) > 320:
            return False
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return bool(re.match(pattern, email))

    def _validate_iban(self, iban: str) -> bool:
        """Validate IBAN using existing validator."""
        try:
            from verenigingen.utils.validation.iban_validator import validate_iban

            result = validate_iban(iban)
            return result.get("valid", False)
        except Exception:
            return False
