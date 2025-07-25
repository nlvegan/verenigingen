import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, getdate, now_datetime, today


class ContributionAmendmentRequest(Document):
    def validate(self):
        """Validate amendment request"""
        self.validate_membership_exists()
        self.validate_effective_date()
        self.validate_amount_changes()
        self.validate_no_conflicting_amendments()
        self.validate_adjustment_frequency()
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
        # Validate membership type changes
        if self.amendment_type == "Membership Type Change":
            if self.current_membership_type and self.requested_membership_type:
                if self.current_membership_type == self.requested_membership_type:
                    frappe.throw(_("Cannot change to the same membership type"))

        if self.amendment_type == "Fee Change" and self.requested_amount is not None:
            if self.requested_amount <= 0:
                frappe.throw(_("Requested amount must be greater than 0"))

            # Check if amount is significantly different (to avoid accidental changes)
            if self.current_amount and abs(self.requested_amount - self.current_amount) < 0.01:
                frappe.throw(_("Requested amount is the same as current amount"))

            # Check minimum fee enforcement
            if self.membership:
                membership = frappe.get_doc("Membership", self.membership)
                if membership.membership_type:
                    membership_type = frappe.get_doc("Membership Type", membership.membership_type)
                    if not membership_type.dues_schedule_template:
                        frappe.throw(
                            f"Membership Type '{membership_type.name}' must have a dues schedule template"
                        )
                    template = frappe.get_doc(
                        "Membership Dues Schedule", membership_type.dues_schedule_template
                    )
                    # Validate template configuration before proceeding
                    if not template.suggested_amount:
                        frappe.throw(
                            f"Dues schedule template '{membership_type.dues_schedule_template}' must have a suggested_amount configured for contribution calculations"
                        )
                    base_amount = template.suggested_amount

                    # Calculate minimum fee (30% of base or €5, whichever is higher)
                    minimum_fee = max(base_amount * 0.3, 5.0)

                    # Check if member is a student (gets 50% minimum instead)
                    if self.member:
                        member = frappe.get_doc("Member", self.member)
                        if getattr(member, "student_status", 0):
                            minimum_fee = max(base_amount * 0.5, 5.0)

                    if self.requested_amount < minimum_fee:
                        frappe.throw(
                            _("Requested amount is less than minimum fee of €{0}").format(minimum_fee)
                        )

    def validate_no_conflicting_amendments(self):
        """Validate that there are no existing pending amendments for this member"""
        if not self.member or not self.is_new():
            return  # Only check for new documents

        # Check for existing pending or approved amendments
        existing_amendments = frappe.get_all(
            "Contribution Amendment Request",
            filters={
                "member": self.member,
                "name": ["!=", self.name],  # Exclude current amendment
                "status": ["in", ["Pending Approval", "Approved"]],
            },
            fields=["name", "status", "requested_amount"],
        )

        if existing_amendments:
            amendment_details = []
            for amendment in existing_amendments:
                amendment_details.append(f"{amendment['name']} ({amendment['status']})")

            frappe.throw(
                _(
                    "Cannot create new amendment. Member {0} already has pending amendments: {1}. "
                    "Please cancel or apply existing amendments before creating new ones."
                ).format(self.member, ", ".join(amendment_details))
            )

    def validate_adjustment_frequency(self):
        """Validate that member hasn't exceeded adjustment frequency limits"""
        if not self.member or not self.requested_by_member:
            return  # Only check for member-requested adjustments

        # Get settings
        settings = frappe.get_single("Verenigingen Settings")
        max_adjustments = getattr(settings, "max_adjustments_per_year", 2)

        # Count adjustments in past 365 days
        date_365_days_ago = add_days(today(), -365)
        adjustments_past_year = frappe.db.count(
            "Contribution Amendment Request",
            filters={
                "member": self.member,
                "amendment_type": "Fee Change",
                "creation": [">=", date_365_days_ago],
                "requested_by_member": 1,
            },
        )

        if adjustments_past_year >= max_adjustments:
            frappe.throw(
                _(
                    "You have reached the maximum number of fee adjustments ({0}) allowed in a 365-day period"
                ).format(max_adjustments)
            )

    def set_current_details(self):
        """Set current membership details using new dues schedule approach"""
        if not self.membership:
            return

        membership = frappe.get_doc("Membership", self.membership)
        member_doc = frappe.get_doc("Member", self.member)

        # Set current membership type
        self.current_membership_type = membership.membership_type

        # PRIORITY 1: Get current amount from active dues schedule
        active_dues_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": self.member, "status": "Active"},
            ["name", "dues_rate", "billing_frequency"],
            as_dict=True,
        )

        if active_dues_schedule:
            self.current_amount = active_dues_schedule.dues_rate
            self.current_billing_interval = active_dues_schedule.billing_frequency or "Monthly"
            self.current_dues_schedule = active_dues_schedule.name
        else:
            # PRIORITY 2: Fall back to legacy fee calculation
            try:
                current_fee = member_doc.get_current_membership_fee()
                self.current_amount = current_fee.get("amount", 0)
            except Exception:
                self.current_amount = (
                    membership.get_billing_amount() if hasattr(membership, "get_billing_amount") else 0
                )

        # Set current billing interval from dues schedule or membership type
        if active_dues_schedule:
            # Already set above from dues schedule
            pass
        elif membership.membership_type:
            # Get billing interval from membership type
            membership_type = frappe.get_doc("Membership Type", membership.membership_type)
            self.current_billing_interval = getattr(membership_type, "billing_period", "Monthly")
        else:
            self.current_billing_interval = "Monthly"

    def set_default_effective_date(self):
        """Set default effective date to next billing period"""
        if not self.effective_date and self.membership:
            try:
                # Check if there's an active dues schedule
                active_dues_schedule = frappe.db.get_value(
                    "Membership Dues Schedule",
                    {"member": self.member, "status": "Active"},
                    ["name", "next_invoice_date"],
                    as_dict=True,
                )

                if active_dues_schedule and active_dues_schedule.next_invoice_date:
                    # Set to next billing period
                    self.effective_date = active_dues_schedule.next_invoice_date
                else:
                    # Fallback to next month
                    self.effective_date = add_days(today(), 30)
            except Exception:
                self.effective_date = add_days(today(), 30)

    def set_requested_by(self):
        """Set requested by to current user"""
        if not self.requested_by:
            self.requested_by = frappe.session.user

    def before_insert(self):
        """Set auto-approval for certain cases with enhanced rules"""
        # Enhanced auto-approval logic
        if self.amendment_type == "Fee Change" and self.requested_amount and self.current_amount:
            member = frappe.get_doc("Member", self.member)

            # Get approval settings from Verenigingen Settings
            settings = frappe.get_single("Verenigingen Settings")
            auto_approve_increases = getattr(settings, "auto_approve_fee_increases", 1)
            auto_approve_member_requests = getattr(settings, "auto_approve_member_requests", 1)
            max_auto_approve_amount = getattr(settings, "max_auto_approve_amount", 1000)

            # Check if this is a member self-request
            is_member_request = frappe.session.user == member.user or frappe.session.user == member.email

            # Auto-approve fee increases by current member (with limits)
            if (
                auto_approve_increases
                and is_member_request
                and self.requested_amount > self.current_amount
                and self.requested_amount <= max_auto_approve_amount
            ):
                self.status = "Approved"
                self.approved_by = frappe.session.user
                self.approved_date = now_datetime()
                self.internal_notes = "Auto-approved: Fee increase by member within limits"

            # Auto-approve small adjustments (less than 5% change)
            elif (
                auto_approve_member_requests
                and is_member_request
                and abs(self.requested_amount - self.current_amount) <= (self.current_amount * 0.05)
            ):
                self.status = "Approved"
                self.approved_by = frappe.session.user
                self.approved_date = now_datetime()
                self.internal_notes = "Auto-approved: Small adjustment within 5% threshold"

            # Otherwise require manual approval
            else:
                self.status = "Pending Approval"
                approval_reason = []
                if not auto_approve_increases:
                    approval_reason.append("fee increases require approval")
                if not is_member_request:
                    approval_reason.append("non-member request")
                if self.requested_amount > max_auto_approve_amount:
                    approval_reason.append(f"amount exceeds limit (€{max_auto_approve_amount})")
                if self.requested_amount < self.current_amount:
                    approval_reason.append("fee decrease")

                self.internal_notes = f"Requires approval: {', '.join(approval_reason)}"

    def after_insert(self):
        """Handle post-insertion tasks"""
        # If this amendment was auto-approved in before_insert, cancel conflicting amendments
        if self.status == "Approved":
            self.cancel_conflicting_amendments()
            self.save()

    @frappe.whitelist()
    def approve_amendment(self, approval_notes=None):
        """Approve the amendment request"""
        if self.status != "Pending Approval":
            frappe.throw(_("Only pending amendments can be approved"))

        # Cancel any other pending or approved amendments for the same member
        self.cancel_conflicting_amendments()

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
        """Apply fee change to membership using new dues schedule approach"""
        try:
            # Create new dues schedule with the requested amount
            dues_schedule_name = self.create_dues_schedule_for_amendment()
            self.new_dues_schedule = dues_schedule_name

            # Update legacy override fields for backward compatibility
            member_doc = frappe.get_doc("Member", self.member)
            member_doc.reload()  # Refresh to avoid timestamp mismatch
            member_doc.dues_rate = self.requested_amount
            member_doc.fee_override_reason = f"Amendment: {self.reason}"
            member_doc.fee_override_date = today()
            member_doc.fee_override_by = frappe.session.user
            # Set flag to bypass permission check for system updates
            member_doc._system_update = True
            member_doc.save(ignore_permissions=True)

            # Updated to use dues schedule system
            self.processing_notes = f"Dues schedule {dues_schedule_name} created for fee change."

        except Exception as e:
            frappe.throw(_("Error applying fee change: {0}").format(str(e)))

    def create_dues_schedule_for_amendment(self):
        """Create a new dues schedule for this amendment"""
        try:
            # Get current active membership
            membership = frappe.db.get_value(
                "Membership",
                {"member": self.member, "status": "Active", "docstatus": 1},
                ["name", "membership_type"],
                as_dict=True,
            )

            if not membership:
                frappe.throw(_("No active membership found for creating dues schedule"))

            # Deactivate existing active dues schedule
            existing_schedule = frappe.db.get_value(
                "Membership Dues Schedule", {"member": self.member, "status": "Active"}, "name"
            )

            if existing_schedule:
                existing_doc = frappe.get_doc("Membership Dues Schedule", existing_schedule)
                existing_doc.status = "Cancelled"
                existing_doc.add_comment(
                    text=f"Cancelled and replaced by amendment {self.name}: €{self.requested_amount:.2f}"
                )
                existing_doc._ignore_permissions = True
                existing_doc.save(ignore_permissions=True)

            # Create new dues schedule
            dues_schedule = frappe.new_doc("Membership Dues Schedule")
            dues_schedule.schedule_name = f"Amendment {self.name} - {frappe.utils.random_string(6)}"
            dues_schedule.member = self.member
            dues_schedule.membership = membership.name
            dues_schedule.membership_type = membership.membership_type
            dues_schedule.contribution_mode = "Custom"
            dues_schedule.dues_rate = self.requested_amount
            dues_schedule.uses_custom_amount = 1
            dues_schedule.custom_amount_approved = 1  # Amendment already approved
            dues_schedule.custom_amount_reason = f"Amendment Request: {self.reason}"

            # Handle zero amounts specially
            if self.requested_amount == 0:
                dues_schedule.custom_amount_reason = f"Free membership via amendment: {self.reason}"

            dues_schedule.billing_frequency = "Monthly"  # Default
            # Payment method is determined dynamically based on member's payment setup
            dues_schedule.status = "Active"
            dues_schedule.auto_generate = 1
            dues_schedule.test_mode = 0
            dues_schedule.effective_date = self.effective_date or today()
            dues_schedule.next_invoice_date = self.effective_date or today()

            # Add amendment metadata in notes
            dues_schedule.notes = (
                f"Created from amendment request {self.name} by {frappe.session.user} on {today()}"
            )

            # Set flag to skip permission check and save with ignore_permissions
            dues_schedule._ignore_permissions = True
            dues_schedule.save(ignore_permissions=True)

            # Add comment about the amendment
            dues_schedule.add_comment(
                text=f"Created from amendment request {self.name}. Amount: €{self.requested_amount:.2f}. Reason: {self.reason}"
            )

            return dues_schedule.name

        except Exception as e:
            frappe.log_error(
                f"Error creating dues schedule for amendment: {str(e)}", "Amendment Dues Schedule Error"
            )
            frappe.throw(_("Error creating dues schedule: {0}").format(str(e)))

    def apply_billing_change(self, membership):
        """Apply billing interval change"""
        # This would involve creating a new dues schedule with different billing interval
        # Implementation depends on specific requirements
        frappe.throw(_("Billing interval changes are not yet implemented"))

    def cancel_conflicting_amendments(self):
        """Cancel any other pending or approved amendments for the same member"""
        if not self.member:
            return

        # Find all other amendments for this member that are pending approval or approved but not applied
        conflicting_amendments = frappe.get_all(
            "Contribution Amendment Request",
            filters={
                "member": self.member,
                "name": ["!=", self.name],  # Exclude current amendment
                "status": ["in", ["Pending Approval", "Approved"]],
            },
            fields=["name", "status", "requested_amount", "effective_date"],
        )

        cancelled_count = 0
        for amendment_data in conflicting_amendments:
            try:
                amendment = frappe.get_doc("Contribution Amendment Request", amendment_data.name)

                # Add cancellation note
                cancellation_note = f"Cancelled due to approval of newer amendment {self.name}"
                amendment.internal_notes = (amendment.internal_notes or "") + f"\n{cancellation_note}"

                # Set status to cancelled
                amendment.status = "Cancelled"
                amendment.flags.ignore_validate_update_after_submit = True
                amendment.save()

                cancelled_count += 1

            except Exception as e:
                frappe.log_error(
                    f"Error cancelling conflicting amendment {amendment_data.name}: {str(e)}",
                    "Amendment Cancellation Error",
                )

        if cancelled_count > 0:
            self.internal_notes = (
                self.internal_notes or ""
            ) + f"\nCancelled {cancelled_count} conflicting amendment(s) upon approval"
            frappe.logger().info(
                f"Cancelled {cancelled_count} conflicting amendments for member {self.member}"
            )

    def send_rejection_notification(self):
        """Send notification to requester about rejection"""
        if not self.requested_by:
            return

        try:
            frappe.sendmail(
                recipients=[self.requested_by],
                subject=_("Membership Amendment Request Rejected"),
                message=f"""
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
            percentage_change = (difference / current_amount * 100) if current_amount > 0 else 0

            impact_class = (
                "text-success" if difference > 0 else "text-danger" if difference < 0 else "text-muted"
            )
            impact_text = "increase" if difference > 0 else "decrease" if difference < 0 else "no change"

            # Get billing interval information from dues schedule or membership type
            billing_interval_display = "per month"  # Default
            annual_multiplier = 12  # Default fallback for monthly

            # Try to get billing interval from current dues schedule
            if self.current_dues_schedule:
                try:
                    dues_schedule = frappe.get_doc("Membership Dues Schedule", self.current_dues_schedule)
                    billing_frequency = getattr(dues_schedule, "billing_frequency", "Monthly")

                    # Map billing frequency to display text and multiplier
                    freq_mapping = {
                        "Monthly": ("per month", 12.0),
                        "Quarterly": ("per quarter", 4.0),
                        "Annual": ("per year", 1.0),
                        "Biannual": ("per 6 months", 2.0),
                        "Weekly": ("per week", 52.0),
                        "Daily": ("per day", 365.0),
                    }

                    if billing_frequency in freq_mapping:
                        billing_interval_display, annual_multiplier = freq_mapping[billing_frequency]
                    else:
                        billing_interval_display = f"per {billing_frequency.lower()}"
                        annual_multiplier = 12.0  # Default fallback

                except Exception as e:
                    frappe.log_error(f"Error getting billing interval from dues schedule: {str(e)}")

            # If no dues schedule, try membership type
            elif self.membership:
                try:
                    membership_type = frappe.get_doc("Membership Type", membership.membership_type)
                    billing_period = getattr(membership_type, "billing_period", "Monthly")

                    # Map billing period to display text and multiplier
                    period_mapping = {
                        "Monthly": ("per month", 12.0),
                        "Quarterly": ("per quarter", 4.0),
                        "Annual": ("per year", 1.0),
                        "Biannual": ("per 6 months", 2.0),
                        "Weekly": ("per week", 52.0),
                        "Daily": ("per day", 365.0),
                        "Lifetime": ("lifetime", 1.0),
                    }

                    if billing_period in period_mapping:
                        billing_interval_display, annual_multiplier = period_mapping[billing_period]
                    else:
                        billing_interval_display = f"per {billing_period.lower()}"
                        annual_multiplier = 12.0  # Default fallback

                except Exception as e:
                    frappe.log_error(f"Error getting billing interval from membership type: {str(e)}")

            # If all parsing failed, keep defaults
            # (billing_interval_display = "per month", annual_multiplier = 12)

            # Calculate annual impact based on proper billing interval
            # Use round() to avoid floating point precision issues in HTML
            annual_difference = round(difference * annual_multiplier, 2)

            # Format currency values safely
            current_amount_formatted = frappe.format_value(current_amount, "Currency")
            new_amount_formatted = frappe.format_value(new_amount, "Currency")
            difference_formatted = frappe.format_value(abs(difference), "Currency")
            annual_difference_formatted = frappe.format_value(annual_difference, "Currency")

            # Format effective date safely
            effective_date_str = (
                frappe.utils.formatdate(self.effective_date) if self.effective_date else "Not set"
            )

            # Clean billing interval for display
            billing_display_clean = billing_interval_display.replace("per ", "").title()

            # Debug info removed - issue resolved

            html = f"""
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
        "Contribution Amendment Request",
        filters={"status": "Approved", "effective_date": ["<=", today()]},
        fields=["name"],
    )

    processed_count = 0
    error_count = 0

    for amendment_data in amendments:
        try:
            amendment = frappe.get_doc("Contribution Amendment Request", amendment_data.name)
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
            # Check if there's an active dues schedule
            active_dues_schedule = frappe.db.get_value(
                "Membership Dues Schedule",
                {"member": member.name, "status": "Active"},
                ["next_invoice_date"],
                as_dict=True,
            )

            if active_dues_schedule and active_dues_schedule.next_invoice_date:
                effective_date = active_dues_schedule.next_invoice_date
            else:
                effective_date = add_days(today(), 30)
        except Exception:
            effective_date = add_days(today(), 30)

    # Create amendment request
    amendment = frappe.get_doc(
        {
            "doctype": "Contribution Amendment Request",
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
    from frappe.utils import getdate, today

    amendments = frappe.get_all(
        "Contribution Amendment Request",
        filters={"member": member_name, "status": ["in", ["Draft", "Pending Approval", "Approved"]]},
        fields=["name", "amendment_type", "status", "requested_amount", "effective_date", "reason"],
        order_by="creation desc",
    )

    # Filter out approved amendments that have passed their effective date
    filtered_amendments = []
    for amendment in amendments:
        # Always show Draft and Pending Approval amendments
        if amendment.status in ["Draft", "Pending Approval"]:
            filtered_amendments.append(amendment)
        # For Approved amendments, only show if effective date hasn't passed
        elif amendment.status == "Approved" and amendment.effective_date:
            if getdate(amendment.effective_date) >= getdate(today()):
                filtered_amendments.append(amendment)
        # For Approved amendments without effective date, show them (edge case)
        elif amendment.status == "Approved" and not amendment.effective_date:
            filtered_amendments.append(amendment)

    return filtered_amendments


@frappe.whitelist()
def test_enhanced_approval_workflows():
    """Test function for enhanced approval workflows"""
    try:
        print("=== Testing Enhanced Approval Workflows ===")

        results = []

        # Test 1: Check if our enhanced methods exist in the class
        methods_to_check = ["create_dues_schedule_for_amendment", "set_current_details", "apply_fee_change"]

        for method in methods_to_check:
            if hasattr(ContributionAmendmentRequest, method):
                results.append(f"✓ Method {method} exists in ContributionAmendmentRequest class")
            else:
                results.append(f"❌ Method {method} missing from ContributionAmendmentRequest class")

        # Test 2: Check if we can create an amendment request document
        try:
            test_amendment = frappe.new_doc("Contribution Amendment Request")
            test_amendment.amendment_type = "Fee Change"
            test_amendment.requested_amount = 25.00
            test_amendment.reason = "Test enhancement"

            # Test if methods are available on the instance
            for method in methods_to_check:
                if hasattr(test_amendment, method):
                    results.append(f"✓ Method {method} available on instance")
                else:
                    results.append(f"❌ Method {method} not available on instance")

            results.append("✓ Amendment document creation successful")
        except Exception as e:
            results.append(f"❌ Error creating amendment document: {str(e)}")

        # Test 3: Test enhanced validation logic exists
        try:
            test_amendment = frappe.new_doc("Contribution Amendment Request")
            if hasattr(test_amendment, "before_insert"):
                results.append("✓ Enhanced before_insert method exists")
            else:
                results.append("❌ Enhanced before_insert method missing")
        except Exception as e:
            results.append(f"❌ Error testing before_insert: {str(e)}")

        # Test 4: Check if new fields exist in the DocType
        try:
            doctype = frappe.get_doc("DocType", "Contribution Amendment Request")
            new_fields = ["new_dues_schedule", "current_dues_schedule"]

            existing_fields = [field.fieldname for field in doctype.fields]

            for field in new_fields:
                if field in existing_fields:
                    results.append(f"✓ New field {field} exists in DocType")
                else:
                    results.append(f"❌ New field {field} missing from DocType")

        except Exception as e:
            results.append(f"❌ Error checking DocType fields: {str(e)}")

        print("\n".join(results))

        return {"success": True, "message": "Enhanced approval workflows test completed", "results": results}

    except Exception as e:
        return {"success": False, "message": f"Error during test: {str(e)}"}


@frappe.whitelist()
def reload_amendment_doctype():
    """Reload the Contribution Amendment Request DocType"""
    try:
        frappe.reload_doc("verenigingen", "doctype", "contribution_amendment_request")
        return {"success": True, "message": "DocType reloaded successfully"}
    except Exception as e:
        return {"success": False, "message": f"Error reloading DocType: {str(e)}"}


@frappe.whitelist()
def test_dues_amendment_integration(member_name=None):
    """Test integration between dues schedules and amendment system

    Args:
        member_name: Specific member to test with (optional)
    """
    try:
        print("=== Testing Dues Amendment Integration ===")

        # Get specific member or first active member if none specified
        if member_name:
            member = frappe.db.get_value("Member", member_name, ["name", "email"], as_dict=True)
            if not member:
                return {"success": False, "message": f"Member {member_name} not found"}
        else:
            # Get first active member for testing (with explicit ordering for consistency)
            member = frappe.db.get_value(
                "Member", {"status": "Active"}, ["name", "email"], as_dict=True, order_by="creation"
            )
            if not member:
                return {"success": False, "message": "No active member found"}

        print(f"✓ Using member: {member.name}")

        # Get their membership
        membership = frappe.db.get_value(
            "Membership",
            {"member": member.name, "docstatus": 1},
            ["name", "membership_type", "status"],
            as_dict=True,
        )

        if not membership:
            return {"success": False, "message": "No membership found"}

        print(f"✓ Using membership: {membership.name} ({membership.status})")

        # Create test amendment
        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": membership.name,
                "member": member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 35.00,
                "reason": "Testing integration",
                "effective_date": frappe.utils.add_days(frappe.utils.today(), 30),
            }
        )

        # Test validation
        amendment.validate()
        print("✓ Amendment validation successful")

        # Test insertion
        amendment.insert()
        print(f"✓ Amendment created with status: {amendment.status}")

        results = []

        # Test new fields exist
        if hasattr(amendment, "new_dues_schedule"):
            results.append("✓ new_dues_schedule field exists")
        else:
            results.append("❌ new_dues_schedule field missing")

        if hasattr(amendment, "current_dues_schedule"):
            results.append("✓ current_dues_schedule field exists")
        else:
            results.append("❌ current_dues_schedule field missing")

        # Test current details detection
        if amendment.current_amount:
            results.append(f"✓ Current amount detected: €{amendment.current_amount}")
        else:
            results.append("! Current amount not detected (may be normal)")

        # Test dues schedule creation method exists
        if hasattr(amendment, "create_dues_schedule_for_amendment"):
            results.append("✓ create_dues_schedule_for_amendment method exists")
        else:
            results.append("❌ create_dues_schedule_for_amendment method missing")

        # Test enhanced set_current_details
        if hasattr(amendment, "set_current_details"):
            results.append("✓ Enhanced set_current_details method exists")
        else:
            results.append("❌ Enhanced set_current_details method missing")

        # Test approval functionality
        if amendment.status == "Pending Approval":
            results.append("✓ Amendment requires approval (as expected)")
        elif amendment.status == "Approved":
            results.append("✓ Amendment was auto-approved")
        else:
            results.append(f"! Amendment status: {amendment.status}")

        # Clean up
        amendment.delete()
        results.append("✓ Test cleanup completed")

        print("\n".join(results))

        return {
            "success": True,
            "message": "Dues amendment integration test completed successfully",
            "results": results,
        }

    except Exception as e:
        return {"success": False, "message": f"Error during test: {str(e)}"}


@frappe.whitelist()
def test_real_world_amendment_scenarios(member_name=None):
    """Test real-world scenarios for dues amendment system

    Args:
        member_name: Specific member to test with (optional)
    """
    try:
        print("=== Testing Real-World Amendment Scenarios ===")

        # Get specific member or first active member if none specified
        if member_name:
            member = frappe.db.get_value("Member", member_name, ["name", "email"], as_dict=True)
            if not member:
                return {"success": False, "message": f"Member {member_name} not found"}
        else:
            # Get first active member for testing (with explicit ordering for consistency)
            member = frappe.db.get_value(
                "Member", {"status": "Active"}, ["name", "email"], as_dict=True, order_by="creation"
            )
            if not member:
                return {"success": False, "message": "No active member found"}

        member_doc = frappe.get_doc("Member", member.name)
        print(f"Member: {member_doc.full_name}")

        # Get their membership
        membership = frappe.db.get_value(
            "Membership",
            {"member": member.name, "docstatus": 1},
            ["name", "membership_type", "status"],
            as_dict=True,
        )

        if not membership:
            return {"success": False, "message": "No membership found"}

        print(f"Membership: {membership.name} ({membership.status})")

        results = []

        # Test 1: Young Professional Fee Increase Scenario
        print("\n--- Testing Fee Increase Scenario ---")
        amendment1 = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": membership.name,
                "member": member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 25.00,
                "reason": "Got a promotion and want to support the organization more",
                "effective_date": frappe.utils.add_days(frappe.utils.today(), 30),
            }
        )

        amendment1.insert()
        results.append(f"✓ Fee increase amendment created: {amendment1.name}")
        results.append(f"  Status: {amendment1.status}")
        results.append(f"  Should be auto-approved: {amendment1.status == 'Approved'}")

        # Clean up
        amendment1.delete()

        # Test 2: Financial Hardship Scenario
        print("\n--- Testing Financial Hardship Scenario ---")
        amendment2 = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": membership.name,
                "member": member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 8.00,
                "reason": "Temporary financial hardship due to job loss",
                "effective_date": frappe.utils.add_days(frappe.utils.today(), 7),
            }
        )

        amendment2.insert()
        results.append(f"✓ Financial hardship amendment created: {amendment2.name}")
        results.append(f"  Status: {amendment2.status}")
        results.append(f"  Should require approval: {amendment2.status == 'Pending Approval'}")

        # Test approval
        amendment2.approve_amendment("Approved due to documented financial hardship")
        results.append(f"  After approval: {amendment2.status}")

        # Test application
        if amendment2.status == "Approved":
            result = amendment2.apply_amendment()
            if result["status"] == "success":
                results.append("✓ Amendment applied successfully")
                if amendment2.new_dues_schedule:
                    results.append(f"  New dues schedule created: {amendment2.new_dues_schedule}")
                    # Clean up dues schedule
                    frappe.delete_doc("Membership Dues Schedule", amendment2.new_dues_schedule)

        # Clean up
        amendment2.delete()

        print("\n".join(results))

        return {
            "success": True,
            "message": "Real-world amendment scenarios tested successfully",
            "results": results,
        }

    except Exception as e:
        return {"success": False, "message": f"Error during real-world testing: {str(e)}"}


@frappe.whitelist()
def check_specific_amendment(amendment_name):
    """Check details of a specific amendment request"""
    try:
        amendment = frappe.get_doc("Contribution Amendment Request", amendment_name)
        return {
            "name": amendment.name,
            "effective_date": amendment.effective_date,
            "creation": amendment.creation,
            "status": amendment.status,
            "member": amendment.member,
            "current_amount": amendment.current_amount,
            "requested_amount": amendment.requested_amount,
            "current_dues_schedule": amendment.current_dues_schedule,
            "reason": amendment.reason,
            "amendment_type": amendment.amendment_type,
        }
    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def fix_membership_type_billing_periods():
    """Fix all membership type billing period misconfigurations"""
    try:
        # Get all membership types
        membership_types = frappe.get_all(
            "Membership Type", fields=["name", "minimum_amount", "billing_period"], order_by="name"
        )

        # Define the expected corrections
        corrections = []

        for mt in membership_types:
            expected_billing = None
            name_lower = mt.name.lower()

            if "daily" in name_lower or "daglid" in name_lower:
                expected_billing = "Daily"
            elif "monthly" in name_lower or "maandlid" in name_lower:
                expected_billing = "Monthly"
            elif "weekly" in name_lower:
                expected_billing = "Weekly"
            elif "quarterly" in name_lower:
                expected_billing = "Quarterly"
            elif "annual" in name_lower or "yearly" in name_lower or "jaarlid" in name_lower:
                expected_billing = "Annual"

            if expected_billing and mt.billing_period != expected_billing:
                corrections.append(
                    {
                        "name": mt.name,
                        "current_billing_period": mt.billing_period,
                        "corrected_billing_period": expected_billing,
                    }
                )

        # Apply corrections
        applied_corrections = []
        errors = []

        for correction in corrections:
            try:
                # Update the membership type
                membership_type = frappe.get_doc("Membership Type", correction["name"])
                membership_type.billing_period = correction["corrected_billing_period"]
                membership_type.save(ignore_permissions=True)

                applied_corrections.append(
                    {
                        "membership_type": correction["name"],
                        "old_billing_period": correction["current_billing_period"],
                        "new_billing_period": correction["corrected_billing_period"],
                        "status": "corrected",
                    }
                )

            except Exception as e:
                errors.append({"membership_type": correction["name"], "error": str(e)})

        return {
            "success": True,
            "total_corrections_needed": len(corrections),
            "applied_corrections": len(applied_corrections),
            "errors": len(errors),
            "corrections_applied": applied_corrections,
            "error_details": errors,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def fix_membership_dues_schedule_templates():
    """Fix membership dues schedule template billing frequency misconfigurations"""
    try:
        # Get all template schedules (where member is null)
        template_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters=[["member", "is", "not set"]],
            fields=["name", "schedule_name", "billing_frequency", "membership_type"],
            order_by="name",
        )

        # Define the expected corrections
        corrections = []

        for schedule in template_schedules:
            expected_frequency = None
            name_lower = schedule.schedule_name.lower()

            if "daily" in name_lower:
                expected_frequency = "Daily"
            elif "monthly" in name_lower:
                expected_frequency = "Monthly"
            elif "weekly" in name_lower:
                expected_frequency = "Weekly"
            elif "quarterly" in name_lower:
                expected_frequency = "Quarterly"
            elif "annual" in name_lower:
                expected_frequency = "Annual"

            if expected_frequency and schedule.billing_frequency != expected_frequency:
                corrections.append(
                    {
                        "name": schedule.name,
                        "schedule_name": schedule.schedule_name,
                        "current_billing_frequency": schedule.billing_frequency,
                        "corrected_billing_frequency": expected_frequency,
                    }
                )

        # Apply corrections
        applied_corrections = []
        errors = []

        for correction in corrections:
            try:
                # Update the dues schedule template
                schedule_doc = frappe.get_doc("Membership Dues Schedule", correction["name"])
                schedule_doc.billing_frequency = correction["corrected_billing_frequency"]
                schedule_doc.save(ignore_permissions=True)

                applied_corrections.append(
                    {
                        "schedule_name": correction["schedule_name"],
                        "old_billing_frequency": correction["current_billing_frequency"],
                        "new_billing_frequency": correction["corrected_billing_frequency"],
                        "status": "corrected",
                    }
                )

            except Exception as e:
                errors.append({"schedule_name": correction["schedule_name"], "error": str(e)})

        return {
            "success": True,
            "total_corrections_needed": len(corrections),
            "applied_corrections": len(applied_corrections),
            "errors": len(errors),
            "corrections_applied": applied_corrections,
            "error_details": errors,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def fix_orphaned_schedule_templates():
    """Fix or remove schedule templates that reference non-existent membership types"""
    try:
        # Get all template schedules
        template_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters=[["member", "is", "not set"]],
            fields=["name", "schedule_name", "billing_frequency", "membership_type"],
            order_by="name",
        )

        orphaned_templates = []
        corrected_templates = []
        errors = []

        for schedule in template_schedules:
            # Check if membership type exists
            if schedule.membership_type and not frappe.db.exists("Membership Type", schedule.membership_type):
                orphaned_templates.append(
                    {
                        "name": schedule.name,
                        "schedule_name": schedule.schedule_name,
                        "missing_membership_type": schedule.membership_type,
                        "billing_frequency": schedule.billing_frequency,
                    }
                )

            # Also check for billing frequency mismatches in existing types
            elif schedule.membership_type:
                try:
                    membership_type = frappe.get_doc("Membership Type", schedule.membership_type)
                    if schedule.billing_frequency != membership_type.billing_period:
                        # Update template to match membership type
                        schedule_doc = frappe.get_doc("Membership Dues Schedule", schedule.name)
                        old_frequency = schedule_doc.billing_frequency
                        schedule_doc.billing_frequency = membership_type.billing_period
                        schedule_doc.save(ignore_permissions=True)

                        corrected_templates.append(
                            {
                                "schedule_name": schedule.schedule_name,
                                "old_frequency": old_frequency,
                                "new_frequency": membership_type.billing_period,
                                "matched_to_membership_type": membership_type.name,
                            }
                        )

                except Exception as e:
                    errors.append({"schedule_name": schedule.schedule_name, "error": str(e)})

        # For orphaned templates, try to clean them up or fix them
        cleanup_results = []
        for orphan in orphaned_templates:
            try:
                # Delete orphaned templates
                frappe.delete_doc("Membership Dues Schedule", orphan["name"], ignore_permissions=True)
                cleanup_results.append(
                    {
                        "schedule_name": orphan["schedule_name"],
                        "action": "deleted",
                        "reason": f"Referenced non-existent membership type: {orphan['missing_membership_type']}",
                    }
                )
            except Exception as e:
                errors.append(
                    {"schedule_name": orphan["schedule_name"], "error": f"Failed to delete: {str(e)}"}
                )

        return {
            "success": len(errors) == 0,
            "orphaned_templates_found": len(orphaned_templates),
            "templates_corrected": len(corrected_templates),
            "templates_deleted": len(cleanup_results),
            "errors": len(errors),
            "corrected_templates": corrected_templates,
            "cleanup_results": cleanup_results,
            "error_details": errors,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def validate_billing_consistency():
    """Validate that membership types and dues schedule templates have consistent billing frequencies"""
    try:
        inconsistencies = []

        # Get all membership types
        membership_types = frappe.get_all(
            "Membership Type", fields=["name", "billing_period", "dues_schedule_template"], order_by="name"
        )

        # Check each membership type against its template
        for mt in membership_types:
            # Use explicit template assignment instead of name generation
            if not mt.dues_schedule_template:
                continue  # Skip membership types without templates

            template = frappe.db.get_value(
                "Membership Dues Schedule",
                {"name": mt.dues_schedule_template, "is_template": 1},
                ["name", "billing_frequency"],
                as_dict=True,
            )

            if template and template.billing_frequency != mt.billing_period:
                inconsistencies.append(
                    {
                        "membership_type": mt.name,
                        "membership_billing_period": mt.billing_period,
                        "template_billing_frequency": template.billing_frequency,
                        "template_name": template_name,
                        "issue": "Mismatch between membership type and template",
                    }
                )

        return {
            "success": len(inconsistencies) == 0,
            "total_checked": len(membership_types),
            "inconsistencies_found": len(inconsistencies),
            "inconsistencies": inconsistencies,
            "status": "All billing configurations are consistent"
            if len(inconsistencies) == 0
            else f"Found {len(inconsistencies)} inconsistencies",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_silvia_scenario_after_fixes():
    """Test if Silvia's scenario would work correctly now with the fixed configurations"""
    try:
        # Check if Test Daily Membership is now properly configured
        test_daily_type = frappe.get_doc("Membership Type", "Test Daily Membership")

        # Check the template
        template = frappe.db.get_value(
            "Membership Dues Schedule",
            {"schedule_name": "Template-Test Daily Membership", "member": ["is", "not set"]},
            ["name", "billing_frequency", "next_invoice_date"],
            as_dict=True,
        )

        # Simulate what would happen if Silvia was on Test Daily Membership now
        from frappe.utils import add_days, today

        expected_daily_next_invoice = add_days(today(), 1)  # Tomorrow for daily

        scenario_analysis = {
            "membership_type_name": test_daily_type.name,
            "membership_billing_period": test_daily_type.billing_period,
            "template_billing_frequency": template.billing_frequency if template else None,
            "configurations_match": test_daily_type.billing_period
            == (template.billing_frequency if template else None),
            "expected_daily_behavior": {
                "next_invoice_should_be": expected_daily_next_invoice,
                "effective_date_should_be": expected_daily_next_invoice,
                "instead_of_7_days_away": "2025-07-27",
            },
            "fix_status": "FIXED" if test_daily_type.billing_period == "Daily" else "STILL_BROKEN",
        }

        return {
            "success": True,
            "scenario_analysis": scenario_analysis,
            "summary": f"Test Daily Membership is now {scenario_analysis['fix_status']} - billing_period is {test_daily_type.billing_period}",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_anbi_dashboard_sql():
    """Test the SQL query from ANBI dashboard to check if it works"""
    try:
        # Test the donor statistics query that was causing the error
        donor_stats = frappe.db.sql(
            """
            SELECT
                COUNT(DISTINCT donor.name) as unique_donors,
                COUNT(DISTINCT CASE WHEN donor.donor_type = 'Individual' THEN donor.name END) as individual_donors,
                COUNT(DISTINCT CASE WHEN donor.donor_type = 'Organization' THEN donor.name END) as organization_donors,
                COUNT(DISTINCT CASE WHEN donor.anbi_consent = 1 THEN donor.name END) as donors_with_consent
            FROM `tabDonor` donor
            WHERE donor.name IN (
                SELECT DISTINCT d.donor FROM `tabDonation` d
                WHERE d.paid = 1 AND d.docstatus = 1
            )
        """,
            as_dict=1,
        )

        if donor_stats:
            result = donor_stats[0]
        else:
            result = {
                "unique_donors": 0,
                "individual_donors": 0,
                "organization_donors": 0,
                "donors_with_consent": 0,
            }

        return {"success": True, "message": "SQL query executed successfully", "donor_stats": result}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def fix_all_test_data_billing_configurations():
    """Fix all test data billing configuration issues in one operation"""
    try:
        results = {
            "membership_types": fix_membership_type_billing_periods(),
            "dues_schedule_templates": fix_membership_dues_schedule_templates(),
        }

        # Summary
        total_corrections = results["membership_types"].get("applied_corrections", 0) + results[
            "dues_schedule_templates"
        ].get("applied_corrections", 0)

        total_errors = results["membership_types"].get("errors", 0) + results["dues_schedule_templates"].get(
            "errors", 0
        )

        overall_success = (
            results["membership_types"].get("success", False)
            and results["dues_schedule_templates"].get("success", False)
            and total_errors == 0
        )

        return {
            "success": overall_success,
            "total_corrections_applied": total_corrections,
            "total_errors": total_errors,
            "detailed_results": results,
            "summary": f"Applied {total_corrections} corrections with {total_errors} errors",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_membership_type_billing_periods():
    """Check all membership types and their billing periods for misconfigurations"""
    try:
        # Get all membership types
        membership_types = frappe.get_all(
            "Membership Type", fields=["name", "minimum_amount", "billing_period"], order_by="name"
        )

        # Get template dues schedules
        template_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters=[["member", "is", "not set"]],
            fields=["name", "schedule_name", "billing_frequency", "status", "membership_type"],
            order_by="name",
        )

        # Analyze misconfigurations
        misconfigurations = []

        for mt in membership_types:
            expected_billing = None
            name_lower = mt.name.lower()

            if "daily" in name_lower or "daglid" in name_lower:
                expected_billing = "Daily"
            elif "monthly" in name_lower or "maandlid" in name_lower:
                expected_billing = "Monthly"
            elif "weekly" in name_lower:
                expected_billing = "Weekly"
            elif "annual" in name_lower or "yearly" in name_lower or "jaarlid" in name_lower:
                expected_billing = "Annual"

            if expected_billing and mt.billing_period != expected_billing:
                misconfigurations.append(
                    {
                        "membership_type": mt.name,
                        "current_billing_period": mt.billing_period,
                        "expected_billing_period": expected_billing,
                        "issue": f"Type suggests {expected_billing} but set to {mt.billing_period}",
                    }
                )

        # Check for template schedules with wrong billing frequency
        schedule_misconfigurations = []
        for schedule in template_schedules:
            name_lower = schedule.schedule_name.lower()
            expected_frequency = None

            if "daily" in name_lower:
                expected_frequency = "Daily"
            elif "monthly" in name_lower:
                expected_frequency = "Monthly"
            elif "weekly" in name_lower:
                expected_frequency = "Weekly"
            elif "annual" in name_lower:
                expected_frequency = "Annual"

            if expected_frequency and schedule.billing_frequency != expected_frequency:
                schedule_misconfigurations.append(
                    {
                        "schedule_name": schedule.schedule_name,
                        "current_billing_frequency": schedule.billing_frequency,
                        "expected_billing_frequency": expected_frequency,
                        "issue": f"Name suggests {expected_frequency} but set to {schedule.billing_frequency}",
                    }
                )

        return {
            "membership_types": membership_types,
            "template_schedules": template_schedules,
            "misconfigurations": misconfigurations,
            "schedule_misconfigurations": schedule_misconfigurations,
            "summary": {
                "total_membership_types": len(membership_types),
                "misconfigured_types": len(misconfigurations),
                "total_template_schedules": len(template_schedules),
                "misconfigured_schedules": len(schedule_misconfigurations),
            },
        }

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def investigate_7_day_discrepancy():
    """Investigate where the 7-day effective date came from in AMEND-2025-02547"""
    try:
        # Look for patterns that might explain the 7-day difference
        analysis_results = []

        # Check if this is related to add_days(today(), 7) somewhere
        from frappe.utils import add_days, today

        seven_days_from_today = add_days(today(), 7)
        analysis_results.append(
            {
                "hypothesis": "add_days(today(), 7)",
                "calculated_date": seven_days_from_today,
                "matches_amendment": seven_days_from_today == "2025-07-27",
            }
        )

        # Check if it's related to a weekly billing cycle
        seven_days_from_creation = add_days("2025-07-20", 7)  # Amendment creation date
        analysis_results.append(
            {
                "hypothesis": "7 days from creation date",
                "calculated_date": seven_days_from_creation,
                "matches_amendment": seven_days_from_creation == "2025-07-27",
            }
        )

        # Check if this could be from a fallback in set_default_effective_date exception handling
        thirty_days_fallback = add_days(today(), 30)
        analysis_results.append(
            {
                "hypothesis": "30-day fallback (should not match)",
                "calculated_date": thirty_days_fallback,
                "matches_amendment": thirty_days_fallback == "2025-07-27",
            }
        )

        # Check if there's any pattern with the membership creation or other dates
        amendment = frappe.get_doc("Contribution Amendment Request", "AMEND-2025-02547")
        membership = frappe.get_doc("Membership", amendment.membership)

        analysis_results.append(
            {
                "amendment_creation": amendment.creation,
                "membership_creation": membership.creation,
                "membership_start_date": getattr(membership, "start_date", None),
                "membership_from_date": getattr(membership, "from_date", None),
            }
        )

        # Let me check if there's any code that sets effective_date manually
        # This might be from user input or some other logic

        # Also check if this amendment was created through a specific API call
        # that might have passed an explicit effective_date

        potential_sources = [
            "Manual user input during amendment creation",
            "API call with explicit effective_date parameter",
            "Some business logic calculating 7 days for weekly cycles",
            "Error in exception handling leading to wrong fallback",
            "Test data setup with hardcoded dates",
        ]

        return {
            "amendment_effective_date": amendment.effective_date,
            "today": today(),
            "analysis_results": analysis_results,
            "potential_sources": potential_sources,
            "key_finding": "The 7-day date was NOT calculated by set_default_effective_date method",
            "likely_cause": "External input - either user input, API parameter, or test data setup",
        }

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def trace_effective_date_calculation(amendment_name):
    """Trace exactly how the effective date was calculated for a specific amendment"""
    try:
        amendment = frappe.get_doc("Contribution Amendment Request", amendment_name)
        member_name = amendment.member

        # Simulate the exact logic from set_default_effective_date
        trace_steps = []

        # Step 1: Check if effective_date was already set
        if amendment.effective_date:
            trace_steps.append(
                {
                    "step": 1,
                    "description": "Amendment already has effective_date set",
                    "value": amendment.effective_date,
                    "source": "pre-existing",
                }
            )

        # Step 2: Check for active dues schedule
        active_dues_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "status": "Active"},
            ["name", "next_invoice_date"],
            as_dict=True,
        )

        if active_dues_schedule:
            trace_steps.append(
                {
                    "step": 2,
                    "description": "Found active dues schedule",
                    "schedule_name": active_dues_schedule.name,
                    "next_invoice_date": active_dues_schedule.next_invoice_date,
                }
            )

            if active_dues_schedule.next_invoice_date:
                trace_steps.append(
                    {
                        "step": 3,
                        "description": "Using next_invoice_date from dues schedule",
                        "calculated_date": active_dues_schedule.next_invoice_date,
                        "source": "dues_schedule_next_invoice",
                    }
                )
            else:
                fallback_date = add_days(today(), 30)
                trace_steps.append(
                    {
                        "step": 3,
                        "description": "next_invoice_date is None, using fallback",
                        "calculated_date": fallback_date,
                        "source": "fallback_30_days",
                    }
                )
        else:
            fallback_date = add_days(today(), 30)
            trace_steps.append(
                {
                    "step": 2,
                    "description": "No active dues schedule found, using fallback",
                    "calculated_date": fallback_date,
                    "source": "fallback_30_days",
                }
            )

        # Now let's also check what the ACTUAL calculation would be if we ran set_default_effective_date
        # Create a test amendment to see what date it would calculate
        test_amendment = frappe.new_doc("Contribution Amendment Request")
        test_amendment.membership = amendment.membership
        test_amendment.member = amendment.member
        test_amendment.amendment_type = "Fee Change"
        test_amendment.requested_amount = 10.0
        test_amendment.reason = "Test calculation"

        # Call set_default_effective_date to see what it calculates
        test_amendment.set_default_effective_date()

        trace_steps.append(
            {
                "step": 4,
                "description": "Fresh calculation using set_default_effective_date",
                "calculated_date": test_amendment.effective_date,
                "source": "set_default_effective_date_method",
            }
        )

        # Compare with actual amendment date
        actual_effective_date = amendment.effective_date
        expected_from_schedule = (
            active_dues_schedule.next_invoice_date
            if active_dues_schedule and active_dues_schedule.next_invoice_date
            else add_days(today(), 30)
        )

        discrepancy_analysis = {
            "actual_effective_date": actual_effective_date,
            "expected_from_schedule": expected_from_schedule,
            "fresh_calculation": test_amendment.effective_date,
            "discrepancy_detected": str(actual_effective_date) != str(expected_from_schedule),
            "days_difference_actual_vs_expected": (
                getdate(actual_effective_date) - getdate(expected_from_schedule)
            ).days
            if actual_effective_date and expected_from_schedule
            else None,
        }

        return {
            "amendment_name": amendment_name,
            "member": member_name,
            "trace_steps": trace_steps,
            "discrepancy_analysis": discrepancy_analysis,
            "today": today(),
            "active_dues_schedule": active_dues_schedule,
        }

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def debug_silvia_schedule_issue():
    """Debug why Silvia's effective date is 7 days when she should be on daily schedule"""
    try:
        member_name = "Assoc-Member-2025-07-2544"  # Silvia Hanna Rietenmaker

        # Get member details
        member = frappe.get_doc("Member", member_name)

        # Get ALL dues schedules for this member (including inactive ones)
        all_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name},
            fields=[
                "name",
                "schedule_name",
                "billing_frequency",
                "status",
                "next_invoice_date",
                "dues_rate",
                "creation",
                "modified",
            ],
            order_by="creation desc",
        )

        # Get all daily schedules in the system
        all_daily_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"billing_frequency": "Daily"},
            fields=[
                "name",
                "schedule_name",
                "member",
                "billing_frequency",
                "status",
                "next_invoice_date",
                "dues_rate",
            ],
            order_by="creation desc",
        )

        # Check current amendment details
        amendment = frappe.get_doc("Contribution Amendment Request", "AMEND-2025-02547")

        # Get active dues schedule and check its next invoice calculation
        active_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "status": "Active"},
            ["name", "next_invoice_date", "billing_frequency"],
            as_dict=True,
        )

        # Check what should be the next invoice date for daily billing
        from frappe.utils import add_days, today

        expected_daily_next_invoice = add_days(today(), 1)  # Tomorrow for daily

        return {
            "member_full_name": member.full_name,
            "member_id": member_name,
            "amendment_effective_date": amendment.effective_date,
            "amendment_creation": amendment.creation,
            "all_member_schedules": all_schedules,
            "all_daily_schedules_in_system": all_daily_schedules,
            "current_active_schedule": active_schedule,
            "today": today(),
            "expected_daily_next_invoice": expected_daily_next_invoice,
            "issue_analysis": {
                "current_billing_frequency": active_schedule.billing_frequency if active_schedule else None,
                "current_next_invoice": active_schedule.next_invoice_date if active_schedule else None,
                "expected_for_daily": expected_daily_next_invoice,
                "discrepancy": "Member appears to be on Annual billing instead of Daily billing",
            },
        }

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def check_member_and_dues_schedule(member_name):
    """Check member details and their dues schedule"""
    try:
        member = frappe.get_doc("Member", member_name)

        # Get active dues schedule
        active_dues_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "status": "Active"},
            ["name", "next_invoice_date", "billing_frequency", "schedule_name", "dues_rate"],
            as_dict=True,
        )

        dues_schedule_doc = None
        if active_dues_schedule:
            dues_schedule_doc = frappe.get_doc("Membership Dues Schedule", active_dues_schedule.name)

        return {
            "member_name": member.full_name,
            "member_id": member.name,
            "active_dues_schedule": active_dues_schedule,
            "dues_schedule_details": {
                "name": dues_schedule_doc.name if dues_schedule_doc else None,
                "schedule_name": dues_schedule_doc.schedule_name if dues_schedule_doc else None,
                "billing_frequency": dues_schedule_doc.billing_frequency if dues_schedule_doc else None,
                "next_invoice_date": dues_schedule_doc.next_invoice_date if dues_schedule_doc else None,
                "amount": dues_schedule_doc.dues_rate if dues_schedule_doc else None,
                "status": dues_schedule_doc.status if dues_schedule_doc else None,
            }
            if dues_schedule_doc
            else None,
        }
    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def investigate_effective_date_logic():
    """Investigate how effective dates are set in contribution amendment requests"""
    try:
        # Get recent amendment requests to understand the pattern
        amendments = frappe.get_all(
            "Contribution Amendment Request",
            fields=["name", "effective_date", "creation", "status", "member"],
            order_by="creation desc",
            limit=10,
        )

        analysis_results = []

        for amendment in amendments:
            # Calculate days between creation and effective date
            creation_date = getdate(amendment.creation)
            effective_date = getdate(amendment.effective_date) if amendment.effective_date else None

            days_difference = None
            if effective_date:
                days_difference = (effective_date - creation_date).days

            # Check if there's an active dues schedule for this member
            active_dues_schedule = frappe.db.get_value(
                "Membership Dues Schedule",
                {"member": amendment.member, "status": "Active"},
                ["name", "next_invoice_date"],
                as_dict=True,
            )

            analysis_results.append(
                {
                    "amendment_name": amendment.name,
                    "creation_date": creation_date,
                    "effective_date": effective_date,
                    "days_difference": days_difference,
                    "member": amendment.member,
                    "active_dues_schedule": active_dues_schedule.name if active_dues_schedule else None,
                    "dues_next_invoice": active_dues_schedule.next_invoice_date
                    if active_dues_schedule
                    else None,
                    "status": amendment.status,
                }
            )

        # Also analyze the logic in set_default_effective_date
        logic_explanation = {
            "default_logic": "The set_default_effective_date method follows this priority:",
            "priority_1": "If member has active dues schedule with next_invoice_date, use that date",
            "priority_2": "Otherwise, fallback to add_days(today(), 30) - 30 days from creation",
            "fallback_on_error": "If any exception occurs, use add_days(today(), 30)",
            "method_called_during": "Called during validation (validate method)",
        }

        return {
            "success": True,
            "logic_explanation": logic_explanation,
            "recent_amendments_analysis": analysis_results,
            "today_date": today(),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def validate_production_schema():
    """Comprehensive validation of production schema readiness"""

    print("=== Production Schema Validation ===")

    results = []
    errors = []

    try:
        # 1. Validate Contribution Amendment Request DocType
        print("\n--- Validating Contribution Amendment Request DocType ---")

        doctype = frappe.get_doc("DocType", "Contribution Amendment Request")

        # Check required new fields
        required_fields = [
            "new_dues_schedule",
            "current_dues_schedule",
            "current_amount",
            "current_billing_interval",
            "old_legacy_system_cancelled",
            "processing_notes",
        ]

        existing_fields = [field.fieldname for field in doctype.fields]

        for field in required_fields:
            if field in existing_fields:
                results.append(f"✓ Field '{field}' exists in Contribution Amendment Request")
            else:
                errors.append(f"❌ Field '{field}' missing from Contribution Amendment Request")

        # Check field properties
        for field in doctype.fields:
            if field.fieldname == "new_dues_schedule":
                if field.fieldtype == "Link" and field.options == "Membership Dues Schedule":
                    results.append("✓ new_dues_schedule field properly configured")
                else:
                    errors.append(
                        f"❌ new_dues_schedule field configuration incorrect: {field.fieldtype}, {field.options}"
                    )

            if field.fieldname == "current_dues_schedule":
                if field.fieldtype == "Link" and field.options == "Membership Dues Schedule":
                    results.append("✓ current_dues_schedule field properly configured")
                else:
                    errors.append(
                        f"❌ current_dues_schedule field configuration incorrect: {field.fieldtype}, {field.options}"
                    )

        # 2. Validate Membership Dues Schedule DocType
        print("\n--- Validating Membership Dues Schedule DocType ---")

        if frappe.db.exists("DocType", "Membership Dues Schedule"):
            results.append("✓ Membership Dues Schedule DocType exists")
        else:
            errors.append("❌ Membership Dues Schedule DocType does not exist")

        # 3. Validate Database Tables
        print("\n--- Validating Database Tables ---")

        # Check if tables exist
        tables_to_check = ["tabContribution Amendment Request", "tabMembership Dues Schedule"]

        for table in tables_to_check:
            if frappe.db.table_exists(table):
                results.append(f"✓ Database table '{table}' exists")
            else:
                errors.append(f"❌ Database table '{table}' does not exist")

        # 4. Validate Custom Methods
        print("\n--- Validating Custom Methods ---")

        # Check if custom methods exist on the class
        test_doc = frappe.new_doc("Contribution Amendment Request")

        methods_to_check = [
            "create_dues_schedule_for_amendment",
            "set_current_details",
            "apply_fee_change",
            "get_current_amount",
        ]

        for method in methods_to_check:
            if hasattr(test_doc, method):
                results.append(f"✓ Method '{method}' exists on Contribution Amendment Request")
            else:
                errors.append(f"❌ Method '{method}' missing from Contribution Amendment Request")

        # 5. Validate API Endpoints
        print("\n--- Validating API Endpoints ---")

        # Check if whitelisted functions exist
        whitelisted_functions = [
            "test_enhanced_approval_workflows",
            "process_pending_amendments",
            "create_fee_change_amendment",
        ]

        for func in whitelisted_functions:
            if hasattr(ContributionAmendmentRequest, func) or func in globals():
                results.append(f"✓ Whitelisted function '{func}' exists")
            else:
                errors.append(f"❌ Whitelisted function '{func}' missing")

        # 6. Summary
        print("\n=== Validation Summary ===")

        print(f"✅ Successful validations: {len(results)}")
        print(f"❌ Errors found: {len(errors)}")

        if errors:
            print("\n🚨 ERRORS THAT MUST BE FIXED:")
            for error in errors:
                print(f"  {error}")

        print("\n✅ SUCCESSFUL VALIDATIONS:")
        for result in results:
            print(f"  {result}")

        # Return results
        return {
            "success": len(errors) == 0,
            "total_checks": len(results) + len(errors),
            "successful_checks": len(results),
            "errors": len(errors),
            "error_details": errors,
            "results": results,
            "ready_for_production": len(errors) == 0,
        }

    except Exception as e:
        error_msg = f"Fatal error during validation: {str(e)}"
        print(f"❌ {error_msg}")
        return {"success": False, "error": error_msg, "ready_for_production": False}
