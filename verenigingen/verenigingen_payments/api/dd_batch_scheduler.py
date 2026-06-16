"""
SEPA Direct Debit Batch Scheduler
Automated scheduling and management of optimized batch creation
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, get_weekday, getdate, now_datetime

from verenigingen.services.communication.email_service import get_email_service
from verenigingen.utils.constants import Roles
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)
from verenigingen.utils.security.authorization import (
    SEPAOperation,
    SEPAPermissionLevel,
    require_sepa_permission,
)
from verenigingen.utils.settings_utils import get_payments_settings
from verenigingen.verenigingen_payments.api.dd_batch_optimizer import DEFAULT_CONFIG, create_optimal_batches


def daily_batch_optimization():
    """
    Daily scheduled task for automatic batch creation
    Called by Frappe scheduler (hooks.py) - runs in early morning hours (typically 00:00-02:00 AM server time)
    Checks if today is a configured batch creation day
    """
    from verenigingen.utils.db_advisory_lock import get_lock, release_lock

    if not get_lock("sched_daily_batch_optimization", timeout=0):
        frappe.logger().info("daily_batch_optimization already running, skipping")
        return

    try:
        return _daily_batch_optimization_impl()
    finally:
        release_lock("sched_daily_batch_optimization")


def _daily_batch_optimization_impl():
    try:
        # Check if auto-creation is enabled
        payments_settings = get_payments_settings()
        if not getattr(payments_settings, "enable_auto_batch_creation", False):
            frappe.logger().info("Auto batch creation is disabled")
            return

        # Check if today is a configured batch creation day
        if not is_batch_creation_day():
            frappe.logger().info("Not a scheduled batch creation day")
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

        # Create optimal batches with enhanced validation
        result = create_optimal_batches(target_date=target_date, config=config)

        if result["success"] and result["batches_created"] > 0:
            # Process validation results for each created batch
            validation_summary = {"blocked": 0, "processed_with_warnings": 0, "processed": 0}

            for batch_name in result.get("batch_names", []):
                try:
                    batch = frappe.get_doc("Direct Debit Batch", batch_name)

                    # Extract validation results
                    critical_errors = []
                    warnings = []

                    if batch.validation_errors:
                        critical_errors = frappe.parse_json(batch.validation_errors)
                    if batch.validation_warnings:
                        warnings = frappe.parse_json(batch.validation_warnings)

                    # Handle validation results in automated context
                    from verenigingen.verenigingen_payments.api.sepa_batch_notifications import (
                        handle_automated_batch_validation,
                    )

                    action_result = handle_automated_batch_validation(batch, critical_errors, warnings)

                    # Track results
                    action_type = action_result["action"].split("_")[0]  # "blocked", "processed", etc.
                    if action_type in validation_summary:
                        validation_summary[action_type] += 1
                    elif action_result["action"] == "processed_with_warnings":
                        validation_summary["processed_with_warnings"] += 1

                except Exception as e:
                    frappe.log_error(
                        f"Error processing validation for batch {batch_name}: {str(e)}",
                        "Batch Validation Processing",
                    )
                    validation_summary["blocked"] += 1

            # Update last run timestamp
            payments_settings.last_batch_creation_run = now_datetime()
            payments_settings.save()

            # Send enhanced daily summary
            from verenigingen.verenigingen_payments.api.sepa_batch_notifications import (
                send_daily_batch_summary,
            )

            send_daily_batch_summary(validation_summary, result)

            # Log successful creation with validation summary
            frappe.logger().info(
                f"Auto-created {result['batches_created']} batches for {target_date} - "
                f"Processed: {validation_summary['processed']}, "
                f"Warnings: {validation_summary['processed_with_warnings']}, "
                f"Blocked: {validation_summary['blocked']}"
            )
        else:
            frappe.logger().info("No batches created - no eligible invoices")

    except Exception as e:
        frappe.log_error(f"Error in daily batch optimization: {str(e)}", "Batch Scheduler Error")

        # Send system error notification
        from verenigingen.verenigingen_payments.api.sepa_batch_notifications import (
            send_system_error_notification,
        )

        send_system_error_notification(str(e))


def is_batch_creation_day():
    """Check if today is a configured batch creation day"""
    try:
        payments_settings = get_payments_settings()
        batch_creation_days = getattr(payments_settings, "batch_creation_days", "1")

        if not batch_creation_days:
            # Default to 1st of month if not configured
            batch_creation_days = "1"

        # Parse comma-separated list of days
        configured_days = []
        for day_str in batch_creation_days.split(","):
            try:
                day = int(day_str.strip())
                if 1 <= day <= 31:
                    configured_days.append(day)
                else:
                    frappe.logger().warning(f"Invalid batch creation day configured: {day}")
            except ValueError:
                frappe.logger().warning(f"Invalid batch creation day format: {day_str}")

        if not configured_days:
            frappe.logger().warning("No valid batch creation days configured, defaulting to 1st")
            configured_days = [1]

        today = getdate()
        current_day = today.day

        # Check if current day matches any configured day
        is_creation_day = current_day in configured_days

        frappe.logger().info(
            f"Batch creation check: Day {current_day}, configured days: {configured_days}, matches: {is_creation_day}"
        )

        return is_creation_day

    except Exception as e:
        frappe.log_error(f"Error checking batch creation day: {str(e)}", "Batch Creation Day Check")
        # Default to 1st of month on error
        return getdate().day == 1


def _weekday_number(date):
    """Return the numeric weekday (Mon=0 .. Sun=6) for a date.

    frappe.utils.get_weekday() returns the weekday NAME (e.g. "Sunday") in this
    environment, so callers that compare against integers (weekend = 5/6) must
    normalize it. Centralizes the name->number map that get_next_batch_creation_date
    already carried inline, so should_skip_batch_creation / get_next_business_day
    don't crash with a str-vs-int TypeError.
    """
    weekday = get_weekday(date)
    if isinstance(weekday, str):
        weekday_map = {
            "Monday": 0,
            "Tuesday": 1,
            "Wednesday": 2,
            "Thursday": 3,
            "Friday": 4,
            "Saturday": 5,
            "Sunday": 6,
        }
        return weekday_map.get(weekday, 0)
    return weekday


def get_next_batch_creation_date(configured_days):
    """Calculate the next date when batch creation should run"""
    import calendar

    from frappe.utils import add_months

    today = getdate()
    current_day = today.day
    current_month = today.month
    current_year = today.year

    # Find next creation day in current month
    for day in sorted(configured_days):
        if day > current_day:
            # Check if it's a weekday and not a holiday
            next_date = getdate(f"{current_year}-{current_month:02d}-{day:02d}")
            if _weekday_number(next_date) < 5 and not is_bank_holiday(next_date):
                return next_date

    # No more days in current month, check next month
    next_month_date = add_months(today, 1)
    next_month = next_month_date.month
    next_year = next_month_date.year

    # Get days in next month to handle February/30-day months
    days_in_month = calendar.monthrange(next_year, next_month)[1]

    for day in sorted(configured_days):
        if day <= days_in_month:
            next_date = getdate(f"{next_year}-{next_month:02d}-{day:02d}")
            if _weekday_number(next_date) < 5 and not is_bank_holiday(next_date):
                return next_date

    # Fallback to first of next month if no valid days found
    return getdate(f"{next_year}-{next_month:02d}-01")


def should_skip_batch_creation():
    """Check if batch creation should be skipped today"""
    today = getdate()
    weekday = _weekday_number(today)

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
    while _weekday_number(tomorrow) >= 5:  # Saturday or Sunday
        tomorrow = add_days(tomorrow, 1)

    return tomorrow


def get_scheduler_config():
    """Get configuration for scheduled batch creation"""
    try:
        payments_settings = get_payments_settings()
        if (
            hasattr(payments_settings, "batch_optimization_config")
            and payments_settings.batch_optimization_config
        ):
            config = frappe.parse_json(payments_settings.batch_optimization_config)
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
                    frappe.get_list("Has Role", filters={"role": Roles.FINANCIAL_MANAGER}, pluck="parent"),
                ],
            },
            fields=["email", "full_name"],
        )

        if not finance_managers:
            return

        # Prepare email content
        subject = f"Auto-created {result['batches_created']} SEPA Direct Debit batches"

        optimization_report = result.get("optimization_report", {})
        summary = optimization_report.get("summary", {})

        message = f"""
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
            message += f"""
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
        email_service = get_email_service()
        for manager in finance_managers:
            email_service.send_simple_email(
                recipients=[manager.email],
                subject=subject,
                message=message,
                delayed=False,
                notification_key="sepa_batch_scheduler_alert",
            )

    except Exception as e:
        frappe.log_error(f"Error sending batch notification: {str(e)}", "Batch Notification Error")


def create_system_notification(result):
    """Create in-system notification for batch creation"""
    try:
        # Create notification for Verenigingen Financial Manager role
        notification = frappe.get_doc(
            {
                "doctype": "Notification Log",
                "subject": f"Auto-created {result['batches_created']} DD batches",
                "type": "Alert",
                "document_type": "Direct Debit Batch",
                "document_name": result.get("batch_names", [None])[0] if result.get("batch_names") else None,
                "from_user": "Administrator",
                "for_user": "",  # Will be set per user below
                "read": 0,
            }
        )

        # Get users with Verenigingen Financial Manager role
        finance_users = frappe.get_list("Has Role", filters={"role": Roles.FINANCIAL_MANAGER}, pluck="parent")

        for user in finance_users:
            notification_copy = notification.copy()
            notification_copy.for_user = user
            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            notification_result = secure_document_operation(
                operation="insert",
                doc=notification_copy,
                justification=f"Create system notification for batch creation - user {user} - {result['batches_created']} batches created",
                required_permissions=["Notification Log:create"],
            )
            if not notification_result.success:
                frappe.log_error(
                    f"Failed to create notification for user {user}: {'; '.join(notification_result.errors)}",
                    "Batch Notification Error",
                )

    except Exception as e:
        frappe.log_error(f"Error creating system notification: {str(e)}", "System Notification Error")


@standard_api(operation_type=OperationType.REPORTING)
@require_sepa_permission(SEPAPermissionLevel.READ, SEPAOperation.BATCH_VALIDATE)
@frappe.whitelist()
def get_batch_creation_schedule():
    """Get the current schedule for automatic batch creation"""
    payments_settings = get_payments_settings()

    # Get configured days
    batch_creation_days = getattr(payments_settings, "batch_creation_days", "1")
    if not batch_creation_days:
        batch_creation_days = "1"

    # Parse and validate days
    configured_days = []
    for day_str in batch_creation_days.split(","):
        try:
            day_str_clean = day_str.strip()
            if day_str_clean:  # Skip empty strings
                day = int(day_str_clean)
                if 1 <= day <= 31:
                    configured_days.append(day)
        except (ValueError, TypeError):
            pass

    if not configured_days:
        configured_days = [1]

    # Create schedule description
    if len(configured_days) == 1:
        schedule_desc = f"Monthly on day {configured_days[0]} (early morning, weekdays only)"
    elif len(configured_days) == 2:
        schedule_desc = (
            f"Monthly on days {configured_days[0]} and {configured_days[1]} (early morning, weekdays only)"
        )
    else:
        days_str = ", ".join(str(d) for d in configured_days[:-1]) + f" and {configured_days[-1]}"
        schedule_desc = f"Monthly on days {days_str} (early morning, weekdays only)"

    # Calculate next run date
    next_run = get_next_batch_creation_date(configured_days)

    return {
        "enabled": getattr(payments_settings, "enable_auto_batch_creation", False),
        "schedule": schedule_desc,
        "configured_days": configured_days,
        "next_run": next_run,
        "config": get_scheduler_config(),
        "last_run": getattr(payments_settings, "last_batch_creation_run", None),
    }


@critical_api(operation_type=OperationType.ADMIN)
@require_sepa_permission(SEPAPermissionLevel.ADMIN, SEPAOperation.BATCH_CREATE)
@frappe.whitelist()
def toggle_auto_batch_creation(enabled):
    """Enable or disable automatic batch creation"""
    try:
        # Input validation
        if enabled is None:
            frappe.throw(_("Parameter 'enabled' is required"))

        # Validate enabled parameter is boolean-like
        from verenigingen.utils.boolean_utils import cbool

        try:
            enabled_bool = cbool(enabled)
        except Exception:
            frappe.throw(_("Parameter 'enabled' must be a boolean value (true/false, 1/0, yes/no)"))

        # Get and update settings
        payments_settings = get_payments_settings()
        payments_settings.enable_auto_batch_creation = enabled_bool
        payments_settings.save()

        action = "enabled" if enabled_bool else "disabled"
        frappe.logger().info(f"Auto batch creation {action} by {frappe.session.user}")

        return {"success": True, "message": f"Auto batch creation {action}", "enabled": bool(enabled_bool)}

    except Exception as e:
        frappe.log_error(f"Failed to toggle auto batch creation: {str(e)}")
        if hasattr(e, "message"):
            frappe.throw(e.message)
        else:
            frappe.throw(_("Failed to toggle auto batch creation. Please check the system logs."))


@critical_api(operation_type=OperationType.FINANCIAL)
@require_sepa_permission(SEPAPermissionLevel.CREATE, SEPAOperation.BATCH_CREATE)
@frappe.whitelist()
def run_batch_creation_now():
    """Manually trigger batch creation (for testing/emergency use)"""
    try:
        # Critical Security Fix: Enhanced input validation and sanitization

        # 1. Validate user session and context
        if not frappe.session or not frappe.session.user:
            return {"success": False, "error": "Invalid user session"}

        if frappe.session.user == "Guest":
            return {"success": False, "error": "Anonymous access not permitted for batch operations"}

        # 2. Enhanced permission validation
        if not frappe.has_permission("Direct Debit Batch", "create"):
            return {"success": False, "error": "You don't have permission to create batches"}

        # 3. Validate user has required roles (not just permissions)
        user_roles = frappe.get_roles(frappe.session.user)
        required_roles = [Roles.FINANCIAL_MANAGER, "SEPA Administrator", Roles.SYSTEM_MANAGER]
        if not any(role in required_roles for role in user_roles):
            return {
                "success": False,
                "error": f"Insufficient role permissions. Required: {', '.join(required_roles)}",
            }

        # 4. Input validation - ensure system is ready for batch creation
        if should_skip_batch_creation():
            return {"success": False, "error": "Batch creation is currently disabled or conditions not met"}

        # 5. Validate system state and configuration
        payments_settings = get_payments_settings()
        if not payments_settings:
            return {"success": False, "error": "System settings not found"}

        # 6. Validate we're not in a bank holiday
        target_date = get_next_business_day()
        if is_bank_holiday(target_date):
            return {"success": False, "error": f"Target date {target_date} is a bank holiday"}

        # 7. Rate limiting check - prevent abuse
        recent_runs = frappe.db.count(
            "Direct Debit Batch",
            {"creation": [">", add_to_date(now_datetime(), hours=-1)], "owner": frappe.session.user},
        )
        if recent_runs > 5:  # Max 5 manual runs per hour per user
            return {
                "success": False,
                "error": "Rate limit exceeded. Maximum 5 manual batch creations per hour.",
            }

        # Get configuration
        config = get_scheduler_config()

        # Create batches
        result = create_optimal_batches(target_date=target_date, config=config)

        if result["success"]:
            # Update last run timestamp
            payments_settings = get_payments_settings()
            payments_settings.last_batch_creation_run = now_datetime()
            payments_settings.save()

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


@standard_api(operation_type=OperationType.UTILITY)
@require_sepa_permission(SEPAPermissionLevel.READ, SEPAOperation.BATCH_VALIDATE)
@frappe.whitelist()
def validate_batch_creation_days(days_string):
    """Validate and parse batch creation days configuration"""
    try:
        if not days_string or not days_string.strip():
            return {"valid": False, "error": "Batch creation days cannot be empty", "parsed_days": []}

        configured_days = []
        invalid_days = []

        for day_str in days_string.split(","):
            day_str = day_str.strip()
            if not day_str:
                continue

            try:
                day = int(day_str)
                if 1 <= day <= 31:
                    if day not in configured_days:  # Avoid duplicates
                        configured_days.append(day)
                else:
                    invalid_days.append(day_str)
            except ValueError:
                invalid_days.append(day_str)

        if not configured_days:
            return {
                "valid": False,
                "error": "No valid days found. Please specify days between 1-31.",
                "parsed_days": [],
            }

        if invalid_days:
            return {
                "valid": False,
                "error": f"Invalid days found: {', '.join(invalid_days)}. Days must be between 1-31.",
                "parsed_days": configured_days,
            }

        # Sort days for display
        configured_days.sort()

        # Check for February 29th and 30th/31st in shorter months
        warnings = []
        if 29 in configured_days:
            warnings.append("Day 29 may be skipped in February during non-leap years")
        if 30 in configured_days:
            warnings.append("Day 30 may be skipped in February")
        if 31 in configured_days:
            warnings.append("Day 31 may be skipped in months with fewer than 31 days")

        return {
            "valid": True,
            "parsed_days": configured_days,
            "warnings": warnings,
            "preview": f"Batches will be created on day(s) {', '.join(map(str, configured_days))} of each month (weekdays only)",
        }

    except Exception as e:
        return {"valid": False, "error": f"Error validating days: {str(e)}", "parsed_days": []}


@standard_api(operation_type=OperationType.REPORTING)
@require_sepa_permission(SEPAPermissionLevel.READ, SEPAOperation.BATCH_VALIDATE)
@frappe.whitelist()
def get_batch_optimization_stats():
    """Get statistics about batch optimization performance"""
    try:
        # Get batches created in last 30 days
        recent_batches = frappe.get_all(
            "Direct Debit Batch",
            filters={
                "creation": [">=", add_days(getdate(), -30)],
                "batch_description": ["like", "%Auto-optimized%"],
            },
            fields=["name", "total_amount", "entry_count", "creation", "status"],
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
        processed_batches = len([b for b in recent_batches if b.status in ["Submitted", "Processed"]])

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


@standard_api(operation_type=OperationType.UTILITY)
@require_sepa_permission(SEPAPermissionLevel.READ, SEPAOperation.BATCH_VALIDATE)
@frappe.whitelist()
def test_batch_scheduler_config():
    """Test the batch scheduler configuration - for development/testing"""
    try:
        from frappe.utils import getdate

        results = {
            "validation_tests": [],
            "schedule_info": {},
            "today_check": {},
            "success": True,
            "errors": [],
        }

        # Test validation function
        test_cases = [
            ("1", True, "Single day"),
            ("1,15", True, "Two days"),
            ("1,5,10,15,20,25", True, "Multiple days"),
            ("1,32", False, "Invalid day 32"),
            ("abc,1", False, "Non-numeric input"),
            ("", False, "Empty input"),
            ("1,1,1", True, "Duplicate days (should be filtered)"),
            ("29,30,31", True, "End of month days (should show warnings)"),
        ]

        for test_input, expected_valid, description in test_cases:
            result = validate_batch_creation_days(test_input)
            test_result = {
                "input": test_input,
                "description": description,
                "expected_valid": expected_valid,
                "actual_valid": result["valid"],
                "passed": result["valid"] == expected_valid,
                "message": result.get("preview", result.get("error")),
                "warnings": result.get("warnings", []),
            }
            results["validation_tests"].append(test_result)

        # Test schedule information
        try:
            schedule_info = get_batch_creation_schedule()
            results["schedule_info"] = {
                "enabled": schedule_info.get("enabled", False),
                "schedule": schedule_info.get("schedule", "Not configured"),
                "configured_days": schedule_info.get("configured_days", []),
                "next_run": str(schedule_info.get("next_run", "Not calculated")),
                "last_run": str(schedule_info.get("last_run", "Never")),
            }
        except Exception as e:
            results["errors"].append(f"Schedule info error: {str(e)}")

        # Test day checking logic
        try:
            today = getdate()
            is_today = is_batch_creation_day()
            results["today_check"] = {
                "today": str(today),
                "day_of_month": today.day,
                "is_batch_creation_day": is_today,
            }
        except Exception as e:
            results["errors"].append(f"Day check error: {str(e)}")

        # Summary
        passed_tests = sum(1 for test in results["validation_tests"] if test["passed"])
        total_tests = len(results["validation_tests"])
        results["summary"] = f"Passed {passed_tests}/{total_tests} validation tests"

        return results

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}
