# Multi-line Item Support Implementation Plan

## Current Issue
E-boekhouden invoices are reduced to single line items, losing all detail.

## Implementation Steps

### Step 1: Analyze E-Boekhouden Line Item Structure

Check REST API for:
- `lines` array in mutation object
- Individual line item fields: description, amount, account, VAT

### Step 2: Create Item Mapping System

1. **Item Mapping DocType**
   ```python
   # Fields:
   - eboekhouden_account_code
   - eboekhouden_description_pattern (regex)
   - erpnext_item_code
   - default_income_account
   - default_expense_account
   ```

2. **Item Matching Logic**
   ```python
   def get_or_create_item_for_line(line_data):
       # First try exact mapping
       mapping = frappe.db.get_value('Item Mapping', {
           'eboekhouden_account_code': line_data.get('accountCode')
       })

       if mapping:
           return mapping.erpnext_item_code

       # Try pattern matching on description
       for pattern in get_description_patterns():
           if re.match(pattern.regex, line_data.get('description', '')):
               return pattern.item_code

       # Create new item if needed
       return create_item_from_line(line_data)
   ```

### Step 3: Modify Invoice Creation

1. **Parse Line Items from E-Boekhouden**
   ```python
   def extract_invoice_lines(mutation):
       lines = []

       # Check if mutation has line items array
       if 'lines' in mutation:
           for line in mutation['lines']:
               lines.append({
                   'description': line.get('description'),
                   'amount': abs(line.get('amount', 0)),
                   'account': line.get('accountCode'),
                   'vat_rate': line.get('vatRate', 0)
               })
       else:
           # Fallback to single line from mutation
           lines.append({
               'description': mutation.get('description'),
               'amount': abs(mutation.get('amount', 0)),
               'account': mutation.get('accountCode'),
               'vat_rate': extract_vat_rate(mutation)
           })

       return lines
   ```

2. **Create Multiple Invoice Items**
   ```python
   def add_items_to_invoice(invoice, lines, is_purchase=False):
       for line in lines:
           item_code = get_or_create_item_for_line(line)
           account = get_account_for_item(item_code, is_purchase)

           invoice.append('items', {
               'item_code': item_code,
               'description': line['description'],
               'qty': 1,
               'rate': line['amount'],
               'income_account': account if not is_purchase else None,
               'expense_account': account if is_purchase else None
           })
   ```

### Step 4: Handle Special Cases

1. **Discount Lines**
   - Detect negative amounts
   - Add as discount items or adjust totals

2. **Shipping/Handling**
   - Map to specific service items
   - Use standard accounts

3. **Rounding Differences**
   - Add as separate line if needed
   - Track for reconciliation
