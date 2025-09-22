# EmailService Architecture and Migration Guide

## Overview

The Verenigingen EmailService consolidates all email functionality from scattered implementations across the codebase into a unified, secure, and maintainable service. This document outlines the architecture, migration patterns, and usage guidelines for developers.

## Architecture Components

### Core Service Layer

```
verenigingen/services/communication/
├── email_service.py           # Main EmailService class
├── template_manager.py        # Template loading and rendering
├── notification_dispatcher.py # Notification type routing
└── compatibility.py          # Backward compatibility layer
```

### EmailService Features

- **Template-based emails** with Jinja2 context rendering
- **Bulk email handling** with configurable rate limiting
- **Communication record creation** for audit trails
- **Error handling and retry logic** with comprehensive logging
- **Security validation** and permission checking
- **Notification routing** based on type mappings

## Usage Patterns

### Python API

```python
from verenigingen.services.communication.email_service import get_email_service

# Get singleton service instance
email_service = get_email_service()

# Send templated email
result = email_service.send_templated_email(
    template_name="membership_application_approved",
    recipients=["member@example.com"],
    context={
        "member_name": "John Doe",
        "approval_date": get_datetime(),
        "chapter_name": "Amsterdam"
    },
    reference_doctype="Member",
    reference_name="MEM-001"
)

# Send system notification
result = email_service.send_notification(
    notification_type="member_approval",
    recipients=["member@example.com"],
    data={"member_name": "John Doe", "chapter": "Amsterdam"}
)

# Bulk email processing
email_batch = [
    {
        "template_name": "welcome",
        "recipients": ["user1@example.com"],
        "context": {"name": "User 1"}
    },
    {
        "template_name": "welcome",
        "recipients": ["user2@example.com"],
        "context": {"name": "User 2"}
    }
]

result = email_service.send_bulk_emails(
    email_batch=email_batch,
    batch_size=50,
    delay_between_batches=1.0
)
```

### JavaScript API

```javascript
// Send templated email
frappe.call({
    method: "verenigingen.api.email_api.send_templated_email",
    args: {
        template_name: "membership_application_approved",
        recipients: JSON.stringify(["member@example.com"]),
        context: JSON.stringify({
            member_name: "John Doe",
            approval_date: frappe.datetime.now_datetime(),
            chapter_name: "Amsterdam"
        }),
        reference_doctype: "Member",
        reference_name: "MEM-001"
    },
    callback: function(r) {
        if (r.message.success) {
            frappe.msgprint("Email sent successfully");
        } else {
            frappe.msgprint("Email failed: " + r.message.errors.join(", "));
        }
    }
});

// Send notification
frappe.call({
    method: "verenigingen.api.email_api.send_notification",
    args: {
        notification_type: "member_approval",
        recipients: JSON.stringify(["member@example.com"]),
        data: JSON.stringify({
            member_name: "John Doe",
            chapter: "Amsterdam"
        })
    }
});

// Get available templates
frappe.call({
    method: "verenigingen.api.email_api.get_available_templates",
    callback: function(r) {
        if (r.message.success) {
            console.log("Available templates:", r.message.templates);
        }
    }
});
```

## Migration Patterns

### Backward Compatibility Layer

The compatibility layer in `compatibility.py` provides seamless migration for existing code:

```python
# Old pattern (still works during transition)
from verenigingen.services.communication.compatibility import send_member_notification

result = send_member_notification(
    member_name="MEM-001",
    notification_type="member_approval",
    context={"chapter": "Amsterdam"}
)

# New pattern (recommended)
from verenigingen.services.communication.email_service import get_email_service

email_service = get_email_service()
result = email_service.send_notification(
    notification_type="member_approval",
    recipients=["member@example.com"],
    data={"chapter": "Amsterdam"}
)
```

### Template Migration

Templates are now managed as fixtures for consistent deployment:

**Before (hardcoded HTML):**
```python
html_content = f'''
<html>
<body>
    <h1>Welcome {member_name}!</h1>
    <p>Your application has been approved.</p>
</body>
</html>
'''
frappe.sendmail(recipients=[email], subject="Welcome", message=html_content)
```

**After (template-based):**
```python
email_service = get_email_service()
result = email_service.send_templated_email(
    template_name="membership_application_approved",
    recipients=[email],
    context={"member_name": member_name}
)
```

**Template fixture** (`fixtures/email_template.json`):
```json
{
    "doctype": "Email Template",
    "name": "membership_application_approved",
    "subject": "Welcome to {{organization_name}}!",
    "response_": "<html><body><h1>Welcome {{member_name}}!</h1>...</body></html>"
}
```

## Notification Type Mappings

The NotificationDispatcher maps notification types to email templates:

```python
template_mapping = {
    "member_approval": "membership_application_approved",
    "member_rejection": "membership_application_rejected",
    "member_suspension": "Member Suspension Notification",
    "payment_failure": "Payment Failure Notification",
    "sepa_mandate_created": "SEPA Mandate Created",
    "board_member_added": "Board Member Added",
    # ... additional mappings
}
```

## Security Framework

All API endpoints use the security framework:

```python
@frappe.whitelist()
@standard_api(operation_type=OperationType.COMMUNICATION)
def send_templated_email(template_name, recipients, context=None, **options):
    # Endpoint implementation with proper validation
```

## Error Handling

The service provides comprehensive error handling:

```python
result = email_service.send_templated_email(...)

if result["success"]:
    print(f"Email sent to {result['data']['recipients_count']} recipients")
    print(f"Communication ID: {result['data']['communication_id']}")
else:
    print(f"Email failed: {'; '.join(result['errors'])}")
```

## Performance Considerations

### Bulk Processing

For multiple emails, use bulk processing to avoid rate limiting:

```python
# Instead of multiple individual calls
for member in members:
    email_service.send_templated_email(...)  # Inefficient

# Use bulk processing
email_batch = [
    {"template_name": "...", "recipients": [...], "context": {...}}
    for member in members
]
email_service.send_bulk_emails(email_batch, batch_size=50)
```

### Template Caching

Templates are automatically cached to improve performance:
- First load: Retrieved from database and cached
- Subsequent loads: Served from memory cache
- Cache invalidation: Automatic on template updates

## Testing

### Unit Testing

```python
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

class TestEmailService(EnhancedTestCase):
    def test_templated_email(self):
        email_service = get_email_service()

        result = email_service.send_templated_email(
            template_name="test_template",
            recipients=["test@example.com"],
            context={"name": "Test User"}
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["recipients_count"], 1)
```

### Integration Testing

```python
# Test script for validating email consolidation
python scripts/test_email_consolidation.py
```

## Migration Checklist

When migrating existing email code:

1. **Identify email sending points** - Search for `frappe.sendmail`, custom email logic
2. **Extract template content** - Move HTML to email template fixtures
3. **Update method calls** - Replace with EmailService or compatibility layer
4. **Add context variables** - Replace hardcoded values with template variables
5. **Test email rendering** - Verify templates render correctly with test data
6. **Update JavaScript calls** - Use new API endpoints for frontend operations
7. **Remove deprecated code** - Clean up old email implementations after migration

## Best Practices

### Template Design
- Use semantic HTML with proper structure
- Include both text and HTML versions when possible
- Test templates with various context data
- Follow organization branding guidelines

### Context Variables
- Use descriptive variable names
- Provide default values for optional variables
- Document required context in template comments
- Validate context data before sending

### Error Handling
- Always check result["success"] before proceeding
- Log errors appropriately for debugging
- Provide user-friendly error messages
- Implement retry logic for transient failures

### Security
- Validate all recipient email addresses
- Sanitize context variables to prevent injection
- Use proper permission checks for sensitive operations
- Audit email operations through Communication records

## Future Enhancements

### Planned Features
- **Email analytics** - Open rates, click tracking
- **Template versioning** - A/B testing capabilities
- **Advanced scheduling** - Time-based email delivery
- **Internationalization** - Multi-language template support
- **Rich media support** - Embedded images, attachments

### Extension Points
- **Custom notification dispatchers** - Organization-specific routing
- **Template processors** - Advanced rendering logic
- **Delivery providers** - Integration with external email services
- **Compliance tools** - GDPR, CAN-SPAM compliance features

## Support and Documentation

For additional support:
- Review existing email templates in fixtures/
- Check Communication records for audit trails
- Monitor error logs for troubleshooting
- Use test scripts for validation during development
