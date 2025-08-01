# Frappe HTML Field Handling Guide

## Overview

This guide documents the solution for displaying data in Frappe HTML fields, particularly for the "Other Members at Same Address" functionality in the Member doctype. HTML fields in Frappe have unique characteristics that require special handling.

## The Challenge: HTML Fields Don't Persist

### Key Understanding
HTML fields in Frappe are **display-only** fields that:
- Do not persist to the database
- Cannot be accessed as regular attributes on document objects
- Are meant for dynamic content display in forms
- Must be populated through JavaScript or special server-side methods

### The Problem
```python
# ❌ This doesn't work
member = frappe.get_doc("Member", "MEM-001")
member.other_members_at_address = "<div>HTML content</div>"
member.save()  # HTML field content is NOT saved!

# ❌ This causes AttributeError
if member.other_members_at_address:  # Field doesn't exist as attribute!
    print(member.other_members_at_address)
```

## The Solution: Using onload() and set_onload()

### Server-Side: Preparing Data for Frontend

The solution uses Frappe's `onload()` method and `set_onload()` to send HTML content to the frontend:

```python
# In Member doctype (member.py)
def onload(self):
    """Called when the document is loaded in the frontend"""
    # Generate or retrieve HTML content
    html_content = self.get_address_members_html()

    # CRITICAL: Use set_onload to make data available to frontend
    if html_content:
        self.set_onload('other_members_at_address', html_content)
```

### Frontend: Displaying the Content

The JavaScript side checks for onload data and injects it into the HTML field:

```javascript
// In member.js
frappe.ui.form.on('Member', {
    refresh: function(frm) {
        // Check if we have onload data
        if (frm.doc.__onload && frm.doc.__onload.other_members_at_address) {
            const html_content = frm.doc.__onload.other_members_at_address;

            // Get the HTML field wrapper
            const field = frm.fields_dict.other_members_at_address;
            if (field && field.$wrapper) {
                // Direct DOM manipulation to avoid dirty state
                field.$wrapper.find('.form-control').html(html_content);
            }
        }
    }
});
```

## Implementation Details

### 1. DocType Configuration

In the Member.json file, the HTML field is defined simply:

```json
{
    "fieldname": "other_members_at_address",
    "fieldtype": "HTML",
    "label": "Other Members at This Address"
    // Note: No read_only, no default value needed
}
```

### 2. Backend HTML Generation

The backend generates the HTML content with all necessary data:

```python
def get_address_members_html(self):
    """Generate HTML for members at the same address"""
    if not self.current_address:
        return ""

    # Get members at same address (using optimized query)
    members = self.get_members_at_same_address()

    # Build HTML
    html_parts = ['<div class="address-members-container">']

    for member in members:
        age = calculate_age(member.birth_date)
        html_parts.append(f'''
            <div class="member-card">
                <a href="/app/member/{member.name}">
                    {member.first_name} {member.last_name}
                </a>
                <span class="age">{age} years</span>
            </div>
        ''')

    html_parts.append('</div>')
    return ''.join(html_parts)
```

### 3. API Endpoint (Optional)

For dynamic updates without page refresh, an API endpoint can be provided:

```python
@frappe.whitelist()
@utility_api(operation_type=OperationType.UTILITY)
def get_address_members_html_api(member_id):
    """API to get HTML for address members"""
    member = frappe.get_doc("Member", member_id)
    return member.get_address_members_html()
```

### 4. JavaScript Enhancement

To support both cached and dynamic loading:

```javascript
refresh: function(frm) {
    // Try onload data first (faster, no API call)
    if (frm.doc.__onload && frm.doc.__onload.other_members_at_address) {
        displayHtmlContent(frm, frm.doc.__onload.other_members_at_address);
    } else if (frm.doc.member_id) {
        // Fallback to API call if needed
        loadAddressMembersViaApi(frm);
    }
}

function displayHtmlContent(frm, html_content) {
    const field = frm.fields_dict.other_members_at_address;
    if (field && field.$wrapper) {
        // Direct DOM manipulation avoids triggering form dirty state
        field.$wrapper.find('.form-control').html(html_content);
    }
}
```

## Key Learnings

### 1. Avoid Form Dirty State

Using `frm.set_value()` with HTML fields triggers the form's dirty state, making Frappe think there are unsaved changes:

```javascript
// ❌ Causes "You have unsaved changes" warnings
frm.set_value('other_members_at_address', html_content);

// ✅ Direct DOM manipulation doesn't trigger dirty state
field.$wrapper.find('.form-control').html(html_content);
```

### 2. HTML Fields Are Not Document Attributes

```python
# ❌ This will fail
if hasattr(member, 'other_members_at_address'):
    # HTML fields don't exist as attributes!

# ✅ Use getattr with default
html_content = getattr(member, 'other_members_at_address', '')
# This will always return '' for HTML fields
```

### 3. Timing and Retry Logic

Sometimes the DOM isn't ready immediately. A retry mechanism ensures content displays:

```javascript
function injectHtmlWithRetry(field, html_content, attempts = 0) {
    if (attempts > 5) return;

    const formControl = field.$wrapper.find('.form-control');
    if (formControl.length) {
        formControl.html(html_content);
    } else {
        // Retry after short delay
        setTimeout(() => {
            injectHtmlWithRetry(field, html_content, attempts + 1);
        }, 100);
    }
}
```

## Common Pitfalls and Solutions

### Pitfall 1: Expecting HTML Fields to Persist

**Problem**: Trying to save HTML content to the database
**Solution**: Generate content dynamically in `onload()` or via API

### Pitfall 2: Security Restrictions

**Problem**: API endpoints with high security blocking frontend access
**Solution**: Use appropriate security decorators (`@utility_api` for read-only display data)

### Pitfall 3: Performance Issues

**Problem**: Heavy computation in onload() slows form loading
**Solution**:
- Cache computed results
- Use optimized queries
- Consider lazy loading via API for complex content

### Pitfall 4: Styling Conflicts

**Problem**: HTML content doesn't match Frappe's styling
**Solution**: Use Frappe's CSS classes or scope custom styles:

```html
<div class="frappe-card">
    <div class="card-body">
        <!-- Content using Frappe's styling -->
    </div>
</div>
```

## Best Practices

1. **Always use set_onload()** for initial HTML field content
2. **Avoid frm.set_value()** for HTML fields to prevent dirty state
3. **Handle missing DOM elements** gracefully with retry logic
4. **Optimize backend queries** since onload() runs on every form load
5. **Use appropriate API security** levels for display-only data
6. **Include error handling** for both backend and frontend code
7. **Test with different user roles** to ensure proper access

## Example: Complete Implementation

Here's the complete implementation for the "Other Members at Same Address" feature:

### Backend (member.py)
```python
def onload(self):
    """Load HTML content for display fields"""
    # Generate HTML for members at same address
    if self.current_address:
        html_content = self.get_address_members_html()
        if html_content:
            self.set_onload('other_members_at_address', html_content)

def get_address_members_html(self):
    """Generate HTML showing other members at same address"""
    if not self.current_address:
        return ""

    # Use optimized address matcher
    matcher = SimpleOptimizedAddressMatcher()
    members = matcher.find_members_at_address(
        self.current_address,
        exclude_member=self.name
    )

    if not members:
        return '<p class="text-muted">No other members at this address</p>'

    # Build HTML
    html = ['<div class="address-members-list">']
    for member in members:
        age = calculate_age(member.birth_date) if member.birth_date else "Unknown"
        html.append(f'''
            <div class="member-item" style="margin-bottom: 10px;">
                <a href="/app/member/{member.name}"
                   style="font-weight: 500; text-decoration: none;">
                    {member.first_name} {member.last_name}
                </a>
                <span style="color: #6c757d; margin-left: 10px;">
                    {age} years old
                </span>
            </div>
        ''')
    html.append('</div>')

    return ''.join(html)
```

### Frontend (member.js)
```javascript
frappe.ui.form.on('Member', {
    refresh: function(frm) {
        // Display other members at same address
        if (frm.doc.__onload && frm.doc.__onload.other_members_at_address) {
            displayAddressMembers(frm, frm.doc.__onload.other_members_at_address);
        }
    }
});

function displayAddressMembers(frm, html_content) {
    const field = frm.fields_dict.other_members_at_address;
    if (!field || !field.$wrapper) return;

    // Use retry mechanism for DOM readiness
    let attempts = 0;
    const inject = () => {
        const formControl = field.$wrapper.find('.form-control');
        if (formControl.length) {
            formControl.html(html_content);
        } else if (attempts < 5) {
            attempts++;
            setTimeout(inject, 100);
        }
    };
    inject();
}
```

## Debugging HTML Fields

### Check if Content is Generated
```python
# In console
member = frappe.get_doc("Member", "MEM-001")
member.onload()
print(member.get("__onload", {}).get("other_members_at_address"))
```

### Verify Frontend Reception
```javascript
// In browser console
cur_frm.doc.__onload
cur_frm.doc.__onload.other_members_at_address
```

### Check DOM Structure
```javascript
// In browser console
cur_frm.fields_dict.other_members_at_address
cur_frm.fields_dict.other_members_at_address.$wrapper
cur_frm.fields_dict.other_members_at_address.$wrapper.find('.form-control')
```

## Related Documentation

- [Field Reference Validation Guide](./FIELD_REFERENCE_VALIDATION_GUIDE.md)
- [Technical Architecture](../TECHNICAL_ARCHITECTURE.md)
- [API Security Framework](../security/api-security-framework-guide.md)

---

**Last Updated**: January 31, 2025
**Version**: 1.0
**Author**: Documentation generated from implementation experience
