# JavaScript/Jinja2 Template Mixing Inventory

## Overview
This document provides a comprehensive inventory of all instances where Jinja2 template variables (particularly translations) are mixed with JavaScript code in the Verenigingen codebase. This pattern causes syntax errors and should be replaced with Frappe's built-in JavaScript translation system.

## Pattern Categories

### 1. Translation Strings in JavaScript Functions
Pattern: `'{{ _("text") }}'` inside JavaScript strings

### 2. Template Variables in JavaScript
Pattern: `{{ variable }}` without proper escaping/defaults

### 3. Complex Template Expressions in JS
Pattern: `{{ _("text {0}").format(var) }}` in JavaScript contexts

## Files with Issues

### ALREADY FIXED:
1. **membership_fee_adjustment.html** - 8 instances fixed
2. **membership_application.html** - 9 instances fixed
3. **volunteer/expenses.html** - 4 instances fixed
4. **dues_schedule_admin.html** - 3 instances fixed

### TO BE FIXED:

#### 1. **batch-optimizer.html**
```javascript
frappe.msgprint('{{ _("Error loading invoice data") }}');
frappe.msgprint('{{ _("Error generating preview") }}');
frappe.msgprint(`{{ _("Error creating batches:") }} ${r.message.error || 'Unknown error'}`);
frappe.msgprint('{{ _("Error creating batches") }}');
```
**Count**: 5 instances

#### 2. **payment_dashboard.html**
```javascript
frappe.msgprint('{{ _("Downloading SEPA mandate document...") }}');
frappe.msgprint('{{ _("Receipt downloaded successfully") }}');
frappe.msgprint('{{ _("Payment history exported successfully") }}');
```
**Count**: 3 instances

#### 3. **address_change.html**
```javascript
$('#comparison-current').html(currentFormatted || '<em>{{ _("No address on file") }}</em>');
```
**Count**: 1 instance

#### 4. **auto_create_dues_schedules.html**
```javascript
$btn.prop('disabled', false).html('<i class="fa fa-play"></i> {{ _("Run Auto-Create Process") }}');
$btn.prop('disabled', false).html('<i class="fa fa-search"></i> {{ _("Check Members Without Schedules") }}');
$btn.prop('disabled', false).html('<i class="fa fa-check"></i> {{ _("Create Schedules for Selected Members") }}');
```
**Count**: 6 instances (duplicates for error handling)

#### 5. **address_change.html**
```javascript
$('#confirm-btn').prop('disabled', true).text('{{ _("Updating...") }}');
$('#confirm-btn').prop('disabled', false).text('{{ _("Confirm and Update") }}');
$('#comparison-current').html(currentFormatted || '<em>{{ _("No address on file") }}</em>');
```
**Count**: 3 instances

#### 6. **schedule_maintenance.html**
```javascript
$('#cleanup-confirmation-text').text(`{{ _("Are you sure you want to clean up") }} ${count} {{ _("schedules for") }} ${title}?`);
```
**Count**: 1 instance (template literal mixing)

#### 7. **my_dues_schedule.html**
```javascript
showMessage('{{ _("Schedule exported successfully") }}', 'success');
showMessage('{{ _("Failed to export schedule") }}', 'danger');
```
**Count**: 2 instances

#### 8. **financial_dashboard.html**
```javascript
showMessage('{{ _("Financial data exported successfully") }}', 'success');
showMessage('{{ _("Payment history exported successfully") }}', 'success');
showMessage('{{ _("All financial data exported successfully") }}', 'success');
showMessage('{{ _("Settings saved successfully") }}', 'success');
showMessage('{{ _("Failed to save settings") }}', 'error');
```
**Count**: 5 instances

#### 9. **contact_request.html**
```javascript
const errorMessage = result.message ? result.message.message : '{{ _("An error occurred") }}';
```
**Count**: 1 instance

#### 10. **eboekhouden_mapping_review.html**
```javascript
const defaultCompany = '{{ default_company }}';
const accountTypes = {{ account_types|tojson }};
```
**Count**: 2 instances (variable assignment)

#### 11. **eboekhouden_item_mapping.html**
```javascript
const defaultCompany = '{{ default_company }}';
const availableItems = {{ items | tojson }};
```
**Count**: 2 instances (variable assignment)

## Additional Patterns to Check

### Button Text Updates
```javascript
.text('{{ _("Submit") }}')
.html('{{ _("Processing...") }}')
```

### Alert Messages
```javascript
showMessage('{{ _("Success") }}', 'success')
show_alert('{{ _("Error") }}')
```

### Dynamic Content
```javascript
.attr('title', '{{ _("Help text") }}')
.attr('placeholder', '{{ _("Enter value") }}')
```

## Recommended Fix Pattern

### Before (Problematic):
```javascript
frappe.msgprint('{{ _("Error occurred") }}');
$btn.html('{{ _("Submit") }}');
```

### After (Correct):
```javascript
frappe.msgprint(__("Error occurred"));
$btn.html(__("Submit"));
```

## Search Commands for Finding More Issues

```bash
# Find frappe.msgprint with Jinja2
grep -r "frappe\.msgprint.*{{ _(" --include="*.html"

# Find jQuery .html() with Jinja2
grep -r "\.html(.*{{ _(" --include="*.html"

# Find jQuery .text() with Jinja2
grep -r "\.text(.*{{ _(" --include="*.html"

# Find showMessage with Jinja2
grep -r "showMessage.*{{ _(" --include="*.html"

# Find attribute setters with Jinja2
grep -r "\.attr(.*{{ _(" --include="*.html"

# Find template variables in JS contexts
grep -r "= *{{ [^_]" --include="*.html" | grep -E "(var|let|const|=)"
```

## Impact Assessment

### High Priority (Causes Runtime Errors):
- Files with `frappe.msgprint()` mixing
- Files with complex string concatenation
- Files with apostrophes in translations

### Medium Priority (Potential Issues):
- Simple button text updates
- Placeholder/title attributes
- Alert messages

### Low Priority (Works but not ideal):
- Simple numeric template variables with defaults
- Boolean template variables

## Summary Statistics

### TOTAL INSTANCES FOUND:
- **Already Fixed**: 24 instances across 4 files
- **Still To Fix**: 30+ instances across 11+ files

### Breakdown by Priority:

#### High Priority (Runtime Error Risk): 18 instances
- batch-optimizer.html: 5 instances
- payment_dashboard.html: 3 instances
- address_change.html: 3 instances
- schedule_maintenance.html: 1 instance (template literal)
- my_dues_schedule.html: 2 instances
- financial_dashboard.html: 5 instances
- contact_request.html: 1 instance

#### Medium Priority (Functional but problematic): 12 instances
- auto_create_dues_schedules.html: 6 instances
- eboekhouden_mapping_review.html: 2 instances
- eboekhouden_item_mapping.html: 2 instances
- Plus remaining instances in membership_fee_adjustment.html (already partially fixed)

#### Files Still Need Investigation:
- member_portal.html & member_portal_new.html
- volunteer/dashboard.html
- Any other HTML files with `<script>` blocks

## Next Steps

1. **URGENT**: Fix all high-priority files first (18 instances)
2. Replace Jinja2 translations with Frappe's `__()` function
3. Add proper defaults for template variables using `|default()` and `|tojson`
4. Test each file after fixing to ensure no JavaScript errors
5. Check remaining files not yet inventoried
6. Consider adding linting rules to prevent future mixing

## Estimated Work
- High priority fixes: ~2-3 hours
- Medium priority fixes: ~1-2 hours
- Complete inventory of remaining files: ~1 hour
- Testing and validation: ~1 hour
- **Total estimated effort**: 5-7 hours
