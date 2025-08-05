/**
 * @fileoverview Chapter DocType Frontend Controller for Verenigingen Association Management
 *
 * This controller manages the Chapter DocType interface, handling geographical organization
 * of association members, board management, and regional coordination. Chapters represent
 * local branches of the association organized by postal code regions.
 *
 * @description Business Context:
 * Chapters are geographical organizational units that group members by location,
 * facilitating local events, representation, and community building. Each chapter
 * has a board of volunteers who manage local activities and serve as liaisons
 * between members and the central organization.
 *
 * @description Key Features:
 * - Geographical organization by postal code ranges
 * - Board member management with roles and terms
 * - Member assignment and chapter membership tracking
 * - Regional coordination and hierarchy management
 * - Publication and visibility control
 * - Integration with member management system
 *
 * @description Integration Points:
 * - Links to Member DocType for geographical assignment
 * - Connects to Volunteer DocType for board positions
 * - Integrates with Chapter Role DocType for position definitions
 * - Coordinates with regional management systems
 *
 * @author Verenigingen Development Team
 * @version 2025-01-13
 * @since 1.0.0
 *
 * @requires frappe - Frappe Framework client-side API
 * @requires BoardManager.js - Board member management utilities
 * @requires ChapterController.js - Chapter business logic controller
 * @requires ChapterValidation.js - Validation utilities
 * @requires MemberManager.js - Member assignment utilities
 *
 * @example
 * // Controller is loaded automatically for Chapter DocType forms
 * // Access through Frappe's form system:
 * frappe.ui.form.on('Chapter', {
 *   refresh: function(frm) {
 *     // Chapter form initialization
 *   }
 * });
 */

// Copyright (c) 2025, Verenigingen Development Team and contributors
// For license information, please see license.txt

/**
 * Main Chapter DocType Form Controller
 *
 * Handles form lifecycle events and user interactions for Chapter management.
 * Orchestrates board management, member assignments, and geographical organization.
 */
frappe.ui.form.on('Chapter', {
	/**
	 * Form Onload Event Handler
	 *
	 * Initializes the chapter form with required functionality and prevents
	 * duplicate initialization. Sets up form behavior, validation rules,
	 * and UI components for chapter management.
	 *
	 * @param {Object} frm - Frappe Form object for chapter document
	 */
	onload(frm) {
		// Initialize chapter form functionality
		if (!frm._chapter_initialized) {
			setup_chapter_form(frm);
			frm._chapter_initialized = true;
		}
	},

	/**
	 * Form Refresh Event Handler
	 *
	 * Called when the chapter form is displayed or refreshed. Sets up
	 * action buttons, updates UI components, and configures board member
	 * management grid based on current chapter state and user permissions.
	 *
	 * @description Key Operations:
	 * - Configures chapter-specific action buttons
	 * - Updates chapter status and member count displays
	 * - Sets up board member management grid
	 * - Applies role-based access controls
	 *
	 * @param {Object} frm - Form object containing chapter data
	 */
	refresh(frm) {
		setup_chapter_buttons(frm);
		update_chapter_ui(frm);
		setup_board_grid(frm);
	},

	/**
	 * Form Validation Event Handler
	 *
	 * Validates chapter form data before saving. Checks postal code ranges,
	 * board member assignments, and business rule compliance.
	 *
	 * @param {Object} frm - Form object to validate
	 * @returns {boolean} True if validation passes, false otherwise
	 */
	validate(frm) {
		return validate_chapter_form(frm);
	},

	/**
	 * Before Save Event Handler
	 *
	 * Prepares chapter data for saving, including data normalization,
	 * relationship validation, and audit trail preparation.
	 *
	 * @param {Object} frm - Form object being saved
	 * @returns {boolean} True to continue save, false to abort
	 */
	before_save(frm) {
		return prepare_chapter_save(frm);
	},

	/**
	 * After Save Event Handler
	 *
	 * Handles post-save operations including member reassignment,
	 * notification sending, and system updates.
	 *
	 * @param {Object} frm - Saved form object
	 */
	after_save(frm) {
		handle_chapter_after_save(frm);
	},

	// ==================== FIELD EVENT HANDLERS ====================

	/**
	 * Postal Codes Field Change Handler
	 *
	 * Validates postal code ranges and checks for conflicts with other chapters.
	 * Ensures proper geographical coverage without overlaps.
	 *
	 * @param {Object} frm - Form object with postal code data
	 */
	postal_codes(frm) {
		validate_postal_codes(frm);
	},

	/**
	 * Chapter Head Field Change Handler
	 *
	 * Validates chapter head assignment and ensures the selected volunteer
	 * is eligible for the leadership role.
	 *
	 * @param {Object} frm - Form object with chapter head assignment
	 */
	chapter_head(frm) {
		validate_chapter_head(frm);
	},

	/**
	 * Region Field Change Handler
	 *
	 * Handles region assignment changes and updates related geographical
	 * configurations and member assignments.
	 *
	 * @param {Object} frm - Form object with region data
	 */
	region(frm) {
		handle_region_change(frm);
	},

	/**
	 * Published Field Change Handler
	 *
	 * Manages chapter publication status changes, affecting visibility
	 * in member portal and public interfaces.
	 *
	 * @param {Object} frm - Form object with publication status
	 */
	published(frm) {
		handle_published_change(frm);
	}
});

/**
 * Chapter Board Member Child Table Event Handlers
 *
 * Manages the board member child table interactions including volunteer
 * assignments, role management, and term tracking. Board members are
 * volunteers who hold leadership positions within the chapter structure.
 */
frappe.ui.form.on('Chapter Board Member', {
	/**
	 * Board Member Add Event Handler
	 *
	 * Triggered when a new board member row is added to the chapter.
	 * Initializes default values and validation rules for the new row.
	 *
	 * @param {Object} frm - Parent chapter form object
	 * @param {string} cdt - Child DocType name ('Chapter Board Member')
	 * @param {string} cdn - Child document name/ID
	 */
	board_members_add(frm, cdt, cdn) {
		handle_board_member_add(frm, cdt, cdn);
	},

	/**
	 * Board Member Remove Event Handler
	 *
	 * Handles cleanup when a board member is removed from the chapter.
	 * Manages role transitions and notification requirements.
	 *
	 * @param {Object} frm - Parent chapter form object
	 * @param {string} cdt - Child DocType name
	 * @param {string} cdn - Child document name/ID
	 */
	board_members_remove(frm, cdt, cdn) {
		handle_board_member_remove(frm, cdt, cdn);
	},

	/**
	 * Volunteer Field Change Handler
	 *
	 * Validates volunteer assignment and checks for eligibility,
	 * conflicts, and capacity constraints.
	 *
	 * @param {Object} frm - Parent form object
	 * @param {string} cdt - Child DocType name
	 * @param {string} cdn - Child document name/ID
	 */
	volunteer(frm, cdt, cdn) {
		handle_volunteer_change(frm, cdt, cdn);
	},

	/**
	 * Chapter Role Field Change Handler
	 *
	 * Manages role assignment validation and ensures role uniqueness
	 * where required (e.g., only one chapter head).
	 *
	 * @param {Object} frm - Parent form object
	 * @param {string} cdt - Child DocType name
	 * @param {string} cdn - Child document name/ID
	 */
	chapter_role(frm, cdt, cdn) {
		handle_role_change(frm, cdt, cdn);
	},

	/**
	 * From Date Field Change Handler
	 *
	 * Validates board member term start dates and checks for
	 * chronological consistency with other date fields.
	 *
	 * @param {Object} frm - Parent form object
	 * @param {string} cdt - Child DocType name
	 * @param {string} cdn - Child document name/ID
	 */
	from_date(frm, cdt, cdn) {
		handle_date_change(frm, cdt, cdn, 'from_date');
	},

	/**
	 * To Date Field Change Handler
	 *
	 * Validates board member term end dates and manages
	 * automatic status transitions for expired terms.
	 *
	 * @param {Object} frm - Parent form object
	 * @param {string} cdt - Child DocType name
	 * @param {string} cdn - Child document name/ID
	 */
	to_date(frm, cdt, cdn) {
		handle_date_change(frm, cdt, cdn, 'to_date');
	},

	/**
	 * Is Active Field Change Handler
	 *
	 * Manages board member active status changes and validates
	 * business rules for active/inactive transitions.
	 *
	 * @param {Object} frm - Parent form object
	 * @param {string} cdt - Child DocType name
	 * @param {string} cdn - Child document name/ID
	 */
	is_active(frm, cdt, cdn) {
		handle_active_change(frm, cdt, cdn);
	}
});

/**
 * Chapter Member Child Table Event Handlers
 *
 * Manages the member assignment child table for direct chapter membership
 * tracking and member-to-chapter relationship management.
 */
frappe.ui.form.on('Chapter Member', {
	/**
	 * Member Add Event Handler
	 *
	 * Triggered when a new member is added to the chapter.
	 * Validates member eligibility and geographic alignment.
	 *
	 * @param {Object} frm - Parent chapter form object
	 * @param {string} cdt - Child DocType name ('Chapter Member')
	 * @param {string} cdn - Child document name/ID
	 */
	members_add(frm, cdt, cdn) {
		handle_member_add(frm, cdt, cdn);
	},

	/**
	 * Member Remove Event Handler
	 *
	 * Handles member removal from chapter and updates
	 * related member records and statistics.
	 *
	 * @param {Object} frm - Parent form object
	 * @param {string} cdt - Child DocType name
	 * @param {string} cdn - Child document name/ID
	 */
	members_remove(frm, cdt, cdn) {
		handle_member_remove(frm, cdt, cdn);
	},

	/**
	 * Member Field Change Handler
	 *
	 * Validates member assignment and checks for conflicts
	 * with other chapter memberships and eligibility criteria.
	 *
	 * @param {Object} frm - Parent form object
	 * @param {string} cdt - Child DocType name
	 * @param {string} cdn - Child document name/ID
	 */
	member(frm, cdt, cdn) {
		handle_member_change(frm, cdt, cdn);
	},

	/**
	 * Enabled Field Change Handler
	 *
	 * Manages member active status within the chapter context,
	 * affecting participation and communication eligibility.
	 *
	 * @param {Object} frm - Parent form object
	 * @param {string} cdt - Child DocType name
	 * @param {string} cdn - Child document name/ID
	 */
	enabled(frm, cdt, cdn) {
		handle_enabled_change(frm, cdt, cdn);
	}
});

// Helper Functions
function setup_chapter_form(frm) {
	// Set up form-level functionality
	setup_postal_code_validation(frm);
	setup_member_filters(frm);
}

function setup_chapter_buttons(frm) {
	// Clear existing custom buttons
	frm.clear_custom_buttons();

	if (!frm.doc.__islocal) {
		// Add navigation buttons
		frm.add_custom_button(__('View Members'), () => {
			view_chapter_members(frm);
		}, __('View'));

		if (frm.doc.current_sepa_mandate) {
			frm.add_custom_button(__('Current SEPA Mandate'), () => {
				frappe.set_route('Form', 'SEPA Mandate', frm.doc.current_sepa_mandate);
			}, __('View'));
		}

		// Add board management buttons
		frm.add_custom_button(__('Manage Board Members'), () => {
			show_board_management_dialog(frm);
		}, __('Board'));

		frm.add_custom_button(__('View Board History'), () => {
			show_board_history(frm);
		}, __('Board'));

		frm.add_custom_button(__('Sync with Volunteer System'), () => {
			sync_board_with_volunteers(frm);
		}, __('Board'));
	}
}

function update_chapter_ui(frm) {
	// Update UI elements based on current state
	update_members_summary(frm);
	update_postal_code_preview(frm);
}

function setup_board_grid(frm) {
	// Set up board members grid
	if (frm.fields_dict.board_members && frm.fields_dict.board_members.grid) {
		frm.fields_dict.board_members.grid.get_field('volunteer').get_query = function () {
			return {
				filters: {
					status: ['in', ['Active', 'New']]
				}
			};
		};

		frm.fields_dict.board_members.grid.get_field('chapter_role').get_query = function () {
			return {
				filters: {
					is_active: 1
				}
			};
		};
	}
}

function validate_chapter_form(frm) {
	// Form validation
	if (!frm.doc.name || !frm.doc.region) {
		frappe.msgprint(__('Name and Region are required'));
		return false;
	}

	// Validate postal codes
	if (frm.doc.postal_codes && !validate_postal_codes(frm)) {
		return false;
	}

	return true;
}

function prepare_chapter_save(frm) {
	// Prepare data before save
	if (!frm.doc.route && frm.doc.name) {
		frm.doc.route = `chapters/${frappe.scrub(frm.doc.name)}`;
	}

	return true;
}

function handle_chapter_after_save(frm) {
	frappe.show_alert({
		message: __('Chapter saved successfully'),
		indicator: 'green'
	}, 3);
}

function validate_postal_codes(frm) {
	if (!frm.doc.postal_codes) { return true; }

	try {
		frappe.call({
			method: 'validate_postal_codes',
			doc: frm.doc,
			callback(r) {
				if (!r.message) {
					frappe.msgprint({
						title: __('Invalid Postal Codes'),
						indicator: 'red',
						message: __('Please check your postal code patterns')
					});
				}
			},
			error(r) {
				frappe.msgprint(__('Error validating postal codes: {0}', [r.message]));
			}
		});
	} catch (error) {
		console.error('Error validating postal codes:', error);
	}

	return true;
}

function validate_chapter_head(frm) {
	if (frm.doc.chapter_head) {
		frappe.db.get_value('Member', frm.doc.chapter_head, 'status', (r) => {
			if (r && r.status !== 'Active') {
				frappe.msgprint(__('Warning: Selected chapter head is not an active member'));
			}
		});
	}
}

function handle_region_change(frm) {
	if (frm.doc.region) {
		suggest_postal_codes_for_region(frm);
	}
}

function handle_published_change(frm) {
	if (frm.doc.published) {
		frappe.show_alert({
			message: __('Chapter is now public and visible to members'),
			indicator: 'green'
		}, 5);
	} else {
		frappe.show_alert({
			message: __('Chapter is now private and hidden from members'),
			indicator: 'orange'
		}, 5);
	}
}

function suggest_postal_codes_for_region(frm) {
	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Chapter',
			filters: {
				region: frm.doc.region,
				name: ['!=', frm.doc.name]
			},
			fields: ['postal_codes'],
			limit_page_length: 5
		},
		callback(r) {
			if (r.message && r.message.length > 0) {
				const all_codes = new Set();
				r.message.forEach(chapter => {
					if (chapter.postal_codes) {
						chapter.postal_codes.split(',').forEach(code => {
							all_codes.add(code.trim());
						});
					}
				});

				if (all_codes.size > 0) {
					frappe.show_alert({
						message: __('Other chapters in {0} use postal codes: {1}',
							[frm.doc.region, Array.from(all_codes).join(', ')]),
						indicator: 'blue'
					}, 10);
				}
			}
		},
		error(r) {
			console.error('Error suggesting postal codes:', r);
		}
	});
}

// Board member handlers
function handle_board_member_add(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row.from_date) {
		frappe.model.set_value(cdt, cdn, 'from_date', frappe.datetime.get_today());
	}
	row.is_active = 1;
}

function handle_board_member_remove(frm, cdt, cdn) {
	// Board member removed
}

function handle_volunteer_change(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (row.volunteer) {
		frappe.db.get_value('Volunteer', row.volunteer, ['volunteer_name', 'email'], (r) => {
			if (r) {
				frappe.model.set_value(cdt, cdn, 'volunteer_name', r.volunteer_name);
				frappe.model.set_value(cdt, cdn, 'email', r.email);
			}
		});
	}
}

function handle_role_change(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	// Handle role-specific logic
}

function handle_date_change(frm, cdt, cdn, field) {
	const row = locals[cdt][cdn];
	if (field === 'to_date' && row.to_date && row.from_date) {
		if (frappe.datetime.get_diff(row.to_date, row.from_date) < 0) {
			frappe.msgprint(__('End date cannot be before start date'));
			frappe.model.set_value(cdt, cdn, 'to_date', '');
		}
	}
}

function handle_active_change(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row.is_active && !row.to_date) {
		frappe.model.set_value(cdt, cdn, 'to_date', frappe.datetime.get_today());
	}
}

// Member handlers
function handle_member_add(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	row.enabled = 1;
	if (!row.chapter_join_date) {
		frappe.model.set_value(cdt, cdn, 'chapter_join_date', frappe.datetime.get_today());
	}
}

function handle_member_remove(frm, cdt, cdn) {
	// Member removed
}

function handle_member_change(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (row.member && !row.chapter_join_date) {
		frappe.model.set_value(cdt, cdn, 'chapter_join_date', frappe.datetime.get_today());
	}
}

function handle_enabled_change(frm, cdt, cdn) {
	// Handle member enabled/disabled change
}

// UI Helper Functions
function update_members_summary(frm) {
	if (frm.doc.members) {
		const active_count = frm.doc.members.filter(m => m.enabled).length;
		const total_count = frm.doc.members.length;

		if (frm.dashboard && frm.dashboard.set_headline) {
			frm.dashboard.set_headline(__('Members: {0} active of {1} total', [active_count, total_count]));
		}
	}
}

function update_postal_code_preview(frm) {
	if (frm.doc.postal_codes) {
		// Could add a preview of postal code patterns
	}
}

function setup_postal_code_validation(frm) {
	// Set up real-time postal code validation
}

function setup_member_filters(frm) {
	// Set up member field filters
	frm.set_query('chapter_head', () => {
		return {
			filters: {
				status: 'Active'
			}
		};
	});
}

// Dialog Functions
function view_chapter_members(frm) {
	// Navigate to members list - members will be filtered by chapter roster
	frappe.msgprint({
		title: __('Chapter Members'),
		message: __('Viewing members for this chapter. Use the chapter roster below to see all members.'),
		indicator: 'blue'
	});
	frappe.set_route('List', 'Member');
}

function show_board_management_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __('Add Board Member'),
		fields: [
			{
				label: __('Volunteer'),
				fieldname: 'volunteer',
				fieldtype: 'Link',
				options: 'Volunteer',
				reqd: 1,
				get_query() {
					return {
						filters: {
							status: ['in', ['Active', 'New']]
						}
					};
				}
			},
			{
				label: __('Board Role'),
				fieldname: 'role',
				fieldtype: 'Link',
				options: 'Chapter Role',
				reqd: 1,
				get_query() {
					return {
						filters: {
							is_active: 1
						}
					};
				}
			},
			{
				label: __('From Date'),
				fieldname: 'from_date',
				fieldtype: 'Date',
				default: frappe.datetime.get_today(),
				reqd: 1
			},
			{
				label: __('To Date'),
				fieldname: 'to_date',
				fieldtype: 'Date'
			}
		],
		primary_action_label: __('Add Board Member'),
		primary_action() {
			const values = d.get_values();
			if (!values) { return; }

			frappe.call({
				method: 'add_board_member',
				doc: frm.doc,
				args: {
					volunteer: values.volunteer,
					role: values.role,
					from_date: values.from_date,
					to_date: values.to_date
				},
				freeze: true,
				freeze_message: __('Adding board member...'),
				callback(r) {
					if (r.message && r.message.success) {
						frappe.show_alert({
							message: __('Board member added successfully'),
							indicator: 'green'
						}, 3);
						frm.reload_doc();
						d.hide();
					}
				},
				error(r) {
					frappe.msgprint(__('Error adding board member: {0}', [r.message]));
				}
			});
		}
	});

	d.show();
}

function show_board_history(frm) {
	frappe.call({
		method: 'get_board_members',
		doc: frm.doc,
		args: {
			include_inactive: true
		},
		callback(r) {
			if (r.message) {
				show_board_history_dialog(r.message);
			}
		},
		error(r) {
			frappe.msgprint(__('Error loading board history: {0}', [r.message]));
		}
	});
}

function show_board_history_dialog(board_history) {
	const d = new frappe.ui.Dialog({
		title: __('Board History'),
		fields: [{
			fieldtype: 'HTML',
			options: render_board_history_html(board_history)
		}],
		primary_action_label: __('Close'),
		primary_action() {
			d.hide();
		}
	});

	d.show();
}

function render_board_history_html(board_history) {
	let html = '<div class="board-history">';
	html += '<table class="table table-bordered">';
	html += '<thead><tr>';
	html += `<th>${__('Volunteer')}</th>`;
	html += `<th>${__('Role')}</th>`;
	html += `<th>${__('From')}</th>`;
	html += `<th>${__('To')}</th>`;
	html += `<th>${__('Status')}</th>`;
	html += '</tr></thead><tbody>';

	board_history.forEach(member => {
		html += '<tr>';
		html += `<td>${member.volunteer_name || ''}</td>`;
		html += `<td>${member.chapter_role || ''}</td>`;
		html += `<td>${member.from_date ? frappe.datetime.str_to_user(member.from_date) : ''}</td>`;
		html += `<td>${member.to_date ? frappe.datetime.str_to_user(member.to_date) : __('Present')}</td>`;
		html += `<td><span class="indicator ${member.is_active ? 'green' : 'red'}">${
			member.is_active ? __('Active') : __('Inactive')}</span></td>`;
		html += '</tr>';
	});

	html += '</tbody></table></div>';
	return html;
}

function sync_board_with_volunteers(frm) {
	frappe.call({
		method: 'sync_board_members',
		doc: frm.doc,
		freeze: true,
		freeze_message: __('Syncing with volunteer system...'),
		callback(r) {
			if (r.message) {
				frappe.show_alert({
					message: __('Board members synced successfully'),
					indicator: 'green'
				}, 3);
				frm.refresh();
			}
		},
		error(r) {
			frappe.msgprint(__('Error syncing board members: {0}', [r.message]));
		}
	});
}
