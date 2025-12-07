/**
 * @fileoverview Member List View customizations with comprehensive status management
 *
 * Provides advanced list view customizations for the Member DocType, featuring
 * sophisticated status tracking, application lifecycle management, and enhanced
 * filtering capabilities. This configuration transforms the default list view
 * into a powerful member management dashboard.
 *
 * Key Features:
 * - Dual status tracking (member status + application status)
 * - Visual status indicators with emojis and color coding
 * - Advanced filtering for new members and status changes
 * - Automatic status synchronization tools
 * - Quick access to member reports and analytics
 * - Application review workflow integration
 * - Chapter assignment change tracking
 *
 * Status Management:
 * - Application status tracking for frontend applications
 * - Member status management for backend members
 * - Visual distinction between application and member records
 * - Automated status synchronization tools
 * - Recent activity highlighting (7-day and 30-day markers)
 * - Chapter assignment change detection
 *
 * Business Context:
 * Essential for membership administrators managing the complete member lifecycle
 * from application through active membership to termination. Provides clear
 * visibility into pending applications, new member onboarding progress,
 * and member status changes for effective membership management.
 *
 * Integration:
 * - Connects to Member and Membership Application DocTypes
 * - Integrates with application review workflows
 * - Links to member analytics and reporting
 * - Supports chapter assignment management
 * - Enables bulk member operations and status fixes
 *
 * @author Verenigingen Development Team
 * @version 2.8.0
 * @since 2024-09-15
 */

// Copyright (c) 2025, Your Name and contributors
// For license information, please see license.txt

frappe.listview_settings['Member'] = {
	// ==================== LIST VIEW CONFIGURATION ====================

	// Add fields needed for new member tracking
	add_fields: [
		'status',
		'chapter_assigned_date',
		'creation',
		'application_id',
		'application_status'
	],

	// Auto refresh when data changes
	refresh(listview) {
		// Force refresh of list view data to show updated statuses
		if (listview && listview.refresh) {
			listview.refresh();
		}

		// Add quick filter buttons for new members
		add_new_member_filter_buttons(listview);
	},

	// ==================== STATUS INDICATORS ====================

	get_indicator(doc) {
		// Check if this is an application-created member
		const is_application_member = !!doc.application_id;

		// Check if member is new (created within last 30 days)
		const thirtyDaysAgo = frappe.datetime.add_days(
			frappe.datetime.nowdate(),
			-30
		);
		const sevenDaysAgo = frappe.datetime.add_days(
			frappe.datetime.nowdate(),
			-7
		);
		const creationDate = doc.creation ? doc.creation.split(' ')[0] : null;

		// Check for recent chapter changes
		let hasRecentChapterChange = false;
		if (doc.chapter_assigned_date) {
			const assignDate = doc.chapter_assigned_date.split(' ')[0];
			hasRecentChapterChange = assignDate >= thirtyDaysAgo;
		}

		// Priority indicators for new members and chapter changes
		if (doc.status === 'Active') {
			if (creationDate && creationDate >= sevenDaysAgo) {
				return ['green', 'Very New Member (≤7 days)', 'status,=,Active'];
			} else if (creationDate && creationDate >= thirtyDaysAgo) {
				return ['blue', 'New Member (≤30 days)', 'status,=,Active'];
			} else if (hasRecentChapterChange) {
				return ['orange', 'Recent Chapter Change', 'status,=,Active'];
			}
		}

		// Primary status based on member status field
		const status_indicators = {
			Pending: [
				'yellow',
				is_application_member ? 'Pending Application' : 'Pending Member'
			],
			Active: ['green', 'Active Member'],
			Rejected: ['red', 'Application Rejected'],
			Expired: ['orange', 'Membership Expired'],
			Suspended: ['dark grey', 'Account Suspended'],
			Banned: ['purple', 'Permanently Banned'],
			Deceased: ['purple', 'Deceased'],
			Terminated: ['red', 'Membership Terminated']
		};

		// Get indicator for main status
		let indicator = status_indicators[doc.status] || [
			'grey',
			doc.status || 'Unknown'
		];

		// Only override with application status for application-created members
		if (
			is_application_member
      && doc.application_status
      && doc.application_status !== 'Active'
		) {
			const app_status_indicators = {
				Pending: ['yellow', 'Application Pending Review'],
				'Under Review': ['blue', 'Under Review'],
				Approved: ['light-blue', 'Approved - Awaiting Payment'],
				Rejected: ['red', 'Application Rejected'],
				'Payment Failed': ['orange', 'Payment Failed'],
				'Payment Cancelled': ['grey', 'Payment Cancelled'],
				'Payment Pending': ['orange', 'Payment Pending']
			};

			indicator = app_status_indicators[doc.application_status] || indicator;
		}

		return indicator;
	},

	// ==================== CUSTOM FORMATTING ====================

	formatters: {
		// Format application status with emoji indicators
		application_status(value, field, doc) {
			if (!value) {
				return '';
			}

			const status_emojis = {
				Pending: '⏳',
				'Under Review': '👀',
				Approved: '✅',
				Active: '🟢',
				Rejected: '❌',
				'Payment Failed': '💳',
				'Payment Cancelled': '⚫',
				'Payment Pending': '⏰'
			};

			const emoji = status_emojis[value] || '';
			return emoji ? `${emoji} ${value}` : value;
		},

		// Format main status with emoji indicators
		status(value, field, doc) {
			if (!value) {
				return '';
			}

			const status_emojis = {
				Pending: '⏳',
				Active: '✅',
				Rejected: '❌',
				Expired: '⏰',
				Suspended: '⏸️',
				Banned: '🚫',
				Deceased: '†'
			};

			const emoji = status_emojis[value] || '';
			return emoji ? `${emoji} ${value}` : value;
		},

		// Format member name with status context
		full_name(value, field, doc) {
			if (!value) {
				return value;
			}

			// Only show application status indicators for application-created members
			const is_application_member = !!doc.application_id;

			if (
				is_application_member
        && doc.application_status
        && doc.application_status !== 'Active'
			) {
				const status_badges = {
					Pending: '🟡',
					'Under Review': '🔵',
					Approved: '🟢',
					Rejected: '🔴',
					'Payment Failed': '🟠',
					'Payment Cancelled': '⚫',
					'Payment Pending': '🟠'
				};

				const badge_emoji = status_badges[doc.application_status] || '⚪';
				return `${value} ${badge_emoji}`;
			}

			// For backend-created members, show member status if not Active
			if (!is_application_member && doc.status && doc.status !== 'Active') {
				const member_status_badges = {
					Pending: '⏳',
					Expired: '⏰',
					Suspended: '⏸️',
					Banned: '🚫',
					Deceased: '†'
				};

				const badge_emoji = member_status_badges[doc.status] || '';
				return badge_emoji ? `${value} ${badge_emoji}` : value;
			}

			return value;
		}
	},

	// ==================== CUSTOM ACTIONS ====================

	onload(listview) {
		// Add custom CSS for better status visualization
		if (!$('#member-list-custom-css').length) {
			$('head').append(`
                <style id="member-list-custom-css">
                    .list-row-container[data-doctype="Member"] {
                        border-left: 3px solid transparent;
                    }

                    /* Status-based row coloring */
                    .list-row-container[data-doctype="Member"][data-name*="Pending"] {
                        border-left-color: #ffc107;
                        background-color: rgba(255, 193, 7, 0.05);
                    }

                    .list-row-container[data-doctype="Member"][data-name*="Active"] {
                        border-left-color: #28a745;
                        background-color: rgba(40, 167, 69, 0.05);
                    }

                    .list-row-container[data-doctype="Member"][data-name*="Rejected"] {
                        border-left-color: #dc3545;
                        background-color: rgba(220, 53, 69, 0.05);
                    }

                    .list-row-container[data-doctype="Member"][data-name*="Expired"] {
                        border-left-color: #fd7e14;
                        background-color: rgba(253, 126, 20, 0.05);
                    }

                    .list-row-container[data-doctype="Member"][data-name*="Suspended"] {
                        border-left-color: #6c757d;
                        background-color: rgba(108, 117, 125, 0.05);
                    }

                    /* Application status indicators */
                    .text-warning { color: #856404 !important; }
                    .text-success { color: #155724 !important; }
                    .text-danger { color: #721c24 !important; }
                    .text-info { color: #0c5460 !important; }
                    .text-primary { color: #004085 !important; }
                    .text-muted { color: #6c757d !important; }
                    .text-dark { color: #1d2124 !important; }
                    .text-secondary { color: #383d41 !important; }

                    /* Badge styling */
                    .badge {
                        font-size: 0.7em;
                        padding: 0.2em 0.4em;
                    }
                </style>
            `);
		}

		// Add refresh button for manual status sync
		listview.page.add_menu_item(__('Refresh Status'), () => {
			frappe.call({
				method:
          'verenigingen.api.membership_application_review.sync_member_statuses',
				callback(r) {
					if (r.message) {
						frappe.show_alert(
							{
								message: __('Member statuses synchronized'),
								indicator: 'green'
							},
							3
						);
						listview.refresh();
					}
				}
			});
		});

		// Add fix for backend members showing as pending
		if (
			frappe.user.has_role(['System Manager', 'Verenigingen Administrator'])
		) {
			listview.page.add_menu_item(__('Fix Backend Member Status'), () => {
				frappe.confirm(
					__(
						'This will fix backend-created members that are incorrectly showing as "Pending". Continue?'
					),
					() => {
						frappe.show_alert(__('Fixing backend member statuses...'), 2);

						frappe.call({
							method:
                'verenigingen.api.membership_application_review.fix_backend_member_statuses',
							callback(r) {
								if (r.message && r.message.success) {
									frappe.show_alert(
										{
											message: r.message.message,
											indicator: 'green'
										},
										5
									);
									listview.refresh();
								} else {
									frappe.show_alert(
										{
											message: __(
												'Error: Please run manually: bench execute verenigingen.manual_fix.fix_backend_members_now'
											),
											indicator: 'red'
										},
										8
									);
								}
							},
							error(err) {
								console.error('Fix backend members error:', err);
								frappe.show_alert(
									{
										message: __(
											'Error occurred. Please run manually: bench execute verenigingen.manual_fix.fix_backend_members_now'
										),
										indicator: 'red'
									},
									8
								);
							}
						});
					}
				);
			});
		}

		// Add application status filter buttons
		add_status_filter_buttons(listview);

		// Add merge members action
		add_merge_members_action(listview);
	},

	// ==================== BUTTON CONFIGURATIONS ====================

	button: {
		show(doc) {
			// Only show for members with application_id (created through application process)
			// and have pending status
			return doc.application_id && doc.application_status === 'Pending';
		},
		get_label(doc) {
			if (doc.application_id && doc.application_status === 'Pending') {
				return __('Review Application');
			}
			return __('View');
		},
		get_description(doc) {
			if (doc.application_id && doc.application_status === 'Pending') {
				return __('Review and approve/reject this application');
			}
			return __('View member details');
		},
		action(doc) {
			// Open form for review
			frappe.set_route('Form', 'Member', doc.name);
		}
	}
};

// ==================== HELPER FUNCTIONS ====================

function add_status_filter_buttons(listview) {
	// Add quick filter buttons for common statuses
	const status_filters = [
		{
			label: __('Pending Applications'),
			filter: { application_status: 'Pending' },
			color: 'orange'
		},
		{
			label: __('Active Members'),
			filter: { status: 'Active' },
			color: 'green'
		},
		{
			label: __('Rejected Applications'),
			filter: { application_status: 'Rejected' },
			color: 'red'
		},
		{
			label: __('Payment Pending'),
			filter: { application_status: 'Payment Pending' },
			color: 'yellow'
		}
	];

	status_filters.forEach((status_filter) => {
		listview.page.add_action_item(status_filter.label, () => {
			// Clear existing filters
			listview.filter_area.clear();

			// Apply new filter
			Object.keys(status_filter.filter).forEach((key) => {
				listview.filter_area.add(key, '=', status_filter.filter[key]);
			});

			listview.refresh();
		});
	});
}

function add_new_member_filter_buttons(listview) {
	// Only add buttons once
	if (listview.$new_member_filters_added) {
		return;
	}
	listview.$new_member_filters_added = true;

	// Add quick filter buttons for new members
	const thirtyDaysAgo = frappe.datetime.add_days(
		frappe.datetime.nowdate(),
		-30
	);
	const sevenDaysAgo = frappe.datetime.add_days(frappe.datetime.nowdate(), -7);

	// Create filter button container
	const $filter_buttons = $(`
        <div class="new-member-filters" style="margin-bottom: 15px; padding: 10px; background: #f8f9fa; border-radius: 6px;">
            <div class="row">
                <div class="col-md-12">
                    <label style="font-weight: bold; margin-right: 15px; color: #495057;">Quick Filters:</label>
                    <button class="btn btn-sm btn-success" data-filter="new-7" style="margin-right: 8px;">
                        <i class="fa fa-star"></i> Very New (7d)
                    </button>
                    <button class="btn btn-sm btn-primary" data-filter="new-30" style="margin-right: 8px;">
                        <i class="fa fa-user-plus"></i> New (30d)
                    </button>
                    <button class="btn btn-sm btn-info" data-filter="chapter-changes" style="margin-right: 8px;">
                        <i class="fa fa-exchange"></i> Chapter Changes
                    </button>
                    <button class="btn btn-sm btn-warning" data-filter="no-chapter" style="margin-right: 8px;">
                        <i class="fa fa-question-circle"></i> No Chapter
                    </button>
                    <button class="btn btn-sm btn-secondary" data-filter="clear">
                        <i class="fa fa-times"></i> Clear
                    </button>
                </div>
            </div>
        </div>
    `);

	// Insert after the filter area
	listview.$frappe_list.find('.filter-area').after($filter_buttons);

	// Bind click events
	$filter_buttons.on('click', 'button', function () {
		const filter = $(this).data('filter');

		listview.filter_area.clear();

		switch (filter) {
			case 'new-7':
				listview.filter_area.add([
					['Member', 'status', '=', 'Active'],
					['Member', 'creation', '>=', sevenDaysAgo]
				]);
				break;
			case 'new-30':
				listview.filter_area.add([
					['Member', 'status', '=', 'Active'],
					['Member', 'creation', '>=', thirtyDaysAgo]
				]);
				break;
			case 'chapter-changes':
				listview.filter_area.add([
					['Member', 'chapter_assigned_date', '>=', thirtyDaysAgo]
				]);
				break;
			case 'no-chapter':
				// Filter for members without chapters - this will need to be handled differently
				// since we now use Chapter Member child table
				frappe.msgprint({
					title: __('Filter Info'),
					message: __(
						'To see members without chapters, please use the "Members Without Chapter" report.'
					),
					indicator: 'blue'
				});
				break;
			case 'clear':
				// Clear all filters
				break;
		}

		// Highlight active button
		$filter_buttons.find('button').removeClass('btn-outline-secondary');
		if (filter !== 'clear') {
			$(this).addClass('btn-outline-secondary');
		}

		listview.refresh();
	});

	// Add menu items for reports
	listview.page.add_menu_item(__('📊 New Members Report'), () => {
		frappe.set_route('query-report', 'New Members');
	});

	listview.page.add_menu_item(__('📊 Recent Chapter Changes Report'), () => {
		frappe.set_route('query-report', 'Recent Chapter Changes');
	});

	listview.page.add_menu_item(__('📊 Members Without Chapter Report'), () => {
		frappe.set_route('query-report', 'Members Without Chapter');
	});
}

function add_merge_members_action(listview) {
	// Add bulk action for merging members
	listview.page.add_action_item(__('Merge Members'), () => {
		const selected = listview.get_checked_items();

		if (selected.length < 2) {
			frappe.msgprint({
				title: __('Selection Required'),
				message: __('Please select at least 2 members to merge.'),
				indicator: 'orange'
			});
			return;
		}

		if (selected.length > 2) {
			// Let user pick which 2
			show_member_selection_dialog(selected, (source, target) => {
				show_merge_dialog(source, target, listview);
			});
		} else {
			// Exactly 2 selected - ask which is source/target
			const [first, second] = selected;
			show_source_target_picker(first.name, second.name, listview);
		}
	});
}

function show_source_target_picker(first_name, second_name, listview) {
	const dialog = new frappe.ui.Dialog({
		title: __('Select Source and Target'),
		fields: [
			{
				fieldtype: 'HTML',
				options: `
					<p class="text-muted">
						<strong>Target:</strong> The member record to KEEP (will receive merged data)<br>
						<strong>Source:</strong> The member record to DELETE (after extracting data)
					</p>
				`
			},
			{
				fieldname: 'target',
				label: __('Target (Keep This Record)'),
				fieldtype: 'Link',
				options: 'Member',
				reqd: 1,
				default: first_name,
				get_query: () => ({
					filters: { name: ['in', [first_name, second_name]] }
				})
			},
			{
				fieldname: 'source',
				label: __('Source (Delete After Merge)'),
				fieldtype: 'Link',
				options: 'Member',
				reqd: 1,
				default: second_name,
				get_query: () => ({
					filters: { name: ['in', [first_name, second_name]] }
				})
			}
		],
		primary_action_label: __('Continue'),
		primary_action(values) {
			if (values.source === values.target) {
				frappe.msgprint(__('Source and target must be different members'));
				return;
			}
			dialog.hide();
			show_merge_dialog(values.source, values.target, listview);
		}
	});

	dialog.show();
}

function show_member_selection_dialog(members, callback) {
	const member_options = members.map(m => m.name).join('\n');

	const dialog = new frappe.ui.Dialog({
		title: __('Select Members to Merge'),
		fields: [
			{
				fieldname: 'source',
				label: __('Source (Delete After Merge)'),
				fieldtype: 'Select',
				options: member_options,
				reqd: 1
			},
			{
				fieldname: 'target',
				label: __('Target (Keep This Record)'),
				fieldtype: 'Select',
				options: member_options,
				reqd: 1
			}
		],
		primary_action_label: __('Continue'),
		primary_action(values) {
			if (values.source === values.target) {
				frappe.msgprint(__('Source and target must be different members'));
				return;
			}
			dialog.hide();
			callback(values.source, values.target);
		}
	});

	dialog.show();
}

function show_merge_dialog(source_name, target_name, listview) {
	// Show loading indicator
	frappe.show_alert(__('Loading merge preview...'), 2);

	// Get merge preview from backend
	frappe.call({
		method: 'verenigingen.services.member_merge_service.get_merge_preview',
		args: {
			source_name: source_name,
			target_name: target_name
		},
		callback(r) {
			if (r.message && r.message.success) {
				render_merge_dialog(r.message.data, listview);
			} else if (r.message && !r.message.success) {
				frappe.msgprint({
					title: __('Error'),
					message: r.message.error_message || __('Failed to load merge preview'),
					indicator: 'red'
				});
			}
		},
		error(err) {
			frappe.msgprint({
				title: __('Error'),
				message: __('Failed to load merge preview: {0}', [err.message || 'Unknown error']),
				indicator: 'red'
			});
		}
	});
}

function render_merge_dialog(preview, listview) {
	const { source, target, fields, warnings } = preview;

	// Build warnings HTML
	let warnings_html = '';
	if (warnings && warnings.length > 0) {
		warnings_html = `
			<div class="alert alert-warning" style="margin-bottom: 15px;">
				<strong>⚠️ Important Warnings:</strong>
				<ul style="margin-bottom: 0; margin-top: 8px;">
					${warnings.map(w => `<li>${w}</li>`).join('')}
				</ul>
			</div>
		`;
	}

	// Build field selection HTML
	const fields_html = fields.map(field => {
		// Format display values with context
		const format_value = (value, fieldname) => {
			if (!value) return '<em>(empty)</em>';

			// Add age display for birth_date
			if (fieldname === 'birth_date' && value) {
				const age = frappe.datetime.get_age(value);
				return `${frappe.datetime.str_to_user(value)} <span style="color: #6c757d; font-size: 0.9em;">(age ${age})</span>`;
			}

			return value;
		};

		const source_display = format_value(field.source_value, field.fieldname);
		const target_display = format_value(field.target_value, field.fieldname);
		const has_conflict = field.has_conflict;
		const suggested = field.suggested || 'target';

		return `
			<div class="merge-field-row" style="margin-bottom: 12px; padding: 10px; background: ${has_conflict ? '#fff3cd' : '#f8f9fa'}; border-radius: 4px; border-left: 3px solid ${has_conflict ? '#ffc107' : '#e9ecef'};">
				<div style="margin-bottom: 6px;">
					<strong>${field.label}</strong>
					${has_conflict ? '<span class="badge badge-warning" style="margin-left: 8px;">Conflict</span>' : ''}
				</div>
				<div style="display: flex; gap: 15px; align-items: center;">
					<label style="flex: 1; margin: 0; cursor: pointer; padding: 8px; background: white; border: 1px solid #dee2e6; border-radius: 4px;">
						<input type="radio" name="field_${field.fieldname}" value="source" ${suggested === 'source' ? 'checked' : ''} style="margin-right: 8px;">
						<span style="color: #6c757d;">Source:</span> ${source_display}
					</label>
					<label style="flex: 1; margin: 0; cursor: pointer; padding: 8px; background: white; border: 1px solid #dee2e6; border-radius: 4px;">
						<input type="radio" name="field_${field.fieldname}" value="target" ${suggested === 'target' ? 'checked' : ''} style="margin-right: 8px;">
						<span style="color: #6c757d;">Target:</span> ${target_display}
					</label>
				</div>
			</div>
		`;
	}).join('');

	const dialog = new frappe.ui.Dialog({
		title: __('Merge Members'),
		size: 'large',
		fields: [
			{
				fieldtype: 'HTML',
				options: `
					<div style="margin-bottom: 20px;">
						<h5>Merging Records</h5>
						<div style="display: flex; gap: 20px; margin-top: 10px;">
							<div style="flex: 1; padding: 12px; background: #fff3cd; border-radius: 6px;">
								<strong>🗑️ Source (Will be Deleted)</strong><br>
								<code>${source.name}</code><br>
								${source.full_name}<br>
								<small>${source.email || ''}</small>
							</div>
							<div style="flex: 1; padding: 12px; background: #d4edda; border-radius: 6px;">
								<strong>✅ Target (Will be Kept)</strong><br>
								<code>${target.name}</code><br>
								${target.full_name}<br>
								<small>${target.email || ''}</small>
							</div>
						</div>
					</div>

					${warnings_html}

					<div style="margin-bottom: 15px;">
						<h6>Select Which Data to Keep for Each Field</h6>
						<p class="text-muted" style="font-size: 0.9em;">
							Fields with conflicts are highlighted. Smart defaults are pre-selected.
						</p>
					</div>

					<div id="merge-fields-container" style="max-height: 400px; overflow-y: auto;">
						${fields_html}
					</div>

					<div class="alert alert-info" style="margin-top: 15px; margin-bottom: 0;">
						<strong>Note:</strong> Financial data, volunteer records, and ERPNext links will NOT be merged.
						They will remain on their original records.
					</div>
				`
			}
		],
		primary_action_label: __('Merge Members'),
		primary_action() {
			// Collect field selections
			const field_selections = {};
			fields.forEach(field => {
				const selected_radio = dialog.$wrapper.find(`input[name="field_${field.fieldname}"]:checked`);
				if (selected_radio.length) {
					field_selections[field.fieldname] = selected_radio.val();
				}
			});

			// Confirm before proceeding
			frappe.confirm(
				__('Are you sure you want to merge these members? This action cannot be undone. The source member ({0}) will be DELETED.', [source.name]),
				() => {
					dialog.hide();
					execute_merge(source.name, target.name, field_selections, listview);
				}
			);
		},
		secondary_action_label: __('Cancel')
	});

	dialog.show();
}

function execute_merge(source_name, target_name, field_selections, listview) {
	frappe.show_alert(__('Merging members...'), 3);

	frappe.call({
		method: 'verenigingen.services.member_merge_service.execute_merge',
		args: {
			source_name: source_name,
			target_name: target_name,
			field_selections: JSON.stringify(field_selections)
		},
		freeze: true,
		freeze_message: __('Merging members, please wait...'),
		callback(r) {
			if (r.message && r.message.success) {
				const result = r.message.data;
				frappe.show_alert({
					message: __('Members merged successfully! {0} changes applied.', [result.changes_applied]),
					indicator: 'green'
				}, 5);

				// Refresh list view
				listview.refresh();

				// Open the merged member
				frappe.set_route('Form', 'Member', result.merged_member);
			} else if (r.message && !r.message.success) {
				frappe.msgprint({
					title: __('Merge Failed'),
					message: r.message.error_message || __('Failed to merge members'),
					indicator: 'red'
				});
			}
		},
		error(err) {
			frappe.msgprint({
				title: __('Merge Failed'),
				message: __('Failed to merge members: {0}', [err.message || 'Unknown error']),
				indicator: 'red'
			});
		}
	});
}
