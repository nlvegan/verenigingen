// Copyright (c) 2025, Your Organization and contributors
// For license information, please see license.txt

frappe.ui.form.on('Volunteer', {
	refresh: function(frm) {
		// Set up dynamic link for address and contact
		// If volunteer is linked to a member, use member's address/contact
		if (frm.doc.member) {
			frappe.dynamic_link = {doc: {name: frm.doc.member, doctype: 'Member'}, fieldname: 'name', doctype: 'Member'};
		} else {
			frappe.dynamic_link = {doc: frm.doc, fieldname: 'name', doctype: 'Volunteer'};
		}

		// Toggle address and contact display
		frm.toggle_display(['address_html', 'contact_html'], !frm.doc.__islocal);

		// Load address and contact information
		if (!frm.doc.__islocal) {
			frappe.contacts.render_address_and_contact(frm);

			// Add button to view member record
			if (frm.doc.member) {
				frm.add_custom_button(__('View Member'), function() {
					frappe.set_route('Form', 'Member', frm.doc.member);
				}, __('Links'));
			}

			// Render custom assignments section
			render_aggregated_assignments(frm);

			// Add assignment buttons
			frm.add_custom_button(__('Add Activity'), function() {
				show_add_activity_dialog(frm);
			}, __('Assignments'));

			// Add button to view volunteer assignments timeline
			frm.add_custom_button(__('View Timeline'), function() {
				show_volunteer_timeline(frm);
			}, __('View'));

			// Add button to generate volunteer report
			frm.add_custom_button(__('Volunteer Report'), function() {
				generate_volunteer_report(frm);
			}, __('View'));
		} else {
			frappe.contacts.clear_address_and_contact(frm);
		}

		// Add skills grid custom button
		if (frm.fields_dict.skills_and_qualifications) {
			frm.fields_dict.skills_and_qualifications.grid.add_custom_button(__('Add Skill'),
				function() {
					add_new_skill(frm);
				}
			);
		}

		// Set up filters for reference_doctype in assignment grid
		frm.set_query('reference_doctype', 'assignment_history', function() {
			return {
				filters: {
					'name': ['in', ['Chapter', 'Team', 'Event', 'Volunteer Activity', 'Commission']]
				}
			};
		});
	},

	after_save: function(frm) {
		// Refresh the assignments view
		render_aggregated_assignments(frm);
	},

	member: function(frm) {
		// When member is changed, update the dynamic link for address/contact
		if (frm.doc.member) {
			frappe.dynamic_link = {doc: {name: frm.doc.member, doctype: 'Member'}, fieldname: 'name', doctype: 'Member'};
		} else {
			frappe.dynamic_link = {doc: frm.doc, fieldname: 'name', doctype: 'Volunteer'};
		}

		// Refresh address and contact display
		if (!frm.doc.__islocal) {
			frappe.contacts.render_address_and_contact(frm);
		}

		// When member is selected, fetch relevant information
		if (frm.doc.member) {
			frappe.call({
				method: 'frappe.client.get',
				args: {
					doctype: 'Member',
					name: frm.doc.member
				},
				callback: function(response) {
					if (response.message) {
						var member = response.message;

						// If this is a new record, update fields from member
						if (frm.doc.__islocal) {
							frm.set_value('volunteer_name', member.full_name);

							// Generate organization email based on full name
							frappe.call({
								method: 'frappe.client.get_value',
								args: {
									doctype: 'Verenigingen Settings',
									fieldname: 'organization_email_domain'
								},
								callback: function(r) {
									// Default domain if not set
									const domain = r.message && r.message.organization_email_domain
										? r.message.organization_email_domain
										: 'example.org';

									// Generate organization email based on full name including middle names/particles
									// This should match the Python logic in volunteer.py
									let nameForEmail = '';
									if (member.full_name) {
										// Replace spaces with dots and convert to lowercase
										nameForEmail = member.full_name.replace(/\s+/g, '.').toLowerCase();

										// Clean up special characters but preserve name particles (van, de, etc.)
										// Remove special characters except dots and letters, but keep the name particles
										nameForEmail = nameForEmail.replace(/[^a-z.]/g, '');

										// Clean up multiple consecutive dots and trim dots from ends
										nameForEmail = nameForEmail.replace(/\.+/g, '.').replace(/^\.+|\.+$/g, '');
									}

									// Construct organization email
									const orgEmail = nameForEmail ? `${nameForEmail}@${domain}` : '';

									if (orgEmail) {
										frm.set_value('email', orgEmail);
									}
								}
							});
						}
					}
				}
			});
		}
	}
});

// Function to render aggregated assignments
function render_aggregated_assignments(frm) {
	// Clear existing
	$(frm.fields_dict.assignment_section.wrapper).find('.assignments-container').remove();

	// Create container for assignments
	const assignments_container = $('<div class="assignments-container">').appendTo(
		frm.fields_dict.assignment_section.wrapper
	);

	// Add header
	$('<div class="assignments-header"><h4>' + __('Current Assignments') + '</h4></div>').appendTo(assignments_container);

	// Get assignments data with error handling
	frappe.call({
		method: 'get_aggregated_assignments',
		doc: frm.doc,
		freeze: true,
		freeze_message: __('Loading assignments...'),
		callback: function(r) {
			if (r.message && r.message.length) {
				// Create table
				const table = $(`
                    <table class="table table-bordered assignments-table">
                        <thead>
                            <tr>
                                <th>${__('Type')}</th>
                                <th>${__('Source')}</th>
                                <th>${__('Role')}</th>
                                <th>${__('From')}</th>
                                <th>${__('To')}</th>
                                <th>${__('Actions')}</th>
                            </tr>
                        </thead>
                        <tbody></tbody>
                    </table>
                `).appendTo(assignments_container);

				// Add rows
				const tbody = table.find('tbody');

				r.message.forEach(function(assignment) {
					const row = $('<tr>').appendTo(tbody);

					// Type column
					$(`<td>${assignment.source_type}</td>`).appendTo(row);

					// Source column with link
					$(`<td>
                        <a href="${assignment.source_link}">${assignment.source_doctype_display}: ${assignment.source_name_display}</a>
                    </td>`).appendTo(row);

					// Role column
					$(`<td>${assignment.role}</td>`).appendTo(row);

					// From date
					$(`<td>${frappe.datetime.str_to_user(assignment.start_date)}</td>`).appendTo(row);

					// To date
					$(`<td>${assignment.end_date ? frappe.datetime.str_to_user(assignment.end_date) : ''}</td>`).appendTo(row);

					// Actions column
					const actions_cell = $('<td class="action-column"></td>').appendTo(row);

					// Only show end assignment button for activities (which are editable)
					if (assignment.editable) {
						$(`<button class="btn btn-xs btn-danger">${__('End')}</button>`)
							.appendTo(actions_cell)
							.click(function() {
								show_end_activity_dialog(frm, assignment.source_name);
							});
					} else {
						$(`<button class="btn btn-xs btn-default">${__('View')}</button>`)
							.appendTo(actions_cell)
							.click(function() {
								frappe.set_route(assignment.source_link);
							});
					}
				});
			} else {
				$(`<div class="text-muted">${__('No active assignments')}</div>`).appendTo(assignments_container);
			}

			// Add button to create new activity
			$(`<div class="add-assignment-btn">
                <button class="btn btn-xs btn-primary">${__('Add Activity')}</button>
            </div>`).appendTo(assignments_container)
				.click(function() {
					show_add_activity_dialog(frm);
				});
		},
		error: function(r) {
			frappe.msgprint(__('Failed to load assignments: {0}', [r.message || __('Unknown error')]));
			$(`<div class="text-muted text-danger">${__('Error loading assignments')}</div>`).appendTo(assignments_container);
		}
	});
}

// Function to show dialog for adding a new activity
function show_add_activity_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __('Add New Activity'),
		fields: [
			{
				fieldname: 'activity_type',
				fieldtype: 'Select',
				label: __('Activity Type'),
				options: 'Project\nEvent\nWorkshop\nTraining\nCampaign\nOther',
				reqd: 1
			},
			{
				fieldname: 'role',
				fieldtype: 'Data',
				label: __('Role/Position'),
				reqd: 1
			},
			{
				fieldname: 'description',
				fieldtype: 'Small Text',
				label: __('Description')
			},
			{
				fieldname: 'dates_section',
				fieldtype: 'Section Break',
				label: __('Dates')
			},
			{
				fieldname: 'start_date',
				fieldtype: 'Date',
				label: __('Start Date'),
				default: frappe.datetime.get_today(),
				reqd: 1
			},
			{
				fieldname: 'end_date',
				fieldtype: 'Date',
				label: __('End Date')
			},
			{
				fieldname: 'reference_section',
				fieldtype: 'Section Break',
				label: __('Reference (Optional)')
			},
			{
				fieldname: 'reference_doctype',
				fieldtype: 'Link',
				label: __('Reference DocType'),
				options: 'DocType',
				get_query: function() {
					return {
						filters: {
							'name': ['in', ['Event', 'Project', 'Task']]
						}
					};
				}
			},
			{
				fieldname: 'reference_name',
				fieldtype: 'Dynamic Link',
				label: __('Reference Name'),
				options: 'reference_doctype'
			},
			{
				fieldname: 'details_section',
				fieldtype: 'Section Break',
				label: __('Additional Details')
			},
			{
				fieldname: 'estimated_hours',
				fieldtype: 'Float',
				label: __('Estimated Hours')
			},
			{
				fieldname: 'notes',
				fieldtype: 'Small Text',
				label: __('Notes')
			}
		],
		primary_action_label: __('Add'),
		primary_action: function() {
			const values = d.get_values();

			frappe.call({
				method: 'add_activity',
				doc: frm.doc,
				freeze: true,
				freeze_message: __('Adding activity...'),
				args: {
					activity_type: values.activity_type,
					role: values.role,
					description: values.description,
					start_date: values.start_date,
					end_date: values.end_date,
					reference_doctype: values.reference_doctype,
					reference_name: values.reference_name,
					estimated_hours: values.estimated_hours,
					notes: values.notes
				},
				callback: function(r) {
					if (r.message) {
						frappe.show_alert({
							message: __('Activity added successfully'),
							indicator: 'green'
						});

						// Refresh the assignments view
						render_aggregated_assignments(frm);
					}
				},
				error: function(r) {
					frappe.msgprint(__('Failed to add activity: {0}', [r.message || __('Unknown error')]));
				}
			});

			d.hide();
		}
	});

	d.show();
}

// Function to show dialog for ending an activity
function show_end_activity_dialog(frm, activity_name) {
	const d = new frappe.ui.Dialog({
		title: __('End Activity'),
		fields: [
			{
				fieldname: 'end_date',
				fieldtype: 'Date',
				label: __('End Date'),
				default: frappe.datetime.get_today(),
				reqd: 1
			},
			{
				fieldname: 'notes',
				fieldtype: 'Small Text',
				label: __('Notes')
			}
		],
		primary_action_label: __('End Activity'),
		primary_action: function() {
			const values = d.get_values();

			frappe.call({
				method: 'end_activity',
				doc: frm.doc,
				freeze: true,
				freeze_message: __('Ending activity...'),
				args: {
					activity_name: activity_name,
					end_date: values.end_date,
					notes: values.notes
				},
				callback: function(r) {
					if (r.message) {
						frappe.show_alert({
							message: __('Activity ended successfully'),
							indicator: 'green'
						});

						// Refresh the assignments view
						render_aggregated_assignments(frm);
					}
				},
				error: function(r) {
					frappe.msgprint(__('Failed to end activity: {0}', [r.message || __('Unknown error')]));
				}
			});

			d.hide();
		}
	});

	d.show();
}

// Function to show volunteer timeline
function show_volunteer_timeline(frm) {
	// Display a timeline visualization of volunteer history
	frappe.call({
		method: 'get_volunteer_history',
		doc: frm.doc,
		freeze: true,
		freeze_message: __('Loading volunteer history...'),
		callback: function(r) {
			if (r.message) {
				var history = r.message;

				// Create a formatted HTML timeline
				var html = '<div class="timeline-view">';
				html += '<h4>' + __('Volunteer History Timeline') + '</h4>';
				html += '<div class="timeline-items">';

				history.forEach(function(item) {
					var status_color = item.is_active ? 'green' : 'grey';
					if (item.status === 'Cancelled') status_color = 'red';

					html += '<div class="timeline-item">';
					html += '<div class="timeline-dot" style="background-color: var(--' + status_color + ');"></div>';
					html += '<div class="timeline-content">';
					html += '<div class="timeline-title">' + item.role + ' (' + item.assignment_type + ')</div>';
					html += '<div class="timeline-reference">' + (item.reference || '') + '</div>';
					html += '<div class="timeline-dates">' + frappe.datetime.str_to_user(item.start_date) +
                           (item.end_date ? ' to ' + frappe.datetime.str_to_user(item.end_date) : ' to Present') + '</div>';
					html += '<div class="timeline-status"><span class="indicator ' + status_color + '">' +
                           (item.is_active ? 'Active' : item.status) + '</span></div>';
					html += '</div>'; // timeline-content
					html += '</div>'; // timeline-item
				});

				html += '</div>'; // timeline-items
				html += '</div>'; // timeline-view

				// Show the timeline in a dialog
				var d = new frappe.ui.Dialog({
					title: __('Volunteer History for {0}', [frm.doc.volunteer_name]),
					fields: [{
						fieldtype: 'HTML',
						options: html
					}],
					primary_action_label: __('Close'),
					primary_action: function() {
						d.hide();
					}
				});

				d.show();

				// Add some custom CSS for the timeline
				d.$wrapper.find('.timeline-view').css({
					'max-height': '400px',
					'overflow-y': 'auto',
					'padding': '10px'
				});

				d.$wrapper.find('.timeline-items').css({
					'position': 'relative',
					'border-left': '2px solid var(--gray-400)',
					'margin-left': '10px',
					'padding-left': '20px'
				});

				d.$wrapper.find('.timeline-item').css({
					'margin-bottom': '20px',
					'position': 'relative'
				});

				d.$wrapper.find('.timeline-dot').css({
					'width': '12px',
					'height': '12px',
					'border-radius': '50%',
					'position': 'absolute',
					'left': '-27px',
					'top': '5px'
				});

				d.$wrapper.find('.timeline-title').css({
					'font-weight': 'bold',
					'font-size': '14px'
				});

				d.$wrapper.find('.timeline-reference').css({
					'color': 'var(--text-muted)',
					'font-size': '12px'
				});

				d.$wrapper.find('.timeline-dates').css({
					'margin-top': '5px',
					'font-size': '12px'
				});
			}
		},
		error: function(r) {
			frappe.msgprint(__('Failed to load volunteer history: {0}', [r.message || __('Unknown error')]));
		}
	});
}

// Function to add a new skill
function add_new_skill(frm) {
	// Dialog to add a new skill
	var d = new frappe.ui.Dialog({
		title: __('Add New Skill'),
		fields: [
			{
				fieldname: 'skill_category',
				fieldtype: 'Select',
				label: __('Skill Category'),
				options: 'Technical\nOrganizational\nCommunication\nLeadership\nFinancial\nEvent Planning\nOther',
				reqd: 1
			},
			{
				fieldname: 'volunteer_skill',
				fieldtype: 'Data',
				label: __('Skill'),
				reqd: 1
			},
			{
				fieldname: 'proficiency_level',
				fieldtype: 'Select',
				label: __('Proficiency Level'),
				options: '1 - Beginner\n2 - Basic\n3 - Intermediate\n4 - Advanced\n5 - Expert',
				default: '3 - Intermediate'
			},
			{
				fieldname: 'experience_years',
				fieldtype: 'Int',
				label: __('Years of Experience')
			},
			{
				fieldname: 'certifications',
				fieldtype: 'Small Text',
				label: __('Relevant Certifications')
			}
		],
		primary_action_label: __('Add'),
		primary_action: function() {
			var values = d.get_values();

			// Add skill to the grid with explicit field setting
			var child = frappe.model.add_child(frm.doc, 'Volunteer Skill', 'skills_and_qualifications');

			// Set values explicitly
			child.skill_category = values.skill_category;
			child.volunteer_skill = values.volunteer_skill;
			child.proficiency_level = values.proficiency_level;
			child.experience_years = values.experience_years;
			child.certifications = values.certifications;

			// Refresh the grid
			frm.refresh_field('skills_and_qualifications');

			d.hide();
		}
	});

	// Add autocomplete to skill field
	d.fields_dict.volunteer_skill.$input.on('input', function() {
		const partial_skill = $(this).val();
		if (partial_skill && partial_skill.length >= 2) {
			frappe.call({
				method: 'verenigingen.verenigingen.doctype.volunteer.volunteer.get_skill_suggestions',
				args: { partial_skill: partial_skill },
				callback: function(r) {
					if (r.message && r.message.length > 0) {
						setup_skill_autocomplete(d.fields_dict.volunteer_skill, r.message);
					}
				}
			});
		}
	});

	d.show();
}

// Helper function to setup skill autocomplete
function setup_skill_autocomplete(field, suggestions) {
	if (!field || !field.$input) return;

	// Remove existing autocomplete
	if (field.$input.autocomplete) {
		field.$input.autocomplete('destroy');
	}

	// Setup new autocomplete
	field.$input.autocomplete({
		source: suggestions,
		minLength: 2,
		select: function(event, ui) {
			field.set_value(ui.item.value);
			return false;
		}
	});
}

// Function to generate volunteer report
async function generate_volunteer_report(frm) {
	// Show loading indicator
	frappe.show_progress(__('Generating Report'), 10, 100, __('Loading data...'));

	try {
		// Use Promise.all to fetch data concurrently
		const [skillsResult, assignmentsResult] = await Promise.all([
			new Promise((resolve, reject) => {
				frappe.call({
					method: 'get_skills_by_category',
					doc: frm.doc,
					callback: function(r) {
						if (r.message !== undefined) {
							resolve(r.message);
						} else {
							reject(new Error('Failed to get skills data'));
						}
					},
					error: function(r) {
						reject(new Error(r.message || 'Failed to get skills data'));
					}
				});
			}),
			new Promise((resolve, reject) => {
				frappe.call({
					method: 'get_aggregated_assignments',
					doc: frm.doc,
					callback: function(r) {
						if (r.message !== undefined) {
							resolve(r.message);
						} else {
							reject(new Error('Failed to get assignments data'));
						}
					},
					error: function(r) {
						reject(new Error(r.message || 'Failed to get assignments data'));
					}
				});
			})
		]);

		frappe.show_progress(__('Generating Report'), 50, 100, __('Processing data...'));

		const skills_by_category = skillsResult || {};
		const assignments = assignmentsResult || [];

		// Generate HTML report
		const html = generate_report_html(frm, skills_by_category, assignments);

		frappe.show_progress(__('Generating Report'), 90, 100, __('Finalizing...'));

		// Show the report in a dialog
		show_report_dialog(frm, html);

		frappe.hide_progress();

	} catch (error) {
		frappe.hide_progress();
		frappe.msgprint(__('Failed to generate report: {0}', [error.message]));
	}
}

// Helper function to generate report HTML
function generate_report_html(frm, skills_by_category, assignments) {
	var html = '<div class="volunteer-report">';
	html += '<h3>' + __('Volunteer Report for {0}', [frm.doc.volunteer_name]) + '</h3>';

	// Basic information section
	html += '<div class="report-section"><h4>' + __('Basic Information') + '</h4>';
	html += '<table class="table table-condensed">';
	html += '<tr><td><strong>' + __('Name') + '</strong></td><td>' + frm.doc.volunteer_name + '</td></tr>';
	html += '<tr><td><strong>' + __('Status') + '</strong></td><td>' + frm.doc.status + '</td></tr>';
	html += '<tr><td><strong>' + __('Volunteer Since') + '</strong></td><td>' +
           frappe.datetime.str_to_user(frm.doc.start_date) + '</td></tr>';
	html += '<tr><td><strong>' + __('Commitment Level') + '</strong></td><td>' +
           (frm.doc.commitment_level || 'Not specified') + '</td></tr>';
	html += '<tr><td><strong>' + __('Experience Level') + '</strong></td><td>' +
           (frm.doc.experience_level || 'Not specified') + '</td></tr>';
	html += '<tr><td><strong>' + __('Work Style') + '</strong></td><td>' +
           (frm.doc.preferred_work_style || 'Not specified') + '</td></tr>';
	html += '</table></div>';

	// Current assignments section
	html += '<div class="report-section"><h4>' + __('Current Assignments') + '</h4>';

	if (assignments && assignments.length) {
		html += '<table class="table table-condensed">';
		html += '<thead><tr><th>' + __('Role') + '</th><th>' + __('Type') + '</th><th>' +
               __('Source') + '</th><th>' + __('Since') + '</th></tr></thead>';
		html += '<tbody>';

		assignments.forEach(function(assignment) {
			html += '<tr>';
			html += '<td>' + assignment.role + '</td>';
			html += '<td>' + assignment.source_type + '</td>';
			html += '<td>' + assignment.source_doctype_display + ': ' + assignment.source_name_display + '</td>';
			html += '<td>' + frappe.datetime.str_to_user(assignment.start_date) + '</td>';
			html += '</tr>';
		});

		html += '</tbody></table>';
	} else {
		html += '<p>' + __('No active assignments') + '</p>';
	}

	// Skills section
	html += '<div class="report-section"><h4>' + __('Skills and Qualifications') + '</h4>';

	if (Object.keys(skills_by_category).length) {
		html += '<div class="row">';

		for (var category in skills_by_category) {
			html += '<div class="col-sm-6 col-md-4">';
			html += '<div class="skill-category"><h5>' + category + '</h5>';
			html += '<ul class="list-unstyled">';

			skills_by_category[category].forEach(function(skill) {
				html += '<li><span class="skill-name">' + skill.skill + '</span> <span class="skill-level">' +
                       skill.level + '</span></li>';
			});

			html += '</ul></div></div>';
		}

		html += '</div>';
	} else {
		html += '<p>' + __('No skills recorded') + '</p>';
	}

	html += '</div>';

	// Areas of interest section
	if (frm.doc.interests && frm.doc.interests.length) {
		html += '<div class="report-section"><h4>' + __('Areas of Interest') + '</h4>';
		html += '<ul class="list-inline">';

		frm.doc.interests.forEach(function(interest) {
			html += '<li class="interest-tag">' + interest.interest_area + '</li>';
		});

		html += '</ul></div>';
	}

	// Footer
	html += '<div class="report-footer text-muted small">' +
           __('Report generated on {0}', [frappe.datetime.now_date()]) + '</div>';

	html += '</div>'; // volunteer-report

	return html;
}

// Helper function to show report dialog
function show_report_dialog(frm, html) {
	var d = new frappe.ui.Dialog({
		title: __('Volunteer Report'),
		fields: [{
			fieldtype: 'HTML',
			options: html
		}],
		primary_action_label: __('Print'),
		primary_action: function() {
			// Print the report
			var w = window.open();
			w.document.write('<html><head><title>' +
                            __('Volunteer Report - {0}', [frm.doc.volunteer_name]) +
                            '</title>');
			w.document.write('<style>');
			w.document.write('body { font-family: Arial, sans-serif; margin: 20px; }');
			w.document.write('.volunteer-report { max-width: 800px; margin: 0 auto; }');
			w.document.write('.report-section { margin-bottom: 20px; }');
			w.document.write('.skill-category { border: 1px solid #ddd; padding: 10px; margin-bottom: 10px; }');
			w.document.write('.skill-level { background-color: #f0f0f0; padding: 2px 6px; border-radius: 10px; font-size: 0.9em; }');
			w.document.write('.interest-tag { display: inline-block; background-color: #f0f0f0; padding: 3px 8px; margin: 3px; border-radius: 10px; }');
			w.document.write('.report-footer { margin-top: 30px; border-top: 1px solid #ddd; padding-top: 10px; }');
			w.document.write('table { width: 100%; border-collapse: collapse; }');
			w.document.write('th, td { padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }');
			w.document.write('</style></head><body>');
			w.document.write(html);
			w.document.write('</body></html>');
			w.print();
			w.close();
		},
		secondary_action_label: __('Close'),
		secondary_action: function() {
			d.hide();
		}
	});

	d.show();

	// Add some custom CSS for the report
	d.$wrapper.find('.volunteer-report').css({
		'max-height': '500px',
		'overflow-y': 'auto',
		'padding': '10px'
	});

	d.$wrapper.find('.report-section').css({
		'margin-bottom': '25px',
		'border-bottom': '1px solid var(--gray-200)',
		'padding-bottom': '15px'
	});

	d.$wrapper.find('.skill-category').css({
		'border': '1px solid var(--gray-200)',
		'border-radius': '4px',
		'padding': '10px',
		'margin-bottom': '10px'
	});

	d.$wrapper.find('.skill-level').css({
		'background-color': 'var(--gray-100)',
		'padding': '2px 6px',
		'border-radius': '10px',
		'font-size': '0.9em'
	});

	d.$wrapper.find('.interest-tag').css({
		'display': 'inline-block',
		'background-color': 'var(--gray-100)',
		'padding': '3px 8px',
		'margin': '3px',
		'border-radius': '10px'
	});
}

// Child table events for Volunteer Skill
frappe.ui.form.on('Volunteer Skill', {
	volunteer_skill: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.volunteer_skill && row.volunteer_skill.length > 2) {
			// Get suggestions from existing skills
			frappe.call({
				method: 'verenigingen.verenigingen.doctype.volunteer.volunteer.get_skill_suggestions',
				args: { partial_skill: row.volunteer_skill },
				callback: function(r) {
					if (r.message && r.message.length > 0) {
						// Log suggestions for now - we can enhance this later with a proper autocomplete widget
						console.warn('Skill suggestions for "' + row.volunteer_skill + '":', r.message);

						// Show suggestions in a frappe message
						if (r.message.length > 1) {
							frappe.show_alert({
								message: __('Similar skills found: {0}', [r.message.slice(0, 3).join(', ')]),
								indicator: 'blue'
							}, 3);
						}
					}
				}
			});
		}
	}
});
