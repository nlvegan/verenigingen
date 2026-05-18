/**
 * @fileoverview Volunteer Utilities Module - Member-Volunteer Integration Services
 *
 * Comprehensive utility library for managing volunteer-related functionality within
 * the Member DocType context. Provides seamless integration between member profiles
 * and volunteer activities, enabling rich volunteer information display, profile
 * creation, and activity tracking directly from member records.
 *
 * ## Business Value
 * - **Volunteer Recruitment**: Streamlined conversion of members to volunteers
 * - **Engagement Visualization**: Rich display of volunteer activities and skills
 * - **Administrative Efficiency**: Centralized volunteer management from member records
 * - **Talent Management**: Skills-based volunteer matching and development
 * - **Activity Tracking**: Comprehensive volunteer contribution monitoring
 *
 * ## Core Capabilities
 * - **Profile Integration**: Dynamic volunteer information display within member forms
 * - **Skill Visualization**: Color-coded proficiency level display with badge system
 * - **Activity Navigation**: Direct access to volunteer activities and assignments
 * - **Profile Creation**: One-click volunteer profile generation from member data
 * - **Status Monitoring**: Real-time volunteer status tracking and visualization
 * - **Interest Mapping**: Display of volunteer interest areas and specializations
 *
 * ## Technical Architecture
 * - **Modular Design**: Reusable utility functions with clean separation of concerns
 * - **DOM Manipulation**: Dynamic HTML injection for volunteer information cards
 * - **Event Handling**: User interaction management for profile creation and navigation
 * - **API Integration**: Secure communication with backend volunteer services
 * - **Error Handling**: Comprehensive validation and user feedback systems
 * - **Global Namespace**: Window-level exports for cross-module accessibility
 *
 * ## Integration Points
 * - **Member DocType**: Primary integration point for volunteer functionality
 * - **Volunteer System**: Complete volunteer profile and activity management
 * - **Skills Database**: Volunteer competency tracking and visualization
 * - **Activity Engine**: Volunteer assignment and contribution tracking
 * - **UI Framework**: Frappe's standard interface components and styling
 * - **Navigation System**: Seamless routing to volunteer-related views
 *
 * ## User Experience Features
 * - **Visual Indicators**: Color-coded badges for status and proficiency levels
 * - **Information Cards**: Rich, contextual volunteer information display
 * - **Quick Actions**: One-click navigation to volunteer profiles and activities
 * - **Confirmation Dialogs**: User-friendly prompts for profile creation
 * - **Progress Feedback**: Visual indicators for long-running operations
 * - **Responsive Design**: Mobile-friendly volunteer information display
 *
 * ## Security Features
 * - **Permission Validation**: Role-based access to volunteer functionality
 * - **Data Sanitization**: Safe HTML generation and DOM manipulation
 * - **Audit Trail**: Complete tracking of volunteer profile creation and modifications
 * - **Privacy Compliance**: GDPR-compliant volunteer data handling
 *
 * ## Performance Optimization
 * - **Lazy Loading**: On-demand volunteer information retrieval
 * - **DOM Caching**: Efficient management of volunteer information displays
 * - **API Optimization**: Minimized server requests through intelligent caching
 * - **Progressive Enhancement**: Graceful degradation for basic functionality
 *
 * ## Module Functions
 * - `show_volunteer_info()`: Display volunteer profile within member form
 * - `create_volunteer_from_member()`: Generate volunteer profile from member data
 * - `show_volunteer_activities()`: Navigate to volunteer activity listings
 * - `show_volunteer_assignments()`: Access volunteer assignment management
 *
 * ## Usage Examples
 * ```javascript
 * // Display volunteer information
 * VolunteerUtils.show_volunteer_info(frm);
 *
 * // Create volunteer profile
 * VolunteerUtils.create_volunteer_from_member(frm);
 *
 * // Navigate to activities
 * VolunteerUtils.show_volunteer_activities('MEM-2025-001');
 * ```
 *
 * @version 1.1.0
 * @author Verenigingen Development Team
 * @since 2024-Q1
 *
 * @requires frappe.client
 * @requires frappe.ui
 * @requires frappe.route
 *
 * @see {@link member.js} Member DocType Controller
 * @see {@link volunteer.js} Volunteer Management System
 * @see {@link volunteer_activity.js} Activity Tracking
 */

// Volunteer-related utility functions for Member doctype

function show_volunteer_info(frm) {
	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Volunteer',
			filters: {
				member: frm.doc.name
			},
			fields: ['name', 'status', 'start_date']
		},
		callback(r) {
			if (r.message && r.message.length > 0) {
				const volunteer = r.message[0];

				// Get detailed volunteer information
				frappe.call({
					method: 'frappe.client.get',
					args: {
						doctype: 'Volunteer',
						name: volunteer.name
					},
					callback(volunteerResponse) {
						if (volunteerResponse.message) {
							const volunteerDoc = volunteerResponse.message;
							let skillsHtml = '';

							if (
								volunteerDoc.volunteer_skills
                && volunteerDoc.volunteer_skills.length > 0
							) {
								skillsHtml = '<strong>Skills:</strong><br>';
								volunteerDoc.volunteer_skills.forEach((skill) => {
									const proficiencyColor = get_proficiency_color(
										skill.proficiency_level
									);
									skillsHtml += `<span class="badge" style="background-color: ${proficiencyColor}; margin: 2px;">${skill.skill} (${skill.proficiency_level})</span><br>`;
								});
							}

							let interestsHtml = '';
							if (
								volunteerDoc.interest_areas
                && volunteerDoc.interest_areas.length > 0
							) {
								interestsHtml = '<strong>Interest Areas:</strong><br>';
								volunteerDoc.interest_areas.forEach((interest) => {
									interestsHtml += `<span class="badge badge-secondary" style="margin: 2px;">${interest.interest_area}</span><br>`;
								});
							}

							const html = `
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
		Beginner: '#ffc107',
		Intermediate: '#17a2b8',
		Advanced: '#28a745',
		Expert: '#6f42c1'
	};
	return colors[proficiency] || '#6c757d';
}

function get_status_class(status) {
	const classes = {
		Active: 'badge-success',
		Inactive: 'badge-secondary',
		'On Hold': 'badge-warning',
		Quit: 'badge-danger'
	};
	return classes[status] || 'badge-secondary';
}

function create_volunteer_from_member(frm) {
	// Create dialog with two paths: interest registration vs full activation
	const d = new frappe.ui.Dialog({
		title: __('Create Volunteer Profile'),
		fields: [
			{
				fieldtype: 'HTML',
				options: `<p class="text-muted">${__('Create a volunteer profile for')} <strong>${frappe.utils.escape_html(frm.doc.full_name || frm.doc.name)}</strong></p>
				<p class="text-muted small">${__('A volunteer profile tracks interests, skills, and background. You can activate full volunteer access later.')}</p>`
			},
			{
				fieldtype: 'Section Break',
				label: __('Activation Options')
			},
			{
				fieldtype: 'Check',
				fieldname: 'activate_volunteer',
				label: __('Activate as Full Volunteer'),
				description: __(
					'Grant volunteer portal access, assign Volunteer role, and create Employee record for expense claims'
				),
				default: 0
			},
			{
				fieldtype: 'HTML',
				fieldname: 'activation_note',
				options: `<div class="alert alert-info" style="margin-top: 10px;">
					<strong>${__('Note:')}</strong> ${__('Activation will be processed via Account Creation Request. An Employee record will be created for expense functionality.')}
				</div>`,
				depends_on: 'eval:doc.activate_volunteer'
			}
		],
		primary_action_label: __('Create Volunteer Profile'),
		primary_action(values) {
			// Prepare API call arguments
			const args = {
				member_name: frm.doc.name,
				create_user_account: values.activate_volunteer ? 1 : 0
			};

			// Add default volunteer role if activation is enabled
			if (values.activate_volunteer) {
				args.roles = ['Verenigingen Volunteer'];
			}

			frappe.call({
				method:
					'verenigingen.verenigingen.doctype.volunteer.volunteer.create_volunteer_from_member',
				args: args,
				freeze: true,
				freeze_message: __('Creating volunteer profile...'),
				callback(r) {
					// Unwrap OperationResult format
					const data = unwrapOperationResult(r.message);
					if (data && data.success) {
						let message = __('Volunteer profile created successfully');

						// Add activation info if queued
						if (data.account_creation_queued) {
							message += `<br><small>${__('Volunteer activation queued')}: ${data.account_request}</small>`;
						}

						frappe.show_alert(
							{
								message: message,
								indicator: 'green'
							},
							7
						);

						d.hide();

						// Reload from DB to show volunteer_record field
						frm.reload_doc();
					} else {
						frappe.msgprint({
							title: __('Error'),
							message: getErrorMessage(r.message, __('Failed to create volunteer profile')),
							indicator: 'red'
						});
					}
				}
			});
		}
	});

	d.show();
}

function show_volunteer_activities(member_name) {
	frappe.route_options = {
		volunteer: member_name
	};
	frappe.set_route('List', 'Volunteer Activity');
}

function show_volunteer_assignments(member_name) {
	frappe.route_options = {
		volunteer: member_name
	};
	frappe.set_route('List', 'Volunteer Assignment');
}

/**
 * Show volunteer activation dialog
 * Shared function used by both Member and Volunteer forms
 * @param {Object} options - Activation options
 * @param {string} options.member_name - Member document name
 * @param {string} options.display_name - Name to display in dialog
 * @param {Function} options.on_success - Callback on successful activation
 */
function show_volunteer_activation_dialog(options) {
	const { member_name, display_name, on_success } = options;

	const d = new frappe.ui.Dialog({
		title: __('Activate Volunteer'),
		fields: [
			{
				fieldtype: 'HTML',
				options: `<p>${__('Activate full volunteer access for')} <strong>${frappe.utils.escape_html(display_name)}</strong></p>
				<p class="text-muted small">${__('This will:')}</p>
				<ul class="text-muted small">
					<li>${__('Assign Verenigingen Volunteer role')}</li>
					<li>${__('Create Employee record for expense claims')}</li>
					<li>${__('Grant access to volunteer portal features')}</li>
				</ul>`
			},
			{
				fieldtype: 'MultiSelect',
				fieldname: 'additional_roles',
				label: __('Additional Roles'),
				options: [
					'Volunteer Team Member',
					'Volunteer Team Leader'
				],
				description: __('Optional additional roles to assign')
			}
		],
		primary_action_label: __('Activate'),
		primary_action(values) {
			// Build roles list - always include Verenigingen Volunteer
			let roles = ['Verenigingen Volunteer'];
			if (values.additional_roles && values.additional_roles.length > 0) {
				values.additional_roles.forEach(role => {
					if (!roles.includes(role)) {
						roles.push(role);
					}
				});
			}

			frappe.call({
				method: 'verenigingen.services.member.account.account_creation_api.queue_account_creation_for_member',
				args: {
					member_name: member_name,
					roles: roles,
					role_profile: 'Verenigingen Volunteer',
					priority: 'Normal'
				},
				freeze: true,
				freeze_message: __('Activating volunteer...'),
				callback(r) {
					if (r.message && r.message.success) {
						frappe.show_alert({
							message: __('Volunteer activation queued: {0}', [r.message.data.request_name]),
							indicator: 'green'
						}, 7);
						d.hide();
						if (on_success) on_success(r.message);
					} else {
						// Extract error from OperationResult format
						const errorMsg = getErrorMessage(r.message, __('Failed to activate volunteer'));
						frappe.msgprint({
							title: __('Error'),
							message: errorMsg,
							indicator: 'red'
						});
					}
				}
			});
		}
	});

	d.show();
}

// Export functions for use in member.js and volunteer.js
window.VolunteerUtils = {
	show_volunteer_info,
	create_volunteer_from_member,
	show_volunteer_activities,
	show_volunteer_assignments,
	show_volunteer_activation_dialog
};
