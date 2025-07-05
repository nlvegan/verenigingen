import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, getdate, now_datetime, today


class MembershipAmendmentRequest(Document):
    def validate(self):
        """Validate amendment request"""
        self.validate_membership_exists()
        self.validate_effective_date()
        self.validate_amount_changes()
        self.set_current_details()
        self.set_default_effective_date()
        self.set_requested_by()

    def validate_membership_exists(self):
        """Ensure membership exists and is active"""
        if not self.membership:
            frappe.throw(_("Membership is required"))

        membership = frappe.get_doc("Membership", self.membership)
        if membership.status not in ["Active", "Inactive"]:
            frappe.throw(_("Can only create amendments for Active or Inactive memberships"))

    def validate_effective_date(self):
        """Validate effective date is in the future"""
        if self.effective_date and getdate(self.effective_date) < getdate(today()):
            frappe.throw(_("Effective date cannot be in the past"))

    def validate_amount_changes(self):
        """Validate amount changes are reasonable"""
        if self.amendment_type == "Fee Change" and self.requested_amount:
            if self.requested_amount <= 0:
                frappe.throw(_("Requested amount must be greater than 0"))

            # Check if amount is significantly different (to avoid accidental changes)
            if self.current_amount and abs(self.requested_amount - self.current_amount) < 0.01:
                frappe.throw(_("Requested amount is the same as current amount"))

    def set_current_details(self):
        """Set current membership details"""
        if not self.membership:
            return

        membership = frappe.get_doc("Membership", self.membership)

        # Set current amount
        self.current_amount = membership.get_billing_amount()

        # Set current subscription details
        if membership.subscription:
            subscription = frappe.get_doc("Subscription", membership.subscription)
            self.current_subscription = subscription.name

            # Get billing interval info (handle different ERPNext versions)
            try:
                if hasattr(subscription, "billing_interval_count"):
                    self.current_billing_interval = (
                        f"{subscription.billing_interval_count} {subscription.billing_interval}(s)"
                    )
                elif hasattr(subscription, "billing_interval"):
                    self.current_billing_interval = subscription.billing_interval
                else:
                    self.current_billing_interval = "Unknown"
            except Exception:
                self.current_billing_interval = "Unknown"

            # Get current plan name
            if subscription.plans:
                plan_name = subscription.plans[0].plan
                self.current_plan = plan_name

    def set_default_effective_date(self):
        """Set default effective date to next billing period"""
        if not self.effective_date and self.membership:
            try:
                membership = frappe.get_doc("Membership", self.membership)
                if membership.subscription:
                    subscription = frappe.get_doc("Subscription", membership.subscription)
                    if hasattr(subscription, "current_invoice_end") and subscription.current_invoice_end:
                        # Set to next billing period
                        self.effective_date = add_days(subscription.current_invoice_end, 1)
                    else:
                        # Fallback to next month
                        self.effective_date = add_days(today(), 30)
                else:
                    self.effective_date = add_days(today(), 30)
            except Exception:
                self.effective_date = add_days(today(), 30)

    def set_requested_by(self):
        """Set requested by to current user"""
        if not self.requested_by:
            self.requested_by = frappe.session.user

    def before_insert(self):
        """Set auto-approval for certain cases"""
        # Auto-approve fee increases by current member
        if (
            self.amendment_type == "Fee Change"
            and self.requested_amount
            and self.current_amount
            and self.requested_amount > self.current_amount
        ):
            member = frappe.get_doc("Member", self.member)
            if frappe.session.user == member.user:
                self.status = "Approved"
                self.approved_by = frappe.session.user
                self.approved_date = now_datetime()

    @frappe.whitelist()
    def approve_amendment(self, approval_notes=None):
        """Approve the amendment request"""
        if self.status != "Pending Approval":
            frappe.throw(_("Only pending amendments can be approved"))

        self.status = "Approved"
        self.approved_by = frappe.session.user
        self.approved_date = now_datetime()

        if approval_notes:
            self.internal_notes = (self.internal_notes or "") + f"\nApproval Notes: {approval_notes}"

        self.save()
        frappe.msgprint(_("Amendment approved successfully"))

    @frappe.whitelist()
    def reject_amendment(self, rejection_reason):
        """Reject the amendment request"""
        if self.status != "Pending Approval":
            frappe.throw(_("Only pending amendments can be rejected"))

        self.status = "Rejected"
        self.rejection_reason = rejection_reason
        self.save()

        # Notify the requester
        self.send_rejection_notification()
        frappe.msgprint(_("Amendment rejected"))

    @frappe.whitelist()
    def apply_amendment(self):
        """Apply the amendment to the membership"""
        if self.status != "Approved":
            frappe.msgprint(_("Only approved amendments can be applied"), indicator="red")
            return {"status": "error", "message": "Amendment not approved"}

        if getdate(self.effective_date) > getdate(today()):
            effective_date_formatted = frappe.utils.formatdate(self.effective_date)
            frappe.msgprint(
                _(
                    "This amendment is scheduled to be applied automatically on {0}. You cannot apply it manually before the effective date."
                ).format(effective_date_formatted),
                title=_("Amendment Not Ready"),
                indicator="orange",
            )
            return {"status": "warning", "message": "Amendment scheduled for future date"}

        try:
            membership = frappe.get_doc("Membership", self.membership)

            if self.amendment_type == "Fee Change":
                self.apply_fee_change(membership)
            elif self.amendment_type == "Billing Interval Change":
                self.apply_billing_change(membership)

            self.status = "Applied"
            self.applied_date = now_datetime()
            self.applied_by = frappe.session.user
            self.save()

            frappe.msgprint(_("Amendment applied successfully"), indicator="green")
            return {"status": "success", "message": "Amendment applied successfully"}

        except Exception as e:
            # Use shorter error message to avoid character length issues
            error_msg = str(e)[:200] + "..." if len(str(e)) > 200 else str(e)
            frappe.logger().error(f"Error applying amendment {self.name}: {error_msg}")
            frappe.msgprint(_("Error applying amendment: {0}").format(error_msg), indicator="red")
            return {"status": "error", "message": f"Error applying amendment: {error_msg}"}

    def apply_fee_change(self, membership):
        """Apply fee change to membership"""
        # Update membership with new amount
        membership.uses_custom_amount = 1
        membership.custom_amount = self.requested_amount
        membership.amount_reason = self.reason

        # Save current subscription reference
        old_subscription = membership.subscription

        # Clear subscription to create new one
        membership.subscription = None
        membership.flags.ignore_validate_update_after_submit = True
        membership.save()

        # Create new subscription with new amount
        new_subscription_name = membership.create_subscription_from_membership()
        self.new_subscription = new_subscription_name

        # Handle old subscription - try to cancel, but don't fail if it has linked documents
        if old_subscription:
            try:
                old_sub = frappe.get_doc("Subscription", old_subscription)

                # Check if subscription has linked invoices before attempting to cancel
                linked_invoices = frappe.get_all(
                    "Sales Invoice", filters={"subscription": old_subscription, "docstatus": 1}
                )

                if linked_invoices:
                    # Cannot cancel due to linked invoices - just disable it
                    old_sub.status = "Cancelled"  # Mark as cancelled but don't use .cancel()
                    old_sub.flags.ignore_validate_update_after_submit = True
                    old_sub.save()
                    self.old_subscription_cancelled = 0

                    self.processing_notes = f"New subscription {new_subscription_name} created. Old subscription {old_subscription} marked as cancelled (has {len(linked_invoices)} linked invoices)"
                else:
                    # Safe to cancel normally
                    old_sub.cancel()
                    self.old_subscription_cancelled = 1
                    self.processing_notes = f"Old subscription {old_subscription} cancelled, new subscription {new_subscription_name} created"

            except Exception as e:
                # Log with shorter message to avoid length issues
                error_msg = str(e)[:100] + "..." if len(str(e)) > 100 else str(e)
                frappe.logger().error(f"Error handling old subscription {old_subscription}: {error_msg}")
                self.processing_notes = f"New subscription {new_subscription_name} created. Old subscription {old_subscription} could not be cancelled: {error_msg}"

    def apply_billing_change(self, membership):
        """Apply billing interval change"""
        # This would involve creating a new subscription plan with different billing interval
        # Implementation depends on specific requirements
        frappe.throw(_("Billing interval changes are not yet implemented"))

    def send_rejection_notification(self):
        """Send notification to requester about rejection"""
        if not self.requested_by:
            return

        try:
            frappe.sendmail(
                recipients=[self.requested_by],
                subject=_("Membership Amendment Request Rejected"),
                message="""
                <h3>Amendment Request Rejected</h3>

                <p>Your membership amendment request has been rejected.</p>

                <p><strong>Details:</strong></p>
                <ul>
                    <li>Amendment ID: {self.name}</li>
                    <li>Type: {self.amendment_type}</li>
                    <li>Requested Amount: {frappe.format_value(self.requested_amount, 'Currency') if self.requested_amount else 'N/A'}</li>
                    <li>Rejection Reason: {self.rejection_reason}</li>
                </ul>

                <p>If you have questions about this decision, please contact the membership team.</p>
                """,
                now=True,
            )
        except Exception as e:
            frappe.log_error(f"Error sending rejection notification: {str(e)}")

    @frappe.whitelist()
    def get_impact_preview(self):
        """Get preview of amendment impact"""
        if not self.membership or self.amendment_type != "Fee Change":
            return {"html": "<p>No preview available</p>"}

        try:
            membership = frappe.get_doc("Membership", self.membership)
            current_amount = membership.get_billing_amount()
            new_amount = self.requested_amount or current_amount

            difference = new_amount - current_amount
            (difference / current_amount * 100) if current_amount > 0 else 0

            # impact_class = (
            #     "text-success" if difference > 0 else "text-danger" if difference < 0 else "text-muted"
            # )
            "increase" if difference > 0 else "decrease" if difference < 0 else "no change"

            # Get billing interval information from subscription
            billing_interval_display = "per month"  # Better default than "per period"
            annual_multiplier = 12  # Default fallback for monthly

            # Always try to get the most accurate data from the subscription first
            # The stored current_billing_interval might be outdated or in a different format
            if membership.subscription:
                try:
                    subscription = frappe.get_doc("Subscription", membership.subscription)

                    # Get billing interval from subscription plans
                    if hasattr(subscription, "plans") and subscription.plans:
                        # Get the first plan (typically there's only one)
                        plan_detail = subscription.plans[0]
                        plan_name = plan_detail.plan if hasattr(plan_detail, "plan") else None

                        if plan_name:
                            # Get the subscription plan document
                            plan = frappe.get_doc("Subscription Plan", plan_name)

                            count = getattr(plan, "billing_interval_count", 1) or 1
                            interval = getattr(plan, "billing_interval", "Month").lower()

                            # Create proper display text
                            if count == 1:
                                billing_interval_display = f"per {interval}"
                            else:
                                billing_interval_display = f"per {count} {interval}s"

                            # Calculate annual multiplier based on billing interval
                            # For months: if billing every 12 months, that's 1 time per year
                            # For months: if billing every 1 month, that's 12 times per year
                            if interval == "month":
                                annual_multiplier = 12.0 / count
                            elif interval == "year":
                                annual_multiplier = 1.0 / count
                            elif interval == "week":
                                annual_multiplier = 52.0 / count
                            elif interval == "day":
                                annual_multiplier = 365.0 / count
                            else:
                                annual_multiplier = 12.0 / count  # Default to monthly calculation

                except Exception as e:
                    frappe.log_error(
                        f"Error getting billing interval for subscription {membership.subscription}: {str(e)}"
                    )
                    # If subscription fails, try the stored value as fallback
                    if self.current_billing_interval and self.current_billing_interval != "Unknown":
                        try:
                            # Parse stored billing interval (e.g., "1 Month(s)", "3 Month(s)", "1 Year(s)")
                            import re

                            match = re.match(r"(\d+)\s*([a-zA-Z]+)", self.current_billing_interval)
                            if match:
                                count = int(match.group(1))
                                interval = (
                                    match.group(2).lower().rstrip("s()")
                                )  # Remove trailing 's' and '()'

                                # Create display text
                                if count == 1:
                                    billing_interval_display = f"per {interval}"
                                else:
                                    billing_interval_display = f"per {count} {interval}s"

                                # Calculate annual multiplier
                                # For months: if billing every 12 months, that's 1 time per year
                                # For months: if billing every 1 month, that's 12 times per year
                                if interval == "month":
                                    annual_multiplier = 12.0 / count
                                elif interval == "year":
                                    annual_multiplier = 1.0 / count
                                elif interval == "week":
                                    annual_multiplier = 52.0 / count
                                elif interval == "day":
                                    annual_multiplier = 365.0 / count
                                else:
                                    annual_multiplier = 12.0 / count  # Default to monthly
                            else:
                                # Fallback parsing for different formats
                                interval_lower = self.current_billing_interval.lower()
                                if "month" in interval_lower:
                                    billing_interval_display = "per month"
                                    annual_multiplier = 12.0
                                elif "year" in interval_lower:
                                    billing_interval_display = "per year"
                                    annual_multiplier = 1.0
                                elif "week" in interval_lower:
                                    billing_interval_display = "per week"
                                    annual_multiplier = 52.0
                                else:
                                    billing_interval_display = f"per {self.current_billing_interval.lower()}"
                                    annual_multiplier = 12.0  # Default fallback
                        except Exception as e:
                            frappe.log_error(
                                f"Error parsing stored billing interval '{self.current_billing_interval}': {str(e)}"
                            )

            # If no subscription or all parsing failed, keep defaults
            # (billing_interval_display = "per month", annual_multiplier = 12)

            # Calculate annual impact based on proper billing interval
            # Use round() to avoid floating point precision issues in HTML
            annual_difference = round(difference * annual_multiplier, 2)

            # Format currency values safely
            frappe.format_value(current_amount, "Currency")
            frappe.format_value(new_amount, "Currency")
            frappe.format_value(abs(difference), "Currency")
            frappe.format_value(annual_difference, "Currency")

            # Format effective date safely
            # effective_date_str = (
            #     frappe.utils.formatdate(self.effective_date) if self.effective_date else "Not set"
            # )

            # Clean billing interval for display
            billing_interval_display.replace("per ", "").title()

            # Debug info removed - issue resolved

            html = """
            <div class="amendment-impact">
                <h5>Amendment Impact Preview</h5>

                <div class="row">
                    <div class="col-md-6">
                        <h6>Current</h6>
                        <p><strong>{current_amount_formatted}</strong> {billing_interval_display}</p>
                    </div>
                    <div class="col-md-6">
                        <h6>After Amendment</h6>
                        <p><strong>{new_amount_formatted}</strong> {billing_interval_display}</p>
                    </div>
                </div>

                <div class="alert alert-info">
                    <h6 class="{impact_class}">
                        {difference_formatted} {impact_text}
                        ({percentage_change:+.1f}%)
                    </h6>
                    <p>Annual impact: <strong class="{impact_class}">{annual_difference_formatted}</strong></p>
                </div>

                <div class="small text-muted">
                    <p><strong>Effective Date:</strong> {effective_date_str}</p>
                    <p><strong>Billing Interval:</strong> {billing_display_clean}</p>
                    <p><strong>Next Billing:</strong> New amount will apply from the next billing period</p>
                </div>
            </div>
            """

            return {"html": html}

        except Exception as e:
            return {"html": f"<p class='text-danger'>Error generating preview: {str(e)}</p>"}


# Module-level functions for scheduled tasks and API calls


@frappe.whitelist()
def process_pending_amendments():
    """Process all approved amendments that are ready to be applied"""
    amendments = frappe.get_all(
        "Membership Amendment Request",
        filters={"status": "Approved", "effective_date": ["<=", today()]},
        fields=["name"],
    )

    processed_count = 0
    error_count = 0

    for amendment_data in amendments:
        try:
            amendment = frappe.get_doc("Membership Amendment Request", amendment_data.name)
            amendment.apply_amendment()
            processed_count += 1
        except Exception as e:
            error_count += 1
            frappe.log_error(f"Error processing amendment {amendment_data.name}: {str(e)}")

    if processed_count > 0 or error_count > 0:
        frappe.logger().info(f"Processed {processed_count} amendments, {error_count} errors")

    return {"processed": processed_count, "errors": error_count}


@frappe.whitelist()
def create_fee_change_amendment(member_name, new_amount, reason, effective_date=None):
    """Create a fee change amendment for a member"""
    member = frappe.get_doc("Member", member_name)

    # Get current active membership
    membership = member.get_active_membership()
    if not membership:
        frappe.throw(_("No active membership found for this member"))

    # Set default effective date if not provided
    if not effective_date:
        # Default to next billing period or next month
        try:
            if membership.subscription:
                subscription = frappe.get_doc("Subscription", membership.subscription)
                if hasattr(subscription, "current_invoice_end") and subscription.current_invoice_end:
                    effective_date = add_days(subscription.current_invoice_end, 1)
                else:
                    effective_date = add_days(today(), 30)
            else:
                effective_date = add_days(today(), 30)
        except Exception:
            effective_date = add_days(today(), 30)

    # Create amendment request
    amendment = frappe.get_doc(
        {
            "doctype": "Membership Amendment Request",
            "membership": membership.name,
            "member": member.name,
            "amendment_type": "Fee Change",
            "requested_amount": new_amount,
            "reason": reason,
            "effective_date": effective_date,
            "status": "Draft",
        }
    )

    amendment.insert()

    # Auto-approve if it's a fee increase by the member themselves
    if (
        amendment.current_amount
        and new_amount > amendment.current_amount
        and frappe.session.user == member.user
    ):
        amendment.approve_amendment("Auto-approved fee increase by member")

    return amendment


@frappe.whitelist()
def get_member_pending_contribution_amendments(member_name):
    """Get pending contribution amendments for a member"""
    try:
        amendments = frappe.get_all(
            "Contribution Amendment Request",
            filters={"member": member_name, "status": ["in", ["Draft", "Pending Approval", "Approved"]]},
            fields=["name", "amendment_type", "status", "requested_amount", "effective_date", "reason"],
            order_by="creation desc",
        )

        return amendments
    except Exception as e:
        # Handle case where Contribution Amendment Request doctype doesn't exist
        frappe.log_error(f"Error getting member amendments: {str(e)}", "Contribution Amendment Request Error")
        return []
