# E-Boekhouden Migration Redesign Proposal

## Current Problems
1. Too many checkboxes that are actually mandatory
2. Confusing "Dry Run" as a checkbox instead of action
3. No mutation ID tracking for preventing duplicates
4. Unclear when to use which options

## Proposed Solution

### Migration Types (Radio Buttons, not checkboxes)

#### 1. **Full Initial Migration** (Recommended for first time)
- Automatically imports:
  - ✓ Chart of Accounts
  - ✓ All Customers/Suppliers
  - ✓ All historical transactions
  - ✓ Opening balances
- Date range: Automatically determined from E-Boekhouden
- Creates mutation ID tracking

#### 2. **Transaction Update** (For regular updates)
- Only imports new transactions
- Requires date range selection
- Skips transactions already imported (by mutation ID)
- Updates related customers/suppliers if needed

#### 3. **Preview Mode** (Test run)
- Shows what would be imported
- No actual changes made
- Helps verify settings

### UI Mockup
```
┌─────────────────────────────────────────────────┐
│ E-Boekhouden Migration                          │
├─────────────────────────────────────────────────┤
│                                                 │
│ Migration Type:                                 │
│ ○ Full Initial Migration (First time setup)    │
│ ● Transaction Update (Import new transactions)  │
│ ○ Preview Mode (Test without importing)        │
│                                                 │
│ Date Range: [Required for Transaction Update]   │
│ From: [2024-01-01] To: [2024-12-31]           │
│                                                 │
│ [Start Migration] [View History]                │
│                                                 │
└─────────────────────────────────────────────────┘
```

### Benefits
1. **Clearer**: Users know exactly what each option does
2. **Safer**: Mutation IDs prevent duplicate imports
3. **Simpler**: No confusing optional checkboxes
4. **Smarter**: System handles dependencies automatically

### Implementation Steps
1. Add mutation ID fields to Journal Entry, Invoice doctypes
2. Update migration logic to track mutation IDs
3. Simplify the UI to radio buttons
4. Auto-detect if this is first migration or update

### Post-Migration Tools (Keep as is)
- Map Account Types ✓
- Fix missing party information
- View migration history

## Code Changes Needed

1. **Add Custom Fields**:
   - Journal Entry: `eboekhouden_mutation_id`
   - Sales/Purchase Invoice: `eboekhouden_invoice_number`
   - Payment Entry: `eboekhouden_mutation_id`

2. **Update Migration Logic**:
   - Check for existing mutation IDs before importing
   - Store mutation IDs when creating entries
   - Better dependency handling

3. **Simplify UI**:
   - Replace checkboxes with radio buttons
   - Remove "Dry Run" checkbox (make it an action)
   - Add smart date range detection
