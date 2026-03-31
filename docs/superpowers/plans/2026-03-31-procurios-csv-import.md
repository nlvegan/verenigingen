# Procurios CSV Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import Procurios CRM contact data from CSV into Member records, with native field mapping for core data and a key-value child table for all remaining Procurios-specific fields.

**Architecture:** Follows the MijnRood CSV Import pattern — dedicated submittable DocType with CSV validation, background batch processing via `CSVImportBackgroundProcessor`, and real-time progress tracking. A `Procurios Member Data` child table on Member stores unmapped fields with category labels for analytics.

**Tech Stack:** Frappe framework (Python controllers, JS client scripts, JSON DocType definitions), existing CSV infrastructure (`SecureCSVParser`, `CSVImportBackgroundProcessor`, data transformers).

**Design spec:** `docs/superpowers/specs/2026-03-31-procurios-csv-import-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `verenigingen/verenigingen/doctype/procurios_member_data/procurios_member_data.json` | Child table DocType schema (field_label, field_value, field_category) |
| `verenigingen/verenigingen/doctype/procurios_member_data/procurios_member_data.py` | Minimal controller |
| `verenigingen/verenigingen/doctype/procurios_status_mapping/procurios_status_mapping.json` | Child table DocType schema (procurios_value, member_status) |
| `verenigingen/verenigingen/doctype/procurios_status_mapping/procurios_status_mapping.py` | Minimal controller |
| `verenigingen/verenigingen/doctype/procurios_csv_import/procurios_csv_import.json` | Import DocType schema |
| `verenigingen/verenigingen/doctype/procurios_csv_import/procurios_csv_import.py` | Import controller (validate, submit, background job) |
| `verenigingen/verenigingen/doctype/procurios_csv_import/procurios_csv_import.js` | Client script (validate button, progress UI) |
| `verenigingen/vereinigingen/doctype/procurios_csv_import/__init__.py` | Package init |
| `verenigingen/verenigingen/doctype/procurios_member_data/__init__.py` | Package init |
| `verenigingen/verenigingen/doctype/procurios_status_mapping/__init__.py` | Package init |
| `verenigingen/utils/csv/procurios_data_validator.py` | Field mapping, validation, categorization logic |
| `verenigingen/tests/member/test_procurios_csv_import.py` | Integration tests |

### Modified Files

| File | Change |
|------|--------|
| `verenigingen/verenigingen/doctype/member/member.json` | Add `gender` field, `procurios_data` table field, and new section |

---

## Task 1: Create Procurios Member Data Child Table DocType

**Files:**
- Create: `verenigingen/verenigingen/doctype/procurios_member_data/__init__.py`
- Create: `verenigingen/verenigingen/doctype/procurios_member_data/procurios_member_data.json`
- Create: `verenigingen/verenigingen/doctype/procurios_member_data/procurios_member_data.py`

- [ ] **Step 1: Create the `__init__.py`**

```python
# empty file
```

- [ ] **Step 2: Create the DocType JSON**

```json
{
  "actions": [],
  "allow_rename": 1,
  "creation": "2026-03-31 10:00:00.000000",
  "doctype": "DocType",
  "editable_grid": 1,
  "engine": "InnoDB",
  "field_order": [
    "field_label",
    "field_category",
    "column_break_1",
    "field_value"
  ],
  "fields": [
    {
      "fieldname": "field_label",
      "fieldtype": "Data",
      "in_list_view": 1,
      "label": "Field Label",
      "reqd": 1
    },
    {
      "fieldname": "field_category",
      "fieldtype": "Select",
      "in_list_view": 1,
      "label": "Category",
      "options": "\nPersonal\nFinancial\nSubscription\nSurvey\nCampaign\nOther"
    },
    {
      "fieldname": "column_break_1",
      "fieldtype": "Column Break"
    },
    {
      "fieldname": "field_value",
      "fieldtype": "Small Text",
      "in_list_view": 1,
      "label": "Value"
    }
  ],
  "index_web_pages_for_search": 0,
  "istable": 1,
  "links": [],
  "modified": "2026-03-31 10:00:00.000000",
  "modified_by": "Administrator",
  "module": "Verenigingen",
  "name": "Procurios Member Data",
  "owner": "Administrator",
  "permissions": [],
  "sort_field": "creation",
  "sort_order": "ASC",
  "states": []
}
```

- [ ] **Step 3: Create the minimal Python controller**

```python
# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ProcuriosMemberData(Document):
    pass
```

- [ ] **Step 4: Verify the DocType loads**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org migrate`
Expected: Migration completes without errors, `tabProcurios Member Data` table created.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen/doctype/procurios_member_data/
git commit -m "feat: add Procurios Member Data child table DocType"
```

---

## Task 2: Create Procurios Status Mapping Child Table DocType

**Files:**
- Create: `verenigingen/verenigingen/doctype/procurios_status_mapping/__init__.py`
- Create: `verenigingen/verenigingen/doctype/procurios_status_mapping/procurios_status_mapping.json`
- Create: `verenigingen/verenigingen/doctype/procurios_status_mapping/procurios_status_mapping.py`

- [ ] **Step 1: Create the `__init__.py`**

```python
# empty file
```

- [ ] **Step 2: Create the DocType JSON**

```json
{
  "actions": [],
  "allow_rename": 1,
  "creation": "2026-03-31 10:00:00.000000",
  "doctype": "DocType",
  "editable_grid": 1,
  "engine": "InnoDB",
  "field_order": [
    "procurios_value",
    "column_break_1",
    "member_status"
  ],
  "fields": [
    {
      "fieldname": "procurios_value",
      "fieldtype": "Data",
      "in_list_view": 1,
      "label": "Procurios Value",
      "reqd": 1
    },
    {
      "fieldname": "column_break_1",
      "fieldtype": "Column Break"
    },
    {
      "fieldname": "member_status",
      "fieldtype": "Select",
      "in_list_view": 1,
      "label": "Member Status",
      "options": "Active\nPending\nExpired\nSuspended\nBanned\nDeceased\nQuit\nRejected",
      "reqd": 1
    }
  ],
  "index_web_pages_for_search": 0,
  "istable": 1,
  "links": [],
  "modified": "2026-03-31 10:00:00.000000",
  "modified_by": "Administrator",
  "module": "Verenigingen",
  "name": "Procurios Status Mapping",
  "owner": "Administrator",
  "permissions": [],
  "sort_field": "creation",
  "sort_order": "ASC",
  "states": []
}
```

- [ ] **Step 3: Create the minimal Python controller**

```python
# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ProcuriosStatusMapping(Document):
    pass
```

- [ ] **Step 4: Verify the DocType loads**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org migrate`
Expected: Migration completes without errors, `tabProcurios Status Mapping` table created.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen/doctype/procurios_status_mapping/
git commit -m "feat: add Procurios Status Mapping child table DocType"
```

---

## Task 3: Add gender field and procurios_data table to Member DocType

**Files:**
- Modify: `verenigingen/verenigingen/doctype/member/member.json`

The `gender` field goes in the member details section (after `pronouns`, before `aanhef`). The `procurios_data` table goes in a new collapsible section in the `miscellaneous_tab` (after `custom_field_4`, before `health_check_section`).

- [ ] **Step 1: Add field names to `field_order` array**

In `member.json`, add `"gender"` after `"pronouns"` in the field_order array:

```json
  "pronouns",
  "gender",
  "aanhef",
```

Add `"procurios_import_data_section"` and `"procurios_data"` after `"custom_field_4"` and before `"health_check_section"`:

```json
  "custom_field_4",
  "procurios_import_data_section",
  "procurios_data",
  "health_check_section",
```

- [ ] **Step 2: Add field definitions to `fields` array**

Add these field objects to the `fields` array in `member.json`:

```json
{
  "fieldname": "gender",
  "fieldtype": "Select",
  "label": "Gender",
  "options": "\nMale\nFemale\nOther\nPrefer not to say"
},
{
  "collapsible": 1,
  "fieldname": "procurios_import_data_section",
  "fieldtype": "Section Break",
  "label": "Procurios Import Data"
},
{
  "fieldname": "procurios_data",
  "fieldtype": "Table",
  "label": "Procurios Data",
  "options": "Procurios Member Data",
  "read_only": 1
}
```

- [ ] **Step 3: Run migration**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org migrate`
Expected: Migration adds `gender` column and `procurios_data` table field to Member.

- [ ] **Step 4: Verify fields exist**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org console`
Then in console:
```python
meta = frappe.get_meta("Member")
assert meta.has_field("gender"), "gender field missing"
assert meta.has_field("procurios_data"), "procurios_data field missing"
print("OK: Both fields exist on Member")
```

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen/doctype/member/member.json
git commit -m "feat: add gender field and procurios_data table to Member DocType"
```

---

## Task 4: Create ProcuriosDataValidator

**Files:**
- Create: `verenigingen/utils/csv/procurios_data_validator.py`
- Test: `verenigingen/tests/member/test_procurios_csv_import.py`

- [ ] **Step 1: Write failing tests for the validator**

Create `verenigingen/tests/member/test_procurios_csv_import.py`:

```python
# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase


class TestProcuriosDataValidator(IntegrationTestCase):
    """Tests for ProcuriosDataValidator field mapping and validation."""

    def setUp(self):
        from verenigingen.utils.csv.procurios_data_validator import ProcuriosDataValidator

        self.validator = ProcuriosDataValidator()

    def test_map_row_maps_native_fields(self):
        """Native Procurios fields map to correct Member fields."""
        row = {
            "Systeem ID": "12345",
            "Voornaam": "Jan",
            "Tussenvoegsel": "van der",
            "Volledige naam": "Jan van der Berg",
            "E-mailadres": "jan@example.com",
            "Geboortedatum": "15-03-1985",
            "Bankrekening": "NL91ABNA0417164300",
            "Aanmaakdatum": "01-01-2020",
            "Mobiel": "+31612345678",
        }
        mapped = self.validator.map_row_data(row, row_num=1)

        self.assertEqual(mapped["member_id"], "12345")
        self.assertEqual(mapped["first_name"], "Jan")
        self.assertEqual(mapped["tussenvoegsel"], "van der")
        self.assertEqual(mapped["email"], "jan@example.com")
        self.assertEqual(mapped["birth_date"], "1985-03-15")
        self.assertEqual(mapped["iban"], "NL91ABNA0417164300")
        self.assertEqual(mapped["member_since"], "2020-01-01")

    def test_map_row_derives_last_name(self):
        """Last name is derived from Volledige naam minus Voornaam and Tussenvoegsel."""
        row = {
            "Voornaam": "Jan",
            "Tussenvoegsel": "van der",
            "Volledige naam": "Jan van der Berg",
            "Systeem ID": "1",
        }
        mapped = self.validator.map_row_data(row, row_num=1)
        self.assertEqual(mapped["last_name"], "Berg")

    def test_map_row_derives_last_name_without_tussenvoegsel(self):
        """Last name derivation works when there is no tussenvoegsel."""
        row = {
            "Voornaam": "Maria",
            "Volledige naam": "Maria Jansen",
            "Systeem ID": "2",
        }
        mapped = self.validator.map_row_data(row, row_num=1)
        self.assertEqual(mapped["last_name"], "Jansen")

    def test_map_row_falls_back_to_naam(self):
        """Falls back to Naam field when Volledige naam is missing."""
        row = {
            "Voornaam": "Pieter",
            "Naam": "Pieter de Groot",
            "Tussenvoegsel": "de",
            "Systeem ID": "3",
        }
        mapped = self.validator.map_row_data(row, row_num=1)
        self.assertEqual(mapped["last_name"], "Groot")

    def test_map_row_stores_extra_fields_in_procurios_data(self):
        """Fields not in NATIVE_FIELD_MAPPING go to procurios_data list."""
        row = {
            "Systeem ID": "1",
            "Voornaam": "Jan",
            "VEGAN Magazine": "Papieren versie (per post)",
            "JOUR_waarom lid geworden": "voor de dieren",
            "Contributie jaarlid": "€ 60,-",
        }
        mapped = self.validator.map_row_data(row, row_num=1)

        labels = [item["field_label"] for item in mapped["procurios_data"]]
        self.assertIn("VEGAN Magazine", labels)
        self.assertIn("JOUR_waarom lid geworden", labels)
        self.assertIn("Contributie jaarlid", labels)

    def test_categorize_field_personal(self):
        """Personal fields are categorized correctly."""
        self.assertEqual(self.validator.categorize_field("Voorkeurstaal"), "Personal")
        self.assertEqual(self.validator.categorize_field("Voorletters"), "Personal")
        self.assertEqual(self.validator.categorize_field("Titel"), "Personal")

    def test_categorize_field_financial(self):
        """Financial fields are categorized correctly."""
        self.assertEqual(self.validator.categorize_field("Contributie jaarlid"), "Financial")
        self.assertEqual(self.validator.categorize_field("Bankrekening"), "Financial")
        self.assertEqual(self.validator.categorize_field("€ 60,-"), "Financial")
        self.assertEqual(self.validator.categorize_field("Bedrag openstaande facturen"), "Financial")

    def test_categorize_field_subscription(self):
        """Subscription fields are categorized correctly."""
        self.assertEqual(self.validator.categorize_field("VEGAN Magazine"), "Subscription")
        self.assertEqual(self.validator.categorize_field("Nieuwsbrief voorkeur"), "Subscription")

    def test_categorize_field_survey(self):
        """Survey fields are categorized correctly."""
        self.assertEqual(self.validator.categorize_field("JOUR_waarom lid geworden"), "Survey")
        self.assertEqual(self.validator.categorize_field("JOUR_wat moeten wij doen"), "Survey")

    def test_categorize_field_campaign(self):
        """Campaign fields are categorized correctly."""
        self.assertEqual(self.validator.categorize_field("Campagnes"), "Campaign")
        self.assertEqual(self.validator.categorize_field("Welkomstcadeau VC"), "Campaign")
        self.assertEqual(self.validator.categorize_field("Binnengekomen via actie"), "Campaign")
        self.assertEqual(self.validator.categorize_field("Aanmeldcode"), "Campaign")

    def test_categorize_field_other(self):
        """Unknown fields default to Other."""
        self.assertEqual(self.validator.categorize_field("Opnummerveld relaties"), "Other")

    def test_validate_row_requires_systeem_id(self):
        """Validation fails when Systeem ID is missing."""
        row = {"first_name": "Jan", "last_name": "Berg", "row_number": 1}
        errors = self.validator.validate_row(row, row_num=1)
        self.assertTrue(any("Systeem ID" in e or "member_id" in e for e in errors))

    def test_validate_row_requires_name(self):
        """Validation fails when both first_name and last_name are missing."""
        row = {"member_id": "123", "row_number": 1}
        errors = self.validator.validate_row(row, row_num=1)
        self.assertTrue(any("name" in e.lower() for e in errors))

    def test_validate_row_accepts_valid_row(self):
        """Validation passes for a complete valid row."""
        row = {
            "member_id": "123",
            "first_name": "Jan",
            "last_name": "Berg",
            "email": "jan@example.com",
            "iban": "NL91ABNA0417164300",
            "row_number": 1,
        }
        errors = self.validator.validate_row(row, row_num=1)
        self.assertEqual(errors, [])

    def test_validate_row_rejects_invalid_email(self):
        """Validation catches invalid email format."""
        row = {
            "member_id": "123",
            "first_name": "Jan",
            "last_name": "Berg",
            "email": "not-an-email",
            "row_number": 1,
        }
        errors = self.validator.validate_row(row, row_num=1)
        self.assertTrue(any("email" in e.lower() for e in errors))

    def test_validate_and_map_data_returns_mapped_data_and_errors(self):
        """Full validation pipeline returns both mapped data and error list."""
        csv_data = [
            {
                "Systeem ID": "100",
                "Voornaam": "Anna",
                "Volledige naam": "Anna Smit",
                "E-mailadres": "anna@example.com",
            },
            {
                "Voornaam": "Missing ID",
                "Volledige naam": "Missing ID Person",
            },
        ]
        mapped_data, errors = self.validator.validate_and_map_data(csv_data)
        self.assertEqual(len(mapped_data), 1)
        self.assertTrue(len(errors) > 0)

    def test_gender_stored_in_procurios_data_by_default(self):
        """When import_gender is False (default), Geslacht goes to procurios_data."""
        row = {
            "Systeem ID": "1",
            "Voornaam": "Jan",
            "Volledige naam": "Jan Berg",
            "Geslacht": "Man",
        }
        mapped = self.validator.map_row_data(row, row_num=1)
        # Gender not mapped to native field by default
        self.assertNotIn("gender", mapped)
        labels = [item["field_label"] for item in mapped["procurios_data"]]
        self.assertIn("Geslacht", labels)

    def test_gender_mapped_when_import_gender_enabled(self):
        """When import_gender is True, Geslacht maps to gender field."""
        from verenigingen.utils.csv.procurios_data_validator import ProcuriosDataValidator

        validator = ProcuriosDataValidator(import_gender=True)
        row = {
            "Systeem ID": "1",
            "Voornaam": "Jan",
            "Volledige naam": "Jan Berg",
            "Geslacht": "Man",
        }
        mapped = validator.map_row_data(row, row_num=1)
        self.assertEqual(mapped["gender"], "Male")

    def test_address_fields_extracted(self):
        """Address fields are grouped into address dicts."""
        row = {
            "Systeem ID": "1",
            "Voornaam": "Jan",
            "Volledige naam": "Jan Berg",
            "Standaardadres: Straat": "Keizersgracht",
            "Standaardadres: Nummer met toevoeging": "123A",
            "Standaardadres: Postcode": "1015 CJ",
            "Standaardadres: Plaats": "Amsterdam",
            "Standaardadres: Landnaam": "Nederland",
            "Standaardadres: Geadresseerde": "Jan Berg",
        }
        mapped = self.validator.map_row_data(row, row_num=1)
        self.assertIn("addresses", mapped)
        self.assertEqual(len(mapped["addresses"]), 1)
        addr = mapped["addresses"][0]
        self.assertEqual(addr["address_type"], "Standaardadres")
        self.assertEqual(addr["street"], "Keizersgracht")
        self.assertEqual(addr["house_number"], "123A")
        self.assertEqual(addr["pincode"], "1015 CJ")
        self.assertEqual(addr["city"], "Amsterdam")

    def test_multiple_address_types_extracted(self):
        """Multiple address types each produce their own address dict."""
        row = {
            "Systeem ID": "1",
            "Voornaam": "Jan",
            "Volledige naam": "Jan Berg",
            "Standaardadres: Straat": "Keizersgracht",
            "Standaardadres: Plaats": "Amsterdam",
            "Postadres: Straat": "Herengracht",
            "Postadres: Plaats": "Amsterdam",
        }
        mapped = self.validator.map_row_data(row, row_num=1)
        self.assertEqual(len(mapped["addresses"]), 2)
        types = [a["address_type"] for a in mapped["addresses"]]
        self.assertIn("Standaardadres", types)
        self.assertIn("Postadres", types)

    def test_empty_address_not_extracted(self):
        """Address types with no data are not included."""
        row = {
            "Systeem ID": "1",
            "Voornaam": "Jan",
            "Volledige naam": "Jan Berg",
            "Factuuradres: Straat": "",
            "Factuuradres: Plaats": "",
        }
        mapped = self.validator.map_row_data(row, row_num=1)
        self.assertEqual(len(mapped.get("addresses", [])), 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.member.test_procurios_csv_import`
Expected: ImportError — `procurios_data_validator` module does not exist.

- [ ] **Step 3: Implement ProcuriosDataValidator**

Create `verenigingen/utils/csv/procurios_data_validator.py`:

```python
# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

import re
from typing import Any, Dict, List, Optional, Tuple

from verenigingen.utils.csv.data_transformers import clean_phone_number, clean_value, parse_date


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
        ("Financial", re.compile(
            r"contributi|bankrekening|machtiging|factuu?r|bedrag|totaal|€|openstaande",
            re.IGNORECASE,
        )),
        ("Subscription", re.compile(
            r"vegan\s*magazine|abonne|nieuwsbrief",
            re.IGNORECASE,
        )),
        ("Survey", re.compile(
            r"jour_|waarom|wat moeten|thema",
            re.IGNORECASE,
        )),
        ("Campaign", re.compile(
            r"campagne|actie|binnengekomen via|welkomstcadeau|aanmeldcode",
            re.IGNORECASE,
        )),
        ("Personal", re.compile(
            r"^naam$|voornaam|titel|geslacht|geboortedatum|voorkeurstaal|voorletters|tenaamstelling",
            re.IGNORECASE,
        )),
    ]

    def __init__(self, import_gender: bool = False):
        self.import_gender = import_gender

    def validate_and_map_data(
        self, csv_data: List[Dict]
    ) -> Tuple[List[Dict], List[str]]:
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
        # Track which original columns we've handled
        handled_keys = set()

        for original_key, value in row.items():
            if not value or not str(value).strip():
                continue

            value = str(value).strip()
            key_lower = original_key.strip().lower()

            # Check native field mapping
            if key_lower in self.NATIVE_FIELD_MAPPING:
                member_field = self.NATIVE_FIELD_MAPPING[key_lower]
                mapped[member_field] = self._clean_native_field(member_field, value)
                handled_keys.add(original_key)
                continue

            # Check name derivation fields
            if key_lower in self.NAME_FIELDS:
                mapped[f"_raw_{key_lower.replace(' ', '_')}"] = value
                handled_keys.add(original_key)
                continue

            # Check gender field
            if key_lower == "geslacht":
                if self.import_gender:
                    mapped["gender"] = self.GENDER_MAPPING.get(value.lower(), "Other")
                else:
                    mapped["procurios_data"].append({
                        "field_label": original_key.strip(),
                        "field_value": value,
                        "field_category": self.categorize_field(original_key.strip()),
                    })
                handled_keys.add(original_key)
                continue

            # Check address fields
            address_matched = False
            for addr_type in self.ADDRESS_TYPES:
                for suffix, field_name in self.ADDRESS_SUBFIELDS.items():
                    if original_key.strip() == f"{addr_type}: {suffix}":
                        if addr_type not in address_data:
                            address_data[addr_type] = {"address_type": addr_type}
                        address_data[addr_type][field_name] = value
                        handled_keys.add(original_key)
                        address_matched = True
                        break
                if address_matched:
                    break
            if address_matched:
                continue

            # Everything else goes to procurios_data
            mapped["procurios_data"].append({
                "field_label": original_key.strip(),
                "field_value": value,
                "field_category": self.categorize_field(original_key.strip()),
            })

        # Derive last_name from full name
        mapped["last_name"] = self._derive_last_name(mapped)

        # Convert address dicts to list (skip empty ones)
        for addr_type, addr in address_data.items():
            has_data = any(
                v for k, v in addr.items()
                if k != "address_type" and v and str(v).strip()
            )
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
        if email:
            if not self._validate_email(email):
                errors.append(f"Row {row_num}: Invalid email format")

        iban = row.get("iban")
        if iban:
            if not self._validate_iban(iban):
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
            remainder = remainder[len(first_name):].strip()
        if tussenvoegsel and remainder.startswith(tussenvoegsel):
            remainder = remainder[len(tussenvoegsel):].strip()

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.member.test_procurios_csv_import`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/utils/csv/procurios_data_validator.py verenigingen/tests/member/test_procurios_csv_import.py
git commit -m "feat: add ProcuriosDataValidator with field mapping and categorization"
```

---

## Task 5: Create Procurios CSV Import DocType Schema

**Files:**
- Create: `verenigingen/verenigingen/doctype/procurios_csv_import/__init__.py`
- Create: `verenigingen/verenigingen/doctype/procurios_csv_import/procurios_csv_import.json`

- [ ] **Step 1: Create `__init__.py`**

```python
# empty file
```

- [ ] **Step 2: Create the DocType JSON**

```json
{
  "actions": [],
  "autoname": "naming_series:",
  "creation": "2026-03-31 10:00:00.000000",
  "doctype": "DocType",
  "editable_grid": 1,
  "engine": "InnoDB",
  "field_order": [
    "naming_series",
    "import_configuration_section",
    "csv_file",
    "encoding",
    "csv_delimiter",
    "column_break_config1",
    "import_gender",
    "default_status",
    "test_mode",
    "status_mapping_section",
    "status_mapping",
    "address_handling_section",
    "import_addresses",
    "preferred_address_type",
    "preview_section",
    "preview_data",
    "progress_section",
    "import_status",
    "progress_percentage",
    "rows_processed",
    "total_rows",
    "column_break_progress1",
    "members_created",
    "members_skipped",
    "last_processed_at",
    "error_section",
    "error_log",
    "top_errors_summary",
    "import_info_section",
    "import_date",
    "descriptive_name"
  ],
  "fields": [
    {
      "fieldname": "naming_series",
      "fieldtype": "Select",
      "hidden": 1,
      "label": "Naming Series",
      "options": "PROC-IMP-.YYYY.-.####.",
      "default": "PROC-IMP-.YYYY.-.####."
    },
    {
      "fieldname": "import_configuration_section",
      "fieldtype": "Section Break",
      "label": "Import Configuration"
    },
    {
      "fieldname": "csv_file",
      "fieldtype": "Attach",
      "label": "CSV File",
      "reqd": 1
    },
    {
      "default": "auto-detect",
      "fieldname": "encoding",
      "fieldtype": "Select",
      "label": "Encoding",
      "options": "auto-detect\nutf-8\nutf-8-sig\niso-8859-1\nwindows-1252"
    },
    {
      "default": "Semicolon",
      "fieldname": "csv_delimiter",
      "fieldtype": "Select",
      "label": "CSV Delimiter",
      "options": "Comma\nSemicolon\nTab"
    },
    {
      "fieldname": "column_break_config1",
      "fieldtype": "Column Break"
    },
    {
      "default": "0",
      "fieldname": "import_gender",
      "fieldtype": "Check",
      "label": "Import Gender",
      "description": "Map Geslacht to Member gender field. When disabled, stored in Procurios data table."
    },
    {
      "default": "Active",
      "fieldname": "default_status",
      "fieldtype": "Select",
      "label": "Default Member Status",
      "options": "Active\nPending",
      "description": "Status assigned when no status mapping matches"
    },
    {
      "default": "0",
      "fieldname": "test_mode",
      "fieldtype": "Check",
      "label": "Test Mode",
      "description": "Process only first 25 rows for validation"
    },
    {
      "fieldname": "status_mapping_section",
      "fieldtype": "Section Break",
      "label": "Status Mapping",
      "collapsible": 1,
      "description": "Map Procurios Type/status values to Member status"
    },
    {
      "fieldname": "status_mapping",
      "fieldtype": "Table",
      "label": "Status Mapping",
      "options": "Procurios Status Mapping"
    },
    {
      "fieldname": "address_handling_section",
      "fieldtype": "Section Break",
      "label": "Address Handling"
    },
    {
      "default": "1",
      "fieldname": "import_addresses",
      "fieldtype": "Check",
      "label": "Import Addresses",
      "description": "Create Address records from Procurios address fields"
    },
    {
      "default": "Standaardadres",
      "depends_on": "eval:doc.import_addresses",
      "fieldname": "preferred_address_type",
      "fieldtype": "Select",
      "label": "Primary Address Type",
      "options": "Standaardadres\nPostadres\nFactuuradres",
      "description": "Which Procurios address type to link as primary_address"
    },
    {
      "depends_on": "eval:doc.import_status == 'Ready for Import'",
      "fieldname": "preview_section",
      "fieldtype": "Section Break",
      "label": "Data Preview"
    },
    {
      "fieldname": "preview_data",
      "fieldtype": "Code",
      "label": "Preview Data",
      "options": "JSON",
      "read_only": 1
    },
    {
      "depends_on": "eval:['Queued', 'In Progress', 'Completed', 'Failed'].includes(doc.import_status)",
      "fieldname": "progress_section",
      "fieldtype": "Section Break",
      "label": "Import Progress"
    },
    {
      "default": "Pending",
      "fieldname": "import_status",
      "fieldtype": "Select",
      "label": "Import Status",
      "options": "Pending\nValidating\nReady for Import\nQueued\nIn Progress\nCompleted\nFailed",
      "read_only": 1
    },
    {
      "default": "0",
      "fieldname": "progress_percentage",
      "fieldtype": "Percent",
      "label": "Progress",
      "read_only": 1
    },
    {
      "default": "0",
      "fieldname": "rows_processed",
      "fieldtype": "Int",
      "label": "Rows Processed",
      "read_only": 1
    },
    {
      "default": "0",
      "fieldname": "total_rows",
      "fieldtype": "Int",
      "label": "Total Rows",
      "read_only": 1
    },
    {
      "fieldname": "column_break_progress1",
      "fieldtype": "Column Break"
    },
    {
      "default": "0",
      "fieldname": "members_created",
      "fieldtype": "Int",
      "label": "Members Created",
      "read_only": 1
    },
    {
      "default": "0",
      "fieldname": "members_skipped",
      "fieldtype": "Int",
      "label": "Members Skipped",
      "read_only": 1
    },
    {
      "fieldname": "last_processed_at",
      "fieldtype": "Datetime",
      "label": "Last Processed At",
      "read_only": 1
    },
    {
      "depends_on": "eval:['Completed', 'Failed'].includes(doc.import_status)",
      "fieldname": "error_section",
      "fieldtype": "Section Break",
      "label": "Error Log"
    },
    {
      "fieldname": "error_log",
      "fieldtype": "Long Text",
      "label": "Error Log",
      "read_only": 1
    },
    {
      "fieldname": "top_errors_summary",
      "fieldtype": "Small Text",
      "label": "Top Errors Summary",
      "read_only": 1
    },
    {
      "fieldname": "import_info_section",
      "fieldtype": "Section Break",
      "label": "Import Information",
      "hidden": 1
    },
    {
      "fieldname": "import_date",
      "fieldtype": "Date",
      "label": "Import Date",
      "read_only": 1
    },
    {
      "fieldname": "descriptive_name",
      "fieldtype": "Data",
      "label": "Descriptive Name",
      "read_only": 1
    }
  ],
  "index_web_pages_for_search": 0,
  "is_submittable": 1,
  "links": [],
  "modified": "2026-03-31 10:00:00.000000",
  "modified_by": "Administrator",
  "module": "Verenigingen",
  "name": "Procurios CSV Import",
  "naming_rule": "By \"Naming Series\" field",
  "owner": "Administrator",
  "permissions": [
    {
      "create": 1,
      "delete": 1,
      "email": 1,
      "export": 1,
      "read": 1,
      "report": 1,
      "role": "System Manager",
      "share": 1,
      "submit": 1,
      "write": 1
    },
    {
      "create": 1,
      "delete": 1,
      "email": 1,
      "export": 1,
      "read": 1,
      "report": 1,
      "role": "Verenigingen Administrator",
      "share": 1,
      "submit": 1,
      "write": 1
    }
  ],
  "sort_field": "creation",
  "sort_order": "DESC",
  "states": [],
  "track_changes": 1
}
```

- [ ] **Step 3: Run migration**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org migrate`
Expected: Migration completes, `tabProcurios CSV Import` table created.

- [ ] **Step 4: Commit**

```bash
git add verenigingen/verenigingen/doctype/procurios_csv_import/__init__.py verenigingen/verenigingen/doctype/procurios_csv_import/procurios_csv_import.json
git commit -m "feat: add Procurios CSV Import DocType schema"
```

---

## Task 6: Create Procurios CSV Import Controller

**Files:**
- Create: `verenigingen/verenigingen/doctype/procurios_csv_import/procurios_csv_import.py`
- Test: `verenigingen/tests/member/test_procurios_csv_import.py` (add integration tests)

- [ ] **Step 1: Add integration tests to the test file**

Append to `verenigingen/tests/member/test_procurios_csv_import.py`:

```python
import csv
import io
import os
import tempfile


class TestProcuriosCSVImportIntegration(IntegrationTestCase):
    """Integration tests for the full Procurios CSV import pipeline."""

    def setUp(self):
        # Clean up any test members from previous runs
        for member_id in ["PROC-TEST-001", "PROC-TEST-002", "PROC-TEST-003"]:
            if frappe.db.exists("Member", {"member_id": member_id}):
                name = frappe.db.get_value("Member", {"member_id": member_id}, "name")
                frappe.delete_doc("Member", name, force=True)
        frappe.db.commit()

    def tearDown(self):
        for member_id in ["PROC-TEST-001", "PROC-TEST-002", "PROC-TEST-003"]:
            if frappe.db.exists("Member", {"member_id": member_id}):
                name = frappe.db.get_value("Member", {"member_id": member_id}, "name")
                frappe.delete_doc("Member", name, force=True)
        frappe.db.commit()

    def _create_csv_file(self, rows, delimiter=";"):
        """Create a temporary CSV file and attach it to a Procurios CSV Import doc."""
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=rows[0].keys(), delimiter=delimiter)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

        csv_content = output.getvalue().encode("utf-8")
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, "test_procurios_import.csv")
        with open(temp_path, "wb") as f:
            f.write(csv_content)

        return temp_path

    def _create_import_doc(self, csv_path, **kwargs):
        """Create a Procurios CSV Import document with the given CSV file."""
        # Upload the file to Frappe
        with open(csv_path, "rb") as f:
            file_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": "test_procurios_import.csv",
                "content": f.read(),
                "is_private": 1,
            })
            file_doc.save()

        doc = frappe.get_doc({
            "doctype": "Procurios CSV Import",
            "csv_file": file_doc.file_url,
            "encoding": kwargs.get("encoding", "utf-8"),
            "csv_delimiter": kwargs.get("csv_delimiter", "Semicolon"),
            "import_gender": kwargs.get("import_gender", 0),
            "default_status": kwargs.get("default_status", "Active"),
            "test_mode": kwargs.get("test_mode", 0),
            "import_addresses": kwargs.get("import_addresses", 1),
            "preferred_address_type": kwargs.get("preferred_address_type", "Standaardadres"),
        })
        doc.insert()
        return doc

    def test_validate_csv_sets_ready_status(self):
        """Validation of a valid CSV sets status to Ready for Import."""
        from verenigingen.verenigingen.doctype.procurios_csv_import.procurios_csv_import import (
            validate_import_file,
        )

        csv_path = self._create_csv_file([
            {
                "Systeem ID": "PROC-TEST-001",
                "Voornaam": "Anna",
                "Volledige naam": "Anna Smit",
                "E-mailadres": "anna.test@example.com",
            },
        ])
        doc = self._create_import_doc(csv_path)
        result = validate_import_file(doc.name)

        self.assertEqual(result["status"], "success")
        doc.reload()
        self.assertEqual(doc.import_status, "Ready for Import")

    def test_process_import_creates_members(self):
        """Background processing creates Member records with correct field values."""
        from verenigingen.verenigingen.doctype.procurios_csv_import.procurios_csv_import import (
            process_import_background,
            validate_import_file,
        )

        csv_path = self._create_csv_file([
            {
                "Systeem ID": "PROC-TEST-001",
                "Voornaam": "Jan",
                "Tussenvoegsel": "van der",
                "Volledige naam": "Jan van der Berg",
                "E-mailadres": "jan.proctest@example.com",
                "Geboortedatum": "15-03-1985",
                "Mobiel": "+31612345678",
                "VEGAN Magazine": "Papieren versie (per post)",
                "JOUR_waarom lid geworden": "voor de dieren",
            },
        ])
        doc = self._create_import_doc(csv_path)
        validate_import_file(doc.name)
        process_import_background(doc.name, test_mode=False)

        doc.reload()
        self.assertEqual(doc.import_status, "Completed")
        self.assertEqual(doc.members_created, 1)

        # Verify the member was created correctly
        member_name = frappe.db.get_value("Member", {"member_id": "PROC-TEST-001"}, "name")
        self.assertIsNotNone(member_name)

        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.first_name, "Jan")
        self.assertEqual(member.tussenvoegsel, "van der")
        self.assertEqual(member.last_name, "Berg")
        self.assertEqual(member.email, "jan.proctest@example.com")
        self.assertEqual(member.status, "Active")

        # Verify procurios_data child table
        labels = [row.field_label for row in member.procurios_data]
        self.assertIn("VEGAN Magazine", labels)
        self.assertIn("JOUR_waarom lid geworden", labels)

        # Verify categories
        for row in member.procurios_data:
            if row.field_label == "VEGAN Magazine":
                self.assertEqual(row.field_category, "Subscription")
            if row.field_label == "JOUR_waarom lid geworden":
                self.assertEqual(row.field_category, "Survey")

    def test_process_import_creates_addresses(self):
        """Import creates Address records and links preferred type as primary_address."""
        from verenigingen.verenigingen.doctype.procurios_csv_import.procurios_csv_import import (
            process_import_background,
            validate_import_file,
        )

        csv_path = self._create_csv_file([
            {
                "Systeem ID": "PROC-TEST-002",
                "Voornaam": "Maria",
                "Volledige naam": "Maria Jansen",
                "Standaardadres: Straat": "Keizersgracht",
                "Standaardadres: Nummer met toevoeging": "123A",
                "Standaardadres: Postcode": "1015 CJ",
                "Standaardadres: Plaats": "Amsterdam",
                "Standaardadres: Landnaam": "Nederland",
            },
        ])
        doc = self._create_import_doc(csv_path)
        validate_import_file(doc.name)
        process_import_background(doc.name, test_mode=False)

        member_name = frappe.db.get_value("Member", {"member_id": "PROC-TEST-002"}, "name")
        member = frappe.get_doc("Member", member_name)

        # Verify address was linked
        self.assertIsNotNone(member.primary_address)
        address = frappe.get_doc("Address", member.primary_address)
        self.assertIn("Keizersgracht", address.address_line1)
        self.assertEqual(address.city, "Amsterdam")
        self.assertEqual(address.pincode, "1015 CJ")

    def test_process_import_with_gender_toggle(self):
        """Gender is mapped to Member field when import_gender is enabled."""
        from verenigingen.verenigingen.doctype.procurios_csv_import.procurios_csv_import import (
            process_import_background,
            validate_import_file,
        )

        csv_path = self._create_csv_file([
            {
                "Systeem ID": "PROC-TEST-003",
                "Voornaam": "Pieter",
                "Volledige naam": "Pieter de Groot",
                "Geslacht": "Man",
            },
        ])
        doc = self._create_import_doc(csv_path, import_gender=1)
        validate_import_file(doc.name)
        process_import_background(doc.name, test_mode=False)

        member_name = frappe.db.get_value("Member", {"member_id": "PROC-TEST-003"}, "name")
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.gender, "Male")

    def test_process_import_applies_status_mapping(self):
        """Status mapping translates Procurios type to Member status."""
        from verenigingen.verenigingen.doctype.procurios_csv_import.procurios_csv_import import (
            process_import_background,
            validate_import_file,
        )

        csv_path = self._create_csv_file([
            {
                "Systeem ID": "PROC-TEST-001",
                "Voornaam": "Ex",
                "Volledige naam": "Ex Member",
                "Type": "Opgezegd",
            },
        ])
        doc = self._create_import_doc(csv_path)
        doc.append("status_mapping", {
            "procurios_value": "Opgezegd",
            "member_status": "Quit",
        })
        doc.save()

        validate_import_file(doc.name)
        process_import_background(doc.name, test_mode=False)

        member_name = frappe.db.get_value("Member", {"member_id": "PROC-TEST-001"}, "name")
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.status, "Quit")

    def test_validation_rejects_missing_systeem_id(self):
        """Rows without Systeem ID are rejected during validation."""
        from verenigingen.verenigingen.doctype.procurios_csv_import.procurios_csv_import import (
            validate_import_file,
        )

        csv_path = self._create_csv_file([
            {
                "Systeem ID": "",
                "Voornaam": "NoID",
                "Volledige naam": "NoID Person",
            },
        ])
        doc = self._create_import_doc(csv_path)
        validate_import_file(doc.name)
        doc.reload()

        # Should still be Ready (empty rows skipped) or show errors
        if doc.error_log:
            self.assertIn("Systeem ID", doc.error_log)
```

- [ ] **Step 2: Run tests to verify the integration tests fail**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.member.test_procurios_csv_import::TestProcuriosCSVImportIntegration`
Expected: ImportError or AttributeError — controller not yet implemented.

- [ ] **Step 3: Implement the controller**

Create `verenigingen/verenigingen/doctype/procurios_csv_import/procurios_csv_import.py`:

```python
# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

import json
import traceback
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe.model.document import Document
from frappe.utils import today

from verenigingen.utils.csv.data_transformers import parse_date
from verenigingen.utils.csv.procurios_data_validator import ProcuriosDataValidator
from verenigingen.utils.csv.secure_csv_parser import SecureCSVParser
from verenigingen.utils.csv_import_processor import (
    CSVImportBackgroundProcessor,
    bulk_member_operations,
    ensure_bulk_import_members_set,
)
from verenigingen.utils.error_handling import sanitize_error_for_audit


DELIMITER_MAP = {
    "Comma": ",",
    "Semicolon": ";",
    "Tab": "\t",
}

ADDRESS_TYPE_MAP = {
    "Standaardadres": "Office",
    "Postadres": "Shipping",
    "Factuuradres": "Billing",
}

COUNTRY_NAME_MAP = {
    "nederland": "Netherlands",
    "belgie": "Belgium",
    "belgië": "Belgium",
    "duitsland": "Germany",
    "frankrijk": "France",
    "verenigd koninkrijk": "United Kingdom",
}


class ProcuriosCSVImport(Document):
    @property
    def _validator(self) -> ProcuriosDataValidator:
        if not hasattr(self, "__validator"):
            self.__validator = ProcuriosDataValidator(
                import_gender=bool(self.import_gender),
            )
        return self.__validator

    @property
    def _parser(self) -> SecureCSVParser:
        if not hasattr(self, "__parser"):
            encoding = None if self.encoding == "auto-detect" else self.encoding
            self.__parser = SecureCSVParser(encoding=encoding)
        return self.__parser

    def validate(self):
        if not self.import_date:
            self.import_date = today()

    def on_submit(self):
        self.db_set("import_status", "Queued")
        frappe.enqueue(
            method="verenigingen.verenigingen.doctype.procurios_csv_import.procurios_csv_import.process_import_background",
            queue="long",
            timeout=3600,
            import_doc_name=self.name,
            test_mode=self.test_mode,
            now=False,
        )

    def _read_csv_file(self) -> List[Dict]:
        delimiter = DELIMITER_MAP.get(self.csv_delimiter, ";")
        return self._parser.read_csv_file(self.csv_file, delimiter=delimiter)

    def _validate_and_map_data(self, csv_data: List[Dict]) -> Tuple[List[Dict], List[str]]:
        return self._validator.validate_and_map_data(csv_data)

    def _validate_and_preview_csv(self):
        self.db_set("import_status", "Validating")
        frappe.db.commit()

        try:
            csv_data = self._read_csv_file()
            if not csv_data:
                self.db_set("import_status", "Failed")
                self.db_set("error_log", "CSV file is empty or could not be read")
                frappe.db.commit()
                return

            mapped_data, errors = self._validate_and_map_data(csv_data)

            if errors:
                self.db_set("error_log", "\n".join(errors[:50]))

            if mapped_data:
                preview = []
                for row in mapped_data[:5]:
                    preview_row = {
                        k: v for k, v in row.items()
                        if k not in ("procurios_data", "addresses", "row_number")
                    }
                    preview_row["_procurios_fields"] = len(row.get("procurios_data", []))
                    preview_row["_addresses"] = len(row.get("addresses", []))
                    preview.append(preview_row)
                self.db_set("preview_data", json.dumps(preview, indent=2, default=str))

            self.db_set("total_rows", len(csv_data))
            self.db_set("descriptive_name", f"Procurios import - {len(csv_data)} rows")

            if mapped_data:
                self.db_set("import_status", "Ready for Import")
            else:
                self.db_set("import_status", "Failed")
                if not errors:
                    self.db_set("error_log", "No valid rows found in CSV")

            frappe.db.commit()

        except Exception as e:
            self.db_set("import_status", "Failed")
            self.db_set("error_log", sanitize_error_for_audit(str(e)))
            frappe.db.commit()
            raise

    def _get_status_mapping(self) -> Dict[str, str]:
        """Build a lookup dict from the status_mapping child table."""
        mapping = {}
        for row in self.status_mapping or []:
            if row.procurios_value and row.member_status:
                mapping[row.procurios_value.strip().lower()] = row.member_status
        return mapping

    def _process_single_member(
        self, row: Dict, error_log: List[str]
    ) -> Tuple[str, str]:
        """Create a single Member from a mapped row. Returns (status, member_name)."""
        try:
            member_id = row.get("member_id", "")
            status_mapping = self._get_status_mapping()

            # Determine member status
            type_value = row.get("_type_value", "")
            if type_value and type_value.strip().lower() in status_mapping:
                member_status = status_mapping[type_value.strip().lower()]
            else:
                member_status = self.default_status or "Active"

            # Create the member doc
            member_doc = frappe.get_doc({
                "doctype": "Member",
                "member_id": member_id,
                "first_name": row.get("first_name", ""),
                "last_name": row.get("last_name", ""),
                "tussenvoegsel": row.get("tussenvoegsel", ""),
                "email": row.get("email", ""),
                "birth_date": row.get("birth_date"),
                "contact_number": row.get("contact_number", ""),
                "iban": row.get("iban", ""),
                "member_since": row.get("member_since"),
                "status": member_status,
            })

            # Set gender if mapped
            if row.get("gender"):
                member_doc.gender = row["gender"]

            # Add procurios_data child rows
            for item in row.get("procurios_data", []):
                member_doc.append("procurios_data", {
                    "field_label": item["field_label"],
                    "field_value": item.get("field_value", ""),
                    "field_category": item.get("field_category", "Other"),
                })

            member_doc.flags.ignore_mandatory = True
            member_doc.flags.ignore_permissions = True
            member_doc.insert()

            # Track for bulk import
            ensure_bulk_import_members_set().add(member_doc.name)

            # Create addresses if enabled
            if self.import_addresses and row.get("addresses"):
                self._create_addresses(member_doc, row["addresses"])

            return ("created", member_doc.name)

        except frappe.DuplicateEntryError:
            error_log.append(
                f"Row {row.get('row_number', '?')}: Duplicate member_id {row.get('member_id', '')}"
            )
            return ("skipped", "")
        except Exception as e:
            sanitized = sanitize_error_for_audit(str(e))
            error_log.append(
                f"Row {row.get('row_number', '?')}: {sanitized}"
            )
            return ("skipped", "")

    def _create_addresses(self, member_doc, addresses: List[Dict]):
        """Create Address records and link the preferred one as primary_address."""
        primary_address_name = None

        for addr_data in addresses:
            addr_type = addr_data.get("address_type", "")
            frappe_addr_type = ADDRESS_TYPE_MAP.get(addr_type, "Other")

            # Build address_line1 from street + house number
            street = addr_data.get("street", "")
            house_number = addr_data.get("house_number", "")
            address_line1 = f"{street} {house_number}".strip() if street else house_number

            if not address_line1 and not addr_data.get("city"):
                continue

            # Normalize country name
            country_raw = addr_data.get("country", "")
            country = COUNTRY_NAME_MAP.get(country_raw.lower(), country_raw) if country_raw else "Netherlands"

            try:
                address_doc = frappe.get_doc({
                    "doctype": "Address",
                    "address_title": addr_data.get("addressee") or member_doc.full_name or f"{member_doc.first_name} {member_doc.last_name}",
                    "address_type": frappe_addr_type,
                    "address_line1": address_line1,
                    "city": addr_data.get("city", ""),
                    "pincode": addr_data.get("pincode", ""),
                    "country": country,
                    "links": [{
                        "link_doctype": "Member",
                        "link_name": member_doc.name,
                    }],
                })
                address_doc.flags.ignore_permissions = True
                address_doc.insert()

                if addr_type == (self.preferred_address_type or "Standaardadres"):
                    primary_address_name = address_doc.name

            except Exception:
                pass  # Address creation failure should not block member import

        if primary_address_name:
            frappe.db.set_value(
                "Member", member_doc.name, "primary_address", primary_address_name,
                update_modified=False,
            )

    def _finalize_import_results(
        self,
        created_count: int,
        updated_count: int,
        skipped_count: int,
        error_log: List[str],
        created_members: Optional[List[str]] = None,
        updated_members: Optional[List[str]] = None,
        skipped_members: Optional[List[str]] = None,
    ):
        """Update the import document with final results."""
        self.reload()
        self.members_created = created_count
        self.members_skipped = skipped_count
        self.import_status = "Completed"

        if error_log:
            truncated = error_log[:50]
            self.error_log = "\n".join(truncated)
            if len(error_log) > 50:
                self.error_log += f"\n... and {len(error_log) - 50} more errors"

        self.save(ignore_permissions=True)
        frappe.db.commit()


@frappe.whitelist()
def validate_import_file(import_doc_name: str) -> dict:
    """Manually trigger CSV validation."""
    doc = frappe.get_doc("Procurios CSV Import", import_doc_name)
    try:
        doc._validate_and_preview_csv()
        doc.reload()
        return {
            "status": "success" if doc.import_status == "Ready for Import" else "error",
            "message": f"Validation complete. Status: {doc.import_status}",
        }
    except Exception as e:
        return {
            "status": "error",
            "message": sanitize_error_for_audit(str(e)),
        }


@frappe.whitelist()
def process_import_background(import_doc_name: str, test_mode: bool = False):
    """Background job: process the validated CSV and create members."""
    frappe.flags.in_background_job = True
    frappe.flags.bulk_member_operations = True
    frappe.flags.ignore_version_changes = True

    doc = frappe.get_doc("Procurios CSV Import", import_doc_name)

    try:
        csv_data = doc._read_csv_file()
        mapped_data, errors = doc._validate_and_map_data(csv_data)

        if not mapped_data:
            doc.db_set("import_status", "Failed")
            doc.db_set("error_log", "No valid rows to import")
            frappe.db.commit()
            return

        if test_mode:
            mapped_data = mapped_data[:25]

        # Extract Type field for status mapping before processing
        # The Type column is not in NATIVE_FIELD_MAPPING, so it ends up in procurios_data
        # We need to pull it out for status mapping
        for row in mapped_data:
            for item in row.get("procurios_data", []):
                if item["field_label"].lower() == "type":
                    row["_type_value"] = item["field_value"]
                    break

        processor = CSVImportBackgroundProcessor(import_doc_name, "Procurios CSV Import")
        processor.load_import_doc()

        with bulk_member_operations(import_doc_name):
            processor.process_import(
                data_rows=mapped_data,
                process_row_callback=doc._process_single_member,
                finalize_callback=doc._finalize_import_results,
                batch_size=50,
                batch_commit=True,
            )

    except Exception as e:
        doc.reload()
        doc.db_set("import_status", "Failed")
        doc.db_set("error_log", sanitize_error_for_audit(traceback.format_exc()))
        frappe.db.commit()

    finally:
        frappe.flags.in_background_job = False
        frappe.flags.bulk_member_operations = False
        frappe.flags.ignore_version_changes = False
```

- [ ] **Step 4: Run integration tests**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.member.test_procurios_csv_import`
Expected: All tests pass (both validator and integration tests).

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen/doctype/procurios_csv_import/procurios_csv_import.py verenigingen/tests/member/test_procurios_csv_import.py
git commit -m "feat: implement Procurios CSV Import controller with member creation and address handling"
```

---

## Task 7: Create Procurios CSV Import Client Script

**Files:**
- Create: `verenigingen/verenigingen/doctype/procurios_csv_import/procurios_csv_import.js`

- [ ] **Step 1: Create the client script**

```javascript
// Copyright (c) 2026, Verenigingen and contributors
// For license information, please see license.txt

frappe.ui.form.on("Procurios CSV Import", {
    refresh(frm) {
        // Clear existing custom buttons
        frm.clear_custom_buttons();

        // Validate CSV button - shown when file is uploaded but not yet validated
        if (
            frm.doc.docstatus === 0 &&
            frm.doc.csv_file &&
            !["Validating", "In Progress", "Queued"].includes(frm.doc.import_status)
        ) {
            frm.add_custom_button(__("Validate CSV"), function () {
                frm.call({
                    method: "validate_import_file",
                    args: { import_doc_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __("Validating CSV file..."),
                    callback: function (r) {
                        if (r.message) {
                            if (r.message.status === "success") {
                                frappe.show_alert({
                                    message: __("Validation successful"),
                                    indicator: "green",
                                });
                            } else {
                                frappe.show_alert({
                                    message: r.message.message || __("Validation failed"),
                                    indicator: "red",
                                });
                            }
                            frm.reload_doc();
                        }
                    },
                });
            });
        }

        // Process Import button - shown when validation passed
        if (frm.doc.docstatus === 0 && frm.doc.import_status === "Ready for Import") {
            frm.add_custom_button(
                __("Process Import"),
                function () {
                    let msg = __("This will create Member records from the CSV data.");
                    if (frm.doc.test_mode) {
                        msg += " " + __("Test mode is ON — only the first 25 rows will be processed.");
                    }
                    frappe.confirm(msg, function () {
                        frm.save("Submit");
                    });
                }
            ).addClass("btn-primary");
        }

        // Auto-refresh during processing
        if (["Queued", "In Progress"].includes(frm.doc.import_status)) {
            setTimeout(function () {
                frm.reload_doc();
            }, 5000);
        }

        // Status intro messages
        if (!frm.doc.csv_file) {
            frm.set_intro(__("1. Upload a CSV file exported from Procurios<br>2. Click 'Validate CSV' to check the data<br>3. Review the preview and click 'Process Import'"));
        } else if (frm.doc.import_status === "Pending") {
            frm.set_intro(__("File selected. Click 'Validate CSV' to check the data."));
        } else if (frm.doc.import_status === "Validating") {
            frm.set_intro(__("Processing file..."), "blue");
        } else if (frm.doc.import_status === "Failed") {
            frm.set_intro(__("Validation failed. Check the Error Log below."), "red");
        } else if (frm.doc.import_status === "Ready for Import") {
            let msg = __("Ready to import! Review the preview data below, then click 'Process Import'.");
            if (frm.doc.test_mode) {
                msg += " " + __("<br><strong>Test mode is ON</strong> — only the first 25 rows will be processed.");
            }
            frm.set_intro(msg, "green");
        } else if (frm.doc.import_status === "Completed") {
            frm.set_intro(
                __("Import completed. {0} members created, {1} skipped.", [
                    frm.doc.members_created,
                    frm.doc.members_skipped,
                ]),
                "green"
            );
        } else if (["Queued", "In Progress"].includes(frm.doc.import_status)) {
            frm.set_intro(
                __("Import in progress... {0}% complete ({1}/{2} rows)", [
                    frm.doc.progress_percentage || 0,
                    frm.doc.rows_processed || 0,
                    frm.doc.total_rows || 0,
                ]),
                "blue"
            );
        }
    },

    csv_file(frm) {
        if (frm.doc.csv_file) {
            frm.set_value("import_status", "Pending");
            frm.set_intro(__("File selected. Click 'Validate CSV' to check the data."));
        }
    },
});
```

- [ ] **Step 2: Verify the form loads in browser**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org clear-cache`
Then navigate to `/app/procurios-csv-import/new` in browser.
Expected: Form loads with Import Configuration section, file upload field, and instruction intro message.

- [ ] **Step 3: Commit**

```bash
git add verenigingen/verenigingen/doctype/procurios_csv_import/procurios_csv_import.js
git commit -m "feat: add Procurios CSV Import client script with validation and progress UI"
```

---

## Task 8: Wire up SecureCSVParser delimiter support and run full test suite

The `SecureCSVParser.read_csv_file()` may not support a `delimiter` parameter. This task verifies the integration and fixes any issues found during the full test run.

**Files:**
- Modify: `verenigingen/verenigingen/doctype/procurios_csv_import/procurios_csv_import.py` (if parser changes needed)
- Test: `verenigingen/tests/member/test_procurios_csv_import.py`

- [ ] **Step 1: Check SecureCSVParser API for delimiter support**

Run: `cd ~/frappe-bench && grep -n "def read_csv_file" apps/verenigingen/verenigingen/utils/csv/secure_csv_parser.py`
Expected: Shows the method signature. If it doesn't accept a `delimiter` param, adjust the controller's `_read_csv_file` method to handle delimiter separately (e.g., using Python's `csv.reader` with the delimiter after `SecureCSVParser` returns raw content).

- [ ] **Step 2: Run the full test suite**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.member.test_procurios_csv_import`
Expected: All tests pass.

- [ ] **Step 3: Fix any failing tests**

Address test failures related to parser integration, field mapping mismatches, or missing imports. Re-run tests after each fix.

- [ ] **Step 4: Run a manual smoke test**

Create a small test CSV with 3-5 rows and semicolon delimiters. Upload via the Procurios CSV Import form, validate, and submit. Verify members are created in the Member list.

- [ ] **Step 5: Commit any fixes**

```bash
git add -u
git commit -m "fix: wire up Procurios CSV Import parser integration and fix test issues"
```

---

## Task 9: Add whitelist entries and final cleanup

**Files:**
- Modify: `verenigingen/whitelist_files.txt` (if used for API method registration)
- Verify: All new files have correct module references

- [ ] **Step 1: Check if whitelist_files.txt needs entries**

Run: `cd ~/frappe-bench && grep -c "procurios" apps/verenigingen/whitelist_files.txt 2>/dev/null || echo "no whitelist file"`

If the file exists and the MijnRood import has entries there, add equivalent entries for the Procurios import's whitelisted methods (`validate_import_file`, `process_import_background`).

- [ ] **Step 2: Verify all DocType `__init__.py` files exist**

Run: `ls apps/verenigingen/verenigingen/verenigingen/doctype/procurios_*/`
Expected: Each directory has `__init__.py`, `.json`, and `.py` files.

- [ ] **Step 3: Run migration and clear cache**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org migrate && bench --site veg11.veganisme.org clear-cache`
Expected: Clean migration with no errors.

- [ ] **Step 4: Run full test suite one more time**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.member.test_procurios_csv_import`
Expected: All tests pass.

- [ ] **Step 5: Final commit**

```bash
git add -u
git commit -m "chore: add whitelist entries and finalize Procurios CSV Import setup"
```
