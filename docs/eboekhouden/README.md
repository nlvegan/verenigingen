# eBoekhouden Integration Documentation

## Overview

This directory contains comprehensive documentation for the eBoekhouden integration system - a production-ready solution for importing financial data from eBoekhouden.nl into ERPNext.

## Quick Start

1. **Setup**: Configure API credentials in [E-Boekhouden Settings](./implementation/configuration.md)
2. **Migration**: Follow the [Migration Guide](./migration/migration-guide.md)
3. **API Reference**: See [API Documentation](./api/api-reference.md)
4. **Troubleshooting**: Check [Common Issues](./maintenance/troubleshooting.md)

## Documentation Structure

### 📚 **Core Documentation**

- **[Migration Guide](./migration/migration-guide.md)** - Complete step-by-step migration process
- **[API Reference](./api/api-reference.md)** - REST API endpoints and usage
- **[Configuration Guide](./implementation/configuration.md)** - Setup and configuration
- **[Troubleshooting](./maintenance/troubleshooting.md)** - Common issues and solutions

### 🔧 **Implementation Details**

- **[Architecture Overview](./implementation/architecture.md)** - System architecture and components
- **[Stock Account Handling](./implementation/stock-accounts.md)** - Special handling for stock accounts
- **[Opening Balance Import](./implementation/opening-balances.md)** - Opening balance processing
- **[Error Handling](./implementation/error-handling.md)** - Error recovery and handling

### 📋 **Maintenance & Development**

- **[Development Guide](./maintenance/development.md)** - Development guidelines
- **[Performance Monitoring](./maintenance/performance.md)** - Performance optimization
- **[Upgrade Notes](./maintenance/upgrades.md)** - Version upgrade information

### 📊 **Project History**

- **[Implementation Summary](./project/implementation-summary.md)** - Complete project history
- **[2025 Reorganization](./project/reorganization-2025.md)** - Major 2025 modernization effort
- **[Cleanup Results](./project/cleanup-results.md)** - Code organization achievements

## System Status

**Current Version**: 2025.1 (August 2025)

- ✅ **REST API Integration** with comprehensive functionality
- ✅ **Complete DocType Implementation** (E-Boekhouden Settings, Migration, Import Log, etc.)
- ✅ **Enhanced migration orchestration** with progress tracking
- ✅ **Intelligent account mapping** with type detection
- ✅ **Comprehensive error handling** and recovery
- ✅ **Production-ready** with modular architecture and proper logging

## Key Features

### 🔄 **Migration Capabilities**

- **Full transaction import** from eBoekhouden.nl
- **Chart of accounts mapping** with intelligent type detection
- **Party management** (customers/suppliers) with automatic creation
- **Opening balance import** with stock account exclusion
- **Real-time progress tracking** with accurate counters

### 🛡️ **Reliability Features**

- **Automatic balancing** prevents migration failures
- **Stock account detection** and proper handling
- **Comprehensive error recovery** with retry mechanisms
- **Transaction validation** and integrity checks
- **Detailed logging** for audit trails

### ⚡ **Performance Optimizations**

- **REST API** provides unlimited transaction access
- **Batch processing** for efficient imports
- **Smart caching** reduces API calls
- **Progressive enhancement** for large datasets

## Support & Maintenance

- **Issue Tracking**: Report issues with detailed logs from migration dashboard
- **Performance**: Monitor via built-in dashboard and logging
- **Updates**: Follow upgrade notes for version migrations
- **Development**: See development guide for customizations

## Quick Reference

### Essential API Endpoints

```python
# Test API connection
verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator.test_rest_iterator()

# Import chart of accounts
verenigingen.e_boekhouden.utils.eboekhouden_coa_import.import_chart_of_accounts()

# Start full REST migration
verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration.start_full_rest_import()

# Import opening balances only
verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration.test_opening_balance_import()

# Run quality checks
verenigingen.e_boekhouden.utils.migration.quality_checker.run_migration_quality_check()

# Get cache statistics
verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration.get_cache_statistics()
```

### Key Configuration DocTypes

- **E-Boekhouden Settings**: Single doctype for API configuration, company defaults, account classification, and cost center mappings. Key fields include:
  - `api_url` / `api_token` / `source_application`: API connection credentials
  - `default_company` / `default_cost_center` / `default_currency`: ERPNext company mapping
  - `fiscal_year_start_month`: Fiscal year configuration
  - `payment_gateway_virtual_account` / `payment_gateway_invoice_prefix`: Payment gateway integration
  - `auto_create_parties_from_bank_transactions`: Automatic customer/supplier creation
  - `group_type_mappings`: Table mapping eBoekhouden groups to ERPNext account types
  - `cost_center_mappings`: Table mapping eBoekhouden cost centers to ERPNext
  - Account classification fields: `bal_asset_ranges`, `bal_liability_ranges`, `bal_equity_ranges`, `vw_income_ranges`, `vw_expense_ranges`, and keyword fields for advanced classification
- **E-Boekhouden Migration**: Migration orchestration with progress tracking
- **E-Boekhouden Dashboard**: Dashboard view for monitoring migration and sync status
- **E-Boekhouden Ledger Mapping**: Account mapping between eBoekhouden and ERPNext chart of accounts
- **E-Boekhouden Account Mapping**: Individual account-level mappings
- **E-Boekhouden Group Type Mapping**: Maps eBoekhouden account groups to ERPNext account types (child table)
- **E-Boekhouden Cost Center Mapping**: Maps eBoekhouden cost centers to ERPNext cost centers (child table)
- **E-Boekhouden Item Mapping**: Maps eBoekhouden items to ERPNext items
- **E-Boekhouden Import Log**: Detailed logging of all import operations
- **E-Boekhouden Payment Mapping**: Payment reconciliation mapping between systems
- **Party Enrichment Queue**: Queue for enriching customer/supplier data from eBoekhouden

### Services

The `e_boekhouden/services/` directory contains the core business logic:

- **account_migration_service.py**: Migrates chart of accounts from eBoekhouden to ERPNext
- **account_classification_service.py**: Classifies accounts by type using configurable rules
- **account_hierarchy_service.py**: Manages account tree structure and parent-child relationships
- **account_organization_service.py**: Organizes accounts into proper ERPNext groups
- **account_diagnostics_service.py**: Diagnostic tools for identifying mapping issues
- **dashboard_service.py**: Powers the E-Boekhouden Dashboard with status and metrics
- **migration_data_quality_service.py**: Validates data quality before and after migration
- **relation_migration_service.py**: Migrates customer and supplier (relation) data

---

**Last Updated**: March 2026
**Documentation Version**: 2026.1
**System Status**: Production Ready
