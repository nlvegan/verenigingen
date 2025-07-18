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

    def set_current_details(self):
        """Set current membership details using new dues schedule approach"""
        if not self.membership:
            return

        membership = frappe.get_doc("Membership", self.membership)
        member_doc = frappe.get_doc("Member", self.member)

        # PRIORITY 1: Get current amount from active dues schedule
        active_dues_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": self.member, "status": "Active"},
            ["name", "amount", "billing_frequency"],
            as_dict=True,
        )

        if active_dues_schedule:
            self.current_amount = active_dues_schedule.amount
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
                    ["name", "current_coverage_end"],
                    as_dict=True,
                )

                if active_dues_schedule and active_dues_schedule.current_coverage_end:
                    # Set to next billing period
                    self.effective_date = add_days(active_dues_schedule.current_coverage_end, 1)
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
            member_doc.membership_fee_override = self.requested_amount
            member_doc.fee_override_reason = f"Amendment: {self.reason}"
            member_doc.fee_override_date = today()
            member_doc.fee_override_by = frappe.session.user
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
                existing_doc.save(ignore_permissions=True)

            # Create new dues schedule
            dues_schedule = frappe.new_doc("Membership Dues Schedule")
            dues_schedule.member = self.member
            dues_schedule.membership = membership.name
            dues_schedule.membership_type = membership.membership_type
            dues_schedule.contribution_mode = "Custom"
            dues_schedule.amount = self.requested_amount
            dues_schedule.uses_custom_amount = 1
            dues_schedule.custom_amount_approved = 1  # Amendment already approved
            dues_schedule.custom_amount_reason = f"Amendment Request: {self.reason}"

            # Handle zero amounts specially
            if self.requested_amount == 0:
                dues_schedule.custom_amount_reason = f"Free membership via amendment: {self.reason}"

            dues_schedule.billing_frequency = "Monthly"  # Default
            dues_schedule.payment_method = "Bank Transfer"  # Default
            dues_schedule.status = "Active"
            dues_schedule.auto_generate = 1
            dues_schedule.test_mode = 0
            dues_schedule.effective_date = self.effective_date or today()
            dues_schedule.current_coverage_start = self.effective_date or today()

            # Add amendment metadata in notes
            dues_schedule.notes = (
                f"Created from amendment request {self.name} by {frappe.session.user} on {today()}"
            )

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
            (difference / current_amount * 100) if current_amount > 0 else 0

            # impact_class = (
            #     "text-success" if difference > 0 else "text-danger" if difference < 0 else "text-muted"
            # )
            "increase" if difference > 0 else "decrease" if difference < 0 else "no change"

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
                ["current_coverage_end"],
                as_dict=True,
            )

            if active_dues_schedule and active_dues_schedule.current_coverage_end:
                effective_date = add_days(active_dues_schedule.current_coverage_end, 1)
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
    amendments = frappe.get_all(
        "Contribution Amendment Request",
        filters={"member": member_name, "status": ["in", ["Draft", "Pending Approval", "Approved"]]},
        fields=["name", "amendment_type", "status", "requested_amount", "effective_date", "reason"],
        order_by="creation desc",
    )

    return amendments


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
def test_dues_amendment_integration():
    """Test integration between dues schedules and amendment system"""
    try:
        print("=== Testing Dues Amendment Integration ===")

        # Get an existing member
        member = frappe.db.get_value("Member", {"status": "Active"}, ["name", "email"], as_dict=True)
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
def test_real_world_amendment_scenarios():
    """Test real-world scenarios for dues amendment system"""
    try:
        print("=== Testing Real-World Amendment Scenarios ===")

        # Get a member with active membership
        member = frappe.db.get_value("Member", {"status": "Active"}, ["name", "email"], as_dict=True)
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
            "old_subscription_cancelled",
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
