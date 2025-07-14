# Invoice Metadata Implementation Plan

## Current Issues
- Missing due dates and payment terms
- No reference numbers preserved
- Missing invoice descriptions
- No tracking of original document dates

## Implementation Strategy

### Step 1: Extract Additional Fields from E-Boekhouden

1. **REST API Fields to Extract**
   ```python
   def extract_invoice_metadata(mutation):
       """Extract all invoice-related metadata from e-boekhouden"""
       metadata = {
           # Basic info
           'invoice_number': mutation.get('factuurNummer') or mutation.get('invoiceNumber'),
           'invoice_date': mutation.get('factuurDatum') or mutation.get('invoiceDate'),
           'due_date': mutation.get('vervaldatum') or mutation.get('dueDate'),

           # Payment terms
           'payment_days': extract_payment_days(mutation),
           'payment_discount': mutation.get('kortingsPercentage'),

           # References
           'po_number': mutation.get('inkoopordernummer') or mutation.get('purchaseOrderNumber'),
           'reference': mutation.get('referentie') or mutation.get('reference'),
           'external_id': mutation.get('externId') or mutation.get('externalId'),

           # Description and notes
           'description': mutation.get('omschrijving') or mutation.get('description'),
           'notes': mutation.get('opmerkingen') or mutation.get('notes'),

           # Contact info
           'contact_person': mutation.get('contactpersoon'),
           'contact_email': mutation.get('email'),

           # Status
           'payment_status': mutation.get('betaalstatus') or mutation.get('paymentStatus'),
           'is_paid': mutation.get('isBetaald') or mutation.get('isPaid', False)
       }

       return {k: v for k, v in metadata.items() if v is not None}
   ```

2. **Calculate Payment Terms**
   ```python
   def extract_payment_days(mutation):
       """Calculate payment days from dates"""
       invoice_date = mutation.get('factuurDatum')
       due_date = mutation.get('vervaldatum')

       if invoice_date and due_date:
           delta = (due_date - invoice_date).days
           return max(0, delta)

       # Check for explicit payment terms
       return mutation.get('betalingstermijn') or 30
   ```

### Step 2: Map to ERPNext Fields

1. **Sales Invoice Mapping**
   ```python
   def apply_invoice_metadata(invoice, metadata):
       """Apply extracted metadata to ERPNext invoice"""

       # Basic fields
       if metadata.get('invoice_date'):
           invoice.posting_date = metadata['invoice_date']

       if metadata.get('due_date'):
           invoice.due_date = metadata['due_date']

       # Payment terms
       if metadata.get('payment_days'):
           payment_term = get_or_create_payment_term(metadata['payment_days'])
           invoice.payment_terms_template = payment_term

       # References
       if metadata.get('po_number'):
           invoice.po_no = metadata['po_number']

       if metadata.get('reference'):
           invoice.remarks = metadata.get('description', '')
           if metadata['reference']:
               invoice.remarks += f"\nReference: {metadata['reference']}"

       # Contact
       if metadata.get('contact_person'):
           invoice.contact_person = get_or_create_contact(
               metadata['contact_person'],
               metadata.get('contact_email'),
               invoice.customer
           )

       # Custom fields for e-boekhouden tracking
       invoice.custom_eboekhouden_invoice_number = metadata.get('invoice_number')
       invoice.custom_eboekhouden_external_id = metadata.get('external_id')
       invoice.custom_eboekhouden_paid_status = metadata.get('is_paid', False)
   ```

2. **Purchase Invoice Mapping**
   ```python
   def apply_purchase_invoice_metadata(pinv, metadata):
       """Similar to sales invoice but for purchase invoices"""
       apply_invoice_metadata(pinv, metadata)  # Base fields

       # Purchase-specific fields
       if metadata.get('invoice_number'):
           pinv.bill_no = metadata['invoice_number']

       if metadata.get('invoice_date'):
           pinv.bill_date = metadata['invoice_date']
   ```

### Step 3: Payment Terms Management

1. **Dynamic Payment Terms Creation**
   ```python
   def get_or_create_payment_term(days):
       """Get or create payment terms template"""
       name = f"Net {days}"

       if not frappe.db.exists("Payment Terms Template", name):
           template = frappe.new_doc("Payment Terms Template")
           template.template_name = name
           template.append("terms", {
               "due_date_based_on": "Day(s) after invoice date",
               "credit_days": days,
               "invoice_portion": 100
           })
           template.insert()

       return name
   ```

2. **Common Dutch Payment Terms**
   ```python
   STANDARD_PAYMENT_TERMS = {
       "8_dagen": {"days": 8, "description": "Netto 8 dagen"},
       "14_dagen": {"days": 14, "description": "Netto 14 dagen"},
       "30_dagen": {"days": 30, "description": "Netto 30 dagen"},
       "60_dagen": {"days": 60, "description": "Netto 60 dagen"},
       "2_10_30": {
           "description": "2% korting binnen 10 dagen, netto 30",
           "discount": 2,
           "discount_days": 10,
           "net_days": 30
       }
   }
   ```

### Step 4: Contact Management

1. **Auto-create Contacts**
   ```python
   def get_or_create_contact(name, email, party):
       """Create contact if it doesn't exist"""
       existing = frappe.db.get_value("Contact", {
           "email_id": email,
           "links": ["like", f"%{party}%"]
       })

       if existing:
           return existing

       contact = frappe.new_doc("Contact")
       contact.first_name = name
       contact.email_id = email
       contact.append("links", {
           "link_doctype": "Customer" if party else "Supplier",
           "link_name": party
       })
       contact.insert()

       return contact.name
   ```

### Step 5: Status Tracking

1. **Payment Status Sync**
   ```python
   def sync_payment_status(invoice_name, is_paid):
       """Update invoice status based on e-boekhouden"""
       invoice = frappe.get_doc("Sales Invoice", invoice_name)

       if is_paid and invoice.outstanding_amount > 0:
           # Create payment entry
           create_payment_from_eboekhouden(invoice)
       elif not is_paid and invoice.outstanding_amount == 0:
           # Log discrepancy
           frappe.log_error(
               f"Invoice {invoice_name} marked unpaid in e-boekhouden but paid in ERPNext",
               "E-Boekhouden Sync Discrepancy"
           )
   ```

2. **Metadata Preservation**
   - Store original e-boekhouden data in custom fields
   - Enable future reconciliation
   - Track import source and timestamp
