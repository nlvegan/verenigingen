# Donation Accounting Structure

## Overview

The Verenigingen app uses a standard nonprofit accounting structure for donations, following the principles of fund accounting. This ensures proper tracking and reporting of donor restrictions.

## Account Types

### 1. **Unrestricted Donation Account**
- **Purpose**: General donations without donor-imposed restrictions
- **Usage**: Can be used for any organizational purpose
- **Examples**:
  - General online donations
  - Unrestricted annual fund gifts
  - Donations where donor selects "where needed most"

### 2. **Campaign Donation Account**
- **Purpose**: Donations restricted to specific fundraising campaigns
- **Type**: Temporarily restricted funds
- **Usage**: Must be used for the designated campaign purpose
- **Examples**:
  - "Building renovation campaign"
  - "Annual holiday toy drive"
  - "Emergency relief fund for Ukraine"
- **Tracking**: Linked to Donation Campaign records

### 3. **Other Restricted Donation Account**
- **Purpose**: Donations with other donor-imposed restrictions (not campaigns)
- **Type**: Temporarily restricted funds
- **Usage**: Must be used according to donor specifications
- **Examples**:
  - "For youth programs only"
  - "Scholarship fund"
  - "Technology upgrades"
  - "Restricted to Amsterdam chapter"

## Key Differences

| Account Type | Restriction Level | Examples | Flexibility |
|--------------|-------------------|----------|-------------|
| Unrestricted | None | General donations | Full - any purpose |
| Campaign | Specific campaign | Building fund | Limited to campaign goal |
| Other Restricted | Donor-specified | "Youth only" | Limited to specification |

## How It Works

1. **During Donation Entry**:
   - If donation has no restrictions → Unrestricted account
   - If linked to a campaign → Campaign account
   - If other donor restrictions → Other Restricted account

2. **In Reports**:
   - Separate tracking for each fund type
   - Ensures compliance with donor intent
   - Required for proper financial reporting

3. **For ANBI Compliance**:
   - All donation types can qualify for tax benefits
   - Proper fund accounting demonstrates transparency
   - Required for Belastingdienst reporting

## Configuration

In **Verenigingen Settings**, under the ANBI section, you can configure:
- **Unrestricted Donation Account**: Your general donation income account
- **Campaign Donation Account**: Account for campaign-specific donations
- **Other Restricted Donation Account**: Account for other restricted purposes

These should be set up as Income accounts in your Chart of Accounts, typically under a structure like:
```
Income
├── Donation Income
│   ├── Unrestricted Donations
│   ├── Campaign Donations
│   └── Other Restricted Donations
```

## Best Practices

1. **Always respect donor intent** - use restricted funds only for stated purpose
2. **Track restrictions carefully** - maintain clear records
3. **Report separately** - show restricted vs unrestricted in financial statements
4. **Review regularly** - ensure temporary restrictions are released when fulfilled

This structure ensures compliance with both Dutch ANBI regulations and international nonprofit accounting standards.
