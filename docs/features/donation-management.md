# Donation Management

Verenigingen includes a full donation management system with ANBI compliance for Dutch tax-deductible donations, campaign tracking, and donor relationship management.

## Core Concepts

### Donations

The Donation DocType (`/app/donation`) records individual gifts to the association. Each donation tracks:

- **Donor** (link to Donor record)
- **Amount** and currency
- **Donation date**
- **Payment method** (bank transfer, SEPA direct debit, Mollie online payment, etc.)
- **Campaign** (optional link to a Donation Campaign)
- **Donation purpose** and category
- **ANBI agreement** fields for tax-deductible donations
- **Periodic donation agreement** reference for recurring gifts
- **Paid status** (whether the donation has been received)
- **Anonymous flag** (for donors who wish to remain unnamed)

Donations are submittable documents. Once submitted, they contribute to campaign progress and financial reporting.

### Donors

The Donor DocType (`/app/donor`) manages the relationship with each person or organization that donates. Key fields:

- **Donor name** and contact information
- **Email address** (used for automatic donor lookup)
- **ANBI consent** flag and consent date
- **BSN/RSIN** tax identifiers (encrypted at rest, visible only to authorized roles)
- **Address and contact** integration via Frappe's standard address system

When a website user makes a donation without an existing donor record, the system automatically creates one based on their user profile.

**Privacy**: Donor tax identifiers (BSN/RSIN) are encrypted before storage. Only users with Verenigingen Admin, Donor Administrator, or Finance Manager roles can view decrypted values.

### Donation Campaigns

Donation Campaigns (`/app/donation-campaign`) let you organize fundraising efforts around specific goals. Each campaign includes:

- **Campaign name** and description
- **Campaign type** (e.g., Project Funding, Annual Appeal)
- **Date range** (start and end dates)
- **Monetary goal** and donor goal
- **Progress tracking** (automatically updated from linked donations)
- **Website visibility** settings for public campaigns
- **Project link** for project-based campaigns
- **Accounting dimension** (auto-generated for financial reporting)

## How Donations Work

### Making a Donation

**Website donations**: Visitors can donate through the public donation form. The system:
1. Identifies the donor by email (creates a new Donor record if needed)
2. Validates payment method and ANBI requirements
3. Processes payment through the configured payment gateway (Mollie)
4. Records the donation and updates campaign progress

**Administrative entry**: Staff can create donations manually at `/app/donation/new`. Select the donor, enter the amount and details, and submit.

### Payment Processing

Donations can be processed through several payment methods:

- **Mollie** (iDEAL, credit card, Bancontact, and other Dutch payment methods)
- **SEPA Direct Debit** (for recurring donations linked to a SEPA mandate)
- **Bank transfer** (manual reconciliation)

For online payments, the Mollie integration handles the payment flow and webhook callbacks to confirm payment status. See [Dutch Compliance](dutch-compliance.md) for SEPA details.

### Periodic Donations

Members and donors can set up recurring donation agreements. When a periodic donation agreement is active:

- The system validates that the agreement is current
- Donations reference the agreement for tracking
- SEPA mandates can be used for automated collection

## ANBI Compliance

ANBI (Algemeen Nut Beogende Instelling) is the Dutch designation for public benefit organizations. Donations to ANBI organizations are tax-deductible for the donor.

### How It Works

1. **Donor consent**: The donor must give explicit ANBI consent on their Donor record. The consent date is automatically recorded.

2. **Agreement tracking**: Each tax-deductible donation can reference an ANBI agreement number and date. These fields are validated together (both must be provided or neither).

3. **Auto-population**: When a periodic donation agreement exists with ANBI fields, new donations automatically inherit the agreement number and date.

4. **Tax reporting**: Donation records with ANBI information can be exported for annual tax reporting to the Belastingdienst (Dutch tax authority).

### Configuration

To enable ANBI features:
- Ensure your organization's ANBI registration is current
- Set up ANBI agreement templates in Verenigingen Settings
- Train staff on when to apply ANBI fields to donations

## Campaign Management

### Creating a Campaign

1. Navigate to `/app/donation-campaign/new`
2. Enter the campaign name, type, and date range
3. Set monetary and/or donor goals
4. Optionally enable website visibility for public fundraising
5. Save the campaign

The system auto-generates an accounting dimension value from the campaign name for financial reporting.

### Tracking Progress

Campaign progress updates automatically when donations are created or modified:

- **Total raised** and **total donations** count
- **Unique donor count** (excluding anonymous donations)
- **Average donation amount**
- **Monetary progress** (percentage toward goal)
- **Donor progress** (percentage toward donor goal)

View progress on the campaign record or through the donation dashboard.

### Campaign Projects

For campaigns that involve expenses (events, marketing, etc.), you can link a Project:

1. Open the campaign record
2. Click "Create Project" to generate a linked ERPNext Project
3. Track tasks and expenses against the project
4. View the combined income/expense summary on the campaign

## Donor Management

### Donor Lookup

The system provides several ways to find donors:

- **By email**: The canonical lookup method, used during website donations
- **By name**: Search at `/app/donor`
- **By donation history**: Filter donations to find specific donors

### Member-Donor Integration

Members who also donate are linked through the member-donor integration service. This allows:

- Viewing a member's complete donation history
- Consolidating financial records for a single person
- Applying SEPA mandates to both membership fees and donations

### Anonymous Donations

Donors can choose to remain anonymous. Anonymous donations:

- Are excluded from public donor lists on campaigns
- Still have a Donor record for internal tracking
- Are included in financial totals but not donor counts

## Reporting

### Donation Dashboard

Access the donation dashboard for an overview of:

- Recent donations and trends
- Campaign performance
- Donor statistics
- Financial summaries

### Financial Integration

Donations integrate with ERPNext's accounting system:

- GL entries are created for submitted donations
- Campaign accounting dimensions enable cost tracking per campaign
- Donation reports can be filtered by date range, campaign, and donor

## Common Tasks

| Task | Where |
|------|-------|
| Record a new donation | `/app/donation/new` |
| View all donations | `/app/donation` |
| Create a campaign | `/app/donation-campaign/new` |
| View campaign progress | `/app/donation-campaign/CAMPAIGN-NAME` |
| Manage donors | `/app/donor` |
| Check ANBI consent | Open donor record, check ANBI Consent field |
| View donation history for a donor | `/app/donation?donor=DONOR-NAME` |
