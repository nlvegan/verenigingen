import frappe
from frappe import _
from frappe.utils import add_days, getdate, today

from verenigingen.utils.error_handling import mask_iban
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, development_only_api


class SEPAMandateNotificationManager:
    """Manages notifications for SEPA mandate status changes"""

    def __init__(self):
        # Cache settings to avoid repeated DB queries
        self.settings = None
        self._template_cache = {}

    def _get_settings(self):
        """Get cached settings with fallback"""
        if not self.settings:
            try:
                self.settings = frappe.get_single("Verenigingen Settings")
            except frappe.DoesNotExistError:
                # Fallback if settings don't exist
                self.settings = type(
                    "MockSettings",
                    (),
                    {"company_name": "Verenigingen", "support_email": "support@verenigingen.org"},
                )()
        return self.settings

    def _get_template(self, template_name):
        """Get cached template"""
        if template_name not in self._template_cache:
            template_path = f"verenigingen/verenigingen_payments/templates/emails/{template_name}.html"
            try:
                with open(
                    frappe.get_app_path("verenigingen", template_path.replace("verenigingen/", ""))
                ) as f:
                    self._template_cache[template_name] = f.read()
            except FileNotFoundError:
                # Fallback to frappe.render_template for dynamic loading
                self._template_cache[template_name] = None
        return self._template_cache[template_name]

    def _load_member_data_bulk(self, member_names):
        """Load member data in bulk to reduce queries"""
        if not member_names:
            return {}

        # Use single query to load all member data
        member_data = frappe.db.sql(
            """
            SELECT name, full_name, email
            FROM `tabMember`
            WHERE name IN %(member_names)s
            """,
            {"member_names": member_names},
            as_dict=True,
        )

        return {member["name"]: member for member in member_data}

    def send_mandate_created_notification(self, mandate):
        """Send notification when a new mandate is created - OPTIMIZED VERSION"""
        # PERFORMANCE OPTIMIZATION: Skip all notification processing in test environment
        if frappe.flags.in_test:
            return

        # PERFORMANCE OPTIMIZATION: Use SQL query instead of loading full Member document
        # This eliminates N+1 queries where frappe.get_doc("Member", mandate.member)
        # would load all Member relationships
        member_data = frappe.db.sql(
            """
            SELECT name, full_name, email
            FROM `tabMember`
            WHERE name = %s
        """,
            (mandate.member,),
            as_dict=True,
        )

        if not member_data or not member_data[0].email:
            return

        member = member_data[0]

        settings = self._get_settings()
        context = {
            "member_name": member.full_name,
            "mandate_id": mandate.mandate_id,
            "iban": self._mask_iban(mandate.iban),
            "bank_name": self._get_bank_name(mandate.iban),
            "sign_date": frappe.utils.format_date(mandate.sign_date),
            "company_name": settings.company_name,
        }

        # MIGRATED: Use unified EmailService instead of custom _send_email
        from verenigingen.services.communication.compatibility import send_sepa_email

        send_sepa_email(
            recipients=[member.email],
            subject=_("SEPA Direct Debit Mandate Activated"),
            template="sepa_mandate_created",
            context=context,
            member=member.name,
        )

    def send_mandate_cancelled_notification(self, mandate, reason=None):
        """Send notification when a mandate is cancelled - OPTIMIZED VERSION"""
        # PERFORMANCE OPTIMIZATION: Use SQL query instead of loading full Member document
        member_data = frappe.db.sql(
            """
            SELECT name, full_name, email
            FROM `tabMember`
            WHERE name = %s
        """,
            (mandate.member,),
            as_dict=True,
        )

        if not member_data or not member_data[0].email:
            return

        member = member_data[0]

        settings = self._get_settings()
        context = {
            "member_name": member.full_name,
            "mandate_id": mandate.mandate_id,
            "iban": self._mask_iban(mandate.iban),
            "cancellation_date": frappe.utils.format_date(today()),
            "cancellation_reason": reason or _("Cancelled by member request"),
            "company_name": settings.company_name,
            "support_email": settings.support_email,
        }

        # MIGRATED: Use unified EmailService instead of custom _send_email
        from verenigingen.services.communication.compatibility import send_sepa_email

        send_sepa_email(
            recipients=[member.email],
            subject=_("SEPA Direct Debit Mandate Cancelled"),
            template="sepa_mandate_cancelled",
            context=context,
            member=member.name,
        )

    def send_mandate_expiring_notification(self, mandate, days_until_expiry):
        """Send notification when a mandate is about to expire - OPTIMIZED VERSION"""
        # PERFORMANCE OPTIMIZATION: Use SQL query instead of loading full Member document
        member_data = frappe.db.sql(
            """
            SELECT name, full_name, email
            FROM `tabMember`
            WHERE name = %s
        """,
            (mandate.member,),
            as_dict=True,
        )

        if not member_data or not member_data[0].email:
            return

        member = member_data[0]

        settings = self._get_settings()
        context = {
            "member_name": member.full_name,
            "mandate_id": mandate.mandate_id,
            "expiry_date": frappe.utils.format_date(mandate.expiry_date),
            "days_until_expiry": days_until_expiry,
            "iban": self._mask_iban(mandate.iban),
            "company_name": settings.company_name,
            "renewal_link": f"{frappe.utils.get_url()}/bank_details",
        }

        # MIGRATED: Use unified EmailService instead of custom _send_email
        from verenigingen.services.communication.compatibility import send_sepa_email

        send_sepa_email(
            recipients=[member.email],
            subject=_("SEPA Mandate Expiring Soon - Action Required"),
            template="sepa_mandate_expiring",
            context=context,
            member=member.name,
        )

    def send_payment_retry_notification(self, retry_record):
        """Send notification about payment retry attempts"""
        invoice = frappe.get_doc("Sales Invoice", retry_record.invoice)
        member = frappe.get_doc("Member", retry_record.member)

        if not member.email:
            return

        context = {
            "member_name": member.full_name,
            "invoice_number": invoice.name,
            "amount": frappe.utils.fmt_money(retry_record.original_amount, currency="EUR"),
            "retry_date": frappe.utils.format_date(retry_record.next_retry_date),
            "retry_count": retry_record.retry_count,
            "failure_reason": retry_record.last_failure_reason or _("Payment failed"),
            "company_name": self._get_settings().company_name,
            "payment_link": f"{frappe.utils.get_url()}/payment-dashboard",
        }

        # MIGRATED: Use unified EmailService instead of custom _send_email
        from verenigingen.services.communication.compatibility import send_sepa_email

        if retry_record.status == "Scheduled":
            send_sepa_email(
                recipients=[member.email],
                subject=_("Payment Retry Scheduled - {0}").format(invoice.name),
                template="payment_retry_scheduled",
                context=context,
                member=member.name,
            )
        elif retry_record.status == "Failed":
            send_sepa_email(
                recipients=[member.email],
                subject=_("Payment Failed - Action Required"),
                template="payment_retry_failed",
                context=context,
                member=member.name,
            )

    def send_payment_success_notification(self, payment_entry):
        """Send notification when a payment is successful"""
        if payment_entry.party_type != "Customer":
            return

        # Find member from customer
        member = frappe.db.get_value("Member", {"customer": payment_entry.party}, "name")
        if not member:
            return

        member_doc = frappe.get_doc("Member", member)
        if not member_doc.email:
            return

        context = {
            "member_name": member_doc.full_name,
            "payment_reference": payment_entry.name,
            "amount": frappe.utils.fmt_money(
                payment_entry.paid_amount, currency=payment_entry.paid_to_account_currency
            ),
            "payment_date": frappe.utils.format_date(payment_entry.posting_date),
            "payment_method": payment_entry.mode_of_payment,
            "company_name": self._get_settings().company_name,
            "receipt_link": f"{frappe.utils.get_url()}/payment-dashboard",
        }

        # MIGRATED: Use unified EmailService instead of custom _send_email
        from verenigingen.services.communication.compatibility import send_sepa_email

        send_sepa_email(
            recipients=[member_doc.email],
            subject=_("Payment Received - Thank You"),
            template="payment_success",
            context=context,
            member=member_doc.name,
        )

    def check_and_send_expiry_notifications(self):
        """Check for expiring mandates and send notifications
        Called by scheduler"""

        # Get mandates expiring in 30 days
        thirty_days_ahead = add_days(today(), 30)

        expiring_mandates = frappe.get_all(
            "SEPA Mandate",
            filters={"status": "Active", "expiry_date": ["between", [today(), thirty_days_ahead]]},
            fields=["name", "member", "expiry_date", "mandate_id", "iban"],
        )

        for mandate_data in expiring_mandates:
            # Check if we already sent a notification recently
            last_notification = frappe.db.get_value(
                "Communication",
                {
                    "reference_doctype": "SEPA Mandate",
                    "reference_name": mandate_data.name,
                    "communication_type": "Automated Message",
                    "subject": ["like", "%Expiring Soon%"],
                    "creation": [">", add_days(today(), -7)],
                },
                "name",
            )

            if not last_notification:
                days_until_expiry = (getdate(mandate_data.expiry_date) - getdate(today())).days
                mandate = frappe.get_doc("SEPA Mandate", mandate_data.name)
                self.send_mandate_expiring_notification(mandate, days_until_expiry)

    def send_mandate_notifications_batch(self, mandate_notifications):
        """Send multiple mandate notifications efficiently

        Args:
            mandate_notifications: List of dicts with keys:
                - mandate: SEPA Mandate object
                - notification_type: 'created', 'cancelled', 'expiring'
                - extra_data: Additional data (reason, days_until_expiry)
        """
        if frappe.flags.in_test:
            return

        if not mandate_notifications:
            return

        # Load member data in bulk to reduce queries
        member_names = [notif["mandate"].member for notif in mandate_notifications]
        member_data_bulk = self._load_member_data_bulk(member_names)

        # Prepare email batch
        email_batch = []
        settings = self._get_settings()

        for notification in mandate_notifications:
            mandate = notification["mandate"]
            notification_type = notification["notification_type"]
            extra_data = notification.get("extra_data", {})

            # Get member data from bulk load
            member_data = member_data_bulk.get(mandate.member)
            if not member_data or not member_data["email"]:
                continue

            # Prepare context based on notification type
            if notification_type == "created":
                context = self._prepare_created_context(mandate, member_data, settings)
                template = "sepa_mandate_created"
                subject = "SEPA Direct Debit Mandate Activated"
            elif notification_type == "cancelled":
                context = self._prepare_cancelled_context(
                    mandate, member_data, settings, extra_data.get("reason")
                )
                template = "sepa_mandate_cancelled"
                subject = "SEPA Direct Debit Mandate Cancelled"
            elif notification_type == "expiring":
                context = self._prepare_expiring_context(
                    mandate, member_data, settings, extra_data.get("days_until_expiry")
                )
                template = "sepa_mandate_expiring"
                subject = "SEPA Mandate Expiring Soon - Action Required"
            else:
                continue

            email_batch.append(
                {
                    "recipients": [member_data["email"]],
                    "subject": subject,
                    "template": template,
                    "context": context,
                    "member": member_data["name"],
                }
            )

        # Send emails in batch
        if email_batch:
            self._send_email_batch(email_batch)

    def _prepare_created_context(self, mandate, member_data, settings):
        """Prepare context for mandate created notification"""
        return self._prepare_context(
            {
                "member_name": member_data["full_name"],
                "mandate_id": mandate.mandate_id,
                "iban": self._mask_iban(mandate.iban),
                "bank_name": self._get_bank_name(mandate.iban),
                "sign_date": frappe.utils.format_date(mandate.sign_date),
                "company_name": settings.company_name,
            }
        )

    def _prepare_cancelled_context(self, mandate, member_data, settings, reason):
        """Prepare context for mandate cancelled notification"""
        return self._prepare_context(
            {
                "member_name": member_data["full_name"],
                "mandate_id": mandate.mandate_id,
                "iban": self._mask_iban(mandate.iban),
                "cancellation_date": frappe.utils.format_date(frappe.utils.today()),
                "cancellation_reason": reason or "Cancelled by member request",
                "company_name": settings.company_name,
                "support_email": settings.support_email,
            }
        )

    def _prepare_expiring_context(self, mandate, member_data, settings, days_until_expiry):
        """Prepare context for mandate expiring notification"""
        return self._prepare_context(
            {
                "member_name": member_data["full_name"],
                "mandate_id": mandate.mandate_id,
                "expiry_date": frappe.utils.format_date(mandate.expiry_date),
                "days_until_expiry": days_until_expiry,
                "iban": self._mask_iban(mandate.iban),
                "company_name": settings.company_name,
                "renewal_link": f"{frappe.utils.get_url()}/bank_details",
            }
        )

    def _send_email_batch(self, email_batch):
        """Send multiple emails efficiently"""
        _ = self._get_settings()  # Settings for future batch optimization

        for email_data in email_batch:
            try:
                # Use cached template if available
                cached_template = self._get_template(email_data["template"])
                if cached_template:
                    message = frappe.render_template(cached_template, email_data["context"])
                else:
                    # Fallback to file-based template loading
                    template_path = (
                        f"verenigingen/verenigingen_payments/templates/emails/{email_data['template']}.html"
                    )
                    message = frappe.render_template(template_path, email_data["context"])

                # Send email with proper security validation
                communication_doc = frappe.get_doc(
                    {
                        "doctype": "Communication",
                        "recipients": email_data["recipients"],
                        "subject": email_data["subject"],
                        "content": message,
                        "communication_type": "Automated Message",
                        "reference_doctype": "Member" if email_data.get("member") else None,
                        "reference_name": email_data.get("member"),
                        "sent_or_received": "Sent",
                        "communication_medium": "Email",
                    }
                )

                # CORRECTED SECURE VERSION: Use proper secure operations
                result = secure_document_operation(
                    operation="insert",
                    doc=communication_doc,
                    justification=f"Send SEPA notification to member {email_data.get('member')}: {email_data['subject']}",
                    required_permissions=["Communication:create"],
                )

                if result.success and result.document:
                    # Queue for actual email delivery
                    frappe.enqueue(
                        method="frappe.core.doctype.communication.email.send_communication_email",
                        queue="default",
                        timeout=300,
                        communication=result.document.name,
                    )

            except Exception as e:
                frappe.log_error(
                    f"Failed to send SEPA notification batch: {str(e)}",
                    f"SEPA Notification Error - {email_data['subject']}",
                )

        # Queue comment logging for batch processing
        if email_batch:
            self._queue_comment_logging([email for email in email_batch if email.get("member")])

    def _queue_comment_logging(self, email_data_list):
        """Queue comment logging as background job"""
        if not email_data_list:
            return

        # Use background job for comment logging to avoid blocking email sending
        frappe.enqueue(
            method="verenigingen.verenigingen_payments.utils.sepa_notifications.log_notification_comments_batch",
            queue="default",
            timeout=300,
            email_data_list=[
                {"member": email["member"], "subject": email["subject"]} for email in email_data_list
            ],
        )

    def _send_email(self, recipients, subject, template, context, member=None):
        """Send email using template - MIGRATED to unified EmailService"""
        # MIGRATED: Use unified EmailService instead of custom batch processing
        from verenigingen.services.communication.compatibility import send_sepa_email

        send_sepa_email(
            recipients=recipients,
            subject=subject,
            template=template,
            context=self._prepare_context(context),
            member=member,
        )

    def _prepare_context(self, context):
        """Prepare email context with common variables"""
        context.update(
            {
                "current_year": frappe.utils.now_datetime().year,
                "website_url": frappe.utils.get_url(),
                "unsubscribe_link": f"{frappe.utils.get_url()}/email-preferences",
            }
        )
        return context

    def _send_email_legacy(self, recipients, subject, template, context, member=None):
        """Legacy send email method - kept for compatibility"""
        try:
            # Get email template
            template_path = f"verenigingen/verenigingen_payments/templates/emails/{template}.html"

            # Add common context
            context = self._prepare_context(context)

            # Render template
            message = frappe.render_template(template_path, context)

            # Send email with proper security validation
            communication_doc = frappe.get_doc(
                {
                    "doctype": "Communication",
                    "recipients": recipients,
                    "subject": subject,
                    "content": message,
                    "communication_type": "Automated Message",
                    "reference_doctype": "Member" if member else None,
                    "reference_name": member,
                    "sent_or_received": "Sent",
                    "communication_medium": "Email",
                }
            )

            # CORRECTED SECURE VERSION: Use proper secure operations
            result = secure_document_operation(
                operation="insert",
                doc=communication_doc,
                justification=f"Send SEPA notification to member {member}: {subject}",
                required_permissions=["Communication:create"],
            )

            if result.success and result.document:
                # Queue for actual email delivery
                frappe.enqueue(
                    method="frappe.core.doctype.communication.email.send_communication_email",
                    queue="default",
                    timeout=300,
                    communication=result.document.name,
                )

            # Queue comment logging as background job for better performance
            if member:
                frappe.enqueue(
                    method="verenigingen.verenigingen_payments.utils.sepa_notifications.log_notification_comment",
                    queue="default",
                    timeout=300,
                    member=member,
                    subject=subject,
                )

        except Exception as e:
            frappe.log_error(
                f"Failed to send SEPA notification: {str(e)}", f"SEPA Notification Error - {subject}"
            )

    def _mask_iban(self, iban):
        """Mask IBAN for security using centralized utility.

        Uses 'brief' style (first 4 + last 4) for user-friendly notifications.
        """
        return mask_iban(iban, style="brief")

    def _get_bank_name(self, iban):
        """Get bank name from IBAN"""
        try:
            from verenigingen.utils.validation.iban_validator import get_bank_from_iban

            bank_info = get_bank_from_iban(iban)
            return bank_info.get("bank_name", "Unknown Bank") if bank_info else "Unknown Bank"
        except Exception:
            return "Unknown Bank"


def check_and_send_expiry_notifications():
    """Scheduled function to check and send expiry notifications"""
    try:
        manager = SEPAMandateNotificationManager()
        manager.check_and_send_expiry_notifications()
    except Exception as e:
        frappe.log_error(f"Failed to check SEPA mandate expiry: {str(e)}", "SEPA Expiry Notification Error")


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_mandate_notification(mandate_id, notification_type="created"):
    """Test function to send a mandate notification"""
    mandate = frappe.get_doc("SEPA Mandate", mandate_id)
    manager = SEPAMandateNotificationManager()

    if notification_type == "created":
        manager.send_mandate_created_notification(mandate)
    elif notification_type == "cancelled":
        manager.send_mandate_cancelled_notification(mandate, "Test cancellation")
    elif notification_type == "expiring":
        manager.send_mandate_expiring_notification(mandate, 15)

    return {"success": True, "message": f"Test notification sent for {notification_type}"}


def log_notification_comment(member, subject):
    """Background job to log notification comment"""
    try:
        # First verify the member exists to avoid cascading errors
        if not frappe.db.exists("Member", member):
            # Silently skip - member might have been deleted
            return

        comment_doc = frappe.get_doc(
            {
                "doctype": "Comment",
                "comment_type": "Info",
                "reference_doctype": "Member",
                "reference_name": member,
                "content": f"Notification sent: {subject}",
            }
        )
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        comment_result = secure_document_operation(
            operation="insert",
            doc=comment_doc,
            justification=f"Log SEPA notification sent to member {member}: {subject}",
            required_permissions=["Comment:create"],
        )
        if not comment_result.success:
            # Truncate error message to avoid Error Log field length issues
            error_msg = f"Comment log failed: {member[:20]}"
            if comment_result.errors:
                error_msg += f" - {str(comment_result.errors[0])[:50]}"
            frappe.log_error(
                error_msg,
                "SEPA Comment Log",
            )
    except Exception as e:
        # Truncate error message to avoid cascading length errors
        error_msg = f"Comment error: {str(e)[:100]}"
        frappe.log_error(
            error_msg,
            "SEPA Comment Error",
        )


def log_notification_comments_batch(email_data_list):
    """Background job to log multiple notification comments"""
    try:
        for email_data in email_data_list:
            log_notification_comment(email_data["member"], email_data["subject"])
    except Exception as e:
        # Truncate to avoid Error Log field length issues
        error_msg = f"Batch comment error: {str(e)[:100]}"
        frappe.log_error(error_msg, "SEPA Batch Comment")
