# Email Fixtures Guide

## Overview

The Verenigingen app now includes a centralized email management system through fixtures and utilities. This system eliminates hardcoded email addresses and provides environment-appropriate email handling.

## File Structure

```
verenigingen/
├── fixtures/
│   └── email_addresses.py          # Central email definitions
├── utils/
│   └── email_utils.py              # Frappe-integrated utilities
└── scripts/testing/
    └── test_email_fixtures.py      # Test suite
```

## Email Categories

### 1. Production Emails
Real email addresses for production use:
- `app_contact`: "info@verenigingen.org"
- `member_administration`: "ledenadministratie@veganisme.org"
- `general_support`: "info@vereniging.nl"
- `admin_notifications`: "admin@veganisme.net"

### 2. Test Emails
Safe email addresses for testing:
- `generic_test`: "test@example.com"
- `admin_test`: "test_admin@example.com"
- `member_test`: "test_member@example.com"
- `volunteer_test`: "test.volunteer.js@example.org"

### 3. Development Emails
User-specific development emails:
- `foppe`: "foppe@veganisme.org"
- `fjdh_leden`: "fjdh@leden.socialisten.org"

### 4. Placeholder Emails
For forms and documentation:
- `example_personal`: "your.email@example.com"
- `example_support`: "support@example.com"
- `example_complex`: "test.email+tag@example.co.uk"

### 5. Security Test Emails
For security testing scenarios:
- `xss_test`: "test@example.com"
- `sql_injection_test`: "hacked@evil.com"
- `header_injection_test`: "test@example.com\\nBcc: hacker@evil.com"

## Usage Examples

### Basic Email Retrieval

```python
from verenigingen.fixtures.email_addresses import get_email

# Get production email
app_email = get_email("production", "app_contact")
# Returns: "info@verenigingen.org"

# Get test email with fallback
test_email = get_email("test", "nonexistent", "fallback@example.com")
# Returns: "fallback@example.com"
```

### Frappe-Integrated Usage

```python
from verenigingen.utils.email_utils import (
    get_member_contact_email,
    get_support_contact_email,
    create_test_user_email
)

# Get member contact email (checks settings, then company, then fallback)
member_email = get_member_contact_email()

# Get support email
support_email = get_support_contact_email()

# Create test user email
test_user = create_test_user_email("admin", "123")
# Returns: "test_admin.123@example.com"
```

### Template Context Integration

```python
from verenigingen.utils.email_utils import update_template_context_with_emails

def get_context(context):
    # Existing context setup...

    # Add email addresses to context
    context = update_template_context_with_emails(context)

    return context
```

### Email Validation

```python
from verenigingen.utils.email_utils import validate_email_usage
from verenigingen.fixtures.email_addresses import is_test_email, is_dev_email

# Check if email is appropriate for context
result = validate_email_usage("test@example.com", "production deployment")
# Returns: {"is_valid": True, "warnings": [...], "email_type": "test"}

# Simple checks
if is_test_email(email):
    print("This is a test email")

if is_dev_email(email):
    print("This is a development email")
```

## Migration from Hardcoded Emails

### Before (Hardcoded)
```python
# ❌ Bad - hardcoded
context.support_email = "support@example.com"

# ❌ Bad - hardcoded with fallback
member_contact_email = (
    frappe.db.get_single_value("Verenigingen Settings", "member_contact_email")
    or "ledenadministratie@veganisme.org"
)
```

### After (Fixtures)
```python
# ✅ Good - uses fixtures
from verenigingen.utils.email_utils import get_support_contact_email
context.support_email = get_support_contact_email()

# ✅ Good - proper fallback chain
from verenigingen.utils.email_utils import get_member_contact_email
member_contact_email = get_member_contact_email()
```

## Template Usage

### HTML Templates
```html
<!-- Use template variables -->
<a href="mailto:{{ member_contact_email }}">Contact Us</a>

<!-- With fallback -->
<p>Support: {{ support_email|default("support@example.com") }}</p>
```

### Template Context Setup
```python
def get_context(context):
    from verenigingen.utils.email_utils import get_template_email_context

    # Add all standard email addresses to context
    context.update(get_template_email_context())

    return context
```

## Environment Behavior

The system automatically detects the environment and provides appropriate emails:

- **Development Environment**: Uses test/placeholder emails
- **Production Environment**: Uses production emails
- **Testing Environment**: Uses test emails

Environment detection checks:
- `FRAPPE_ENV=development`
- `ENVIRONMENT=development`
- `SITE_NAME` contains "dev.veganisme.net"

## Testing

Run the test suite to validate the email fixtures:

```bash
python scripts/testing/test_email_fixtures.py
```

## Benefits

### 1. Centralized Management
- All email addresses defined in one place
- Easy to update across entire codebase
- No duplicate hardcoded emails

### 2. Environment-Aware
- Automatically uses appropriate emails for each environment
- Prevents test emails in production
- Supports development-specific emails

### 3. Type Safety
- Clear categorization of email types
- Validation functions to check email appropriateness
- Fallback mechanisms for missing emails

### 4. Easy Testing
- Dedicated test email addresses
- Functions to create unique test emails
- Email sanitization for testing

### 5. Template Integration
- Easy template context integration
- Proper fallback handling in templates
- Consistent email usage across templates

## Best Practices

### 1. Always Use Utilities
```python
# ✅ Good
from verenigingen.utils.email_utils import get_member_contact_email
email = get_member_contact_email()

# ❌ Bad
email = "ledenadministratie@veganisme.org"
```

### 2. Environment-Appropriate Emails
```python
# ✅ Good - environment aware
from verenigingen.fixtures.email_addresses import get_environment_email
email = get_environment_email("member_administration")

# ❌ Bad - always production
email = get_email("production", "member_administration")
```

### 3. Test Email Cleanup
```python
# ✅ Good - clean up test data
from verenigingen.fixtures.email_addresses import get_emails_for_cleanup

test_emails = get_emails_for_cleanup()
for email in test_emails:
    # Clean up records with this email
    cleanup_records_with_email(email)
```

### 4. Email Validation in Production
```python
# ✅ Good - validate email usage
from verenigingen.utils.email_utils import validate_email_usage

result = validate_email_usage(email, "production context")
if result["warnings"]:
    frappe.log_error("Email validation warnings: " + str(result["warnings"]))
```

## Adding New Email Addresses

### 1. Add to Fixtures
Edit `verenigingen/fixtures/email_addresses.py`:

```python
PRODUCTION_EMAILS = {
    # ... existing emails ...
    "new_category": "new.email@example.org",
}
```

### 2. Add Utility Function (Optional)
Edit `verenigingen/utils/email_utils.py`:

```python
def get_new_category_email() -> str:
    """Get the new category email with proper fallback."""
    return get_environment_email("new_category", "fallback@example.com")
```

### 3. Update Tests
Edit `scripts/testing/test_email_fixtures.py` to include tests for the new email.

### 4. Update Documentation
Add the new email to this guide and any relevant code documentation.

## Troubleshooting

### Issue: Email not found
**Error**: `KeyError: Email key 'xyz' not found in category 'production'`

**Solution**: Check that the email key exists in the specified category in `email_addresses.py`.

### Issue: Wrong email in production
**Problem**: Test emails appearing in production environment.

**Solution**: Use `get_environment_email()` or the utility functions which handle environment detection.

### Issue: Template email not working
**Problem**: Email not appearing in template context.

**Solution**: Ensure the template context is updated with email utilities:
```python
context = update_template_context_with_emails(context)
```

## Migration Checklist

When migrating from hardcoded emails:

- [ ] Identify all hardcoded email addresses
- [ ] Categorize emails (production, test, dev, placeholder)
- [ ] Add emails to appropriate fixtures category
- [ ] Replace hardcoded usage with utility functions
- [ ] Update template contexts
- [ ] Test in development environment
- [ ] Validate production environment behavior
- [ ] Update documentation

## Future Enhancements

Potential future improvements:
- Integration with Frappe's Email Account doctype
- Dynamic email configuration from database
- Email template management
- Bounce handling and validation
- Multi-language email support
