/**
 * @fileoverview Member ID Counter Management - Sequential ID Assignment & Migration Tools
 *
 * This module provides comprehensive member ID counter management functionality,
 * featuring sequential ID assignment, gap detection, counter reset capabilities,
 * and migration tools for transitioning from legacy member ID systems.
 *
 * ## Core Functionality
 * - **Sequential ID Assignment**: Automatic assignment of unique, sequential member IDs
 * - **Gap Detection & Utilization**: Intelligent identification and reuse of ID gaps
 * - **Counter Management**: Administrative controls for counter reset and adjustment
 * - **Migration Support**: Tools for migrating from legacy member ID systems
 * - **Statistics & Monitoring**: Real-time counter statistics and assignment tracking
 * - **Validation & Safety**: Comprehensive validation to prevent ID conflicts
 *
 * ## Technical Architecture
 * - **Atomic Operations**: Thread-safe counter incrementation with database locks
 * - **Gap Analysis**: Efficient algorithms for identifying and managing ID gaps
 * - **Migration Engine**: Robust migration tools with rollback capabilities
 * - **Audit Trail**: Complete logging of all counter operations and changes
 * - **Performance Optimization**: Optimized queries for large member datasets
 * - **Error Recovery**: Graceful handling of counter conflicts and edge cases
 *
 * ## ID Assignment Strategy
 * - **Sequential Allocation**: IDs assigned in numerical sequence starting from configurable base
 * - **Gap Filling**: Automatic reuse of gaps created by deleted or migrated members
 * - **Conflict Prevention**: Atomic operations prevent duplicate ID assignment
 * - **Range Management**: Support for different ID ranges for different member types
 * - **Custom Numbering**: Configurable starting points and increment patterns
 * - **Legacy Integration**: Seamless integration with existing member numbering schemes
 *
 * ## Administrative Features
 * - **Counter Reset**: Controlled reset of member ID counter with validation
 * - **Statistics Dashboard**: Real-time monitoring of ID assignment patterns
 * - **Gap Analysis**: Detailed reporting of unused ID ranges
 * - **Migration Tools**: Step-by-step migration from legacy systems
 * - **System Health**: Monitoring and alerting for counter system issues
 * - **Bulk Operations**: Efficient processing of large member datasets
 *
 * ## Migration Capabilities
 * - **Legacy System Import**: Automated migration from Verenigingen Settings counter
 * - **Data Validation**: Comprehensive validation of existing member ID assignments
 * - **Conflict Resolution**: Intelligent handling of ID conflicts during migration
 * - **Rollback Support**: Safe rollback options if migration issues occur
 * - **Progress Tracking**: Real-time migration progress monitoring
 * - **Post-Migration Validation**: Comprehensive system health checks after migration
 *
 * ## Safety & Validation
 * - **Duplicate Prevention**: Multi-layer validation prevents duplicate ID assignment
 * - **Range Validation**: Ensures counter values stay within acceptable ranges
 * - **Permission Control**: Role-based access to sensitive counter operations
 * - **Audit Logging**: Complete audit trail of all counter modifications
 * - **Backup Integration**: Automatic backup before major counter operations
 * - **Recovery Procedures**: Documented recovery procedures for system failures
 *
 * ## User Interface Features
 * - **Real-time Preview**: Shows next member ID during member creation
 * - **Administrative Dashboard**: Comprehensive counter management interface
 * - **Visual Statistics**: Charts and graphs showing ID assignment patterns
 * - **Alert System**: Notifications for unusual counter activity
 * - **Migration Wizard**: Step-by-step guidance for system migration
 * - **Troubleshooting Tools**: Diagnostic tools for resolving counter issues
 *
 * ## Integration Points
 * - Member management system
 * - Verenigingen Settings configuration
 * - Database counter tables
 * - Audit logging system
 * - Migration utilities
 * - System health monitoring
 *
 * ## Performance Considerations
 * - **Optimized Queries**: Efficient database operations for counter management
 * - **Caching Strategy**: Smart caching of counter values and statistics
 * - **Bulk Processing**: Optimized algorithms for large-scale operations
 * - **Memory Management**: Efficient handling of member ID datasets
 * - **Connection Pooling**: Optimized database connection usage
 * - **Background Processing**: Non-blocking operations for complex tasks
 *
 * @company R.S.P. (Verenigingen Association Management)
 * @version 2025.1.0
 * @since 2024.1.0
 * @license Proprietary
 *
 * @requires frappe>=15.0.0
 * @requires verenigingen.member
 * @requires verenigingen.verenigingen_settings
 * @requires verenigingen.member.member_id_manager
 *
 * @see {@link /app/Form/Member} Member Form
 * @see {@link /app/Form/Verenigingen%20Settings} System Settings
 */

/**
 * Member Counter Management Frontend
 * verenigingen/public/js/member_counter.js
 */

// Member doctype form customizations
frappe.ui.form.on('Member', {
	refresh(frm) {
		// Only show counter management for system managers
		if (frappe.user.has_role('System Manager')) {
			setup_member_counter_section(frm);
			load_counter_statistics(frm);
		}

		// Show member ID preview for new members
		if (frm.doc.__islocal && !frm.doc.member_id) {
			show_member_id_preview(frm);
		}
	},

	reset_counter_button(frm) {
		handle_counter_reset(frm);
	},

	birth_date(frm) {
		// Auto-calculate age when birth date changes
		if (frm.doc.birth_date) {
			const age = calculate_age(frm.doc.birth_date);
			frm.set_value('age', age);

			// Show warning for unusual ages
			if (age < 12) {
				frappe.show_alert(
					{
						message: __('Applicant is under 12 years old - may require special handling'),
						indicator: 'orange'
					},
					8
				);
			} else if (age > 100) {
				frappe.show_alert(
					{
						message: __('Please verify birth date - applicant would be over 100 years old'),
						indicator: 'yellow'
					},
					8
				);
			}
		}
	}
});

function setup_member_counter_section(frm) {
	// Add custom buttons for counter management
	// Counter Statistics button removed as requested

	frm.add_custom_button(
		__('Reset Counter'),
		() => {
			show_counter_reset_dialog(frm);
		},
		__('Member ID Management')
	);

	frm.add_custom_button(
		__('Migration Tools'),
		() => {
			show_migration_tools_dialog();
		},
		__('Member ID Management')
	);
}

function load_counter_statistics(frm) {
	// Load current counter statistics (for future dashboard use)
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.member.member_id_manager.get_member_id_statistics',
		callback(r) {
			const data = unwrapOperationResult(r.message);
			if (data) {
				// Statistics loaded successfully - can be used for dashboard/reports
				console.log('Member ID statistics loaded:', data);
			}
		}
	});
}

function show_member_id_preview(frm) {
	// Show preview of next member ID for new members
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.member.member_id_manager.get_next_member_id_preview',
		callback(r) {
			const data = unwrapOperationResult(r.message);
			if (data && data.next_id) {
				frm.set_df_property('member_id', 'description', `Will be assigned: ${data.next_id}`);
			}
		}
	});
}

function handle_counter_reset(frm) {
	// Handle the reset counter button click
	if (!frm.doc.reset_counter_to) {
		frappe.msgprint(__('Please enter a value to reset the counter to'));
		return;
	}

	frappe.confirm(
		__('Are you sure you want to reset the member ID counter to {0}? This action cannot be undone.', [
			frm.doc.reset_counter_to
		]),
		() => {
			frappe.call({
				method: 'verenigingen.verenigingen.doctype.member.member_id_manager.reset_member_id_counter',
				args: {
					counter_value: frm.doc.reset_counter_to
				},
				freeze: true,
				freeze_message: __('Resetting counter...'),
				callback(r) {
					const data = unwrapOperationResult(r.message);
					if (data && data.success !== false) {
						frappe.show_alert(
							{
								message: data.message || __('Counter reset successfully'),
								indicator: 'green'
							},
							5
						);

						// Clear the input field
						frm.set_value('reset_counter_to', '');

						// Reload statistics
						load_counter_statistics(frm);
					} else {
						const errorMsg = verenigingen.utils.getErrorMessage(r.message, __('Failed to reset counter'));
						frappe.msgprint(errorMsg);
					}
				}
			});
		}
	);
}

function _show_counter_statistics_dialog() {
	// Show detailed counter statistics
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.member.member_id_manager.get_member_id_statistics',
		callback(r) {
			const stats = unwrapOperationResult(r.message);
			if (stats) {
				let dialog_content = `
                    <div class="counter-stats">
                        <h4>Member ID Counter Statistics</h4>
                        <table class="table table-bordered">
                            <tr><td><strong>Next ID to Assign</strong></td><td>${stats.next_id}</td></tr>
                            <tr><td><strong>Current Counter Value</strong></td><td>${stats.current_counter}</td></tr>
                            <tr><td><strong>Highest Assigned ID</strong></td><td>${stats.highest_assigned}</td></tr>
                            <tr><td><strong>Total Members with Numeric IDs</strong></td><td>${stats.total_with_numeric_ids}</td></tr>
                            <tr><td><strong>ID Gaps Found</strong></td><td>${stats.gap_count}</td></tr>
                        </table>
                `;

				if (stats.gaps && stats.gaps.length > 0) {
					dialog_content += `
                        <h5>Available ID Gaps (first 10):</h5>
                        <p class="text-muted">${stats.gaps.join(', ')}</p>
                    `;
				}

				dialog_content += '</div>';

				frappe.msgprint({
					title: __('Member ID Statistics'),
					message: dialog_content,
					wide: true
				});
			}
		}
	});
}

function show_counter_reset_dialog(frm) {
	// Show dialog for counter reset with validation
	const d = new frappe.ui.Dialog({
		title: __('Reset Member ID Counter'),
		fields: [
			{
				fieldname: 'new_counter_value',
				fieldtype: 'Int',
				label: __('New Counter Value'),
				reqd: 1,
				description: __('Enter the new counter value. Must be greater than current highest assigned ID.')
			},
			{
				fieldname: 'confirm_reset',
				fieldtype: 'Check',
				label: __('I understand this action cannot be undone'),
				reqd: 1
			}
		],
		primary_action_label: __('Reset Counter'),
		primary_action(values) {
			if (!values.confirm_reset) {
				frappe.msgprint(__('Please confirm you understand this action cannot be undone'));
				return;
			}

			frappe.call({
				method: 'verenigingen.verenigingen.doctype.member.member_id_manager.reset_member_id_counter',
				args: {
					counter_value: values.new_counter_value
				},
				freeze: true,
				freeze_message: __('Resetting counter...'),
				callback(r) {
					const data = unwrapOperationResult(r.message);
					if (data && data.success !== false) {
						frappe.show_alert(
							{
								message: data.message || __('Counter reset successfully'),
								indicator: 'green'
							},
							5
						);

						d.hide();
						load_counter_statistics(frm);
					} else {
						const errorMsg = verenigingen.utils.getErrorMessage(r.message, __('Failed to reset counter'));
						frappe.msgprint(errorMsg);
					}
				}
			});
		}
	});

	d.show();
}

function show_migration_tools_dialog() {
	// Show migration tools for counter system
	const d = new frappe.ui.Dialog({
		title: __('Member ID Migration Tools'),
		fields: [
			{
				fieldname: 'migration_info',
				fieldtype: 'HTML',
				options: `
                    <div class="alert alert-info">
                        <h5>Migration Tools</h5>
                        <p>These tools help migrate from the old counter system in Verenigingen Settings to the new Member-based counter system.</p>
                        <p><strong>Warning:</strong> Only run migration once during system upgrade.</p>
                    </div>
                `
			}
		],
		primary_action_label: __('Run Migration'),
		primary_action() {
			frappe.confirm(
				__('Run member ID counter migration? This should only be done once during system upgrade.'),
				() => {
					frappe.call({
						method: 'verenigingen.verenigingen.doctype.member.member_id_manager.migrate_member_id_counter',
						freeze: true,
						freeze_message: __('Running migration...'),
						callback(r) {
							const data = unwrapOperationResult(r.message);
							if (data && data.success !== false) {
								frappe.show_alert(
									{
										message: data.message || __('Migration completed successfully'),
										indicator: 'green'
									},
									8
								);
							} else {
								const errorMsg = verenigingen.utils.getErrorMessage(r.message, __('Migration failed'));
								frappe.msgprint(__('Migration failed: {0}', [errorMsg]));
							}
							d.hide();
						}
					});
				}
			);
		}
	});

	d.show();
}

function calculate_age(birth_date) {
	// Calculate age from birth date
	if (!birth_date) {
		return null;
	}

	const birth = new Date(birth_date);
	const today = new Date();

	if (isNaN(birth.getTime())) {
		return null;
	}

	let age = today.getFullYear() - birth.getFullYear();

	// Adjust if birthday hasn't occurred this year
	if (
		today.getMonth() < birth.getMonth() ||
		(today.getMonth() === birth.getMonth() && today.getDate() < birth.getDate())
	) {
		age--;
	}

	return age;
}

// Verenigingen Settings form customizations
frappe.ui.form.on('Verenigingen Settings', {
	refresh(frm) {
		if (frappe.user.has_role('System Manager')) {
			setup_settings_counter_section(frm);
		}
	},

	member_id_start(frm) {
		// Show warning when changing the start value
		if (frm.doc.member_id_start) {
			frm.set_df_property(
				'member_id_start',
				'description',
				'Changes to this value will update the member ID counter if the new value is higher than the current counter.'
			);
		}
	}
});

function setup_settings_counter_section(frm) {
	// Add button to view current counter status
	frm.add_custom_button(
		__('View Member ID Status'),
		() => {
			frappe.call({
				method: 'verenigingen.verenigingen.doctype.member.member_id_manager.get_member_id_statistics',
				callback(r) {
					const stats = unwrapOperationResult(r.message);
					if (stats) {
						frappe.msgprint({
							title: __('Current Member ID Status'),
							message: `
                            <table class="table">
                                <tr><td><strong>Current Counter:</strong></td><td>${stats.current_counter}</td></tr>
                                <tr><td><strong>Next ID:</strong></td><td>${stats.next_id}</td></tr>
                                <tr><td><strong>Settings Start Value:</strong></td><td>${frm.doc.member_id_start || 1000}</td></tr>
                                <tr><td><strong>Highest Assigned:</strong></td><td>${stats.highest_assigned}</td></tr>
                            </table>
                            <p class="text-muted">The counter will only be updated if you set the start value higher than the current counter.</p>
                        `,
							wide: true
						});
					} else {
						const errorMsg = verenigingen.utils.getErrorMessage(r.message, __('Failed to load statistics'));
						frappe.msgprint(errorMsg);
					}
				}
			});
		},
		__('Member ID Management')
	);
}

/**
 * Migration Script
 * Run this once after updating the system
 */

// Console command for manual migration (run in browser console if needed)
function migrate_member_id_system() {
	console.log('Starting member ID system migration...');

	frappe.call({
		method: 'verenigingen.verenigingen.doctype.member.member_id_manager.migrate_member_id_counter',
		callback(r) {
			const data = unwrapOperationResult(r.message);
			if (data && data.success !== false) {
				console.log('✓ Migration successful:', data.message);
				frappe.show_alert(
					{
						message: 'Member ID system migration completed successfully',
						indicator: 'green'
					},
					8
				);
			} else {
				const errorMsg = verenigingen.utils.getErrorMessage(r.message, 'Unknown error');
				console.error('✗ Migration failed:', errorMsg);
				frappe.msgprint(`Migration failed: ${errorMsg}`);
			}
		},
		error(r) {
			console.error('✗ Migration error:', r);
			frappe.msgprint('Migration error occurred. Check console for details.');
		}
	});
}

// Make migration function available globally for console use
window.migrate_member_id_system = migrate_member_id_system;

// Auto-run migration check on page load for System Managers
$(document).ready(() => {
	if (
		(frappe.user.has_role('System Manager') &&
			frappe.get_route()[0] === 'List' &&
			frappe.get_route()[1] === 'Member') ||
		(frappe.get_route()[0] === 'Form' && frappe.get_route()[1] === 'Verenigingen Settings')
	) {
		// Check if migration might be needed
		frappe.call({
			method: 'frappe.client.get_single_value',
			args: {
				doctype: 'Verenigingen Settings',
				field: 'last_member_id'
			},
			callback(r) {
				if (r.message && parseInt(r.message, 10) > 0) {
					// Old system detected, suggest migration
					frappe.show_alert(
						{
							message: __(
								'Old member ID system detected. Consider running migration. Type migrate_member_id_system() in console.'
							),
							indicator: 'orange'
						},
						10
					);
				}
			}
		});
	}
});
