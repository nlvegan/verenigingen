"""
SEPA Direct Debit Batch Scheduler
Automated scheduling and management of optimized batch creation
"""


import frappe
from frappe import _
from frappe.utils import add_days, get_weekday, getdate, now_datetime

from verenigingen.api.dd_batch_optimizer import DEFAULT_CONFIG, create_optimal_batches


def daily_batch_optimization():
    """
    Daily scheduled task for automatic batch creation
    Called by Frappe scheduler (hooks.py)
    """
    try:
        # Check if auto-creation is enabled
        settings = frappe.get_single("Verenigingen Settings")
        if not getattr(settings, "enable_auto_batch_creation", False):
            frappe.logger().info("Auto batch creation is disabled")
            return

        # Don't create batches on weekends or holidays
        if should_skip_batch_creation():
            frappe.logger().info("Skipping batch creation - weekend or holiday")
            return

        # Get configuration
        config = get_scheduler_config()

        # Calculate target date (usually next business day)
        target_date = get_next_business_day()

        frappe.logger().info(f"Starting scheduled batch optimization for {target_date}")

        # Create optimal batches
        result = create_optimal_batches(target_date=target_date, config=config)

        if result["success"] and result["batches_created"] > 0:
            # Send notification to finance team
            send_batch_creation_notification(result)

            # Log successful creation
            frappe.logger().info(f"Auto-created {result['batches_created']} batches for {target_date}")

            # Create system notification
            create_system_notification(result)
        else:
            frappe.logger().info("No batches created - no eligible invoices")

    except Exception as e:
        frappe.log_error(f"Error in daily batch optimization: {str(e)}", "Batch Scheduler Error")


def should_skip_batch_creation():
    """Check if batch creation should be skipped today"""
    today = getdate()
    weekday = get_weekday(today)

    # Skip weekends (Saturday = 5, Sunday = 6)
    if weekday >= 5:
        return True

    # Check for holidays (this could be enhanced with a holiday calendar)
    if is_bank_holiday(today):
        return True

    return False


def is_bank_holiday(date):
    """Check if date is a bank holiday (basic implementation)"""
    # This is a simplified version - in production you'd check against
    # a proper holiday calendar for your country

    # Common fixed holidays in Netherlands
    year = date.year
    holidays = [
        f"{year}-01-01",  # New Year's Day
        f"{year}-04-27",  # King's Day
        f"{year}-05-05",  # Liberation Day (every 5 years)
        f"{year}-12-25",  # Christmas
        f"{year}-12-26",  # Boxing Day
    ]

    return date.strftime("%Y-%m-%d") in holidays


def get_next_business_day():
    """Get next business day for batch processing"""
    tomorrow = add_days(getdate(), 1)

    # If tomorrow is weekend, move to Monday
    while get_weekday(tomorrow) >= 5:  # Saturday or Sunday
        tomorrow = add_days(tomorrow, 1)

    return tomorrow


def get_scheduler_config():
    """Get configuration for scheduled batch creation"""
    try:
        settings = frappe.get_single("Verenigingen Settings")
        if hasattr(settings, "batch_optimization_config") and settings.batch_optimization_config:
            config = frappe.parse_json(settings.batch_optimization_config)
        else:
            config = DEFAULT_CONFIG.copy()

        # Scheduler-specific adjustments
        scheduler_config = config.copy()

        # More conservative limits for automated creation
        scheduler_config["max_amount_per_batch"] = min(3000, config.get("max_amount_per_batch", 4000))
        scheduler_config["max_invoices_per_batch"] = min(15, config.get("max_invoices_per_batch", 20))
        scheduler_config["preferred_batch_size"] = 10  # Smaller batches for auto-creation

        return scheduler_config

    except Exception as e:
        frappe.logger().warning(f"Error loading scheduler config, using defaults: {str(e)}")
        return DEFAULT_CONFIG


def send_batch_creation_notification(result):
    """Send email notification about created batches"""
    try:
        # Get finance team members
        finance_managers = frappe.get_all(
            "User",
            filters={
                "enabled": 1,
                "name": [
                    "in",
                    frappe.get_list("Has Role", filters={"role": "Finance Manager"}, pluck="parent"),
                ],
            },
            fields=["email", "full_name"],
        )

        if not finance_managers:
            return

        # Prepare email content
        subject = f"Auto-created {result['batches_created']} SEPA Direct Debit batches"

        optimization_report = result.get("optimization_report", {})
        optimization_report.get("summary", {})

        message = """
        <h3>Automated Batch Creation Summary</h3>

        <p><strong>Date:</strong> {now_datetime().strftime('%Y-%m-%d %H:%M')}</p>

        <h4>Results:</h4>
        <ul>
            <li><strong>Batches Created:</strong> {result['batches_created']}</li>
            <li><strong>Total Invoices:</strong> {result['total_invoices']}</li>
            <li><strong>Total Amount:</strong> €{summary.get('total_amount_processed', 0):,.2f}</li>
            <li><strong>Average Batch Size:</strong> {summary.get('average_batch_size', 0):.1f} invoices</li>
            <li><strong>Efficiency Score:</strong> {summary.get('efficiency_score', 0)}/100</li>
        </ul>

        <h4>Created Batches:</h4>
        <table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse;">
            <tr>
                <th>Batch Name</th>
                <th>Invoices</th>
                <th>Amount</th>
                <th>Risk Level</th>
            </tr>
        """

        batch_details = optimization_report.get("batch_details", [])
        for batch in batch_details:
            message += """
            <tr>
                <td>{batch['name']}</td>
                <td>{batch['invoice_count']}</td>
                <td>€{batch['total_amount']:,.2f}</td>
                <td>{batch['risk_level']}</td>
            </tr>
            """

        message += """
        </table>

        <p><strong>Next Steps:</strong></p>
        <ul>
            <li>Review and approve batches in the system</li>
            <li>Submit approved batches for SEPA processing</li>
            <li>Monitor payment status</li>
        </ul>

        <p><em>This is an automated notification from the batch optimization system.</em></p>
        """

        # Send email to finance team
        for manager in finance_managers:
            frappe.sendmail(recipients=[manager.email], subject=subject, message=message, delayed=False)

    except Exception as e:
        frappe.log_error(f"Error sending batch notification: {str(e)}", "Batch Notification Error")


def create_system_notification(result):
    """Create in-system notification for batch creation"""
    try:
        # Create notification for Finance Manager role
        notification = frappe.get_doc(
            {
                "doctype": "Notification Log",
                "subject": f"Auto-created {result['batches_created']} DD batches",
                "type": "Alert",
                "document_type": "SEPA Direct Debit Batch",
                "document_name": result.get("batch_names", [None])[0] if result.get("batch_names") else None,
                "from_user": "Administrator",
                "for_user": "",  # Will be set per user below
                "read": 0,
            }
        )

        # Get users with Finance Manager role
        finance_users = frappe.get_list("Has Role", filters={"role": "Finance Manager"}, pluck="parent")

        for user in finance_users:
            notification_copy = notification.copy()
            notification_copy.for_user = user
            notification_copy.insert(ignore_permissions=True)

    except Exception as e:
        frappe.log_error(f"Error creating system notification: {str(e)}", "System Notification Error")


@frappe.whitelist()
def get_batch_creation_schedule():
    """Get the current schedule for automatic batch creation"""
    settings = frappe.get_single("Verenigingen Settings")

    return {
        "enabled": getattr(settings, "enable_auto_batch_creation", False),
        "schedule": "Daily at 18:00 (weekdays only)",
        "next_run": get_next_business_day(),
        "config": get_scheduler_config(),
        "last_run": getattr(settings, "last_batch_creation_run", None),
    }


@frappe.whitelist()
def toggle_auto_batch_creation(enabled):
    """Enable or disable automatic batch creation"""
    settings = frappe.get_single("Verenigingen Settings")
    settings.enable_auto_batch_creation = int(enabled)
    settings.save()

    action = "enabled" if enabled else "disabled"
    frappe.logger().info(f"Auto batch creation {action} by {frappe.session.user}")

    return {"success": True, "message": f"Auto batch creation {action}", "enabled": bool(enabled)}


@frappe.whitelist()
def run_batch_creation_now():
    """Manually trigger batch creation (for testing/emergency use)"""
    try:
        # Check permissions
        if not frappe.has_permission("SEPA Direct Debit Batch", "create"):
            frappe.throw(_("You don't have permission to create batches"))

        # Get configuration
        config = get_scheduler_config()
        target_date = get_next_business_day()

        # Create batches
        result = create_optimal_batches(target_date=target_date, config=config)

        if result["success"]:
            # Update last run timestamp
            settings = frappe.get_single("Verenigingen Settings")
            settings.last_batch_creation_run = now_datetime()
            settings.save()

            # Send notification
            send_batch_creation_notification(result)

            return {
                "success": True,
                "message": f"Created {result['batches_created']} batches",
                "result": result,
            }
        else:
            return {"success": False, "message": result.get("error", "Unknown error"), "result": result}

    except Exception as e:
        frappe.log_error(f"Error in manual batch creation: {str(e)}", "Manual Batch Creation Error")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_batch_optimization_stats():
    """Get statistics about batch optimization performance"""
    try:
        # Get batches created in last 30 days
        recent_batches = frappe.get_all(
            "SEPA Direct Debit Batch",
            filters={
                "creation": [">=", add_days(getdate(), -30)],
                "batch_description": ["like", "%Auto-optimized%"],
            },
            fields=["name", "total_amount", "entry_count", "creation", "workflow_state"],
        )

        if not recent_batches:
            return {
                "success": True,
                "stats": {
                    "total_batches": 0,
                    "total_amount": 0,
                    "total_invoices": 0,
                    "average_batch_size": 0,
                    "success_rate": 0,
                },
            }

        total_amount = sum(batch.total_amount for batch in recent_batches)
        total_invoices = sum(batch.entry_count for batch in recent_batches)
        processed_batches = len([b for b in recent_batches if b.workflow_state in ["Completed", "Submitted"]])

        stats = {
            "total_batches": len(recent_batches),
            "total_amount": total_amount,
            "total_invoices": total_invoices,
            "average_batch_size": total_invoices / len(recent_batches) if recent_batches else 0,
            "success_rate": (processed_batches / len(recent_batches) * 100) if recent_batches else 0,
            "recent_batches": recent_batches[:10],  # Last 10 batches
        }

        return {"success": True, "stats": stats}

    except Exception as e:
        frappe.log_error(f"Error getting optimization stats: {str(e)}", "Batch Stats Error")
        return {"success": False, "error": str(e)}
