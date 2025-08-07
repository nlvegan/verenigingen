# User Guide: eBoekhouden Cost Center Creation

## Overview

This guide explains how to use the eBoekhouden Cost Center Creation feature in ERPNext. This powerful feature allows you to automatically create cost centers in ERPNext based on your eBoekhouden account groups (rekeninggroepen).

## Prerequisites

Before using this feature, ensure you have:

1. **E-Boekhouden Settings** configured with a valid API token
2. **A Company** selected in the settings
3. **Account Group Mappings** entered in the text field
4. **System Manager** or **Verenigingen Administrator** role

## Step-by-Step Guide

### Step 1: Access E-Boekhouden Settings

1. Navigate to **E-Boekhouden Settings** in ERPNext
2. Ensure your API connection is working (look for "✅ Connection Successful")
3. Select your **Default Company**

### Step 2: Enter Account Group Mappings

In the **Account Group Mappings** field, enter your eBoekhouden account groups in the format:
```
code name
```

**Example:**
```
001 Vaste activa
055 Opbrengsten verkoop
056 Personeelskosten
060 Algemene kosten
070 Afschrijvingen
600 Kantoorkosten
```

**Important:**
- One account group per line
- Code and name separated by a space
- Use the exact format from your eBoekhouden system

### Step 3: Parse and Configure Cost Centers

1. Click the **"Parse Groups & Configure Cost Centers"** button
2. The system will analyze your account groups and suggest which should become cost centers
3. Review the suggestions in the table that appears:
   - ✅ Checkmark = Suggested for cost center creation
   - ❌ No checkmark = Not suitable for cost center (e.g., balance sheet items)
   - **Reason** column explains why each suggestion was made

### Step 4: Customize Configuration (Optional)

You can customize the suggested configuration:

1. **Toggle Creation**: Check/uncheck the "Create Cost Center" checkbox
2. **Edit Names**: Modify the "Cost Center Name" if desired
3. **Set Hierarchy**: Define parent cost centers for hierarchical structure
4. **Mark as Group**: Check "Is Group" for cost centers that will have children

### Step 5: Save Configuration

Click **"Save"** to store your cost center configuration. This saves your settings but does not yet create the cost centers.

### Step 6: Preview Cost Center Creation

1. After saving, new buttons appear: **"Preview Cost Center Creation"** and **"Create Cost Centers"**
2. Click **"Preview Cost Center Creation"** to see what will happen:
   - **Would Create**: New cost centers that will be created
   - **Would Skip**: Cost centers that already exist
   - Review the detailed preview table

### Step 7: Create Cost Centers

1. If the preview looks correct, click **"Create Cost Centers"**
2. Confirm the action in the dialog that appears
3. The system will create the cost centers and show results:
   - **Successfully Created**: New cost centers created
   - **Skipped**: Existing cost centers that were skipped
   - **Failed**: Any errors encountered (rare)

## Understanding the Intelligent Suggestions

The system uses Dutch accounting standards to make intelligent suggestions:

### Cost Centers ARE Suggested For:
- **Expense Groups (5xx, 6xx)**: Personnel costs, general expenses
- **Revenue Groups (3xx)**: Sales, income tracking
- **Operational Groups**: Containing keywords like "afdeling", "team", "project"
- **Cost-related Groups**: Containing "kosten", "uitgaven", "lasten"

### Cost Centers are NOT Suggested For:
- **Assets (1xx)**: Fixed assets, current assets
- **Liabilities (2xx)**: Debts, obligations
- **Balance Sheet Items**: Bank accounts, receivables, payables

## Tips and Best Practices

### 1. Start Small
Test with a few account groups first to understand the process

### 2. Use Preview
Always preview before creating to avoid surprises

### 3. Hierarchical Structure
Consider creating group cost centers for better organization:
- "Expenses" as a group
- Individual expense types as children

### 4. Naming Conventions
The system automatically cleans names, but you can customize:
- Original: "056 Personeelskosten rekeningen"
- Cleaned: "Personeelskosten"

### 5. Company Integration
Cost centers are automatically linked to your selected company

## Troubleshooting

### "No cost center mappings configured"
- Ensure you've clicked "Parse Groups & Configure Cost Centers" first
- Save the document after parsing

### "Default company not configured"
- Select a company in the Default Company field
- Save the settings

### Cost Center Already Exists
- The system automatically skips existing cost centers
- Check the "Skipped" section in results
- No action needed - this is normal behavior

### Permission Errors
- Ensure you have System Manager or Verenigingen Administrator role
- Check that you have permission to create Cost Centers

## Advanced Features

### Batch Processing
- Process hundreds of account groups at once
- Individual failures don't stop the batch
- Comprehensive reporting of all results

### Parent-Child Relationships
- Create hierarchical cost center structures
- Parent cost centers should be marked as "Is Group"
- System creates parents before children automatically

### Multi-Language Support
- Dutch account names are handled intelligently
- Keywords in Dutch trigger appropriate suggestions
- English ERPNext interface with Dutch data support

## Security and Safety

### Preview Before Creation
- Always preview changes before committing
- No cost centers are created during preview
- Safe to experiment with different configurations

### Duplicate Prevention
- System automatically detects existing cost centers
- Prevents accidental duplicates
- Shows exactly what exists in skip report

### Audit Trail
- All created cost centers include description with source
- Shows which eBoekhouden group it came from
- Includes the suggestion reasoning

## Frequently Asked Questions

### Q: Can I undo cost center creation?
A: Cost centers must be manually deleted if needed. Always use preview first.

### Q: What happens to existing cost centers?
A: They are automatically detected and skipped. No duplicates are created.

### Q: Can I run this multiple times?
A: Yes, the system safely handles multiple runs by skipping existing cost centers.

### Q: How are cost center IDs generated?
A: Format: "Cost Center Name - Company Name"

### Q: Can I use this with multiple companies?
A: Yes, select the appropriate company before creating cost centers.

## Next Steps

After creating cost centers:

1. **Assign Transactions**: Link transactions to appropriate cost centers
2. **Run Reports**: Use cost center-based financial reports
3. **Set Budgets**: Create budgets for cost centers (Phase 3 feature)
4. **Track Performance**: Monitor cost center utilization

## Support

For issues or questions:
- Check the error messages in the results dialog
- Review the skipped items for existing cost centers
- Ensure all prerequisites are met
- Contact your system administrator for permissions issues

---

This user guide covers the complete workflow for creating cost centers from eBoekhouden account groups. The intelligent automation saves hours of manual work while ensuring consistency and accuracy in your ERPNext cost center structure.
