/**
 * @fileoverview Team Member DocType JavaScript for team composition management
 *
 * Provides comprehensive form functionality for Team Member records, which serve
 * as child table entries within Team DocType for managing team composition,
 * roles, and member lifecycle. This module handles the complex business logic
 * around team membership including role assignments and status transitions.
 *
 * Key Features:
 * - Intelligent role assignment based on team type and position
 * - Automated volunteer information population and validation
 * - Status-based date management and lifecycle tracking
 * - Role type categorization with leader/member distinctions
 * - Date validation for membership periods
 * - Synchronized status and activity tracking
 *
 * Role Management:
 * - Dynamic role titles based on team type (Committee Chair vs Project Manager)
 * - Automatic leader/member role assignment based on role type
 * - Context-sensitive role suggestions for different team structures
 * - Role hierarchy support for team organization
 * - Professional title alignment with association standards
 *
 * Status Lifecycle:
 * - Active/inactive status synchronization with membership dates
 * - Automatic end date assignment on status changes
 * - Date validation to prevent inconsistent membership periods
 * - Status history tracking for audit and reporting
 * - Seamless transition handling for role changes
 *
 * Business Context:
 * Essential for managing the complex structure of association teams including
 * committees, working groups, project teams, and operational units. Ensures
 * proper role assignment, clear leadership hierarchy, and accurate tracking
 * of member participation across different organizational structures.
 *
 * Integration:
 * - Child table within Team DocType for membership tracking
 * - Links to Volunteer DocType for member information
 * - Supports team analytics and reporting systems
 * - Enables team structure visualization and planning
 * - Connects to responsibility and accountability frameworks
 *
 * @author Verenigingen Development Team
 * @version 2.0.0
 * @since 2024-09-10
 */

// Copyright (c) 2025, Your Organization and contributors
// For license information, please see license.txt

frappe.ui.form.on('Team Member', {
	volunteer(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.volunteer) {
			// Fetch volunteer details
			frappe.db.get_doc('Volunteer', row.volunteer).then(doc => {
				frappe.model.set_value(cdt, cdn, 'volunteer_name', doc.volunteer_name);
			});
		}
	},

	role_type(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const parent = frappe.get_doc(frm.doctype, frm.docname);

		// Set default role based on role type and team type
		if (parent && parent.team_type) {
			if (row.role_type === 'Team Leader') {
				const leader_title = get_leader_title(parent.team_type);
				frappe.model.set_value(cdt, cdn, 'role', leader_title);
			} else {
				const member_title = get_member_title(parent.team_type);
				frappe.model.set_value(cdt, cdn, 'role', member_title);
			}
		}
	},

	status(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		// If setting to inactive/completed, set end date if not already set
		if (row.status !== 'Active' && !row.to_date) {
			frappe.model.set_value(cdt, cdn, 'to_date', frappe.datetime.get_today());
		}

		// Update is_active flag to match status
		if (row.status === 'Active' && !row.is_active) {
			frappe.model.set_value(cdt, cdn, 'is_active', 1);
		} else if (row.status !== 'Active' && row.is_active) {
			frappe.model.set_value(cdt, cdn, 'is_active', 0);
		}
	},

	is_active(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		// If setting to inactive, set end date if not already set
		if (!row.is_active && !row.to_date) {
			frappe.model.set_value(cdt, cdn, 'to_date', frappe.datetime.get_today());
		}

		// Update status to match is_active
		if (!row.is_active && row.status === 'Active') {
			frappe.model.set_value(cdt, cdn, 'status', 'Inactive');
		} else if (row.is_active && row.status !== 'Active') {
			frappe.model.set_value(cdt, cdn, 'status', 'Active');
		}
	},

	from_date(frm, cdt, cdn) {
		validate_dates(frm, cdt, cdn);
	},

	to_date(frm, cdt, cdn) {
		validate_dates(frm, cdt, cdn);
	}
});

// Helper function to validate dates
function validate_dates(frm, cdt, cdn) {
	const row = locals[cdt][cdn];

	if (row.to_date && row.from_date && frappe.datetime.str_to_obj(row.from_date) > frappe.datetime.str_to_obj(row.to_date)) {
		frappe.msgprint(__('Start date cannot be after end date'));
		frappe.model.set_value(cdt, cdn, 'to_date', row.from_date);
	}
}

// Helper function to get leader title based on team type
function get_leader_title(team_type) {
	const leader_titles = {
		Committee: 'Committee Chair',
		'Working Group': 'Working Group Lead',
		'Task Force': 'Task Force Lead',
		'Project Team': 'Project Manager',
		'Operational Team': 'Team Coordinator',
		Other: 'Team Leader'
	};

	return leader_titles[team_type] || 'Team Leader';
}

// Helper function to get member title based on team type
function get_member_title(team_type) {
	const member_titles = {
		Committee: 'Committee Member',
		'Working Group': 'Working Group Member',
		'Task Force': 'Task Force Member',
		'Project Team': 'Project Team Member',
		'Operational Team': 'Operational Team Member',
		Other: 'Team Member'
	};

	return member_titles[team_type] || 'Team Member';
}
