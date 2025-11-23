# Type Hint Conventions for Verenigingen

This document outlines the typing conventions and best practices for the Verenigingen codebase.

## Overview

We use Python type hints to improve code quality, enable static type checking, and enhance IDE support. Type hints are optional at runtime but provide significant development benefits.

## Benefits of Type Hints

1. **IDE Support**: Better autocomplete and inline documentation
2. **Early Error Detection**: Catch type errors before runtime with mypy
3. **Refactoring Safety**: Safer refactoring with type checking
4. **Living Documentation**: Types serve as self-documenting code
5. **Developer Experience**: Faster onboarding with clearer interfaces

## Getting Started

### Running Type Checks

```bash
# Check a specific file
python -m mypy verenigingen/verenigingen/doctype/member/member.py --config-file=mypy.ini

# Check the entire codebase (services)
python -m mypy verenigingen/services --config-file=mypy.ini

# Check with explicit package bases (recommended for Frappe apps)
python -m mypy verenigingen --config-file=mypy.ini --explicit-package-bases
```

### Configuration

Type checking is configured in `mypy.ini` at the project root with:
- Gradual typing approach (permissive initially, stricter for new code)
- Service layer enforces strict typing
- Controllers use gradual typing
- Frappe framework stubs included

## General Rules

### 1. All New Functions Must Have Type Hints

```python
# ❌ Bad - No type hints
def create_member(data):
    return frappe.get_doc({"doctype": "Member", **data})

# ✅ Good - Full type hints
def create_member(data: Dict[str, Any]) -> Document:
    return frappe.get_doc({"doctype": "Member", **data})
```

### 2. Return Types Are Mandatory

```python
# ❌ Bad - Missing return type
def get_member_name(member):
    return member.full_name

# ✅ Good - Explicit return type
def get_member_name(member: "Member") -> str:
    return member.full_name
```

### 3. Parameter Types Are Mandatory

```python
# ❌ Bad - No parameter types
def update_address(member_name, new_address):
    pass

# ✅ Good - All parameters typed
def update_address(member_name: str, new_address: str) -> None:
    pass
```

### 4. Use Optional for Nullable Values

```python
# ❌ Bad - Implicit None
def get_volunteer(member_name: str) -> Document:
    return frappe.db.get_value("Volunteer", {"member": member_name})  # Can return None!

# ✅ Good - Explicit Optional
def get_volunteer(member_name: str) -> Optional[Document]:
    return frappe.db.get_value("Volunteer", {"member": member_name})
```

## Common Type Patterns

### Document Types

```python
from frappe.model.document import Document
from verenigingen.custom_types import MemberDict, VolunteerDict

# Using Document base class
def process_member(member: Document) -> bool:
    return member.status == "Active"

# Using forward reference for same-file class
def update_member(self, member: "Member") -> None:
    member.save()

# Using TypedDict for dictionaries
def create_member_dict(name: str, email: str) -> MemberDict:
    return {
        "name": name,
        "doctype": "Member",
        "email": email,
        "first_name": "",
        "last_name": "",
        # ... other required fields
    }
```

### Lifecycle Hooks

All document lifecycle hooks should return `None`:

```python
class Member(Document):
    def validate(self) -> None:
        """Validate member data"""
        self.validate_birth_date()

    def before_save(self) -> None:
        """Execute before saving"""
        self.update_full_name()

    def after_insert(self) -> None:
        """Execute after inserting"""
        self.create_customer()

    def on_submit(self) -> None:
        """Execute on submit"""
        self.create_dues_schedule()
```

### API Methods

API methods decorated with `@frappe.whitelist()` should have clear return types:

```python
@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_member_details(member_name: str) -> Dict[str, Any]:
    """Get member details.

    Args:
        member_name: Name of the member

    Returns:
        Dictionary with member details
    """
    member = frappe.get_doc("Member", member_name)
    return {
        "name": member.name,
        "email": member.email,
        "status": member.status,
    }
```

### Lists and Dictionaries

```python
from typing import List, Dict, Any

# List of strings
def get_member_names() -> List[str]:
    return frappe.db.get_all("Member", pluck="name")

# List of dictionaries
def get_member_list() -> List[Dict[str, Any]]:
    return frappe.db.get_all("Member", fields=["name", "email"])

# Dictionary with specific value types
def get_member_status_counts() -> Dict[str, int]:
    return {"active": 10, "inactive": 5}
```

### Using TypedDict

For complex dictionary structures, use TypedDict from `custom_types.py`:

```python
from verenigingen.custom_types import MemberDict, DuesScheduleDict

def create_schedule(member: str, amount: float) -> DuesScheduleDict:
    """Create dues schedule dictionary.

    Args:
        member: Member name
        amount: Dues amount

    Returns:
        DuesScheduleDict with schedule data
    """
    return {
        "name": "",
        "doctype": "Membership Dues Schedule",
        "member": member,
        "amount": amount,
        "billing_frequency": "Monthly",
        "status": "Active",
        "auto_process": True,
        # Standard Frappe fields
        "owner": frappe.session.user,
        "creation": frappe.utils.now_datetime(),
        "modified": frappe.utils.now_datetime(),
        "modified_by": frappe.session.user,
        "docstatus": 0,
    }
```

## Available Type Aliases

The `verenigingen/custom_types.py` module provides common type aliases:

```python
from verenigingen.custom_types import (
    MemberDict,
    VolunteerDict,
    ChapterDict,
    MembershipDict,
    DuesScheduleDict,
    SalesInvoiceDict,
    PaymentEntryDict,
    MemberStatus,
    PaymentMethod,
    MembershipType,
)

# Use in function signatures
def get_active_members() -> List[MemberDict]:
    pass

def update_status(member: MemberDict, status: MemberStatus) -> None:
    pass
```

## Frappe Framework Stubs

Basic Frappe type stubs are available in `frappe-stubs/`:

```python
import frappe
from frappe import Document

# These now have type hints:
doc: Document = frappe.get_doc("Member", "MEM-001")
values: List[Dict[str, Any]] = frappe.db.get_all("Member", fields=["name"])
exists: Optional[str] = frappe.db.exists("Member", "MEM-001")
```

## Handling Forward References

When referencing a class that's defined in the same file:

```python
class Member(Document):
    def update_from_other(self, other: "Member") -> None:
        """Update this member from another member.

        Note: Use string literal "Member" for forward reference.
        """
        self.email = other.email
```

## Dealing with `Any`

Use `Any` sparingly and only when truly necessary:

```python
from typing import Any

# ✅ Acceptable - Truly dynamic data
def process_dynamic_data(data: Any) -> None:
    pass

# ❌ Avoid - Can be more specific
def get_member_field(field_name: Any) -> Any:
    pass

# ✅ Better
def get_member_field(field_name: str) -> Optional[str]:
    pass
```

## mypy Configuration

Our `mypy.ini` configures different strictness levels:

### Service Layer (Strict)
```ini
[mypy-verenigingen.services.*]
disallow_untyped_defs = True
check_untyped_defs = True
warn_return_any = True
```

### Controllers (Gradual)
```ini
[mypy-verenigingen.verenigingen.doctype.member.member]
disallow_untyped_defs = False
check_untyped_defs = True
```

## Common mypy Errors

### Missing Return Type
```python
# Error: Function is missing a return type annotation
def get_data(self):
    return []

# Fix: Add return type
def get_data(self) -> List[Any]:
    return []
```

### Implicit Optional
```python
# Error: Incompatible default for argument
def create_member(name: str, email: str = None):
    pass

# Fix: Use Optional
def create_member(name: str, email: Optional[str] = None):
    pass
```

### Returning Any
```python
# Error: Returning Any from function declared to return str
def get_name() -> str:
    return frappe.db.get_value("Member", "MEM-001", "name")  # Returns Any

# Fix: Cast or assert type
def get_name() -> str:
    result = frappe.db.get_value("Member", "MEM-001", "name")
    return str(result) if result else ""
```

## Best Practices

1. **Start with return types** - They provide the most immediate value
2. **Use TypedDict for complex structures** - Better than Dict[str, Any]
3. **Leverage IDE autocomplete** - Type hints enable better tooling
4. **Run mypy regularly** - Catch errors early in development
5. **Don't over-type** - Use `Any` when truly dynamic
6. **Document complex types** - Add docstring explanations
7. **Use forward references** - Avoid circular imports with string literals

## Migration Strategy

### For New Code
- All new functions must have complete type hints
- All new files must pass mypy with strict settings

### For Existing Code
- Add type hints incrementally
- Focus on public APIs first
- Add hints when refactoring existing code
- Don't force-add hints to stable, working code

## Resources

- [Python Type Hints Documentation](https://docs.python.org/3/library/typing.html)
- [mypy Documentation](https://mypy.readthedocs.io/)
- [PEP 484 - Type Hints](https://www.python.org/dev/peps/pep-0484/)
- [TypedDict PEP 589](https://www.python.org/dev/peps/pep-0589/)

## Examples by DocType

### Member Controller

```python
from typing import Optional, Dict, Any
from verenigingen.custom_types import MemberDict

class Member(Document):
    # Lifecycle hooks
    def validate(self) -> None:
        pass

    def before_save(self) -> None:
        pass

    # Helper methods
    def is_application_member(self) -> bool:
        return bool(self.application_id)

    # API methods
    @frappe.whitelist()
    def create_customer(self) -> str:
        return create_customer_for_member(self)

    @frappe.whitelist()
    def approve_application(self) -> bool:
        return member_lifecycle_service.approve_application(self)
```

### Service Layer

```python
from typing import Dict, Any, Optional, List
from verenigingen.custom_types import MemberDict

class MemberLifecycleService:
    """Service for member lifecycle operations."""

    def approve_application(self, member: Document) -> Dict[str, Any]:
        """Approve member application.

        Args:
            member: Member document to approve

        Returns:
            Dict with success status and data
        """
        try:
            # Business logic
            return {
                "success": True,
                "data": {"member": member.name}
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
```

## Conclusion

Type hints are a powerful tool for improving code quality and developer experience. Follow these conventions to maintain a consistent, type-safe codebase.

For questions or clarification, consult the team or refer to the Python typing documentation.
