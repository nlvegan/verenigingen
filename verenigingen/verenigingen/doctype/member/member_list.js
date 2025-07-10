// Copyright (c) 2025, Your Name and contributors
// For license information, please see license.txt

frappe.listview_settings['Member'] = {

	// ==================== LIST VIEW CONFIGURATION ====================

	// Add fields needed for new member tracking
	add_fields: ['status', 'chapter_assigned_date', 'creation', 'application_id', 'application_status'],

	// Auto refresh when data changes
	refresh: function(listview) {
		// Force refresh of list view data to show updated statuses
		if (listview && listview.refresh) {
			listview.refresh();
		}

		// Add quick filter buttons for new members
		add_new_member_filter_buttons(listview);
	},

	// ==================== STATUS INDICATORS ====================

	get_indicator: function(doc) {
		// Check if this is an application-created member
		const is_application_member = !!doc.application_id;

		// Check if member is new (created within last 30 days)
		const thirtyDaysAgo = frappe.datetime.add_days(frappe.datetime.nowdate(), -30);
		const sevenDaysAgo = frappe.datetime.add_days(frappe.datetime.nowdate(), -7);
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
			'Pending': ['yellow', is_application_member ? 'Pending Application' : 'Pending Member'],
			'Active': ['green', 'Active Member'],
			'Rejected': ['red', 'Application Rejected'],
			'Expired': ['orange', 'Membership Expired'],
			'Suspended': ['dark grey', 'Account Suspended'],
			'Banned': ['black', 'Permanently Banned'],
			'Deceased': ['purple', 'Deceased'],
			'Terminated': ['red', 'Membership Terminated']
		};

		// Get indicator for main status
		let indicator = status_indicators[doc.status] || ['grey', doc.status || 'Unknown'];

		// Only override with application status for application-created members
		if (is_application_member && doc.application_status && doc.application_status !== 'Active') {
			const app_status_indicators = {
				'Pending': ['yellow', 'Application Pending Review'],
				'Under Review': ['blue', 'Under Review'],
				'Approved': ['light-blue', 'Approved - Awaiting Payment'],
				'Rejected': ['red', 'Application Rejected'],
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
		application_status: function(value, field, doc) {
			if (!value) return '';

			const status_emojis = {
				'Pending': '⏳',
				'Under Review': '👀',
				'Approved': '✅',
				'Active': '🟢',
				'Rejected': '❌',
				'Payment Failed': '💳',
				'Payment Cancelled': '⚫',
				'Payment Pending': '⏰'
			};

			const emoji = status_emojis[value] || '';
			return emoji ? `${emoji} ${value}` : value;
		},

		// Format main status with emoji indicators
		status: function(value, field, doc) {
			if (!value) return '';

			const status_emojis = {
				'Pending': '⏳',
				'Active': '✅',
				'Rejected': '❌',
				'Expired': '⏰',
				'Suspended': '⏸️',
				'Banned': '🚫',
				'Deceased': '🕊️',
				'Terminated': '🔴'
			};

			const emoji = status_emojis[value] || '';
			return emoji ? `${emoji} ${value}` : value;
		},

		// Format member name with status context
		full_name: function(value, field, doc) {
			if (!value) return value;

			// Only show application status indicators for application-created members
			const is_application_member = !!doc.application_id;

			if (is_application_member && doc.application_status && doc.application_status !== 'Active') {
				const status_badges = {
					'Pending': '🟡',
					'Under Review': '🔵',
					'Approved': '🟢',
					'Rejected': '🔴',
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
					'Pending': '⏳',
					'Expired': '⏰',
					'Suspended': '⏸️',
					'Banned': '🚫',
					'Deceased': '🕊️',
					'Terminated': '🔴'
				};

				const badge_emoji = member_status_badges[doc.status] || '';
				return badge_emoji ? `${value} ${badge_emoji}` : value;
			}

			return value;
		}
	},

	// ==================== CUSTOM ACTIONS ====================

	onload: function(listview) {
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
		listview.page.add_menu_item(__('Refresh Status'), function() {
			frappe.call({
				method: 'verenigingen.api.membership_application_review.sync_member_statuses',
				callback: function(r) {
					if (r.message) {
						frappe.show_alert({
							message: __('Member statuses synchronized'),
							indicator: 'green'
						}, 3);
						listview.refresh();
					}
				}
			});
		});

		// Add fix for backend members showing as pending
		if (frappe.user.has_role(['System Manager', 'Verenigingen Administrator'])) {
			listview.page.add_menu_item(__('Fix Backend Member Status'), function() {
				frappe.confirm(
					__('This will fix backend-created members that are incorrectly showing as "Pending". Continue?'),
					function() {
						frappe.show_alert(__('Fixing backend member statuses...'), 2);

						frappe.call({
							method: 'verenigingen.api.membership_application_review.fix_backend_member_statuses',
							callback: function(r) {
								if (r.message && r.message.success) {
									frappe.show_alert({
										message: r.message.message,
										indicator: 'green'
									}, 5);
									listview.refresh();
								} else {
									frappe.show_alert({
										message: __('Error: Please run manually: bench execute verenigingen.manual_fix.fix_backend_members_now'),
										indicator: 'red'
									}, 8);
								}
							},
							error: function(err) {
								console.error('Fix backend members error:', err);
								frappe.show_alert({
									message: __('Error occurred. Please run manually: bench execute verenigingen.manual_fix.fix_backend_members_now'),
									indicator: 'red'
								}, 8);
							}
						});
					}
				);
			});
		}

		// Add application status filter buttons
		add_status_filter_buttons(listview);
	},

	// ==================== BUTTON CONFIGURATIONS ====================

	button: {
		show: function(doc) {
			// Only show for members with application_id (created through application process)
			// and have pending status
			return doc.application_id && doc.application_status === 'Pending';
		},
		get_label: function(doc) {
			if (doc.application_id && doc.application_status === 'Pending') {
				return __('Review Application');
			}
			return __('View');
		},
		get_description: function(doc) {
			if (doc.application_id && doc.application_status === 'Pending') {
				return __('Review and approve/reject this application');
			}
			return __('View member details');
		},
		action: function(doc) {
			// Open form for review
			frappe.set_route('Form', 'Member', doc.name);
		}
	}
};

// ==================== HELPER FUNCTIONS ====================

function add_status_filter_buttons(listview) {
	// Add quick filter buttons for common statuses
	const status_filters = [
		{ label: __('Pending Applications'), filter: { application_status: 'Pending' }, color: 'orange' },
		{ label: __('Active Members'), filter: { status: 'Active' }, color: 'green' },
		{ label: __('Rejected Applications'), filter: { application_status: 'Rejected' }, color: 'red' },
		{ label: __('Payment Pending'), filter: { application_status: 'Payment Pending' }, color: 'yellow' }
	];

	status_filters.forEach(function(status_filter) {
		listview.page.add_action_item(status_filter.label, function() {
			// Clear existing filters
			listview.filter_area.clear();

			// Apply new filter
			Object.keys(status_filter.filter).forEach(function(key) {
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
	const thirtyDaysAgo = frappe.datetime.add_days(frappe.datetime.nowdate(), -30);
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
	$filter_buttons.on('click', 'button', function() {
		const filter = $(this).data('filter');

		listview.filter_area.clear();

		switch(filter) {
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
					message: __('To see members without chapters, please use the "Members Without Chapter" report.'),
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
	listview.page.add_menu_item(__('📊 New Members Report'), function() {
		frappe.set_route('query-report', 'New Members');
	});

	listview.page.add_menu_item(__('📊 Recent Chapter Changes Report'), function() {
		frappe.set_route('query-report', 'Recent Chapter Changes');
	});

	listview.page.add_menu_item(__('📊 Members Without Chapter Report'), function() {
		frappe.set_route('query-report', 'Members Without Chapter');
	});
}
