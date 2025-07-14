# Payment Import Implementation Plan v2 - API-Aware

## Critical Context: REST API Limitations

### What We Know from Code Analysis

Based on the transaction processing audit and existing code, the REST API payment structure appears to be:

```javascript
// Mutation Type 3 or 4 (Payment)
{
    "id": 12345,
    "type": 3,  // 3=Customer Payment, 4=Supplier Payment
    "date": "2024-01-15",
    "amount": 250.00,
    "ledgerId": 13201869,  // Main ledger = Bank account
    "relationId": "REL001",  // Customer/Supplier ID
    "invoiceNumber": "INV-2024-001",  // Optional
    "description": "Payment for invoice INV-2024-001",
    "rows": [  // Optional detail rows
        {
            "ledgerId": 13201853,  // Receivable/Payable account
            "amount": 250.00
        }
    ]
}
```

### Key Assumptions & Uncertainties

1. **Main LedgerId = Bank Account**: The audit file states this, but we haven't seen the API spec confirm it
2. **Row Structure**: Payments might have rows like other mutations, but this isn't confirmed
3. **Available Fields**: We're assuming based on patterns, not API documentation

### What We Need to Validate

Before implementing, we should:
1. Test actual API responses for payment mutations
2. Verify the ledgerId really represents the bank account
3. Confirm what additional fields are available

## Quality-First Implementation Plan

### 1. API Discovery Phase (REQUIRED FIRST STEP)

```python
# verenigigen/utils/eboekhouden/payment_api_discovery.py
"""
Discovery tool to understand the actual E-Boekhouden payment API structure.
Run this BEFORE implementing the payment processor.
"""

import frappe
from frappe import _
from verenigigen.utils.eboekhouden.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

@frappe.whitelist()
def discover_payment_api_structure(sample_size=10):
    """
    Analyze real payment mutations to understand API structure.
    This will inform our implementation design.
    """
    iterator = EBoekhoudenRESTIterator()

    discoveries = {
        'type_3_structure': None,
        'type_4_structure': None,
        'ledger_analysis': {},
        'field_availability': {},
        'patterns_found': []
    }

    # Fetch sample payments of each type
    for payment_type in [3, 4]:
        mutations = iterator.fetch_mutations_by_type(
            mutation_type=payment_type,
            limit=sample_size
        )

        if mutations:
            # Analyze structure
            sample = mutations[0]
            discoveries[f'type_{payment_type}_structure'] = {
                'fields': list(sample.keys()),
                'has_rows': 'rows' in sample or 'Regels' in sample,
                'sample_data': sample
            }

            # Analyze ledger patterns
            for mutation in mutations:
                ledger_id = mutation.get('ledgerId')
                if ledger_id:
                    # Check what account this ledger maps to
                    mapping = frappe.db.get_value(
                        'E-Boekhouden Ledger Mapping',
                        {'ledger_id': ledger_id},
                        ['ledger_code', 'ledger_name', 'erpnext_account']
                    )

                    if mapping:
                        discoveries['ledger_analysis'][ledger_id] = {
                            'code': mapping[0],
                            'name': mapping[1],
                            'erpnext_account': mapping[2],
                            'is_bank': 'bank' in mapping[1].lower() or mapping[0] in ['10440', '10470', '10620']
                        }

            # Identify patterns
            if all(discoveries['ledger_analysis'].get(m.get('ledgerId'), {}).get('is_bank')
                   for m in mutations if m.get('ledgerId')):
                discoveries['patterns_found'].append('Main ledgerId appears to be bank account')

    return discoveries
```

### 2. Clean Implementation Without Legacy Baggage

```python
# payment_processing/payment_processor.py
"""
Clean payment processor implementation based on actual API capabilities.
No backward compatibility - pure quality focus.
"""

import frappe
from frappe import _
from typing import Dict, Optional, List
import json

class PaymentProcessor:
    """
    Payment processor that correctly handles E-Boekhouden payment mutations.

    Design Principles:
    1. API-first: Based on actual E-Boekhouden REST API structure
    2. No hardcoding: All accounts determined dynamically
    3. Fail-fast: Clear errors instead of wrong defaults
    4. Traceable: Every decision is logged
    """

    def __init__(self, company: str):
        self.company = company
        self.api_version = self._detect_api_version()

    def process_payment_mutation(self, mutation_data: Dict) -> Optional[frappe.Document]:
        """
        Process a payment mutation from E-Boekhouden.

        This is the ONLY way payments should be processed.
        No fallbacks to old methods.
        """
        # Validate we have required fields
        required_fields = ['id', 'type', 'date', 'amount', 'ledgerId']
        missing = [f for f in required_fields if f not in mutation_data]
        if missing:
            frappe.throw(
                f"Payment mutation missing required fields: {missing}. "
                f"This indicates an API change or incomplete data."
            )

        # Determine bank account from ledger
        bank_account = self._determine_bank_account(mutation_data)
        if not bank_account:
            frappe.throw(
                f"Cannot determine bank account for payment {mutation_data['id']}. "
                f"LedgerId {mutation_data.get('ledgerId')} has no mapping."
            )

        # Create payment with correct accounts
        return self._create_payment_entry(mutation_data, bank_account)

    def _determine_bank_account(self, mutation_data: Dict) -> Optional[str]:
        """
        Determine bank account from mutation data.

        Based on our understanding:
        1. Main ledgerId should map to a bank/cash account
        2. If not, check patterns in description
        3. If still not found, FAIL (no guessing)
        """
        ledger_id = mutation_data.get('ledgerId')

        # Primary method: Direct ledger mapping
        if ledger_id:
            result = frappe.db.sql("""
                SELECT
                    lm.erpnext_account,
                    a.account_type,
                    lm.ledger_code,
                    lm.ledger_name
                FROM `tabE-Boekhouden Ledger Mapping` lm
                JOIN `tabAccount` a ON a.name = lm.erpnext_account
                WHERE lm.ledger_id = %s
                AND a.company = %s
                LIMIT 1
            """, (ledger_id, self.company), as_dict=True)

            if result:
                account_data = result[0]

                # Verify this is actually a bank/cash account
                if account_data['account_type'] in ['Bank', 'Cash']:
                    frappe.logger().info(
                        f"Payment {mutation_data['id']}: "
                        f"Mapped ledger {ledger_id} to {account_data['erpnext_account']}"
                    )
                    return account_data['erpnext_account']
                else:
                    frappe.logger().warning(
                        f"Payment {mutation_data['id']}: "
                        f"Ledger {ledger_id} maps to {account_data['account_type']} account, not Bank/Cash"
                    )

        # Secondary method: Check if we have row data with bank info
        rows = mutation_data.get('rows') or mutation_data.get('Regels', [])
        if rows and len(rows) > 0:
            # Sometimes the bank account might be in the rows
            for row in rows:
                row_ledger = row.get('ledgerId')
                if row_ledger and row_ledger != ledger_id:
                    # Check if this row contains bank account
                    bank_account = self._check_ledger_for_bank_account(row_ledger)
                    if bank_account:
                        frappe.logger().info(
                            f"Payment {mutation_data['id']}: "
                            f"Found bank account in row ledger {row_ledger}"
                        )
                        return bank_account

        # No fallback - we don't guess
        return None

    def _create_payment_entry(self, mutation_data: Dict, bank_account: str) -> frappe.Document:
        """
        Create payment entry with proper accounts and party handling.
        """
        mutation_id = mutation_data['id']
        mutation_type = mutation_data['type']
        amount = frappe.utils.flt(mutation_data['amount'])
        posting_date = mutation_data['date']

        # Create payment entry
        pe = frappe.new_doc("Payment Entry")
        pe.company = self.company
        pe.posting_date = posting_date
        pe.payment_type = "Receive" if mutation_type == 3 else "Pay"

        # Set bank accounts correctly
        if pe.payment_type == "Receive":
            pe.paid_to = bank_account
            pe.received_amount = amount
        else:
            pe.paid_from = bank_account
            pe.paid_amount = amount

        # Handle party if present
        if mutation_data.get('relationId'):
            party_info = self._resolve_party(mutation_data['relationId'], pe.payment_type)
            if party_info:
                pe.party_type = party_info['party_type']
                pe.party = party_info['party']

                # Set the receivable/payable account
                if pe.payment_type == "Receive":
                    pe.paid_from = party_info['account']
                else:
                    pe.paid_to = party_info['account']

        # Set reference information
        pe.reference_no = mutation_data.get('invoiceNumber', f"EB-{mutation_id}")
        pe.reference_date = posting_date

        # E-Boekhouden tracking
        pe.eboekhouden_mutation_nr = str(mutation_id)
        pe.eboekhouden_api_version = self.api_version

        # Add comprehensive remarks for traceability
        pe.remarks = self._generate_payment_remarks(mutation_data, bank_account)

        # Save and submit
        pe.insert()
        pe.submit()

        # Attempt reconciliation if we have invoice info
        if mutation_data.get('invoiceNumber') and pe.party:
            self._attempt_reconciliation(pe, mutation_data)

        return pe
```

### 3. Quality Assurance & Validation

```python
# payment_processing/payment_validator.py
"""
Strict validation to ensure payment quality.
No silent failures or incorrect defaults.
"""

class PaymentValidator:
    """Validates payment data integrity before processing."""

    @staticmethod
    def validate_mutation_structure(mutation_data: Dict) -> Dict[str, Any]:
        """
        Validate mutation has expected structure based on API version.
        Returns validation result with specific issues.
        """
        issues = []
        warnings = []

        # Check mutation type
        if mutation_data.get('type') not in [3, 4]:
            issues.append(f"Invalid mutation type: {mutation_data.get('type')}. Expected 3 or 4.")

        # Check amount
        amount = mutation_data.get('amount')
        if not amount or float(amount) == 0:
            issues.append(f"Invalid amount: {amount}")

        # Check ledger mapping exists
        ledger_id = mutation_data.get('ledgerId')
        if ledger_id:
            has_mapping = frappe.db.exists(
                'E-Boekhouden Ledger Mapping',
                {'ledger_id': ledger_id}
            )
            if not has_mapping:
                issues.append(f"No mapping found for ledger {ledger_id}")
        else:
            issues.append("Missing ledgerId")

        # Check party resolution
        if mutation_data.get('relationId'):
            # Verify we can resolve this party
            party_exists = (
                frappe.db.exists('Customer', {'eboekhouden_relation_id': mutation_data['relationId']}) or
                frappe.db.exists('Supplier', {'eboekhouden_relation_id': mutation_data['relationId']})
            )
            if not party_exists:
                warnings.append(f"Party {mutation_data['relationId']} will need to be created")

        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'warnings': warnings
        }
```

### 4. API Version Detection & Handling

```python
# payment_processing/api_version_handler.py
"""
Handle different E-Boekhouden API versions/structures.
"""

class APIVersionHandler:
    """
    Detects and handles different API response structures.

    E-Boekhouden might have different field names or structures.
    This handler normalizes them for consistent processing.
    """

    @staticmethod
    def normalize_mutation_data(raw_mutation: Dict) -> Dict:
        """
        Normalize mutation data to standard structure.

        Handles variations like:
        - 'Regels' vs 'rows'
        - Different date formats
        - Field name variations
        """
        normalized = raw_mutation.copy()

        # Normalize row data
        if 'Regels' in normalized and 'rows' not in normalized:
            normalized['rows'] = normalized['Regels']

        # Ensure consistent date format
        if 'date' in normalized and 'T' in str(normalized['date']):
            normalized['date'] = normalized['date'].split('T')[0]

        # Add any other normalizations discovered during API discovery

        return normalized
```

### 5. Testing Strategy Based on Real API

```python
# tests/test_payment_api_integration.py
"""
Integration tests using real E-Boekhouden API responses.
"""

class TestPaymentAPIIntegration(FrappeTestCase):
    """Test with actual API responses, not mocked data."""

    def setUp(self):
        # First, run API discovery to understand structure
        self.api_structure = discover_payment_api_structure(sample_size=5)
        self.processor = PaymentProcessor(get_default_company())

    def test_actual_payment_structure(self):
        """Test that our assumptions about API structure are correct."""
        # Verify type 3 structure
        type_3 = self.api_structure.get('type_3_structure')
        self.assertIsNotNone(type_3, "No type 3 payments found in E-Boekhouden")

        if type_3:
            self.assertIn('ledgerId', type_3['fields'])
            self.assertIn('amount', type_3['fields'])
            self.assertIn('date', type_3['fields'])

    def test_ledger_to_bank_mapping(self):
        """Verify that payment ledgers actually map to bank accounts."""
        ledger_analysis = self.api_structure.get('ledger_analysis', {})

        bank_ledgers = [
            ledger_id for ledger_id, info in ledger_analysis.items()
            if info.get('is_bank')
        ]

        self.assertGreater(
            len(bank_ledgers), 0,
            "No bank account ledgers found in payment mutations"
        )

    def test_payment_processing_with_real_data(self):
        """Test processing with actual API response."""
        # Get a real payment mutation
        type_3_sample = self.api_structure.get('type_3_structure', {}).get('sample_data')

        if type_3_sample:
            # Process it
            payment = self.processor.process_payment_mutation(type_3_sample)

            # Verify correct bank account was used
            self.assertNotEqual(payment.paid_to, '10000 - Kas - NVV',
                              "Payment should not default to Kas account")
```

## Implementation Approach

### Phase 1: API Discovery (Day 1-2)
1. Run the discovery tool to understand actual API structure
2. Document findings and adjust plan if needed
3. Validate our assumptions about ledger mappings

### Phase 2: Core Implementation (Day 3-5)
1. Implement PaymentProcessor based on discovered API structure
2. Build strict validation (no silent failures)
3. Create comprehensive test suite

### Phase 3: Migration & Cleanup (Day 6-7)
1. Remove ALL old payment processing code
2. Update all entry points to use new processor
3. Run full test suite with real data

## Key Differences from Previous Plan

1. **API-First**: We acknowledge we don't have the full API spec and build discovery into the process
2. **No Assumptions**: We validate every assumption about the API structure
3. **No Backward Compatibility**: Clean implementation without legacy support
4. **Fail-Fast**: If we can't determine the correct bank account, we fail with a clear error
5. **Real Testing**: Tests use actual API responses, not mocked data

## Critical Success Factors

1. **API Discovery Results**: We must understand the actual API structure before implementing
2. **Ledger Mapping Completeness**: All payment ledgers must be mapped to bank accounts
3. **No Fallbacks**: If data is missing or unclear, fail with helpful errors rather than guessing

This approach ensures we build on solid understanding of the API rather than assumptions, resulting in a robust implementation that correctly handles payments.
