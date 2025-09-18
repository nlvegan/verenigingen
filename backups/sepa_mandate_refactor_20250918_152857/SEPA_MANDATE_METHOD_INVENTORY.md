# SEPA Mandate Controller - Method Inventory and Refactoring Plan

**File**: `verenigingen/verenigingen_payments/doctype/sepa_mandate/sepa_mandate.py`
**Total Lines**: 624
**Analysis Date**: 2025-09-18
**Backup Location**: `/home/frappe/frappe-bench/apps/verenigingen/backups/sepa_mandate_refactor_20250918_152857/`

## Method Inventory

### 1. Core Validation and Lifecycle Methods

#### `validate()` (Lines 14-22)
- **Complexity**: Low
- **Responsibility**: Validation orchestration
- **Service Candidate**: No (remains in controller as orchestrator)
- **Dependencies**: Calls 4 validation methods

#### `auto_generate_mandate_id()` (Lines 23-50)
- **Complexity**: High
- **Responsibility**: ID generation with pattern support
- **Service Candidate**: **YES** - Extract to `SEPAMandateIdentityService`
- **Dependencies**: Verenigingen Settings, error handling

#### `_generate_mandate_id_with_counter()` (Lines 51-118)
- **Complexity**: Very High (68 lines)
- **Responsibility**: Complex pattern parsing and counter logic
- **Service Candidate**: **YES** - Extract to `SEPAMandateIdentityService`
- **Dependencies**: Regex, datetime, SQL queries

### 2. Status and Lifecycle Management

#### `sync_status_is_active()` (Lines 120-127)
- **Complexity**: Low
- **Responsibility**: Status synchronization
- **Service Candidate**: No (simple field sync)
- **Dependencies**: None

#### `set_status_based_on_dates()` (Lines 128-149)
- **Complexity**: Medium
- **Responsibility**: Date-based status calculation
- **Service Candidate**: **YES** - Extract to `SEPAMandateLifecycleService`
- **Dependencies**: Date utilities

#### `set_value()` (Lines 151-171)
- **Complexity**: Medium
- **Responsibility**: Complex field override logic
- **Service Candidate**: **YES** - Extract to `SEPAMandateLifecycleService`
- **Dependencies**: Document field handling

### 3. Validation Services

#### `validate_dates()` (Lines 173-189)
- **Complexity**: Medium
- **Responsibility**: Business rule validation for dates
- **Service Candidate**: **YES** - Extract to `SEPAMandateValidationService`
- **Dependencies**: DateRangeValidator

#### `validate_iban()` (Lines 191-206)
- **Complexity**: Medium-High
- **Responsibility**: IBAN validation and BIC derivation
- **Service Candidate**: **YES** - Extract to `SEPAMandateValidationService`
- **Dependencies**: IBAN validator, BIC lookup

### 4. Event Handlers

#### `after_insert()` (Lines 207-230)
- **Complexity**: Medium
- **Responsibility**: Post-creation lifecycle management
- **Service Candidate**: **YES** - Extract to `SEPAMandateLifecycleService`
- **Dependencies**: Member integration, status sync

#### `on_update()` (Lines 232-247)
- **Complexity**: Medium
- **Responsibility**: Status change handling
- **Service Candidate**: **YES** - Extract to `SEPAMandateLifecycleService`
- **Dependencies**: Status comparison, member updates

### 5. Member Integration (Highest Complexity Section)

#### `update_member_sepa_mandates_table()` (Lines 248-297)
- **Complexity**: Very High (50 lines)
- **Responsibility**: Main member-mandate integration
- **Service Candidate**: **YES** - Extract to `SEPAMandateMemberIntegrationService`
- **Dependencies**: Permissions, validation, secure operations

#### `_validate_sepa_mandate_permissions()` (Lines 299-361)
- **Complexity**: High (63 lines)
- **Responsibility**: Complex permission validation
- **Service Candidate**: **YES** - Extract to `SEPAMandateMemberIntegrationService`
- **Dependencies**: Permission resolver, member access

#### `_validate_mandate_link_fields()` (Lines 363-404)
- **Complexity**: Medium (42 lines)
- **Responsibility**: Field validation for mandate links
- **Service Candidate**: **YES** - Extract to `SEPAMandateMemberIntegrationService`
- **Dependencies**: Document existence validation

#### `_execute_secure_mandate_link_update()` (Lines 406-497)
- **Complexity**: Very High (92 lines)
- **Responsibility**: Complex SQL operations for member updates
- **Service Candidate**: **YES** - Extract to `SEPAMandateMemberIntegrationService`
- **Dependencies**: Secure operations, SQL transactions

#### `_create_sepa_audit_log()` (Lines 499-526)
- **Complexity**: Medium (28 lines)
- **Responsibility**: Audit logging for mandate operations
- **Service Candidate**: **YES** - Extract to `SEPAMandateMemberIntegrationService`
- **Dependencies**: Audit context, logging utilities

### 6. Cancellation Logic

#### `cancel_mandate()` (Lines 528-567)
- **Complexity**: Medium (40 lines)
- **Responsibility**: Business logic for mandate cancellation
- **Service Candidate**: **YES** - Extract to `SEPAMandateLifecycleService`
- **Dependencies**: Status validation, member updates, notifications

### 7. Permission System

#### `has_permission()` (Lines 569-594)
- **Complexity**: Medium (26 lines)
- **Responsibility**: Custom permission logic
- **Service Candidate**: **MAYBE** - Could enhance existing permission service
- **Dependencies**: Permission resolver

#### `get_permission_query_conditions()` (Lines 596-624)
- **Complexity**: Medium (29 lines)
- **Responsibility**: Query filtering for permissions
- **Service Candidate**: **MAYBE** - Could enhance existing permission service
- **Dependencies**: Permission resolver, SQL conditions

## Refactoring Plan: 3-Phase Service Extraction

### Phase 1: Identity and Validation Services (Lines 23-206)
**Target**: Extract 5 methods, ~184 lines
- Create `SEPAMandateIdentityService` for ID generation
- Create `SEPAMandateValidationService` for business rule validation
- Create `SEPAMandateLifecycleService` for status management

### Phase 2: Member Integration Service (Lines 248-526)
**Target**: Extract 5 methods, ~279 lines
- Create `SEPAMandateMemberIntegrationService` for complex member operations
- Move all member-mandate relationship logic to service
- Maintain security and audit logging

### Phase 3: Lifecycle and Cancellation (Lines 207-567)
**Target**: Extract 3 methods, ~118 lines
- Enhance `SEPAMandateLifecycleService` with event handlers
- Move cancellation logic to lifecycle service
- Integrate with notification system

## Expected Outcomes

### Code Reduction
- **Current**: 624 lines
- **Target**: ~200-250 lines (60% reduction)
- **Service Lines**: ~400-450 lines in 4 new services

### Service Architecture
```
SEPA Mandate Controller (Slim)
├── SEPAMandateIdentityService
├── SEPAMandateValidationService
├── SEPAMandateLifecycleService
└── SEPAMandateMemberIntegrationService
```

### Benefits
- **Testability**: Each service can be unit tested independently
- **Reusability**: Services can be used by API endpoints, bulk operations
- **Maintainability**: Clear separation of concerns
- **SEPA Compliance**: Centralized compliance logic
- **Performance**: Optimized for bulk operations

## Risk Assessment

### Low Risk
- Identity generation (self-contained logic)
- Validation services (pure functions)

### Medium Risk
- Member integration (complex SQL, permissions)
- Lifecycle management (event handling)

### Dependencies to Verify
- Existing SEPA utilities integration
- Permission system compatibility
- Audit logging consistency
- Notification system integration

## Testing Strategy

### Unit Tests Required
- Each service method with mock dependencies
- Permission edge cases
- IBAN validation scenarios
- ID generation patterns

### Integration Tests Required
- Full mandate lifecycle workflows
- Member-mandate relationship operations
- Permission validation end-to-end
- Error handling and rollback scenarios
