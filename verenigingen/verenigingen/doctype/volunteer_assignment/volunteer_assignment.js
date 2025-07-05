// Copyright (c) 2025, Your Organization and contributors
// For license information, please see license.txt

frappe.ui.form.on('Volunteer Assignment', {
    // When assignment type changes, set reference_doctype based on assignment type
    before_add: function(frm, cdt, cdn) {
        // Set default values for new rows
        setTimeout(function() {
            var row = frappe.get_doc(cdt, cdn);
            if (!row.status) {
                frappe.model.set_value(cdt, cdn, 'status', 'Active');
            }
        }, 100);
    }
    assignment_type: function(frm, cdt, cdn) {
        var child = locals[cdt][cdn];

        // Set reference doctype based on assignment type
        if(child.assignment_type === 'Board Position') {
            frappe.model.set_value(cdt, cdn, 'reference_doctype', 'Chapter');
        } else if(child.assignment_type === 'Team') {
            frappe.model.set_value(cdt, cdn, 'reference_doctype', 'Team');
        } else if(child.assignment_type === 'Event') {
            frappe.model.set_value(cdt, cdn, 'reference_doctype', 'Event');
        } else if(child.assignment_type === 'Commission') {
            frappe.model.set_value(cdt, cdn, 'reference_doctype', 'Commission');
        }

        // Refresh the parent form to update UI and apply filters
        frm.refresh_field('active_assignments');
    },

    // When reference doctype changes, clear the reference name
    reference_doctype: function(frm, cdt, cdn) {
        frappe.model.set_value(cdt, cdn, 'reference_name', '');

        // Refresh the parent form to update UI and apply filters
        frm.refresh_field('active_assignments');

        // Force a re-query of the reference_name field to apply the latest filters
        var child = locals[cdt][cdn];
        if(child.reference_doctype) {
            setTimeout(function() {
                // This forces the dynamic link to refresh its options
                frm.fields_dict.active_assignments.grid.grid_rows_by_docname[cdn].refresh_field('reference_name');
            }, 300);
        }
    }
});
