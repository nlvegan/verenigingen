# Newsletter & Communication System Usage Guide

## Overview
The Verenigingen app now includes a comprehensive newsletter and communication system that respects member preferences while ensuring compliance with legal requirements for statutory communications.

## Quick Start

### 1. Access Newsletter Functions
Navigate to the **Verenigingen** workspace and look for the **"Communication & Newsletters"** section:
- **Newsletter** - Create and send newsletters
- **Email Group** - Manage recipient lists
- **Communication** - View communication history
- **Email Template** - Manage templates

Direct URLs:
- Newsletter: `https://dev.veganisme.net/app/newsletter`
- Email Groups: `https://dev.veganisme.net/app/email-group`

### 2. Email Groups Setup
We've created the following default email groups:
- **All Active Members** - All members with email addresses (313 members)
- **Newsletter Subscribers** - Members who haven't opted out (313 members)
- **Board Members** - Current board members
- **Active Volunteers** - Active volunteer members (23 members)
- **[Chapter] Members** - Chapter-specific groups (e.g., "Amsterdam Members")

## Sending Newsletters

### Method 1: Using Frappe's Newsletter Module (GUI)

1. Go to **Newsletter** from the workspace
2. Click **New Newsletter**
3. Fill in the details:
   - **Subject**: Your email subject
   - **Sender Email**: Select or enter sender email
   - **Email Group**: Select recipient group(s)
   - **Content Type**: Choose "Rich Text" or "Markdown"
   - **Message**: Your newsletter content
4. Click **Save**
5. Click **Send Now** or **Schedule**

### Method 2: Using Chapter Communication Manager (Code)

For chapter-specific newsletters that respect opt-out preferences:

```python
bench --site dev.veganisme.net console

# Get a chapter
chapter = frappe.get_doc("Chapter", "Amsterdam")

# Send optional newsletter (respects opt-out)
result = chapter.send_chapter_newsletter(
    subject="Amsterdam Chapter - Monthly Update",
    content="<h2>Chapter News</h2><p>Your content here...</p>",
    recipient_filter="all"  # Options: "all", "board", "members"
)

print(f"Sent to {result['sent_count']} recipients")
```

### Method 3: Statutory Communications (Mandatory)

For legally required communications that bypass opt-out preferences:

```python
# Send AGM notice to ALL members
result = chapter.communication_manager.send_statutory_communication(
    subject="Annual General Meeting - Official Notice",
    content="<p>You are hereby notified of the AGM...</p>",
    communication_type="agm"  # Options: "agm", "egm", "voting", "dues"
)
```

## Member Communication Preferences

### How Opt-Out Works

1. **During Registration**: Members can check "Opt-out of optional communications" on the membership application form
2. **Stored in Database**: The preference is saved in the `opt_out_optional_emails` field
3. **Respected by System**:
   - Optional newsletters skip opted-out members
   - Statutory communications ignore opt-out preferences

### Current Statistics
```
Total Active Members: 313
Members with Email: 313
Opted Out: 0 (0%)
Newsletter Subscribers: 313
```

## Sample Newsletter Template

We've created a sample newsletter template called "Monthly Member Update" that includes:
- Personalized greeting using `{{ first_name }}`
- Sections for events, highlights, and announcements
- Legal disclaimer about opt-out preferences
- Note about mandatory statutory communications

## API Functions Available

### Setup Functions
```python
# Set up default email groups
from verenigingen.api.newsletter_demo import setup_email_groups
setup_email_groups()

# Populate groups with current members
from verenigingen.api.newsletter_demo import populate_email_groups
populate_email_groups()

# Get newsletter statistics
from verenigingen.api.newsletter_demo import get_newsletter_statistics
stats = get_newsletter_statistics()
```

### Communication Manager Methods
```python
# Get chapter
chapter = frappe.get_doc("Chapter", "Amsterdam")

# Send newsletter (respects opt-out)
chapter.send_chapter_newsletter(subject, content, recipient_filter)

# Send statutory communication (ignores opt-out)
chapter.communication_manager.send_statutory_communication(subject, content, type)

# Send bulk notification
chapter.communication_manager.send_bulk_notification(
    template_name="welcome_email",
    recipients=["email1@example.com", "email2@example.com"],
    subject="Welcome",
    context={"name": "John"}
)

# Get communication history
history = chapter.get_communication_history(limit=50)
```

## Best Practices

### 1. Content Guidelines
- Keep newsletters concise and relevant
- Use personalization tokens: `{{ first_name }}`, `{{ last_name }}`
- Include unsubscribe information for optional communications
- Clearly mark statutory communications

### 2. Frequency Recommendations
- Monthly newsletters for general updates
- Quarterly for major announcements
- Immediate for urgent/statutory notices

### 3. Legal Compliance
- **Always use `send_statutory_communication()`** for:
  - AGM/EGM notices
  - Voting announcements
  - Membership dues notices
  - Legal notifications
- Include disclaimer text in optional newsletters
- Maintain audit trail through Communication records

### 4. Performance Tips
- Send newsletters in batches (automatic with bulk_notification)
- Schedule during off-peak hours
- Monitor email bounce rates

## Troubleshooting

### Newsletter Not Sending
1. Check if Email Account is configured
2. Verify SMTP settings in Email Account
3. Check recipient email addresses are valid
4. Review error logs in Communication record

### Members Not Receiving Emails
1. Check if member has valid email address
2. Verify member is in correct email group
3. Check opt-out status for optional emails
4. Review spam/junk folders

### Email Groups Not Updating
1. Run `populate_email_groups()` to refresh
2. Check member status (must be "Active")
3. Verify chapter assignments

## Integration with Existing Systems

### Member Portal
Members can update their communication preferences through their profile (if implemented).

### Chapter Management
Chapter administrators can send targeted communications to their chapter members.

### Reporting
- View newsletter open rates (if tracking enabled)
- Monitor opt-out trends
- Track communication history per member

## Security Considerations

1. **Permissions**: Only authorized users can send newsletters
2. **Data Protection**: Email addresses are protected by Frappe's permission system
3. **Audit Trail**: All communications are logged
4. **Rate Limiting**: Built-in protection against spam

## Future Enhancements

Consider implementing:
1. Automated welcome emails for new members
2. Birthday greetings
3. Membership renewal reminders
4. Event invitations with RSVP tracking
5. SMS integration for urgent notices
6. Advanced segmentation based on member attributes

## Support

For issues or questions:
1. Check Communication logs for errors
2. Review Email Account configuration
3. Verify permission settings
4. Contact system administrator

---

*Last Updated: December 2024*
*System Version: Verenigingen 1.0*
