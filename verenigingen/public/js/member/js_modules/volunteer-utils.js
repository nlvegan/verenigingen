// Volunteer-related utility functions for Member doctype

function show_volunteer_info(frm) {
    frappe.call({
        method: 'frappe.client.get_list',
        args: {
            doctype: 'Volunteer',
            filters: {
                'member': frm.doc.name
            },
            fields: ['name', 'status', 'start_date']
        },
        callback: function(r) {
            if (r.message && r.message.length > 0) {
                const volunteer = r.message[0];

                // Get detailed volunteer information
                frappe.call({
                    method: 'frappe.client.get',
                    args: {
                        doctype: 'Volunteer',
                        name: volunteer.name
                    },
                    callback: function(r) {
                        if (r.message) {
                            const volunteerDoc = r.message;
                            let skillsHtml = '';

                            if (volunteerDoc.volunteer_skills && volunteerDoc.volunteer_skills.length > 0) {
                                skillsHtml = '<strong>Skills:</strong><br>';
                                volunteerDoc.volunteer_skills.forEach(skill => {
                                    const proficiencyColor = get_proficiency_color(skill.proficiency_level);
                                    skillsHtml += `<span class="badge" style="background-color: ${proficiencyColor}; margin: 2px;">${skill.skill} (${skill.proficiency_level})</span><br>`;
                                });
                            }

                            let interestsHtml = '';
                            if (volunteerDoc.interest_areas && volunteerDoc.interest_areas.length > 0) {
                                interestsHtml = '<strong>Interest Areas:</strong><br>';
                                volunteerDoc.interest_areas.forEach(interest => {
                                    interestsHtml += `<span class="badge badge-secondary" style="margin: 2px;">${interest.interest_area}</span><br>`;
                                });
                            }

                            let html = `
                                <div class="volunteer-info-card" style="background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 10px 0;">
                                    <h5>🤝 Volunteer Information</h5>
                                    <div class="row">
                                        <div class="col-md-6">
                                            <p><strong>Status:</strong> <span class="badge ${get_status_class(volunteerDoc.status)}">${volunteerDoc.status}</span></p>
                                            <p><strong>Volunteer Since:</strong> ${frappe.datetime.str_to_user(volunteerDoc.start_date) || 'N/A'}</p>
                                        </div>
                                        <div class="col-md-6">
                                            ${skillsHtml}
                                            ${interestsHtml}
                                        </div>
                                    </div>
                                    <div class="mt-2">
                                        <button class="btn btn-sm btn-primary" onclick="frappe.set_route('Form', 'Volunteer', '${volunteerDoc.name}')">
                                            View Full Volunteer Profile
                                        </button>
                                    </div>
                                </div>
                            `;

                            // Insert the HTML into a suitable location in the form
                            if (!$('.volunteer-info-card').length) {
                                $(frm.fields_dict.full_name.wrapper).after(html);
                            }
                        }
                    }
                });
            }
        }
    });
}

function get_proficiency_color(proficiency) {
    const colors = {
        'Beginner': '#ffc107',
        'Intermediate': '#17a2b8',
        'Advanced': '#28a745',
        'Expert': '#6f42c1'
    };
    return colors[proficiency] || '#6c757d';
}

function get_status_class(status) {
    const classes = {
        'Active': 'badge-success',
        'Inactive': 'badge-secondary',
        'On Hold': 'badge-warning',
        'Terminated': 'badge-danger'
    };
    return classes[status] || 'badge-secondary';
}

function create_volunteer_from_member(frm) {
    frappe.confirm(
        __('Would you like to create a volunteer profile for this member?'),
        function() {
            frappe.call({
                method: 'verenigingen.verenigingen.doctype.volunteer.volunteer.create_from_member',
                args: {
                    member: frm.doc.name
                },
                callback: function(r) {
                    if (r.message) {
                        frappe.show_alert({
                            message: __('Volunteer profile created successfully'),
                            indicator: 'green'
                        }, 5);

                        // Refresh the form to show volunteer info
                        setTimeout(() => {
                            frm.refresh();
                        }, 1000);
                    }
                }
            });
        }
    );
}

function show_volunteer_activities(member_name) {
    frappe.route_options = {
        "volunteer": member_name
    };
    frappe.set_route("List", "Volunteer Activity");
}

function show_volunteer_assignments(member_name) {
    frappe.route_options = {
        "volunteer": member_name
    };
    frappe.set_route("List", "Volunteer Assignment");
}

// Export functions for use in member.js
window.VolunteerUtils = {
    show_volunteer_info,
    create_volunteer_from_member,
    show_volunteer_activities,
    show_volunteer_assignments
};
