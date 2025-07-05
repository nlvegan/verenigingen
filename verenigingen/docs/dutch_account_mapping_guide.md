# Dutch to ERPNext Account Type Mapping Guide

## Common Mappings

### Balance Sheet Accounts

#### Assets (Activa)
| Dutch Term | ERPNext Account Type | Notes |
|------------|---------------------|-------|
| Liquide middelen | Cash | Physical cash |
| Kas | Cash | Cash box |
| Bank | Bank | Bank accounts |
| Bankrekening | Bank | Bank accounts |
| Spaarrekening | Bank | Savings accounts |
| Debiteuren | Receivable | Customer balances |
| Vorderingen | Receivable | Amounts owed to company |
| Te ontvangen | Receivable | To be received |
| Voorraad | Stock | Inventory |
| Inventaris | Fixed Asset | Equipment/furniture |
| Vaste activa | Fixed Asset | Fixed assets |
| Materiële vaste activa | Fixed Asset | Tangible fixed assets |

#### Liabilities (Passiva)
| Dutch Term | ERPNext Account Type | Notes |
|------------|---------------------|-------|
| Crediteuren | Payable | Supplier balances |
| Te betalen | Payable | To be paid |
| Schulden | Payable | Debts |
| Kortlopende schulden | Current Liability | Short-term debts |
| Langlopende schulden | Current Liability* | Long-term debts |
| Lening | Current Liability | Loans |
| Hypotheek | Current Liability | Mortgage |

*Note: ERPNext doesn't have a separate "Long-term Liability" type

#### Equity (Eigen Vermogen)
| Dutch Term | ERPNext Account Type | Notes |
|------------|---------------------|-------|
| Eigen vermogen | Equity | Owner's equity |
| Kapitaal | Equity | Capital |
| Algemene reserve | Equity | General reserve |
| Winstreserve | Equity | Profit reserve |
| Ingehouden winst | Equity | Retained earnings |
| Resultaat | Equity | Current year result |

### Income Statement Accounts

#### Income (Opbrengsten)
| Dutch Term | ERPNext Account Type | Notes |
|------------|---------------------|-------|
| Omzet | Income | Revenue/Sales |
| Opbrengsten | Income | Income/Revenue |
| Verkoop | Income | Sales |
| Inkomsten | Income | Income |
| Contributie | Income | Membership fees |
| Donaties | Income | Donations |

#### Expenses (Kosten)
| Dutch Term | ERPNext Account Type | Notes |
|------------|---------------------|-------|
| Kosten | Expense | Costs/Expenses |
| Uitgaven | Expense | Expenditures |
| Inkoop | Expense | Purchases |
| Personeelskosten | Expense | Personnel costs |
| Lonen | Expense | Wages |
| Salarissen | Expense | Salaries |
| Huur | Expense | Rent |
| Afschrijving | Depreciation | Depreciation |

### Special Accounts

| Dutch Term | ERPNext Account Type | Notes |
|------------|---------------------|-------|
| BTW | Tax | VAT accounts |
| Omzetbelasting | Tax | Sales tax |
| Loonbelasting | Tax | Payroll tax |
| Tussenrekening | Temporary | Interim accounts |
| Kruispost | Temporary | Cross-entry accounts |

## E-Boekhouden Group Codes

Common group code patterns:

- **00x**: Usually Eigen Vermogen (Equity)
- **01x**: Usually Vaste Activa (Fixed Assets)
- **02x**: Usually Vlottende Activa (Current Assets)
- **10x**: Usually Liquide Middelen (Cash/Bank)
- **12x**: Usually Debiteuren (Receivables)
- **20x**: Usually Crediteuren (Payables)
- **40x**: Usually Omzet (Income)
- **60x-70x**: Usually Kosten (Expenses)

## Important Notes

1. **Receivable/Payable Accounts**: These require party (customer/supplier) information in journal entries
2. **Root Types**: ERPNext automatically determines root type based on account type
3. **Tax Accounts**: BTW accounts should be mapped as "Tax" type
4. **Verenigingen Specific**: For associations, "Contributie" (membership fees) should be Income
