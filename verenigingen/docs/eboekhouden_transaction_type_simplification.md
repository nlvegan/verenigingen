# E-Boekhouden Transaction Type Simplification

## Overview

E-Boekhouden provides native transaction types (Soort/MutatieType) that can be directly mapped to ERPNext document types, eliminating the need for complex pattern matching based on account codes and descriptions.

## Direct Transaction Type Mapping

### E-Boekhouden Transaction Types → ERPNext Documents

| E-Boekhouden Type | ERPNext Document | Notes |
|------------------|------------------|-------|
| Factuur ontvangen | Purchase Invoice | Invoice received from supplier |
| Factuur verstuurd | Sales Invoice | Invoice sent to customer |
| Factuurbetaling ontvangen | Payment Entry | Payment received (links to Sales Invoice) |
| Factuurbetaling verstuurd | Payment Entry | Payment sent (links to Purchase Invoice) |
| Geld ontvangen | Journal Entry | Money received (non-invoice) |
| Geld verstuurd | Journal Entry | Money sent (non-invoice) |
| Memoriaal | Journal Entry | Manual journal/adjustment entry |

## Benefits of This Approach

1. **Accuracy**: Direct mapping based on E-Boekhouden's own categorization
2. **Simplicity**: No complex pattern matching or account analysis needed
3. **Performance**: Faster processing without regex pattern matching
4. **Reliability**: Consistent results based on source system data
5. **Maintenance**: No need to update patterns for new account types

## Implementation

### 1. Transaction Type Mapper

Created `eboekhouden_transaction_type_mapper.py` with simple functions:
- `get_erpnext_document_type()`: Maps E-Boekhouden type to ERPNext document
- `get_payment_entry_reference_type()`: Determines invoice type for payments
- `simplify_migration_process()`: Main function for migration use

### 2. Updated UI

The mapping review page now shows:
- Clear explanation of native type mapping
- Interactive type mapping display
- Test functionality to verify mappings
- Deprecated complex pattern matching

### 3. Migration Process Updates

To use the simplified approach:

```python
from verenigingen.utils.eboekhouden_transaction_type_mapper import simplify_migration_process

# During mutation processing
mutation_data = {
    "Soort": "Factuur ontvangen",  # From E-Boekhouden
    "MutatieNr": "12345",
    # ... other fields
}

# Get document type
mapping_result = simplify_migration_process(mutation_data)
# Returns: {
#     "document_type": "Purchase Invoice",
#     "transaction_type": "Factuur ontvangen",
#     "confidence": "high",
#     "reason": "Direct mapping from E-boekhouden type: Factuur ontvangen"
# }
```

## Deprecation Plan

The complex transaction mapping functionality should be:
1. Kept available for edge cases or custom requirements
2. Disabled by default in the UI
3. Eventually removed after confirming all use cases are covered

## API Considerations

- REST API is preferred over SOAP (500 transaction limit)
- Both APIs should provide the Soort/MutatieType field
- Ensure this field is always captured during import

## Next Steps

1. Update the migration process to use `simplify_migration_process()`
2. Test with real E-Boekhouden data to verify type coverage
3. Add any missing transaction types if discovered
4. Consider removing the complex mapping UI after validation period
