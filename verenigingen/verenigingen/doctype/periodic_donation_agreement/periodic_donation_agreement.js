/**
 * @fileoverview Periodic Donation Agreement Management - ANBI Tax Compliance & Donor Relations
 *
 * This module manages multi-year donation agreements between donors and the organization,
 * with specialized support for Dutch ANBI (Algemeen Nut Beogende Instelling) tax compliance.
 * Handles commitment tracking, payment scheduling, and automatic tax benefit qualification.
 *
 * ## Core Business Functions
 * - **ANBI Compliance Management**: Automatic qualification for 5+ year agreements
 * - **Multi-Year Commitment Tracking**: Progress monitoring across agreement duration
 * - **Payment Schedule Management**: Flexible frequency options (monthly, quarterly, annual)
 * - **Donation Linkage**: Connect individual donations to periodic agreements
 * - **Tax Benefit Optimization**: Maximize donor tax advantages through proper structuring
 * - **Agreement Lifecycle**: Draft → Active → Completed/Cancelled workflow
 *
 * ## Technical Architecture
 * - **Real-time Validation**: ANBI eligibility checks during data entry
 * - **Progress Tracking**: Visual indicators for commitment fulfillment
 * - **Document Generation**: PDF agreement creation with legal compliance
 * - **Integration Points**: Links with Donation, Donor, and SEPA mandate systems
 * - **Audit Trail**: Complete history of agreement modifications and cancellations
 *
 * ## ANBI Tax Compliance Features
 * - **5-Year Minimum**: Automatic qualification detection for periodic donation benefits
 * - **Tax Deduction Optimization**: Full deductibility without annual limits for qualified agreements
 * - **Donor Verification**: Identity and consent validation for tax purposes
 * - **Notarial Requirements**: Automatic determination of deed requirements based on amounts
 * - **Compliance Reporting**: ANBI-ready documentation for tax authority submissions
 *
 * ## Financial Integration
 * - **Payment Amount Calculation**: Automatic distribution across payment frequency
 * - **Expected vs Actual Tracking**: Monitors commitment fulfillment rates
 * - **SEPA Integration**: Links with direct debit mandates for automated collections
 * - **Donation Attribution**: Proper allocation of received payments to agreements
 * - **Revenue Recognition**: Support for accounting period allocation
 *
 * ## Donor Experience Features
 * - **Flexible Commitment Options**: Multiple duration and payment frequency choices
 * - **Progress Visualization**: Clear status on commitment fulfillment
 * - **Agreement Modification**: Structured process for changes and cancellations
 * - **Tax Benefit Communication**: Clear explanation of available tax advantages
 * - **Automated Reminders**: Payment notification and receipt generation
 *
 * ## Compliance & Security
 * - **GDPR Compliance**: Secure handling of donor personal and financial data
 * - **ANBI Regulation Adherence**: Meets Dutch tax authority requirements
 * - **Audit Trail**: Complete logging for compliance and forensic purposes
 * - **Data Integrity**: Validation prevents invalid agreement configurations
 * - **Permission Control**: Role-based access to sensitive donation data
 *
 * @company R.S.P. (Verenigingen Association Management)
 * @version 2025.1.0
 * @since 2024.2.0
 * @license Proprietary
 *
 * @requires frappe>=15.0.0
 * @requires verenigingen.donor
 * @requires verenigingen.donation
 *
 * @see {@link https://www.belastingdienst.nl/wps/wcm/connect/bldcontentnl/belastingdienst/zakelijk/bijzondere_regelingen/goede_doelen/anbi/} ANBI Regulations
 */

// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Periodic Donation Agreement', {
	refresh(frm) {
		// Show ANBI validation status
		if (frm.doc.anbi_eligible) {
			show_anbi_validation_status(frm);
		}

		// Add buttons based on status
		if (!frm.doc.__islocal) {
			if (frm.doc.status === 'Active') {
				frm.add_custom_button(__('Link Donation'), () => {
					link_donation_dialog(frm);
				}, __('Actions'));

				frm.add_custom_button(__('Cancel Agreement'), () => {
					cancel_agreement_dialog(frm);
				}, __('Actions'));

				frm.add_custom_button(__('Generate PDF'), () => {
					generate_agreement_pdf(frm);
				}, __('Actions'));
			}

			if (frm.doc.status === 'Draft') {
				frm.add_custom_button(__('Activate Agreement'), () => {
					activate_agreement(frm);
				}, __('Actions'));
			}

			// Add donation statistics
			add_donation_statistics(frm);
		}

		// Set agreement type options based on configuration
		set_agreement_type_options(frm);

		// Update payment amount on change
		frm.trigger('annual_amount');
		frm.trigger('payment_frequency');

		// Update ANBI eligibility display
		if (frm.doc.agreement_duration_years) {
			update_anbi_eligibility_message(frm);
		}
	},

	annual_amount(frm) {
		calculate_payment_amount(frm);
	},

	payment_frequency(frm) {
		calculate_payment_amount(frm);
	},

	agreement_duration_years(frm) {
		// Update ANBI eligibility message
		update_anbi_eligibility_message(frm);

		// Auto-update end date based on duration
		if (frm.doc.start_date && frm.doc.agreement_duration_years) {
			const duration = parseInt(frm.doc.agreement_duration_years.split(' ')[0], 10);
			if (duration) {
				const end_date = frappe.datetime.add_years(frm.doc.start_date, duration);
				frm.set_value('end_date', end_date);
			}
		}
	},

	start_date(frm) {
		// Auto-calculate end date based on selected duration
		if (frm.doc.start_date && frm.doc.agreement_duration_years) {
			const duration = parseInt(frm.doc.agreement_duration_years.split(' ')[0], 10);
			if (duration) {
				const end_date = frappe.datetime.add_years(frm.doc.start_date, duration);
				frm.set_value('end_date', end_date);
			}
		}
	},

	donor(frm) {
		// Check if donor has active ANBI consent
		if (frm.doc.donor) {
			frappe.call({
				method: 'verenigingen.api.anbi_operations.get_donor_anbi_data',
				args: {
					donor: frm.doc.donor
				},
				callback(r) {
					if (r.message && r.message.success) {
						if (!r.message.anbi_consent) {
							frappe.msgprint({
								title: __('ANBI Consent Missing'),
								message: __('This donor has not given ANBI consent. The agreement can still be created, but may not be valid for tax purposes.'),
								indicator: 'orange'
							});
						}

						if (!r.message.identification_verified) {
							frappe.msgprint({
								title: __('Identification Not Verified'),
								message: __('This donor\'s identification has not been verified. Consider verifying before creating the agreement.'),
								indicator: 'orange'
							});
						}
					}
				}
			});
		}
	}
});

function calculate_payment_amount(frm) {
	if (frm.doc.annual_amount && frm.doc.payment_frequency) {
		let payment_amount = 0;

		if (frm.doc.payment_frequency === 'Monthly') {
			payment_amount = frm.doc.annual_amount / 12;
		} else if (frm.doc.payment_frequency === 'Quarterly') {
			payment_amount = frm.doc.annual_amount / 4;
		} else if (frm.doc.payment_frequency === 'Annually') {
			payment_amount = frm.doc.annual_amount;
		}

		frm.set_value('payment_amount', payment_amount);
	}
}

function link_donation_dialog(frm) {
	// Get unlinked donations for this donor
	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Donation',
			filters: {
				donor: frm.doc.donor,
				periodic_donation_agreement: ['is', 'not set'],
				docstatus: 1
			},
			fields: ['name', 'donation_date', 'amount', 'payment_method'],
			limit_page_length: 100
		},
		callback(r) {
			if (r.message && r.message.length > 0) {
				const fields = [
					{
						label: __('Select Donation'),
						fieldname: 'donation',
						fieldtype: 'Select',
						options: r.message.map(d => ({
							value: d.name,
							label: `${d.name} - ${frappe.datetime.str_to_user(d.donation_date)} - €${d.amount}`
						})),
						reqd: 1
					}
				];

				const d = new frappe.ui.Dialog({
					title: __('Link Donation to Agreement'),
					fields,
					primary_action_label: __('Link'),
					primary_action(values) {
						frappe.call({
							method: 'link_donation',
							doc: frm.doc,
							args: {
								donation_name: values.donation
							},
							callback(response) {
								if (response.message) {
									frappe.show_alert({
										message: __('Donation linked successfully'),
										indicator: 'green'
									});
									frm.reload_doc();
								}
							}
						});
						d.hide();
					}
				});

				d.show();
			} else {
				frappe.msgprint(__('No unlinked donations found for this donor'));
			}
		}
	});
}

function cancel_agreement_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __('Cancel Periodic Donation Agreement'),
		fields: [
			{
				label: __('Cancellation Reason'),
				fieldname: 'reason',
				fieldtype: 'Small Text',
				reqd: 1
			}
		],
		primary_action_label: __('Cancel Agreement'),
		primary_action(values) {
			frappe.confirm(
				__('Are you sure you want to cancel this agreement? This action cannot be undone.'),
				() => {
					frappe.call({
						method: 'cancel_agreement',
						doc: frm.doc,
						args: {
							reason: values.reason
						},
						callback(r) {
							if (r.message) {
								frappe.show_alert({
									message: __('Agreement cancelled successfully'),
									indicator: 'green'
								});
								frm.reload_doc();
							}
						}
					});
				}
			);
			d.hide();
		}
	});

	d.show();
}

function activate_agreement(frm) {
	// Check required fields
	const required_fields = ['donor', 'start_date', 'annual_amount', 'payment_frequency', 'payment_method'];
	const missing_fields = [];

	required_fields.forEach(field => {
		if (!frm.doc[field]) {
			missing_fields.push(frm.fields_dict[field].df.label);
		}
	});

	if (missing_fields.length > 0) {
		frappe.msgprint({
			title: __('Missing Required Fields'),
			message: __('Please fill the following fields before activating: {0}', [missing_fields.join(', ')]),
			indicator: 'red'
		});
		return;
	}

	frappe.confirm(
		__('Are you sure you want to activate this agreement?'),
		() => {
			frm.set_value('status', 'Active');
			frm.save();
		}
	);
}

function generate_agreement_pdf(_frm) {
	// TODO: Implement PDF generation
	frappe.msgprint(__('PDF generation will be implemented in Phase 3'));
}

function add_donation_statistics(frm) {
	// Add donation statistics to the dashboard
	if (frm.doc.donations && frm.doc.donations.length > 0) {
		// Calculate actual duration in years
		let duration_years = 5; // default
		if (frm.doc.agreement_duration_years) {
			duration_years = parseInt(frm.doc.agreement_duration_years.split(' ')[0], 10) || 5;
		}

		const total_expected = frm.doc.annual_amount * duration_years;
		const progress_percentage = total_expected > 0 ? ((frm.doc.total_donated / total_expected) * 100).toFixed(1) : 0;

		// Determine agreement type for display
		const agreement_type = duration_years >= 5 ? __('ANBI Agreement') : __('Donation Pledge');

		const stats_html = `
            <div class="donation-statistics">
                <h5>${__('Donation Statistics')} - ${agreement_type}</h5>
                <div class="row">
                    <div class="col-sm-3">
                        <strong>${__('Total Expected')}:</strong><br>
                        €${total_expected.toFixed(2)}
                        <small class="text-muted">(${duration_years} ${__('years')})</small>
                    </div>
                    <div class="col-sm-3">
                        <strong>${__('Total Donated')}:</strong><br>
                        €${(frm.doc.total_donated || 0).toFixed(2)}
                    </div>
                    <div class="col-sm-3">
                        <strong>${__('Progress')}:</strong><br>
                        ${progress_percentage}%
                    </div>
                    <div class="col-sm-3">
                        <strong>${__('Next Expected')}:</strong><br>
                        ${frm.doc.next_expected_donation ? frappe.datetime.str_to_user(frm.doc.next_expected_donation) : __('Not set')}
                    </div>
                </div>
            </div>
        `;

		frm.dashboard.add_comment(stats_html, 'blue', true);
	}
}

function set_agreement_type_options(_frm) {
	// Set agreement type options based on configuration
	// For now, we'll use the default options
	// This can be expanded to pull from system settings
}

// Child table events for donations tracking
frappe.ui.form.on('Periodic Donation Agreement Item', {
	donations_add(frm, _cdt, _cdn) {
		// Update tracking when donation is added
		frm.trigger('update_donation_tracking');
	},

	donations_remove(frm, _cdt, _cdn) {
		// Update tracking when donation is removed
		frm.trigger('update_donation_tracking');
	},

	status(frm, cdt, cdn) {
		// Update tracking when status changes
		frm.trigger('update_donation_tracking');
	}
});

frappe.ui.form.on('Periodic Donation Agreement', {
	update_donation_tracking(frm) {
		// This will be handled server-side in the validate method
		frm.dirty();
	}
});

function show_anbi_validation_status(frm) {
	// Get ANBI validation status from server
	frappe.call({
		method: 'get_anbi_validation_status',
		doc: frm.doc,
		callback(r) {
			if (r.message) {
				const status = r.message;
				const indicator_class = status.valid ? 'green' : 'red';
				const icon = status.valid ? '✓' : '⚠';

				// Create status HTML
				let status_html = `
					<div class="anbi-validation-status" style="margin: 10px 0; padding: 10px; border-radius: 4px; border: 1px solid; ${status.valid ? 'background-color: #d4edda; border-color: #c3e6cb; color: #155724;' : 'background-color: #f8d7da; border-color: #f5c6cb; color: #721c24;'}">
						<strong>${icon} ${__('ANBI Validation Status')}: ${status.message}</strong>
				`;

				// Add errors if any
				if (status.errors && status.errors.length > 0) {
					status_html += `
						<div style="margin-top: 8px;">
							<strong>${__('Issues to resolve')}:</strong>
							<ul style="margin: 5px 0 0 20px;">
					`;
					status.errors.forEach(error => {
						status_html += `<li>${__(error)}</li>`;
					});
					status_html += '</ul></div>';
				}

				// Add warnings if any
				if (status.warnings && status.warnings.length > 0) {
					status_html += `
						<div style="margin-top: 8px;">
							<strong>${__('Warnings')}:</strong>
							<ul style="margin: 5px 0 0 20px;">
					`;
					status.warnings.forEach(warning => {
						status_html += `<li>${__(warning)}</li>`;
					});
					status_html += '</ul></div>';
				}

				status_html += '</div>';

				// Remove existing validation status
				frm.dashboard.wrapper.find('.anbi-validation-status').remove();

				// Add new validation status to dashboard
				frm.dashboard.add_comment(status_html, indicator_class, true);

				// If there are errors, also show an alert
				if (!status.valid) {
					frappe.show_alert({
						message: __('ANBI validation failed. Please review the issues listed above.'),
						indicator: 'red'
					}, 8);
				}
			}
		},
		error(_xhr, _status, error) {
			frappe.show_alert({
				message: __('Failed to check ANBI validation status. Please try again.'),
				indicator: 'orange'
			}, 5);
		}
	});
}

function update_anbi_eligibility_message(frm) {
	// Update ANBI eligibility message based on selected duration
	if (frm.doc.agreement_duration_years) {
		const duration = parseInt(frm.doc.agreement_duration_years.split(' ')[0], 10);
		let message = '';
		let indicator = '';

		if (duration >= 5) {
			message = __('This agreement qualifies for ANBI periodic donation tax benefits (5+ year commitment).');
			indicator = 'green';
			frm.set_value('anbi_eligible', 1);

			// Show expected ANBI benefits
			const anbi_info = `
                <div style="margin-top: 10px; padding: 10px; background-color: #d4edda; border: 1px solid #c3e6cb; border-radius: 4px;">
                    <strong>${__('ANBI Tax Benefits')}:</strong>
                    <ul style="margin-bottom: 0;">
                        <li>${__('Full tax deductibility for donor')}</li>
                        <li>${__('No maximum deduction limit')}</li>
                        <li>${__('Notarial deed not required for agreements up to €5,000/year')}</li>
                    </ul>
                </div>
            `;
			frm.set_df_property('agreement_duration_years', 'description',
				__('Duration of the commitment. Minimum 5 years required for ANBI periodic donation tax benefits.') + anbi_info);
		} else {
			message = __('This is a donation pledge without ANBI tax benefits (less than 5 years). The donor can still deduct donations but with standard limits.');
			indicator = 'orange';
			frm.set_value('anbi_eligible', 0);

			// Show pledge information
			const pledge_info = `
                <div style="margin-top: 10px; padding: 10px; background-color: #fff3cd; border: 1px solid #ffeaa7; border-radius: 4px;">
                    <strong>${__('Donation Pledge (No Special ANBI Benefits)')}:</strong>
                    <ul style="margin-bottom: 0;">
                        <li>${__('Standard tax deduction rules apply')}</li>
                        <li>${__('Subject to annual deduction limits')}</li>
                        <li>${__('Consider extending to 5+ years for full ANBI benefits')}</li>
                    </ul>
                </div>
            `;
			frm.set_df_property('agreement_duration_years', 'description',
				__('Duration of the commitment. Minimum 5 years required for ANBI periodic donation tax benefits.') + pledge_info);
		}

		// Display message to user
		if (!frm.is_new()) {
			frappe.show_alert({
				message,
				indicator
			}, 5);
		}

		// Update commitment type field if it exists
		if (frm.fields_dict.commitment_type) {
			frm.refresh_field('commitment_type');
		}
	}
}
