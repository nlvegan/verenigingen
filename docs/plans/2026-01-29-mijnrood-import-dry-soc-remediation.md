# MijnRood CSV Import DRY/SoC Remediation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce the MijnRood CSV Import DocType from a 2,882-line god object to a thin orchestration layer (~400-500 lines) by extracting business logic into testable services.

**Approach:** Conservative - focus on DRY refactors and service extraction without changing external behavior. Use parallel-run strategy for safe rollout.

**Tech Stack:** Python 3.11, Frappe Framework, MariaDB savepoints, RQ background jobs

---

## Audit Verification Summary

| Finding | Status | Evidence |
|---------|--------|----------|
| DocType is a "god object" (~2,882 lines) | **Confirmed** | Contains member CRUD, address creation, Mollie handling, chapter assignment, volunteer creation, membership billing logic, account provisioning |
| Repeated `CSVDataValidator()` instantiation | **Confirmed** | Lines 226, 231, 236, 242, 247 - new instance created in each helper method |
| Finalization mixes orchestration + business logic | **Confirmed** | `_finalize_import_results()` handles tracker linking, Mollie validation, volunteer creation, account queuing (~180 lines) |
| Bulk operation flag handling is ad-hoc | **Confirmed** | Manual flag set/clear in multiple places without context manager pattern |
| Error logging centralized in `import_helpers` | **Confirmed, Good** | `persist_full_error_log()` and `truncate_error_log_for_display()` exist |
| IBAN validation centralized | **Confirmed, Good** | Streaming MOD-97 in `iban_validator.py`, CSVDataValidator delegates correctly |
| Business rules scattered in DocType | **Confirmed** | Address creation (lines 1643-1775), membership billing, volunteer creation, termination handling |

---

## Architecture After Refactoring

```
┌─────────────────────────────────────────────────────────────────┐
│                    MijnroodCSVImport DocType                     │
│                     (Orchestration Only)                         │
│  - validate() / on_submit() / queue background job               │
│  - _finalize_import_results() → calls services                   │
└───────────────┬─────────────────────────────────────────────────┘
                │ delegates to
                ▼
┌───────────────────────────────────────────────────────────────────┐
│                      Service Layer                                 │
├──────────────────┬──────────────────┬─────────────────────────────┤
│ MemberImportSvc  │ AddressImportSvc │ MembershipImportSvc         │
│ - create_or_     │ - create_or_     │ - create_from_csv()         │
│   update_member()│   update()       │ - determine_type()          │
│ - update_fields()│ - link_to_member │ - get_dues_template()       │
├──────────────────┼──────────────────┼─────────────────────────────┤
│ MollieSyncSvc    │ MemberLookupSvc  │ BulkVolunteerCreationSvc    │
│ - sync_customer_ │ - find_member()  │ (already exists)            │
│   mollie_data()  │ - cascade match  │                             │
└──────────────────┴──────────────────┴─────────────────────────────┘
                │ uses
                ▼
┌───────────────────────────────────────────────────────────────────┐
│                    Shared Infrastructure                           │
│  bulk_member_operations() context manager                          │
│  CSVDataValidator (reuse instance)                                 │
│  import_helpers (persist_full_error_log, truncate_error_log)       │
└───────────────────────────────────────────────────────────────────┘
```

**Key Principles:**
- Each service has a single responsibility and is independently testable
- Services are stateless where possible (use `StatelessService` base)
- DocType only coordinates service calls and handles document lifecycle
- No behavior changes to external API - same inputs produce same outputs

---

## Phase A: Quick DRY Wins (Low Risk)

Small, safe refactors that can be done immediately with minimal testing burden.

### Task A1: Reuse Validator/Parser Instances

**Problem:** `CSVDataValidator()` instantiated 6+ times across helper methods.

**Solution:** Lazy-initialize once on first use.

**Files:** `mijnrood_csv_import.py`

**Implementation:**

```python
# Add to MijnroodCSVImport class
@property
def _validator(self):
    if not hasattr(self, '__validator'):
        self.__validator = CSVDataValidator()
    return self.__validator

@property
def _parser(self):
    if not hasattr(self, '__parser'):
        self.__parser = SecureCSVParser(encoding=self.encoding)
    return self.__parser
```

Then replace all `validator = CSVDataValidator()` calls with `self._validator`.

**Risk:** Very low - internal optimization only

**Test:** Existing tests should pass unchanged

---

### Task A2: Bulk Operations Context Manager

**Problem:** Manual flag setting/clearing scattered across processor and DocType.

**Solution:** Create context manager in `csv_import_processor.py`:

**Files:** `csv_import_processor.py`, `mijnrood_csv_import.py`

**Implementation:**

```python
from contextlib import contextmanager

@contextmanager
def bulk_member_operations(import_doc_name: str = None):
    """Context manager for bulk import operations.

    Ensures proper initialization and cleanup of:
    - frappe.flags.bulk_member_operations
    - frappe.local.bulk_import_members set
    """
    try:
        frappe.flags.bulk_member_operations = True
        ensure_bulk_import_members_set()
        frappe.logger().info(f"Bulk import started: {import_doc_name or 'unnamed'}")
        yield frappe.local.bulk_import_members
    finally:
        frappe.flags.bulk_member_operations = False
        if hasattr(frappe.local, "bulk_import_members"):
            frappe.local.bulk_import_members.clear()
        frappe.logger().info(f"Bulk import cleanup complete: {import_doc_name or 'unnamed'}")
```

**Usage:**
```python
with bulk_member_operations(self.import_doc_name) as member_set:
    # ... process batches ...
    member_set.add(member.name)
```

**Risk:** Low - replaces manual code with safer pattern

**Test:** Add test for exception cleanup behavior

---

### Task A3: Adopt MemberLookupService

**Problem:** DocType has inline member lookup logic (lines 1162-1166) that duplicates `MemberLookupService`.

**Solution:** Replace inline lookup with service call.

**Files:** `mijnrood_csv_import.py`

**Implementation:**

```python
# Before (in _create_or_update_member):
existing_member = None
if row_data.get("member_id"):
    existing_member = frappe.db.get_value("Member", {"member_id": row_data["member_id"]}, "name")
if not existing_member and row_data.get("email"):
    existing_member = frappe.db.get_value("Member", {"email": row_data["email"]}, "name")

# After:
from verenigingen.services.member.member_lookup_service import get_member_lookup_service

service = get_member_lookup_service()
existing_member_doc = service.find_member(row_data, strategies=service.MIJNROOD_STRATEGIES)
existing_member = existing_member_doc.name if existing_member_doc else None
```

**Risk:** Low - service already tested, same logic

**Test:** Existing import tests cover this path

---

## Phase B: Service Extraction (Medium Risk, High Payoff)

Extract core business logic from DocType into dedicated services. Each service created with tests first (TDD).

### Task B1: Create MemberImportService

**Responsibility:** Core member create/update logic, currently ~170 lines in DocType.

**Location:** `verenigingen/services/import/member_import_service.py`

**Files to Create:**
- `verenigingen/services/import/__init__.py`
- `verenigingen/services/import/member_import_service.py`
- `verenigingen/services/import/test_member_import_service.py`

**Service API:**

```python
class MemberImportService(StatelessService):
    """Service for creating/updating members during CSV import."""

    def create_or_update_member(
        self,
        row_data: Dict,
        import_doc_name: str,
        create_volunteer_records: bool = False,
    ) -> Tuple[str, Optional[str]]:
        """
        Create or update a member from CSV row data.

        Returns:
            Tuple of (status, member_name_or_reason)
            - status: "created", "updated", "skipped", or "failed"
        """
        ...

    def update_member_fields(
        self,
        member_doc: Document,
        row_data: Dict,
        import_doc_name: str,
        create_volunteer_records: bool = False,
    ) -> None:
        """Update member document fields from row data."""
        ...

    def determine_member_status(self, membership_type: str) -> str:
        """Map CSV membership_type to Member.status."""
        ...
```

**What Moves Out of DocType:**
- `_create_or_update_member()` → `service.create_or_update_member()`
- `_update_member_fields()` → `service.update_member_fields()`
- `_create_member_with_safe_optimization()` → internal to service
- Status determination logic → `service.determine_member_status()`

**Risk:** Medium - core business logic

**Safety:** Parallel-run strategy for first deployment

---

### Task B2: Create AddressImportService

**Responsibility:** Address creation/update and linking, currently ~130 lines in DocType.

**Location:** `verenigingen/services/import/address_import_service.py`

**Files to Create:**
- `verenigingen/services/import/address_import_service.py`
- `verenigingen/services/import/test_address_import_service.py`

**Service API:**

```python
class AddressImportService(StatelessService):
    """Service for creating/updating addresses during CSV import."""

    def create_or_update_address(
        self,
        member_doc: Document,
        row_data: Dict,
    ) -> Optional[str]:
        """
        Create or update address for member from CSV data.

        Returns:
            Address name if created/updated, None if skipped (no data)
        """
        ...

    def remove_stale_address_links(self, address_doc: Document) -> int:
        """Remove links to deleted members/customers. Returns count removed."""
        ...
```

**What Moves Out of DocType:**
- `_create_or_update_address()` → `service.create_or_update_address()`
- `_remove_stale_address_links()` → `service.remove_stale_address_links()`

**Risk:** Medium - affects address data

**Test:** Test with addresses that have existing links, test duplicate detection

---

### Task B3: Create MollieSyncService

**Responsibility:** Mollie data validation and Customer record updates, currently ~60 lines.

**Location:** `verenigingen/services/import/mollie_sync_service.py`

**Files to Create:**
- `verenigingen/services/import/mollie_sync_service.py`
- `verenigingen/services/import/test_mollie_sync_service.py`

**Service API:**

```python
class MollieSyncService(StatelessService):
    """Service for syncing Mollie subscription data to Member/Customer."""

    def sync_mollie_data(
        self,
        member_doc: Document,
        mollie_data: Dict,
    ) -> None:
        """
        Sync Mollie customer/subscription IDs to Member and Customer records.

        Raises:
            frappe.ValidationError: If Mollie data format is invalid
        """
        ...

    def validate_mollie_data_preservation(
        self,
        member_names: List[str],
        auto_fix_payment_method: bool = True,
    ) -> Tuple[List[str], List[str]]:
        """
        Validate Mollie data on imported members.

        Returns:
            Tuple of (issues, auto_fixed)
        """
        ...
```

**What Moves Out of DocType:**
- `_update_customer_mollie_data()` → `service.sync_mollie_data()`
- `_validate_mollie_data_preservation()` → `service.validate_mollie_data_preservation()`

**Risk:** Medium - financial data

**Test:** Test invalid format detection, test auto-fix behavior

---

### Task B4: Create MembershipImportService

**Responsibility:** Membership and dues schedule creation from CSV.

**Location:** `verenigingen/services/import/membership_import_service.py`

**Files to Create:**
- `verenigingen/services/import/membership_import_service.py`
- `verenigingen/services/import/test_membership_import_service.py`

**Service API:**

```python
class MembershipImportService(StatelessService):
    """Service for creating Membership records during CSV import."""

    def create_membership_from_csv(
        self,
        member_doc: Document,
        row_data: Dict,
    ) -> Optional[str]:
        """
        Create Membership record for imported member.

        Returns:
            Membership name if created, None if skipped
        """
        ...

    def get_dues_schedule_template(self, row_data: Dict) -> str:
        """Get dues schedule template based on payment period."""
        ...

    def determine_membership_type(self, row_data: Dict) -> str:
        """Determine membership type (regular vs aspirant)."""
        ...
```

**Note:** Mostly wraps existing `data_transformers.py` functions with cleaner API.

**Risk:** Medium-High - billing sensitive

**Test:** Test with various payment periods, test missing template handling

---

## Phase C: DocType Refactoring (Wire Services)

Transform DocType from god object to thin orchestration layer.

### Task C1: Refactor _process_single_member to Use Services

**Current State:** `_process_single_member()` calls `_create_or_update_member()` with all logic inline.

**New State:** Delegates to `MemberImportService`:

```python
def _process_single_member(self, row: Dict, error_log: List[str]) -> tuple:
    """Process a single member - orchestration only."""
    from verenigingen.services.import.member_import_service import get_member_import_service

    try:
        service = get_member_import_service()
        result, member_name = service.create_or_update_member(
            row_data=row,
            import_doc_name=self.name,
            create_volunteer_records=self.create_volunteer_records,
        )

        if result in ("created", "updated") and member_name:
            self._create_related_records_via_services(member_name, row)

        return result, member_name

    except frappe.ValidationError as ve:
        return self._handle_validation_error(ve, row, error_log)
    except Exception as e:
        return self._handle_unexpected_error(e, row, error_log)
```

**Lines Removed from DocType:** ~150 lines

---

### Task C2: Refactor _create_related_records_with_tracking to Use Services

**New State:** Orchestrates service calls:

```python
def _create_related_records_via_services(self, member_name: str, row_data: Dict) -> List[str]:
    """Create related records using extracted services."""
    from verenigingen.services.import.address_import_service import get_address_import_service
    from verenigingen.services.import.mollie_sync_service import get_mollie_sync_service
    from verenigingen.services.import.membership_import_service import get_membership_import_service

    member_doc = frappe.get_doc("Member", member_name)
    failed_operations = []

    # Address creation
    if self._has_address_data(row_data):
        try:
            address_service = get_address_import_service()
            address_name = address_service.create_or_update_address(member_doc, row_data)
            if address_name:
                frappe.db.set_value("Member", member_name, "primary_address", address_name, update_modified=False)
        except Exception as e:
            failed_operations.append("address")
            frappe.log_error(f"Address creation failed for {member_name}: {e}", "CSV Import - Address Error")

    # Mollie data sync
    if hasattr(member_doc, "_mollie_data") and member_doc._mollie_data:
        try:
            mollie_service = get_mollie_sync_service()
            mollie_service.sync_mollie_data(member_doc, member_doc._mollie_data)
        except Exception as e:
            failed_operations.append("mollie_data")

    # Membership creation
    if self._should_create_membership(member_doc, row_data):
        try:
            membership_service = get_membership_import_service()
            membership_service.create_membership_from_csv(member_doc, row_data)
        except Exception as e:
            failed_operations.append("membership")

    return failed_operations
```

**Lines Removed from DocType:** ~70 lines

---

### Task C3: Refactor _finalize_import_results to Orchestration-Only

**New State:** Pure orchestration calling services:

```python
def _finalize_import_results(
    self,
    created_count: int,
    updated_count: int,
    skipped_count: int,
    error_log: List[str],
    created_members: List[str] = None,
    updated_members: List[str] = None,
    skipped_members: List[str] = None,
):
    """Finalize import - orchestration only."""
    from verenigingen.services.import.mollie_sync_service import get_mollie_sync_service

    processed_members = (created_members or []) + (updated_members or [])

    with bulk_member_operations(self.name):
        # User account creation (already delegates to AccountCreationService)
        user_summary = ""
        if self.create_user_accounts and processed_members:
            user_summary = self._process_user_account_creation(processed_members)

        # Volunteer creation (already delegates to BulkVolunteerCreationService)
        volunteer_summary = ""
        if self.create_volunteer_records and processed_members:
            volunteer_summary = self._process_bulk_volunteer_creation(processed_members)

    # Mollie validation via service
    mollie_summary = ""
    if processed_members:
        mollie_service = get_mollie_sync_service()
        issues, auto_fixed = mollie_service.validate_mollie_data_preservation(
            processed_members, auto_fix_payment_method=True
        )
        mollie_summary = self._format_mollie_summary(issues, auto_fixed)

    # Set final status
    self._set_final_status(created_count, updated_count, skipped_count, error_log,
                           user_summary, volunteer_summary, mollie_summary,
                           created_members, updated_members, skipped_members)
```

**Lines Removed from DocType:** ~80 lines

---

### Task C4: Remove Deprecated/Dead Code

After service extraction, remove dead code:

| Method | Lines | Reason |
|--------|-------|--------|
| `_create_or_update_member` | ~170 | Moved to MemberImportService |
| `_update_member_fields` | ~190 | Moved to MemberImportService |
| `_create_or_update_address` | ~130 | Moved to AddressImportService |
| `_remove_stale_address_links` | ~30 | Moved to AddressImportService |
| `_update_customer_mollie_data` | ~60 | Moved to MollieSyncService |
| `_validate_mollie_data_preservation` | ~110 | Moved to MollieSyncService |
| `_create_related_records` (deprecated) | ~15 | Already marked deprecated |

**Total Lines Removed:** ~700 lines

**Final DocType Size:** ~400-500 lines (orchestration + UI helpers)

---

## Phase D: Testing & Safety Strategy

### Task D1: Unit Tests for Each Extracted Service

**MemberImportService Tests:**

```python
class TestMemberImportService(FrappeTestCase):

    def test_create_new_member_from_csv_row(self):
        """Test creating a new member from CSV data."""
        ...

    def test_update_existing_member_by_member_id(self):
        """Test updating existing member matched by member_id."""
        ...

    def test_status_mapping_from_membership_type(self):
        """Test all membership_type → status mappings."""
        test_cases = [
            ("Lid", "Active"),
            ("Aspirant", "Active"),
            ("Overleden", "Deceased"),
            ("Opgezegd", "Terminated"),
            ("Geroyeerd", "Banned"),
            ("Dubbel", "Rejected"),
            ("Unknown", "Active"),
        ]
        ...

    def test_aspirant_flag_set_correctly(self):
        """Test is_aspirant flag set for Aspirant membership type."""
        ...
```

**AddressImportService Tests:**

```python
class TestAddressImportService(FrappeTestCase):

    def test_skip_address_creation_without_required_fields(self):
        """Test that address is NOT created if address_line1 or city missing."""
        ...

    def test_reuse_existing_matching_address(self):
        """Test that duplicate addresses are linked, not created."""
        ...

    def test_stale_link_removal(self):
        """Test that links to deleted members are removed."""
        ...
```

**MollieSyncService Tests:**

```python
class TestMollieSyncService(FrappeTestCase):

    def test_validate_mollie_customer_id_format(self):
        """Test that invalid Mollie customer ID format is rejected."""
        ...

    def test_critical_issue_detection_active_subscription_on_terminated(self):
        """Test detection of active Mollie subscription on terminated member."""
        ...
```

---

### Task D2: Parallel-Run Strategy for Safe Rollout

**Feature flag in Verenigingen Settings:**
- Field: `use_new_import_services` (Check, default=0)

**Implementation:**

```python
def _process_single_member(self, row: Dict, error_log: List[str]) -> tuple:
    """Process single member with parallel-run safety."""
    settings = frappe.get_cached_doc("Verenigingen Settings")

    if settings.use_new_import_services:
        return self._process_single_member_via_services(row, error_log)
    else:
        return self._process_single_member_legacy(row, error_log)
```

**Validation Phases:**

1. **Shadow Mode:** Run both paths, log differences, use legacy result
2. **Canary (10%):** Use new path for 10% of imports
3. **Full Rollout:** Enable for all imports
4. **Cleanup:** Remove legacy code after 2 weeks stable

---

### Task D3: Integration Test with Real CSV Data

```python
class TestMijnroodCSVImportIntegration(FrappeTestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_csv_content = """voornaam,achternaam,e-mailadres,lidnr.,geboortedatum,lidmaatschapstype,contributiebedrag,betaalperiode,iban,adres,plaats,postcode
Test,Active,active@test.com,TEST-001,1990-01-15,Lid,15.00,Maandelijks,NL91ABNA0417164300,Teststraat 1,Amsterdam,1234AB
Test,Aspirant,aspirant@test.com,TEST-002,1995-06-20,Aspirant,10.00,Jaarlijks,,,,
Test,Terminated,terminated@test.com,TEST-003,1985-03-10,Opgezegd,0,,,,,
"""

    def test_full_import_creates_expected_records(self):
        """Test that CSV import creates all expected records."""
        ...
```

---

## Implementation Sequence

```
Week 1: Phase A (Quick Wins)
├── PR #1: Reuse validator/parser instances
├── PR #2: Add bulk_member_operations context manager
└── PR #3: Adopt MemberLookupService

Week 2: Phase B (Service Extraction) - Part 1
├── PR #4: Create MemberImportService (with tests)
└── PR #5: Create AddressImportService (with tests)

Week 3: Phase B (Service Extraction) - Part 2
├── PR #6: Create MollieSyncService (with tests)
└── PR #7: Create MembershipImportService (with tests)

Week 4: Phase C (Wire Services)
├── PR #8: Refactor DocType to use services (feature-flagged)
├── PR #9: Add parallel-run validation logging
└── PR #10: Integration tests

Week 5: Validation & Cleanup
├── Enable feature flag for canary testing
├── Monitor for 1 week
├── PR #11: Remove legacy code paths
└── PR #12: Final cleanup and documentation
```

---

## Commit Templates

### Phase A Commits

```bash
# PR #1
git commit -m "refactor(mijnrood-import): reuse CSVDataValidator and SecureCSVParser instances

Adds lazy-initialized properties for validator and parser to avoid
repeated instantiation in helper methods. Internal optimization only."

# PR #2
git commit -m "refactor(csv-import): add bulk_member_operations context manager

Replaces manual flag setting/clearing with context manager pattern.
Ensures proper cleanup on exceptions."

# PR #3
git commit -m "refactor(mijnrood-import): adopt MemberLookupService for member matching

Replaces inline member lookup logic with existing MemberLookupService.
Uses MIJNROOD_STRATEGIES (member_id → email cascade)."
```

### Phase B Commits

```bash
# PR #4
git commit -m "feat(services): create MemberImportService for CSV member creation

Extracts core member create/update logic from MijnroodCSVImport DocType."

# PR #5
git commit -m "feat(services): create AddressImportService for CSV address handling

Extracts address creation/update and linking logic from DocType."

# PR #6
git commit -m "feat(services): create MollieSyncService for Mollie data handling

Extracts Mollie customer/subscription sync and validation logic."

# PR #7
git commit -m "feat(services): create MembershipImportService for billing setup

Extracts membership and dues schedule creation from CSV import."
```

### Phase C Commits

```bash
# PR #8
git commit -m "refactor(mijnrood-import): wire DocType to use extracted services

Feature-flagged via Verenigingen Settings.use_new_import_services.
DocType reduced from ~2900 lines to ~1200 lines (services + legacy)."

# PR #11 (after validation)
git commit -m "refactor(mijnrood-import): remove legacy code paths

Removes feature flag and legacy implementation after validation.
DocType reduced from ~1200 lines to ~450 lines."
```

---

## Rollback Strategy

```bash
# Immediate rollback - disable feature flag
bench --site veg11.veganisme.org set-config -p use_new_import_services 0
bench --site veg11.veganisme.org clear-cache

# If flag doesn't work, revert PR #8
git revert <PR-8-commit-hash>
bench --site veg11.veganisme.org migrate
```

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Import success rate | ≥99.5% | Compare before/after |
| Average import time | No regression (±5%) | Benchmark 1000-row imports |
| Memory usage | No regression | Monitor during large imports |
| Test coverage | ≥90% for new services | Coverage report |
| DocType line count | ≤500 lines | `wc -l` |

---

## Summary

| Phase | PRs | Lines Changed | Risk | Duration |
|-------|-----|---------------|------|----------|
| A: Quick Wins | 3 | ~100 | Low | 2-3 days |
| B: Service Extraction | 4 | ~800 new | Medium | 1 week |
| C: Wire Services | 3 | ~500 modified | Medium | 1 week |
| D: Testing | - | ~400 tests | Low | Ongoing |
| Cleanup | 2 | -700 removed | Low | After validation |

**Final Result:** DocType reduced from **2,882 lines** to **~450 lines** (84% reduction), with all business logic in testable, reusable services.

---

## Execution

To implement this plan:

1. **Subagent-Driven (recommended):** Dispatch fresh subagent per task with review between tasks
2. **Parallel Session:** Open new session with `superpowers:executing-plans` for batch execution

Start with Phase A tasks for immediate DRY wins, then proceed to service extraction.
