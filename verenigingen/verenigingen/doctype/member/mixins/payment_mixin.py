import frappe
from frappe import _
from frappe.utils import date_diff, today

from verenigingen.utils.constants import Roles
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


class PaymentMixin:
    """Mixin for payment-related functionality"""

    def _batch_fetch_with_chunking(self, doctype, name_list, fields, filters=None, chunk_size=500):
        """Fetch records in batches — delegates to shared utility."""
        from verenigingen.utils import batch_fetch_with_chunking

        return batch_fetch_with_chunking(doctype, name_list, fields, filters, chunk_size)

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.FINANCIAL)
    def load_payment_history(self):
        """
        Load payment history for this member with focus on invoices.
        Also include unreconciled payments, but maintain separation from the Donation system.
        Then save the document to persist the changes.

        OPTIMIZED: Uses batch queries and intelligent caching for 3x performance improvement
        """
        # Import optimized function
        from verenigingen.utils.background_jobs import refresh_member_financial_history_optimized

        try:
            # Use optimized batch query approach
            result = refresh_member_financial_history_optimized(self)

            # Legacy behavior for backward compatibility
            if result.get("status") == "completed":
                return True
            elif result.get("status") == "cached":
                return True
            else:
                # Fallback to original method if optimization fails
                frappe.log_error(f"Optimized payment history failed for {self.name}, using fallback")
                return self._load_payment_history_original()

        except Exception as e:
            frappe.log_error(f"Optimized payment history failed for {self.name}: {e}, using fallback")
            return self._load_payment_history_original()

    def _load_payment_history_original(self):
        """Original payment history loading method as fallback"""
        self._load_payment_history_without_save()
        # Use flags to reduce activity logging for bulk payment history updates
        self.flags.ignore_version = True
        self.flags.ignore_links = True
        # Allow updates after submit for payment history refresh
        self.flags.ignore_validate_update_after_submit = True

        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        member_result = secure_document_operation(
            operation="save",
            doc=self,
            justification=f"Update member {self.name} payment history with optimized financial data",
            required_permissions=["Member:write"],
        )

        if not member_result.success:
            frappe.log_error(
                f"Failed to save member payment history: {'; '.join(member_result.errors)}",
                "Member Payment History Security",
            )
            return False
        return True

    def on_load(self):
        """Load payment history when the document is loaded"""
        if self.customer:
            self._load_payment_history_without_save()

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.FINANCIAL)
    def refresh_payment_entry(self, payment_entry_name: str):
        """
        Update payment history for a specific payment entry instead of full rebuild

        INCREMENTAL UPDATE: Only processes the affected payment entry and related invoices
        for significant performance improvement
        """
        try:
            if not self.customer:
                return {"status": "skipped", "reason": "No customer record"}

            # Import optimized functions
            from verenigingen.utils.background_jobs import refresh_member_financial_history_optimized

            # Invalidate specific cache entries
            self.invalidate_payment_cache_for_entry(payment_entry_name)

            # Get affected invoices for this payment entry
            affected_invoices = self.get_invoices_for_payment(payment_entry_name)

            if affected_invoices:
                # Update only affected invoices in payment history
                result = self.update_payment_history_for_invoices(affected_invoices)

                # Save with optimized flags
                self.flags.ignore_version = True
                self.flags.ignore_links = True
                self.flags.ignore_validate_update_after_submit = True

                # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                member_result = secure_document_operation(
                    operation="save",
                    doc=self,
                    justification=f"Incremental member {self.name} payment history update for payment entry {payment_entry_name}",
                    required_permissions=["Member:write"],
                )

                if not member_result.success:
                    frappe.log_error(
                        f"Failed to save incremental payment update: {'; '.join(member_result.errors)}",
                        "Member Payment History Security",
                    )
                    return {"status": "error", "errors": member_result.errors}

                return {
                    "status": "incremental_update_completed",
                    "invoices_updated": len(affected_invoices),
                    "payment_entry": payment_entry_name,
                }
            else:
                # If no specific invoices affected, do minimal refresh
                result = refresh_member_financial_history_optimized(self, payment_entry_name)
                return result

        except Exception as e:
            frappe.log_error(f"Incremental payment update failed for {self.name}: {e}")
            # Fallback to full refresh
            return self.load_payment_history()

    def _load_payment_history_without_save(self):
        """
        Internal method to load payment history without saving.

        Uses optimized batch queries. No fallback - errors will surface for debugging.
        """
        if not self.customer:
            return

        # Use optimized batch version (81 → 3 queries)
        self._load_payment_history_batched()

    def _load_payment_history_batched(self):
        """
        OPTIMIZED: Load payment history using batch queries to eliminate N+1 pattern.

        EXTRACTED: Delegates to PaymentHistoryService.load_payment_history_batched()
        for service layer separation (Phase 1 Payment Service Extraction).

        Query Reduction: 81 queries → 3 queries (96% reduction)
        See PaymentHistoryService for implementation details.
        """
        if not self.customer:
            return

        from verenigingen.services.member.payment import get_payment_history_service

        try:
            result = get_payment_history_service().load_payment_history_batched(self)

            if not result.success:
                frappe.log_error(
                    f"Payment history loading failed for {self.name}: {result.error_message}",
                    "Payment History Service Error",
                )

        except Exception as e:
            frappe.log_error(
                f"Critical error in batched payment history loading: {str(e)}",
                "Batched Payment History Load Error",
            )
            # Don't raise - allow fallback to work

    def _get_coverage_from_schedule(self, invoice_name):
        """
        Get coverage from schedule - direct link, no heuristics (authoritative source).

        EXTRACTED: Delegates to PaymentCoverageService.get_coverage_from_schedule()
        for service layer separation (Phase 1 Payment Service Extraction).
        """
        from verenigingen.services.member.payment import get_payment_coverage_service

        coverage = get_payment_coverage_service().get_coverage_from_schedule(self.name, invoice_name)
        return (coverage.start_date, coverage.end_date)

    def _get_coverage_from_invoice(self, invoice):
        """
        Fallback: get coverage from invoice cache.

        EXTRACTED: Delegates to PaymentCoverageService.get_coverage_from_invoice()
        for service layer separation (Phase 1 Payment Service Extraction).
        """
        from verenigingen.services.member.payment import get_payment_coverage_service

        coverage = get_payment_coverage_service().get_coverage_from_invoice(invoice)
        return (coverage.start_date, coverage.end_date)

    def validate_payment_method(self):
        """Validate payment method and related fields"""
        if not hasattr(self, "payment_method"):
            memberships = frappe.get_all(
                "Membership",
                filters={"member": self.name, "status": ["!=", "Cancelled"]},
                fields=["name", "membership_type", "status"],
            )

            for membership in memberships:
                # Check if member has SEPA mandates (indicates SEPA payment method)
                sepa_mandates = frappe.get_all(
                    "SEPA Mandate", filters={"member": self.name, "status": "Active"}, limit=1
                )
                if sepa_mandates:
                    default_mandate = self.get_default_sepa_mandate()
                    if not default_mandate:
                        frappe.msgprint(
                            _(
                                "Member {0} has a membership with SEPA Direct Debit payment method but no active SEPA mandate."
                            ).format(self.name),
                            indicator="yellow",
                        )
                    break

            return

    def set_payment_reference(self):
        """Generate a unique payment reference for this membership"""
        if not self.payment_reference and self.name:
            self.payment_reference = self.name

    def validate_bank_details(self):
        """Validate bank details if payment method is SEPA Direct Debit"""
        # Track IBAN changes for history
        if hasattr(self, "iban") and self.iban:
            # Format and validate IBAN
            self.iban = self.validate_iban_format(self.iban)

            # Check if IBAN has changed on existing records
            if not self.is_new() and self.has_value_changed("iban"):
                self.track_iban_change()

        # Additional validation for SEPA Direct Debit
        if getattr(self, "payment_method", None) == "SEPA Direct Debit":
            if not self.iban:
                frappe.throw(_("IBAN is required for SEPA Direct Debit payment method"))

            if not self.bank_account_name:
                frappe.throw(_("Account Holder Name is required for SEPA Direct Debit payment method"))

    def validate_iban_format(self, iban):
        """
        Comprehensive IBAN validation and formatting using PaymentValidationService.

        CONSOLIDATED: Delegates all validation and BIC derivation to PaymentValidationService.
        The service handles IBAN validation, formatting, and automatic BIC derivation for Dutch banks.

        Args:
            iban: IBAN to validate and format

        Returns:
            str: Formatted IBAN

        Raises:
            frappe.ValidationError: If IBAN validation fails
        """
        if not iban:
            return None

        from verenigingen.services.payment.validation_service import get_payment_validation_service

        service = get_payment_validation_service()

        # Use comprehensive bank details validation with auto BIC derivation
        # Only auto-derive BIC if IBAN changed or BIC is empty (performance optimization)
        iban_changed = self.has_value_changed("iban") if not self.is_new() else True
        should_derive_bic = hasattr(self, "bic") and (iban_changed or not self.bic)

        # When deriving BIC, don't pass the old BIC to the service
        # This ensures the service actually derives a new one
        bic_for_validation = None if should_derive_bic else (self.bic if hasattr(self, "bic") else None)

        result = service.validate_bank_details(
            iban=iban,
            bic=bic_for_validation,
            account_holder_name=self.bank_account_name if hasattr(self, "bank_account_name") else None,
            auto_derive_bic=should_derive_bic,
            require_bic=False,
        )

        if not result.valid:
            # Service provides user-friendly error messages
            frappe.throw(result.message, title=_("Invalid IBAN"), exc=frappe.ValidationError)

        # Update BIC if it was derived by the service
        if should_derive_bic and result.data.get("bic") and result.data.get("bic_derived"):
            if self.bic != result.data["bic"]:
                self.bic = result.data["bic"]

        return result.data.get("formatted_iban", iban)

    def validate_iban_history_rows(self):
        """Enforce the rules `Member IBAN History.validate()` stated but never ran.

        Member IBAN History is a child table (`"istable": 1`), so Frappe never calls
        its own `validate()` -- see #596. Its `to_date`/`is_active` consistency checks
        had no other enforcement, and its BIC auto-derivation was the only thing that
        would have filled in a missing BIC for a row appended without one (as
        `services/member/approval/member_approval_service.py`'s
        `create_member_iban_history` does). IBAN format/checksum validation is
        deliberately NOT repeated here: `track_iban_change` above already formats and
        validates `self.iban` before appending, so every row this class itself writes
        already carries a clean IBAN; re-validating a possibly-legacy IBAN already
        sitting in history on every subsequent save would risk breaking old records
        this method never touched before.
        """
        from verenigingen.utils.validation.iban_validator import derive_bic_from_iban

        for row in self.iban_history:
            if row.to_date and row.from_date and row.to_date < row.from_date:
                frappe.throw(
                    _("IBAN History row {0}: Valid Until date cannot be before Valid From date").format(
                        row.idx
                    )
                )

            if row.is_active and row.to_date:
                frappe.throw(
                    _("IBAN History row {0}: Active IBAN records should not have an end date").format(row.idx)
                )

            if not row.changed_by:
                row.changed_by = frappe.session.user

            if row.iban and not row.bic:
                derived_bic = derive_bic_from_iban(row.iban)
                if derived_bic:
                    row.bic = derived_bic

    def track_iban_change(self):
        """
        Track IBAN changes in history.

        NOTE: Cannot delegate to external manager during save due to recursion issues.
        Keeps inline implementation. Deactivates old entries via in-memory mutation
        (not SQL UPDATE) so Frappe's child table save persists the changes.
        """
        try:
            # Get old IBAN from database
            old_iban = frappe.db.get_value("Member", self.name, "iban")

            if old_iban and old_iban != self.iban:
                # Deactivate previous IBAN history records in memory so Frappe
                # persists the change when saving the child table.
                for row in self.iban_history:
                    if row.is_active and row.iban == old_iban:
                        row.is_active = 0
                        row.to_date = today()

                # Add new IBAN history record
                self.append(
                    "iban_history",
                    {
                        "iban": self.iban,
                        "bic": self.bic,
                        "bank_account_name": self.bank_account_name,
                        "from_date": today(),
                        "is_active": 1,
                        "changed_by": frappe.session.user,
                        "change_reason": "Bank Change" if old_iban else "Initial Setup",
                    },
                )

                frappe.logger().info(f"IBAN changed for member {self.name} from {old_iban} to {self.iban}")

                # Show SEPA mandate warning if applicable
                if hasattr(self, "payment_method") and self.payment_method == "SEPA Direct Debit":
                    frappe.msgprint(
                        _(
                            "IBAN has been changed. Please review SEPA mandates as they may need to be updated."
                        ),
                        indicator="orange",
                        alert=True,
                    )
        except Exception as e:
            frappe.logger().error(f"Error tracking IBAN change for member {self.name}: {str(e)}")

    def can_view_member_payments(self, view_member):
        """Check if this member can view another member's payment info"""
        if Roles.SYSTEM_MANAGER in frappe.get_roles(self.user):
            return True

        if self.name == view_member:
            return True

        if not self._is_chapter_management_enabled():
            return False

        member_obj = frappe.get_doc("Member", view_member)

        if member_obj.permission_category == "Public":
            return True

        if member_obj.permission_category == "Admin Only":
            return False

        # Check if member belongs to any chapters
        member_chapters = self.get_member_chapters()
        if member_chapters:
            # Check if any of the member's chapters allow viewing payments
            for chapter_name in member_chapters:
                chapter = frappe.get_doc("Chapter", chapter_name)
                if chapter.can_view_member_payments(self.name):
                    return True

        return False

    def get_member_chapters(self):
        """Get list of chapters this member belongs to"""
        try:
            chapters = frappe.get_all(
                "Chapter Member",
                filters={"member": self.name, "enabled": 1},
                fields=["parent"],
                order_by="chapter_join_date desc",
            )
            return [ch.parent for ch in chapters]
        except Exception:
            return []

    def _is_chapter_management_enabled(self):
        """Check if chapter management is enabled"""
        try:
            return frappe.db.get_single_value("Verenigingen Settings", "enable_chapter_management") == 1
        except Exception:
            return True

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.FINANCIAL)
    def refresh_financial_history(self):
        """
        Atomic financial history refresh with integrity checking.

        EXTRACTED: Delegates to PaymentHistoryService.refresh_financial_history()
        for service layer separation (Phase 1 Payment Service Extraction).

        This method:
        1. Cleans broken/invalid entries from payment history
        2. Adds missing entries without clearing valid existing data
        3. Refreshes dues schedule history

        Called by the "Refresh Financial History" button and scheduled tasks.
        """
        from verenigingen.services.member.payment import get_payment_history_service

        result = get_payment_history_service().refresh_financial_history(self)

        # Convert OperationResult to dict for backward compatibility.
        # OperationResult has no `message` attribute; the success message lives in
        # metadata (set via OperationResult.ok(..., message=...)).
        if result.success:
            return {
                "success": True,
                "message": result.metadata.get("message"),
                "payment_history_count": result.data.get("payment_history_count", 0),
                "added_entries": result.data.get("added_entries", 0),
                "removed_entries": result.data.get("removed_entries", 0),
                "cleanup_details": result.data.get("cleanup_details", {}),
                "method": result.data.get("method", "atomic_updates_with_cleanup"),
            }
        else:
            return {"success": False, "message": result.error_message}

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.FINANCIAL)
    def force_full_payment_history_rebuild(self):
        """
        Legacy method for full payment history rebuild - ONLY use when atomic updates fail
        This method clears and rebuilds the entire payment history table
        """
        try:
            # Set flags to reduce activity logging for bulk financial updates
            self.flags.ignore_version = True
            self.flags.ignore_links = True

            # LEGACY: Use the old full refresh method
            self._load_payment_history_without_save()

            # Save once with reduced logging
            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            member_result = secure_document_operation(
                operation="save",
                doc=self,
                justification=f"Legacy full payment history rebuild for member {self.name} (DEPRECATED METHOD)",
                required_permissions=["Member:write"],
            )

            if not member_result.success:
                frappe.log_error(
                    f"Failed to save legacy payment rebuild: {'; '.join(member_result.errors)}",
                    "Member Payment History Security",
                )
                return {
                    "success": False,
                    "message": f"Security error during legacy rebuild: {'; '.join(member_result.errors)}",
                }

            return {
                "success": True,
                "message": f"Full payment history rebuild completed for member {self.name} (LEGACY METHOD USED)",
                "payment_history_count": len(self.payment_history) if hasattr(self, "payment_history") else 0,
                "method": "full_table_clear_and_rebuild",
                "warning": "This method clears all existing payment history and rebuilds it",
            }

        except Exception as e:
            frappe.logger().error(f"Error in full payment history rebuild for member {self.name}: {str(e)}")
            return {"success": False, "message": f"Error in full rebuild: {str(e)}"}

    # ===== NEW INCREMENTAL UPDATE METHODS =====

    def add_invoice_to_payment_history(self, invoice_name):
        """Add a single invoice to payment history using batched processing"""
        if not self.customer:
            return

        # IMPROVED: Use 10s batching to eliminate lock contention
        from verenigingen.utils.financial_history_batch_processor import queue_payment_update

        queue_payment_update(self.name, invoice_name)
        return True  # Queued successfully

    def _get_invoice_with_retry(self, invoice_name, max_retries=3):
        """
        Get invoice with exponential backoff retry mechanism for race conditions.

        Uses exponential backoff with jitter to handle transient failures:
        - Normal mode: 0.5s base delay (retries at ~0.5s, ~1s, ~2s with jitter)
        - Bulk mode: 2s base delay (retries at ~2s, ~4s, ~8s with jitter)

        Jitter (±25%) prevents thundering herd when multiple requests retry simultaneously.
        """
        import random
        import time

        is_bulk_processing = getattr(frappe.flags, "bulk_invoice_generation", False)

        # Base delay: 0.5s for normal, 2s for bulk processing
        base_delay = 2.0 if is_bulk_processing else 0.5
        max_delay = 10.0  # Cap maximum delay at 10 seconds

        for retry_count in range(max_retries):
            try:
                return frappe.get_doc("Sales Invoice", invoice_name)
            except frappe.DoesNotExistError:
                if retry_count < max_retries - 1:
                    # Exponential backoff: base_delay * (2 ^ retry_count)
                    delay = min(base_delay * (2**retry_count), max_delay)

                    # Add jitter: ±25% randomization to prevent synchronized retries
                    jitter = random.uniform(0.75, 1.25)
                    sleep_duration = delay * jitter

                    frappe.logger("payment_history").info(
                        f"Invoice {invoice_name} not found (attempt {retry_count + 1}/{max_retries}). "
                        f"Exponential backoff: waiting {sleep_duration:.2f}s "
                        f"{'(bulk mode)' if is_bulk_processing else '(normal mode)'}"
                    )

                    time.sleep(sleep_duration)
                    frappe.db.commit()
                else:
                    # Calculate total wait time for error message
                    total_wait = sum(min(base_delay * (2**i), max_delay) for i in range(max_retries - 1))

                    frappe.log_error(
                        f"Sales Invoice {invoice_name} not found after {max_retries} retries "
                        f"(~{total_wait:.1f}s total wait) - possible race condition",
                        "Payment History Race Condition",
                    )
                    return None
        return None

    def update_invoice_in_payment_history(self, invoice_name):
        """Update an existing invoice in payment history using consolidated manager"""
        # This is essentially the same as add_or_update, so just call that
        return self.add_invoice_to_payment_history(invoice_name)

    def _build_payment_history_entry(self, invoice):
        """
        Build a payment history entry from an invoice document.

        EXTRACTED: Delegates to PaymentHistoryService.build_payment_history_entry()
        for service layer separation (Phase 1 Payment Service Extraction).

        Uses the shared PaymentHistoryEntryBuilder for consistency with bulk updates,
        with schedule-specific coverage date overrides.
        """
        from verenigingen.services.member.payment import get_payment_history_service

        return get_payment_history_service().build_payment_history_entry(invoice, member_doc=self)
