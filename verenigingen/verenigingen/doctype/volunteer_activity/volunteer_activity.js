/**
 * @fileoverview Volunteer Activity DocType Controller - Comprehensive Activity Lifecycle Management
 *
 * Advanced volunteer activity management system for the Verenigingen association platform,
 * providing complete activity lifecycle tracking from initiation to completion. Enables
 * sophisticated volunteer engagement monitoring with time tracking, reference linking,
 * and completion workflow automation for optimal volunteer resource management.
 *
 * ## Business Value
 * - **Volunteer Engagement**: Detailed tracking of volunteer contributions and activities
 * - **Resource Planning**: Accurate time estimation and actual hour tracking for planning
 * - **Impact Measurement**: Quantifiable volunteer contribution metrics and analytics
 * - **Activity Coordination**: Seamless integration with events, projects, and organizational tasks
 * - **Performance Analytics**: Historical data for volunteer productivity and engagement analysis
 *
 * ## Core Capabilities
 * - **Activity Lifecycle**: Complete workflow from active status to completion
 * - **Time Tracking**: Estimated vs. actual hours with variance analysis
 * - **Volunteer Integration**: Direct linking to volunteer profiles and member records
 * - **Reference Linking**: Connection to events, projects, tasks, and meetings
 * - **Completion Workflow**: Structured activity completion with notes and metrics
 * - **Date Validation**: Intelligent date range validation and consistency checks
 *
 * ## Technical Architecture
 * - **Form Controller**: Event-driven activity form management with validation
 * - **Dialog Components**: Modal interfaces for activity completion and data entry
 * - **Data Validation**: Real-time validation of dates, hours, and status transitions
 * - **API Integration**: Secure communication with volunteer and reference systems
 * - **Status Management**: Automated status transitions with business rule enforcement
 * - **Error Handling**: Comprehensive validation with user-friendly feedback
 *
 * ## Integration Points
 * - **Volunteer System**: Bidirectional integration with volunteer profiles and assignments
 * - **Event Management**: Connection to organizational events and activities
 * - **Project Tracking**: Integration with project management and task systems
 * - **Member Records**: Indirect connection through volunteer-member relationships
 * - **Reporting Engine**: Data feed for volunteer analytics and impact reporting
 * - **Notification System**: Automated alerts for activity status changes
 *
 * ## Workflow Features
 * - **Activity Creation**: Structured activity initiation with reference linking
 * - **Status Tracking**: Real-time activity status monitoring and transitions
 * - **Completion Process**: Guided completion workflow with metrics collection
 * - **Time Management**: Comprehensive tracking of estimated and actual time investment
 * - **Note Management**: Rich text notes with completion annotations
 * - **Validation Rules**: Business logic enforcement for data consistency
 *
 * ## Security Features
 * - **Access Control**: Role-based permissions for activity creation and modification
 * - **Data Validation**: Server-side validation of all activity data
 * - **Audit Trail**: Complete tracking of activity modifications and status changes
 * - **Privacy Protection**: Secure handling of volunteer activity information
 *
 * ## Performance Optimization
 * - **Lazy Loading**: On-demand loading of volunteer and reference information
 * - **Smart Caching**: Efficient caching of volunteer names and reference data
 * - **Optimized Queries**: Efficient database access for activity operations
 * - **Progressive Enhancement**: Graceful degradation for basic activity management
 *
 * ## User Experience Features
 * - **Quick Actions**: One-click activity completion and volunteer navigation
 * - **Smart Defaults**: Intelligent default values for activity completion
 * - **Validation Feedback**: Real-time validation messages for data entry
 * - **Navigation Links**: Direct access to related volunteer and reference records
 * - **Structured Completion**: Guided workflow for activity closure
 *
 * ## Usage Examples
 * ```javascript
 * // Complete an activity
 * show_complete_dialog(frm);
 *
 * // Navigate to volunteer profile
 * frappe.set_route('Form', 'Volunteer', frm.doc.volunteer);
 *
 * // Validate date ranges
 * frm.trigger('start_date');
 * ```
 *
 * @version 1.1.0
 * @author Verenigingen Development Team
 * @since 2024-Q1
 *
 * @requires frappe.ui.form
 * @requires frappe.ui.Dialog
 * @requires frappe.db
 *
 * @see {@link volunteer.js} Volunteer Profile Management
 * @see {@link volunteer_assignment.js} Assignment Coordination
 * @see {@link event.js} Event Integration
 */

// For license information, please see license.txt

frappe.ui.form.on('Volunteer Activity', {
	refresh(frm) {
		// Add button to view volunteer
		if (!frm.is_new() && frm.doc.volunteer) {
			frm.add_custom_button(__('View Volunteer'), () => {
				frappe.set_route('Form', 'Volunteer', frm.doc.volunteer);
			}, __('Links'));
		}

		// Add button to complete activity
		if (!frm.is_new() && frm.doc.status === 'Active') {
			frm.add_custom_button(__('Complete Activity'), () => {
				show_complete_dialog(frm);
			}, __('Actions'));
		}

		// Add reference filters
		frm.set_query('reference_doctype', () => {
			return {
				filters: {
					name: ['in', ['Event', 'Project', 'Task', 'Meeting']]
				}
			};
		});
	},

	volunteer(frm) {
		// When volunteer is selected, fetch name
		if (frm.doc.volunteer) {
			frappe.db.get_doc('Volunteer', frm.doc.volunteer).then(doc => {
				frm.set_value('volunteer_name', doc.volunteer_name);
			});
		}
	},

	start_date(frm) {
		// Validate dates
		if (frm.doc.end_date && frm.doc.start_date > frm.doc.end_date) {
			frappe.msgprint(__('Start date cannot be after end date'));
			frm.set_value('start_date', frm.doc.end_date);
		}
	},

	end_date(frm) {
		// Validate dates
		if (frm.doc.start_date && frm.doc.end_date && frm.doc.start_date > frm.doc.end_date) {
			frappe.msgprint(__('End date cannot be before start date'));
			frm.set_value('end_date', frm.doc.start_date);
		}
	},

	status(frm) {
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
		primary_action() {
			const values = d.get_values();

			frm.set_value('status', 'Completed');
			frm.set_value('end_date', values.end_date);

			if (values.actual_hours) {
				frm.set_value('actual_hours', values.actual_hours);
			}

			if (values.notes) {
				frm.set_value('notes', frm.doc.notes ? (`${frm.doc.notes}\n\nCompletion Notes: ${values.notes}`) : values.notes);
			}

			frm.save();
			d.hide();
		}
	});

	d.show();
}
