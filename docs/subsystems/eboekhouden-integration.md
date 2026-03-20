# eBoekhouden Accounting Integration

## Overview

The eBoekhouden Integration System provides synchronization between the Verenigingen association management platform and eBoekhouden (e-boekhouden.nl), a Dutch cloud-based accounting platform. This system enables financial data flow, maintains accounting compliance, and provides integration between association operations and financial reporting.

## Architecture Overview

### Module Structure

The integration lives under `e_boekhouden/` with this structure:

- **`doctype/`** -- 9 DocTypes for settings, mappings, dashboard, and import tracking
- **`services/`** -- 7 service modules for migration and data quality
- **`utils/`** -- REST client, migration tools, processors, and consolidated utilities
- **`api/`** -- Migration API endpoint
- **`workspace/`** -- eBoekhouden workspace configuration

### REST API Client (`eboekhouden_rest_client.py`)

Primary integration point for data retrieval:

- Paginated mutation retrieval (overcomes 500-record SOAP limitation)
- Session-based authentication with automatic token management
- Cached ledger and relation data for performance optimization
- REST iterator (`eboekhouden_rest_iterator.py`) for bulk data pagination
- HTTP client mixin (`http_client_mixin.py`) for shared HTTP behavior

### Settings Management (`E-Boekhouden Settings`)

Centralized configuration DocType (`e_boekhouden/doctype/e_boekhouden_settings/`):

**Core Settings:**

- **API Connection**: api_url, api_token, source_application
- **SOAP Credentials**: soap_username, soap_security_code1, soap_security_code2
- **Default Mapping**: default_company, default_cost_center, default_currency

### DocTypes

| DocType | Purpose |
|---------|---------|
| `E-Boekhouden Settings` | API credentials and integration configuration |
| `E-Boekhouden Dashboard` | Integration status monitoring |
| `E-Boekhouden Account Mapping` | Maps eBoekhouden accounts to ERPNext accounts |
| `E-Boekhouden Cost Center Mapping` | Maps eBoekhouden cost centers to ERPNext |
| `E-Boekhouden Group Type Mapping` | Maps account group types |
| `E-Boekhouden Import Log` | Tracks import history and errors |
| `E-Boekhouden Item Mapping` | Maps items between systems |
| `E-Boekhouden Ledger Mapping` | Maps ledger accounts with JS UI |
| `E-Boekhouden Migration` | Migration state tracking |
| `E-Boekhouden Payment Mapping` | Maps payment methods |
| `Party Enrichment Queue` | Queue for party data enrichment |

## Migration Architecture

### Multi-Phase Migration

The migration engine (`eboekhouden_enhanced_migration.py`) orchestrates data migration in phases:

1. **Chart of Accounts Setup**: Account structure and hierarchy import
2. **Customer/Supplier Import**: Party master data with validation via `relation_migration_service.py`
3. **Opening Balances**: Historical balance establishment via `opening_balance_processor.py`
4. **Transaction History**: Complete mutation import with categorization via type-specific processors
5. **Reconciliation**: Balance validation and discrepancy resolution via `reconcile_eboekhouden_balances.py`

### Transaction Classification

The mutation processing pipeline classifies eBoekhouden mutations into ERPNext document types:

- **Invoice Processor**: Sales Invoice and Purchase Invoice creation from mutation data
- **Journal Processor**: Journal Entry creation for non-invoice transactions
- **Stock Processor**: Stock transaction handling
- **Opening Balance Processor**: Opening balance Journal Entries

Each processor extends `base_processor.py` and follows a common interface.

### Party Resolution

`party_extractor.py` extracts customer/supplier data from mutations. `consolidated/party_utils.py` handles creation and matching of ERPNext Customer and Supplier records. The `Party Enrichment Queue` DocType queues party records for additional data enrichment.

### Data Quality

Quality is maintained at multiple stages:

- `migration_data_quality_service.py` -- Validates data during migration
- `migration/quality_checker.py` -- Post-migration quality checks
- `data_quality_utils.py` -- General quality utilities
- `data_integrity.py` -- Data integrity validation
- `account_diagnostics_service.py` -- Account migration completeness checks

### Error Handling

- `error_handling_framework.py` -- Structured error handling with classification
- `migration_error_logger.py` -- Structured error logging with context
- `E-Boekhouden Import Log` DocType tracks import history and errors

## Services Layer (`e_boekhouden/services/`)

- `account_migration_service.py` -- Account structure migration (reference implementation)
- `account_classification_service.py` -- Classifies accounts into ERPNext types
- `account_hierarchy_service.py` -- Builds parent-child account hierarchy
- `account_organization_service.py` -- Organizes migrated accounts into groups
- `account_diagnostics_service.py` -- Validates migration completeness
- `relation_migration_service.py` -- Customer/supplier data migration
- `migration_data_quality_service.py` -- Data quality validation
- `dashboard_service.py` -- Powers the Dashboard DocType

## Utils Layer (`e_boekhouden/utils/`)

### Transaction Processors (`utils/processors/`)

- `base_processor.py` -- Base class for all processors
- `invoice_processor.py` -- Sales/Purchase Invoice mutations
- `journal_processor.py` -- Journal Entry mutations
- `opening_balance_processor.py` -- Opening balance imports
- `stock_processor.py` -- Stock transaction processing

### Consolidated Utilities (`utils/consolidated/`)

- `account_manager.py`, `bank_account_utils.py`, `cost_center_utils.py`
- `invoice_line_utils.py`, `migration_coordinator.py`, `party_utils.py`
- `payment_entry_creation.py`, `progress_utils.py`

### Migration Tools

- `eboekhouden_enhanced_migration.py` -- Multi-phase migration engine
- `migration_api.py` -- API entry point
- `migration_error_logger.py` -- Error logging
- `migration/quality_checker.py`, `migration/transaction_processor.py`

### Other Utilities

- `configurable_account_mapper.py`, `account_type_validator.py`
- `eboekhouden_smart_account_typing.py` -- Intelligent account type inference
- `bank_transaction_parser.py`, `bank_transaction_analysis.py`, `bank_transaction_summary.py`
- `payment_processing/overpayment_detector.py`
- `eboekhouden_payment_mapping.py`, `eboekhouden_payment_naming.py`, `eboekhouden_payment_import.py`
- `create_eboekhouden_custom_fields.py`, `data_quality_utils.py`, `data_integrity.py`
- `error_handling_framework.py`, `invoice_classifier.py`, `party_extractor.py`

## Account Mapping Configuration

### Configurable Account Mapper (`configurable_account_mapper.py`)

Provides user-configurable rules for mapping eBoekhouden accounts to ERPNext:

- Rule-based mapping with priority ordering
- Account type inference via `eboekhouden_smart_account_typing.py`
- Account type validation via `account_type_validator.py`
- Account group handling via `eboekhouden_account_group_fix.py`

### Group Type Mapping

The `E-Boekhouden Group Type Mapping` DocType maps eBoekhouden's account group numbering to ERPNext account types:

```
001 Vaste activa -> Fixed Assets
002 Liquide middelen -> Current Assets
055 Opbrengsten -> Income
056 Personeelskosten -> Personnel Costs
```

### Transaction Type Mapping

`eboekhouden_transaction_type_mapper.py` maps eBoekhouden transaction types to ERPNext document types. `invoice_classifier.py` further classifies transactions.

### Payment Mapping

- `E-Boekhouden Payment Mapping` DocType maps payment methods
- `eboekhouden_payment_mapping.py` applies payment method mappings
- `eboekhouden_payment_naming.py` generates proper payment names
- `payment_processing/overpayment_detector.py` detects overpayments during import

## Custom Field Integration

Defined in `e_boekhouden/hooks.py` fixtures:

- `Account-eboekhouden_account_id`
- `Customer-eboekhouden_customer_id`
- `Supplier-eboekhouden_supplier_id`

Note: `e_boekhouden/hooks.py` is a module-level config. Frappe only loads hooks.py from the app root. Real doc_events and scheduler tasks are in `hooks/doc_events.py` and `hooks/scheduler.py`.

## Scheduled Tasks

From `hooks/scheduler.py`:

- **Daily**: `update_dashboard_data_periodically` -- refreshes integration dashboard

## Known Issues

- MUTATION_TYPE_SINGULAR type mapping: type 1 = Purchase Invoice, type 2 = Sales Invoice (was previously swapped; fixed in Phase 5 audit)

## Key File Locations

- **Module root**: `e_boekhouden/`
- **DocTypes**: `e_boekhouden/doctype/` (9 DocTypes)
- **Services**: `e_boekhouden/services/` (7 service modules + tests)
- **Utils**: `e_boekhouden/utils/` (30+ utility modules)
- **Processors**: `e_boekhouden/utils/processors/` (5 processor modules)
- **Tests**: `tests/e_boekhouden/`
