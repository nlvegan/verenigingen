// Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Donor', {
	refresh: function(frm) {
		frappe.dynamic_link = {doc: frm.doc, fieldname: 'name', doctype: 'Donor'};

		frm.toggle_display(['address_html','contact_html'], !frm.doc.__islocal);

		if(!frm.doc.__islocal) {
			frappe.contacts.render_address_and_contact(frm);

			// Add donation history functionality
			setup_donation_history(frm);

			// Add ANBI functionality
			setup_anbi_features(frm);
		} else {
			frappe.contacts.clear_address_and_contact(frm);
		}
	},

	donor_type: function(frm) {
		// Show/hide appropriate tax identifier field based on donor type
		update_tax_field_visibility(frm);
	},

	identification_verified: function(frm) {
		// Update verification fields when checkbox is changed
		if (frm.doc.identification_verified && !frm.doc.identification_verification_date) {
			frm.set_value('identification_verification_date', frappe.datetime.nowdate());
		}
	},

	anbi_consent: function(frm) {
		// Update consent date when consent is given
		if (frm.doc.anbi_consent && !frm.doc.anbi_consent_date) {
			frm.set_value('anbi_consent_date', frappe.datetime.now_datetime());
		}
	},

	bsn_citizen_service_number: function(frm) {
		// Validate BSN on change
		if (frm.doc.bsn_citizen_service_number && !frm.doc.bsn_citizen_service_number.startsWith('*')) {
			validate_bsn_field(frm);
		}
	}
});

function setup_donation_history(frm) {
	// Add sync button for donation history
	frm.add_custom_button(__('Sync Donation History'), function() {
		sync_donation_history(frm);
	}, __('Actions'));

	// Add new donation button
	frm.add_custom_button(__('New Donation'), function() {
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
		callback: function(r) {
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
		callback: function(r) {
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
		let methods = [];
		for (let method in summary.payment_methods) {
			methods.push(`${method} (${summary.payment_methods[method]})`);
		}
		methods_html += methods.join(', ') + '</p>';
		summary_html += `
			<div class="row">
				<div class="col-sm-12">
					${methods_html}
				</div>
			</div>
		`;
	}

	// Find the donation history section and add summary before it
	let $donation_tab = frm.get_field('donor_history').$wrapper.closest('.tab-pane');
	if ($donation_tab.length) {
		// Remove existing summary if it exists
		$donation_tab.find('.donation-summary').remove();

		// Add new summary at the top of the tab
		$donation_tab.prepend(`<div class="donation-summary" style="margin-bottom: 20px; padding: 15px; background-color: #f8f9fa; border-radius: 5px;">${summary_html}</div>`);
	}
}

// ANBI-specific functions
function setup_anbi_features(frm) {
	// Add ANBI buttons if user has appropriate permissions
	if (frm.perm[1] && frm.perm[1].read) {  // Check permlevel 1 permissions
		frm.add_custom_button(__('ANBI Operations'), function() {
			show_anbi_menu(frm);
		}, __('Actions'));

		// Add visual indicators for ANBI compliance
		add_anbi_indicators(frm);
	}

	// Update field visibility based on donor type
	update_tax_field_visibility(frm);
}

function show_anbi_menu(frm) {
	let d = new frappe.ui.Dialog({
		title: __('ANBI Operations'),
		fields: [
			{
				label: __('Select Operation'),
				fieldname: 'operation',
				fieldtype: 'Select',
				options: [
					'Update Tax Identifiers',
					'Validate BSN',
					'Generate ANBI Report',
					'Update ANBI Consent'
				],
				reqd: 1,
				change: function() {
					update_anbi_dialog_fields(d);
				}
			},
			{
				label: __('BSN (Citizen Service Number)'),
				fieldname: 'bsn',
				fieldtype: 'Data',
				depends_on: 'eval:doc.operation==\'Update Tax Identifiers\' || doc.operation==\'Validate BSN\'',
				description: __('9-digit Dutch citizen service number')
			},
			{
				label: __('RSIN (Organization Tax Number)'),
				fieldname: 'rsin',
				fieldtype: 'Data',
				depends_on: 'eval:doc.operation==\'Update Tax Identifiers\'',
				description: __('8 or 9-digit organization tax number')
			},
			{
				label: __('Verification Method'),
				fieldname: 'verification_method',
				fieldtype: 'Select',
				options: '\nDigiD\nManual\nBank Verification\nOther',
				depends_on: 'eval:doc.operation==\'Update Tax Identifiers\''
			},
			{
				label: __('ANBI Consent'),
				fieldname: 'consent',
				fieldtype: 'Check',
				depends_on: 'eval:doc.operation==\'Update ANBI Consent\''
			},
			{
				label: __('Reason (if withdrawing consent)'),
				fieldname: 'reason',
				fieldtype: 'Small Text',
				depends_on: 'eval:doc.operation==\'Update ANBI Consent\' && !doc.consent'
			}
		],
		primary_action_label: __('Execute'),
		primary_action: function(values) {
			execute_anbi_operation(frm, values);
			d.hide();
		}
	});

	d.show();
}

function update_anbi_dialog_fields(dialog) {
	// Reset fields based on selected operation
	let operation = dialog.get_value('operation');

	if (operation === 'Validate BSN') {
		dialog.set_df_property('bsn', 'reqd', 1);
	} else if (operation === 'Update Tax Identifiers') {
		dialog.set_df_property('verification_method', 'reqd', 1);
	}
}

function execute_anbi_operation(frm, values) {
	let operation = values.operation;

	if (operation === 'Update Tax Identifiers') {
		update_tax_identifiers(frm, values);
	} else if (operation === 'Validate BSN') {
		validate_bsn(values.bsn);
	} else if (operation === 'Generate ANBI Report') {
		generate_anbi_report(frm);
	} else if (operation === 'Update ANBI Consent') {
		update_anbi_consent(frm, values);
	}
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
		callback: function(r) {
			if (r.message && r.message.success) {
				frappe.show_alert({
					message: r.message.message,
					indicator: 'green'
				});
				frm.reload_doc();
			} else {
				frappe.show_alert({
					message: r.message ? r.message.message : __('Error updating tax identifiers'),
					indicator: 'red'
				});
			}
		}
	});
}

function validate_bsn(bsn) {
	frappe.call({
		method: 'verenigingen.api.anbi_operations.validate_bsn',
		args: {
			bsn: bsn
		},
		callback: function(r) {
			if (r.message) {
				frappe.msgprint({
					title: __('BSN Validation Result'),
					message: r.message.message,
					indicator: r.message.valid ? 'green' : 'red'
				});
			}
		}
	});
}

function validate_bsn_field(frm) {
	let bsn = frm.doc.bsn_citizen_service_number;
	if (bsn) {
		frappe.call({
			method: 'verenigingen.api.anbi_operations.validate_bsn',
			args: {
				bsn: bsn
			},
			callback: function(r) {
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
	let d = new frappe.ui.Dialog({
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
		primary_action: function(values) {
			frappe.call({
				method: 'verenigingen.api.anbi_operations.generate_anbi_report',
				args: values,
				callback: function(r) {
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
	let report_html = `
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

window.download_anbi_report = function(report_data_encoded) {
	let report_data = JSON.parse(decodeURIComponent(report_data_encoded));

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
	let blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
	let link = document.createElement('a');
	link.href = URL.createObjectURL(blob);
	link.download = `ANBI_Report_${report_data.period.from}_to_${report_data.period.to}.csv`;
	link.click();
};

function update_anbi_consent(frm, values) {
	frappe.call({
		method: 'verenigingen.api.anbi_operations.update_anbi_consent',
		args: {
			donor: frm.doc.name,
			consent: values.consent,
			reason: values.reason || null
		},
		callback: function(r) {
			if (r.message && r.message.success) {
				frappe.show_alert({
					message: r.message.message,
					indicator: 'green'
				});
				frm.reload_doc();
			}
		}
	});
}

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
