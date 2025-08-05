/**
 * @fileoverview Expiring Memberships report JavaScript for proactive membership management
 *
 * Provides interactive functionality for the Expiring Memberships report, enabling
 * administrators to proactively manage membership renewals and prevent involuntary
 * membership lapses. This module transforms membership expiration monitoring into
 * an actionable administrative workflow.
 *
 * Key Features:
 * - Visual expiration timeline with urgency indicators
 * - Bulk renewal initiation for multiple memberships
 * - Automated renewal reminder dispatch
 * - Membership extension tools for special cases
 * - Export capabilities for offline processing
 * - Integration with payment processing workflows
 *
 * Renewal Management:
 * - Automated renewal notice generation
 * - Payment link creation for online renewals
 * - Grace period extension for administrative exceptions
 * - Bulk processing for membership batches
 * - Custom renewal terms for special circumstances
 * - Integration with SEPA direct debit workflows
 *
 * Business Context:
 * Essential for maintaining continuous membership engagement and preventing
 * unintentional membership lapses. Helps administrators stay ahead of expiration
 * deadlines, maintain steady membership revenue, and ensure members receive
 * appropriate renewal notices and payment opportunities.
 *
 * Integration:
 * - Connects to Membership DocType for renewal processing
 * - Links to payment processing and invoice generation
 * - Works with email notification systems
 * - Integrates with membership analytics and reporting
 * - Supports member retention tracking and analysis
 *
 * @author Verenigingen Development Team
 * @version 1.4.0
 * @since 2024-04-30
 */

// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Expiring Memberships"] = {
	"filters": [
		{
			"fieldname": "fiscal_year",
			"label": __("Fiscal Year"),
			"fieldtype": "Link",
			"options": "Fiscal Year",
			"default": frappe.defaults.get_user_default("fiscal_year"),
			"reqd": 1
		},
		{
			"fieldname":"month",
			"label": __("Month"),
			"fieldtype": "Select",
			"options": "Jan\nFeb\nMar\nApr\nMay\nJun\nJul\nAug\nSep\nOct\nNov\nDec",
			"default": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov",
				"Dec"][frappe.datetime.str_to_obj(frappe.datetime.get_today()).getMonth()],
		}
	]
}
