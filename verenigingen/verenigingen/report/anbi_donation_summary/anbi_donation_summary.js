/**
 * @fileoverview ANBI Donation Summary Report for Verenigingen Association Management
 *
 * This report provides comprehensive ANBI (Algemeen Nut Beogende Instelling) compliance
 * reporting for Dutch charitable organizations, enabling proper tax reporting and
 * regulatory compliance for donation activities.
 *
 * @description Business Context:
 * ANBI Donation Summary supports Dutch tax compliance requirements for charitable
 * organizations by providing:
 * - Comprehensive donation tracking with ANBI compliance indicators
 * - Tax ID (BSN/RSIN) management with privacy protection through masking
 * - Consent management for donor privacy and GDPR compliance
 * - Periodic donation agreement tracking for sustained giving programs
 * - Export capabilities for Belastingdienst (Dutch Tax Authority) reporting
 * - Automated consent request workflows for donor engagement
 *
 * @description Key Features:
 * - Date range filtering for specific reporting periods
 * - Donor type classification (Individual vs Organization)
 * - Reportable donation identification for tax purposes
 * - Periodic agreement tracking for sustained giving analysis
 * - ANBI consent status monitoring for privacy compliance
 * - Privacy-protected tax ID display with intelligent masking
 * - Color-coded indicators for quick status assessment
 * - Export functionality for regulatory reporting
 *
 * @description Integration Points:
 * - Donor management system for comprehensive donor information
 * - Donation tracking for financial compliance reporting
 * - Periodic donation agreement system for sustained giving
 * - ANBI operations API for compliance workflow automation
 * - Belastingdienst export functionality for regulatory filing
 * - Email system for automated consent request communications
 *
 * @description Compliance Features:
 * - GDPR-compliant privacy protection with tax ID masking
 * - ANBI regulatory compliance with proper categorization
 * - Audit trail maintenance for regulatory oversight
 * - Consent management for donor privacy protection
 * - Automated reporting workflows for tax authority submissions
 *
 * @author Verenigingen Development Team
 * @version 2025-01-13
 * @since 1.0.0
 *
 * @requires frappe.query_reports
 * @requires frappe.call
 * @requires frappe.datetime
 *
 * @example
 * // Report automatically provides:
 * // - ANBI-compliant donation summaries with privacy protection
 * // - Regulatory export capabilities for tax authority submission
 * // - Consent management workflows for donor engagement
 * // - Comprehensive filtering for specific compliance requirements
 */

// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports['ANBI Donation Summary'] = {
	'filters': [
		{
			'fieldname': 'from_date',
			'label': __('From Date'),
			'fieldtype': 'Date',
			'default': frappe.datetime.add_months(frappe.datetime.get_today(), -12),
			'reqd': 0
		},
		{
			'fieldname': 'to_date',
			'label': __('To Date'),
			'fieldtype': 'Date',
			'default': frappe.datetime.get_today(),
			'reqd': 0
		},
		{
			'fieldname': 'donor',
			'label': __('Donor'),
			'fieldtype': 'Link',
			'options': 'Donor'
		},
		{
			'fieldname': 'donor_type',
			'label': __('Donor Type'),
			'fieldtype': 'Select',
			'options': '\nIndividual\nOrganization'
		},
		{
			'fieldname': 'only_reportable',
			'label': __('Only Reportable'),
			'fieldtype': 'Check',
			'default': 0,
			'description': __('Show only donations that need to be reported to Belastingdienst')
		},
		{
			'fieldname': 'only_periodic',
			'label': __('Only Periodic Agreements'),
			'fieldtype': 'Check',
			'default': 0,
			'description': __('Show only donations linked to periodic agreements')
		},
		{
			'fieldname': 'consent_status',
			'label': __('ANBI Consent Status'),
			'fieldtype': 'Select',
			'options': '\nGiven\nNot Given'
		}
	],

	'formatter': function(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (column.fieldname == 'tax_id' && value && value !== '***ENCRYPTED***') {
			// Mask BSN/RSIN for privacy
			if (data.donor_type === 'Individual') {
				// BSN format: XXX-XX-1234
				if (value.length >= 4) {
					value = 'XXX-XX-' + value.slice(-4);
				}
			} else {
				// RSIN format: XXXX1234
				if (value.length >= 4) {
					value = 'XXXX' + value.slice(-4);
				}
			}
		}

		if (column.fieldname == 'reportable' && value) {
			value = `<span class="indicator-pill green">${__('Yes')}</span>`;
		} else if (column.fieldname == 'reportable') {
			value = `<span class="indicator-pill gray">${__('No')}</span>`;
		}

		if (column.fieldname == 'consent_given' && value) {
			value = `<span class="indicator-pill green">${__('Yes')}</span>`;
		} else if (column.fieldname == 'consent_given') {
			value = `<span class="indicator-pill orange">${__('No')}</span>`;
		}

		if (column.fieldname == 'agreement_type') {
			if (value.includes('ANBI Periodic')) {
				value = `<span style="color: green; font-weight: bold;">${value}</span>`;
			} else if (value.includes('Pledge')) {
				value = `<span style="color: blue;">${value}</span>`;
			}
		}

		return value;
	},

	onload: function(report) {
		// Add custom buttons
		report.page.add_inner_button(__('Export for Belastingdienst'), function() {
			frappe.call({
				method: 'verenigingen.api.anbi_operations.export_belastingdienst_report',
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

		report.page.add_inner_button(__('Send Consent Requests'), function() {
			frappe.confirm(
				__('Send ANBI consent request emails to all donors without consent?'),
				function() {
					frappe.call({
						method: 'verenigingen.api.anbi_operations.send_consent_requests',
						args: {
							filters: report.get_filter_values()
						},
						callback: function(r) {
							if (r.message) {
								frappe.msgprint(__('{0} consent request emails sent', [r.message.sent_count]));
								report.refresh();
							}
						}
					});
				}
			);
		});
	}
};
