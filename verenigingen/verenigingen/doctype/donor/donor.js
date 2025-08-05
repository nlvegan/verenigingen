/**
 * @fileoverview Donor DocType Controller - Comprehensive Donor Management with ANBI Compliance
 *
 * This module provides advanced donor management capabilities for Dutch association compliance,
 * featuring ANBI (Algemeen Nut Beogende Instelling) tax regulations, donation tracking,
 * BSN/RSIN validation, and comprehensive donor relationship management. Integrates with
 * contact management, donation history, and regulatory reporting for full compliance support.
 *
 * Key Features:
 * - ANBI compliance management with automated BSN/RSIN validation
 * - Comprehensive donation history tracking and analytics
 * - Advanced tax identifier validation and secure storage
 * - Contact and address management integration
 * - Periodic donation agreement creation and management
 * - Real-time donation synchronization and reporting
 * - Privacy-compliant data handling with encryption support
 *
 * ANBI Compliance Features:
 * - BSN (Burgerservicenummer) format validation and verification
 * - RSIN (Rechtspersonen en Samenwerkingsverbanden Identificatienummer) management
 * - ANBI consent tracking with audit trails
 * - Tax deduction eligibility verification
 * - Regulatory reporting with export capabilities
 * - Identity verification workflow management
 *
 * Business Value:
 * - Ensures compliance with Dutch tax regulations for charitable organizations
 * - Streamlines donor onboarding and relationship management
 * - Provides comprehensive donation analytics for strategic planning
 * - Automates regulatory reporting reducing administrative burden
 * - Enhances donor engagement through integrated communication tools
 * - Supports data privacy requirements with secure identifier handling
 *
 * Technical Architecture:
 * - Frappe DocType form controller with comprehensive event handling
 * - Integration with Dutch government validation services
 * - Secure tax identifier storage with encryption capabilities
 * - Real-time donation synchronization and aggregation
 * - Advanced contact and address management integration
 * - Export capabilities for regulatory compliance reporting
 *
 * Security Features:
 * - Role-based access control for sensitive tax information
 * - Encrypted storage of BSN/RSIN identifiers
 * - audit logging for all ANBI-related operations
 * - GDPR-compliant data handling and privacy protection
 * - Secure validation through external government services
 *
 * @author Verenigingen Development Team
 * @version 2.3.0
 * @since 1.0.0
 *
 * @requires frappe
 * @requires frappe.contacts (Address and Contact management)
 * @requires verenigingen.utils.donation_history_manager (Donation analytics)
 * @requires verenigingen.api.anbi_operations (ANBI compliance backend)
 *
 * @example
 * // ANBI-compliant donor setup
 * // 1. Set donor_type: 'Individual' or 'Organization'
 * // 2. Enable anbi_consent: true
 * // 3. Set identification_verified: true
 * // 4. Add BSN (for individuals) or RSIN (for organizations)
 * // 5. System automatically tracks compliance status
 *
 * @see {@link verenigingen.api.anbi_operations} ANBI Compliance Backend
 * @see {@link verenigingen.utils.donation_history_manager} Donation Analytics
 * @see {@link verenigingen.verenigingen.doctype.donation} Donation Management
 * @see {@link verenigingen.verenigingen.doctype.periodic_donation_agreement} Recurring Donations
 */

// Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

/**
 * @namespace DonorController
 * @description Comprehensive donor management form controller with ANBI compliance support
 */
frappe.ui.form.on('Donor', {
	/**
	 * @method refresh
	 * @description Initializes comprehensive donor management interface with ANBI compliance tools
	 *
	 * Sets up the donor form with integrated contact management, donation history tracking,
	 * and ANBI compliance features. Provides context-sensitive interface elements based
	 * on donor type and compliance status for streamlined donor relationship management.
	 *
	 * Interface Components:
	 * - Dynamic contact and address management integration
	 * - Donation history dashboard with analytics
	 * - ANBI compliance tools and validation interfaces
	 * - Tax identifier management for Dutch regulations
	 * - Periodic donation agreement creation
	 * - Regulatory reporting and export capabilities
	 *
	 * @param {Object} frm - Frappe form object with donor data and methods
	 * @since 1.0.0
	 */
	refresh(frm) {
		frappe.dynamic_link = { doc: frm.doc, fieldname: 'name', doctype: 'Donor' };

		frm.toggle_display(['address_html', 'contact_html'], !frm.doc.__islocal);

		if (!frm.doc.__islocal) {
			frappe.contacts.render_address_and_contact(frm);

			// Add donation history functionality
			setup_donation_history(frm);

			// Add ANBI functionality
			setup_anbi_features(frm);
		} else {
			frappe.contacts.clear_address_and_contact(frm);
		}
	},

	donor_type(frm) {
		// Show/hide appropriate tax identifier field based on donor type
		update_tax_field_visibility(frm);
	},

	identification_verified(frm) {
		// Update verification fields when checkbox is changed
		if (frm.doc.identification_verified && !frm.doc.identification_verification_date) {
			frm.set_value('identification_verification_date', frappe.datetime.nowdate());
		}
	},

	anbi_consent(frm) {
		// Update consent date when consent is given
		if (frm.doc.anbi_consent && !frm.doc.anbi_consent_date) {
			frm.set_value('anbi_consent_date', frappe.datetime.now_datetime());
		}
	},

	bsn_citizen_service_number(frm) {
		// Validate BSN on change
		if (frm.doc.bsn_citizen_service_number && !frm.doc.bsn_citizen_service_number.startsWith('*')) {
			validate_bsn_field(frm);
		}
	}
});

/**
 * @function setup_donation_history
 * @description Configures comprehensive donation history management interface
 *
 * Sets up donation tracking capabilities including history synchronization,
 * new donation creation, and analytics dashboard. Provides integrated
 * donation management tools for enhanced donor relationship tracking.
 *
 * Features:
 * - Real-time donation history synchronization
 * - Quick new donation creation with donor pre-population
 * - Comprehensive donation analytics and summary dashboard
 * - Payment method tracking and analysis
 * - Donation status monitoring and reporting
 *
 * @param {Object} frm - Frappe form object for donor
 * @since 1.5.0
 */
function setup_donation_history(frm) {
	// Add sync button for donation history
	frm.add_custom_button(__('Sync Donation History'), () => {
		sync_donation_history(frm);
	}, __('Actions'));

	// Add new donation button
	frm.add_custom_button(__('New Donation'), () => {
		frappe.new_doc('Donation', {
			donor: frm.doc.name
		});
	}, __('Create'));

	// Load and display donation summary
	load_donation_summary(frm);
}

function sync_donation_history(frm) {
	frappe.show_alert({
		message: __('Syncing donation history...'),
		indicator: 'blue'
	});

	frappe.call({
		method: 'verenigingen.utils.donation_history_manager.sync_donor_history',
		args: {
			donor_name: frm.doc.name
		},
		callback(r) {
			if (r.message && r.message.success) {
				frappe.show_alert({
					message: __(r.message.message),
					indicator: 'green'
				});
				frm.reload_doc();
			} else {
				frappe.show_alert({
					message: __('Error syncing donation history: ') + (r.message.error || 'Unknown error'),
					indicator: 'red'
				});
			}
		}
	});
}

function load_donation_summary(frm) {
	frappe.call({
		method: 'verenigingen.utils.donation_history_manager.get_donor_summary',
		args: {
			donor_name: frm.doc.name
		},
		callback(r) {
			if (r.message && !r.message.error) {
				display_donation_summary(frm, r.message);
			}
		}
	});
}

function display_donation_summary(frm, summary) {
	// Create summary HTML
	let summary_html = `
		<div class="row" style="margin-bottom: 15px;">
			<div class="col-sm-12">
				<h5 style="margin-bottom: 10px;">Donation Summary</h5>
			</div>
		</div>
		<div class="row">
			<div class="col-sm-3">
				<div class="text-center">
					<h4 class="text-primary">${summary.total_donations}</h4>
					<p class="text-muted">Total Donations</p>
				</div>
			</div>
			<div class="col-sm-3">
				<div class="text-center">
					<h4 class="text-success">€${(summary.total_amount || 0).toFixed(2)}</h4>
					<p class="text-muted">Total Amount</p>
				</div>
			</div>
			<div class="col-sm-3">
				<div class="text-center">
					<h4 class="text-info">€${(summary.paid_amount || 0).toFixed(2)}</h4>
					<p class="text-muted">Paid Amount</p>
				</div>
			</div>
			<div class="col-sm-3">
				<div class="text-center">
					<h4 class="text-warning">€${(summary.unpaid_amount || 0).toFixed(2)}</h4>
					<p class="text-muted">Unpaid Amount</p>
				</div>
			</div>
		</div>
	`;

	if (summary.last_donation_date) {
		summary_html += `
			<div class="row" style="margin-top: 10px;">
				<div class="col-sm-12">
					<p><strong>Last Donation:</strong> ${frappe.datetime.str_to_user(summary.last_donation_date)}</p>
				</div>
			</div>
		`;
	}

	// Add payment methods breakdown if available
	if (summary.payment_methods && Object.keys(summary.payment_methods).length > 0) {
		let methods_html = '<p><strong>Payment Methods:</strong> ';
		const methods = [];
		for (const method in summary.payment_methods) {
			methods.push(`${method} (${summary.payment_methods[method]})`);
		}
		methods_html += `${methods.join(', ')}</p>`;
		summary_html += `
			<div class="row">
				<div class="col-sm-12">
					${methods_html}
				</div>
			</div>
		`;
	}

	// Find the donation history section and add summary before it
	const $donation_tab = frm.get_field('donor_history').$wrapper.closest('.tab-pane');
	if ($donation_tab.length) {
		// Remove existing summary if it exists
		$donation_tab.find('.donation-summary').remove();

		// Add new summary at the top of the tab
		$donation_tab.prepend(`<div class="donation-summary" style="margin-bottom: 20px; padding: 15px; background-color: #f8f9fa; border-radius: 5px;">${summary_html}</div>`);
	}
}

// ANBI-specific functions
function setup_anbi_features(frm) {
	// Add simplified ANBI operations for tax identifiers only
	if (frm.perm[1] && frm.perm[1].read) { // Check permlevel 1 permissions
		frm.add_custom_button(__('Validate BSN'), () => {
			validate_bsn_dialog(frm);
		}, __('ANBI'));

		frm.add_custom_button(__('Update Tax ID'), () => {
			update_tax_id_dialog(frm);
		}, __('ANBI'));

		// Add visual indicators for ANBI compliance
		add_anbi_indicators(frm);
	}

	// Add button for creating periodic donation agreement
	frm.add_custom_button(__('Create Donation Agreement'), () => {
		frappe.new_doc('Periodic Donation Agreement', {
			donor: frm.doc.name,
			donor_name: frm.doc.donor_name
		});
	}, __('Create'));

	// Update field visibility based on donor type
	update_tax_field_visibility(frm);
}

function validate_bsn_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __('Validate BSN'),
		fields: [
			{
				label: __('BSN (Citizen Service Number)'),
				fieldname: 'bsn',
				fieldtype: 'Data',
				reqd: 1,
				description: __('9-digit Dutch citizen service number'),
				change() {
					validate_bsn_format(d, this.get_value());
				}
			}
		],
		primary_action_label: __('Validate'),
		primary_action(values) {
			if (validate_bsn_format(d, values.bsn)) {
				validate_bsn(values.bsn);
				d.hide();
			}
		}
	});
	d.show();
}

function update_tax_id_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __('Update Tax Identifiers'),
		fields: [
			{
				label: __('BSN (Citizen Service Number)'),
				fieldname: 'bsn',
				fieldtype: 'Data',
				description: __('9-digit Dutch citizen service number')
			},
			{
				label: __('RSIN (Organization Tax Number)'),
				fieldname: 'rsin',
				fieldtype: 'Data',
				description: __('8 or 9-digit organization tax number')
			},
			{
				label: __('Verification Method'),
				fieldname: 'verification_method',
				fieldtype: 'Select',
				options: '\nDigiD\nManual\nBank Verification\nOther',
				reqd: 1
			}
		],
		primary_action_label: __('Update'),
		primary_action(values) {
			update_tax_identifiers(frm, values);
			d.hide();
		}
	});
	d.show();
}

// BSN format validation function
function validate_bsn_format(dialog, bsn) {
	if (!bsn) { return false; }

	// Clean BSN - remove spaces and non-digits
	const clean_bsn = bsn.replace(/\D/g, '');

	// Check length
	if (clean_bsn.length !== 9) {
		dialog.set_df_property('bsn', 'description',
			__('Invalid: BSN must be exactly 9 digits (currently {0})', [clean_bsn.length]));
		return false;
	}

	// Check for obvious invalid patterns
	if (clean_bsn === '000000000' || clean_bsn === '111111111'
		|| clean_bsn === '222222222' || clean_bsn === '333333333'
		|| clean_bsn === '444444444' || clean_bsn === '555555555'
		|| clean_bsn === '666666666' || clean_bsn === '777777777'
		|| clean_bsn === '888888888' || clean_bsn === '999999999') {
		dialog.set_df_property('bsn', 'description',
			__('Invalid: BSN cannot be all the same digit'));
		return false;
	}

	// Reset to normal description if valid format
	dialog.set_df_property('bsn', 'description',
		__('9-digit Dutch citizen service number'));
	return true;
}

function update_tax_identifiers(frm, values) {
	frappe.call({
		method: 'verenigingen.api.anbi_operations.update_donor_tax_identifiers',
		args: {
			donor: frm.doc.name,
			bsn: values.bsn || null,
			rsin: values.rsin || null,
			verification_method: values.verification_method
		},
		callback(r) {
			if (r.message && r.message.success) {
				frappe.show_alert({
					message: r.message.message || __('Tax identifiers updated successfully'),
					indicator: 'green'
				});
				frm.reload_doc();
			} else {
				const error_msg = r.message && r.message.message
					? r.message.message : __('Failed to update tax identifiers. Please try again.');
				frappe.show_alert({
					message: error_msg,
					indicator: 'red'
				});
			}
		},
		error(xhr, status, error) {
			frappe.show_alert({
				message: __('Network error while updating tax identifiers. Please check your connection.'),
				indicator: 'red'
			});
		}
	});
}

function validate_bsn(bsn) {
	frappe.call({
		method: 'verenigingen.api.anbi_operations.validate_bsn',
		args: {
			bsn
		},
		callback(r) {
			if (r.message) {
				frappe.msgprint({
					title: __('BSN Validation Result'),
					message: r.message.message || (r.message.valid ? __('BSN is valid') : __('BSN is invalid')),
					indicator: r.message.valid ? 'green' : 'red'
				});
			} else {
				frappe.msgprint({
					title: __('BSN Validation Result'),
					message: __('Unable to validate BSN. Please try again.'),
					indicator: 'orange'
				});
			}
		},
		error(xhr, status, error) {
			frappe.msgprint({
				title: __('BSN Validation Error'),
				message: __('Network error during BSN validation. Please check your connection and try again.'),
				indicator: 'red'
			});
		}
	});
}

function validate_bsn_field(frm) {
	const bsn = frm.doc.bsn_citizen_service_number;
	if (bsn) {
		frappe.call({
			method: 'verenigingen.api.anbi_operations.validate_bsn',
			args: {
				bsn
			},
			callback(r) {
				if (r.message && !r.message.valid) {
					frappe.show_alert({
						message: r.message.message,
						indicator: 'orange'
					});
				}
			}
		});
	}
}

function generate_anbi_report(frm) {
	const d = new frappe.ui.Dialog({
		title: __('Generate ANBI Report'),
		fields: [
			{
				label: __('From Date'),
				fieldname: 'from_date',
				fieldtype: 'Date',
				reqd: 1,
				default: frappe.datetime.year_start()
			},
			{
				label: __('To Date'),
				fieldname: 'to_date',
				fieldtype: 'Date',
				reqd: 1,
				default: frappe.datetime.year_end()
			},
			{
				label: __('Include BSN/RSIN'),
				fieldname: 'include_bsn',
				fieldtype: 'Check',
				description: __('Include decrypted tax identifiers (requires special permission)')
			}
		],
		primary_action_label: __('Generate'),
		primary_action(values) {
			frappe.call({
				method: 'verenigingen.api.anbi_operations.generate_anbi_report',
				args: values,
				callback(r) {
					if (r.message && r.message.success) {
						// Show report in a dialog or download as Excel
						show_anbi_report(r.message);
					} else {
						frappe.show_alert({
							message: r.message ? r.message.message : __('Error generating report'),
							indicator: 'red'
						});
					}
				}
			});
			d.hide();
		}
	});

	d.show();
}

function show_anbi_report(report_data) {
	// Create a detailed report dialog
	const report_html = `
		<h4>ANBI Report - ${frappe.datetime.str_to_user(report_data.report_date)}</h4>
		<p><strong>Period:</strong> ${frappe.datetime.str_to_user(report_data.period.from)} to ${frappe.datetime.str_to_user(report_data.period.to)}</p>
		<p><strong>Total Donations:</strong> ${report_data.summary.total_donations}</p>
		<p><strong>Total Amount:</strong> €${report_data.summary.total_amount.toFixed(2)}</p>
		<p><strong>Includes Tax IDs:</strong> ${report_data.summary.includes_tax_ids ? 'Yes' : 'No'}</p>
		<hr>
		<button class="btn btn-primary btn-sm" onclick="download_anbi_report('${encodeURIComponent(JSON.stringify(report_data))}')">
			<i class="fa fa-download"></i> Download as Excel
		</button>
	`;

	frappe.msgprint({
		title: __('ANBI Report Generated'),
		message: report_html,
		wide: true
	});
}

window.download_anbi_report = function (report_data_encoded) {
	const report_data = JSON.parse(decodeURIComponent(report_data_encoded));

	// Convert to CSV format for Excel
	let csv = 'Donation ID,Date,Amount,Donor Name,Donor Type,ANBI Agreement Number,ANBI Agreement Date,Purpose';
	if (report_data.summary.includes_tax_ids) {
		csv += ',BSN/RSIN';
	}
	csv += '\n';

	report_data.donations.forEach(donation => {
		csv += `"${donation.donation_id}","${donation.date}",${donation.amount},"${donation.donor_name}","${donation.donor_type}","${donation.anbi_agreement_number || ''}","${donation.anbi_agreement_date || ''}","${donation.purpose}"`;
		if (report_data.summary.includes_tax_ids) {
			csv += `,"${donation.bsn || donation.rsin || ''}"`;
		}
		csv += '\n';
	});

	// Download CSV file
	const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
	const link = document.createElement('a');
	link.href = URL.createObjectURL(blob);
	link.download = `ANBI_Report_${report_data.period.from}_to_${report_data.period.to}.csv`;
	link.click();
};

// ANBI consent is now handled directly via form field - no special function needed

function add_anbi_indicators(frm) {
	// Add visual indicators for ANBI compliance status
	let indicator_html = '<div class="anbi-indicators" style="margin-top: 10px;">';

	// ANBI consent indicator
	if (frm.doc.anbi_consent) {
		indicator_html += '<span class="indicator-pill green">ANBI Consent ✓</span> ';
	} else {
		indicator_html += '<span class="indicator-pill grey">No ANBI Consent</span> ';
	}

	// Identification verification indicator
	if (frm.doc.identification_verified) {
		indicator_html += '<span class="indicator-pill green">ID Verified ✓</span> ';
	} else {
		indicator_html += '<span class="indicator-pill orange">ID Not Verified</span> ';
	}

	// Tax ID indicator
	if (frm.doc.bsn_citizen_service_number || frm.doc.rsin_organization_tax_number) {
		indicator_html += '<span class="indicator-pill blue">Tax ID Available</span> ';
	}

	indicator_html += '</div>';

	// Add to form header
	frm.dashboard.add_comment(indicator_html, 'blue', true);
}

function update_tax_field_visibility(frm) {
	// Show/hide tax fields based on donor type
	if (frm.doc.donor_type === 'Individual') {
		frm.set_df_property('bsn_citizen_service_number', 'hidden', 0);
		frm.set_df_property('rsin_organization_tax_number', 'hidden', 1);
	} else if (frm.doc.donor_type === 'Organization') {
		frm.set_df_property('bsn_citizen_service_number', 'hidden', 1);
		frm.set_df_property('rsin_organization_tax_number', 'hidden', 0);
	}
}
