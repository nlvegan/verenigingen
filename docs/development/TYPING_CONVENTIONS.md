# Typing and Code Style Conventions

This document covers Python type hints, code formatting configuration, and style conventions for the Verenigingen codebase.

## Code Formatting Configuration

### Black (Formatter)

Configured in `pyproject.toml` under `[tool.black]`:

```
Line length:      110
Target versions:  py310, py311
```

```bash
# Check formatting
black --check .

# Auto-format
black .
```

### Ruff (Linter -- replaces flake8 + isort)

Configured in `pyproject.toml` under `[tool.ruff]`:

```
Line length:      110
Target version:   py310
Rules enabled:    E, W (pycodestyle), F (pyflakes), I (isort)
```

Key ignored rules:
- `E501` -- Line too long (handled by Black)
- `E722` -- Bare except (sometimes intentional)
- `F401` -- Unused import (too noisy during development)
- `F821` -- Undefined name (Frappe framework magic like `frappe._`)

```bash
# Check
ruff check .

# Auto-fix
ruff check --fix .
```

### isort (Import Sorting -- via Ruff)

Configured in `pyproject.toml` under `[tool.isort]` and `[tool.ruff.lint.isort]`:

```
Profile:          black
Line length:      110
Known first-party: verenigingen
```

Ruff handles import sorting via its `I` rules, so a separate `isort` invocation is not needed.

### Pylint (Deep Analysis -- pre-push only)

```
Fail threshold:   7.0
Runs at:          pre-push stage only
```

### Summary

| Tool | Purpose | Line Length | When |
|------|---------|------------|------|
| Black | Formatting | 110 | Pre-commit |
| Ruff | Linting + imports | 110 | Pre-commit |
| Pylint | Deep analysis | N/A | Pre-push |
| ESLint | JavaScript linting | N/A | Pre-commit |

## Python Version

**Minimum: Python 3.10** (configured in `pyproject.toml` as `requires-python = ">=3.10"`).

Supported versions: 3.10, 3.11, 3.12.

Use Python 3.10+ syntax:
- `X | Y` union syntax (PEP 604) -- allowed but `Optional[X]` and `Union[X, Y]` from `typing` are also fine
- `match` statements (PEP 634) -- use where appropriate
- `ParamSpec` and `TypeVarTuple` (PEP 612, 646) -- available if needed

## Type Hint Conventions

### General Rules

1. **All new functions must have type hints** (parameters and return type)
2. **Return types are mandatory**
3. **Use `Optional` for nullable values**
4. **Use `Any` sparingly** -- only when truly dynamic

```python
# All parameters and return typed
def create_member(data: Dict[str, Any]) -> Document:
    return frappe.get_doc({"doctype": "Member", **data})

# Optional for nullable returns
def get_volunteer(member_name: str) -> Optional[Document]:
    return frappe.db.get_value("Volunteer", {"member": member_name})

# Avoid implicit None
def find_member(email: str, status: Optional[str] = None) -> Optional[Document]:
    filters = {"email": email}
    if status:
        filters["status"] = status
    return frappe.db.get_value("Member", filters)
```

### Document Lifecycle Hooks

All hooks return `None`:

```python
class Member(Document):
    def validate(self) -> None:
        self.validate_birth_date()

    def before_save(self) -> None:
        self.update_full_name()

    def after_insert(self) -> None:
        self.create_customer()

    def on_submit(self) -> None:
        self.create_dues_schedule()
```

### API Methods

```python
@frappe.whitelist()
def get_member_details(member_name: str) -> Dict[str, Any]:
    """Get member details.

    Args:
        member_name: Name of the member

    Returns:
        Dictionary with member details
    """
    member = frappe.get_doc("Member", member_name)
    return {"name": member.name, "email": member.email, "status": member.status}
```

### Service Methods

Service methods should use `OperationResult` with a type parameter:

```python
from verenigingen.utils.operation_result import OperationResult

class MemberLifecycleService:
    def approve_application(self, member: Document) -> OperationResult[Document]:
        ...
```

### Common Type Patterns

```python
from typing import Dict, Any, List, Optional, Tuple

# List of strings
def get_member_names() -> List[str]:
    return frappe.db.get_all("Member", pluck="name")

# List of dicts
def get_member_list() -> List[Dict[str, Any]]:
    return frappe.db.get_all("Member", fields=["name", "email"])

# Dict with specific value types
def get_status_counts() -> Dict[str, int]:
    return {"active": 10, "inactive": 5}

# Tuple returns
def get_name_and_email(member_name: str) -> Tuple[str, str]:
    doc = frappe.get_doc("Member", member_name)
    return doc.full_name, doc.email
```

### Forward References

Use string literals when referencing a class defined in the same file:

```python
class Member(Document):
    def update_from_other(self, other: "Member") -> None:
        self.email = other.email
```

### TypedDict for Complex Structures

For well-known dict shapes, use TypedDict from `vereinigingen/custom_types.py`:

```python
from verenigingen.custom_types import MemberDict, VolunteerDict, ChapterDict

def get_active_members() -> List[MemberDict]:
    ...
```

Available type aliases in `custom_types.py`:
- `MemberDict`, `VolunteerDict`, `ChapterDict`, `MembershipDict`
- `DuesScheduleDict`, `SalesInvoiceDict`, `PaymentEntryDict`
- `MemberStatus`, `PaymentMethod`, `MembershipType`

## mypy Configuration

Type checking is configured in `mypy.ini` with different strictness levels:

### Service Layer (Strict)

```ini
[mypy-vereinigingen.services.*]
disallow_untyped_defs = True
check_untyped_defs = True
warn_return_any = True
```

### Controllers (Gradual)

```ini
[mypy-vereinigingen.vereinigingen.doctype.member.member]
disallow_untyped_defs = False
check_untyped_defs = True
```

### Running mypy

```bash
# Check a specific file
python -m mypy vereinigingen/services/member/core/member_lifecycle_service.py --config-file=mypy.ini

# Check the services layer
python -m mypy vereinigingen/services --config-file=mypy.ini

# Check with explicit package bases (recommended for Frappe apps)
python -m mypy vereinigingen --config-file=mypy.ini --explicit-package-bases
```

### Common mypy Fixes

```python
# Missing return type
# Error: Function is missing a return type annotation
def get_data(self) -> List[Any]:  # Add return type
    return []

# Implicit Optional
# Error: Incompatible default for argument
def create(name: str, email: Optional[str] = None):  # Use Optional
    pass

# Returning Any
# Error: Returning Any from function declared to return str
def get_name() -> str:
    result = frappe.db.get_value("Member", "MEM-001", "name")
    return str(result) if result else ""  # Cast explicitly
```

## Translation Strings

- **Python:** Wrap user-facing strings in `_()`
- **JavaScript:** Wrap user-facing strings in `__()`

```python
frappe.throw(_("Birth date is required"))
```

```javascript
frappe.msgprint(__("Member approved successfully"));
```

## SQL Formatting

Multi-line queries should indent consistently:

```sql
SELECT
    item_name, description, default_warehouse
FROM
    tabItem
WHERE
    disabled = 0
```

Always use parameterized queries:

```python
# GOOD
frappe.db.sql("SELECT name FROM tabMember WHERE status = %s", [status])

# BAD (SQL injection risk)
frappe.db.sql(f"SELECT name FROM tabMember WHERE status = '{status}'")
```

## Comments

- Explain **why** implementation choices were made, not just **what** the code does
- Do not over-comment obvious code
- Document non-obvious business rules and edge cases

## Migration Strategy

### For New Code

- All new functions must have complete type hints
- All new files must pass mypy with strict settings

### For Existing Code

- Add type hints incrementally when editing files
- Focus on public APIs first
- Add hints when refactoring existing code
- Do not force-add hints to stable, working code

## Resources

- [Python Type Hints Documentation](https://docs.python.org/3/library/typing.html)
- [mypy Documentation](https://mypy.readthedocs.io/)
- [Black Documentation](https://black.readthedocs.io/)
- [Ruff Documentation](https://docs.astral.sh/ruff/)
- `vereinigingen/custom_types.py` -- Project-specific type aliases
- `docs/development/ERROR_HANDLING_CONVENTIONS.md` -- OperationResult typing
