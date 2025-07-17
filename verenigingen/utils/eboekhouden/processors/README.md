# eBoekhouden Transaction Processors

This directory contains modular transaction processors that provide a clean interface for processing eBoekhouden mutations.

## Overview

The processors wrap the existing functionality from `eboekhouden_rest_full_migration.py` to provide:
- Clear separation of concerns
- Easier testing and maintenance
- Consistent error handling
- Unified processing interface

## Architecture

```
transaction_coordinator.py
    ├── invoice_processor.py     → Wraps _create_sales_invoice() and _create_purchase_invoice()
    ├── payment_processor.py     → Wraps _create_payment_entry()
    ├── journal_processor.py     → Wraps _create_journal_entry()
    └── opening_balance_processor.py → Wraps opening balance logic
```

## Usage

### Basic Usage

```python
from verenigingen.utils.eboekhouden.processors.transaction_coordinator import TransactionCoordinator

# Initialize coordinator
coordinator = TransactionCoordinator(company="Your Company")

# Process a single mutation
mutation = {"id": 123, "type": 1, "amount": 100.0, ...}
result = coordinator.process_mutation(mutation)

# Process a batch
mutations = [...]  # List of mutations from API
stats = coordinator.process_batch(mutations)
print(f"Created: {stats['successfully_created']}, Failed: {stats['failed']}")
```

### Integration with Main Migration

The coordinator can be integrated into the main migration file gradually:

```python
# In eboekhouden_rest_full_migration.py
def _import_rest_mutations_batch_modular(migration_name, mutations, settings):
    """New modular implementation using coordinator"""
    from .processors.transaction_coordinator import TransactionCoordinator

    # Get company from settings
    company = settings.default_company
    cost_center = get_default_cost_center(company)

    # Create coordinator
    coordinator = TransactionCoordinator(company, cost_center)

    # Validate prerequisites
    validation = coordinator.validate_prerequisites()
    if not validation["valid"]:
        frappe.throw(_("Prerequisites not met: {}").format(", ".join(validation["issues"])))

    # Process mutations
    def progress_callback(current, total):
        frappe.publish_progress(
            current * 100 / total,
            title=_("Processing Mutations"),
            description=_("Processing mutation {0} of {1}").format(current, total)
        )

    stats = coordinator.process_batch(mutations, progress_callback)

    # Log results
    if stats["error_count"] > 0:
        frappe.log_error(
            message=json.dumps(stats["errors"], indent=2),
            title="eBoekhouden Import Errors"
        )

    return stats
```

## Benefits

1. **Modularity**: Each processor handles one type of transaction
2. **Reusability**: Uses existing, tested functions from the main file
3. **Maintainability**: Easier to modify or extend individual processors
4. **Testability**: Each processor can be tested independently
5. **Gradual Migration**: Can be adopted incrementally without breaking existing code

## Future Enhancements

- Add caching for frequently accessed data (accounts, items, etc.)
- Implement parallel processing for better performance
- Add dry-run mode for testing
- Enhanced error recovery and retry logic
- Transaction rollback capabilities
