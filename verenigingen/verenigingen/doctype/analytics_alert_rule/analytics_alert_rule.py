# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import add_to_date, get_datetime, now_datetime


class AnalyticsAlertRule(Document):
    def validate(self):
        # Validate threshold value based on metric type
        if self.metric in ["Churn Rate", "Growth Rate", "Payment Failure Rate", "Goal Achievement"]:
            if self.threshold_value < 0 or self.threshold_value > 100:
                frappe.throw("Percentage metrics must be between 0 and 100")

    def check_and_trigger(self):
        """Check if alert conditions are met and trigger if necessary"""
        if not self.is_active:
            return

        # Check if it's time to check based on frequency
        if not self.should_check():
            return

        # Get current metric value
        current_value = self.get_metric_value()

        # Check if condition is met
        if self.evaluate_condition(current_value):
            self.trigger_alert(current_value)

        # Update last checked time
        self.db_set("last_checked", now_datetime())

    def should_check(self):
        """Check if it's time to run this alert based on frequency"""
        if not self.last_checked:
            return True

        last_checked = get_datetime(self.last_checked)
        now = get_datetime()

        frequency_hours = {"Hourly": 1, "Daily": 24, "Weekly": 168, "Monthly": 720}

        hours_passed = (now - last_checked).total_seconds() / 3600
        return hours_passed >= frequency_hours.get(self.check_frequency, 24)

    def get_metric_value(self):
        """Get the current value of the monitored metric"""
        if self.metric == "Total Members":
            return frappe.db.count("Member", {"status": "Active"})

        elif self.metric == "New Members":
            # New members in the last period based on check frequency
            period_days = {"Hourly": 1, "Daily": 1, "Weekly": 7, "Monthly": 30}
            days = period_days.get(self.check_frequency, 1)

            return frappe.db.count(
                "Member",
                {
                    "member_since": [">=", add_to_date(now_datetime(), days=-days)],
                    "status": ["!=", "Rejected"],
                },
            )

        elif self.metric == "Churn Rate":
            return self.calculate_churn_rate()

        elif self.metric == "Revenue":
            return self.calculate_current_revenue()

        elif self.metric == "Growth Rate":
            return self.calculate_growth_rate()

        elif self.metric == "Payment Failure Rate":
            return self.calculate_payment_failure_rate()

        elif self.metric == "Member Engagement":
            return self.calculate_engagement_score()

        elif self.metric == "Goal Achievement":
            return self.calculate_goal_achievement()

        return 0

    def evaluate_condition(self, current_value):
        """Evaluate if the condition is met"""
        threshold = self.threshold_value

        if self.condition == "Greater Than":
            return current_value > threshold
        elif self.condition == "Less Than":
            return current_value < threshold
        elif self.condition == "Equals":
            return abs(current_value - threshold) < 0.01
        elif self.condition in ["Increases By", "Decreases By", "Changes By"]:
            # Need historical value
            previous_value = self.get_previous_value()
            if previous_value is None:
                return False

            change = current_value - previous_value
            change_pct = (change / previous_value * 100) if previous_value != 0 else 0

            if self.condition == "Increases By":
                return change_pct >= threshold
            elif self.condition == "Decreases By":
                return change_pct <= -threshold
            elif self.condition == "Changes By":
                return abs(change_pct) >= threshold

        return False

    def trigger_alert(self, current_value):
        """Trigger the alert actions"""
        # Update last triggered
        self.db_set("last_triggered", now_datetime())

        # Prepare alert data
        alert_data = {
            "rule": self.rule_name,
            "metric": self.metric,
            "value": current_value,
            "threshold": self.threshold_value,
            "condition": self.condition,
            "timestamp": now_datetime(),
        }

        # Send notifications
        if self.send_email or self.send_system_notification:
            self.send_notifications(alert_data)

        # Execute automated actions
        if self.automated_actions:
            self.execute_automated_actions(alert_data)

        # Call webhook if configured
        if self.webhook_url:
            self.call_webhook(alert_data)

        # Execute custom script if provided
        if self.custom_script:
            self.execute_custom_script(alert_data)

        # Log the alert
        self.log_alert(alert_data)

    def send_notifications(self, alert_data):
        """Send email and system notifications"""
        message = self.format_message(alert_data)

        recipients = [r.recipient for r in self.alert_recipients if r.recipient]

        if self.send_system_notification:
            for recipient in recipients:
                notification = frappe.get_doc(
                    {
                        "doctype": "Notification Log",
                        "subject": f"Analytics Alert: {self.rule_name}",
                        "for_user": recipient,
                        "type": "Alert",
                        "document_type": "Analytics Alert Rule",
                        "document_name": self.name,
                        "from_user": "Administrator",
                        "email_content": message,
                    }
                )
                notification.insert(ignore_permissions=True)

        if self.send_email and recipients:
            frappe.sendmail(
                recipients=recipients,
                subject=f"Analytics Alert: {self.rule_name}",
                message=message,
                delayed=False,
            )

    def format_message(self, alert_data):
        """Format the alert message using template"""
        template = self.alert_message_template or "Alert: {metric} is {value} (threshold: {threshold})"

        # Calculate change if applicable
        change = ""
        if self.condition in ["Increases By", "Decreases By", "Changes By"]:
            previous = self.get_previous_value()
            if previous:
                change_val = alert_data["value"] - previous
                change_pct = (change_val / previous * 100) if previous != 0 else 0
                change = f"{change_pct:+.1f}%"

        return template.format(
            metric=alert_data["metric"],
            value=alert_data["value"],
            threshold=alert_data["threshold"],
            change=change,
        )

    def execute_automated_actions(self, alert_data):
        """Execute configured automated actions"""
        for action in self.automated_actions:
            try:
                if action.action_type == "Create Task":
                    self.create_task(action, alert_data)
                elif action.action_type == "Update Field":
                    self.update_field(action, alert_data)
                elif action.action_type == "Run Report":
                    self.run_report(action, alert_data)
                elif action.action_type == "Send Campaign":
                    self.trigger_campaign(action, alert_data)
            except Exception as e:
                frappe.log_error(f"Failed to execute action {action.action_type}: {str(e)}")

    def call_webhook(self, alert_data):
        """Call configured webhook URL"""
        try:
            import requests

            response = requests.post(self.webhook_url, json=alert_data, timeout=30)
            response.raise_for_status()
        except Exception as e:
            frappe.log_error(f"Webhook call failed: {str(e)}")

    def execute_custom_script(self, alert_data):
        """Execute custom Python script with security restrictions"""
        # SECURITY: Disable exec() for security reasons
        # TODO: Implement safer alternative like sandboxed execution or whitelist approach
        frappe.log_error(
            "Custom script execution disabled for security reasons. Contact administrator to implement safer alternative."
        )
        frappe.throw(
            "Custom script execution is disabled for security reasons. Please contact your system administrator."
        )

    def log_alert(self, alert_data):
        """Log the alert for audit trail"""
        frappe.get_doc(
            {
                "doctype": "Analytics Alert Log",
                "alert_rule": self.name,
                "triggered_at": alert_data["timestamp"],
                "metric_value": alert_data["value"],
                "threshold_value": alert_data["threshold"],
                "condition": alert_data["condition"],
                "alert_data": frappe.as_json(alert_data),
            }
        ).insert(ignore_permissions=True)

    # Helper methods for metric calculations
    def calculate_churn_rate(self):
        """Calculate current churn rate"""
        period_days = {"Hourly": 1, "Daily": 30, "Weekly": 30, "Monthly": 365}
        days = period_days.get(self.check_frequency, 30)

        active_members = frappe.db.count("Member", {"status": "Active"})
        terminated = frappe.db.count(
            "Membership Termination Request",
            {"status": "Completed", "termination_date": [">=", add_to_date(now_datetime(), days=-days)]},
        )

        return (terminated / active_members * 100) if active_members > 0 else 0

    def calculate_current_revenue(self):
        """Calculate current monthly revenue"""
        result = frappe.db.sql(
            """
            SELECT SUM(grand_total) as total
            FROM `tabSales Invoice`
            WHERE member IS NOT NULL
            AND docstatus = 1
            AND posting_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
        """
        )[0][0]

        return result or 0

    def calculate_growth_rate(self):
        """Calculate member growth rate"""
        current_members = frappe.db.count("Member", {"status": "Active"})

        # Members 30 days ago
        past_members = frappe.db.sql(
            """
            SELECT COUNT(*)
            FROM `tabMember`
            WHERE status = 'Active'
            AND member_since <= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
        """
        )[0][0]

        if past_members > 0:
            return ((current_members - past_members) / past_members) * 100
        return 0

    def calculate_payment_failure_rate(self):
        """Calculate recent payment failure rate"""
        total_invoices = frappe.db.count(
            "Sales Invoice",
            {
                "member": ["!=", ""],
                "docstatus": 1,
                "posting_date": [">=", add_to_date(now_datetime(), days=-30)],
            },
        )

        failed_invoices = frappe.db.count(
            "Sales Invoice",
            {
                "member": ["!=", ""],
                "status": "Overdue",
                "posting_date": [">=", add_to_date(now_datetime(), days=-30)],
            },
        )

        return (failed_invoices / total_invoices * 100) if total_invoices > 0 else 0

    def calculate_engagement_score(self):
        """Calculate average member engagement score"""
        # Simplified - would need actual engagement tracking
        return 75.0

    def calculate_goal_achievement(self):
        """Calculate average goal achievement percentage"""
        current_year = frappe.utils.now_datetime().year
        goals = frappe.get_all(
            "Membership Goal",
            filters={"goal_year": current_year, "status": ["!=", "Cancelled"]},
            fields=["achievement_percentage"],
        )

        if goals:
            return sum(g.achievement_percentage for g in goals) / len(goals)
        return 0

    def get_previous_value(self):
        """Get previous value for comparison"""
        # Look for previous log entry
        last_log = frappe.get_all(
            "Analytics Alert Log",
            filters={"alert_rule": self.name},
            fields=["metric_value"],
            order_by="triggered_at desc",
            limit=1,
        )

        if last_log:
            return last_log[0].metric_value
        return None

    def create_task(self, action, alert_data):
        """Create a task based on alert"""
        task = frappe.get_doc(
            {
                "doctype": "Task",
                "subject": action.task_subject or f"Alert: {self.rule_name}",
                "description": self.format_message(alert_data),
                "priority": action.task_priority or "Medium",
                "status": "Open",
            }
        )
        task.insert(ignore_permissions=True)

    def update_field(self, action, alert_data):
        """Update a field in a document"""
        if action.target_doctype and action.target_field:
            # This is a simplified example
            # In practice, you'd need more sophisticated targeting
            pass

    def run_report(self, action, alert_data):
        """Run and distribute a report"""
        if action.report_name:
            # Queue report generation
            frappe.enqueue(method="frappe.desk.query_report.run", report_name=action.report_name, filters={})

    def trigger_campaign(self, action, alert_data):
        """Trigger a marketing campaign"""
        # This would integrate with campaign management
        # For now, just log the intent
        frappe.log_error(f"Campaign trigger requested: {action.campaign_name}")


@frappe.whitelist()
def check_all_active_alerts():
    """Check all active alert rules - called by scheduler"""
    active_rules = frappe.get_all("Analytics Alert Rule", filters={"is_active": 1}, fields=["name"])

    for rule in active_rules:
        try:
            alert = frappe.get_doc("Analytics Alert Rule", rule.name)
            alert.check_and_trigger()
        except Exception as e:
            frappe.log_error(f"Error checking alert rule {rule.name}: {str(e)}")
