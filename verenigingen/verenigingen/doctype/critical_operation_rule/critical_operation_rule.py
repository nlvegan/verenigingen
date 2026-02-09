# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config


class CriticalOperationRule(Document):
    """
    Critical Operation Rule DocType for runtime security configuration

    This DocType enables administrators to configure security rules for critical
    operations without code deployments. It supports business logic validation,
    rate limiting, audit requirements, and monitoring thresholds.
    """

    def validate(self):
        """Validate the rule configuration"""
        self.validate_operation_name()
        self.validate_security_level_consistency()
        self.validate_rate_limit_settings()
        self.validate_business_rules()
        self.validate_notification_settings()
        self.validate_system_user_settings()

    def validate_operation_name(self):
        """Ensure operation name follows naming conventions"""
        if not self.operation_name:
            frappe.throw(_("Operation Name is required"))

        # Operation names should be descriptive and follow snake_case or module.function format
        if not self.operation_name.replace("_", "").replace("-", "").replace(".", "").isalnum():
            frappe.throw(
                _("Operation Name should contain only letters, numbers, underscores, hyphens, and dots")
            )

    def validate_security_level_consistency(self):
        """Ensure security level matches operation type"""
        # Map operation types to recommended security levels
        recommended_levels = {
            "financial": ["critical", "high"],
            "member_data": ["high", "medium"],
            "admin": ["critical", "high"],
            "reporting": ["medium", "low"],
            "utility": ["low", "public"],
            "public": ["public"],
        }

        if self.operation_type in recommended_levels:
            if self.security_level not in recommended_levels[self.operation_type]:
                frappe.msgprint(
                    _(
                        "Security level '{0}' may not be appropriate for operation type '{1}'. "
                        "Recommended levels: {2}"
                    ).format(
                        self.security_level,
                        self.operation_type,
                        ", ".join(recommended_levels[self.operation_type]),
                    ),
                    indicator="orange",
                )

    def validate_rate_limit_settings(self):
        """Validate rate limiting configuration"""
        if self.rate_limit_calls is not None and self.rate_limit_calls < 1:
            frappe.throw(_("Rate limit calls must be at least 1"))

        if self.rate_limit_period_seconds is not None and self.rate_limit_period_seconds < 60:
            frappe.throw(_("Rate limit period must be at least 60 seconds"))

        # Validate batch rate limits if configured
        if self.batch_rate_limit_calls is not None:
            if self.batch_rate_limit_calls < 1:
                frappe.throw(_("Batch rate limit calls must be at least 1"))

            # Batch limits should be higher than or equal to interactive limits
            if self.rate_limit_calls and self.batch_rate_limit_calls < self.rate_limit_calls:
                frappe.throw(
                    _(
                        "Batch rate limit ({0}) should be greater than or equal to interactive rate limit ({1})"
                    ).format(self.batch_rate_limit_calls, self.rate_limit_calls)
                )

        if self.batch_rate_limit_period_seconds is not None and self.batch_rate_limit_period_seconds < 60:
            frappe.throw(_("Batch rate limit period must be at least 60 seconds"))

        # Warn about very permissive rate limits for critical operations
        if self.security_level == "critical" and self.rate_limit_calls > 50:
            frappe.msgprint(
                _(
                    "Very high rate limit ({0} calls) for critical operation. Consider reducing for better security."
                ).format(self.rate_limit_calls),
                indicator="orange",
            )

    def validate_business_rules(self):
        """Validate business rule configuration"""
        if self.enable_business_validation:
            if self.operation_type == "financial" and not self.amount_threshold:
                frappe.msgprint(
                    _("Consider setting an amount threshold for financial operations"), indicator="blue"
                )

            if self.amount_threshold and self.amount_threshold < 0:
                frappe.throw(_("Amount threshold cannot be negative"))

    def validate_notification_settings(self):
        """Validate notification configuration"""
        if self.alert_on_execution and not self.notification_recipients:
            # Skip validation during fixture import to avoid circular dependency
            if frappe.flags.in_import:
                frappe.logger().info(
                    f"Skipping notification validation for COR {self.name} during fixture import"
                )
                return

            # Auto-populate from Verenigingen Settings if available
            try:
                settings = frappe.get_single("Verenigingen Settings")
                # Try contact_email first, fall back to member_contact_email
                contact_email = getattr(settings, "contact_email", None) or getattr(
                    settings, "member_contact_email", None
                )
                if contact_email:
                    self.notification_recipients = contact_email
                    frappe.logger().info(
                        f"Auto-populated notification recipients for COR {self.name}: {contact_email}"
                    )
                else:
                    frappe.throw(
                        _(
                            "Notification recipients are required when alert on execution is enabled. Please configure contact_email or member_contact_email in Verenigingen Settings."
                        )
                    )
            except Exception:
                frappe.throw(_("Notification recipients are required when alert on execution is enabled"))

        if self.notification_recipients:
            from frappe.utils import validate_email_address

            recipients = [r.strip() for r in self.notification_recipients.split(",")]
            for recipient in recipients:
                if not validate_email_address(recipient, throw=False):
                    frappe.throw(_("Invalid email address: {0}").format(recipient))

    def validate_system_user_settings(self):
        """Warn when system user fallback is enabled on high-security operations"""
        if self.allow_system_user and self.security_level in ("critical", "high"):
            frappe.msgprint(
                _(
                    "System user fallback is enabled for a {0}-level operation. "
                    "This allows privilege escalation when the triggering user lacks permissions. "
                    "Only enable this for operations that run in automated/webhook contexts."
                ).format(self.security_level),
                indicator="orange",
            )

    def on_trash(self):
        """Clear cached rule configurations when a rule is deleted"""
        self.clear_rule_cache()

    def on_update(self):
        """Handle rule updates with security considerations"""
        # Log security policy changes for audit trail
        frappe.logger("verenigingen.security").info(
            f"Critical Operation Rule '{self.operation_name}' updated by {frappe.session.user}"
        )

        # Clear any cached rule configurations
        self.clear_rule_cache()

        # Send notifications about policy changes if configured
        self.notify_policy_change()

    def clear_rule_cache(self):
        """Clear cached rule configurations"""
        cache_key = "critical_operation_rules"
        frappe.cache().delete_value(cache_key)

        # Also clear specific rule cache
        specific_cache_key = f"critical_operation_rule:{self.operation_name}"
        frappe.cache().delete_value(specific_cache_key)

    def notify_policy_change(self):
        """Queue notifications about policy changes for aggregated digest.

        Instead of sending individual emails for each rule change, we queue
        changes and send a digest via scheduled task to prevent email flooding.
        """
        # Skip during fixture import/migration - these are bulk operations
        if frappe.flags.in_import or frappe.flags.in_migrate or frappe.flags.in_install:
            frappe.logger("critical_operation_rule").debug(
                f"Skipping notification queue for COR '{self.operation_name}' - "
                "in bulk operation (import/migrate/install)"
            )
            return

        # Only queue notifications for critical/high security rules
        if self.security_level not in ["critical", "high"]:
            return

        try:
            # Queue the change for digest notification
            change_record = {
                "operation_name": self.operation_name,
                "security_level": self.security_level,
                "operation_type": self.operation_type,
                "changed_by": frappe.session.user,
                "changed_at": frappe.utils.now(),
                "enabled_status": "Yes" if self.enabled else "No",
            }

            # Use Redis list to queue changes
            queue_key = "security_policy_change_queue"
            import json

            frappe.cache().lpush(queue_key, json.dumps(change_record))

            # Set expiry on the queue (24 hours max retention)
            frappe.cache().expire(queue_key, 86400)

            frappe.logger("critical_operation_rule").debug(
                f"Queued policy change notification for '{self.operation_name}'"
            )

        except Exception as e:
            # Gracefully handle any queue failures
            frappe.logger("critical_operation_rule").warning(
                f"Could not queue policy change notification for '{self.operation_name}': {str(e)}"
            )

    def _is_email_configured(self):
        """Check if email is properly configured"""
        try:
            # Check if there's a default outgoing email account with valid configuration
            default_account = frappe.db.get_value(
                "Email Account", {"default_outgoing": 1}, ["name", "email_id", "enable_outgoing"]
            )

            if not default_account:
                return False

            # Check if the email account has a valid email_id
            return bool(default_account[1])  # email_id should not be None/empty

        except Exception:
            return False

    def _get_admin_emails(self):
        """Get list of admin emails for notifications"""
        try:
            admins = frappe.get_all(
                "Has Role", filters={"role": "System Manager", "parenttype": "User"}, fields=["parent"]
            )

            admin_emails = []
            for admin in admins:
                try:
                    user = frappe.get_doc("User", admin.parent)
                    if user.enabled and user.email and "@" in user.email:
                        admin_emails.append(user.email)
                except Exception:
                    continue  # Skip problematic user records

            return admin_emails

        except Exception:
            return []

    @staticmethod
    def get_rule_config(operation_name: str) -> dict:
        """Get configuration for a specific operation (cached)"""
        cache_key = f"critical_operation_rule:{operation_name}"
        config = frappe.cache().get_value(cache_key)

        if not config:
            try:
                rule = frappe.get_doc("Critical Operation Rule", operation_name)
                if rule.enabled:
                    config = {
                        "operation_name": rule.operation_name,
                        "operation_type": rule.operation_type,
                        "security_level": rule.security_level,
                        "required_roles": [
                            r.strip() for r in (rule.required_roles or "").split(",") if r.strip()
                        ],
                        "required_permissions": [
                            p.strip() for p in (rule.required_permissions or "").split(",") if p.strip()
                        ],
                        "rate_limit": {
                            "calls": rule.rate_limit_calls if rule.rate_limit_calls is not None else 10,
                            "period_seconds": rule.rate_limit_period_seconds
                            if rule.rate_limit_period_seconds is not None
                            else 3600,
                            "scope": rule.rate_limit_scope or "per_user",
                        },
                        "allow_system_user": rule.allow_system_user,
                        "bypass_validations": [
                            v.strip() for v in (rule.bypass_validations or "").split(",") if v.strip()
                        ],
                        "business_rules": {
                            "enabled": rule.enable_business_validation,
                            "amount_threshold": rule.amount_threshold,
                        },
                        "audit_level": rule.audit_level,
                        "requires_justification": rule.requires_justification,
                        "monitoring": {
                            "execution_time": rule.monitor_execution_time,
                            "execution_time_threshold_ms": rule.execution_time_threshold_ms or 5000,
                            "failure_rate": rule.monitor_failure_rate,
                            "failure_rate_threshold_percent": rule.failure_rate_threshold_percent or 10,
                        },
                    }

                    # Cache for 5 minutes with explicit invalidation on update/delete
                    frappe.cache().set_value(cache_key, config, expires_in_sec=300)
                else:
                    config = None

            except frappe.DoesNotExistError:
                config = None

        return config

    @staticmethod
    def get_all_rules() -> dict:
        """Get all enabled rules (cached)"""
        cache_key = "critical_operation_rules"
        rules = frappe.cache().get_value(cache_key)

        if not rules:
            rule_docs = frappe.get_all(
                "Critical Operation Rule", filters={"enabled": 1}, fields=["operation_name"]
            )

            rules = {}
            for rule_doc in rule_docs:
                config = CriticalOperationRule.get_rule_config(rule_doc.operation_name)
                if config:
                    rules[rule_doc.operation_name] = config

            # Cache for 5 minutes with explicit invalidation on update/delete
            frappe.cache().set_value(cache_key, rules, expires_in_sec=300)

        return rules or {}


def send_security_policy_change_digest():
    """
    Scheduled task to send aggregated security policy change notifications.

    Processes the queue of policy changes and sends a single digest email
    instead of individual emails for each change. This prevents email flooding
    during bulk operations like fixture imports or migrations.

    Run frequency: Every 15 minutes (via scheduler_events)
    """
    import json
    from collections import defaultdict

    queue_key = "security_policy_change_queue"

    # Collect all queued changes
    changes = []
    while True:
        raw = frappe.cache().rpop(queue_key)
        if not raw:
            break
        try:
            changes.append(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue

    if not changes:
        return  # Nothing to send

    # Deduplicate changes by operation_name (keep latest)
    unique_changes = {}
    for change in changes:
        op_name = change.get("operation_name")
        if op_name:
            unique_changes[op_name] = change

    changes = list(unique_changes.values())

    if not changes:
        return

    # Group changes by security level for the digest
    by_level = defaultdict(list)
    for change in changes:
        by_level[change.get("security_level", "unknown")].append(change)

    # Check if email is configured
    default_account = frappe.db.get_value(
        "Email Account", {"default_outgoing": 1}, ["name", "email_id", "enable_outgoing"]
    )
    if not default_account or not default_account[1]:
        frappe.logger("critical_operation_rule").info(
            f"Skipping security policy digest - email not configured. {len(changes)} changes pending."
        )
        return

    # Get admin emails
    admins = frappe.get_all(
        "Has Role", filters={"role": "System Manager", "parenttype": "User"}, fields=["parent"]
    )
    admin_emails = []
    for admin in admins:
        try:
            user = frappe.get_doc("User", admin.parent)
            if user.enabled and user.email and "@" in user.email:
                admin_emails.append(user.email)
        except Exception:
            continue

    if not admin_emails:
        frappe.logger("critical_operation_rule").info(
            f"No admin emails found for security policy digest. {len(changes)} changes pending."
        )
        return

    # Build digest content
    try:
        company = get_mollie_config().get_default_company()
    except Exception:
        company = "Verenigingen"

    # Create digest summary
    digest_lines = []
    for level in ["critical", "high"]:
        if level in by_level:
            digest_lines.append(f"\n**{level.upper()} Security Level Changes ({len(by_level[level])}):**")
            for change in by_level[level]:
                digest_lines.append(
                    f"- {change['operation_name']} ({change['operation_type']}) - "
                    f"Enabled: {change['enabled_status']} - "
                    f"Changed by: {change['changed_by']} at {change['changed_at']}"
                )

    digest_text = "\n".join(digest_lines)

    # Send digest email using EmailService for UI controllability
    try:
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        # Build context for the template
        context = {
            "member_name": "System Administrator",
            "notification_message": f"{len(changes)} security rule(s) were modified and require your attention.",
            "payment_reference": f"Security Digest {frappe.utils.today()}",
            "amount": f"{len(changes)} rules",
            "payment_date": str(frappe.utils.now()),
            "payment_method": "Security Policy Change",
            "action_required": digest_text,
            "next_steps": "Please review these changes to ensure they align with security policies.",
            "company": company,
        }

        email_service.send_templated_email(
            template_name="payment_notification",
            recipients=admin_emails,
            context=context,
            subject_override=f"Security Policy Digest: {len(changes)} rule(s) modified",
            reference_doctype="Critical Operation Rule",
            reference_name=None,
            priority="high",
            notification_key="security_policy_digest",
        )

        frappe.logger("critical_operation_rule").info(
            f"Sent security policy digest with {len(changes)} changes to {len(admin_emails)} admins"
        )

    except Exception as e:
        frappe.logger("critical_operation_rule").warning(f"Could not send security policy digest: {str(e)}")
