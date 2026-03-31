# Procurios CSV Import — Design Spec

**Date:** 2026-03-31
**Status:** Approved
**Scope:** One-time CSV import of Procurios CRM contact data into Verenigingen Member records

## Context

Procurios is the current CRM used by the association. The organization is migrating away from it. The Procurios REST API is too limited for ongoing sync (no webhooks, limited endpoints), so the strategy is:

1. **Now:** CSV import for member/contact data exported from Procurios
2. **Later:** Database dump processor for remaining data (separate project)

This spec covers step 1.

## Decisions

- **Import type:** Clean import — all Procurios contacts are new records, no duplicate matching needed
- **Storage strategy:** Native Member fields for core data, key-value child table for everything else
- **Status:** Configurable mapping from Procurios values; defaults to Active when no mapping matches
- **Gender:** Optional — toggled via `import_gender` checkbox on the import form; when disabled, stored in child table instead
- **Architecture:** Clone of MijnRood CSV Import pattern (dedicated DocType, validator, background processor)

## Data Model

### New Child Table: `Procurios Member Data`

Key-value child table on Member for storing Procurios-specific fields.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `field_label` | Data | Yes | Original Procurios column name |
| `field_value` | Small Text | No | The value (Small Text for longer survey answers) |
| `field_category` | Select | No | Personal, Financial, Subscription, Survey, Campaign, Other |

Added to Member DocType as table field `procurios_data` in a new collapsible section "Procurios Import Data" after the existing custom fields section.

### New Child Table: `Procurios Status Mapping`

Configuration child table on the import DocType.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `procurios_value` | Data | Yes | Value from the Procurios status/type field |
| `member_status` | Select | Yes | Target Member status (Active, Pending, Expired, Quit, etc.) |

### New Field on Member

| Field | Type | Options | Description |
|-------|------|---------|-------------|
| `gender` | Select | Male, Female, Other, Prefer not to say | Only populated when `import_gender` is enabled |

### Field Mapping: Procurios CSV to Member

**Mapped to native Member fields:**

| Procurios Column | Member Field | Notes |
|-----------------|-------------|-------|
| `Systeem ID` | `member_id` | Primary identifier |
| `Voornaam` | `first_name` | |
| `Tussenvoegsel` | `tussenvoegsel` | |
| `Volledige naam` | Used to derive `last_name` | Strip first_name + tussenvoegsel from full name |
| `E-mailadres` | `email` | |
| `Geboortedatum` | `birth_date` | |
| `Geslacht` | `gender` (if toggle on) or child table | |
| `Bankrekening` | `iban` | Validated with MOD-97 |
| `Aanmaakdatum` | `member_since` | |
| `Mobiel` | `contact_number` | |
| `Voorletters` | Stored in child table | No native field for initials |
| `Titel` | Stored in child table | Could map to `aanhef` but values may not match |

**Address fields → Address DocType records:**

Each address type (Standaardadres, Postadres, Factuuradres) has these subfields:

| Procurios Subfield | Address DocType Field |
|-------------------|----------------------|
| `Geadresseerde` | `address_title` |
| `Straat` | `address_line1` (street part) |
| `Nummer met toevoeging` | `address_line1` (appended to street) |
| `Postcode` | `pincode` |
| `Plaats` | `city` |
| `Landnaam` | `country` (normalized to Frappe country name) |

Address type mapping to Frappe:
- Standaardadres → Office
- Postadres → Shipping
- Factuuradres → Billing

**Everything else** → `procurios_data` child table.

### Field Categorization

Fields stored in the child table are auto-categorized:

| Category | Matching patterns |
|----------|------------------|
| Personal | Naam, Voornaam, Titel, Geslacht, Geboortedatum, Voorkeurstaal, Voorletters, Tenaamstelling |
| Financial | Contributie, Bankrekening, Machtiging, facturen, Bedrag, Totaal, € |
| Subscription | VEGAN Magazine, Abonnee, Nieuwsbrief |
| Survey | JOUR_, waarom, wat moeten, Thema |
| Campaign | Campagne, actie, Binnengekomen via, Welkomstcadeau, Aanmeldcode |
| Other | Everything not matching above |

## Procurios CSV Import DocType

**Module:** Verenigingen
**Name:** Procurios CSV Import
**Is Submittable:** Yes

### Form Layout

**Section: Import Configuration**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `csv_file` | Attach | — | CSV or Excel file |
| `encoding` | Select | auto-detect | UTF-8, Latin-1, auto-detect |
| `csv_delimiter` | Select | Semicolon | Comma, Semicolon, Tab |
| `import_gender` | Check | 0 | Map Geslacht to Member.gender field |
| `default_status` | Select | Active | Status when no mapping matches |
| `test_mode` | Check | 0 | Process only first 25 rows |

**Section: Status Mapping**

| Field | Type | Description |
|-------|------|-------------|
| `status_mapping` | Table (Procurios Status Mapping) | Procurios value → Member status pairs |

**Section: Address Handling**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `import_addresses` | Check | 1 | Create Address records |
| `preferred_address_type` | Select | Standaardadres | Which address becomes `primary_address` |

Options: Standaardadres, Postadres, Factuuradres

**Section: Progress (read-only, visible after submit)**

| Field | Type | Description |
|-------|------|-------------|
| `import_status` | Select | Not Started, Validating, In Progress, Completed, Failed |
| `progress_percentage` | Percent | 0-100 |
| `rows_processed` | Int | Counter |
| `total_rows` | Int | Total data rows in CSV |
| `members_created` | Int | Successfully created |
| `members_skipped` | Int | Skipped due to errors |

**Section: Error Log (read-only, visible after submit)**

| Field | Type | Description |
|-------|------|-------------|
| `error_log` | Long Text | Per-row errors with row numbers |
| `top_errors_summary` | Small Text | Most common error types |

## Processing Architecture

### New Files

```
verenigingen/verenigingen/doctype/procurios_csv_import/
├── procurios_csv_import.json
├── procurios_csv_import.py
├── procurios_csv_import.js
├── test_procurios_csv_import.py

verenigingen/verenigingen/doctype/procurios_member_data/
├── procurios_member_data.json
├── procurios_member_data.py

verenigingen/verenigingen/doctype/procurios_status_mapping/
├── procurios_status_mapping.json
├── procurios_status_mapping.py

verenigingen/utils/csv/procurios_data_validator.py
```

### Processing Flow

1. **Upload & Validate** — User uploads CSV, clicks "Validate CSV" button
   - `ProcuriosDataValidator.validate_and_map_data()` parses CSV
   - Validates required fields: `Systeem ID`, plus `Voornaam` or `Volledige naam`
   - Maps native fields, categorizes the rest
   - Returns validation errors and preview data

2. **Preview** — Shows sample of first valid rows + error summary (same UI as MijnRood)

3. **Submit** — Queues `process_import_background()` via `frappe.enqueue()` on long queue (1 hour timeout)

4. **Per-row processing:**
   - Create Member with native mapped fields
   - Apply status from status mapping (or `default_status`)
   - Set `member_id` from `Systeem ID`
   - If `import_gender` enabled: map `Geslacht` to `gender`; otherwise store in child table
   - If `import_addresses` enabled: create Address record(s) for non-empty address types, link preferred type as `primary_address`
   - Populate `procurios_data` child table with all remaining fields and their categories
   - Derive `last_name` from `Volledige naam` minus `Voornaam` and `Tussenvoegsel`

5. **Batch processing** — 50 rows per batch, commit per batch, progress tracking via `CSVImportBackgroundProcessor`

### Reused Infrastructure

- `SecureCSVParser` — file parsing, encoding detection
- `CSVImportBackgroundProcessor` — batch processing, progress, error recovery
- `clean_phone_number()`, `parse_date()` — existing data transformers
- `validate_iban()` — existing MOD-97 IBAN validation
- `frappe.flags.bulk_member_operations` — bulk import flag to suppress hooks

### Name Derivation Logic

```
full_name = "Jan van der Berg"
first_name = "Jan"
tussenvoegsel = "van der"
last_name = full_name.removeprefix(first_name).removeprefix(tussenvoegsel).strip()
# Result: "Berg"
```

If `Volledige naam` is missing, fall back to `Naam` field. If only `Voornaam` is present, `last_name` defaults to empty string.

## Testing Strategy

### Unit Tests

- Field mapping correctness — each Procurios column maps to the right Member field or child table entry
- Category assignment — fields categorized correctly based on pattern matching
- Required field validation — missing `Systeem ID` or name fields produce errors
- Date/IBAN/email validation — malformed values caught
- Status mapping — configurable values applied, default used as fallback
- Gender toggle — maps to `gender` when enabled, child table when disabled
- Name derivation — `last_name` correctly extracted from various name formats (with/without tussenvoegsel)
- Address parsing — all 3 types parsed, empty addresses skipped, preferred type linked

### Integration Tests

- Full import cycle — upload CSV, validate, submit, verify Members created with correct data
- Address creation — verify Address records created and linked as `primary_address`
- Batch processing — progress tracking updates, error recovery across batches
- Child table — all unmapped fields present with correct categories

No mocking of business logic — real Member creation against test database.
