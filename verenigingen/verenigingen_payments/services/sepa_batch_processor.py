"""
SEPA Direct Debit Batch Processor Service

Handles SEPA batch creation, invoice processing, return handling,
and payment failure management for membership dues collection.

Extracted from direct_debit_batch/sepa_processor.py for better
separation of concerns and testability.
"""

from datetime import datetime

import frappe
from frappe import _
from frappe.utils import add_days, cstr, flt, getdate, today

from verenigingen.services.communication.email_service import get_email_service
from verenigingen.utils.settings_utils import get_payments_settings
from verenigingen.verenigingen_payments.utils.batch_performance_optimizer import (
    get_batch_performance_optimizer,
)
from verenigingen.verenigingen_payments.utils.sepa_config_manager import get_sepa_config_manager
from verenigingen.verenigingen_payments.utils.sepa_error_handler import get_sepa_error_handler
from verenigingen.verenigingen_payments.utils.sepa_mandate_service import get_sepa_mandate_service


class SEPABatchProcessor:
    """
    SEPA batch processor that handles membership dues schedules.

    Responsibilities:
    - Create direct debit batches from unpaid invoices
    - Process SEPA return files (pain.002)
    - Handle failed payments and grace periods
    - Verify invoice coverage for collection dates
    - Manage mandate sequence types (FRST, RCUR, etc.)
    """

    def __init__(self):
        self.config_manager = get_sepa_config_manager()
        self.mandate_service = get_sepa_mandate_service()
        self.error_handler = get_sepa_error_handler()
        self.performance_optimizer = get_batch_performance_optimizer()

        # Get company from centralized config
        # Note: Permission validation happens at API entry points via @critical_api decorator
        # Services trust the caller has already been authorized
        company_config = self.config_manager.get_company_sepa_config()
        company_name = company_config.get("company")
        self.company = frappe.get_doc("Company", company_name) if company_name else None

    # =========================================================================
    # Batch Creation
    # =========================================================================

    def create_dues_collection_batch(self, collection_date=None, verify_invoicing=True):
        """
        Create a direct debit batch for membership dues collection.
        Processes existing unpaid invoices and verifies complete invoicing coverage.

        Args:
            collection_date: Date for batch processing (default: today)
            verify_invoicing: Whether to run invoice coverage verification
        """
        if not collection_date:
            collection_date = today()

        # Step 1: Verify invoice coverage if requested
        if verify_invoicing:
            verification_result = self.verify_invoice_coverage(collection_date)
            if not verification_result["complete"]:
                frappe.log_error(
                    title="SEPA Batch - Invoice Coverage Issues",
                    message=f"Invoice coverage verification failed: {verification_result['issues']}",
                )
                # Continue with batch creation but log the issues

        # Step 2: Get existing unpaid invoices instead of creating new ones
        eligible_invoices = self.get_existing_unpaid_sepa_invoices(collection_date)

        if not eligible_invoices:
            frappe.logger().info(f"No unpaid SEPA invoices found for collection on {collection_date}")
            return None

        # Step 3: Create batch from existing invoices
        batch = self.create_batch_from_invoices(eligible_invoices, collection_date)

        # Batch process sequence types for all invoices at once
        self.add_invoices_to_batch_optimized(batch, eligible_invoices)

        if batch.invoices:
            batch.calculate_totals()
            batch.save()

            # Handle validation and notifications for automated processing
            self.handle_automated_batch_validation(batch)

            frappe.db.commit()

            frappe.logger().info(
                f"Created SEPA batch {batch.name} with {len(batch.invoices)} invoices for €{batch.total_amount}"
            )
            return batch
        else:
            # No valid invoices, delete empty batch
            batch.delete()
            return None

    def create_batch_from_invoices(self, invoices, collection_date):
        """Create SEPA batch from existing invoices"""
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = collection_date
        # collection_date is often a string (today() / callers pass strings), so
        # normalise before strftime — a raw str has no .strftime and crashes batch creation.
        batch.batch_description = f"Monthly SEPA collection - {getdate(collection_date).strftime('%B %Y')}"
        batch.batch_type = "CORE"  # SEPA scheme
        batch.sequence_type = "RCUR"  # Default to recurring
        batch.currency = "EUR"
        batch.status = "Draft"

        # Set flag for automated processing
        batch._automated_processing = True

        return batch

    def create_batch_document(self, schedules, collection_date):
        """Create the SEPA Direct Debit Batch document"""
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = collection_date
        batch.batch_description = f"Membership dues collection - {collection_date}"
        batch.batch_type = "CORE"  # SEPA scheme
        batch.sequence_type = "RCUR"  # Default to recurring
        batch.currency = "EUR"
        batch.status = "Draft"

        # Set flag for automated processing (affects validation behavior)
        batch._automated_processing = True

        return batch

    # =========================================================================
    # Invoice Processing
    # =========================================================================

    def get_existing_unpaid_sepa_invoices(self, collection_date):
        """Get existing unpaid invoices for SEPA Direct Debit members using optimized service"""
        # Get lookback days from centralized config
        processing_config = self.config_manager.get_processing_config()
        lookback_days = processing_config["lookback_days"]

        invoices = self.mandate_service.get_sepa_invoices_with_mandates(
            collection_date, lookback_days=lookback_days
        )

        frappe.logger().info(f"Found {len(invoices)} existing unpaid SEPA invoices")
        return invoices

    def add_invoices_to_batch_optimized(self, batch, invoices):
        """Add multiple invoices to batch with performance-optimized processing"""
        if not invoices:
            return

        # Extract invoice names for bulk processing
        invoice_names = [inv.get("name") for inv in invoices if inv.get("name")]

        if not invoice_names:
            return

        # Use performance optimizer to process batch invoices efficiently
        try:
            processed_invoices = self.performance_optimizer.process_batch_invoices_optimized(invoice_names)

            # Prepare mandate-invoice pairs for batch sequence type lookup
            mandate_invoice_pairs = []
            for processed in processed_invoices:
                mandate_data = processed.get("mandate_data")
                if mandate_data and mandate_data.get("name"):
                    mandate_invoice_pairs.append((mandate_data["name"], processed["invoice_name"]))

            # Batch get sequence types
            sequence_types = self.mandate_service.get_sequence_types_batch(mandate_invoice_pairs)

            # Add invoices to batch with optimized data
            # #774: cap this defensive branch's detail writes the same way
            # process_batch_invoices_optimized caps its own (see the comment
            # there) -- unreachable today, but a future change to that
            # invariant must not turn into unbounded Error Log rows either.
            MAX_DETAIL_LOGS = 10
            incomplete_names = []
            successful_count = 0
            for processed in processed_invoices:
                mandate_data = processed.get("mandate_data")
                invoice_data = processed.get("invoice_data")
                member_data = processed.get("member_data")

                if not mandate_data or not invoice_data or not member_data:
                    # process_batch_invoices_optimized() only ever returns rows with
                    # all three present, so this should be unreachable -- but if that
                    # invariant is ever broken, the fallback must not be another
                    # silent frappe.logger().warning() (#774).
                    incomplete_names.append(processed.get("invoice_name"))
                    if len(incomplete_names) <= MAX_DETAIL_LOGS:
                        frappe.log_error(
                            title="SEPA Batch - Unexpected Incomplete Processed Invoice",
                            message=(
                                f"add_invoices_to_batch_optimized: skipped invoice "
                                f"{processed.get('invoice_name')} for batch {batch.name} - incomplete data "
                                f"(mandate_data={'present' if mandate_data else 'MISSING'}, "
                                f"invoice_data={'present' if invoice_data else 'MISSING'}, "
                                f"member_data={'present' if member_data else 'MISSING'})."
                            ),
                        )
                    continue

                # Get sequence type from batch lookup
                cache_key = f"{mandate_data['name']}:{processed['invoice_name']}"
                sequence_type = sequence_types.get(cache_key, "RCUR")

                try:
                    # Use optimized invoice addition with pre-fetched data
                    self.add_processed_invoice_to_batch(batch, processed, sequence_type)
                    successful_count += 1
                except Exception:
                    frappe.log_error(
                        title="SEPA Batch Processor - Batch Addition Error",
                        message=(
                            f"{frappe.get_traceback()}\n\n"
                            f"Context:\n"
                            f"User: {frappe.session.user}\n"
                            f"Invoice: {processed.get('invoice_name')}\n"
                            f"Batch: {batch.name}\n"
                            f"Member: {processed.get('member_data', {}).get('name', 'N/A')}"
                        ),
                    )
                    continue

            frappe.logger().info(
                f"Performance-optimized batch addition: {successful_count}/{len(invoice_names)} invoices processed"
            )

            # #774: the line above is the only place this count ever existed, and
            # frappe.logger().info() never reaches anywhere an operator or CI can
            # see -- a bare logger's effective level is ERROR. A batch that
            # collects fewer invoices than requested must leave a durable, visible
            # record of that fact, not just look identical to a fully successful
            # run. Record it twice: on the batch document itself (found by anyone
            # who opens this specific batch) and in the Error Log (found by anyone
            # scanning for anomalies without knowing which batch to look at).
            if successful_count < len(invoice_names):
                from verenigingen.verenigingen_payments.utils.sepa_utilities import BatchLoggingUtilities

                shortfall = len(invoice_names) - successful_count
                message = (
                    f"Batch {batch.name}: requested {len(invoice_names)} invoices, "
                    f"added {successful_count} ({shortfall} not collected this run). "
                    f"See individual 'SEPA Batch - Invoice Not Found', 'SEPA Batch - Invoice "
                    f"Skipped (Missing Member/Mandate Data)' and 'SEPA Batch Processor - Batch "
                    f"Addition Error' Error Log entries around this time for the per-invoice reasons."
                )
                BatchLoggingUtilities.add_to_document_batch_log(batch, message)
                frappe.log_error(title="SEPA Batch - Invoice Shortfall", message=message)

                # #774 review round 3: a blob in batch_log/Error Log is findable
                # but not QUERYABLE -- nothing programmatic (the scheduler entry
                # point, a report, a dashboard) reads either. This is a NEW,
                # distinct status ("Partially Collected"), not the existing
                # "Partially Failed" (process_batch_returns, ~line 575, for
                # bounced payments POST-submission, asserted by
                # test_sepa_batch_processor_returns_coverage.py:131) -- that
                # string already means something different (the bank rejected a
                # payment after the batch was submitted) and there is also a
                # third, distinct "Partially Processed"
                # (_update_batch_status_after_processing). Reusing "Partially
                # Failed" here would give an operator no way to tell "the
                # collection undershot" from "the bank bounced a payment" without
                # opening the batch and reading batch_log. Verified before adding
                # the option: no Workflow is attached to Direct Debit Batch
                # (grepped every workflow fixture in the app); the status
                # Select's options list is not enumerated anywhere that would
                # need updating (the form's status_colors map and the "SEPA
                # Payment Status" dashboard chart's group-by are both
                # value-agnostic, falling back to 'gray'/an extra donut slice for
                # any unrecognised string -- the same as "Partially Failed"
                # already does in status_colors today).
                #
                # Also verified this does not block anything downstream:
                # on_submit() only checks sepa_file_generated, and no production
                # code gates validation, submission, or XML generation on
                # status == "Draft".
                #
                # Grepped every "Draft"/"Generated" reader that treats those as
                # "still needs attention" and updated each so a shortfall batch
                # does not silently drop out of view (the actual #774 review-2
                # regression): sepa_monitoring_dashboard.get_system_alerts's
                # stuck-batch check, sepa_zabbix_enhanced's
                # sepa.batch.stuck_count metric (feeds a live Zabbix trigger
                # prototype), dd_batch_workflow_controller.
                # get_batches_pending_approval, and the two same-shape
                # same-date-conflict warnings in sepa_race_condition_manager and
                # sepa_conflict_detector. NOT changed:
                # authorization.py::_check_batch_permissions's
                # status in ["Draft", "Validated"] gate -- that is an ACCESS
                # decision (can a PROCESS-level non-owner/non-admin user act on
                # this batch via a decorated API), not a visibility one; every
                # non-Draft/Validated status already excludes it today
                # (including the pre-existing "Partially Failed" and "Partially
                # Processed"), so this is existing, narrower behaviour rather
                # than something this change newly breaks, and tightening who
                # may act on a just-flagged batch is arguably the safer default
                # rather than a regression.
                #
                # One caveat this does NOT fix, disclosed rather than glossed
                # over: this status survives only until the batch is
                # SUBMITTED. on_submit() unconditionally calls
                # generate_sepa_xml() whenever sepa_file_generated is falsy, and
                # generate_sepa_xml_for_batch() does
                # db_set("status", "Generated") with no read of the prior value
                # -- so EVERY submitted batch loses this status, not only
                # auto-submitted ones; auto-submit just shrinks the observation
                # window to milliseconds inside one job. The Error Log entry
                # above is unaffected by that and remains the durable signal
                # regardless of submission.
                #
                # DEPLOYMENT REQUIREMENT: "Partially Collected" is a NEW Select
                # option added to direct_debit_batch.json. Frappe validates
                # Select values against the DocField's CACHED options on save
                # (`_validate_selects`, base_document.py) -- a JSON edit alone
                # does not refresh that cache. Measured on test_site_5: before
                # `bench reload-doctype "Direct Debit Batch"`,
                # `frappe.get_meta(...).get_field("status").options` still read
                # the pre-#774 list with no "Partially Collected"; the SAME
                # site, same code, only differing by that one command, then
                # let a real `batch.insert()` with this status succeed. Any
                # site this ships to needs `bench migrate` (which reloads every
                # changed doctype) or `bench reload-doctype "Direct Debit
                # Batch"` run BEFORE the next scheduled
                # create_dues_collection_batch call, or the very first
                # shortfall batch will raise a ValidationError out of
                # batch.save() instead of merely being under-collected --
                # turning this fix into a harder failure on an unmigrated site.
                batch.status = "Partially Collected"

            # Log performance statistics
            stats = self.performance_optimizer.get_performance_stats()
            frappe.logger().info(
                f"Performance stats - Cache hit rate: {stats['cache_stats']['hit_rate']:.2%}, "
                f"Time saved: {stats['optimization_efficiency']['total_time_saved_seconds']:.1f}s"
            )

        except Exception as e:
            frappe.log_error(
                title="SEPA Performance Optimizer Error",
                message=f"Performance optimizer failed, falling back to standard processing: {str(e)}",
            )
            # Fallback to original logic
            self._add_invoices_to_batch_fallback(batch, invoices)

    def add_processed_invoice_to_batch(self, batch, processed_invoice, sequence_type):
        """Add invoice to batch using pre-processed optimized data.

        Ensures atomicity: if usage record creation fails, the invoice row
        is removed from the batch to prevent orphaned records.
        """
        invoice_data = processed_invoice["invoice_data"]
        member_data = processed_invoice["member_data"]
        mandate_data = processed_invoice["mandate_data"]

        # Track batch invoices count before append for rollback
        invoices_before = len(batch.invoices)

        batch.append(
            "invoices",
            {
                "invoice": invoice_data["name"],
                "membership": (
                    invoice_data.get("membership", {}).get("name") if invoice_data.get("membership") else None
                ),
                "member": member_data["name"],
                "member_name": member_data["full_name"],
                "amount": invoice_data["grand_total"],
                "currency": invoice_data["currency"],
                "iban": mandate_data["iban"],
                "mandate_reference": mandate_data["mandate_id"],
                "mandate_sign_date": mandate_data.get("sign_date"),
                "status": "Pending",
                "sequence_type": sequence_type,
            },
        )

        # Create mandate usage record for tracking
        # If this fails, remove the invoice row to maintain consistency
        try:
            self._create_mandate_usage_record(
                mandate_data["name"],
                invoice_data["name"],
                invoice_data["grand_total"],
                sequence_type,
            )
        except Exception as e:
            # Compensate: remove the appended invoice row
            if len(batch.invoices) > invoices_before:
                batch.invoices.pop()
            frappe.log_error(
                title="SEPA Batch - Invoice Addition Rolled Back",
                message=(
                    f"Usage record creation failed, invoice removed from batch.\n"
                    f"Invoice: {invoice_data['name']}\n"
                    f"Mandate: {mandate_data['name']}\n"
                    f"Error: {str(e)}"
                ),
            )
            raise

    def add_invoice_to_batch(self, batch, invoice, schedule):
        """Add invoice to SEPA batch with proper sequence type determination"""
        # Get SEPA mandate details
        mandate = self.get_active_mandate(schedule)
        if not mandate:
            frappe.log_error(
                title="SEPA Mandate Missing",
                message=f"No active SEPA mandate found for schedule {schedule.name}",
            )
            return

        # Get member details
        member = frappe.get_doc("Member", schedule.member)

        # Determine correct sequence type using mandate history
        from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage import (
            get_mandate_sequence_type,
        )

        sequence_info = get_mandate_sequence_type(mandate.name, invoice.name)
        correct_sequence_type = sequence_info["sequence_type"]

        batch.append(
            "invoices",
            {
                "invoice": invoice.name,
                "membership": schedule.membership,
                "member": schedule.member,
                "member_name": member.full_name,
                "amount": invoice.grand_total,
                "currency": invoice.currency,
                "bank_account": mandate.name,
                "iban": mandate.iban,
                "mandate_reference": mandate.mandate_id,
                "mandate_sign_date": mandate.sign_date,
                "status": "Pending",
                "sequence_type": correct_sequence_type,
            },
        )

        # Create mandate usage record for tracking
        self._create_mandate_usage_record(
            mandate.name,
            invoice.name,
            invoice.grand_total,
            correct_sequence_type,
        )

    def add_invoice_to_batch_with_sequence(self, batch, invoice_data, sequence_type):
        """Add single invoice to batch with pre-determined sequence type"""
        batch.append(
            "invoices",
            {
                "invoice": invoice_data["name"],
                "membership": invoice_data["membership"],
                "member": invoice_data["member"],
                "member_name": invoice_data["member_name"],
                "amount": invoice_data["amount"],
                "currency": invoice_data["currency"],
                "iban": invoice_data["iban"],
                "mandate_reference": invoice_data["mandate_reference"],
                "mandate_sign_date": invoice_data.get("mandate_sign_date"),
                "status": "Pending",
                "sequence_type": sequence_type,
            },
        )

        # Create mandate usage record for tracking
        self._create_mandate_usage_record(
            invoice_data["mandate_name"],
            invoice_data["name"],
            invoice_data["amount"],
            sequence_type,
        )

    def add_existing_invoice_to_batch(self, batch, invoice_data):
        """Add existing invoice to SEPA batch with proper sequence type determination"""
        from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage import (
            get_mandate_sequence_type,
        )

        mandate_name = invoice_data["mandate_name"]
        if not mandate_name:
            frappe.log_error(
                title="SEPA Batch - Missing Mandate",
                message=f"No active SEPA mandate found for invoice {invoice_data['name']}",
            )
            return

        sequence_info = get_mandate_sequence_type(mandate_name, invoice_data["name"])
        correct_sequence_type = sequence_info["sequence_type"]

        batch.append(
            "invoices",
            {
                "invoice": invoice_data["name"],
                "membership": invoice_data["membership"],
                "member": invoice_data["member"],
                "member_name": invoice_data["member_name"],
                "amount": invoice_data["amount"],
                "currency": invoice_data["currency"],
                "iban": invoice_data["iban"],
                "mandate_reference": invoice_data["mandate_reference"],
                "mandate_sign_date": invoice_data.get("mandate_sign_date"),
                "status": "Pending",
                "sequence_type": correct_sequence_type,
            },
        )

        # Create mandate usage record for tracking
        self._create_mandate_usage_record(
            mandate_name,
            invoice_data["name"],
            invoice_data["amount"],
            correct_sequence_type,
        )

    def _add_invoices_to_batch_fallback(self, batch, invoices):
        """Fallback method using original logic when performance optimizer fails"""
        # Prepare mandate-invoice pairs for batch sequence type lookup
        mandate_invoice_pairs = []
        invoice_lookup = {}

        for invoice_data in invoices:
            mandate_name = invoice_data.get("mandate_name")
            invoice_name = invoice_data.get("name")

            if mandate_name and invoice_name:
                mandate_invoice_pairs.append((mandate_name, invoice_name))
                invoice_lookup[f"{mandate_name}:{invoice_name}"] = invoice_data

        # Batch get sequence types
        sequence_types = self.mandate_service.get_sequence_types_batch(mandate_invoice_pairs)

        # Add invoices to batch with pre-determined sequence types
        successful_count = 0
        for pair in mandate_invoice_pairs:
            mandate_name, invoice_name = pair
            cache_key = f"{mandate_name}:{invoice_name}"
            invoice_data = invoice_lookup[cache_key]
            sequence_type = sequence_types.get(cache_key, "RCUR")  # Default to RCUR

            try:
                self.add_invoice_to_batch_with_sequence(batch, invoice_data, sequence_type)
                successful_count += 1
            except Exception as e:
                frappe.log_error(
                    title="SEPA Batch Processor - Batch Addition Error",
                    message=f"Error adding invoice {invoice_name} to batch: {str(e)}",
                )
                continue

        frappe.logger().info(
            f"Fallback processing: {successful_count}/{len(invoices)} invoices added to batch"
        )

    def _create_mandate_usage_record(self, mandate_name, invoice_name, amount, sequence_type):
        """Create mandate usage record for tracking.

        Raises exception on failure to allow caller to handle compensation.
        """
        try:
            from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage import (
                create_mandate_usage_record,
            )

            create_mandate_usage_record(
                mandate_name=mandate_name,
                reference_doctype="Sales Invoice",
                reference_name=invoice_name,
                amount=amount,
                sequence_type=sequence_type,
            )
        except Exception:
            frappe.log_error(
                title="SEPA Batch Processor - Mandate Usage Creation Error",
                message=(
                    f"{frappe.get_traceback()}\n\n"
                    f"Context:\n"
                    f"User: {frappe.session.user}\n"
                    f"Mandate: {mandate_name}\n"
                    f"Invoice: {invoice_name}\n"
                    f"Amount: {amount}\n"
                    f"Sequence Type: {sequence_type}"
                ),
            )
            # Re-raise to allow caller to handle compensation
            raise

    # =========================================================================
    # Return Processing (Bank Response Handling)
    # =========================================================================

    def process_batch_returns(self, batch_name, return_file_path):
        """Process SEPA return file and handle failed payments"""
        try:
            batch = frappe.get_doc("Direct Debit Batch", batch_name)

            # Parse return file
            returns = self.parse_sepa_return_file(return_file_path)

            failed_count = 0
            for return_item in returns:
                # Find the invoice in the batch
                invoice_item = self.find_invoice_in_batch(batch, return_item)
                if invoice_item:
                    # Update invoice status
                    invoice_item.status = "Failed"
                    invoice_item.result_code = return_item.get("reason_code")
                    invoice_item.result_message = return_item.get("reason_description")

                    # Handle the failed payment
                    self.handle_failed_payment(invoice_item, return_item)
                    failed_count += 1

            # Update batch status
            if failed_count > 0:
                batch.status = "Partially Failed"
                batch.add_to_batch_log(f"Processed {failed_count} returned payments")

            batch.save()
            return failed_count

        except Exception:
            frappe.log_error(
                title="SEPA Return Processing Error",
                message=(
                    f"{frappe.get_traceback()}\n\n"
                    f"Context:\n"
                    f"User: {frappe.session.user}\n"
                    f"Batch: {batch_name}\n"
                    f"Return File: {return_file_path}"
                ),
            )
            raise

    def parse_sepa_return_file(self, file_path):
        """Parse a SEPA pain.002 return file and return the REJECTED collections.

        Delegates to the canonical pain.002 parser
        (``verenigingen_payments.utils.sepa_return_parser.get_rejected_transactions``)
        — the same parser the reconciliation API uses — so both paths share one
        source of truth for the ISO 20022 semantics (namespace versions, status
        codes, reason-code descriptions). Returns a list of
        ``{end_to_end_id, reason_code, reason_description, ...}`` dicts (one per
        RJCT transaction) consumed by ``process_batch_returns``. A malformed or
        unreadable file logs and returns ``[]``.
        """
        try:
            from verenigingen.verenigingen_payments.utils.sepa_return_parser import (
                get_rejected_transactions,
            )

            with open(file_path, encoding="utf-8") as f:
                xml_content = f.read()

            return get_rejected_transactions(xml_content)

        except Exception:
            frappe.log_error(
                title="SEPA Return File Parser Error",
                message=(
                    f"{frappe.get_traceback()}\n\n"
                    f"Context:\n"
                    f"User: {frappe.session.user}\n"
                    f"File Path: {file_path}"
                ),
            )
            return []

    def find_invoice_in_batch(self, batch, return_item):
        """Find the batch invoice row a return refers to.

        The pain.008 EndToEndId is ``INV-<invoice>`` (or the invoice name itself
        when it already starts with ``INV``), so match the pain.002 OrgnlEndToEndId
        against both the bare invoice name and the INV-prefixed form.
        """
        end_to_end_id = return_item.get("end_to_end_id")
        if not end_to_end_id:
            return None
        for invoice_item in batch.invoices:
            invoice = invoice_item.invoice
            if end_to_end_id in (invoice, f"INV-{invoice}"):
                return invoice_item
        return None

    def handle_failed_payment(self, invoice_item, return_info):
        """
        Handle a failed SEPA payment with transaction safety.

        The schedule update and notification are handled separately to ensure:
        1. Schedule state change is atomic (savepoint protection)
        2. Notification failure doesn't affect schedule update
        3. Both operations are logged for audit trail
        """
        schedule = None
        schedule_updated = False

        try:
            # Get the dues schedule
            invoice = frappe.get_doc("Sales Invoice", invoice_item.invoice)
            if not invoice.membership_dues_schedule_display:
                return

            schedule = frappe.get_doc("Membership Dues Schedule", invoice.membership_dues_schedule_display)

            # Use savepoint for atomic schedule update
            frappe.db.savepoint("handle_failed_payment")

            try:
                # Increment failure count
                schedule.consecutive_failures = (schedule.consecutive_failures or 0) + 1

                # Update schedule status based on failure count
                # Get grace period settings from Verenigingen Settings
                settings = frappe.get_single("Verenigingen Settings")
                grace_period_days = settings.default_grace_period_days or 30
                auto_apply_grace_period = settings.grace_period_auto_apply

                if schedule.consecutive_failures >= 3:
                    # Only auto-suspend if grace period auto-apply is enabled
                    if auto_apply_grace_period:
                        schedule.status = "Suspended"
                        schedule.add_comment(
                            text=f"Suspended due to {schedule.consecutive_failures} consecutive payment failures"
                        )
                    else:
                        # Keep in grace period indefinitely if auto-suspend is disabled
                        schedule.status = "Grace Period"
                        schedule.grace_period_until = add_days(today(), grace_period_days)
                        schedule.add_comment(
                            text=f"Payment failure #{schedule.consecutive_failures} - Grace period extended (auto-suspension disabled)"
                        )
                else:
                    schedule.status = "Grace Period"
                    schedule.grace_period_until = add_days(today(), grace_period_days)

                schedule.save()
                frappe.db.release_savepoint("handle_failed_payment")
                schedule_updated = True

            except Exception:
                # Rollback schedule changes on any error
                frappe.db.rollback_savepoint("handle_failed_payment")
                raise

        except Exception:
            frappe.log_error(
                title="Failed Payment Handler Error",
                message=(
                    f"{frappe.get_traceback()}\n\n"
                    f"Context:\n"
                    f"User: {frappe.session.user}\n"
                    f"Invoice: {invoice_item.invoice}\n"
                    f"Return Reason: {return_info.get('reason_code', 'N/A')}\n"
                    f"Return Description: {return_info.get('reason_description', 'N/A')}"
                ),
            )
            return

        # Notification is separate from schedule update - failure here won't affect schedule
        if schedule_updated and schedule:
            try:
                self.notify_payment_failure(schedule, return_info)
            except Exception:
                # Log notification failure but don't fail the overall operation
                frappe.log_error(
                    title="Failed Payment Notification Error (Non-Critical)",
                    message=(
                        f"{frappe.get_traceback()}\n\n"
                        f"Context:\n"
                        f"User: {frappe.session.user}\n"
                        f"Schedule: {schedule.name}\n"
                        f"Note: Schedule was updated successfully, only notification failed"
                    ),
                )

    def notify_payment_failure(self, schedule, return_info):
        """Send notification about payment failure"""
        try:
            member = frappe.get_doc("Member", schedule.member)

            reason = return_info.get("reason_description", "Payment was rejected by the bank")

            subject = _("Payment Failed - Action Required")
            message = f"""
            Dear {member.full_name},

            Your membership payment of €{schedule.dues_rate} has failed with the following reason:
            {reason}

            Please update your payment information or contact us to resolve this issue.
            You have a grace period until {schedule.grace_period_until} to resolve this.

            If you have any questions, please contact our membership team.

            Best regards,
            Organization
            """

            email_service = get_email_service()
            email_service.send_simple_email(
                recipients=[member.email],
                subject=subject,
                message=message,
                reference_doctype="Membership Dues Schedule",
                reference_name=schedule.name,
                notification_key="payment_failure_final",
            )

        except Exception:
            frappe.log_error(
                title="Payment Failure Notification Error",
                message=(
                    f"{frappe.get_traceback()}\n\n"
                    f"Context:\n"
                    f"User: {frappe.session.user}\n"
                    f"Schedule: {schedule.name}\n"
                    f"Member: {schedule.member}\n"
                    f"Return Reason: {return_info.get('reason_code', 'N/A')}"
                ),
            )

    # =========================================================================
    # Invoice Coverage Verification
    # =========================================================================

    def verify_invoice_coverage(self, collection_date):
        """
        Verify that all eligible members have been properly invoiced.
        Optimized with batch processing for better performance.
        """
        issues = []
        total_checked = 0

        try:
            # Batch query to get all schedules with their invoice status
            coverage_data = frappe.db.sql(
                """
                SELECT
                    mds.name as schedule_name,
                    mds.member,
                    mds.billing_frequency,
                    mds.next_invoice_date,
                    mds.last_invoice_coverage_start,
                    mds.last_invoice_coverage_end,
                    mds.payment_terms_template,
                    COUNT(si.name) as invoice_count
                FROM `tabMembership Dues Schedule` mds
                LEFT JOIN `tabSales Invoice` si ON (
                    si.membership_dues_schedule_display = mds.name
                    AND si.custom_coverage_start_date = mds.last_invoice_coverage_start
                    AND si.custom_coverage_end_date = mds.last_invoice_coverage_end
                    AND si.docstatus != 2
                )
                WHERE
                    mds.status = 'Active'
                    AND mds.auto_generate = 1
                    AND mds.test_mode = 0
                GROUP BY mds.name
                LIMIT 500  -- Pagination for large datasets
            """,
                as_dict=True,
            )

            # Batch validate coverage periods
            schedule_data = [
                {
                    "name": row["schedule_name"],
                    "member": row["member"],
                    "billing_frequency": row["billing_frequency"],
                    "last_invoice_coverage_start": row["last_invoice_coverage_start"],
                    "last_invoice_coverage_end": row["last_invoice_coverage_end"],
                    "payment_terms_template": row["payment_terms_template"],
                }
                for row in coverage_data
            ]

            coverage_issues = self.validate_coverage_periods_batch(schedule_data, collection_date)

            for row in coverage_data:
                total_checked += 1
                schedule_name = row["schedule_name"]

                # Check for coverage period issues
                if schedule_name in coverage_issues:
                    issues.append(
                        {
                            "schedule": schedule_name,
                            "member": row["member"],
                            "issue": coverage_issues[schedule_name],
                            "billing_frequency": row["billing_frequency"],
                        }
                    )

                # Check if invoice exists for SEPA schedules
                if row["payment_terms_template"] == "SEPA Direct Debit" and row["invoice_count"] == 0:
                    issues.append(
                        {
                            "schedule": schedule_name,
                            "member": row["member"],
                            "issue": "Missing invoice for current coverage period",
                            "billing_frequency": row["billing_frequency"],
                        }
                    )

            frappe.logger().info(
                f"Invoice coverage verification: {total_checked} schedules checked, "
                f"{len(issues)} issues found"
            )

            return {
                "complete": len(issues) == 0,
                "total_checked": total_checked,
                "issues_count": len(issues),
                "issues": issues,
            }

        except Exception as e:
            frappe.log_error(
                title="Invoice Coverage Verification Error",
                message=f"Error in invoice coverage verification: {str(e)}",
            )
            return {"complete": False, "error": str(e), "total_checked": total_checked, "issues": issues}

    def validate_coverage_period(self, schedule, collection_date):
        """Validate coverage period against billing frequency (rolling periods)"""
        if not schedule["last_invoice_coverage_start"] or not schedule["last_invoice_coverage_end"]:
            return "Missing coverage period dates"

        start_date = getdate(schedule["last_invoice_coverage_start"])
        end_date = getdate(schedule["last_invoice_coverage_end"])
        billing_freq = schedule["billing_frequency"]

        # Calculate expected period length
        period_days = (end_date - start_date).days + 1  # +1 to include end date

        if billing_freq == "Daily":
            expected_days = 1
            tolerance = 0
        elif billing_freq == "Weekly":
            expected_days = 7
            tolerance = 1
        elif billing_freq == "Monthly":
            # Rolling months: 28-31 days
            expected_days = 30  # Average
            tolerance = 3
        elif billing_freq == "Quarterly":
            # Rolling quarters: ~90 days
            expected_days = 90
            tolerance = 7
        elif billing_freq == "Annual":
            # Rolling years: 365/366 days
            expected_days = 365
            tolerance = 2
        else:
            # Custom billing frequency
            return None  # Skip validation for custom frequencies

        if abs(period_days - expected_days) > tolerance:
            return (
                f"Coverage period ({period_days} days) doesn't match "
                f"{billing_freq} billing frequency (expected ~{expected_days} days)"
            )

        return None

    def validate_coverage_periods_batch(self, schedules, collection_date):
        """Batch validate coverage periods for multiple schedules"""
        issues = {}

        for schedule in schedules:
            issue = self.validate_coverage_period(schedule, collection_date)
            if issue:
                issues[schedule["name"]] = issue

        return issues

    # =========================================================================
    # Dues Schedule Helpers
    # =========================================================================

    def get_eligible_dues_schedules(self, collection_date):
        """Get membership dues schedules eligible for collection"""
        # Calculate the date range for eligible schedules
        # We want to collect dues that are due within the invoice_days_before period
        max_due_date = add_days(collection_date, 30)  # Default 30 days lookahead

        filters = {
            "status": "Active",
            "auto_generate": 1,
            "test_mode": 0,
            "payment_terms_template": "SEPA Direct Debit",
            "next_invoice_date": ["<=", max_due_date],
        }

        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters=filters,
            fields=[
                "name",
                "member",
                "membership",
                "membership_type",
                "dues_rate",
                "billing_frequency",
                "next_invoice_date",
                "invoice_days_before",
                "contribution_mode",
                "billing_day",
            ],
        )

        # Filter based on invoice_days_before
        eligible = []
        for schedule in schedules:
            days_before = schedule.invoice_days_before or 30
            generate_date = add_days(schedule.next_invoice_date, -days_before)

            if getdate(collection_date) >= getdate(generate_date):
                # Always include eligible schedules
                schedule_doc = frappe.get_doc("Membership Dues Schedule", schedule.name)
                eligible.append(schedule_doc)

        frappe.logger().info(f"Found {len(eligible)} eligible dues schedules for collection")
        return eligible

    def find_existing_invoice_for_schedule(self, schedule):
        """Find existing invoice for the current coverage period"""
        existing = frappe.get_all(
            "Sales Invoice",
            filters={
                "customer": schedule.member,
                "membership_dues_schedule_display": schedule.name,
                "custom_coverage_start_date": schedule.last_invoice_coverage_start,
                "docstatus": ["!=", 2],  # Not cancelled
                "status": ["in", ["Unpaid", "Overdue"]],  # Only unpaid invoices
            },
            fields=["name", "grand_total", "status"],
            limit=1,
        )
        return existing[0] if existing else None

    def member_has_sepa_enabled(self, schedule):
        """Check if member has SEPA Direct Debit enabled and active mandate"""
        try:
            # Check if schedule has SEPA payment method
            if getattr(schedule, "payment_terms_template", None) != "SEPA Direct Debit":
                return False

            # Check if member has active SEPA mandate
            mandate = self.get_active_mandate(schedule)
            return mandate is not None

        except Exception as e:
            frappe.log_error(f"Error checking SEPA status for schedule {schedule.name}: {str(e)}")
            return False

    def get_active_mandate(self, schedule):
        """Get the active SEPA mandate for the schedule's member.

        Membership Dues Schedule has no ``active_mandate`` field, so the mandate is
        resolved from the member. A prior version read ``schedule.active_mandate``
        directly (and cached back to it via ``db_set``); both raised AttributeError
        on every real schedule, which ``member_has_sepa_enabled`` swallowed —
        silently reporting SEPA members as NOT enabled and excluding them from
        direct-debit batches. The getattr() below still honours a cached value if
        the field is ever added, but no longer crashes when it is absent.
        """
        cached = getattr(schedule, "active_mandate", None)
        if cached:
            return frappe.get_doc("SEPA Mandate", cached)

        # Resolve the member's single Active MEMBERSHIP mandate, or refuse.
        #
        # This was `order_by="creation desc", limit=1` with no purpose filter -- the
        # literal shape #584 was filed about, on the automated collection path. A
        # member may hold an Active membership mandate AND an Active donation
        # mandate (`validate_single_active_mandate_per_purpose`), so the newer
        # donation-only mandate became the mandate this batch debited (#597).
        #
        # `unambiguous_active_mandate` returns one mandate, nothing, or a refusal,
        # and logs the candidates. Refusing here means the schedule is left out of
        # the batch rather than debited against a guess -- `member_has_sepa_enabled`
        # above reads None as "not enabled", which is the safe direction.
        from verenigingen.verenigingen_payments.utils.mandate_candidates import (
            unambiguous_active_mandate,
        )

        choice = unambiguous_active_mandate(
            schedule.member, "Ambiguous SEPA mandate for dues collection batch"
        )
        if choice:
            return frappe.get_doc("SEPA Mandate", choice.mandate["name"])

        return None

    # =========================================================================
    # Invoice Creation (for schedules without existing invoices)
    # =========================================================================

    def create_dues_invoice(self, schedule, collection_date):
        """Create invoice for membership dues"""
        try:
            # Get member details
            member = frappe.get_doc("Member", schedule.member)

            # For daily billing: Check if member has too many unpaid invoices
            if schedule.billing_frequency == "Daily":
                unpaid_count = frappe.db.count(
                    "Sales Invoice",
                    {
                        "customer": member.customer or schedule.member,
                        "status": ["in", ["Unpaid", "Overdue"]],
                        "outstanding_amount": [">", 0],
                    },
                )

                # Skip if member has more than 5 unpaid invoices (configurable)
                max_unpaid = 5  # Could be moved to settings
                if unpaid_count >= max_unpaid:
                    frappe.logger().info(
                        f"Skipping invoice creation for {member.full_name} - "
                        f"has {unpaid_count} unpaid invoices (max: {max_unpaid})"
                    )
                    return None

            # Create invoice
            invoice = frappe.new_doc("Sales Invoice")
            invoice.customer = member.customer or schedule.member
            # Set the company explicitly from the processor's configured company
            # rather than relying on an implicit global default (which is absent
            # or ambiguous when multiple companies exist, raising "Please select
            # a Company").
            if self.company:
                invoice.company = self.company.name
            invoice.posting_date = today()
            invoice.due_date = schedule.next_invoice_date

            # Set payment terms if available
            if schedule.payment_terms_template:
                invoice.payment_terms_template = schedule.payment_terms_template

            # Compute the coverage period THIS invoice covers, BEFORE generating the
            # line description (which must show this period). The schedule's
            # last_invoice_coverage_* fields describe the PREVIOUS invoice (and are
            # None for the first one). update_schedule_after_invoice persists these
            # same dates onto the schedule afterwards.
            coverage_start, coverage_end = schedule.calculate_next_coverage_period()

            # Add membership dues item
            item_code = self.get_or_create_dues_item(schedule)

            # Generate description based on contribution mode
            description = self.generate_invoice_description(schedule, coverage_start, coverage_end)

            invoice.append(
                "items",
                {
                    "item_code": item_code,
                    "item_name": f"Membership Dues - {schedule.membership_type}",
                    "description": description,
                    "qty": 1,
                    "rate": schedule.dues_rate,
                    "amount": schedule.dues_rate,
                },
            )

            # Add custom fields for tracking
            invoice.membership_dues_schedule_display = schedule.name
            invoice.custom_coverage_start_date = coverage_start
            invoice.custom_coverage_end_date = coverage_end
            invoice.custom_contribution_mode = schedule.contribution_mode

            # Add reference
            invoice.remarks = (
                f"Membership dues for {member.full_name}\n"
                f"Period: {coverage_start} to {coverage_end}\n"
                f"Schedule: {schedule.name}"
            )

            invoice.save()
            frappe.db.commit()

            # Update schedule after creating invoice
            self.update_schedule_after_invoice(schedule)

            return invoice

        except Exception:
            frappe.log_error(
                title="Dues Invoice Creation Error",
                message=(
                    f"{frappe.get_traceback()}\n\n"
                    f"Context:\n"
                    f"User: {frappe.session.user}\n"
                    f"Schedule: {schedule.name}\n"
                    f"Member: {schedule.member}\n"
                    f"Amount: {schedule.dues_rate}\n"
                    f"Billing Frequency: {schedule.billing_frequency}"
                ),
            )
            raise

    def generate_invoice_description(self, schedule, coverage_start=None, coverage_end=None):
        """Generate invoice description based on contribution mode.

        coverage_start/coverage_end describe the period THIS invoice covers; pass
        them in from create_dues_invoice. When omitted, the period is computed
        from the schedule (the upcoming period this invoice would cover) rather
        than read from last_invoice_coverage_* — those fields hold the PREVIOUS
        invoice's period and would mislabel the line item (Wave E flag A).
        """
        base_desc = f"Membership dues - {schedule.billing_frequency}"

        # The Membership Dues Schedule field is `default_multiplier`; there is no
        # `base_multiplier` column (referencing it raised AttributeError and broke
        # invoice description generation). See report: base_multiplier is still
        # referenced in several other modules and should be reconciled.
        multiplier = getattr(schedule, "default_multiplier", None)
        if schedule.contribution_mode == "Income-Based" and multiplier:
            percentage = int(multiplier * 100)
            base_desc += f"\nContribution: {percentage}% of suggested amount"
        elif schedule.contribution_mode == "Flexible":
            base_desc += f"\nFlexible contribution"

        # Fill in any missing period bound from the upcoming coverage period
        # (never from the previously-invoiced last_invoice_coverage_* fields).
        if coverage_start is None or coverage_end is None:
            computed_start, computed_end = schedule.calculate_next_coverage_period()
            coverage_start = coverage_start if coverage_start is not None else computed_start
            coverage_end = coverage_end if coverage_end is not None else computed_end

        base_desc += f"\nCoverage: {coverage_start} to {coverage_end}"

        return base_desc

    def get_or_create_dues_item(self, schedule):
        """Get or create item for membership dues billing"""
        item_code = f"DUES-{schedule.membership_type}-{schedule.billing_frequency}".replace(" ", "-").upper()

        if not frappe.db.exists("Item", item_code):
            item = frappe.new_doc("Item")
            item.item_code = item_code
            item.item_name = f"Membership Dues - {schedule.membership_type} ({schedule.billing_frequency})"
            item.item_group = "Services"
            item.is_stock_item = 0
            item.is_sales_item = 1
            item.is_service_item = 1
            item.save()

        return item_code

    def update_schedule_after_invoice(self, schedule):
        """Update dues schedule after creating invoice"""
        # Record the coverage period just invoiced and advance the schedule dates.
        # (The old call to schedule.calculate_coverage_dates() referenced a method
        # that does not exist; the correct API is calculate_next_coverage_period()
        # + update_schedule_dates(), mirroring InvoiceGenerationOrchestrator.)
        coverage_start, coverage_end = schedule.calculate_next_coverage_period()
        schedule.last_invoice_coverage_start = coverage_start
        schedule.last_invoice_coverage_end = coverage_end
        schedule.last_invoice_date = today()
        schedule.update_schedule_dates(actual_invoice_date=today())

        # Save changes
        schedule.save()

    # =========================================================================
    # Batch Validation
    # =========================================================================

    def handle_automated_batch_validation(self, batch):
        """
        Handle validation results for automated batch creation.
        Uses the same validation system as the Direct Debit Batch.
        """
        try:
            # Check if batch has validation results
            if not hasattr(batch, "validation_status") or not batch.validation_status:
                # Batch doesn't have validation results, skip notification
                return

            critical_errors = []
            warnings = []

            # Parse validation results if they exist
            if batch.validation_errors:
                try:
                    critical_errors = frappe.parse_json(batch.validation_errors)
                except (ValueError, TypeError) as e:
                    frappe.log_error(
                        title="SEPABatchProcessorValidation",
                        message=f"Failed to parse validation_errors: {e}",
                    )
                    critical_errors = []

            if batch.validation_warnings:
                try:
                    warnings = frappe.parse_json(batch.validation_warnings)
                except (ValueError, TypeError) as e:
                    frappe.log_error(
                        title="SEPABatchProcessorValidation",
                        message=f"Failed to parse validation_warnings: {e}",
                    )
                    warnings = []

            # Use the existing notification system
            from verenigingen.verenigingen_payments.api.sepa_batch_notifications import (
                handle_automated_batch_validation,
            )

            result = handle_automated_batch_validation(batch, critical_errors, warnings)

            frappe.logger().info(
                f"SEPA Batch Processor validation handled: {result['action']} for batch {batch.name}"
            )

        except Exception as e:
            frappe.log_error(
                title="SEPA Batch Processor - Validation Handler Error",
                message=f"Error handling automated batch validation for {batch.name}: {str(e)}",
            )


# =============================================================================
# Factory Function
# =============================================================================


def get_sepa_batch_processor():
    """Factory function to get SEPABatchProcessor instance"""
    return SEPABatchProcessor()


# =============================================================================
# Backward Compatibility Alias
# =============================================================================

# Alias for backward compatibility with existing code
SEPAProcessor = SEPABatchProcessor
