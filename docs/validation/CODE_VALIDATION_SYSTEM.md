# Code Validation System

## Overview

The Verenigingen app includes a comprehensive code validation system that catches common errors at development time, preventing runtime failures and improving code quality.

## Validation Components

### 1. Database Field Validator (`enhanced_field_validator.py`)
**Purpose**: Validates that database field references exist in DocType schemas

**What it catches**:
- ✅ `frappe.db.get_value("Doctype", filters, ["field1", "field2"])` with invalid fields
- ✅ `frappe.db.get_all("Doctype", fields=["field1", "field2"])` with invalid fields
- ✅ `doc.field_name` attribute access with invalid fields
- ✅ SQL queries with invalid field names

**Performance**: ~0.6s (764 Python files, 76 doctypes)

### 2. Template Variable Validator (`template_variable_validator.py`)
**Purpose**: Validates that Jinja template variables are provided by Python context

**What it catches**:
- ✅ `{{ variable }}` in templates without corresponding Python context
- ✅ Template context mismatches between HTML and Python files
- ✅ Risky patterns like `field or 0` that might break string formatting
- ✅ Missing fallback handling that could return `None`

**Performance**: ~1.1s (62 templates, 93 context providers)

### 3. Comprehensive Validator (`comprehensive_validator.py`)
**Purpose**: Unified validation suite with performance monitoring

**Features**:
- 🚀 Runs both validators with timing information
- 🎛️ CLI arguments for different modes (`--quiet`, `--field-only`, `--skip-template`)
- ⚡ Error handling and timeout protection
- 📊 Performance metrics and summaries

## Integration Points

### Pre-Commit Hooks
Located in `.pre-commit-config.yaml`:

```yaml
# Comprehensive validation (runs on .py and .html files)
- id: comprehensive-validation
  name: Comprehensive Code Validation (field + template)
  entry: python scripts/validation/comprehensive_validator.py --quiet
  stages: [pre-commit]

# Fast field-only validation (runs on git push)
- id: field-validation-only
  name: Database Field Validation (fast check)
  entry: python scripts/validation/comprehensive_validator.py --field-only --quiet
  stages: [pre-push]
```

### CI/CD Pipeline
Located in `.github/workflows/code-validation.yml`:

- **Pull Request**: Fast field validation with PR comments
- **Push to main/develop**: Full validation suite
- **Manual trigger**: Complete validation with integration tests

### Test Suite Integration
Located in `scripts/testing/runners/validation_test_runner.py`:

```bash
# Full test suite with validation
python scripts/testing/runners/validation_test_runner.py

# Fast tests only (validation + custom tests)
python scripts/testing/runners/validation_test_runner.py --fast

# Validation only
python scripts/testing/runners/validation_test_runner.py --validation-only
```

## Usage Examples

### Development Workflow
```bash
# Before committing (automatic via pre-commit)
python scripts/validation/comprehensive_validator.py

# Quick field check during development
python scripts/validation/comprehensive_validator.py --field-only

# Debug template issues
python scripts/validation/template_variable_validator.py
```

### CI/CD Integration
```bash
# CI mode (minimal output)
python scripts/validation/comprehensive_validator.py --quiet

# Fast CI check
python scripts/validation/comprehensive_validator.py --field-only --quiet

# Integration with test suite
python scripts/testing/runners/validation_test_runner.py --fast
```

## Configuration

### Exception Handling
Located in `scripts/validation/validation_config.py`:

```python
# Known false positives
FIELD_VALIDATION_EXCEPTIONS = {
    "scripts/setup/auto_assign_profiles.py": ["Team Leader", "Leader"],
}

TEMPLATE_VALIDATION_EXCEPTIONS = {
    "templates/pages/workflow_demo.html": ["sample_members", "workflow"],
}

# Allowed risky patterns
ALLOWED_RISKY_PATTERNS = {
    "template.minimum_amount or 0": "Used for validation constraints",
}
```

### Performance Tuning
- **Field Validation**: 764 files in ~0.6s (1200+ files/second)
- **Template Validation**: 62 templates in ~1.1s (50+ templates/second)
- **Total Suite**: Complete validation in ~1.7s

## Error Types and Fixes

### Database Field Errors
**Error**: `Field 'auto_renew' not found in doctype 'Membership'`

**Fix**:
```python
# ❌ Before
fields = ["name", "status", "auto_renew"]

# ✅ After (check DocType JSON first)
fields = ["name", "status"]  # auto_renew field doesn't exist
```

### Template Variable Errors
**Error**: `'standard_fee' is undefined`

**Fix**:
```python
# ❌ Before
standard_fee = template.suggested_amount or 0

# ✅ After
standard_fee = template.dues_rate or template.suggested_amount or membership_type.minimum_amount or 15.0
standard_fee = float(standard_fee) if standard_fee else 15.0
```

## Success Stories

### Recent Field Reference Fixes (January 2025)
The validation system successfully identified and helped fix critical field reference issues:

**System Alert DocType Issues:**
```bash
# Issues caught by enhanced_field_validator.py
🔴 vereinigingen/www/monitoring_dashboard.py:
   Line 45: compliance_status not found in doctype 'System Alert'

🔴 vereinigingen/doctype/system_alert/system_alert.py:
   Line 28: compliance_status not found in doctype 'System Alert'
```

**Fix Applied:**
```python
# ❌ Before - invalid field reference
filters["compliance_status"] = status

# ✅ After - correct field reference
filters["severity"] = status
```

### Payment History Event Handler Optimization
Enhanced validation detected inefficient payment history rebuilds:

**Issue Identified:**
```python
# ❌ Before - full rebuild on every event
def on_payment_entry_submit(doc, method):
    rebuild_complete_payment_history(doc.party)
```

**Optimization Applied:**
```python
# ✅ After - atomic updates for better performance
def on_payment_entry_submit(doc, method):
    refresh_financial_history(doc.party, doc.name)
```

### Pre-commit Hook Reliability Improvements
Fixed critical pre-commit hook failures:

**Problem:** `ModuleNotFoundError: No module named 'barista'`
**Solution:** Updated pre-commit configuration to use direct Python execution instead of bench commands

**Before:**
```yaml
entry: bench --site dev.veganisme.net execute "module.function"
```

**After:**
```yaml
entry: python scripts/testing/integration/simple_test.py
```

### Runtime Error Prevention
- **19 high-risk template variable issues** caught at development time
- **50 risky fallback patterns** identified for review
- **Zero field reference issues** in production code after recent fixes
- **3 critical field reference bugs** fixed in System Alert doctype
- **Payment history performance** improved through atomic event handlers

## Performance Metrics

| Validator | Files Scanned | Time | Rate |
|-----------|---------------|------|------|
| Field Validator | 764 Python files | 0.6s | 1200+ files/s |
| Template Validator | 62 templates | 1.1s | 50+ templates/s |
| **Total Suite** | **826 files** | **1.7s** | **485+ files/s** |

## Best Practices

### For Developers
1. **Run validation before committing** (automatic via pre-commit)
2. **Check DocType JSON files** before referencing fields
3. **Provide proper fallbacks** for template variables
4. **Use validator feedback** to improve code quality

### For CI/CD
1. **Use `--quiet` mode** for cleaner CI logs
2. **Use `--field-only`** for fast PR checks
3. **Allow template validation failures** (warnings) in CI
4. **Require field validation success** for merges

### For Testing
1. **Include validation in test suites** via `validation_test_runner.py`
2. **Run fast validation first** to catch issues early
3. **Use comprehensive validation** for release branches
4. **Monitor performance metrics** for regression detection

## Maintenance

### Adding Exceptions
1. Edit `scripts/validation/validation_config.py`
2. Add file path and field/variable names to appropriate exception lists
3. Document the reason for the exception

### Performance Optimization
- Field validation is I/O bound (reading JSON files)
- Template validation is CPU bound (regex processing)
- Both validators support parallel execution for future optimization

### Monitoring
- Check validation performance in CI/CD logs
- Monitor false positive rates
- Update exception lists as needed
- Review and validate new DocType fields

## Future Enhancements

1. **Parallel Processing**: Run validators concurrently
2. **Smart Caching**: Cache DocType schemas between runs
3. **IDE Integration**: VS Code extension for real-time validation
4. **Custom Rules**: User-defined validation patterns
5. **Metrics Dashboard**: Track validation trends over time
