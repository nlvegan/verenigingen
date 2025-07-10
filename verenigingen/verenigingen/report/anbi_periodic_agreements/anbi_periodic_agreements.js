// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports['ANBI Periodic Agreements'] = {
	'filters': [
		{
			'fieldname': 'status',
			'label': __('Status'),
			'fieldtype': 'Select',
			'options': '\nActive\nCompleted\nCancelled\nExpired'
		},
		{
			'fieldname': 'donor',
			'label': __('Donor'),
			'fieldtype': 'Link',
			'options': 'Donor'
		},
		{
			'fieldname': 'anbi_eligible',
			'label': __('ANBI Eligible'),
			'fieldtype': 'Select',
			'options': '\nYes\nNo',
			'description': __('Filter by ANBI eligibility status')
		},
		{
			'fieldname': 'expiring_in_days',
			'label': __('Expiring in Days'),
			'fieldtype': 'Int',
			'description': __('Show agreements expiring within specified days')
		},
		{
			'fieldname': 'payment_frequency',
			'label': __('Payment Frequency'),
			'fieldtype': 'Select',
			'options': '\nMonthly\nQuarterly\nAnnually'
		},
		{
			'fieldname': 'min_annual_amount',
			'label': __('Minimum Annual Amount'),
			'fieldtype': 'Currency',
			'description': __('Show only agreements with annual amount >= this value')
		}
	],

	'formatter': function(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (column.fieldname == 'status') {
			if (value.includes('Active')) {
				if (value.includes('Expiring Soon')) {
					value = `<span class="indicator-pill orange">${value}</span>`;
				} else {
					value = `<span class="indicator-pill green">${value}</span>`;
				}
			} else if (value === 'Completed') {
				value = `<span class="indicator-pill blue">${value}</span>`;
			} else if (value === 'Cancelled') {
				value = `<span class="indicator-pill red">${value}</span>`;
			} else if (value === 'Expired') {
				value = `<span class="indicator-pill gray">${value}</span>`;
			}
		}

		if (column.fieldname == 'commitment_type') {
			if (value.includes('ANBI')) {
				value = `<span style="color: green; font-weight: bold;">${value}</span>`;
			} else if (value.includes('Pledge')) {
				value = `<span style="color: blue;">${value}</span>`;
			}
		}

		if (column.fieldname == 'anbi_eligible' && value) {
			value = `<span class="indicator-pill green">${__('Yes')}</span>`;
		} else if (column.fieldname == 'anbi_eligible') {
			value = `<span class="indicator-pill gray">${__('No')}</span>`;
		}

		if (column.fieldname == 'completion_percentage') {
			let color = 'red';
			if (value >= 80) color = 'green';
			else if (value >= 50) color = 'orange';
			value = `<span style="color: ${color}; font-weight: bold;">${value}%</span>`;
		}

		if (column.fieldname == 'days_remaining') {
			if (value > 0 && value <= 30) {
				value = `<span style="color: red; font-weight: bold;">${value}</span>`;
			} else if (value > 30 && value <= 90) {
				value = `<span style="color: orange; font-weight: bold;">${value}</span>`;
			}
		}

		return value;
	},

	onload: function(report) {
		// Add custom buttons
		report.page.add_inner_button(__('Send Renewal Reminders'), function() {
			frappe.prompt({
				fieldname: 'days',
				label: __('Days Before Expiry'),
				fieldtype: 'Int',
				default: 90,
				description: __('Send reminders to agreements expiring within these many days')
			}, function(values) {
				frappe.call({
					method: 'verenigingen.api.periodic_donation_operations.send_renewal_reminders',
					args: {
						days_before_expiry: values.days
					},
					callback: function(r) {
						if (r.message) {
							frappe.msgprint(__('{0} renewal reminder emails sent', [r.message.sent_count]));
						}
					}
				});
			}, __('Send Renewal Reminders'));
		});

		report.page.add_inner_button(__('Generate Tax Receipts'), function() {
			let filters = report.get_filter_values();
			filters.generate_receipts = true;

			frappe.call({
				method: 'verenigingen.api.anbi_operations.generate_tax_receipts',
				args: {
					filters: filters
				},
				callback: function(r) {
					if (r.message) {
						frappe.msgprint(__('{0} tax receipts generated', [r.message.generated_count]));
					}
				}
			});
		});

		report.page.add_inner_button(__('Export Agreements'), function() {
			frappe.call({
				method: 'verenigingen.api.periodic_donation_operations.export_agreements',
				args: {
					filters: report.get_filter_values()
				},
				callback: function(r) {
					if (r.message && r.message.file_url) {
						window.open(r.message.file_url);
					}
				}
			});
		});
	}
};
