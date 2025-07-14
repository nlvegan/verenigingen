# VAT/BTW Tax Handling Implementation Plan

## Step 1: Analyze E-Boekhouden Tax Data Structure

### API Fields to Extract:
- `vatAmount` - BTW amount
- `vatPercentage` - BTW percentage (0%, 9%, 21%)
- `vatCode` - BTW code for categorization
- `vatInclusive` - Whether amount includes VAT

### Implementation Tasks:

1. **Extend REST API Data Extraction**
   ```python
   # In eboekhouden_rest_iterator.py
   def extract_vat_data(mutation):
       return {
           'vat_amount': mutation.get('vatAmount', 0),
           'vat_rate': mutation.get('vatPercentage', 0),
           'vat_code': mutation.get('vatCode', ''),
           'vat_inclusive': mutation.get('vatInclusive', False)
       }
   ```

2. **Create VAT Account Mapping DocType**
   - Fields: VAT Code, VAT Rate, ERPNext Tax Account, Description
   - Pre-populate with Dutch standard rates:
     - 0% - Vrijgesteld van BTW
     - 9% - BTW Laag tarief
     - 21% - BTW Hoog tarief

3. **Modify Invoice Creation Logic**
   ```python
   def add_tax_lines_to_invoice(invoice, vat_data):
       if vat_data.get('vat_amount'):
           tax_account = get_tax_account_for_rate(vat_data['vat_rate'])
           invoice.append('taxes', {
               'charge_type': 'Actual',
               'account_head': tax_account,
               'tax_amount': vat_data['vat_amount'],
               'description': f"BTW {vat_data['vat_rate']}%",
               'rate': 0  # Using actual amount
           })
   ```

4. **Handle Inclusive/Exclusive VAT**
   - If inclusive: Extract VAT from total
   - If exclusive: Add VAT to net amount

## Step 2: Create Tax Templates

1. **Sales Tax Templates**
   - BTW 21% Verkoop
   - BTW 9% Verkoop
   - BTW 0% Verkoop
   - BTW Verlegd

2. **Purchase Tax Templates**
   - BTW 21% Inkoop
   - BTW 9% Inkoop
   - BTW 0% Inkoop
   - BTW EU Inkoop

## Step 3: Testing Requirements

- Test invoices with different VAT rates
- Test inclusive vs exclusive VAT
- Verify VAT reports match e-boekhouden
- Test reverse charge scenarios
