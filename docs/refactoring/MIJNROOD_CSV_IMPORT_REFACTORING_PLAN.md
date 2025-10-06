# Mijnrood CSV Import Refactoring Plan

**Status**: Planning
**Priority**: Medium
**Estimated Effort**: 3-4 weeks
**Risk Level**: High (2,350+ lines of critical business logic)

## Current State Analysis

### File Metrics
- **Total Lines**: 2,350 (after dead code removal)
- **Method Count**: 44 methods
- **Responsibilities**: 10+ distinct concerns
- **Complexity**: God Object anti-pattern

### Core Problem
The `MijnroodCSVImport` DocType violates Single Responsibility Principle by handling:
1. CSV file I/O and parsing
2. Data validation and sanitization
3. Data transformation (dates, phones, countries)
4. Member CRUD operations
5. Address management
6. Membership/Dues schedule creation
7. Chapter assignment
8. Volunteer record creation
9. User account provisioning
10. Performance metrics and reporting

---

## Refactoring Strategy

### Phase 1: Extract Pure Functions (Low Risk, 2-3 days)

**Goal**: Move stateless data transformation logic to utility modules

#### 1.1 Create `verenigingen/utils/csv/data_transformers.py`
Extract these pure functions (currently lines 447-597):

```python
def clean_phone_number(phone: str) -> str
    """Clean and validate Dutch phone numbers"""

def convert_country_code(code: str) -> str
    """Convert country codes to full names"""

def parse_date(date_str: str) -> Optional[str]
    """Parse flexible date formats to YYYY-MM-DD"""

def convert_membership_type(type_str: str) -> str
    """Map legacy membership types to current system"""

def clean_value(value: str, field_type: str) -> Any
    """Generic value cleaning based on field type"""
```

**Testing**: Create `tests/test_csv_data_transformers.py` with 100% coverage

**Impact**: Zero risk - these are pure functions with no side effects

---

### Phase 2: Extract CSV Parser (Low-Medium Risk, 3-4 days)

**Goal**: Separate file I/O and CSV parsing from business logic

#### 2.1 Create `verenigingen/utils/csv/secure_csv_parser.py`

```python
class SecureCSVParser:
    """
    Security-hardened CSV parser with path traversal protection
    and injection prevention.
    """

    def read_csv_file(self, file_path: str) -> List[Dict]
        """Read CSV from file path with security checks"""

    def parse_csv_content(self, content: bytes, filename: str) -> List[Dict]
        """Parse CSV content from bytes"""

    def validate_file_path(self, path: str) -> bool
        """Check for path traversal and other security issues"""

    def sanitize_csv_content(self, csvfile) -> List[Dict]
        """Parse and sanitize CSV rows"""
```

**Extract Methods** (lines 91-373):
- `_read_csv_file()` → `SecureCSVParser.read_csv_file()`
- `_parse_csv_content()` → `SecureCSVParser.parse_csv_content()`
- `_is_safe_file_path()` → `SecureCSVParser.validate_file_path()`
- File resolution methods

**Testing**:
- Unit tests for parser
- Security tests for path traversal, CSV injection
- Integration tests with MijnroodCSVImport

**Impact**: Medium risk - file I/O changes could break import flow

---

### Phase 3: Extract Validation Layer (Medium Risk, 4-5 days)

**Goal**: Separate validation logic from DocType

#### 3.1 Create `verenigingen/utils/csv/csv_data_validator.py`

```python
class CSVDataValidator:
    """
    Validates CSV data against business rules before import.
    """

    def validate_row(self, row: Dict, row_num: int) -> List[str]
        """Validate single row against all rules"""

    def validate_email(self, email: str) -> bool
        """RFC-compliant email validation"""

    def validate_iban(self, iban: str) -> bool
        """SEPA IBAN validation with checksum"""

    def validate_and_map_data(self, csv_data: List[Dict]) -> Tuple[List[Dict], List[str]]
        """Validate and map all rows"""
```

**Extract Methods** (lines 374-771):
- `_validate_row()` → `CSVDataValidator.validate_row()`
- `_is_valid_email()` → `CSVDataValidator.validate_email()`
- `_is_valid_iban()` → `CSVDataValidator.validate_iban()`
- `_validate_and_map_data()` → `CSVDataValidator.validate_and_map_data()`

**Testing**:
- Edge case testing for each validation rule
- Performance testing for large datasets
- Regression testing against existing import data

**Impact**: Medium risk - validation changes could reject valid data

---

### Phase 4: Extract Member Import Service (HIGH Risk, 1-2 weeks)

**Goal**: Move core member creation/update logic to service layer

#### 4.1 Create `verenigingen/services/member_import_service.py`

```python
class MemberImportService:
    """
    Service layer for member creation/updates during CSV import.
    Handles all related record creation (addresses, memberships, etc.)
    """

    def create_or_update_member(self, row_data: Dict) -> Tuple[str, str]
        """Create new member or update existing based on match criteria"""

    def create_related_records(self, member: Document, row_data: Dict) -> None
        """Create address, membership, dues schedule, etc."""

    def handle_member_termination(self, member: Document, data: dict) -> None
        """Process member termination from CSV"""

    def assign_to_chapter(self, member: Document, chapter: str) -> None
        """Assign member to appropriate chapter"""
```

**Extract Methods** (lines 1124-1900):
- `_create_or_update_member()` → `MemberImportService.create_or_update_member()`
- `_update_member_fields()` → `MemberImportService.update_member_fields()`
- `_create_or_update_address()` → `MemberImportService.create_address()`
- `_create_related_records()` → `MemberImportService.create_related_records()`
- `_create_termination_record()` → `MemberImportService.handle_termination()`
- `_assign_member_to_chapter()` → `MemberImportService.assign_to_chapter()`

**Testing**:
- Full integration tests for each import scenario
- Test with production-like data volumes (10,000+ members)
- Validate Mollie data preservation
- Test termination workflow
- Verify chapter assignment logic

**Impact**: **HIGH RISK** - This is the core business logic. Any bugs here affect live member data.

**Migration Strategy**:
1. Create service layer with existing logic
2. Run in parallel mode: Call both old and new code, compare results
3. Monitor for 2 weeks in production
4. Switch to service-only mode
5. Remove old code after 1 month of stable operation

---

### Phase 5: Extract Membership/Dues Logic (Medium-High Risk, 4-5 days)

**Goal**: Separate membership and dues schedule creation

#### 5.1 Create `verenigingen/services/membership_import_service.py`

```python
class MembershipImportService:
    """
    Handles membership and dues schedule creation during CSV import.
    """

    def create_membership_from_csv(self, member: Document, data: dict) -> Document
        """Create membership record with CSV-provided data"""

    def create_dues_schedule(self, member: Document, data: dict) -> Document
        """Create dues schedule with custom rates"""

    def determine_membership_type(self, row_data: dict) -> str
        """Map CSV membership type to system type"""
```

**Extract Methods** (lines 1837-2036):
- `_create_membership_from_import()` → `MembershipImportService.create_membership()`
- `_create_dues_schedule_from_import()` → `MembershipImportService.create_dues_schedule()`
- `_determine_membership_type()` → `MembershipImportService.determine_membership_type()`
- `_calculate_next_invoice_date()` → `MembershipImportService.calculate_next_invoice_date()`

**Testing**:
- Test all membership type mappings
- Verify dues rate override logic
- Test billing frequency calculations
- Integration tests with existing Member.create_membership_on_approval()

**Impact**: Medium-High risk - Affects billing and financial data

---

### Phase 6: Extract Address Handler (Medium Risk, 2-3 days)

**Goal**: Separate address creation/update logic

#### 6.1 Create `verenigingen/services/address_import_handler.py`

```python
class AddressImportHandler:
    """
    Handles address creation and linking during member import.
    """

    def create_or_update_address(self, member: Document, data: Dict) -> str
        """Create or update address linked to member"""

    def link_address_to_member(self, member: Document, address_name: str) -> None
        """Update member's primary_address field"""
```

**Extract Methods** (lines 1466-1591):
- `_create_or_update_address()` → `AddressImportHandler.create_or_update_address()`

**Testing**:
- Test address matching logic
- Verify address updates don't overwrite manual changes
- Test link table population

**Impact**: Medium risk - Address linking is critical for postal services

---

### Phase 7: Consolidate Post-Processing (Low-Medium Risk, 2-3 days)

**Goal**: Clean up bulk operations that run after member import

#### 7.1 Keep These As Thin Wrappers
These methods already delegate to existing services - keep them:

- `_process_user_account_creation()` → Calls `AccountCreationManager`
- `_process_bulk_volunteer_creation()` → Calls `bulk_create_volunteers_for_members()`
- `_process_bulk_chapter_assignment()` → Calls chapter assignment utilities

**Action**: Document these as orchestration methods, not business logic

---

## Final Architecture

```
MijnroodCSVImport (DocType - 400-500 lines)
├── validate()                          # Frappe hook
├── on_submit()                         # Frappe hook
├── _validate_and_preview_csv()         # Uses SecureCSVParser
└── _finalize_import_results()          # Orchestration only

process_import_background()              # Background job entry point
└── Uses CSVImportBackgroundProcessor

Supporting Services:
├── CSVImportBackgroundProcessor         # Batch processing with progress tracking
├── SecureCSVParser                      # File I/O and CSV parsing
├── CSVDataValidator                     # Validation rules
├── Data Transformers                    # Pure functions for data cleaning
├── MemberImportService                  # Core member CRUD
├── AddressImportHandler                 # Address management
├── MembershipImportService              # Membership/Dues creation
└── Existing services remain unchanged:
    ├── AccountCreationManager
    ├── bulk_create_volunteers_for_members()
    └── optimized_chapter_lookup
```

---

## Testing Strategy

### Unit Testing
- Each extracted module gets comprehensive unit tests
- Target: 90%+ code coverage for new modules
- Use Enhanced Test Factory for realistic test data

### Integration Testing
- Full end-to-end CSV import tests
- Test with production-like datasets (10K+ rows)
- Validate data integrity after refactoring

### Regression Testing
- Export production CSV imports from last 6 months
- Re-run through refactored code
- Compare results with original imports

### Performance Testing
- Benchmark before/after refactoring
- Target: No performance degradation
- Monitor memory usage during large imports

---

## Risk Mitigation

### High-Risk Areas
1. **Member CRUD Logic** (Phase 4)
   - Parallel execution mode during transition
   - Extended monitoring period (4 weeks)
   - Rollback plan with feature flag

2. **Membership/Dues Creation** (Phase 5)
   - Affects billing - requires finance team review
   - Staged rollout: test environment → staging → production
   - Maintain audit trail of all changes

### Rollback Strategy
- Feature flag: `enable_refactored_csv_import`
- Keep old code intact until 1 month after full migration
- Database backups before each phase deployment
- Ability to revert to old code path in < 5 minutes

---

## Success Metrics

### Code Quality
- Reduce main DocType from 2,350 lines to < 500 lines
- Average method complexity: < 10 (from current 15+)
- Test coverage: > 85% (from current ~60%)

### Maintainability
- New developer onboarding time: < 2 hours (from 4+ hours)
- Time to add new CSV field: < 30 minutes (from 1-2 hours)
- Bug fix turnaround: < 1 day (from 2-3 days)

### Performance
- Import throughput: >= current performance
- Memory usage: <= current usage
- Error recovery time: <= current time

---

## Timeline

| Phase | Duration | Risk | Dependencies |
|-------|----------|------|--------------|
| Phase 1: Data Transformers | 2-3 days | Low | None |
| Phase 2: CSV Parser | 3-4 days | Low-Med | Phase 1 |
| Phase 3: Validator | 4-5 days | Medium | Phase 1, 2 |
| Phase 4: Member Service | 1-2 weeks | **HIGH** | Phase 1, 2, 3 |
| Phase 5: Membership Service | 4-5 days | Med-High | Phase 4 |
| Phase 6: Address Handler | 2-3 days | Medium | Phase 4 |
| Phase 7: Post-Processing | 2-3 days | Low-Med | All previous |

**Total Estimated Time**: 3-4 weeks (with 1 week buffer for unexpected issues)

---

## Approval Requirements

Before proceeding with this refactoring:
- [ ] Product owner sign-off (impacts import functionality)
- [ ] Finance team review (affects billing/dues logic)
- [ ] DevOps team capacity confirmation (deployment support needed)
- [ ] QA team resource allocation (extensive testing required)
- [ ] Backup/rollback procedures validated
- [ ] Monitoring dashboards configured for new services

---

## Post-Refactoring Benefits

### Developer Experience
- Clear separation of concerns
- Easier to understand and modify
- Simpler to add new CSV fields
- Better testability

### System Reliability
- Isolated failures (parser error doesn't affect member creation)
- Better error messages (know exactly which layer failed)
- Easier debugging (smaller, focused modules)

### Future Extensibility
- Easy to add new import sources (Excel, JSON, API)
- Reusable services for other import types
- Simpler to add new validation rules
- Better support for import customizations

---

## Conclusion

This refactoring addresses the God Object anti-pattern in `MijnroodCSVImport` by extracting 10+ responsibilities into focused service classes and utilities. While high-risk (especially Phase 4), the systematic approach with parallel execution, comprehensive testing, and staged rollout minimizes the danger. The long-term benefits in maintainability, reliability, and extensibility justify the 3-4 week investment.

**Recommended Next Step**: Start with Phase 1 (Data Transformers) - low risk, immediate value, builds confidence for later phases.
