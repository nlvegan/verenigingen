# Dutch Compliance

Verenigingen is built specifically for Dutch non-profit associations and includes features for ANBI tax compliance, SEPA direct debit payment processing, integration with eBoekhouden (Dutch accounting software), and privacy/GDPR considerations.

## ANBI Compliance

### What is ANBI?

ANBI (Algemeen Nut Beogende Instelling) is a Dutch tax designation for public benefit organizations. Donations to ANBI-registered organizations are tax-deductible for the donor. This requires the organization to track specific information about donors and donations.

### How Verenigingen Supports ANBI

**Donor Records:**
- Each donor's ANBI consent is explicitly tracked with a consent date
- BSN (Burgerservicenummer) and RSIN tax identifiers are stored encrypted
- Only authorized roles (Verenigingen Admin, Donor Administrator, Finance Manager) can view decrypted tax identifiers
- Consent status is validated before applying ANBI treatment to donations

**Donation Records:**
- ANBI agreement number and date fields on each donation
- Validation ensures both fields are provided together (not one without the other)
- Periodic donation agreements can auto-populate ANBI fields on new donations
- Submitted donations with ANBI information are available for annual tax reporting

**Reporting:**
- Donation records can be filtered by ANBI status for Belastingdienst (Dutch tax authority) reporting
- Campaign-level financial summaries include ANBI-qualifying donation totals
- GL entries are created for proper accounting treatment

### Configuration

1. Ensure your organization's ANBI registration is current with the Belastingdienst
2. Set up ANBI agreement templates in `/app/verenigingen-settings`
3. Train staff on collecting donor ANBI consent
4. Configure role permissions so only authorized users can access BSN/RSIN data

## SEPA Direct Debit

### Overview

SEPA (Single Euro Payments Area) Direct Debit allows the association to collect payments directly from a member's or donor's bank account, with their written authorization (mandate).

Verenigingen manages the complete SEPA mandate lifecycle.

### SEPA Mandate Management

SEPA Mandates are managed at `/app/sepa-mandate`. Each mandate includes:

- **Mandate ID** (auto-generated in a format compliant with SEPA requirements)
- **Member** link
- **IBAN** (validated for format correctness)
- **Status**: Draft, Active, Suspended, Cancelled, Expired
- **Usage scope**: Can be marked for memberships, donations, or both
- **Signing date** and **expiry date**
- **Active flag** (synchronized with status)

### Mandate Lifecycle

1. **Creation**: A mandate is created when a member provides bank authorization. The mandate ID is auto-generated.

2. **Activation**: After verification, the mandate status is set to Active. The `is_active` flag is automatically synchronized.

3. **Usage**: Active mandates can be used for:
   - Membership fee collection (recurring dues)
   - Donation collection (one-time or periodic)
   - Combined usage for both purposes

4. **Suspension**: A mandate can be temporarily suspended (e.g., payment disputes). Direct debits are paused but the mandate is preserved.

5. **Expiry/Cancellation**: Mandates expire on their expiry date (automatic status update) or can be cancelled manually. Cancelled and expired mandates cannot be reactivated.

### IBAN Validation

The system validates IBAN numbers during mandate creation:
- Format validation (country code, check digits, BBAN structure)
- Dutch IBAN-specific validation (NL format)

IBAN changes on member records are tracked in the **Member IBAN History** for audit purposes.

### Mandate Usage Tracking

SEPA Mandate Usage records (`/app/sepa-mandate-usage`) track each time a mandate is used for a collection, providing a complete audit trail.

## eBoekhouden Integration

### What is eBoekhouden?

eBoekhouden is a popular Dutch online accounting software. Verenigingen provides a comprehensive integration for migrating from and synchronizing with eBoekhouden.

### Integration Components

The eBoekhouden module (`/app/e-boekhouden-settings`) provides:

**Account Migration:**
- Import chart of accounts from eBoekhouden into ERPNext
- Map eBoekhouden account types to ERPNext account types
- Handle Dutch account classification (balans/resultaat)
- Account hierarchy preservation

**Transaction Import:**
- Import invoices (purchase and sales)
- Import journal entries
- Import opening balances
- Import payment entries
- Bank transaction import and analysis

**Mapping Configuration:**
- **Account Mapping** (`/app/e-boekhouden-account-mapping`) - Map eBoekhouden accounts to ERPNext accounts
- **Ledger Mapping** (`/app/e-boekhouden-ledger-mapping`) - Map ledger codes
- **Cost Center Mapping** (`/app/e-boekhouden-cost-center-mapping`) - Map cost centers
- **Item Mapping** (`/app/e-boekhouden-item-mapping`) - Map items/products
- **Payment Mapping** (`/app/e-boekhouden-payment-mapping`) - Map payment methods
- **Group Type Mapping** (`/app/e-boekhouden-group-type-mapping`) - Map account group types

**Import Logging:**
- **Import Log** (`/app/e-boekhouden-import-log`) tracks every import operation with success/failure status
- **Migration Dashboard** (`/app/e-boekhouden-dashboard`) provides an overview of migration progress

**Party Management:**
- Party (customer/supplier) extraction from eBoekhouden transactions
- Party enrichment queue for batch processing
- Reconciliation of eBoekhouden relations with ERPNext customers/suppliers

### Migration Workflow

1. Configure connection settings in `/app/e-boekhouden-settings`
2. Set up account mappings using the mapping DocTypes
3. Run the account migration to import the chart of accounts
4. Import transactions (invoices, payments, journal entries)
5. Verify imported data using the dashboard and import logs
6. Reconcile balances between eBoekhouden and ERPNext

### REST API Client

The integration uses eBoekhouden's REST API for data retrieval. The client includes:
- Authenticated API access
- Paginated data retrieval
- Error handling and retry logic
- Rate limiting compliance

## Dutch Address and Name Support

### Dutch Name Formatting

Verenigingen supports Dutch naming conventions:

- **Tussenvoegsel** (name prefix like "van", "de", "van der") stored separately
- **Full name formatting** follows Dutch conventions (e.g., "Jan van der Berg")
- Proper alphabetical sorting by last name (ignoring tussenvoegsels)

### Dutch Address Normalization

The system includes a Dutch address normalizer that:

- Standardizes postal code format (1234 AB)
- Normalizes street names and suffixes
- Creates address fingerprints for duplicate detection
- Handles collision resolution for similar addresses

## Mollie Payment Integration

### Overview

Mollie is the leading Dutch payment service provider. Verenigingen integrates with Mollie for:

- **iDEAL** (Dutch online banking payments)
- **Credit/debit card** payments
- **Bancontact** and other European payment methods
- **SEPA Direct Debit** collection via Mollie

### Payment Flow

1. Member or donor initiates payment (membership fee or donation)
2. System creates a Mollie payment request
3. User is redirected to Mollie's payment page
4. After payment, Mollie sends a webhook callback
5. System verifies the payment and updates the relevant records

### Refund Handling

The Mollie integration includes refund processing:
- Per-refund-ID idempotency (prevents double refunds)
- Refund status tracking
- Automatic accounting entries for refunds

### Configuration

Configure Mollie at `/app/verenigingen-settings`:
- API key (test and live)
- Webhook URL
- Payment method preferences
- Days-back limit for payment lookups

## Privacy and GDPR

### Data Protection Measures

Verenigingen includes several privacy-focused features:

- **Encrypted storage** for sensitive data (BSN/RSIN tax identifiers)
- **Permission-level access** controls for sensitive fields
- **Anonymous donation** support for donors who wish not to be identified
- **Audit logging** for access to sensitive records
- **Member portal** allowing members to view and update their own data

### Data Retention

- Member records are preserved after termination for legal compliance
- Financial records follow Dutch retention requirements (7 years)
- Audit trails are maintained for all sensitive operations

### Consent Management

- ANBI consent is explicitly tracked with timestamp
- SEPA mandate authorization includes signing date
- Communication preferences can be managed per member

## Common Tasks

| Task | Where |
|------|-------|
| Manage SEPA mandates | `/app/sepa-mandate` |
| Configure eBoekhouden | `/app/e-boekhouden-settings` |
| View import logs | `/app/e-boekhouden-import-log` |
| Check migration status | `/app/e-boekhouden-dashboard` |
| Manage account mappings | `/app/e-boekhouden-account-mapping` |
| Configure Mollie | `/app/verenigingen-settings` |
| View donor ANBI consent | Open donor record, check ANBI fields |
| Track IBAN changes | `/app/member-iban-history` |
