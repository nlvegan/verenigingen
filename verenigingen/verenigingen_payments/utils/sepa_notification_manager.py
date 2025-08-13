"""
SEPA Notification Manager

Comprehensive notification system for SEPA batch operations including:
- Batch processing notifications
- Failure alerts
- Recovery notifications
- Rollback notifications
- Performance monitoring alerts

Implements Week 3 Day 5 requirements from the SEPA billing improvements project.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import add_days, get_datetime, now, today

from verenigingen.utils.error_handling import SEPAError, handle_api_error, log_error


class NotificationType(Enum):
    """Types of SEPA notifications"""

    BATCH_SUCCESS = "batch_success"
    BATCH_FAILURE = "batch_failure"
    BATCH_WARNING = "batch_warning"
    ROLLBACK_INITIATED = "rollback_initiated"
    ROLLBACK_COMPLETED = "rollback_completed"
    PERFORMANCE_ALERT = "performance_alert"
    COMPLIANCE_ISSUE = "compliance_issue"
    MANDATE_EXPIRY = "mandate_expiry"
    RECOVERY_SUCCESS = "recovery_success"
    SYSTEM_ERROR = "system_error"


class NotificationPriority(Enum):
    """Notification priority levels"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class NotificationChannel(Enum):
    """Notification delivery channels"""

    EMAIL = "email"
    SMS = "sms"
    SYSTEM_NOTIFICATION = "system_notification"
    WEBHOOK = "webhook"
    SLACK = "slack"


@dataclass
class NotificationTemplate:
    """Notification template definition"""

    template_id: str
    notification_type: NotificationType
    priority: NotificationPriority
    channels: List[NotificationChannel]
    subject_template: str
    message_template: str
    enabled: bool = True


@dataclass
class NotificationRule:
    """Notification rule definition"""

    rule_id: str
    name: str
    conditions: Dict[str, Any]
    template_id: str
    recipients: List[str]
    enabled: bool = True
    cooldown_minutes: int = 60


class SEPANotificationManager:
    """
    Comprehensive notification manager for SEPA operations

    Features:
    - Template-based notifications
    - Multiple delivery channels
    - Priority-based routing
    - Cooldown management
    - Recipient management
    - Delivery tracking
    """

    def __init__(self):
        self.templates = self._initialize_templates()
        self.rules = self._initialize_rules()
        self.delivery_log = []
        self._ensure_notification_tables()

    def _ensure_notification_tables(self):
        """Ensure notification tracking tables exist"""
        try:
            # Notification log table
            frappe.db.sql(
                """
                CREATE TABLE IF NOT EXISTS `tabSEPA_Notification_Log` (
                    `name` varchar(255) NOT NULL PRIMARY KEY,
                    `creation` datetime(6) DEFAULT NULL,
                    `modified` datetime(6) DEFAULT NULL,
                    `notification_id` varchar(255) NOT NULL UNIQUE,
                    `notification_type` varchar(100) NOT NULL,
                    `priority` varchar(50) NOT NULL,
                    `channels` varchar(255) DEFAULT NULL,
                    `recipients` longtext DEFAULT NULL,
                    `subject` text DEFAULT NULL,
                    `message` longtext DEFAULT NULL,
                    `context` longtext DEFAULT NULL,
                    `delivery_status` varchar(50) DEFAULT 'pending',
                    `delivery_attempts` int DEFAULT 0,
                    `last_attempt` datetime(6) DEFAULT NULL,
                    `delivered_at` datetime(6) DEFAULT NULL,
                    `error_message` text DEFAULT NULL,
                    INDEX `idx_notification_type` (`notification_type`),
                    INDEX `idx_delivery_status` (`delivery_status`),
                    INDEX `idx_creation` (`creation`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
            )

            # Notification preferences table
            frappe.db.sql(
                """
                CREATE TABLE IF NOT EXISTS `tabSEPA_Notification_Preferences` (
                    `name` varchar(255) NOT NULL PRIMARY KEY,
                    `creation` datetime(6) DEFAULT NULL,
                    `modified` datetime(6) DEFAULT NULL,
                    `user_email` varchar(255) NOT NULL,
                    `notification_type` varchar(100) NOT NULL,
                    `enabled` tinyint(1) DEFAULT 1,
                    `channels` varchar(255) DEFAULT 'email',
                    `minimum_priority` varchar(50) DEFAULT 'medium',
                    UNIQUE KEY `unique_user_type` (`user_email`, `notification_type`),
                    INDEX `idx_user_email` (`user_email`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
            )

            frappe.db.commit()

        except Exception as e:
            frappe.logger().warning(f"Notification table creation issue: {str(e)}")

    def _initialize_templates(self) -> Dict[str, NotificationTemplate]:
        """Initialize notification templates"""
        templates = {}

        # Batch Success Template
        templates["batch_success"] = NotificationTemplate(
            template_id="batch_success",
            notification_type=NotificationType.BATCH_SUCCESS,
            priority=NotificationPriority.LOW,
            channels=[NotificationChannel.EMAIL, NotificationChannel.SYSTEM_NOTIFICATION],
            subject_template="SEPA Batch {batch_name} Processed Successfully",
            message_template="""
SEPA Batch Processing Completed Successfully

Batch Details:
- Batch Name: {batch_name}
- Collection Date: {collection_date}
- Total Amount: €{total_amount:,.2f}
- Transaction Count: {transaction_count}
- Processing Time: {processing_time}

All transactions have been processed successfully and submitted to the bank.

Generated at: {timestamp}
            """.strip(),
        )

        # Batch Failure Template
        templates["batch_failure"] = NotificationTemplate(
            template_id="batch_failure",
            notification_type=NotificationType.BATCH_FAILURE,
            priority=NotificationPriority.HIGH,
            channels=[
                NotificationChannel.EMAIL,
                NotificationChannel.SMS,
                NotificationChannel.SYSTEM_NOTIFICATION,
            ],
            subject_template="CRITICAL: SEPA Batch {batch_name} Processing Failed",
            message_template="""
SEPA Batch Processing FAILED

Batch Details:
- Batch Name: {batch_name}
- Collection Date: {collection_date}
- Total Amount: €{total_amount:,.2f}
- Transaction Count: {transaction_count}

Failure Details:
- Error Type: {error_type}
- Error Message: {error_message}
- Failed Transactions: {failed_count}

IMMEDIATE ACTION REQUIRED:
{action_required}

Please investigate and resolve the issues immediately.

Generated at: {timestamp}
            """.strip(),
        )

        # Rollback Notification Template
        templates["rollback_initiated"] = NotificationTemplate(
            template_id="rollback_initiated",
            notification_type=NotificationType.ROLLBACK_INITIATED,
            priority=NotificationPriority.HIGH,
            channels=[NotificationChannel.EMAIL, NotificationChannel.SYSTEM_NOTIFICATION],
            subject_template="SEPA Batch Rollback Initiated: {batch_name}",
            message_template="""
SEPA Batch Rollback Operation Initiated

Operation Details:
- Operation ID: {operation_id}
- Batch Name: {batch_name}
- Rollback Reason: {reason}
- Rollback Scope: {scope}
- Affected Invoices: {affected_invoices_count}
- Total Amount: €{total_amount:,.2f}

Initiated by: {initiated_by}
Initiated at: {initiated_at}

The rollback operation is now in progress. You will receive another notification when completed.

Generated at: {timestamp}
            """.strip(),
        )

        # Performance Alert Template
        templates["performance_alert"] = NotificationTemplate(
            template_id="performance_alert",
            notification_type=NotificationType.PERFORMANCE_ALERT,
            priority=NotificationPriority.MEDIUM,
            channels=[NotificationChannel.EMAIL, NotificationChannel.SYSTEM_NOTIFICATION],
            subject_template="SEPA Performance Alert: {alert_type}",
            message_template="""
SEPA System Performance Alert

Alert Details:
- Alert Type: {alert_type}
- Threshold Exceeded: {threshold_exceeded}
- Current Value: {current_value}
- Recommended Action: {recommended_action}

Performance Metrics:
{performance_metrics}

Please review system performance and take appropriate action if necessary.

Generated at: {timestamp}
            """.strip(),
        )

        # Mandate Expiry Warning Template
        templates["mandate_expiry"] = NotificationTemplate(
            template_id="mandate_expiry",
            notification_type=NotificationType.MANDATE_EXPIRY,
            priority=NotificationPriority.MEDIUM,
            channels=[NotificationChannel.EMAIL, NotificationChannel.SYSTEM_NOTIFICATION],
            subject_template="SEPA Mandate Expiry Warning: {expiring_count} Mandates",
            message_template="""
SEPA Mandate Expiry Warning

{expiring_count} mandates are expiring within the next {days_ahead} days:

{mandate_list}

Action Required:
- Contact affected members to renew mandates
- Update mandate information in the system
- Ensure continuity of payment processing

Please take action to prevent payment disruptions.

Generated at: {timestamp}
            """.strip(),
        )

        return templates

    def _initialize_rules(self) -> List[NotificationRule]:
        """Initialize notification rules"""
        return [
            NotificationRule(
                rule_id="batch_success_rule",
                name="Batch Success Notification",
                conditions={"notification_type": "batch_success"},
                template_id="batch_success",
                recipients=["sepa_administrators"],
                cooldown_minutes=0,  # No cooldown for success notifications
            ),
            NotificationRule(
                rule_id="batch_failure_rule",
                name="Batch Failure Alert",
                conditions={"notification_type": "batch_failure"},
                template_id="batch_failure",
                recipients=["sepa_administrators", "system_managers"],
                cooldown_minutes=30,  # 30-minute cooldown for failure alerts
            ),
            NotificationRule(
                rule_id="performance_alert_rule",
                name="Performance Alert",
                conditions={"notification_type": "performance_alert"},
                template_id="performance_alert",
                recipients=["system_managers"],
                cooldown_minutes=60,  # 1-hour cooldown for performance alerts
            ),
            NotificationRule(
                rule_id="mandate_expiry_rule",
                name="Mandate Expiry Warning",
                conditions={"notification_type": "mandate_expiry"},
                template_id="mandate_expiry",
                recipients=["sepa_administrators"],
                cooldown_minutes=1440,  # 24-hour cooldown for expiry warnings
            ),
        ]

    def send_notification(
        self,
        notification_type: NotificationType,
        context: Dict[str, Any],
        priority: NotificationPriority = None,
        recipients: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Send notification based on type and context

        Args:
            notification_type: Type of notification
            context: Context data for template rendering
            priority: Override priority level
            recipients: Override recipients

        Returns:
            Notification result
        """
        try:
            # Get template
            template = self.templates.get(notification_type.value)
            if not template:
                return {
                    "success": False,
                    "error": f"No template found for notification type: {notification_type.value}",
                }

            # Find applicable rules
            applicable_rules = [
                rule
                for rule in self.rules
                if rule.enabled and self._rule_matches(rule, {"notification_type": notification_type.value})
            ]

            if not applicable_rules:
                return {
                    "success": False,
                    "error": f"No applicable rules found for notification type: {notification_type.value}",
                }

            results = []

            for rule in applicable_rules:
                # Check cooldown
                if self._is_in_cooldown(rule, context):
                    continue

                # Get recipients
                rule_recipients = recipients or self._get_rule_recipients(rule)
                if not rule_recipients:
                    continue

                # Render notification content
                rendered_content = self._render_notification(template, context)
                if not rendered_content["success"]:
                    results.append(rendered_content)
                    continue

                # Determine delivery channels
                channels = self._get_delivery_channels(template, rule_recipients)

                # Send notification
                delivery_result = self._deliver_notification(
                    template=template,
                    content=rendered_content,
                    recipients=rule_recipients,
                    channels=channels,
                    context=context,
                    priority=priority or template.priority,
                )

                results.append(delivery_result)

            # Aggregate results
            success_count = sum(1 for r in results if r.get("success"))
            total_count = len(results)

            return {
                "success": success_count > 0,
                "delivered": success_count,
                "total_attempts": total_count,
                "results": results,
            }

        except Exception as e:
            error_msg = f"Notification sending failed: {str(e)}"
            log_error(
                e, context={"notification_type": notification_type.value}, module="sepa_notification_manager"
            )
            return {"success": False, "error": error_msg}

    def _rule_matches(self, rule: NotificationRule, context: Dict[str, Any]) -> bool:
        """Check if rule conditions match context"""
        for key, expected_value in rule.conditions.items():
            if context.get(key) != expected_value:
                return False
        return True

    def _is_in_cooldown(self, rule: NotificationRule, context: Dict[str, Any]) -> bool:
        """Check if rule is in cooldown period"""
        if rule.cooldown_minutes <= 0:
            return False

        try:
            # Check last notification time for this rule and context
            last_notification = frappe.db.sql(
                """
                SELECT MAX(creation) as last_sent
                FROM `tabSEPA_Notification_Log`
                WHERE notification_type = %s
                AND creation > %s
            """,
                (context.get("notification_type"), add_days(now(), days=-1)),  # Check last 24 hours
                as_dict=True,
            )

            if last_notification and last_notification[0].last_sent:
                last_sent = get_datetime(last_notification[0].last_sent)
                cooldown_end = last_sent + timedelta(minutes=rule.cooldown_minutes)

                if datetime.now() < cooldown_end:
                    return True

            return False

        except Exception:
            # If check fails, allow notification
            return False

    def _get_rule_recipients(self, rule: NotificationRule) -> List[str]:
        """Get recipients for a notification rule"""
        recipients = []

        for recipient_group in rule.recipients:
            if recipient_group == "sepa_administrators":
                # Get users with SEPA admin roles
                sepa_admins = frappe.get_all(
                    "Has Role", filters={"role": "Verenigingen Administrator"}, fields=["parent"]
                )
                for admin in sepa_admins:
                    user = frappe.get_doc("User", admin.parent)
                    if user.email and user.enabled:
                        recipients.append(user.email)

            elif recipient_group == "system_managers":
                # Get system managers
                sys_managers = frappe.get_all(
                    "Has Role", filters={"role": "System Manager"}, fields=["parent"]
                )
                for manager in sys_managers:
                    user = frappe.get_doc("User", manager.parent)
                    if user.email and user.enabled:
                        recipients.append(user.email)

            else:
                # Direct email address
                if "@" in recipient_group:
                    recipients.append(recipient_group)

        return list(set(recipients))  # Remove duplicates

    def _render_notification(self, template: NotificationTemplate, context: Dict[str, Any]) -> Dict[str, Any]:
        """Render notification content using template"""
        try:
            # Add timestamp to context
            context["timestamp"] = now()

            # Render subject
            subject = template.subject_template.format(**context)

            # Render message
            message = template.message_template.format(**context)

            return {"success": True, "subject": subject, "message": message}

        except KeyError as e:
            return {"success": False, "error": f"Missing context variable: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"Template rendering failed: {str(e)}"}

    def _get_delivery_channels(
        self, template: NotificationTemplate, recipients: List[str]
    ) -> List[NotificationChannel]:
        """Get delivery channels based on template and recipient preferences"""
        # For now, use template default channels
        # In full implementation, would check individual recipient preferences
        return template.channels

    def _deliver_notification(
        self,
        template: NotificationTemplate,
        content: Dict[str, Any],
        recipients: List[str],
        channels: List[NotificationChannel],
        context: Dict[str, Any],
        priority: NotificationPriority,
    ) -> Dict[str, Any]:
        """Deliver notification through specified channels"""
        try:
            notification_id = f"NOTIF_{template.template_id}_{frappe.generate_hash()[:8]}"

            # Log notification
            self._log_notification(
                notification_id=notification_id,
                template=template,
                content=content,
                recipients=recipients,
                channels=channels,
                context=context,
                priority=priority,
            )

            delivery_results = {}

            # Deliver through each channel
            for channel in channels:
                if channel == NotificationChannel.EMAIL:
                    result = self._send_email(content, recipients, context)
                    delivery_results["email"] = result

                elif channel == NotificationChannel.SYSTEM_NOTIFICATION:
                    result = self._create_system_notification(content, recipients, context)
                    delivery_results["system"] = result

                elif channel == NotificationChannel.SMS:
                    result = self._send_sms(content, recipients, context)
                    delivery_results["sms"] = result

                # Add other channels as needed

            # Update delivery status
            success = any(result.get("success") for result in delivery_results.values())
            self._update_delivery_status(
                notification_id, "delivered" if success else "failed", delivery_results
            )

            return {
                "success": success,
                "notification_id": notification_id,
                "delivery_results": delivery_results,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _send_email(
        self, content: Dict[str, Any], recipients: List[str], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send email notification"""
        try:
            # Send email using Frappe's email system
            frappe.sendmail(
                recipients=recipients,
                subject=content["subject"],
                message=content["message"],
                reference_doctype=context.get("reference_doctype"),
                reference_name=context.get("reference_name"),
            )

            return {"success": True, "recipients_count": len(recipients)}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _create_system_notification(
        self, content: Dict[str, Any], recipients: List[str], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create system notification"""
        try:
            for recipient in recipients:
                try:
                    # Create notification document
                    notification = frappe.get_doc(
                        {
                            "doctype": "Notification Log",
                            "subject": content["subject"],
                            "email_content": content["message"],
                            "for_user": recipient,
                            "type": "Alert",
                            "document_type": context.get("reference_doctype"),
                            "document_name": context.get("reference_name"),
                        }
                    )
                    notification.insert(ignore_permissions=True)

                except Exception as e:
                    frappe.logger().warning(f"Failed to create system notification for {recipient}: {str(e)}")

            return {"success": True, "recipients_count": len(recipients)}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _send_sms(
        self, content: Dict[str, Any], recipients: List[str], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send SMS notification (placeholder)"""
        # SMS implementation would depend on SMS provider
        return {"success": False, "error": "SMS delivery not implemented"}

    def _log_notification(
        self,
        notification_id: str,
        template: NotificationTemplate,
        content: Dict[str, Any],
        recipients: List[str],
        channels: List[NotificationChannel],
        context: Dict[str, Any],
        priority: NotificationPriority,
    ):
        """Log notification to database"""
        try:
            frappe.db.sql(
                """
                INSERT INTO `tabSEPA_Notification_Log`
                (name, creation, modified, notification_id, notification_type, priority,
                 channels, recipients, subject, message, context, delivery_status)
                VALUES (%(name)s, %(now)s, %(now)s, %(notification_id)s, %(notification_type)s,
                        %(priority)s, %(channels)s, %(recipients)s, %(subject)s, %(message)s,
                        %(context)s, 'pending')
            """,
                {
                    "name": f"NOTIF_LOG_{notification_id}",
                    "now": now(),
                    "notification_id": notification_id,
                    "notification_type": template.notification_type.value,
                    "priority": priority.value,
                    "channels": ",".join([c.value for c in channels]),
                    "recipients": frappe.as_json(recipients),
                    "subject": content["subject"],
                    "message": content["message"],
                    "context": frappe.as_json(context),
                },
            )

            frappe.db.commit()

        except Exception as e:
            frappe.logger().error(f"Error logging notification: {str(e)}")

    def _update_delivery_status(self, notification_id: str, status: str, results: Dict[str, Any]):
        """Update notification delivery status"""
        try:
            frappe.db.sql(
                """
                UPDATE `tabSEPA_Notification_Log`
                SET delivery_status = %s, delivered_at = %s, delivery_attempts = delivery_attempts + 1,
                    last_attempt = %s, error_message = %s
                WHERE notification_id = %s
            """,
                (
                    status,
                    now() if status == "delivered" else None,
                    now(),
                    frappe.as_json(results) if status == "failed" else None,
                    notification_id,
                ),
            )

            frappe.db.commit()

        except Exception as e:
            frappe.logger().error(f"Error updating delivery status: {str(e)}")

    def get_notification_history(self, days_back: int = 7, notification_type: str = None) -> Dict[str, Any]:
        """Get notification history"""
        try:
            filters = ["creation >= %s"]
            params = [add_days(today(), -days_back)]

            if notification_type:
                filters.append("notification_type = %s")
                params.append(notification_type)

            where_clause = " WHERE " + " AND ".join(filters)

            notifications = frappe.db.sql(
                f"""
                SELECT notification_id, notification_type, priority, channels, recipients,
                       subject, delivery_status, creation, delivered_at, error_message
                FROM `tabSEPA_Notification_Log`
                {where_clause}
                ORDER BY creation DESC
            """,
                params,
                as_dict=True,
            )

            return {
                "success": True,
                "notifications": [
                    {
                        "notification_id": n.notification_id,
                        "notification_type": n.notification_type,
                        "priority": n.priority,
                        "channels": n.channels.split(",") if n.channels else [],
                        "recipients": frappe.parse_json(n.recipients) if n.recipients else [],
                        "subject": n.subject,
                        "delivery_status": n.delivery_status,
                        "created_at": str(n.creation),
                        "delivered_at": str(n.delivered_at) if n.delivered_at else None,
                        "error_message": frappe.parse_json(n.error_message) if n.error_message else None,
                    }
                    for n in notifications
                ],
                "total_notifications": len(notifications),
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


# Convenience functions for common notifications


def notify_batch_success(batch_name: str, **context):
    """Send batch success notification"""
    manager = SEPANotificationManager()
    return manager.send_notification(NotificationType.BATCH_SUCCESS, {"batch_name": batch_name, **context})


def notify_batch_failure(batch_name: str, error_message: str, **context):
    """Send batch failure notification"""
    manager = SEPANotificationManager()
    return manager.send_notification(
        NotificationType.BATCH_FAILURE,
        {
            "batch_name": batch_name,
            "error_message": error_message,
            "error_type": context.get("error_type", "Unknown"),
            "action_required": context.get("action_required", "Please investigate immediately"),
            **context,
        },
        priority=NotificationPriority.CRITICAL,
    )


def notify_rollback_initiated(operation_id: str, batch_name: str, **context):
    """Send rollback initiated notification"""
    manager = SEPANotificationManager()
    return manager.send_notification(
        NotificationType.ROLLBACK_INITIATED,
        {"operation_id": operation_id, "batch_name": batch_name, **context},
    )


def notify_performance_alert(alert_type: str, **context):
    """Send performance alert notification"""
    manager = SEPANotificationManager()
    return manager.send_notification(
        NotificationType.PERFORMANCE_ALERT, {"alert_type": alert_type, **context}
    )


# API Functions


@frappe.whitelist()
@handle_api_error
def send_sepa_notification(notification_type: str, context: str, priority: str = None) -> Dict[str, Any]:
    """
    API endpoint to send SEPA notification

    Args:
        notification_type: Type of notification
        context: JSON string with context data
        priority: Optional priority override

    Returns:
        Notification result
    """
    import json

    try:
        parsed_context = json.loads(context) if isinstance(context, str) else context
        notification_type_enum = NotificationType(notification_type)
        priority_enum = NotificationPriority(priority) if priority else None

        manager = SEPANotificationManager()
        return manager.send_notification(notification_type_enum, parsed_context, priority_enum)

    except (ValueError, json.JSONDecodeError) as e:
        return {"success": False, "error": f"Invalid parameter: {str(e)}"}


@frappe.whitelist()
@handle_api_error
def get_sepa_notification_history(days_back: int = 7, notification_type: str = None) -> Dict[str, Any]:
    """
    API endpoint to get notification history

    Args:
        days_back: Number of days to look back
        notification_type: Filter by notification type

    Returns:
        Notification history
    """
    manager = SEPANotificationManager()
    return manager.get_notification_history(days_back, notification_type)


@frappe.whitelist()
@handle_api_error
def test_sepa_notification_system() -> Dict[str, Any]:
    """
    API endpoint to test notification system

    Returns:
        Test results
    """
    manager = SEPANotificationManager()

    # Send test notification
    test_context = {
        "batch_name": "TEST_BATCH",
        "collection_date": today(),
        "total_amount": 1000.00,
        "transaction_count": 10,
        "processing_time": "30 seconds",
    }

    result = manager.send_notification(NotificationType.BATCH_SUCCESS, test_context)

    return {
        "success": result["success"],
        "test_result": result,
        "message": "Test notification sent" if result["success"] else "Test notification failed",
    }
