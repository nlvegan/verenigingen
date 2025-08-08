# Email Opt-Out Implementation Plan
## Adding Communication Preferences to Membership Application

### Overview
Add a checkbox for opting out of optional organizational emails while making it clear that legally required communications (like AGM invitations) cannot be opted out of.

## Current State Analysis

### Existing Forms
1. **Enhanced Form**: `/templates/pages/membership_application.html`
   - Multi-step form with personal info, address, contribution, volunteer, payment sections
   - Already has `interested_in_volunteering` checkbox
   - Has terms acceptance checkbox

2. **Basic Form**: `/templates/membership_application.html`
   - Simpler single-page form
   - Standard personal and address fields
   - No current preference fields

### Member DocType
- **No existing newsletter/opt-in fields**
- Only has `interested_in_volunteering` and `donation_interest` fields
- CommunicationManager sends to all members with email addresses

## Implementation Plan

### 1. Add Field to Member DocType

```python
# Custom field to add to Member DocType
{
    "dt": "Member",
    "fieldname": "opt_out_optional_emails",
    "fieldtype": "Check",
    "label": "Opt-out of Optional Communications",
    "default": "0",  # Default to opted-in
    "insert_after": "email",
    "description": "Opt out of newsletters and optional organizational emails. Note: Legal communications such as AGM invitations cannot be opted out."
}
```

### 2. Update Enhanced Membership Application Form

Add after the volunteer section (Step 4) and before payment (Step 5):

```html
<!-- Communication Preferences Section -->
<div class="form-step" data-step="5">
    <div class="form-card">
        <div class="form-header">
            <h3>{{ _("Communication Preferences") }}</h3>
        </div>
        <div class="form-body">
            <!-- Legal Notice -->
            <div class="alert alert-info mb-4">
                <strong>{{ _("Important Legal Notice") }}</strong>
                <p class="mb-0 mt-2">
                    {{ _("As a member, you will receive certain legally required communications that cannot be opted out of, including:") }}
                </p>
                <ul class="mt-2 mb-0">
                    <li>{{ _("Annual General Meeting (AGM) invitations and notices") }}</li>
                    <li>{{ _("Extraordinary General Meeting notices") }}</li>
                    <li>{{ _("Statutory voting communications") }}</li>
                    <li>{{ _("Membership dues and payment notices") }}</li>
                </ul>
            </div>

            <!-- Optional Communications Opt-Out -->
            <div class="input-group">
                <div class="form-check">
                    <input type="checkbox"
                           id="opt_out_optional_emails"
                           name="opt_out_optional_emails"
                           class="form-check-input">
                    <label for="opt_out_optional_emails" class="form-check-label">
                        <strong>{{ _("Opt-out of optional organizational emails") }}</strong>
                        <p class="text-muted small mt-1 mb-0">
                            {{ _("If checked, you will NOT receive:") }}
                        </p>
                        <ul class="text-muted small mt-1">
                            <li>{{ _("Monthly/quarterly newsletters") }}</li>
                            <li>{{ _("Event announcements (non-statutory)") }}</li>
                            <li>{{ _("Volunteer opportunities") }}</li>
                            <li>{{ _("General organizational updates") }}</li>
                        </ul>
                    </label>
                </div>
            </div>

            <!-- Opt-In for Special Communications -->
            <div class="input-group mt-4">
                <p class="text-muted small">
                    {{ _("You can update your communication preferences at any time through your member portal.") }}
                </p>
            </div>
        </div>
    </div>
</div>
```

### 3. Update Basic Membership Application Form

Add before the submit button:

```html
<!-- Communication Preferences -->
<div class="card mb-4">
    <div class="card-header">
        <h4>{{ _("Communication Preferences") }}</h4>
    </div>
    <div class="card-body">
        <!-- Legal Notice -->
        <div class="alert alert-info">
            <strong>{{ _("Legal Notice") }}</strong>:
            {{ _("AGM invitations and other statutory communications must be sent to all members by law and cannot be opted out of.") }}
        </div>

        <!-- Opt-Out Checkbox -->
        <div class="form-check">
            <input type="checkbox"
                   class="form-check-input"
                   id="opt_out_optional_emails"
                   name="opt_out_optional_emails">
            <label class="form-check-label" for="opt_out_optional_emails">
                {{ _("I do NOT wish to receive optional newsletters and organizational updates") }}
                <br>
                <small class="text-muted">
                    {{ _("You will still receive legally required communications such as AGM notices.") }}
                </small>
            </label>
        </div>
    </div>
</div>
```

### 4. Update Backend Processing

```python
# In submit_membership_application function, add:
"opt_out_optional_emails": data.get("opt_out_optional_emails", False)
```

### 5. Update CommunicationManager

```python
# In _get_newsletter_recipients method, add filtering:
def _get_newsletter_recipients(self, filter_type: str) -> List[str]:
    """Get recipients for newsletter based on filter"""
    recipients = []

    try:
        if filter_type == "all":
            # All chapter members who haven't opted out
            for member in self.chapter_doc.members or []:
                if member.enabled:
                    member_doc = frappe.get_doc("Member", member.member)
                    # Check opt-out preference
                    if member_doc.email and not member_doc.get("opt_out_optional_emails"):
                        recipients.append(member_doc.email)

            # Board members (always included for chapter communications)
            for board_member in self.chapter_doc.board_members or []:
                if board_member.is_active and board_member.email:
                    recipients.append(board_member.email)

        # ... rest of the method
```

### 6. Add Method for Statutory Communications

```python
def send_statutory_communication(self, subject: str, content: str, communication_type: str = "agm") -> Dict:
    """
    Send legally required communications to ALL members regardless of preferences

    Args:
        subject: Email subject
        content: Email content
        communication_type: Type of statutory communication (agm, egm, voting, dues)
    """
    # Get ALL members with email addresses
    all_recipients = []

    for member in self.chapter_doc.members or []:
        if member.enabled:
            member_doc = frappe.get_doc("Member", member.member)
            if member_doc.email:
                all_recipients.append(member_doc.email)

    # Log this as a statutory communication
    self.log_action(
        "Statutory communication sent",
        {
            "type": communication_type,
            "recipient_count": len(all_recipients),
            "subject": subject
        }
    )

    # Send with special header indicating statutory nature
    return self.send_bulk_notification(
        template_name=f"statutory_{communication_type}",
        recipients=all_recipients,
        subject=f"[STATUTORY] {subject}",
        context={
            "is_statutory": True,
            "communication_type": communication_type,
            "content": content
        }
    )
```

## Migration Script

```python
# One-time script to add the field and set default values
def add_email_preferences():
    # Add custom field
    if not frappe.db.exists("Custom Field", {"dt": "Member", "fieldname": "opt_out_optional_emails"}):
        frappe.get_doc({
            "doctype": "Custom Field",
            "dt": "Member",
            "fieldname": "opt_out_optional_emails",
            "fieldtype": "Check",
            "label": "Opt-out of Optional Communications",
            "default": "0",
            "insert_after": "email",
            "description": "Opt out of newsletters and optional organizational emails. Note: Legal communications such as AGM invitations cannot be opted out."
        }).insert()

    # Set all existing members to opted-in by default
    frappe.db.sql("""
        UPDATE `tabMember`
        SET opt_out_optional_emails = 0
        WHERE opt_out_optional_emails IS NULL
    """)

    frappe.db.commit()
```

## Testing Plan

1. **Field Creation**
   - Verify field appears in Member DocType
   - Check default value is 0 (opted-in)

2. **Form Updates**
   - Test enhanced form shows new section
   - Test basic form shows new checkbox
   - Verify legal disclaimer is clear

3. **Data Processing**
   - Submit application with opt-out checked
   - Verify member record has correct preference

4. **Email Filtering**
   - Send newsletter to chapter
   - Verify opted-out members don't receive
   - Send AGM notice
   - Verify ALL members receive

## UI Text Translations

```python
# Key translations to add
translations = {
    "en": {
        "opt_out_disclaimer": "Legal communications such as AGM invitations must be sent to all members by law and cannot be opted out of.",
        "opt_out_label": "I do not wish to receive optional newsletters and organizational updates",
        "statutory_notice": "This is a legally required communication sent to all members"
    },
    "nl": {
        "opt_out_disclaimer": "Wettelijke communicatie zoals ALV-uitnodigingen moet volgens de wet naar alle leden worden gestuurd en kan niet worden uitgezet.",
        "opt_out_label": "Ik wil geen optionele nieuwsbrieven en organisatie-updates ontvangen",
        "statutory_notice": "Dit is een wettelijk verplichte communicatie verzonden naar alle leden"
    }
}
```

## Implementation Timeline

1. **Day 1**: Add field to Member DocType
2. **Day 2**: Update both membership application forms
3. **Day 3**: Update backend processing and CommunicationManager
4. **Day 4**: Testing and refinement
5. **Day 5**: Deploy to production

## Success Metrics

- ✓ Members can opt-out during application
- ✓ Opted-out members don't receive optional emails
- ✓ ALL members receive statutory communications
- ✓ Clear legal disclaimer visible
- ✓ Preference can be changed later
