// Copyright (c) 2025, Your Organization and contributors
// For license information, please see license.txt

frappe.ui.form.on('Team Responsibility', {
    responsibility: function(frm, cdt, cdn) {
        // No specific actions needed yet, but keeping for future extensions
    },

    assigned_to: function(frm, cdt, cdn) {
        // When assigning to a team member, validate that they belong to this team
        var row = locals[cdt][cdn];
        var parent = frappe.get_doc(frm.doctype, frm.docname);

        if (row.assigned_to && parent.team_members) {
            // Check if the assigned_to exists in the team_members
            var team_member_exists = parent.team_members.some(function(member) {
                return member.name === row.assigned_to;
            });

            if (!team_member_exists) {
                frappe.msgprint(__("The assigned person must be a member of this team"));
                frappe.model.set_value(cdt, cdn, 'assigned_to', '');
            }
        }
    },

    status: function(frm, cdt, cdn) {
        // Update UI based on status changes
        var row = locals[cdt][cdn];

        // You could add specific behaviors for different statuses
        if (row.status === 'Completed') {
            // Maybe notify or update some counters
        }
    }
});
