# Service Architecture Refactoring Specification

**Version:** 1.0
**Date:** 2025-12-03
**Status:** Approved

---

## Executive Summary

This specification defines the refactoring plan to align all service classes with the established `BaseService` architecture in `verenigingen/services/infrastructure/base_service.py`. The goal is consistent logging, error handling, performance metrics, and result patterns across ~56 service files.

---

## 1. Current State Analysis

### 1.1 Compliance Metrics

| Metric | Count | Rate |
|--------|-------|------|
| Total service files | 56 | - |
| Properly inheriting BaseService | 2 | 3.6% |
| Using direct `frappe.logger()` | 46 | 82% |
| Using `@staticmethod` | 41 files (174 occurrences) | Anti-pattern |
| Custom result classes | 8 | Fragmented |

### 1.2 Existing Infrastructure

**Base Classes** (`services/infrastructure/base_service.py`):
- `BaseService` - Abstract base with logging, metrics, error handling
- `StatelessService` - For pure calculations/validations
- `StatefulService` - For transaction management
- `DataService` - For CRUD with caching
- `APIService` - For external integrations

**Result Utilities**:
- `OperationResult[T]` (`utils/operation_result.py`) - Generic, type-safe, with chaining/mapping
- `OperationResult.from_dict_result()` - Legacy dict conversion
- `create_service_result()` (`utils/service_error_handler.py`) - Dict-based (deprecated)
- `handle_service_error()` - Standardized error logging
- `ServiceError` - Custom exception class

---

## 2. Target Architecture

### 2.1 Result Type Consolidation

**Primary Result Type: `OperationResult[T]`**

All services SHOULD return `OperationResult[T]` for operations that can fail.

```python
from verenigingen.utils.operation_result import OperationResult

def create_member(data: dict) -> OperationResult[Member]:
    if not data.get("email"):
        return OperationResult.fail("Email is required", errors=["email"])
    member = frappe.get_doc({"doctype": "Member", **data}).insert()
    return OperationResult.ok(member, created=True)
```

**Domain Data Structures**

For complex return data, define dataclasses as payloads:

```python
from dataclasses import dataclass
from verenigingen.utils.operation_result import OperationResult

@dataclass
class CoveragePeriod:
    """Pure data structure - no success/fail semantics."""
    start_date: date
    end_date: date
    calculation_method: str

def calculate_coverage(...) -> OperationResult[CoveragePeriod]:
    period = CoveragePeriod(start, end, "sequential")
    return OperationResult.ok(period)
```

### 2.2 Result Class Disposition

| Current Class | Location | Disposition | Migration |
|---------------|----------|-------------|-----------|
| `CreationResult` | dues_schedule_creation_service.py | **REMOVE** | `OperationResult[str]` with `schedule_name` as data |
| `DuplicateInvoiceDetectionResult` | duplicate_invoice_detector.py | **REMOVE** | `OperationResult[None]` - success=can_generate |
| `ValidationResult` (TypedDict) | dues_schedule_validation_service.py | **REMOVE** | `OperationResult[Dict]` |
| `RecoveryResult` (TypedDict) | invoice_error_handler_service.py | **REMOVE** | `OperationResult[Dict]` |
| `ValidationResult` (dataclass) | payment/validation_service.py | **REMOVE** | Already uses `OperationResult` for APIs |
| `InvoiceGenerationResult` | invoice_generator.py | **REMOVE** | `OperationResult[SalesInvoice]` |
| `CoveragePeriodResult` | coverage_calculator.py | **SPLIT** | `CoveragePeriod` dataclass + `OperationResult[CoveragePeriod]` |
| `EligibilityResult` | eligibility_checker.py | **KEEP** | Domain-specific `category` field enables routing logic |

### 2.3 Base Class Selection Guide

| Service Characteristics | Base Class | Example Services |
|------------------------|------------|------------------|
| Pure calculations, validations, queries | `StatelessService` | `CoverageCalculator`, `EligibilityChecker`, `MemberFeeCalculationService` |
| Database transactions, workflow state | `StatefulService` | `MemberLifecycleService`, `SEPAMandateManager`, `DuesScheduleCreationService` |
| CRUD operations, bulk processing, caching | `DataService` | `ChapterQueryService`, `MemberHistoryUpdateService`, `DonationReportingService` |
| External API calls, webhooks | `APIService` | `MollieDebugService` |

---

## 3. Refactoring Patterns

### 3.1 Standard Service Refactoring

**Before:**
```python
class SomeService:
    @staticmethod
    def do_operation(param):
        try:
            frappe.logger().info("Starting operation")
            result = some_logic(param)
            return {"success": True, "data": result}
        except Exception as e:
            frappe.logger().error(f"Failed: {e}")
            return {"success": False, "error": str(e)}
```

**After:**
```python
from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.operation_result import OperationResult

class SomeService(StatelessService):
    def __init__(self):
        super().__init__(service_name="SomeService")

    def do_operation(self, param) -> OperationResult[Any]:
        def _logic():
            self.logger.info("Starting operation")
            return some_logic(param)

        try:
            result = self.execute_operation(_logic)
            return OperationResult.ok(result)
        except Exception as e:
            self.handle_error(e, "do_operation", {"param": param}, raise_error=False)
            return OperationResult.fail(str(e))
```

### 3.2 Backward Compatibility Pattern

For services with existing static method consumers:

```python
class SomeService(StatelessService):
    _instance = None

    def __init__(self):
        super().__init__(service_name="SomeService")

    @classmethod
    def get_instance(cls) -> "SomeService":
        """Singleton accessor for backward compatibility."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def do_operation(self, param) -> OperationResult[Any]:
        # Instance method implementation
        ...

    # Deprecated static wrapper - remove after all callers updated
    @staticmethod
    def do_operation_static(param) -> OperationResult[Any]:
        """Deprecated: Use SomeService().do_operation() instead."""
        return SomeService.get_instance().do_operation(param)
```

### 3.3 Transaction-Aware Pattern

For services requiring database transactions:

```python
from verenigingen.services.infrastructure.base_service import StatefulService
from verenigingen.utils.operation_result import OperationResult

class MemberCleanupService(StatefulService):
    def __init__(self):
        super().__init__(service_name="MemberCleanupService")

    def cleanup_member_records(self, member_name: str) -> OperationResult[int]:
        def _cleanup():
            count = 0
            # cleanup logic
            return count

        try:
            result = self.execute_with_transaction(_cleanup)
            return OperationResult.ok(result, records_cleaned=result)
        except Exception as e:
            return OperationResult.fail(str(e), error_category="cleanup")
```

### 3.4 Converting Result Classes

**From custom result to OperationResult:**

```python
# Before: Custom result class
class CreationResult:
    def __init__(self, success, schedule_name=None, error=None, error_category=None, retry_job_id=None):
        ...

def create_schedule(...) -> CreationResult:
    return CreationResult(success=True, schedule_name="DUES-001")

# After: OperationResult with metadata
def create_schedule(...) -> OperationResult[str]:
    return OperationResult.ok("DUES-001", retry_job_id=None)
    # or on failure:
    return OperationResult.fail("Creation failed", error_category="validation", retry_job_id="job-123")
```

**From data+validation result to separated concerns:**

```python
# Before: Mixed data and validation
class CoveragePeriodResult:
    def __init__(self, start_date, end_date, calculation_method, **metadata):
        ...
    def is_valid(self) -> bool:
        ...

# After: Pure data structure
@dataclass
class CoveragePeriod:
    start_date: date
    end_date: date
    calculation_method: str

# Validation in the operation
def calculate_coverage(...) -> OperationResult[CoveragePeriod]:
    period = CoveragePeriod(start, end, method)
    if period.start_date > period.end_date:
        return OperationResult.fail("Invalid period: start after end")
    return OperationResult.ok(period)
```

---

## 4. Migration Phases

### Phase 1: Billing Services (Week 1-2)
**Priority: P1 - High business impact, well-tested**

| Service | Current | Target | Effort |
|---------|---------|--------|--------|
| `InvoiceGenerator` | Plain class | StatelessService | Medium |
| `CoverageCalculator` | Plain class | StatelessService | Low |
| `EligibilityChecker` | Plain class | StatelessService | Low |
| `DuplicateInvoiceDetector` | Plain class | StatelessService | Low |
| `DuesScheduleCreationService` | Plain class | StatefulService | Medium |
| `DuesScheduleValidationService` | Plain class | StatelessService | Low |
| `TemplateConfigurationService` | Plain class | StatelessService | Low |
| `TemplateCreationService` | Plain class | StatelessService | Low |
| `InvoiceErrorHandlerService` | Plain class | StatelessService | Low |

**Result Class Migrations in Phase 1:**
- Remove `InvoiceGenerationResult` → `OperationResult[SalesInvoice]`
- Remove `CoveragePeriodResult` → `CoveragePeriod` dataclass + `OperationResult[CoveragePeriod]`
- Remove `CreationResult` → `OperationResult[str]`
- Remove `DuplicateInvoiceDetectionResult` → `OperationResult[None]`
- Remove `ValidationResult` (TypedDict) → `OperationResult[Dict]`
- Remove `RecoveryResult` → `OperationResult[Dict]`
- Keep `EligibilityResult` (domain-specific routing via `category`)

### Phase 2: Member Services (Week 3-4)
**Priority: P2 - Largest volume, extracted from Member DocType**

| Service | Target Base |
|---------|-------------|
| `MemberLifecycleService` | StatefulService |
| `MemberAddressService` | StatelessService |
| `MemberCleanupService` | StatefulService |
| `MemberFeeChangeService` | StatefulService |
| `MemberIDService` | StatelessService |
| `MemberFeeCalculationService` | StatelessService |
| `MemberFeeValidationService` | StatelessService |
| `MemberItemService` | DataService |
| `MemberHistoryUpdateService` | DataService |
| `MemberFeeChangeHistoryService` | DataService |
| `MemberUserAccountService` | StatefulService |
| `MemberRoleService` | StatelessService |
| `MembershipCreationService` | StatefulService |
| `MemberDonorIntegrationService` | StatefulService |
| `DonorManagementService` | StatefulService |
| `MemberDebugService` | StatelessService |
| `MemberVolunteerDisplayService` | StatelessService |
| `MemberChapterDisplayService` | StatelessService |
| `MemberAddressDisplayService` | StatelessService |

### Phase 3: Chapter Services (Week 5)
**Priority: P3**

| Service | Target Base |
|---------|-------------|
| `ChapterAssignmentService` | StatefulService |
| `ChapterValidationService` | StatelessService |
| `ChapterPermissionService` | StatelessService |
| `ChapterFinanceService` | DataService |
| `ChapterQueryService` | DataService |
| `ChapterMatchingService` | StatelessService |
| `ChapterBoardService` | StatefulService |
| `ChapterEventService` | StatefulService |
| `DepartmentSyncService` | StatefulService |
| `ChapterManagementService` | StatefulService |

### Phase 4: Payment & Volunteer Services (Week 6)
**Priority: P4**

| Service | Target Base |
|---------|-------------|
| `SEPAMandateManager` | StatefulService |
| `PaymentValidationService` | StatelessService |
| `PaymentProcessingService` | StatefulService |
| `VolunteerActivityService` | StatefulService |
| `VolunteerAssignmentService` | StatefulService |
| `VolunteerExpenseApproverService` | StatelessService |
| `VolunteerExpenseSubmissionService` | StatefulService |
| `AssignmentQueryBuilder` | StatelessService |

### Phase 5: Remaining Services (Week 7)
**Priority: P5**

| Service | Target Base |
|---------|-------------|
| `DonationManagementService` | StatefulService |
| `DonationValidationService` | StatelessService |
| `DonationDonorService` | StatefulService |
| `DonationFinancialService` | DataService |
| `DonationReportingService` | DataService |
| `EmailService` | StatelessService |
| `NotificationDispatcher` | StatelessService |
| `TemplateManager` | StatelessService |
| `TerminationExecutionService` | StatefulService |
| `TerminationAuditService` | DataService |
| `TerminationApprovalService` | StatefulService |
| `AccountCreationService` | StatefulService |
| `TeamService` | StatefulService |
| `TeamValidationService` | StatelessService |
| `MollieDebugService` | APIService |
| `ANBIValidationService` | StatelessService |
| `MemberMergeService` | StatefulService |
| `CustomerService` | StatefulService |
| `FieldSyncService` | StatefulService |

---

## 5. Testing Requirements

### 5.1 Per-Service Migration Tests

Each refactored service MUST have:

1. **Unit tests** verifying identical behavior before/after
2. **Logging verification** - confirm `self.logger` calls work
3. **Metrics verification** - confirm `get_metrics()` returns valid data
4. **Error handling tests** - verify `OperationResult.fail()` cases
5. **Type hints** - all public methods should have return type annotations

### 5.2 Integration Tests

After each phase:
- Run full test suite: `make test`
- Run phase-specific tests
- Verify no regressions in DocType hooks calling services

### 5.3 Regression Testing Pattern

```python
class TestServiceMigration(EnhancedTestCase):
    def test_old_api_still_works(self):
        """Verify backward compatibility during migration."""
        # Old pattern (if deprecated wrapper exists)
        old_result = SomeService.static_method(param)

        # New pattern
        new_result = SomeService().method(param)

        # Both should produce equivalent results
        self.assertEqual(old_result, new_result.to_dict())
```

---

## 6. Rollback Strategy

Each service migration is atomic:
1. Create feature branch per service or small group
2. Refactor with backward-compatible wrappers if needed
3. Update direct callers
4. Remove deprecated wrappers after validation
5. If issues found, revert single service without affecting others

---

## 7. Success Criteria

| Metric | Current | Target |
|--------|---------|--------|
| BaseService inheritance | 3.6% | 100% |
| Direct `frappe.logger()` usage | 46 files | 0 files |
| `@staticmethod` in services | 174 occurrences | 0 (except justified cases) |
| Custom result classes | 8 | 1 (`EligibilityResult`) |
| `OperationResult` adoption | Partial | Standard for all fallible operations |
| Type hints on public methods | Partial | 100% |

---

## 8. Appendix: Quick Reference

### A. Import Template

```python
# Standard imports for refactored service
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import frappe
from frappe import _

from verenigingen.services.infrastructure.base_service import StatelessService  # or appropriate base
from verenigingen.utils.operation_result import OperationResult
```

### B. Method Signature Template

```python
def operation_name(self, param1: str, param2: Optional[int] = None) -> OperationResult[ReturnType]:
    """
    One-line description.

    Args:
        param1: Description
        param2: Description (optional)

    Returns:
        OperationResult containing ReturnType on success, error details on failure
    """
```

### C. Converting Existing Patterns

| From | To |
|------|-----|
| `return {"success": True, "data": x}` | `return OperationResult.ok(x)` |
| `return {"success": False, "error": e}` | `return OperationResult.fail(str(e))` |
| `frappe.logger().info(msg)` | `self.logger.info(msg)` |
| `frappe.log_error(msg)` | `self.handle_error(e, "operation", ctx)` |
| `@staticmethod` | Remove, use instance method |
| `SomeService.method()` | `SomeService().method()` |
| `result["can_generate"]` | `result.success` |
| `result.to_dict()` | `result.to_dict()` (same API) |

### D. OperationResult API Reference

```python
# Creation
OperationResult.ok(data, **metadata)           # Success with data
OperationResult.fail(message, errors=[], **metadata)  # Failure

# Access
result.success          # bool
result.data             # T or None
result.error_message    # str or None
result.errors           # List[str]
result.metadata         # Dict[str, Any]

# Utilities
result.unwrap()         # Returns data or raises ValueError
result.unwrap_or(default)  # Returns data or default
result.map(func)        # Transform data if successful
result.chain(message)   # Add context to failure
result.to_dict()        # Convert to dict for APIs

# Legacy conversion
OperationResult.from_dict_result({"success": True, "data": x})
```

### E. Compliant Service Examples

**Reference implementations:**
- `MemberMembershipService` (`services/member/core/member_membership_service.py`) - StatelessService
- `CustomerHandlingService` (`services/customer_handling_service.py`) - StatefulService

---

## 9. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-03 | Initial specification |
