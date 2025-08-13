/**
 * @fileoverview SEPA Audit Log Form Controller
 * @description Comprehensive audit trail management for SEPA payment transactions
 *
 * Business Context:
 * Maintains detailed audit logs for all SEPA Direct Debit transactions,
 * ensuring regulatory compliance and providing comprehensive transaction
 * tracking for financial oversight and dispute resolution.
 *
 * Key Features:
 * - Immutable transaction audit trails
 * - Regulatory compliance documentation
 * - Cross-reference linking to payment records
 * - Status change tracking for payment workflows
 * - Error logging for failed transactions
 *
 * Compliance Framework:
 * - SEPA regulation compliance tracking
 * - Audit trail preservation for legal requirements
 * - Transaction integrity verification
 * - Dispute resolution support documentation
 *
 * Integration Points:
 * - SEPA Mandate management for authorization tracking
 * - Direct Debit Batch processing for transaction correlation
 * - Payment systems for real-time transaction monitoring
 * - Banking interfaces for status synchronization
 *
 * Security Considerations:
 * - Read-only audit records for data integrity
 * - Secure transaction correlation identifiers
 * - Compliance-grade data retention policies
 * - Access control for sensitive financial data
 *
 * @author Verenigingen Development Team
 * @since 2024
 * @module SEPAAuditLog
 * @requires frappe.ui.form
 */

frappe.ui.form.on('SEPA Audit Log', {
	refresh(frm) {
		// Set read-only nature of audit logs
		if (!frm.is_new()) {
			frm.set_read_only();
		}

		// Add navigation to related records
		if (frm.doc.reference_doctype === 'SEPA Mandate' && frm.doc.reference_name) {
			frm.add_custom_button(__('View Mandate'), () => {
				frappe.set_route('Form', 'SEPA Mandate', frm.doc.reference_name);
			}, __('Related Records'));
		}

		if (frm.doc.reference_doctype === 'Direct Debit Batch' && frm.doc.reference_name) {
			frm.add_custom_button(__('View Batch'), () => {
				frappe.set_route('Form', 'Direct Debit Batch', frm.doc.reference_name);
			}, __('Related Records'));
		}

		// Set status indicator
		if (frm.doc.transaction_status) {
			const statusColor = {
				Pending: 'orange',
				Processed: 'blue',
				Completed: 'green',
				Failed: 'red',
				Rejected: 'red',
				Cancelled: 'gray'
			};

			frm.set_indicator_label(
				frm.doc.transaction_status,
				statusColor[frm.doc.transaction_status] || 'gray'
			);
		}
	},

	transaction_reference(frm) {
		// Validate transaction reference format
		if (frm.doc.transaction_reference
			&& !/^[A-Z0-9]{1,35}$/.test(frm.doc.transaction_reference)) {
			frappe.msgprint(__('Transaction reference must be alphanumeric and max 35 characters'));
		}
	}
});
