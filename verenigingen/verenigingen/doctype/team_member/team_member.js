// Copyright (c) 2025, Your Organization and contributors
// For license information, please see license.txt

frappe.ui.form.on('Team Member', {
    volunteer: function(frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        if (row.volunteer) {
            // Fetch volunteer details
            frappe.db.get_doc("Volunteer", row.volunteer).then(doc => {
                frappe.model.set_value(cdt, cdn, 'volunteer_name', doc.volunteer_name);
            });
        }
    },

    role_type: function(frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        var parent = frappe.get_doc(frm.doctype, frm.docname);

        // Set default role based on role type and team type
        if (parent && parent.team_type) {
            if (row.role_type === 'Team Leader') {
                var leader_title = get_leader_title(parent.team_type);
                frappe.model.set_value(cdt, cdn, 'role', leader_title);
            } else {
                var member_title = get_member_title(parent.team_type);
                frappe.model.set_value(cdt, cdn, 'role', member_title);
            }
        }
    },

    status: function(frm, cdt, cdn) {
        var row = locals[cdt][cdn];
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

    is_active: function(frm, cdt, cdn) {
        var row = locals[cdt][cdn];
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

    from_date: function(frm, cdt, cdn) {
        validate_dates(frm, cdt, cdn);
    },

    to_date: function(frm, cdt, cdn) {
        validate_dates(frm, cdt, cdn);
    }
});

// Helper function to validate dates
function validate_dates(frm, cdt, cdn) {
    var row = locals[cdt][cdn];

    if (row.to_date && row.from_date && frappe.datetime.str_to_obj(row.from_date) > frappe.datetime.str_to_obj(row.to_date)) {
        frappe.msgprint(__("Start date cannot be after end date"));
        frappe.model.set_value(cdt, cdn, 'to_date', row.from_date);
    }
}

// Helper function to get leader title based on team type
function get_leader_title(team_type) {
    const leader_titles = {
        'Committee': 'Committee Chair',
        'Working Group': 'Working Group Lead',
        'Task Force': 'Task Force Lead',
        'Project Team': 'Project Manager',
        'Operational Team': 'Team Coordinator',
        'Other': 'Team Leader'
    };

    return leader_titles[team_type] || 'Team Leader';
}

// Helper function to get member title based on team type
function get_member_title(team_type) {
    const member_titles = {
        'Committee': 'Committee Member',
        'Working Group': 'Working Group Member',
        'Task Force': 'Task Force Member',
        'Project Team': 'Project Team Member',
        'Operational Team': 'Operational Team Member',
        'Other': 'Team Member'
    };

    return member_titles[team_type] || 'Team Member';
}
