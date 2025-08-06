# eBoekhouden API Reference

## Overview

The eBoekhouden integration provides comprehensive REST API endpoints for importing financial data from eBoekhouden.nl. The implementation uses modern REST architecture with comprehensive error handling.

**Base URL**: Your ERPNext site URL
**Authentication**: Session-based (must be logged in)
**Content-Type**: application/json
**API Version**: 2025.1 (August 2025)

## Core Migration APIs

### Full REST Migration

#### `start_full_rest_import`
**Endpoint**: `verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration.start_full_rest_import`

Starts a complete REST API migration of all eBoekhouden data.

**Parameters**:
```json
{
    "migration_name": "Production Import 2025"
}
```

**Response**:
```json
{
    "success": true,
    "migration_id": "EBMIG-2025-00001",
    "message": "Migration started successfully",
    "estimated_records": 2500
}
```

#### `test_opening_balance_import`
**Endpoint**: `verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration.test_opening_balance_import`

Tests and imports opening balance entries only.

**Parameters**: None

**Response**:
```json
{
    "success": true,
    "processed": 45,
    "errors": 0,
    "message": "Imported 45 opening balances",
    "journal_entries_created": ["JE-2025-00001", "JE-2025-00002"]
}
```

#### `get_cache_statistics`
**Endpoint**: `verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration.get_cache_statistics`

Retrieves API cache performance metrics.

**Parameters**: None

**Response**:
```json
{
    "success": true,
    "cache_stats": {
        "mutations_cached": 1500,
        "ledgers_cached": 150,
        "relations_cached": 75,
        "cache_hit_rate": 0.85
    }
}
```

## Chart of Accounts Management

### Import Chart of Accounts

#### `import_chart_of_accounts`
**Endpoint**: `verenigingen.e_boekhouden.utils.eboekhouden_coa_import.import_chart_of_accounts`

Imports complete chart of accounts from eBoekhouden.

**Parameters**: None

**Response**:
```json
{
    "success": true,
    "accounts_created": 150,
    "accounts_updated": 25,
    "mappings_created": 175,
    "message": "Chart of accounts import completed"
}
```

#### `analyze_chart_of_accounts`
**Endpoint**: `verenigingen.e_boekhouden.utils.eboekhouden_coa_import.analyze_chart_of_accounts`

Analyzes the chart of accounts structure before import.

**Parameters**: None

**Response**:
```json
{
    "success": true,
    "total_accounts": 150,
    "account_types": {
        "Current Asset": 45,
        "Fixed Asset": 15,
        "Current Liability": 25,
        "Income": 30,
        "Expense": 35
    }
}
```

## Connection and Testing

### API Connection Testing

#### `test_rest_iterator`
**Endpoint**: `verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator.test_rest_iterator`

Tests REST API connectivity and data availability.

**Parameters**: None

**Response**:
```json
{
    "success": true,
    "message": "REST API connection successful",
    "session_token_valid": true,
    "mutations_available": 2500,
    "ledgers_available": 150
}
```

#### `estimate_mutation_range`
**Endpoint**: `verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator.estimate_mutation_range`

Estimates the volume of data available for migration.

**Parameters**: None

**Response**:
```json
{
    "success": true,
    "total_mutations": 2500,
    "date_range": {
        "from": "2020-01-01",
        "to": "2025-08-04"
    },
    "estimated_import_time": "2-3 hours"
}
```

## Migration Management

### Migration DocType APIs

#### `start_migration`
**Endpoint**: E-Boekhouden Migration DocType method

Starts migration through the Migration DocType interface.

**Usage via DocType**:
```python
migration = frappe.get_doc("E-Boekhouden Migration", migration_name)
migration.start_migration()
```

#### `pause_migration`
**Endpoint**: E-Boekhouden Migration DocType method

Pauses a running migration.

**Usage via DocType**:
```python
migration = frappe.get_doc("E-Boekhouden Migration", migration_name)
migration.pause_migration()
```

## Quality Assurance

### Migration Quality Check

#### `run_migration_quality_check`
**Endpoint**: `verenigingen.e_boekhouden.utils.migration.quality_checker.run_migration_quality_check`

Runs comprehensive quality checks on migrated data.

**Parameters**: None

**Response**:
```json
{
    "success": true,
    "checks_passed": 8,
    "checks_failed": 0,
    "warnings": 2,
    "report": {
        "balance_validation": "PASS",
        "account_mapping": "PASS",
        "party_creation": "PASS",
        "transaction_integrity": "PASS"
    }
}
```

## Utility Functions

### Cleanup and Maintenance

#### `cleanup_failed_migrations`
**Endpoint**: `verenigingen.e_boekhouden.utils.cleanup_utils.cleanup_failed_migrations`

Cleans up data from failed migration attempts.

**Parameters**: None

**Response**:
```json
{
    "success": true,
    "migrations_cleaned": 2,
    "records_removed": 150,
    "message": "Cleanup completed successfully"
}
```

#### `reset_migration_state`
**Endpoint**: `verenigingen.e_boekhouden.utils.cleanup_utils.reset_migration_state`

Resets migration to fresh state for retry.

**Parameters**:
```json
{
    "migration_name": "EBMIG-2025-00001"
}
```

**Response**:
```json
{
    "success": true,
    "message": "Migration state reset successfully"
}
```

## Configuration Management

### Settings Validation

#### `test_api_connection`
**Endpoint**: `verenigingen.e_boekhouden.utils.eboekhouden_migration_config.test_api_connection`

Tests API connection using current settings.

**Parameters**: None

**Response**:
```json
{
    "success": true,
    "api_status": "Connected",
    "session_token": "Valid",
    "settings_valid": true
}
```

#### `validate_migration_settings`
**Endpoint**: `verenigingen.e_boekhouden.utils.eboekhouden_migration_config.validate_migration_settings`

Validates all migration configuration settings.

**Parameters**: None

**Response**:
```json
{
    "success": true,
    "validation_result": {
        "api_credentials": "Valid",
        "company_settings": "Valid",
        "account_mappings": "Valid"
    }
}
```

## Error Handling

All API endpoints follow consistent error response format:

```json
{
    "success": false,
    "error": "Detailed error message",
    "error_type": "ValidationError|APIError|ConfigurationError",
    "suggestions": ["Check API credentials", "Verify company settings"]
}
```

## Authentication

All endpoints require valid ERPNext session. Use one of these roles:
- System Manager
- Verenigingen Administrator

## Usage Examples

### JavaScript (Frappe Client)
```javascript
frappe.call({
    method: 'verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator.test_rest_iterator',
    callback: function(r) {
        if (r.message.success) {
            frappe.msgprint('API connection successful');
        } else {
            frappe.msgprint('Connection failed: ' + r.message.error);
        }
    }
});
```

### Command Line (Bench)
```bash
# Test API connection
bench --site dev.veganisme.net execute verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator.test_rest_iterator

# Import chart of accounts
bench --site dev.veganisme.net execute verenigingen.e_boekhouden.utils.eboekhouden_coa_import.import_chart_of_accounts

# Start full migration
bench --site dev.veganisme.net execute verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration.start_full_rest_import --args '{"migration_name": "Production Import"}'
```

---

**Last Updated**: August 2025
**API Version**: 2025.1
**Status**: Production Ready ✅
