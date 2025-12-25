# Feedback on Email Notification Configuration System Implementation

## Executive Summary
The implementation successfully introduces a configuration-driven notification system, migrating hardcoded email logic to a unified `EmailService`. The addition of `notification_key` parameters and the `Email Configuration` DocType provides the requested granular control.

However, a critical integration gap exists in the backward compatibility layer for member notifications, and a few specific notification calls are missing keys.

## Analysis

### 1. `EmailService.send_notification` Integration Gap (Critical)
The `verenigingen/services/communication/email_service.py` method `send_notification` (marked deprecated but used by `member_subscribers.py`) maps old notification types to templates but **does not pass the `notification_key`** to the underlying `send_templated_email` call.

**Impact:**
Notifications sent via `send_member_notification` (compatibility wrapper) will **bypass** the enablement checks and cooldown logic configured in `Email Configuration`. This affects:
- Member Approvals (`member_application_approved`)
- Member Suspensions (`member_suspended`)
- Member Terminations (`member_terminated`)
- Member Reactivations (`member_activated`)

**Recommendation:**
Update `EmailService.send_notification` to resolve the `notification_key` from the `notification_type` and pass it to `send_templated_email`.

```python
# Suggested fix in EmailService.send_notification
key_mapping = {
    "member_approval": "member_application_approved",
    "member_suspension": "member_suspended",
    "member_termination": "member_terminated",
    "member_reactivation": "member_activated",
    # ... add other mappings
}
notification_key = key_mapping.get(notification_type)

return self.send_templated_email(
    template_name=template_name,
    recipients=recipients,
    context=data,
    notification_key=notification_key, # <--- Missing
    **options
)
```

### 2. Missing Notification Key in Chapter Subscribers
In `verenigingen/events/subscribers/chapter_subscribers.py`, the function `_send_settings_change_notification` does not include a `notification_key`.

**Impact:**
Chapter settings change notifications cannot be disabled via UI and won't respect global email settings or cooldowns.

**Recommendation:**
Add `notification_key="chapter_settings_changed"` (or similar) to the call, and ensure this key is registered in the configuration patches.

```python
# In _send_settings_change_notification
email_service.send_templated_email(
    # ...
    notification_key="chapter_settings_changed", # <--- Add this
)
```

### 3. Patch Strategy
The split between `migrate_email_settings_to_configuration.py` and `add_team_chapter_notification_types.py` is understandable for handling existing vs. new installations.
- `migrate_email_settings_to_configuration.py` initializes the system.
- `add_team_chapter_notification_types.py` adds the new granular keys.

Ensure `chapter_settings_changed` (if added) is also included in `add_team_chapter_notification_types.py`.

### 4. Code Quality & Standards
- **Migration:** The migration of `critical_operation_rule.py` to `EmailService` is correctly implemented using the `security_policy_digest` key.
- **Team Subscribers:** `team_subscribers.py` correctly implements all 5 new notification keys.
- **Direct Calls:** `member_subscribers.py` uses `EmailService` directly for `_send_lifecycle_notification` with the correct `member_status_change` key, which is good. The issue is restricted to the legacy wrapper calls.

## Conclusion
The core feature is well-structured, but the `send_notification` wrapper needs an immediate fix to ensure the configuration UI actually controls the legacy-style member notifications.
