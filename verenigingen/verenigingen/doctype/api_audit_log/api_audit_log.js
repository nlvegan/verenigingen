/**
 * @fileoverview API Audit Log DocType Controller for Verenigingen Association Management
 *
 * This controller manages the display and interaction with API audit log records,
 * providing comprehensive audit trail visualization, reference document navigation,
 * and detailed event information for security and compliance monitoring.
 *
 * @description Business Context:
 * API Audit Log maintains a comprehensive audit trail of all API interactions
 * within the association management system, ensuring compliance and security:
 * - Complete API call tracking with timestamps and user attribution
 * - Reference document linking for context and traceability
 * - Severity-based categorization for priority assessment
 * - Detailed event information capture for debugging and analysis
 * - User activity monitoring for security compliance
 * - System event tracking for operational monitoring
 *
 * @description Key Features:
 * - Read-only interface to prevent audit trail tampering
 * - Severity-based visual indicators for quick assessment
 * - Reference document navigation for contextual analysis
 * - Formatted detail viewing with JSON syntax highlighting
 * - User profile integration for identity tracking
 * - Timestamp formatting for human-readable display
 * - Comprehensive event detail preservation
 *
 * @description Integration Points:
 * - Reference DocType linking for context navigation
 * - User management system for identity verification
 * - Security monitoring systems for compliance reporting
 * - System administration tools for operational analysis
 * - JSON detail parsing for structured data display
 * - Moment.js integration for timestamp formatting
 *
 * @description Security Features:
 * - Immutable audit records with read-only enforcement
 * - Complete event detail capture for forensic analysis
 * - User attribution for accountability tracking
 * - Severity classification for security incident response
 * - Reference linking for impact assessment
 *
 * @author Verenigingen Development Team
 * @version 2025-01-13
 * @since 1.0.0
 *
 * @requires frappe.ui.form
 * @requires frappe.ui.Dialog
 * @requires moment
 *
 * @example
 * // The controller automatically handles:
 * // - Read-only audit record display with tamper prevention
 * // - Severity-based visual indicators and navigation
 * // - Reference document linking and user profile access
 * // - Formatted detail viewing with JSON syntax highlighting
 */

// Copyright (c) 2025, Verenigingen and contributors
// For license information, please see license.txt

frappe.ui.form.on('API Audit Log', {
	refresh(frm) {
		// Make form read-only to prevent modifications
		frm.disable_save();
		frm.set_read_only();

		// Add custom buttons for viewing related records
		if (frm.doc.reference_doctype && frm.doc.reference_name) {
			frm.add_custom_button(__('View Reference Document'), () => {
				frappe.set_route('Form', frm.doc.reference_doctype, frm.doc.reference_name);
			});
		}

		if (frm.doc.user && frm.doc.user !== 'System') {
			frm.add_custom_button(__('View User'), () => {
				frappe.set_route('Form', 'User', frm.doc.user);
			});
		}

		// Show details in a formatted way
		if (frm.doc.details) {
			try {
				const details = typeof frm.doc.details === 'string'
					? JSON.parse(frm.doc.details) : frm.doc.details;

				if (Object.keys(details).length > 0) {
					frm.add_custom_button(__('View Details'), () => {
						const dialog = new frappe.ui.Dialog({
							title: __('Event Details'),
							size: 'large',
							fields: [{
								fieldtype: 'Code',
								fieldname: 'details_json',
								label: __('Details'),
								options: 'JSON',
								value: JSON.stringify(details, null, 2),
								read_only: 1
							}]
						});
						dialog.show();
					});
				}
			} catch (e) {
				console.warn('Failed to parse audit log details:', e);
			}
		}

		// Add severity-based styling
		if (frm.doc.severity) {
			const severityColors = {
				info: '#17a2b8',
				warning: '#ffc107',
				error: '#dc3545',
				critical: '#6f42c1'
			};

			const color = severityColors[frm.doc.severity] || '#6c757d';
			frm.set_indicator(frm.doc.severity.toUpperCase(), color);
		}
	},

	onload(frm) {
		// Format timestamp display
		if (frm.doc.timestamp) {
			frm.set_value('timestamp', moment(frm.doc.timestamp).format('YYYY-MM-DD HH:mm:ss'));
		}
	}
});
