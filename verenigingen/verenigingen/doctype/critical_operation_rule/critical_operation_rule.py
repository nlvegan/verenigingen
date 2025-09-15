# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


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
        if self.rate_limit_calls and self.rate_limit_calls < 1:
            frappe.throw(_("Rate limit calls must be at least 1"))

        if self.rate_limit_period_seconds and self.rate_limit_period_seconds < 60:
            frappe.throw(_("Rate limit period must be at least 60 seconds"))

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
            frappe.throw(_("Notification recipients are required when alert on execution is enabled"))

        if self.notification_recipients:
            # Basic email validation for recipients
            recipients = [r.strip() for r in self.notification_recipients.split(",")]
            for recipient in recipients:
                if "@" not in recipient:
                    frappe.throw(_("Invalid email address: {0}").format(recipient))

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
        """Send notifications about policy changes following reviewer's pattern"""
        try:
            # Get administrators who should be notified
            admins = frappe.get_all(
                "Has Role", filters={"role": "System Manager", "parenttype": "User"}, fields=["parent"]
            )

            admin_emails = []
            for admin in admins:
                user = frappe.get_doc("User", admin.parent)
                if user.enabled and user.email:
                    admin_emails.append(user.email)

            if admin_emails and self.security_level in ["critical", "high"]:
                # Send notification for critical/high security rule changes
                frappe.sendmail(
                    recipients=admin_emails,
                    subject=f"Critical Operation Rule Changed: {self.operation_name}",
                    message=f"""
                    <h3>Security Policy Change Alert</h3>
                    <p><strong>Rule:</strong> {self.operation_name}</p>
                    <p><strong>Security Level:</strong> {self.security_level}</p>
                    <p><strong>Operation Type:</strong> {self.operation_type}</p>
                    <p><strong>Changed By:</strong> {frappe.session.user}</p>
                    <p><strong>Changed At:</strong> {frappe.utils.now()}</p>
                    <p><strong>Enabled:</strong> {'Yes' if self.enabled else 'No'}</p>

                    <p>Please review this change to ensure it aligns with security policies.</p>
                    """,
                    send_priority=1,
                )

        except Exception as e:
            # Don't fail the document save if notifications fail
            frappe.log_error(f"Failed to send policy change notification: {str(e)}")

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
                            "calls": rule.rate_limit_calls or 10,
                            "period_seconds": rule.rate_limit_period_seconds or 3600,
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

                    # Cache for 5 minutes
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

            # Cache for 5 minutes
            frappe.cache().set_value(cache_key, rules, expires_in_sec=300)

        return rules or {}
