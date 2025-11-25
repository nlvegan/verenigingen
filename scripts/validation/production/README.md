# Production-Ready Validators

**Status**: ✅ Production-Ready
**Count**: 10 validators

These validators are production-tested, have high accuracy, and are recommended for daily development workflows, CI/CD pipelines, and pre-commit hooks.

## Validators in This Directory

### Primary Field Validation
- **comprehensive_field_reference_validator.py** - Enterprise-grade field validation with schema introspection
- **database_field_reference_validator.py** - Configurable field validation (1,049 DocTypes)
- **field_reference_validator.py** - Core field reference validation engine
- **production_ready_validator.py** - Production system with accurate detection

### SQL & Database Validation
- **sql_field_reference_validator.py** - ⭐ Best SQL validator with confidence scoring

### DocType & Template Validation
- **enhanced_doctype_validator.py** - Advanced DocType validation with confidence scoring
- **doctype_field_analyzer.py** - Detailed DocType field analysis
- **template_field_validator.py** - Template integrity and field references
- **javascript_doctype_field_validator.py** - JS field validation

### API & Cross-Language Validation
- **js_python_parameter_validator_enhanced.py** - API parameter alignment validation
- **database_field_issue_inventory.py** - Comprehensive inventory and analysis

## Usage Recommendations

### Daily Development Workflow
```bash
# Quick validation (recommended for pre-commit)
python scripts/validation/production/database_field_reference_validator.py

# Comprehensive field check
python scripts/validation/production/comprehensive_field_reference_validator.py

# SQL validation
python scripts/validation/production/sql_field_reference_validator.py
```

### Template & Portal Validation
```bash
# Template integrity
python scripts/validation/production/template_field_validator.py

# JavaScript validation
python scripts/validation/production/javascript_doctype_field_validator.py
```

### Comprehensive Analysis
```bash
# Full production validation
python scripts/validation/production/production_ready_validator.py

# Detailed inventory
python scripts/validation/production/database_field_issue_inventory.py
```

## Integration

All validators in this directory are:
- ✅ Pre-commit hook compatible
- ✅ CI/CD pipeline ready
- ✅ Accurate and focused detection
- ✅ Performance-optimized
- ✅ Production-tested

## Documentation

See `docs/validation_tool_inventory.md` for comprehensive validator capabilities and technical details.
