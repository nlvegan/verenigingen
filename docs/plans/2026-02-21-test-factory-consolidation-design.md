# Test Factory Consolidation Design

**Date:** 2026-02-21
**Status:** Phase 1 + Phase 2 + Phase 3 complete.
**Estimated effort:** 12-17 hours across 3 phases

---

## Problem Statement

The Verenigingen test suite has 8 competing test data factories totalling ~12,500 LOC, plus ~44 test files with local "shadow factory" methods. Core entity creation (`create_member`, `create_chapter`, `create_membership`, `create_test_iban`) is implemented independently in 3-4 places with different signatures, defaults, and side effects. This causes:

- Inconsistent test data (some factories validate fields, others don't)
- `member_id` counter collisions across factories
- Maintenance burden when DocType schemas change (must update 4+ factories)
- Confusion about which factory to use for new tests

---

## Current State: 8 Factories + 44 Shadow Factories

### Factory Inventory

| # | Factory | File | LOC | Consumers | Role |
|---|---------|------|-----|-----------|------|
| 1 | `StreamlinedTestDataFactory` | `tests/fixtures/test_data_factory.py` | 959 | 12 direct + VTC delegation | Core base factory |
| 1b | Bridge module | `tests/test_data_factory.py` | 31 | Re-exports from fixtures | Convenience re-export |
| 2 | `EnhancedTestDataFactory` + `EnhancedTestCase` | `tests/fixtures/enhanced_test_factory.py` | 5,304 | 365 (359 as base class only) | Dominant test case base class |
| 3 | `SecureTestDataFactory` | `tests/fixtures/secure_test_data_factory.py` | 471 | 3 | Redundant with Enhanced |
| 4 | `SEPAMandateTestDataFactory` | `tests/fixtures/sepa_mandate_test_factory.py` | 746 | 1 | Domain-specific SEPA compliance |
| 5 | `PontoTestDataFactory` | `tests/fixtures/ponto_test_data_factory.py` | 699 | 3 | Domain-specific Ponto API mocks |
| 6a | `PaymentHistoryTestDataFactory` | `tests/fixtures/payment_history_test_factory.py` | 784 | **0** | ORPHANED |
| 6b | `PaymentHistoryTestFactory` | `tests/scalability/payment_history_test_factory.py` | 587 | 3 | Domain-specific load testing |
| 7 | `VereningingenTestCase` | `tests/utils/base.py` | 2,532 | 116 | ERPNext financial integration base |
| 8 | `SEPATestDataFactory` | `tests/fixtures/sepa_test_factory.py` | ~400 | Used by EnhancedTestCase | SEPA mandate creation for ETC |

### Two Parallel Hierarchies

**EnhancedTestCase** (365 files) and **VereningingenTestCase** (116 files) serve different purposes and should remain separate:

- **EnhancedTestCase**: Association management testing — field validation, email mocking, security/permission testing, Mollie webhooks, rate limit mocking, custom assertions
- **VereningingenTestCase**: ERPNext financial integration testing — Chart of Accounts, cost centers, payment modes, Sales Invoices, Payment Entries, ANBI donations, SEPA settings management

Both internally create an entity factory instance (`self.factory`) but use different classes and independently implement overlapping `create_test_*` methods.

### Shadow Factories

~44 test files define their own `create_*` methods locally:
- **27 pure shadow files**: No factory imports, define own creation methods
- **17 hybrid files**: Import a factory for base class but still define additional local `create_*` methods
- Concentrated in `tests/backend/components/`, `tests/test_*.py` (billing/dues), and `vereiningen/doctype/*/test_*.py`

---

## Overlap Analysis

### Methods Duplicated Across Factories

| Method | StreamlinedTDF | EnhancedTDF | SecureTDF | VereningingenTC |
|--------|:-:|:-:|:-:|:-:|
| `create_member` / `create_test_member` | Y | Y | Y | Y (shadowed) |
| `create_chapter` / `create_test_chapter` | Y | Y | Y | Y (shadowed) |
| `create_volunteer` / `create_test_volunteer` | Y | Y | Y | - |
| `create_membership` / `create_test_membership` | Y | Y | - | Y |
| `create_membership_type` | Y | Y | - | Y |
| `create_sepa_mandate` | Y | Y | - | Y |
| `create_test_iban` / `generate_test_iban` | Y | Y | Y | Y |
| `create_team` / `create_test_team` | Y | Y | - | - |
| `create_sales_invoice` | - | Y | - | Y |
| `create_donor` / `create_test_donor` | - | Y | - | Y |
| `create_donation` | - | Y | - | Y |
| `create_dues_schedule` | Y (scenario) | Y | - | Y |

### Critical Signature Differences for `create_member`

| Dimension | EnhancedTDF | StreamlinedTDF | VTC (shadowed) |
|-----------|-------------|----------------|----------------|
| **Signature** | `(**kwargs)` | `(chapter=None, **kwargs)` | `(**kwargs)` |
| **Names** | Internal generator (deterministic) | Faker (random) | Hardcoded `"Test"/"Member"` |
| **Email** | Hash-based (deterministic) | `fake.email()` (random) | `{hash6}@example.com` |
| **member_id** | Explicit generation | Not set (autoname) | Not set (autoname) |
| **ignore_permissions** | No (user-switches to Admin) | Yes | No (plain save) |
| **Auto-create Customer** | Yes (always) | No | No |
| **Chapter assignment** | `ChapterMembershipManager` (service) | Child table append | No |
| **Field validation** | Yes (against DocType meta) | No | No |

### IBAN Generation: 4 Implementations

| Factory | Method | Deterministic? | Delegation |
|---------|--------|:-:|---|
| EnhancedTDF | `create_test_iban(bank_code)` | Yes (sequential) | `iban_validator.generate_test_iban()` |
| StreamlinedTDF | `generate_test_iban(bank_code)` | No (random) | Inline MOD-97 |
| SecureTDF | `create_test_iban(bank_code)` | No | `iban_validator.generate_test_iban()` |
| VTC | `_get_test_iban(bank_code)` | No | `iban_validator.generate_test_iban()` with fallback |

---

## Design

### Guiding Principles

1. **ETC and VTC keep their identities** — they serve different concerns
2. **StreamlinedTestDataFactory becomes the canonical core** — it's already used by both hierarchies
3. **Enhance the core, not the consumers** — test files shouldn't need to change
4. **Domain-specific factories stay separate** — Ponto, SEPA mandate, payment history
5. **Opt-in for expensive behaviors** — Customer creation, field validation are optional flags

### Architecture After Consolidation

```
CoreTestDataFactory (enhanced, ~1,000 LOC)            ← THE canonical core
├── create_test_member(*, auto_create_customer=False, validate_fields=False, ...)
├── create_test_chapter(*, validate_fields=False, ...)
├── create_test_membership(...)
├── create_test_volunteer(...)
├── generate_test_iban(bank_code=None) → str
├── create_test_membership_type(...)
├── create_test_sepa_mandate(...)
├── create_test_team(...)
├── _generate_name(type) → str          [deterministic, from Enhanced]
├── _generate_email(purpose) → str      [deterministic, from Enhanced]
├── _generate_member_id() → str         [explicit, from Enhanced]
├── _validate_fields(doctype, data)     [opt-in, from Enhanced]
├── track_doc(doctype, name)
└── cleanup()

EnhancedTestDataFactory (~4,800 LOC, trimmed)
├── HAS-A CoreTestDataFactory (self.core)
├── create_member(**kwargs)              → delegates to self.core.create_test_member(
│                                            auto_create_customer=True, validate_fields=True)
├── create_chapter(**kwargs)             → delegates to self.core.create_test_chapter(
│                                            validate_fields=True)
├── [KEEPS] email mocking (5 pathways)
├── [KEEPS] permission testing (MockRolesContext, as_user)
├── [KEEPS] Mollie testing methods
├── [KEEPS] ensure_* idempotent methods
├── [KEEPS] force_unique_name()
├── [ABSORBS] SecureTestDataFactory capabilities
│   ├── validate_required_fields(doctype, data)
│   ├── cleanup_with_verification()
│   └── with_secure_test_data() decorator
└── [REMOVES] create_member/chapter/volunteer/iban (delegated to core)

EnhancedTestCase (365 files, unchanged interface)
├── self.factory = EnhancedTestDataFactory()
├── create_test_member(**kwargs) → self.factory.create_member(**kwargs)
└── [everything else unchanged]

VereningingenTestCase (116 files, cleaned up)
├── self.factory = CoreTestDataFactory()
├── create_test_member(**kwargs) → self.factory.create_test_member(**kwargs)  [ONLY the delegation version]
├── [REMOVES] shadowed method definitions (lines 706-884)
├── [KEEPS] ERPNext infrastructure setup
├── [KEEPS] ANBI donation helpers
├── [KEEPS] SEPA settings backup/restore
└── [KEEPS] create_test_sales_invoice (ERPNext-specific, not in core)

Domain-Specific Factories (UNCHANGED):
├── PontoTestDataFactory         — pure API mocks, no overlap
├── SEPAMandateTestDataFactory   — SEPA compliance scenarios
├── SEPATestDataFactory          — extends Enhanced for SEPA mandates
└── PaymentHistoryTestFactory    — extends CoreTestDataFactory for load testing
```

### Core Factory Method Signatures

After consolidation, `StreamlinedTestDataFactory` will have these canonical signatures:

```python
class StreamlinedTestDataFactory:
    """Canonical test data factory. All entity creation flows through here."""

    def __init__(self, cleanup_on_exit=True, seed=None):
        self.cleanup_on_exit = cleanup_on_exit
        self.seed = seed or int(time.time())
        self._sequence_counters = {}
        self._tracked_docs = []  # (doctype, name, priority) tuples

    # --- Core Entity Creation ---

    def create_test_member(self, *, chapter=None,
                           auto_create_customer=False,
                           validate_fields=False, **kwargs):
        """Create a test Member document.

        Args:
            chapter: Chapter name or doc to assign member to (via ChapterMembershipManager)
            auto_create_customer: If True, also creates ERPNext Customer + Address
            validate_fields: If True, validates kwargs against DocType schema
            **kwargs: Field overrides for the Member document
        """

    def create_test_chapter(self, *, validate_fields=False, **kwargs):
        """Create a test Chapter document. Auto-creates Region if needed."""

    def create_test_membership(self, *, member=None,
                                membership_type=None, **kwargs):
        """Create a test Membership document."""

    def create_test_membership_type(self, **kwargs):
        """Create a test Membership Type document."""

    def create_test_volunteer(self, *, member=None, **kwargs):
        """Create a test Volunteer document."""

    def create_test_team(self, **kwargs):
        """Create a test Team document."""

    def create_test_team_member(self, *, team=None,
                                 volunteer=None, **kwargs):
        """Create a test Team Member document."""

    def create_test_sepa_mandate(self, *, member=None, **kwargs):
        """Create a test SEPA Mandate document."""

    # --- IBAN Generation ---

    def generate_test_iban(self, bank_code=None):
        """Generate a valid Dutch test IBAN.

        Uses deterministic sequential generation via iban_validator.
        Bank codes cycle through TEST/MOCK/DEMO.
        """

    def derive_bic_from_test_iban(self, iban):
        """Derive BIC code from a test IBAN."""

    # --- Idempotent Getters ---

    def get_or_create_test_region(self):
        """Get or create a shared test Region (cached per instance)."""

    def get_or_create_test_chapter(self):
        """Get or create a shared test Chapter (cached per instance)."""

    def get_or_create_test_membership_type(self):
        """Get or create a shared test Membership Type (cached per instance)."""

    # --- Internal Helpers ---

    def _generate_name(self, name_type="first"):
        """Deterministic name generation (replaces Faker dependency)."""

    def _generate_email(self, purpose="member"):
        """Deterministic email generation based on sequence + seed."""

    def _generate_member_id(self):
        """Generate explicit member_id to avoid autoname counter collisions."""

    def _validate_fields(self, doctype, data):
        """Validate field names exist in DocType meta. Raises on unknown fields."""

    def _get_next_sequence(self, prefix):
        """Get next sequence number for a given prefix (deterministic)."""

    # --- Lifecycle ---

    def track_doc(self, doctype, name, priority=0):
        """Track a document for cleanup. Higher priority = deleted first."""

    def cleanup(self):
        """Delete all tracked documents in priority order."""
```

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Core factory class | `StreamlinedTestDataFactory` | Already used by both VTC and PaymentHistoryTF via delegation/inheritance |
| `auto_create_customer` default | `False` | Only Enhanced needs Customers; most tests don't. Keeps core fast. |
| `validate_fields` default | `False` | Opt-in to avoid slowing tests that don't need schema validation. |
| `ignore_permissions` | Always `True` in core | Test speed. Enhanced's user-switching was slower for no test-correctness benefit. |
| Chapter assignment | `ChapterMembershipManager` (service layer) | Correct behavior; child table append bypasses hooks/history tracking. |
| IBAN generation | Deterministic sequential (from Enhanced) | Reproducible test runs; delegates to production `iban_validator`. |
| Name generation | Internal deterministic (from Enhanced) | Faker is non-deterministic and adds a heavy dependency for names. |
| `member_id` | Explicit generation in core | Prevents autoname counter collisions (fixed in commit a4513777). |
| Faker dependency | Remove from core | Move to optional parameter; tests wanting random data can pass `first_name=fake.first_name()`. |

---

## Implementation Plan

### Phase 1: Cleanup (minimal risk, no behavior changes) — COMPLETE

**Completed:** 2026-02-21, commit `614f356e`
**Result:** -1,500 LOC. Renamed StreamlinedTDF → CoreTestDataFactory, deleted orphaned/bridge modules, removed shadowed methods, absorbed SecureTestDataFactory.
**Estimated effort: 1-2 hours**

#### Step 1.1: Delete orphaned factory
- Delete `tests/fixtures/payment_history_test_factory.py` (784 LOC)
- Verify: only imported by `examples/scalability_testing_example.py` (non-test file)
- Update or remove the example file reference

#### Step 1.2: Delete bridge module and update importers
- Delete `tests/test_data_factory.py` (31 LOC bridge)
- Update 12 files that import via bridge to use canonical path:
  ```python
  # Before:
  from vereiningen.tests.test_data_factory import TestDataFactory
  # After:
  from vereiningen.tests.fixtures.test_data_factory import StreamlinedTestDataFactory as TestDataFactory
  ```
- Files to update:
  - `tests/backend/components/test_member_iban_history.py`
  - `tests/backend/components/test_member_lifecycle_iban.py`
  - `tests/backend/performance/test_performance_edge_cases.py`
  - `tests/backend/workflows/test_member_lifecycle_complete.py`
  - `tests/fixtures/test_data_factory_extended.py`
  - `tests/test_invoice_validation_safeguards.py`
  - `tests/test_payment_history_scalability.py`
  - `tests/test_sepa_mandate_member_integration_service.py`
  - `tests/utils/test_environment_validator.py`
  - `tests/workflows/test_enhanced_membership_lifecycle.py`
  - `tests/backend/components/test_membership_dues_system.py` (already uses canonical)
  - `tests/utils/setup_helpers.py` (if applicable)

#### Step 1.3: Remove shadowed methods from VereningingenTestCase
- In `tests/utils/base.py`, the methods at lines ~706-884 are overridden at runtime by delegation methods at lines ~2293-2310
- Delete the shadowed (never-executed) implementations
- Keep only the delegation wrappers:
  ```python
  def create_test_member(self, **kwargs):
      member = self.factory.create_test_member(**kwargs)
      self.track_doc("Member", member.name)
      return member
  ```
- **Note**: Fix the double-tracking bug — `self.factory.create_test_member()` already calls `track_doc` internally. Remove the redundant `self.track_doc()` call in the wrapper OR remove tracking from Streamlined's internals and let callers track.

#### Step 1.4: Absorb SecureTestDataFactory into EnhancedTestDataFactory
- Move these 3 unique capabilities into Enhanced:
  - `validate_required_fields(doctype, data)` — auto-fill missing required fields with type-aware defaults
  - `cleanup_with_verification()` — verify each deletion succeeded
  - `with_secure_test_data()` — function decorator that injects factory
- Update 3 consumer files:
  - `tests/fixtures/test_secure_factory.py` — update imports
  - `tests/test_membership_application_skills_secure.py` — update imports
  - `vereiningen/doctype/chapter_member/test_chapter_members.py` — update imports
- Delete `tests/fixtures/secure_test_data_factory.py` (471 LOC)

**Phase 1 deliverables:**
- ~1,600 LOC deleted (784 orphaned + 471 Secure + 31 bridge + ~300 shadowed methods)
- 15-18 files updated
- No test behavior changes

---

### Phase 2: Core Enhancement + Enhanced Delegation — COMPLETE

**Completed:** 2026-02-22, commit `1ffda7ff`
**Result:** -126 LOC (362 insertions, 488 deletions). CoreTestDataFactory enhanced with deterministic generation, keyword-only params, ChapterMembershipManager integration, IBAN delegation. EnhancedTestDataFactory refactored to delegate create_member (~135→~60 LOC), create_chapter (~104→~25 LOC), create_volunteer (~103→~40 LOC), create_test_iban (→ one-liner). Zero test regressions verified by side-by-side comparison on old/new code.

**Implementation notes:**
- `_generate_name("last")` appends `test_run_id[-5:]` suffix to prevent Customer name collisions (Customer uses full_name as PK)
- `_generate_member_id()` uses microsecond timestamp + sequence (not seed hash) for cross-instance uniqueness
- `_generate_email()` uses `test_run_id` (not seed) for cross-instance uniqueness
- `chapter` param on `create_test_member`: `None` = auto-create, `False` = skip, string/doc = assign
- Chapter assignment falls back to child table append if ChapterMembershipManager fails (for tests without Verenigingen Settings)
- Enhanced unique_suffix logic preserved for explicitly-provided kwargs names

**Estimated effort: 6-8 hours**

#### Step 2.1: Enhance StreamlinedTestDataFactory with best patterns

Add to `tests/fixtures/test_data_factory.py`:

1. **Deterministic name generation** (from Enhanced):
   ```python
   _FIRST_NAMES = ["Adam", "Eva", "Jan", "Maria", "Pieter", "Anna", ...]
   _LAST_NAMES = ["De Vries", "Jansen", "Van Dijk", "Bakker", "Visser", ...]

   def _generate_name(self, name_type="first"):
       names = self._FIRST_NAMES if name_type == "first" else self._LAST_NAMES
       idx = self._get_next_sequence(f"name_{name_type}") % len(names)
       return names[idx]
   ```

2. **Deterministic email generation** (from Enhanced):
   ```python
   def _generate_email(self, purpose="member"):
       seq = self._get_next_sequence(f"email_{purpose}")
       return f"test-{purpose}-{seq:04d}@test.invalid"
   ```

3. **Explicit member_id generation** (from Enhanced):
   ```python
   def _generate_member_id(self):
       seq = self._get_next_sequence("member_id")
       return f"TEST-MBR-{self.seed}-{seq:06d}"
   ```

4. **Optional field validation** (from Enhanced/Secure):
   ```python
   def _validate_fields(self, doctype, data):
       meta = frappe.get_meta(doctype)
       valid_fields = {f.fieldname for f in meta.fields}
       valid_fields |= {"doctype", "name", "owner", "docstatus", ...}
       unknown = set(data.keys()) - valid_fields
       if unknown:
           raise ValueError(f"Unknown fields for {doctype}: {unknown}")
       return data
   ```

5. **`auto_create_customer` flag** on `create_test_member`:
   ```python
   if auto_create_customer:
       member.create_customer()
       member.reload()
       self._create_customer_address(member)
   ```

6. **Chapter assignment via service** (replace child table append):
   ```python
   if chapter:
       from vereiningen.services.member.chapter.chapter_membership_manager import (
           ChapterMembershipManager,
       )
       ChapterMembershipManager.assign_member_to_chapter(member.name, chapter_name)
   ```

#### Step 2.2: Refactor EnhancedTestDataFactory to delegate

In `tests/fixtures/enhanced_test_factory.py`:

1. Add `self.core = StreamlinedTestDataFactory(seed=self.seed)` to `__init__`
2. Replace `create_member()` implementation (~80 LOC) with delegation:
   ```python
   def create_member(self, **kwargs):
       member = self.core.create_test_member(
           auto_create_customer=True,
           validate_fields=True,
           **kwargs,
       )
       # Enhanced-specific post-processing (if any)
       return member
   ```
3. Same for `create_chapter()`, `create_volunteer()`, `create_test_iban()`
4. Keep all Enhanced-specific methods (email mocking, permission testing, Mollie, ensure_*, etc.)
5. **Estimated deletion**: ~300-400 LOC of duplicate entity creation logic

#### Step 2.3: Clean up VereningingenTestCase delegation

In `tests/utils/base.py`:

1. The delegation wrappers (lines ~2293-2310) should be the ONLY entity creation methods
2. Remove the double-tracking: either track in Streamlined OR in VTC, not both
3. Keep all VTC-specific methods:
   - `ensure_erpnext_infrastructure()` and all ERPNext account/cost center helpers
   - `create_test_sales_invoice()` (ERPNext-specific, beyond core scope)
   - `create_test_donor()`, `create_test_donation()`, `create_anbi_compliant_agreement()`
   - SEPA settings backup/restore
   - `setup_payment_modes()`

#### Step 2.4: Update PaymentHistoryTestFactory inheritance

`tests/scalability/payment_history_test_factory.py` extends `StreamlinedTestDataFactory`. After Step 2.1, it automatically gets the enhanced core. Verify:
- Its `create_payment_history_batch()` still works with the new `create_test_member()` signature
- Any direct calls to super methods use the right parameter names

#### Step 2.5: Verify all tests pass

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen
```

Run the full test suite. Fix any regressions from signature changes.

**Phase 2 deliverables:**
- Core entity creation unified in one place
- EnhancedTDF and VTC delegate to core
- ~400 LOC of duplicate logic removed (net)
- Deterministic, reproducible test data across all factories

---

### Phase 3: Shadow Factory Migration (medium risk, per-file analysis)

**Estimated effort: 4-8 hours**

#### Step 3.1: Categorize shadow factories

For each of the ~44 files with local `create_*` methods, classify into:

**Category A — Direct replacement** (~20 files):
Local `create_test_member()` is a simple `frappe.get_doc({...}).insert()` with no special logic. Replace with factory import.

Example before:
```python
def create_test_member(self, **kwargs):
    member = frappe.get_doc({"doctype": "Member", "first_name": "Test", ...})
    member.insert(ignore_permissions=True)
    return member
```

Example after:
```python
# setUp:
self.factory = StreamlinedTestDataFactory()
# In test method:
member = self.factory.create_test_member(**kwargs)
```

**Category B — Parameterized replacement** (~15 files):
Local method has specific defaults needed for that test suite. Replace with factory call + kwargs.

Example: test file always creates members with `status="Pending"`:
```python
member = self.factory.create_test_member(status="Pending")
```

**Category C — Intentionally different** (~9 files):
Local method creates intentionally invalid/edge-case data for negative testing. Keep as-is but document why.

Example: test creates member without required fields to test validation.

#### Step 3.2: Execute migration

For each Category A and B file:

1. Add factory import or use base class factory
2. Replace local `create_*` method calls with factory calls
3. Remove local method definition
4. Run that file's tests to verify

**Priority order** (by consumer count of the shadow pattern):
1. `tests/backend/components/test_base.py` — base class used by other component tests
2. `tests/backend/components/test_membership_dues_enhanced_features.py` — 6 local methods
3. `tests/test_chapter_board_permissions_comprehensive.py` — 11 local methods
4. `tests/workflows/test_volunteer_board_finance_persona.py` — 3 local methods
5. Remaining files alphabetically

#### Step 3.3: Document Category C exceptions

For files that intentionally bypass factories, add a comment:
```python
# NOTE: This test intentionally creates invalid data to test validation.
# Do not replace with factory — the factory enforces valid defaults.
```

**Phase 3 deliverables:**
- ~800 LOC of shadow factory code removed
- ~35 files standardized to use canonical factories
- ~9 files documented as intentional exceptions

---

## What Stays Separate (No Changes)

| Factory | Reason |
|---------|--------|
| `PontoTestDataFactory` (699 LOC) | Pure API mock data (JSON responses, JWT signing). Zero overlap with entity creation. |
| `SEPAMandateTestDataFactory` (746 LOC) | Domain-specific SEPA compliance scenarios (PSD2, GDPR, DNB). Uses Enhanced as optional dependency. |
| `SEPATestDataFactory` (~400 LOC) | Extends Enhanced for SEPA mandate creation. Bridge between Enhanced and SEPA domain. |
| `PaymentHistoryTestFactory` (587 LOC) | Extends Streamlined for scalability/load testing. Automatically benefits from Phase 2 core improvements. |
| `CostCenterTestDataFactory` | Extends Enhanced for eBoekhouden cost center testing. |

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Broken tests after Phase 2 signature changes | Run full test suite after each step; Phase 2 changes internal implementation, not external interfaces |
| Double-tracking cleanup issues | Audit track_doc calls; establish single tracking point (core factory) |
| Shadow factory migration breaks negative tests | Category C classification preserves intentional edge cases |
| Faker removal breaks test data | Replace with deterministic generators that produce same quality data |
| ChapterMembershipManager assignment differs from child table append | This is the correct behavior; tests should use the service layer |

---

## Success Criteria

After all 3 phases:

1. **Single source of truth** for core entity creation (`StreamlinedTestDataFactory`)
2. **No duplicate `create_member` implementations** — all factories delegate to core
3. **Deterministic test data** — same seed produces same data across runs
4. **~2,800 LOC removed** (1,600 Phase 1 + 400 Phase 2 + 800 Phase 3)
5. **All existing tests pass** without modification (except import path changes)
6. **Clear guidance** for new tests: use `EnhancedTestCase` for association tests, `VereningingenTestCase` for ERPNext financial tests

---

## Metrics

| Metric | Before | After |
|--------|--------|-------|
| Factory files | 8 + bridge | 6 (Streamlined, Enhanced, SEPA Mandate, Ponto, PaymentHistory scalability, SEPATest) |
| Total factory LOC | ~12,500 | ~9,700 |
| `create_member` implementations | 4 | 1 (in core, called by all) |
| `create_test_iban` implementations | 4 | 1 (in core) |
| Shadow factory files | ~44 | ~9 (intentional exceptions only) |
| Test files needing import changes | 0 | ~65 (Phase 1: 18, Phase 2: ~5, Phase 3: ~42) |
