# Developer Quick Start Guide

Fast-track guide for developers to set up, understand, and contribute to the Verenigingen codebase.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Setup](#quick-setup)
- [Development Environment](#development-environment)
- [Codebase Overview](#codebase-overview)
- [Service Layer](#service-layer)
- [Development Workflow](#development-workflow)
- [Code Formatting and Linting](#code-formatting-and-linting)
- [Pre-commit Hooks](#pre-commit-hooks)
- [Testing](#testing)
- [Key Concepts](#key-concepts)
- [Contributing](#contributing)
- [Getting Help](#getting-help)

## Prerequisites

### Required Knowledge

- **Python 3.10+**: Object-oriented programming and web frameworks
- **JavaScript ES6+**: Modern frontend development
- **Database**: SQL, MariaDB/MySQL experience
- **Web Technologies**: HTML5, CSS3, REST APIs
- **Version Control**: Git workflows and branching strategies

### Required Tools

```bash
python3.10+         # Python runtime (3.10, 3.11, or 3.12)
node.js 16+         # JavaScript runtime
git                 # Version control
mysql/mariadb       # Database server
redis               # Caching and queues
supervisor          # Process management
```

### Recommended Background

- **Frappe Framework**: [Official Documentation](https://frappeframework.com/docs)
- **ERPNext**: Basic understanding of ERP concepts
- **Dutch Business**: Understanding of Dutch non-profit and business practices

## Quick Setup

### 30-Minute Development Setup

```bash
# 1. Install Frappe Bench (if not installed)
sudo apt-get update
sudo apt-get install -y python3-dev python3-pip redis-server mariadb-server

# Install bench
pip3 install frappe-bench

# 2. Create development environment
bench init --frappe-branch version-15 verenigingen-dev
cd verenigingen-dev

# 3. Create development site
bench new-site dev.verenigingen.local
bench use dev.verenigingen.local

# 4. Install required apps
bench get-app erpnext --branch version-15
bench get-app payments
bench get-app hrms

# 5. Install Verenigingen
bench get-app https://github.com/0spinboson/verenigingen
bench install-app verenigingen

# 6. Setup development tools
bench setup requirements --dev
bench setup socketio
bench setup supervisor
bench setup nginx

# 7. Enable developer mode
bench --site dev.verenigingen.local set-config developer_mode 1
bench --site dev.verenigingen.local clear-cache

# 8. Start development server
bench start
```

### Access Your Development Environment

- **Site**: http://dev.verenigingen.local:8000
- **Admin Login**: Administrator / (password set during setup)

### Daily Development Commands

```bash
bench start                                          # Start with hot reload
bench build --app verenigingen                       # Build assets
bench --site dev.verenigingen.local migrate          # Run migrations
bench --site dev.verenigingen.local clear-cache      # Clear cache
bench restart                                        # Restart services
```

## Development Environment

### IDE Configuration (VS Code)

```json
// .vscode/settings.json
{
  "python.defaultInterpreter": "./env/bin/python",
  "python.linting.enabled": true,
  "python.formatting.provider": "black",
  "[python]": {
    "editor.formatOnSave": true,
    "editor.defaultFormatter": "ms-python.black-formatter"
  },
  "editor.rulers": [110],
  "files.associations": {
    "*.py": "python",
    "*.js": "javascript",
    "*.html": "html"
  }
}
```

Recommended extensions:

```bash
code --install-extension ms-python.python
code --install-extension ms-python.black-formatter
code --install-extension charliermarsh.ruff
code --install-extension esbenp.prettier-vscode
code --install-extension bradlc.vscode-tailwindcss
```

### Debugging

```python
# Add to any Python file for debugging
import frappe
frappe.logger().debug("Debug message here")

# Use IPython for interactive debugging
import IPython; IPython.embed()

# Check logs
tail -f ~/frappe-bench/logs/worker.error.log
```

## Codebase Overview

### Directory Structure

```
verenigingen/
├── verenigingen/                # Main app package
│   ├── api/                    # REST API endpoints (@frappe.whitelist)
│   ├── commands/               # CLI commands (bench commands)
│   ├── config/                 # App configuration
│   ├── constants/              # Constants and enums
│   ├── e_boekhouden/           # eBoekhouden accounting integration
│   ├── email/                  # Email templates and logic
│   ├── events/                 # Document event handlers (hooks)
│   ├── fixtures/               # Initial data and configuration
│   ├── hooks/                  # Frappe hook implementations
│   ├── integrations/           # External integrations
│   ├── mijnrood_sync/          # MijnRood external DB sync
│   ├── monitoring/             # Health checks, dashboards
│   ├── overrides/              # ERPNext/Frappe overrides
│   ├── pages/                  # Custom desk pages
│   ├── patches/                # Database migration patches
│   ├── payments/               # Payment processing (Mollie, SEPA)
│   ├── public/                 # Static assets (CSS, JS, images)
│   ├── reports/                # Custom reports
│   ├── repositories/           # Data access layer
│   ├── schemas/                # Validation schemas
│   ├── services/               # Business logic service layer
│   ├── setup/                  # App installation setup
│   ├── tasks/                  # Scheduled background tasks
│   ├── templates/              # HTML/Jinja2 templates and portal pages
│   ├── tests/                  # Test suites (domain-organized)
│   ├── translations/           # i18n translation files
│   └── utils/                  # Shared utility functions
├── docs/                       # Developer and user documentation
├── scripts/                    # Dev/deployment/validation scripts
│   ├── security/               # Security scanning scripts
│   ├── testing/                # Test runner scripts
│   └── validation/             # Pre-commit validator scripts
├── pyproject.toml              # Python config (Black, ruff, isort, deps)
├── .pre-commit-config.yaml     # Pre-commit hook definitions
├── package.json                # Node.js dependencies
├── tailwind.config.js          # Tailwind CSS configuration
└── pytest.ini                  # Test configuration
```

### Key Components

#### DocTypes (Business Objects)

```
Member                    # Member records and lifecycle
Membership                # Member subscriptions and billing
Volunteer                 # Volunteer profiles and assignments
Chapter                   # Geographic organization units
Direct Debit Batch        # SEPA payment processing
Membership Dues Schedule  # Recurring fee management
```

#### API Modules (`verenigingen/api/`)

```
membership_application.py        # Public-facing member applications
membership_application_review.py # Admin review/approval
payment_processing.py            # Payment and financial operations
sepa_batch_ui.py                 # SEPA direct debit management
volunteer_api.py                 # Volunteer coordination
```

## Service Layer

The service layer (`verenigingen/services/`) contains business logic organized by domain. See `docs/development/SERVICE_INFRASTRUCTURE_USAGE_GUIDE.md` for full details.

### Layout

```
services/
├── infrastructure/         # Base classes, factory, field validation
├── member/                 # Member domain (largest)
│   ├── account/            # User account creation
│   ├── application/        # Membership application processing
│   ├── approval/           # Membership approval/creation
│   ├── chapter/            # Chapter assignment
│   ├── core/               # Lifecycle, status management
│   ├── display/            # Member display/formatting
│   ├── donor/              # Donor operations
│   ├── financial/          # Financial operations
│   ├── history/            # History tracking managers
│   ├── identification/     # Member ID generation
│   ├── integration/        # External system integration
│   ├── lifecycle/          # Status notifications
│   ├── payment/            # Payment processing
│   ├── testing/            # Test helpers
│   ├── utils/              # Member-specific utilities
│   └── validation/         # Input validation
├── account/                # Account operations
├── approval/               # Approval workflows
├── billing/                # Billing and invoicing
├── chapter/                # Chapter management
├── communication/          # Email/notification services
├── csv_import/             # CSV/data import services
├── document/               # Document operations
├── donation/               # Donation processing
├── monitoring/             # Health monitoring
├── payment/                # Payment processing
├── termination/            # Membership termination
└── volunteer/              # Volunteer management
```

### Singleton Pattern

Most services use a module-level singleton with a getter function:

```python
_service_instance = None

def get_member_lifecycle_service() -> MemberLifecycleService:
    global _service_instance
    if _service_instance is None:
        _service_instance = MemberLifecycleService()
    return _service_instance
```

Usage:

```python
from verenigingen.services.member.core.member_lifecycle_service import (
    get_member_lifecycle_service,
)

service = get_member_lifecycle_service()
result = service.approve_application(member)
```

## Development Workflow

### Git Workflow

The main branch is `develop`. Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>[optional scope]: <description>
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

```bash
# Create feature branch
git checkout -b feat/new-feature develop

# Commit with conventional commit message
git commit -m "feat(member): add bulk status update endpoint"

# Push and create PR against develop
git push -u origin feat/new-feature
```

### Creating New Features

#### Adding a New DocType

```bash
# Via UI: Desk > DocType > New DocType (recommended)
# Or via bench:
bench --site dev.verenigingen.local make-doctype "New Doctype Name"

# After editing the generated files:
bench --site dev.verenigingen.local migrate
```

#### Adding a New API Endpoint

```python
# Create: verenigingen/api/my_new_api.py
import frappe

@frappe.whitelist()  # MUST be outermost decorator
def my_endpoint(param1: str, param2: str = "") -> dict:
    """Endpoint description."""
    # Business logic via service layer
    return {"success": True, "data": result}
```

**Critical**: `@frappe.whitelist()` must always be the outermost (first/top) decorator. See `CLAUDE.md` for the full explanation.

## Code Formatting and Linting

### Formatter: Black

```
Line length: 110
Target: Python 3.10, 3.11
```

Configured in `pyproject.toml` under `[tool.black]`.

```bash
# Check formatting
black --check .

# Auto-format
black .
```

### Linter: Ruff (replaces flake8 + isort)

```
Line length: 110
Target: Python 3.10
Rules: E, W (pycodestyle), F (pyflakes), I (isort)
```

Configured in `pyproject.toml` under `[tool.ruff]`.

```bash
# Check
ruff check .

# Auto-fix
ruff check --fix .
```

### Import Sorting: isort (via ruff)

isort is configured for Black compatibility (`profile = "black"`, line length 110). Ruff handles import sorting via its `I` rules, so a separate isort invocation is not needed.

### JavaScript: ESLint

```bash
npx eslint "**/*.js"
npx eslint --fix "**/*.js"
```

### Pylint (deep analysis, pre-push only)

Threshold: 7.0. Runs only on `pre-push` stage, not on every commit.

## Pre-commit Hooks

### Installation

```bash
cd ~/frappe-bench/apps/verenigingen
python -m pip install pre-commit
pre-commit install
```

### Hook Stages

| Stage | When | What Runs |
|-------|------|-----------|
| `pre-commit` | Every commit | Fast validators (~30 checks): Black, ruff, ESLint, Bandit security scan, field validators, template validators, import path validator, test quality enforcer |
| `pre-push` | Before pushing | Slower validators: Pylint (threshold 7.0), API security validator, JS-Python parameter validator, method resolution, runtime import check, Jest tests, coverage reports |
| `manual` | On demand | Comprehensive validation suites, performance validators |

### Running Hooks Manually

```bash
# All pre-commit stage checks
pre-commit run --all-files

# Specific validator
pre-commit run ruff --all-files
pre-commit run ast-field-analyzer --all-files

# Pre-push stage validators
pre-commit run --hook-stage pre-push --all-files

# Manual stage validators
pre-commit run comprehensive-validation --all-files
```

### Key Pre-commit Hooks

**Code Quality:**
- `black` -- Python formatting (line-length 110)
- `ruff` -- Python linting (10-100x faster than flake8)
- `eslint` -- JavaScript linting
- `pylint` -- Deep static analysis (pre-push, threshold 7.0)

**Security:**
- `bandit-focused` -- Fast security scan on critical files
- `whitelist-type-safety` -- Validates @whitelist parameter types (Frappe v15+)
- `api-security-validator` -- Checks API security decorators (pre-push)
- `insecure-api-detector` -- Finds unprotected API endpoints (pre-push)
- `permission-bypass-validator` -- Detects `ignore_permissions=True` without justification

**Field/DocType Validation:**
- `ast-field-analyzer` -- AST-based field reference validation
- `doctype-field-validator` -- DocType field attribute access validation
- `sql-field-validator` -- SQL query field validation
- `template-field-validator` -- HTML/JavaScript template field validation
- `javascript-doctype-validator` -- JS DocType field validation (pre-push)

**Test Quality:**
- `test-quality-enforcer` -- Blocks mock abuse, enforces real integration testing

**Other:**
- `import-path-validator` -- Validates Python import paths exist
- `child-table-creation-validator` -- Detects incorrect child table patterns
- `frappe-hooks-validator` -- Validates Frappe hooks and event handlers

### Known Hook Issues

- `whitelist-type-safety` has widespread pre-existing failures. Use `SKIP=whitelist-type-safety` when needed.
- `javascript-doctype-validator` has a broken import. Use `SKIP=javascript-doctype-validator` when pushing.
- Pre-push Jest hook has 3 pre-existing test failures. Use `SKIP=jest-testing` when pushing.
- `insecure-api-detector` false positive on `database_index_manager_phase5a.py`. Use `SKIP=insecure-api-detector` when pushing.

## Testing

```bash
# Run all tests for the app
cd ~/frappe-bench
bench --site veg11.veganisme.org run-tests --app verenigingen

# Run tests for a specific module
bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.member.test_member_lifecycle

# Run tests for a specific doctype
bench --site veg11.veganisme.org run-tests --doctype "Member"
```

See `docs/DEVELOPER_TESTING_GUIDE.md` for full testing documentation including directory structure, base classes, and factory methods.

## Key Concepts

### Frappe Document Lifecycle

```python
class Member(Document):
    def validate(self):
        """Called before save -- validate data"""
        pass

    def before_save(self):
        """Called before writing to DB"""
        pass

    def on_submit(self):
        """Called when document is submitted"""
        pass

    def on_cancel(self):
        """Called when document is cancelled"""
        pass
```

### Database Operations

```python
# Create
doc = frappe.new_doc("Member")
doc.update(data)
doc.insert()

# Read
doc = frappe.get_doc("Member", member_name)
docs = frappe.get_all("Member", filters={"status": "Active"})

# Update
doc.field = "new value"
doc.save()

# Delete
frappe.delete_doc("Member", member_name)
```

### API Patterns

```python
@frappe.whitelist()
def my_endpoint(param1: str, param2: str = "") -> dict:
    """Always validate permissions and inputs."""
    if not frappe.has_permission("Member", "read"):
        frappe.throw("Insufficient permissions")

    result = process_data(param1, param2)
    return {"success": True, "data": result}
```

### Frontend Patterns

```javascript
frappe.call({
  method: "verenigingen.api.my_api.my_endpoint",
  args: { param1: "value1", param2: "value2" },
  callback: function (response) {
    if (response.message.success) {
      console.log(response.message.data);
    } else {
      frappe.msgprint(response.message.error);
    }
  },
});
```

## Contributing

### Pre-Implementation Checklist

Before writing new code:

1. **Search for existing utilities** -- Check `services/`, `utils/` for similar functionality
2. **Find similar features** -- Study how comparable functionality is already implemented
3. **Check the service layer** -- Does a service already exist for this domain?
4. **Confirm conventions** -- Naming, error handling (see `docs/development/ERROR_HANDLING_CONVENTIONS.md`), transaction patterns (see `CLAUDE.md`)

### Guidelines

1. Read `CLAUDE.md` for detailed development guidelines
2. Follow code style: Black formatting (110 char), type hints, docstrings
3. Write tests: All new features require tests
4. `@frappe.whitelist()` must always be the outermost decorator
5. Business logic belongs in the service layer, not in API endpoints or controllers
6. Use `safe_child_table_update()` for child table writes

## Getting Help

### Debugging Resources

```bash
# View system logs
tail -f ~/frappe-bench/logs/worker.error.log

# Database console
bench --site veg11.veganisme.org mariadb

# Python console with Frappe context
bench --site veg11.veganisme.org console
```

### Related Documentation

- `CLAUDE.md` -- Comprehensive project instructions and conventions
- `docs/DEVELOPER_TESTING_GUIDE.md` -- Test framework and patterns
- `docs/development/ERROR_HANDLING_CONVENTIONS.md` -- Error handling patterns
- `docs/development/SERVICE_INFRASTRUCTURE_USAGE_GUIDE.md` -- Service layer guide
- `docs/development/TYPING_CONVENTIONS.md` -- Type hint conventions
- `docs/API_DOCUMENTATION.md` -- API reference
- [Frappe Framework Docs](https://frappeframework.com/docs)
- [ERPNext Documentation](https://docs.erpnext.com)
