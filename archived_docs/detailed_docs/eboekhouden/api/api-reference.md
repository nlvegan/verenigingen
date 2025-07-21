# eBoekhouden API Reference

## Overview

The eBoekhouden integration provides a REST API interface for importing financial data from eBoekhouden.nl. All APIs are accessible via HTTP POST with proper authentication.

**Base URL**: Your ERPNext site URL
**Authentication**: Session-based (must be logged in)
**Content-Type**: application/json
**API Version**: 2025.1 (July 2025)

## Core Migration APIs

### Full Migration

#### `clean_import_all`
**Endpoint**: `verenigingen.utils.eboekhouden.import_manager.clean_import_all`

Performs a complete migration of all eBoekhouden data to ERPNext.

**Parameters**:
```json
{
    "from_date": "2024-01-01",  // Optional: Start date (YYYY-MM-DD)
    "to_date": "2024-12-31",    // Optional: End date (YYYY-MM-DD)
    "mutation_types": ["Sales Invoice", "Purchase Invoice"]  // Optional: Specific types
}
```

**Response**:
```json
{
    "success": true,
    "migration_id": "EBMIG-2025-00001",
    "total_records": 1500,
    "estimated_duration": "2-3 hours",
    "status": "In Progress"
}
```

**Example Usage**:
```javascript
frappe.call({
    method: 'verenigingen.utils.eboekhouden.import_manager.clean_import_all',
    callback: function(r) {
        if (r.message.success) {
            frappe.msgprint('Migration started: ' + r.message.migration_id);
        }
    }
});
```

### Migration Status

#### `get_import_status`
**Endpoint**: `verenigingen.utils.eboekhouden.import_manager.get_import_status`

Retrieves current migration status and progress information.

**Parameters**: None

**Response**:
```json
{
    "success": true,
    "active_migrations": 1,
    "current_migration": {
        "id": "EBMIG-2025-00001",
        "status": "In Progress",
        "progress_percentage": 65,
        "records_imported": 975,
        "total_records": 1500,
        "estimated_completion": "2025-07-19 15:30:00"
    },
    "recent_completions": []
}
```

### Opening Balances

#### `import_opening_balances_only`
**Endpoint**: `verenigingen.utils.eboekhouden.eboekhouden_rest_full_migration.import_opening_balances_only`

Imports only opening balance entries, useful for balance sheet setup.

**Parameters**:
```json
{
    "company": "Your Company Name",
    "opening_date": "2024-01-01"  // Optional: Custom opening date
}
```

**Response**:
```json
{
    "success": true,
    "journal_entry": "JE-2025-00001",
    "accounts_processed": 45,
    "total_debit": 125000.00,
    "total_credit": 125000.00,
    "balanced": true,
    "skipped_accounts": {
        "stock": [{"account": "Stock Account", "balance": 5000.00}],
        "pnl": [{"account": "Sales Account", "type": "Income"}]
    }
}
```

## Connection and Testing APIs

### Connection Testing

#### `test_eboekhouden_connection`
**Endpoint**: `verenigingen.api.test_eboekhouden_connection.test_eboekhouden_connection`

Tests the REST API connection to eBoekhouden.

**Parameters**: None

**Response**:
```json
{
    "success": true,
    "message": "✅ REST API: Connection successful",
    "rest_working": true,
    "rest_configured": true
}
```

### Chart of Accounts Preview

#### `preview_chart_of_accounts`
**Endpoint**: `verenigingen.utils.eboekhouden.eboekhouden_api.preview_chart_of_accounts`

Previews the chart of accounts structure before migration.

**Parameters**: None

**Response**:
```json
{
    "success": true,
    "total_count": 150,
    "accounts": [
        {
            "id": 1000,
            "code": "1000",
            "name": "Bank Account",
            "type": "Asset",
            "category": "Bank"
        }
    ],
    "account_structure": {
        "assets": 45,
        "liabilities": 20,
        "equity": 5,
        "income": 35,
        "expenses": 45
    }
}
```

## Account Management APIs

### Account Type Mapping

#### `setup_default_payment_mappings`
**Endpoint**: `verenigingen.utils.eboekhouden.eboekhouden_payment_mapping.setup_default_payment_mappings`

Sets up default payment account mappings for a company.

**Parameters**:
```json
{
    "company": "Your Company Name"
}
```

**Response**:
```json
{
    "success": true,
    "mappings_created": 5,
    "bank_accounts": ["Bank Account 1", "Bank Account 2"],
    "cash_accounts": ["Cash Account"],
    "default_accounts_set": true
}
```

### Account Type Detection

#### `fix_account_types`
**Endpoint**: `verenigingen.utils.eboekhouden.eboekhouden_api.fix_account_types`

Automatically detects and fixes account types for imported accounts.

**Parameters**: None

**Response**:
```json
{
    "success": true,
    "accounts_updated": 12,
    "type_changes": {
        "receivable": 3,
        "payable": 4,
        "bank": 2,
        "cash": 1,
        "expense": 2
    }
}
```

## Enhanced Migration APIs

### Progress Tracking

#### `get_progress_info`
**Endpoint**: `verenigingen.utils.eboekhouden.eboekhouden_rest_full_migration.get_progress_info`

Provides real-time progress information during migration.

**Parameters**:
```json
{
    "migration_id": "EBMIG-2025-00001"
}
```

**Response**:
```json
{
    "success": true,
    "migration_id": "EBMIG-2025-00001",
    "current_phase": "Transaction Import",
    "progress_percentage": 65,
    "records_processed": 975,
    "total_records": 1500,
    "current_operation": "Processing Sales Invoices",
    "estimated_completion": "2025-07-19 15:30:00",
    "performance_stats": {
        "records_per_minute": 45,
        "average_processing_time": 1.3,
        "error_rate": 0.02
    }
}
```

### Migration Statistics

#### `migration_status_summary`
**Endpoint**: `verenigingen.utils.eboekhouden.eboekhouden_rest_full_migration.migration_status_summary`

Provides comprehensive migration statistics and summaries.

**Parameters**:
```json
{
    "migration_id": "EBMIG-2025-00001"
}
```

**Response**:
```json
{
    "success": true,
    "migration_summary": {
        "total_mutations_processed": 1500,
        "successful_imports": 1485,
        "failed_imports": 15,
        "skipped_records": 0,
        "success_rate": 99.0
    },
    "import_breakdown": {
        "journal_entries": 850,
        "sales_invoices": 420,
        "purchase_invoices": 215,
        "payment_entries": 0
    },
    "party_creation": {
        "customers_created": 45,
        "suppliers_created": 28
    },
    "account_mappings": {
        "accounts_mapped": 150,
        "grootboek_numbers_assigned": 150
    }
}
```

## Utility and Maintenance APIs

### Data Quality

#### `get_dashboard_data_api`
**Endpoint**: `verenigingen.utils.eboekhouden.eboekhouden_api.get_dashboard_data_api`

Retrieves dashboard data for migration monitoring.

**Parameters**: None

**Response**:
```json
{
    "success": true,
    "dashboard_data": {
        "active_migrations": 1,
        "completed_migrations": 5,
        "total_records_imported": 15000,
        "error_rate": 0.5,
        "performance_metrics": {
            "average_import_speed": 42.5,
            "peak_performance": 85.2
        }
    },
    "system_health": {
        "api_connection": "healthy",
        "database_status": "optimal",
        "memory_usage": "normal"
    }
}
```

### Settings Management

#### `update_api_url`
**Endpoint**: `verenigingen.utils.eboekhouden.eboekhouden_api.update_api_url`

Updates the API URL to the correct modern endpoint.

**Parameters**: None

**Response**:
```json
{
    "success": true,
    "old_url": "https://api.e-boekhouden.nl/",
    "new_url": "https://api.e-boekhouden.nl/v1",
    "settings_updated": true
}
```

## Error Handling

### Standard Error Response
All APIs return consistent error responses:

```json
{
    "success": false,
    "error": "Descriptive error message",
    "error_type": "ValidationError|ConnectionError|DataError",
    "details": {
        "field": "api_token",
        "message": "API token is required"
    },
    "retry_possible": true
}
```

### Common Error Types

#### Authentication Errors
- **Missing API Token**: Configure token in E-Boekhouden Settings
- **Invalid Token**: Verify token is correct and active
- **Token Expired**: Regenerate token in eBoekhouden account

#### Connection Errors
- **Network Timeout**: Check internet connection and API status
- **Rate Limiting**: Built-in retry mechanisms handle this automatically
- **Service Unavailable**: eBoekhouden API maintenance

#### Data Errors
- **Invalid Date Range**: Check date formats (YYYY-MM-DD)
- **Missing Company**: Ensure company is configured in settings
- **Account Conflicts**: Duplicate account codes or missing accounts

## Rate Limiting

The API includes built-in rate limiting:
- **Requests per minute**: 60 (automatically managed)
- **Concurrent migrations**: 1 per company
- **Retry mechanism**: Automatic with exponential backoff
- **Queue system**: Requests queued during high usage

## API Usage Examples

### JavaScript (Frappe Client)
```javascript
// Start full migration
frappe.call({
    method: 'verenigingen.utils.eboekhouden.import_manager.clean_import_all',
    args: {
        from_date: '2024-01-01',
        to_date: '2024-12-31'
    },
    callback: function(r) {
        if (r.message.success) {
            console.log('Migration started:', r.message.migration_id);
            // Start progress monitoring
            monitor_migration_progress(r.message.migration_id);
        }
    }
});

// Monitor progress
function monitor_migration_progress(migration_id) {
    setInterval(function() {
        frappe.call({
            method: 'verenigingen.utils.eboekhouden.eboekhouden_rest_full_migration.get_progress_info',
            args: { migration_id: migration_id },
            callback: function(r) {
                if (r.message.success) {
                    update_progress_bar(r.message.progress_percentage);
                }
            }
        });
    }, 5000); // Update every 5 seconds
}
```

### Python (Server-side)
```python
import frappe

# Start migration programmatically
def start_migration():
    result = frappe.call(
        'verenigingen.utils.eboekhouden.import_manager.clean_import_all',
        from_date='2024-01-01',
        to_date='2024-12-31'
    )

    if result.get('success'):
        migration_id = result.get('migration_id')
        frappe.log(f"Migration started: {migration_id}")
        return migration_id
    else:
        frappe.throw(result.get('error', 'Migration failed'))

# Check migration status
def check_status(migration_id):
    return frappe.call(
        'verenigingen.utils.eboekhouden.eboekhouden_rest_full_migration.get_progress_info',
        migration_id=migration_id
    )
```

## Best Practices

### API Usage
1. **Always check success flag** before processing response data
2. **Implement error handling** for all API calls
3. **Use progress monitoring** for long-running operations
4. **Batch operations** when possible to reduce API calls
5. **Cache results** where appropriate to improve performance

### Performance
1. **Monitor rate limits** and implement appropriate delays
2. **Use async calls** for non-blocking operations
3. **Implement timeouts** for long-running requests
4. **Handle large datasets** with pagination when available

### Security
1. **Secure API tokens** - never expose in client-side code
2. **Validate permissions** before making API calls
3. **Log API usage** for audit trails
4. **Use HTTPS** for all API communications

---

**API Version**: 2025.1
**Last Updated**: July 2025
**Support**: System Administrator or eBoekhouden Integration Team
