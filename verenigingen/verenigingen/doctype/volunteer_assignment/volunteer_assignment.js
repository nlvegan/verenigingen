/**
 * @fileoverview Volunteer Assignment Form Controller
 * @description Manages volunteer role assignments across different organizational contexts
 *
 * Business Context:
 * Handles the assignment of volunteers to various roles within the organization,
 * including board positions, teams, events, and commissions. Provides flexible
 * assignment management with dynamic reference linking.
 *
 * Key Features:
 * - Dynamic reference DocType selection based on assignment type
 * - Automatic status management for new assignments
 * - Context-sensitive field filtering and validation
 * - Real-time UI updates for assignment context changes
 *
 * Assignment Types:
 * - Board Position: Assigns volunteers to chapter board roles
 * - Team: Assigns volunteers to working teams and committees
 * - Event: Assigns volunteers to specific events and activities
 * - Commission: Assigns volunteers to organizational commissions
 *
 * Dynamic Linking:
 * - Contextual reference DocType selection
 * - Auto-clearing of invalid references on type changes
 * - Field refresh triggering for updated filters
 * - Delayed field updates for UI synchronization
 *
 * Data Integrity:
 * - Default status assignment for new records
 * - Reference validation based on assignment context
 * - UI state synchronization with data changes
 * - Cross-reference consistency maintenance
 *
 * @author Verenigingen Development Team
 * @since 2024
 * @module VolunteerAssignment
 * @requires frappe.ui.form, frappe.model
 */

frappe.ui.form.on('Volunteer Assignment', {
	// When assignment type changes, set reference_doctype based on assignment type
	before_add(frm, cdt, cdn) {
		// Set default values for new rows
		setTimeout(() => {
			const row = frappe.get_doc(cdt, cdn);
			if (!row.status) {
				frappe.model.set_value(cdt, cdn, 'status', 'Active');
			}
		}, 100);
	},
	assignment_type(frm, cdt, cdn) {
		const child = locals[cdt][cdn];

		// Set reference doctype based on assignment type
		if (child.assignment_type === 'Board Position') {
			frappe.model.set_value(cdt, cdn, 'reference_doctype', 'Chapter');
		} else if (child.assignment_type === 'Team') {
			frappe.model.set_value(cdt, cdn, 'reference_doctype', 'Team');
		} else if (child.assignment_type === 'Event') {
			frappe.model.set_value(cdt, cdn, 'reference_doctype', 'Event');
		} else if (child.assignment_type === 'Commission') {
			frappe.model.set_value(cdt, cdn, 'reference_doctype', 'Commission');
		}

		// Refresh the parent form to update UI and apply filters
		frm.refresh_field('active_assignments');
	},

	// When reference doctype changes, clear the reference name
	reference_doctype(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, 'reference_name', '');

		// Refresh the parent form to update UI and apply filters
		frm.refresh_field('active_assignments');

		// Force a re-query of the reference_name field to apply the latest filters
		const child = locals[cdt][cdn];
		if (child.reference_doctype) {
			setTimeout(() => {
				// This forces the dynamic link to refresh its options
				frm.fields_dict.active_assignments.grid.grid_rows_by_docname[cdn].refresh_field('reference_name');
			}, 300);
		}
	}
});
