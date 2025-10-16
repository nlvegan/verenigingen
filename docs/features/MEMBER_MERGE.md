# Member Merge Feature

## Overview

The Member Merge feature allows administrators to consolidate duplicate member records by selectively merging identity and contact data while preserving complex financial and volunteer relationships.

## User Interface

### Accessing Merge

1. Navigate to **Member List View**
2. Select 2+ members using checkboxes
3. Click **Actions** → **Merge Members**
4. If more than 2 selected, choose which 2 to merge

### Merge Dialog Workflow

1. **Source/Target Selection**
   - **Target**: The member record to KEEP (receives merged data)
   - **Source**: The member record to DELETE (after data extraction)

2. **Field-by-Field Selection**
   - Visual side-by-side comparison of all mergeable fields
   - Smart defaults pre-selected (populated fields preferred over empty)
   - Conflicts highlighted in yellow with warning badges
   - Radio buttons to choose source or target value for each field

3. **Warnings Display**
   - Active memberships on source
   - Unpaid invoices
   - Volunteer records
   - User account conflicts
   - Customer record conflicts

4. **Confirmation**
   - Final confirmation before merge execution
   - Clear warning that source will be deleted

## What Gets Merged

### Mergeable Fields (Identity & Contact Data)

**Identity:**
- `first_name`, `middle_name`, `tussenvoegsel`, `last_name`
- `full_name`, `pronouns`, `aanhef`

**Contact:**
- `email` (secondary email saved to Contact if both populated)
- `contact_number`
- `primary_address` (link updated, not merged)

**Personal:**
- `birth_date`, `age`, `image`

**Preferences:**
- `accepts_optional_communications`
- `permission_category`

**Notes:**
- `notes`

### What Does NOT Get Merged

**Financial Data** (remains on original records):
- Payment methods (IBAN, Mollie, credit card)
- Payment history, SEPA mandates
- Sales invoices, dues schedules
- Customer records (deleted if no invoices)

**Membership Data:**
- Membership plans, status, dates
- Application history

**Volunteer & ERPNext Links:**
- Volunteer record
- Employee record
- User account
- Contact record (used for secondary emails)

## Technical Implementation

### Backend Service

**Location:** `verenigingen/services/member_merge_service.py`

**Key Classes:**
- `MemberMergeService`: Main merge logic
  - `get_merge_preview()`: Generates field comparison with smart defaults
  - `execute_merge()`: Performs actual merge with user selections
  - `_check_merge_conflicts()`: Validates and warns about conflicts
  - `_add_secondary_emails()`: Saves displaced email to Contact

**API Endpoints:**
```python
@frappe.whitelist()
def get_merge_preview(source_name: str, target_name: str)

@frappe.whitelist()
def execute_merge(source_name: str, target_name: str, field_selections: dict)
```

### Frontend Implementation

**Location:** `verenigingen/verenigingen/doctype/member/member_list.js`

**Key Functions:**
- `add_merge_members_action()`: Adds bulk action to list view
- `show_source_target_picker()`: Initial dialog for 2 selected members
- `show_member_selection_dialog()`: Picker when >2 selected
- `show_merge_dialog()`: Loads preview from backend
- `render_merge_dialog()`: Renders field-by-field selection UI
- `execute_merge()`: Calls backend API and handles result

### Security & Permissions

- Requires **write permission** on both source and target members
- No permission bypasses
- Audit trail via comment on target record
- Error logging for Customer deletion failures

## Merge Process

1. **Validation**
   - Verify write permissions on both members
   - Check for financial/volunteer conflicts
   - Generate warnings

2. **Data Transfer**
   - Apply user's field selections to target
   - Track all changes for audit trail
   - Save secondary emails to Contact if applicable

3. **Cleanup**
   - Delete source's Customer record (if no invoices)
   - Delete source Member record
   - Add merge comment to target with change summary

4. **Confirmation**
   - Show success message with change count
   - Refresh list view
   - Navigate to merged member form

## Testing

**Test Suite:** `verenigingen/tests/test_member_merge.py`

**Coverage:**
- Merge preview generation with conflict detection
- Field selection and smart defaults
- Email preservation in Contact records
- Warning generation for financial conflicts
- Permission checks
- Customer deletion handling

**Run Tests:**
```bash
bench --site dev.veganisme.net run-tests --module verenigingen.tests.test_member_merge
```

## Common Use Cases

### Case 1: Duplicate from Data Entry Error
- Member entered twice with slightly different names
- **Merge**: Identity fields from correct entry, contact from both
- **Result**: Clean single record, no data loss

### Case 2: Member with Multiple Accounts
- Same person signed up twice online
- **Warning**: May have multiple membership plans
- **Merge**: Choose newer account as target, extract contact from older
- **Result**: Single account, manual cleanup of extra membership

### Case 3: Name Change After Marriage
- Member record under maiden name, new under married name
- **Merge**: New name as target, historical data from old
- **Result**: Current name with full history

## Limitations

1. **No Cascade Merge**: Linked records (Customer, User, Volunteer) NOT automatically merged
2. **Financial Data Stays Put**: Invoices remain linked to original Customer
3. **Manual Cleanup May Be Needed**: User accounts, volunteer records need manual transfer if desired
4. **No Undo**: Merge is permanent (source deleted)
5. **Two Members Only**: Can only merge 2 members at a time

## Future Enhancements

Potential future improvements:
- Batch merge of multiple duplicates
- Smart duplicate detection and suggestions
- Optional Customer/Invoice consolidation
- Merge preview before commit
- Rollback/undo capability
- Volunteer record transfer

## Best Practices

1. **Review Before Merging**: Check financial status of both members
2. **Choose Target Carefully**: Usually newer/more complete record
3. **Note Financial History**: Document which Customer has invoices
4. **Manual Cleanup**: Transfer User/Volunteer links if needed after merge
5. **Use Audit Trail**: Check target's comments for merge history

## Troubleshooting

**Issue**: Merge fails with "Customer has invoices"
- **Solution**: Customer with invoices is preserved, member deleted successfully

**Issue**: User account not transferred
- **Solution**: Manual transfer required for security. Use User record to change linked member.

**Issue**: Secondary email not showing in Contact
- **Solution**: Check target had Contact record before merge. Create Contact manually if needed.

**Issue**: Volunteer record still points to deleted member
- **Solution**: Update Volunteer.member field manually to target member.

## Related Documentation

- Member DocType: `verenigingen/doctype/member/member.py`
- Enhanced Test Factory: For creating test data
- Account Creation System: For User account management

## Version History

- **v1.0.0** (2025-10-16): Initial implementation with field-level merge
