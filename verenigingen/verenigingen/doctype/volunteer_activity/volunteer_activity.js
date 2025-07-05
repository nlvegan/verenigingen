// For license information, please see license.txt

frappe.ui.form.on('Volunteer Activity', {
    refresh: function(frm) {
        // Add button to view volunteer
        if (!frm.is_new() && frm.doc.volunteer) {
            frm.add_custom_button(__('View Volunteer'), function() {
                frappe.set_route('Form', 'Volunteer', frm.doc.volunteer);
            }, __('Links'));
        }

        // Add button to complete activity
        if (!frm.is_new() && frm.doc.status === 'Active') {
            frm.add_custom_button(__('Complete Activity'), function() {
                show_complete_dialog(frm);
            }, __('Actions'));
        }

        // Add reference filters
        frm.set_query("reference_doctype", function() {
            return {
                filters: {
                    "name": ["in", ["Event", "Project", "Task", "Meeting"]]
                }
            };
        });
    },

    volunteer: function(frm) {
        // When volunteer is selected, fetch name
        if (frm.doc.volunteer) {
            frappe.db.get_doc("Volunteer", frm.doc.volunteer).then(doc => {
                frm.set_value('volunteer_name', doc.volunteer_name);
            });
        }
    },

    start_date: function(frm) {
        // Validate dates
        if (frm.doc.end_date && frm.doc.start_date > frm.doc.end_date) {
            frappe.msgprint(__("Start date cannot be after end date"));
            frm.set_value('start_date', frm.doc.end_date);
        }
    },

    end_date: function(frm) {
        // Validate dates
        if (frm.doc.start_date && frm.doc.end_date && frm.doc.start_date > frm.doc.end_date) {
            frappe.msgprint(__("End date cannot be before start date"));
            frm.set_value('end_date', frm.doc.start_date);
        }
    },

    status: function(frm) {
        // Set end date when completing
        if (frm.doc.status === 'Completed' && !frm.doc.end_date) {
            frm.set_value('end_date', frappe.datetime.get_today());
        }
    }
});

// Function to show dialog for completing an activity
function show_complete_dialog(frm) {
    const d = new frappe.ui.Dialog({
        title: __('Complete Activity'),
        fields: [
            {
                fieldname: 'end_date',
                fieldtype: 'Date',
                label: __('End Date'),
                default: frappe.datetime.get_today(),
                reqd: 1
            },
            {
                fieldname: 'actual_hours',
                fieldtype: 'Float',
                label: __('Actual Hours'),
                description: __('Total hours spent on this activity')
            },
            {
                fieldname: 'notes',
                fieldtype: 'Small Text',
                label: __('Completion Notes')
            }
        ],
        primary_action_label: __('Complete'),
        primary_action: function() {
            const values = d.get_values();

            frm.set_value('status', 'Completed');
            frm.set_value('end_date', values.end_date);

            if (values.actual_hours) {
                frm.set_value('actual_hours', values.actual_hours);
            }

            if (values.notes) {
                frm.set_value('notes', frm.doc.notes ? (frm.doc.notes + '\n\nCompletion Notes: ' + values.notes) : values.notes);
            }

            frm.save();
            d.hide();
        }
    });

    d.show();
}
