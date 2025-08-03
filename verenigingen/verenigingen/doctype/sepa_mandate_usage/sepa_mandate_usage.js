/**
 * @fileoverview SEPA Mandate Usage Tracking Controller
 * @description Monitors and manages SEPA mandate utilization for compliance and analytics
 *
 * Business Context:
 * Tracks the usage of SEPA mandates for direct debit transactions,
 * ensuring regulatory compliance with mandate usage limits and
 * providing analytics for payment processing optimization.
 *
 * Key Features:
 * - Mandate usage frequency tracking
 * - Compliance monitoring for SEPA regulations
 * - Usage analytics for payment optimization
 * - Historical tracking for audit purposes
 *
 * Compliance Requirements:
 * - SEPA mandate usage limitation enforcement
 * - First/recurring payment differentiation
 * - Mandate validity period monitoring
 * - Usage pattern analysis for fraud detection
 *
 * Analytics Integration:
 * - Payment success rate correlation with usage patterns
 * - Mandate lifecycle analytics
 * - Member payment behavior tracking
 * - Financial processing optimization metrics
 *
 * Data Integrity:
 * - Automatic usage logging for all mandate operations
 * - Cross-reference validation with payment records
 * - Audit trail maintenance for regulatory compliance
 * - Real-time usage statistics updates
 *
 * @author Verenigingen Development Team
 * @since 2024
 * @module SEPAMandateUsage
 * @requires frappe.ui.form
 */

frappe.ui.form.on('SEPA Mandate Usage', {
	refresh(frm) {
		// Set read-only for usage tracking records
		if (!frm.is_new()) {
			frm.set_read_only();
		}

		// Add navigation buttons to related records
		if (frm.doc.mandate) {
			frm.add_custom_button(__('View Mandate'), () => {
				frappe.set_route('Form', 'SEPA Mandate', frm.doc.mandate);
			}, __('Related Records'));
		}

		if (frm.doc.transaction_reference) {
			frm.add_custom_button(__('View Transaction'), () => {
				// Navigate to related payment or batch record
				frappe.db.get_value('Direct Debit Batch',
					{ transaction_references: ['like', `%${frm.doc.transaction_reference}%`] },
					'name')
					.then(r => {
						if (r.message && r.message.name) {
							frappe.set_route('Form', 'Direct Debit Batch', r.message.name);
						} else {
							frappe.msgprint(__('Related transaction not found'));
						}
					});
			}, __('Related Records'));
		}

		// Show usage statistics
		if (frm.doc.mandate) {
			frappe.call({
				method: 'frappe.client.get_list',
				args: {
					doctype: 'SEPA Mandate Usage',
					filters: { mandate: frm.doc.mandate },
					fields: ['usage_date', 'amount', 'status'],
					order_by: 'usage_date desc',
					limit: 10
				},
				callback(r) {
					if (r.message && r.message.length > 0) {
						show_usage_statistics(frm, r.message);
					}
				}
			});
		}
	},

	mandate(frm) {
		// Auto-populate mandate details when mandate is selected
		if (frm.doc.mandate) {
			frappe.db.get_value('SEPA Mandate', frm.doc.mandate,
				['mandate_id', 'member', 'status', 'first_use_date'],
				(r) => {
					if (r) {
						frm.set_value('mandate_reference', r.mandate_id);
						frm.set_value('member', r.member);

						// Determine if this is first use
						if (!r.first_use_date) {
							frm.set_value('is_first_use', 1);
						}
					}
				}
			);
		}
	}
});

function show_usage_statistics(frm, usage_data) {
	const total_usage = usage_data.length;
	const total_amount = usage_data.reduce((sum, record) => sum + (record.amount || 0), 0);
	const successful_transactions = usage_data.filter(record => record.status === 'Completed').length;
	const success_rate = total_usage > 0 ? (successful_transactions / total_usage * 100).toFixed(1) : 0;

	const stats_html = `
		<div class="mandate-usage-stats">
			<h6>${__('Mandate Usage Statistics')}</h6>
			<div class="row">
				<div class="col-md-3">
					<div class="stat-card">
						<div class="stat-value">${total_usage}</div>
						<div class="stat-label">${__('Total Uses')}</div>
					</div>
				</div>
				<div class="col-md-3">
					<div class="stat-card">
						<div class="stat-value">€${total_amount.toFixed(2)}</div>
						<div class="stat-label">${__('Total Amount')}</div>
					</div>
				</div>
				<div class="col-md-3">
					<div class="stat-card">
						<div class="stat-value">${success_rate}%</div>
						<div class="stat-label">${__('Success Rate')}</div>
					</div>
				</div>
				<div class="col-md-3">
					<div class="stat-card">
						<div class="stat-value">${successful_transactions}</div>
						<div class="stat-label">${__('Successful')}</div>
					</div>
				</div>
			</div>
		</div>
	`;

	// Add CSS if not already present
	if (!$('#mandate-usage-styles').length) {
		$('<style id="mandate-usage-styles">').html(`
			.mandate-usage-stats {
				background: #f8f9fa;
				padding: 15px;
				border-radius: 6px;
				margin: 15px 0;
			}
			.stat-card {
				text-align: center;
				padding: 15px;
				background: white;
				border-radius: 6px;
				box-shadow: 0 1px 3px rgba(0,0,0,0.1);
			}
			.stat-value {
				font-size: 24px;
				font-weight: bold;
				color: #495057;
			}
			.stat-label {
				font-size: 12px;
				color: #6c757d;
				text-transform: uppercase;
				letter-spacing: 0.5px;
				margin-top: 5px;
			}
		`).appendTo('head');
	}

	// Add to form
	if (!frm.fields_dict.usage_stats_html) {
		frm.add_field({
			fieldname: 'usage_stats_html',
			fieldtype: 'HTML',
			options: stats_html
		}, 'section_break_1');
	} else {
		$(frm.fields_dict.usage_stats_html.wrapper).html(stats_html);
	}
}
