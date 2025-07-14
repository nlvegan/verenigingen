# Account Mapping Improvements Implementation Plan

## Current Issues
- Hardcoded account mappings
- No validation of mapped accounts
- Missing many account categories
- No UI for managing mappings

## Implementation Strategy

### Step 1: Create Account Mapping DocType

1. **E-Boekhouden Account Mapping DocType**
   ```
   Fields:
   - eboekhouden_account_code (Data, unique)
   - eboekhouden_account_name (Data)
   - account_type (Select: Asset/Liability/Income/Expense/Equity)
   - erpnext_account (Link to Account)
   - is_tax_account (Check)
   - tax_rate (Percent, depends on is_tax_account)
   - mapping_confidence (Select: High/Medium/Low/Manual)
   - auto_mapped (Check)
   - notes (Small Text)
   ```

2. **Validation Logic**
   ```python
   def validate(self):
       # Ensure ERPNext account matches expected type
       if self.erpnext_account:
           account_type = frappe.db.get_value('Account',
               self.erpnext_account, 'root_type')

           if not self.matches_account_type(account_type):
               frappe.throw(_("Account type mismatch"))

       # Validate tax accounts
       if self.is_tax_account and not self.tax_rate:
           frappe.throw(_("Tax rate required for tax accounts"))
   ```

### Step 2: Auto-Mapping Algorithm

1. **Pattern-Based Mapping**
   ```python
   ACCOUNT_PATTERNS = {
       'bank': {
           'patterns': ['bank', '1100', '1110'],
           'account_type': 'Asset',
           'parent': 'Bank Accounts'
       },
       'accounts_receivable': {
           'patterns': ['1300', 'debiteur', 'receivable'],
           'account_type': 'Asset',
           'parent': 'Accounts Receivable'
       },
       'vat_payable': {
           'patterns': ['1600', 'btw', 'vat'],
           'account_type': 'Liability',
           'is_tax': True
       },
       'sales': {
           'patterns': ['8000', 'opbrengst', 'revenue'],
           'account_type': 'Income',
           'parent': 'Sales'
       }
   }

   def auto_map_accounts(ebh_accounts):
       for ebh_account in ebh_accounts:
           mapping = find_best_match(ebh_account)
           if mapping['confidence'] > 70:
               create_account_mapping(ebh_account, mapping)
   ```

2. **Smart Account Creation**
   ```python
   def get_or_create_account(ebh_account_code):
       # Check existing mapping
       mapping = frappe.db.get_value('E-Boekhouden Account Mapping',
           {'eboekhouden_account_code': ebh_account_code})

       if mapping:
           return mapping.erpnext_account

       # Try auto-mapping
       auto_map = suggest_account_mapping(ebh_account_code)

       if auto_map['confidence'] > 85:
           return auto_map['account']

       # Create new account with smart defaults
       return create_account_from_ebh(ebh_account_code)
   ```

### Step 3: UI for Mapping Management

1. **Mapping Review Page**
   - List view of all mappings
   - Confidence indicators
   - Bulk mapping actions
   - Import/export mappings

2. **Mapping Wizard**
   ```javascript
   frappe.pages['account-mapping-wizard'] = {
       refresh: function(wrapper) {
           // Show unmapped accounts
           // Suggest matches
           // Allow manual selection
           // Bulk operations
       }
   }
   ```

### Step 4: Integration with Import Process

1. **Pre-Import Validation**
   ```python
   def validate_account_mappings(company):
       unmapped = get_unmapped_accounts(company)

       if unmapped:
           return {
               'status': 'warning',
               'unmapped_accounts': unmapped,
               'message': _('Please map {0} accounts before import')
                   .format(len(unmapped))
           }

       return {'status': 'success'}
   ```

2. **Dynamic Mapping During Import**
   ```python
   def get_account_for_transaction(transaction, company):
       account_code = transaction.get('accountCode')

       # Try mapping first
       mapped_account = get_mapped_account(account_code, company)
       if mapped_account:
           return mapped_account

       # Queue for manual mapping
       create_mapping_request(account_code, transaction)

       # Return suspense account
       return get_suspense_account(company)
   ```

### Step 5: Standard Dutch Chart of Accounts

1. **Pre-configured Mappings**
   - Load standard Dutch accounting codes
   - Map to ERPNext standard accounts
   - Include common variations

2. **Industry Templates**
   - Retail template
   - Service business template
   - Non-profit template
   - Manufacturing template
