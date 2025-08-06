/**
 * @fileoverview Payment Utility Functions for Member DocType
 *
 * This module provides comprehensive payment-related functionality for the Member
 * DocType, including payment processing, dues calculation, and SEPA integration.
 * Updated to use the Membership Dues Schedule system for accurate payment tracking.
 *
 * Business Context:
 * - Members pay membership dues and donations through SEPA direct debit
 * - Payment processing must integrate with e-Boekhouden accounting system
 * - Dues schedules determine payment amounts and frequencies
 * - Failed payments require retry logic and member notification
 * - Payment history affects membership status and benefits
 *
 * Key Features:
 * - Payment processing with dues schedule integration
 * - SEPA mandate validation and payment execution
 * - Payment history formatting and display
 * - Failed payment handling and retry mechanisms
 * - Integration with accounting and reporting systems
 *
 * Payment Flow:
 * 1. Dues calculation based on membership type and schedule
 * 2. SEPA mandate validation and payment authorization
 * 3. Payment processing through direct debit system
 * 4. Payment recording and member history update
 * 5. Accounting integration and reconciliation
 *
 * @module verenigingen/public/js/member/js_modules/payment-utils
 * @version 1.0.0
 * @since 2024
 * @see {@link ./sepa-utils.js|SEPA Utilities}
 * @see {@link ../../../e_boekhouden/|E-Boekhouden Integration}
 */

// Payment-related utility functions for Member doctype
// Updated to use the Membership Dues Schedule system.

function process_payment(frm) {
	if (!frm.doc.name) {
		frappe.msgprint(__('Please save the member record first.'));
		return;
	}

	frappe.call({
		method: 'verenigingen.verenigingen.doctype.member.member.process_payment',
		args: {
			member: frm.doc.name
		},
		callback(r) {
			if (r.message) {
				frm.refresh();
				frappe.show_alert(__('Payment processed successfully'), 5);
			}
		},
		error(r) {
			console.error('Error processing payment:', r);
			frappe.msgprint(__('Error processing payment. Please try again.'));
		}
	});
}

function mark_as_paid(frm) {
	frappe.confirm(
		__('Are you sure you want to mark this member as paid?'),
		() => {
			frappe.call({
				method: 'verenigingen.verenigingen.doctype.member.member.mark_as_paid',
				args: {
					member: frm.doc.name
				},
				callback(r) {
					if (r.message) {
						frm.refresh();
						frappe.show_alert(__('Member marked as paid'), 5);
					}
				}
			});
		}
	);
}

function format_payment_history_row(row) {
	if (row && row.doc) {
		const statusColors = {
			Paid: 'green',
			Unpaid: 'red',
			Overdue: 'orange',
			'Partially Paid': 'yellow'
		};

		const status = row.doc.payment_status;
		if (status && statusColors[status]) {
			$(row.wrapper).find('[data-fieldname="payment_status"]').css({
				color: statusColors[status],
				'font-weight': 'bold'
			});
		}
	}
}

function refresh_membership_dues_info(frm) {
	frappe.show_alert({
		message: __('Refreshing financial history...'),
		indicator: 'blue'
	});

	frappe.call({
		method: 'refresh_financial_history',
		doc: frm.doc,
		callback(_r) {
			frm.refresh_field('payment_history');

			// Updated to refresh dues schedule summary
			frappe.call({
				method: 'verenigingen.verenigingen.doctype.member.member.get_current_dues_schedule_details',
				args: {
					member: frm.doc.name
				},
				callback(r) {
					if (r.message && r.message.has_schedule && r.message.schedule_name) {
						frm.set_value('current_dues_schedule', r.message.schedule_name);
						if (r.message.dues_rate !== undefined) {
							frm.set_value('dues_rate', r.message.dues_rate);
						}
					}
				}
			});

			// Refresh fee change history from dues schedules
			frappe.call({
				method: 'verenigingen.verenigingen.doctype.member.member.refresh_fee_change_history',
				args: {
					member_name: frm.doc.name
				},
				callback(r) {
					if (r.message && r.message.success) {
						frm.refresh_field('fee_change_history');
					}
				}
			});

			// Count records by type
			const records = frm.doc.payment_history || [];
			const stats = calculate_financial_stats(records);

			// Show detailed message
			const message = `<div>Financial history refreshed:<br>
                ${stats.invoices + stats.membership_invoices} invoices (${stats.membership_invoices} membership, ${stats.paid} paid, ${stats.unpaid} unpaid, ${stats.overdue} overdue)<br>
                ${stats.unreconciled} unreconciled payments, ${stats.donations} linked to donations<br>
                Total: ${format_currency(stats.total_amount)}, Outstanding: ${format_currency(stats.outstanding)}</div>`;

			frappe.show_alert({
				message,
				indicator: stats.outstanding > 0 ? 'orange' : 'green'
			}, 10);
		}
	});
}

function calculate_financial_stats(records) {
	const stats = {
		total: records.length,
		invoices: 0,
		membership_invoices: 0,
		unreconciled: 0,
		donations: 0,
		paid: 0,
		unpaid: 0,
		overdue: 0,
		total_amount: 0,
		outstanding: 0
	};

	records.forEach(record => {
		stats.total_amount += flt(record.amount || 0);
		stats.outstanding += flt(record.outstanding_amount || 0);

		if (record.transaction_type === 'Regular Invoice') {
			stats.invoices++;
			if (record.payment_status === 'Paid') { stats.paid++; } else if (record.payment_status === 'Overdue') { stats.overdue++; } else if (['Unpaid', 'Partially Paid'].includes(record.payment_status)) { stats.unpaid++; }
		} else if (record.transaction_type === 'Membership Invoice') {
			stats.membership_invoices++;
			if (record.payment_status === 'Paid') { stats.paid++; } else if (record.payment_status === 'Overdue') { stats.overdue++; } else if (['Unpaid', 'Partially Paid'].includes(record.payment_status)) { stats.unpaid++; }
		} else if (record.transaction_type === 'Donation Payment') {
			stats.donations++;
		} else if (record.transaction_type === 'Unreconciled Payment') {
			stats.unreconciled++;
		}
	});

	return stats;
}

// Export functions for use in member.js
window.PaymentUtils = {
	process_payment,
	mark_as_paid,
	format_payment_history_row,
	refresh_membership_dues_info,
	calculate_financial_stats
};
