# 🛠️ Developer Quick Start Guide

Fast-track guide for developers to set up, understand, and contribute to the Verenigingen codebase.

## 📋 Table of Contents

- [🎯 Prerequisites](#-prerequisites)
- [⚡ Quick Setup](#-quick-setup)
- [🏗️ Development Environment](#️-development-environment)
- [📁 Codebase Overview](#-codebase-overview)
- [🔧 Development Workflow](#-development-workflow)
- [🧪 Testing](#-testing)
- [📚 Key Concepts](#-key-concepts)
- [🚀 Contributing](#-contributing)
- [📞 Getting Help](#-getting-help)

## 🎯 Prerequisites

### ✅ Required Knowledge

- **Python 3.10+**: Object-oriented programming and web frameworks
- **JavaScript ES6+**: Modern frontend development
- **Database**: SQL, MariaDB/MySQL experience
- **Web Technologies**: HTML5, CSS3, REST APIs
- **Version Control**: Git workflows and branching strategies

### 🛠️ Required Tools

```bash
# Essential development tools
python3.10+         # Python runtime
node.js 16+          # JavaScript runtime
git                  # Version control
mysql/mariadb        # Database server
redis                # Caching and queues
supervisor           # Process management

# Recommended editors
# VS Code with Python, Frappe, and Vue extensions
# PyCharm Professional
# Vim/Neovim with appropriate plugins
```

### 📚 Recommended Background

- **Frappe Framework**: [Official Documentation](https://frappeframework.com/docs)
- **ERPNext**: Basic understanding of ERP concepts
- **Dutch Business**: Understanding of Dutch non-profit and business practices

## ⚡ Quick Setup

### 🚀 30-Minute Development Setup

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
bench get-app crm

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

### 🌐 Access Your Development Environment

- **Site**: http://dev.verenigingen.local:8000
- **Admin Login**: Administrator / (password set during setup)
- **Developer Tools**: http://dev.verenigingen.local:8000/app/website

### ⚡ Daily Development Commands

```bash
# Start development with hot reload
bench start

# Build assets after changes
bench build --app verenigingen

# Run migrations after code changes
bench --site dev.verenigingen.local migrate

# Clear cache after framework changes
bench --site dev.verenigingen.local clear-cache

# Restart after Python changes
bench restart
```

## 🏗️ Development Environment

### 🔧 IDE Configuration

#### VS Code Setup

```json
// .vscode/settings.json
{
  "python.defaultInterpreter": "./env/bin/python",
  "python.linting.enabled": true,
  "python.linting.pylintEnabled": true,
  "python.formatting.provider": "black",
  "editor.formatOnSave": true,
  "files.associations": {
    "*.py": "python",
    "*.js": "javascript",
    "*.html": "html",
    "*.css": "css"
  }
}
```

#### Recommended Extensions

```bash
# VS Code extensions for Verenigingen development
code --install-extension ms-python.python
code --install-extension esbenp.prettier-vscode
code --install-extension bradlc.vscode-tailwindcss
code --install-extension ms-vscode.vscode-json
```

### 🛠️ Pre-commit Hooks

```bash
# Install pre-commit hooks (already configured)
pre-commit install

# Test pre-commit hooks
pre-commit run --all-files
```

### 🐛 Debugging Setup

```python
# Add to any Python file for debugging
import frappe
frappe.logger().debug("Debug message here")

# Use IPython for interactive debugging
import IPython; IPython.embed()

# Check logs
tail -f ~/frappe-bench/logs/worker.error.log
```

## 📁 Codebase Overview

### 🏗️ Architecture Overview

```
verenigingen/
├── 📁 verenigingen/              # Main app package
│   ├── 📁 api/                   # REST API endpoints
│   ├── 📁 doctype/               # Business objects (Member, Volunteer, etc.)
│   ├── 📁 fixtures/              # Initial data and configuration
│   ├── 📁 public/                # Static assets (CSS, JS, images)
│   ├── 📁 templates/             # HTML templates and pages
│   ├── 📁 utils/                 # Utility functions and helpers
│   └── 📁 www/                   # Public web pages
├── 📁 docs/                      # Documentation
├── 📁 scripts/                   # Development and deployment scripts
└── 📁 tests/                     # Test suites
```

### 🔑 Key Components

#### 📊 Doctypes (Business Objects)

```python
# Core doctypes and their purposes
Member                 # Member records and lifecycle
Membership            # Member subscriptions and billing
Volunteer             # Volunteer profiles and assignments
Chapter               # Geographic organization
Direct_Debit_Batch    # SEPA payment processing
```

#### 🔌 API Modules

```python
# Key API modules
membership_application.py    # Member application processing
payment_processing.py       # Payment and financial operations
sepa_batch_ui.py           # SEPA direct debit management
volunteer_api.py           # Volunteer coordination
```

#### 🧰 Utilities

```python
# Important utility modules
utils/validation/          # Input validation and sanitization
utils/eboekhouden/        # eBoekhouden integration
utils/migration/          # Data migration tools
utils/performance/        # Performance optimization
```

### 📋 Configuration Files

```yaml
# Important configuration files
hooks.py                  # App configuration and event hooks
pyproject.toml           # Python package configuration
package.json             # Node.js dependencies
tailwind.config.js       # CSS framework configuration
```

## 🔧 Development Workflow

### 🌿 Git Workflow

```bash
# 1. Create feature branch
git checkout -b feature/new-feature-name

# 2. Make changes and commit
git add .
git commit -m "Add new feature: description"

# 3. Push and create pull request
git push origin feature/new-feature-name
# Create PR on GitHub

# 4. After review, merge to main
git checkout main
git pull origin main
git branch -d feature/new-feature-name
```

### 🔄 Development Cycle

```bash
# Daily development workflow
# 1. Start development environment
bench start

# 2. Make code changes
# 3. Test changes
bench --site dev.verenigingen.local execute verenigingen.tests.utils.quick_validation.run_quick_tests

# 4. Build assets if needed
bench build --app verenigingen

# 5. Commit changes
git add . && git commit -m "Description of changes"
```

### 📦 Creating New Features

#### 🆕 Adding New Doctype

```bash
# Create new doctype
bench --site dev.verenigingen.local make-doctype "New Doctype Name"

# Edit the generated files:
# - verenigingen/doctype/new_doctype_name/new_doctype_name.json
# - verenigingen/doctype/new_doctype_name/new_doctype_name.py

# Add to hooks.py if needed
# Migrate
bench --site dev.verenigingen.local migrate
```

#### 🔌 Adding New API Endpoint

```python
# Create new file: verenigingen/api/my_new_api.py
import frappe

@frappe.whitelist()
def my_new_endpoint(param1, param2):
    """API endpoint description"""
    # Validate inputs
    # Process logic
    # Return response
    return {"success": True, "data": result}
```

#### 🎨 Adding New Portal Page

```python
# Create page files:
# verenigingen/templates/pages/my_page.html
# verenigingen/templates/pages/my_page.py

def get_context(context):
    context.title = "My Page"
    context.data = get_page_data()
    return context
```

## 🧪 Testing

### ⚡ Quick Testing

```bash
# Run all quick tests
bench --site dev.verenigingen.local execute verenigingen.tests.utils.quick_validation.run_quick_tests

# Run specific test module
bench --site dev.verenigingen.local run-tests --app verenigingen --module verenigingen.tests.backend.validation.test_iban_validator

# Run comprehensive tests
python scripts/testing/runners/regression_test_runner.py
```

### 🧪 Test Categories

```bash
# Business logic tests
bench --site dev.verenigingen.local run-tests --app verenigingen --module verenigingen.tests.backend.business_logic

# Security tests
bench --site dev.verenigingen.local run-tests --app verenigingen --module verenigingen.tests.backend.security

# Integration tests
bench --site dev.verenigingen.local run-tests --app verenigingen --module verenigingen.tests.backend.integration

# Performance tests
python verenigingen/tests/backend/performance/test_api_optimization_comprehensive.py
```

### ✏️ Writing Tests

```python
# Example test file: test_my_feature.py
import frappe
import unittest

class TestMyFeature(unittest.TestCase):
    def setUp(self):
        """Set up test data"""
        pass

    def test_my_functionality(self):
        """Test description"""
        # Arrange
        test_data = {"field": "value"}

        # Act
        result = my_function(test_data)

        # Assert
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("data"), expected_value)

    def tearDown(self):
        """Clean up test data"""
        pass
```

## 📚 Key Concepts

### 🏗️ Frappe Framework Patterns

```python
# Document lifecycle
class Member(Document):
    def validate(self):
        """Called before save"""
        pass

    def on_submit(self):
        """Called when document is submitted"""
        pass

    def on_cancel(self):
        """Called when document is cancelled"""
        pass

# Database operations
# Create
doc = frappe.new_doc("Member")
doc.update(data)
doc.insert()

# Read
doc = frappe.get_doc("Member", member_name)
docs = frappe.get_all("Member", filters={"status": "Active"})

# Update
doc.update(new_data)
doc.save()

# Delete
frappe.delete_doc("Member", member_name)
```

### 🔌 API Patterns

```python
# Standard API endpoint
@frappe.whitelist()
def my_api_endpoint(param1, param2=None):
    """API endpoint with validation and error handling"""
    try:
        # Validate permissions
        if not frappe.has_permission("Member", "read"):
            frappe.throw("Insufficient permissions")

        # Validate inputs
        if not param1:
            frappe.throw("param1 is required")

        # Process request
        result = process_data(param1, param2)

        # Return response
        return {"success": True, "data": result}

    except Exception as e:
        frappe.log_error(f"API Error: {str(e)}")
        return {"success": False, "error": str(e)}
```

### 🎨 Frontend Patterns

```javascript
// Frappe frontend patterns
// Call API from JavaScript
frappe.call({
  method: "verenigingen.api.my_api.my_endpoint",
  args: {
    param1: "value1",
    param2: "value2",
  },
  callback: function (response) {
    if (response.message.success) {
      // Handle success
      console.log(response.message.data);
    } else {
      // Handle error
      frappe.msgprint(response.message.error);
    }
  },
});
```

## 🚀 Contributing

### 📋 Contribution Guidelines

1. **Read [CLAUDE.md](../CLAUDE.md)** for detailed development guidelines
2. **Follow code style**: Black formatting, type hints, docstrings
3. **Write tests**: All new features require tests
4. **Update docs**: Include documentation updates with features
5. **Security first**: Review [SECURITY.md](../SECURITY.md) requirements

### 🐛 Bug Reports

```markdown
# Bug report template

## Environment

- Verenigingen version:
- ERPNext version:
- Browser/OS:

## Steps to Reproduce

1.
2.
3.

## Expected vs Actual Behavior

**Expected**:
**Actual**:

## Additional Context

(screenshots, logs, etc.)
```

### ✨ Feature Requests

```markdown
# Feature request template

## Problem Statement

Describe the problem this feature would solve

## Proposed Solution

Describe your proposed solution

## Alternatives Considered

Other approaches you've considered

## Additional Context

Use cases, mockups, examples
```

## 📞 Getting Help

### 🆘 Support Channels

1. **Documentation**: Start with [docs/](../docs/) for comprehensive guides
2. **Code Examples**: Check existing similar implementations
3. **GitHub Issues**: Search existing issues before creating new ones
4. **Community**: Frappe Framework community forums
5. **Professional Support**: Available for complex integrations

### 🔍 Debugging Resources

```bash
# View system logs
tail -f ~/frappe-bench/logs/worker.error.log

# Database console
bench --site dev.verenigingen.local mariadb

# Python console with Frappe context
bench --site dev.verenigingen.local console

# Performance profiling
bench --site dev.verenigingen.local execute verenigingen.utils.performance_utils.profile_request
```

### 📚 Learning Resources

- **[Frappe Framework Docs](https://frappeframework.com/docs)**
- **[ERPNext Documentation](https://docs.erpnext.com)**
- **[Verenigingen API Docs](API_DOCUMENTATION.md)**
- **[Python Best Practices](https://docs.python-guide.org/)**
- **[Vue.js Guide](https://vuejs.org/guide/)** (for frontend development)

---

## 🎯 Quick Reference

### ⚡ Daily Commands

```bash
bench start                 # Start development server
bench build                 # Build assets
bench migrate               # Run database migrations
bench restart               # Restart all services
bench clear-cache           # Clear application cache
```

### 🧪 Testing Commands

```bash
# Quick tests
bench --site dev.verenigingen.local execute verenigingen.tests.utils.quick_validation.run_quick_tests

# Specific module tests
bench --site dev.verenigingen.local run-tests --app verenigingen --module MODULE_NAME

# All tests
python scripts/testing/runners/regression_test_runner.py
```

### 🐛 Debugging Commands

```bash
# Error logs
tail -f ~/frappe-bench/logs/worker.error.log

# Database console
bench --site dev.verenigingen.local mariadb

# Python console
bench --site dev.verenigingen.local console
```

---

**Ready to contribute?** Check out the [open issues](https://github.com/0spinboson/verenigingen/issues) and [development board](../CLAUDE.md) for tasks that need attention!
