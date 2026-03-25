# Service Infrastructure Usage Guide

## Overview

The Verenigingen service layer (`verenigingen/services/`) contains business logic organized by domain. Services are accessed via a singleton pattern and follow consistent conventions for error handling, transaction management, and testing.

## Service Directory Layout

```
services/
├── infrastructure/              # Framework: base classes, factory, field validation
│   ├── base_service.py          # StatelessService, DataService, APIService, StatefulService
│   ├── service_factory.py       # ServiceFactory with get_service_factory()
│   ├── service_integration.py   # Integration manager, health checks
│   └── field_validator.py       # DocType field validation
│
├── member/                      # Member domain (largest service group)
│   ├── account/                 # User account creation/linking
│   │   └── member_user_account_service.py
│   ├── application/             # Membership application processing
│   │   └── membership_application_service.py
│   ├── approval/                # Approval workflows
│   │   ├── member_approval_service.py
│   │   └── membership_creation_service.py
│   ├── chapter/                 # Chapter assignment operations
│   │   └── chapter_assignment_service.py
│   ├── core/                    # Lifecycle and status management
│   │   └── member_lifecycle_service.py
│   ├── display/                 # Display/formatting helpers
│   ├── donor/                   # Donor-specific operations
│   ├── financial/               # Financial operations
│   ├── history/                 # History tracking (BaseHistoryManager pattern)
│   ├── identification/          # Member ID generation
│   ├── integration/             # External system integration
│   ├── lifecycle/               # Status notification services
│   ├── payment/                 # Payment processing
│   ├── testing/                 # Test helpers
│   ├── utils/                   # Member-specific utilities
│   └── validation/              # Input validation
│
├── account/                     # Account operations
├── approval/                    # Approval workflow services
├── billing/                     # Billing and invoicing
├── chapter/                     # Chapter management services
├── communication/               # Email and notification services
│   └── email_service.py
├── csv_import/                  # CSV/data import services
│   ├── member_import_service.py
│   ├── membership_import_service.py
│   └── mollie_sync_service.py
├── document/                    # Document operation services
├── donation/                    # Donation processing
│   └── dashboard_service.py
├── monitoring/                  # Health monitoring services
├── payment/                     # Payment processing services
├── termination/                 # Membership termination
│   └── termination_execution_service.py
├── volunteer/                   # Volunteer management
│
├── member_merge_service.py      # Member merge operations (top-level)
├── customer_handling_service.py # Customer record management (top-level)
├── field_sync_service.py        # Field synchronization (top-level)
├── team_service.py              # Team operations (top-level)
└── anbi_validation_service.py   # ANBI compliance (top-level)
```

## Singleton Pattern

Most services use a module-level singleton accessed via a getter function. This is the standard pattern throughout the codebase:

```python
# In the service module (e.g., services/member/core/member_lifecycle_service.py)

_service_instance = None

def get_member_lifecycle_service() -> MemberLifecycleService:
    """Get or create the singleton MemberLifecycleService instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MemberLifecycleService()
    return _service_instance
```

### Using a Service

```python
from verenigingen.services.member.core.member_lifecycle_service import (
    get_member_lifecycle_service,
)

service = get_member_lifecycle_service()
result = service.approve_application(member)
```

### Why Singletons

- Services are stateless or carry only configuration state
- Avoids repeated initialization overhead
- Consistent with Frappe's request-based lifecycle (module-level globals persist within a worker process)
- Lazy initialization -- service is only created when first used

## Service Base Classes

The `services/infrastructure/base_service.py` module provides four base classes. Choose based on your service's needs:

### StatelessService

For pure calculations, transformations, and logic with no database interaction:

```python
from verenigingen.services.infrastructure.base_service import StatelessService

class FeeCalculationService(StatelessService):
    def __init__(self):
        super().__init__("fee_calculation")

    def calculate_fee(self, member_type: str, base_fee: float) -> dict:
        discount = self._get_discount(member_type)
        return self.create_result(
            success=True,
            data={"final_fee": base_fee * (1 - discount)}
        )

    def _get_discount(self, member_type: str) -> float:
        return {"Student": 0.5, "Senior": 0.3}.get(member_type, 0.0)
```

### DataService

For services that query the database. Provides `safe_query()` with automatic field validation:

```python
from verenigingen.services.infrastructure.base_service import DataService

class MemberDataService(DataService):
    def __init__(self):
        super().__init__("member_data")

    def search_active_members(self, term: str, limit: int = 10) -> dict:
        members = self.safe_query(
            doctype="Member",
            fields=["name", "full_name", "email", "status"],
            filters={"status": "Active", "full_name": ["like", f"%{term}%"]},
            limit=limit
        )
        return self.create_result(success=True, data={"members": members})
```

### APIService

For services that call external APIs (Mollie, eBoekhouden, etc.):

```python
from verenigingen.services.infrastructure.base_service import APIService

class NotificationService(APIService):
    def __init__(self):
        super().__init__("notification")

    def send_welcome_email(self, member_name: str) -> dict:
        member = frappe.get_doc("Member", member_name)
        # ... email sending logic ...
        return self.create_result(success=True, data={"email_sent": True})
```

### StatefulService

For services that maintain state across operations. Provides `execute_with_transaction()` for explicit transaction management:

```python
from verenigingen.services.infrastructure.base_service import StatefulService

class BatchProcessingService(StatefulService):
    def __init__(self):
        super().__init__("batch_processing")
        self.batch_size = 100
```

## Service Factory

For services registered with the factory (primarily infrastructure services):

```python
from verenigingen.services.infrastructure.service_factory import get_service_factory

factory = get_service_factory()

# Register a service
factory.register_service(
    name="member_data",
    service_class=MemberDataService,
    config={"debug_mode": frappe.conf.developer_mode},
    singleton=True
)

# Get a registered service
service = factory.get_service("member_data")
result = service.search_active_members("John")
```

Most domain services (member lifecycle, approval, etc.) use the simple singleton pattern rather than the factory. The factory is mainly used by infrastructure and monitoring services.

## Error Handling in Services

Services use three return patterns (see `docs/development/ERROR_HANDLING_CONVENTIONS.md` for full details):

### New Code: OperationResult

```python
from verenigingen.utils.operation_result import OperationResult

class MemberLifecycleService:
    def approve(self, member: Document) -> OperationResult[Document]:
        if member.status != "Pending":
            return OperationResult.fail("Not pending", current_status=member.status)
        member.status = "Active"
        member.save()
        return OperationResult.ok(member, approved=True)
```

### Infrastructure Services: create_result()

Infrastructure base classes provide `self.create_result()`, which calls `create_service_result()`:

```python
class MyDataService(DataService):
    def get_stats(self) -> dict:
        return self.create_result(
            success=True,
            data={"total": 100, "active": 80}
        )
```

### Existing Code: Plain Dicts

Some older services return plain `{"success": bool, ...}` dicts. These are stable and do not need migration.

## Transaction Handling

Frappe uses implicit per-request transactions. See `CLAUDE.md` for the five documented transaction patterns:

1. **Explicit commit after `db_set()`** -- when bypassing document hooks
2. **Begin without commit** -- in document hook context
3. **Full transaction with early returns** -- each exit path commits
4. **Commit after multi-step operations** -- atomic multi-op
5. **FOR UPDATE locks** -- race condition prevention

Key rules:
- **Do not add `frappe.db.commit()` in hook-context code** (validate, before_save)
- **Use `frappe.database.savepoint()`** for nested operations
- **Document why commits are placed** in comments

## Creating a New Service

### 1. Choose the Right Base Class

| Need | Base Class |
|------|-----------|
| Pure logic, no DB | `StatelessService` |
| Database queries | `DataService` |
| External API calls | `APIService` |
| Stateful operations | `StatefulService` |
| Simple domain service | No base class needed -- just a plain class with singleton getter |

### 2. Create the Module

Place in the appropriate domain subdirectory:

```python
# services/member/validation/address_validation_service.py

from typing import Dict, Any
from verenigingen.utils.operation_result import OperationResult

class AddressValidationService:
    """Validates member addresses against postal code registry."""

    def validate_address(self, postal_code: str, house_number: str) -> OperationResult[dict]:
        if not postal_code or len(postal_code) != 6:
            return OperationResult.fail("Invalid postal code format")
        # ... validation logic ...
        return OperationResult.ok({"valid": True, "normalized": normalized_address})

# Singleton accessor
_service_instance = None

def get_address_validation_service() -> AddressValidationService:
    global _service_instance
    if _service_instance is None:
        _service_instance = AddressValidationService()
    return _service_instance
```

### 3. Use from Other Code

```python
from verenigingen.services.member.validation.address_validation_service import (
    get_address_validation_service,
)

result = get_address_validation_service().validate_address("1234AB", "42")
if result.success:
    print(result.data["normalized"])
```

## Testing Services

```python
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

class TestAddressValidationService(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = get_address_validation_service()

    def test_valid_postal_code(self):
        result = self.service.validate_address("1234AB", "42")
        self.assertTrue(result.success)

    def test_invalid_postal_code(self):
        result = self.service.validate_address("123", "42")
        self.assertFalse(result.success)
        self.assertIn("Invalid", result.error_message)
```

## Reference Implementations

These existing services demonstrate recommended patterns:

| Service | Path | Pattern |
|---------|------|---------|
| User account creation | `services/member/account/member_user_account_service.py` | Singleton, explicit commits |
| Multi-step approval | `services/member/approval/membership_creation_service.py` | OperationResult, orchestration |
| External integration | `e_boekhouden/services/account_migration_service.py` | API service, error recovery |
| History tracking | `utils/base_history_manager.py` | BaseHistoryManager callback pattern |
| Race condition safety | `services/termination/termination_execution_service.py` | FOR UPDATE locks |
| Member merge | `services/member_merge_service.py` | Multi-step with single commit |

## Health Monitoring

```python
from verenigingen.services.infrastructure.service_integration import get_integration_manager

manager = get_integration_manager()
health = manager.get_service_health_summary()
# {"overall_health": 0.95, "healthy_services": 19, "total_services": 20, ...}
```

## Related Documentation

- `docs/development/ERROR_HANDLING_CONVENTIONS.md` -- Return patterns (OperationResult, dicts)
- `docs/development/TYPING_CONVENTIONS.md` -- Type hint conventions
- `CLAUDE.md` -- Transaction handling patterns, coding standards
