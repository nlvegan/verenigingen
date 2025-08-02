/**
 * @fileoverview Chapter Board Member Management Module for Verenigingen Association Management
 *
 * This module provides comprehensive board member management functionality for chapters,
 * including role assignments, term management, transitions, and bulk operations.
 * Board members are volunteers who hold leadership positions within chapter structures.
 *
 * @description Business Context:
 * Chapter boards consist of volunteers who manage local chapter activities, coordinate
 * with the central organization, and represent member interests. The system manages
 * board composition, role transitions, term limits, and succession planning while
 * maintaining compliance with organizational governance requirements.
 *
 * @description Key Features:
 * - Board member addition, removal, and role management
 * - Term tracking and automatic transition handling
 * - Bulk operations for efficient board management
 * - Integration with volunteer management system
 * - Role-based permission and validation enforcement
 * - Board history and audit trail maintenance
 *
 * @description Governance Integration:
 * - Enforces organizational governance rules
 * - Manages role uniqueness constraints (e.g., single chapter head)
 * - Validates volunteer eligibility for board positions
 * - Tracks term limits and succession requirements
 * - Maintains democratic representation standards
 *
 * @author Verenigingen Development Team
 * @version 2025-01-13
 * @since 1.0.0
 *
 * @requires ChapterAPI - Chapter-specific API operations
 * @requires ChapterValidation - Board validation utilities
 * @requires frappe - Frappe Framework client-side API
 *
 * @example
 * // Usage within chapter form controller:
 * const boardManager = new BoardManager(frm, state, ui);
 * boardManager.addButtons();
 * boardManager.setupGrid();
 */

// verenigingen/verenigingen/doctype/chapter/modules/BoardManager.js

import { ChapterAPI } from '../utils/ChapterAPI.js';
import { ChapterValidation } from '../utils/ChapterValidation.js';

/**
 * Chapter Board Management Class
 *
 * Provides comprehensive functionality for managing chapter board members,
 * including role assignments, term tracking, and governance compliance.
 */
export class BoardManager {
	/**
	 * BoardManager Constructor
	 *
	 * Initializes the board management system with required dependencies
	 * and sets up state tracking for board member operations.
	 *
	 * @param {Object} frm - Frappe Form object for chapter document
	 * @param {Object} state - Chapter state management object
	 * @param {Object} ui - Chapter UI management object
	 */
	constructor(frm, state, ui) {
		this.frm = frm;
		this.state = state;
		this.ui = ui;
		this.api = new ChapterAPI();
		this.selectedMembers = new Set();
	}

	/**
	 * Add Board Management Action Buttons
	 *
	 * Creates action buttons for board member management operations
	 * including role transitions, bulk operations, and system integration.
	 *
	 * @description Available Actions:
	 * - Manage Board Members: Add/remove board members with validation
	 * - Transition Board Role: Handle role changes and succession planning
	 * - View Board History: Display historical board composition and changes
	 * - Sync with Volunteer System: Integrate with volunteer management
	 * - Bulk Remove Board Members: Efficient bulk operations for board changes
	 *
	 * @example
	 * // Called during chapter form initialization:
	 * boardManager.addButtons();
	 */
	addButtons() {
		// Add board management buttons
		this.ui.addButton(__('Manage Board Members'), () => this.showManageDialog(), __('Board'));
		this.ui.addButton(__('Transition Board Role'), () => this.showTransitionDialog(), __('Board'));
		this.ui.addButton(__('View Board History'), () => this.showHistory(), __('Board'));
		this.ui.addButton(__('Sync with Volunteer System'), () => this.syncWithVolunteerSystem(), __('Board'));
		this.ui.addButton(__('Bulk Remove Board Members'), () => this.showBulkRemoveDialog(), __('Board'));
	}

	/**
	 * Setup Board Member Grid Interface
	 *
	 * Configures the board member child table grid with enhanced functionality
	 * including custom buttons, selection handling, and bulk operations.
	 *
	 * @description Grid Enhancements:
	 * - Custom action buttons for board operations
	 * - Multi-selection support for bulk operations
	 * - Real-time validation and business rule enforcement
	 * - Enhanced user interface for board management
	 *
	 * @example
	 * // Called during form refresh:
	 * boardManager.setupGrid();
	 */
	setupGrid() {
		const grid = this.frm.fields_dict.board_members?.grid;
		if (!grid) return;

		// Add custom button to grid
		grid.add_custom_button(__('Add Board Member'), () => this.addNewBoardMember());
		grid.add_custom_button(__('Bulk Operations'), () => this.showBulkOperationsInfo());

		// Set up selection handling
		setTimeout(() => this.enhanceGridWithSelection(), 500);
	}

	enhanceGridWithSelection() {
		const $grid = this.frm.fields_dict.board_members?.grid.wrapper;
		if (!$grid) return;

		// Add bulk actions bar if not exists
		if (!$grid.find('.bulk-actions-bar').length) {
			const $bulkBar = $(`
                <div class="bulk-actions-bar" style="display: none;">
                    <button class="btn btn-xs btn-default" onclick="window._chapterBoardManager.selectAllActive()">
                        ${__('Select All Active')}
                    </button>
                    <button class="btn btn-xs btn-default" onclick="window._chapterBoardManager.deselectAll()">
                        ${__('Deselect All')}
                    </button>
                    <span style="margin: 0 15px;">|</span>
                    <button class="btn btn-xs btn-danger" onclick="window._chapterBoardManager.bulkRemoveSelected()">
                        ${__('Remove Selected')}
                    </button>
                    <button class="btn btn-xs btn-warning" onclick="window._chapterBoardManager.bulkDeactivateSelected()">
                        ${__('Deactivate Selected')}
                    </button>
                </div>
            `);

			$grid.find('.grid-body').before($bulkBar);
		}

		// Store reference for onclick handlers
		window._chapterBoardManager = this;

		// Add checkboxes to rows
		this.addSelectionCheckboxes();
	}

	addSelectionCheckboxes() {
		const $grid = this.frm.fields_dict.board_members?.grid.wrapper;
		if (!$grid) return;

		$grid.find('.grid-row').each((i, row) => {
			const $row = $(row);
			const idx = $row.attr('data-idx');

			if (idx && !$row.find('.board-member-checkbox').length) {
				const boardMember = this.frm.doc.board_members[idx - 1];

				if (boardMember && boardMember.is_active) {
					const $checkbox = $(`<input type="checkbox" class="board-member-checkbox" data-idx="${idx}">`);

					$checkbox.change(() => {
						if ($checkbox.is(':checked')) {
							$row.addClass('board-member-selected');
							this.selectedMembers.add(idx);
						} else {
							$row.removeClass('board-member-selected');
							this.selectedMembers.delete(idx);
						}

						this.updateBulkActionsVisibility();
					});

					$row.find('.data-row').first().prepend($checkbox);
				}
			}
		});
	}

	updateBulkActionsVisibility() {
		const $grid = this.frm.fields_dict.board_members?.grid.wrapper;
		if (!$grid) return;

		const $bulkBar = $grid.find('.bulk-actions-bar');
		if (this.selectedMembers.size > 0) {
			$bulkBar.show();
			this.state.update('ui.bulkActionsVisible', true);
		} else {
			$bulkBar.hide();
			this.state.update('ui.bulkActionsVisible', false);
		}
	}

	selectAllActive() {
		const $grid = this.frm.fields_dict.board_members?.grid.wrapper;
		if (!$grid) return;

		$grid.find('.board-member-checkbox').each((i, checkbox) => {
			$(checkbox).prop('checked', true).trigger('change');
		});
	}

	deselectAll() {
		const $grid = this.frm.fields_dict.board_members?.grid.wrapper;
		if (!$grid) return;

		$grid.find('.board-member-checkbox:checked').prop('checked', false).trigger('change');
	}

	async addNewBoardMember() {
		// Get available chapter roles
		const roles = await this.api.getList('Chapter Role', {
			filters: { is_active: 1 },
			fields: ['name', 'permissions_level']
		});

		if (!roles || !roles.length) {
			this.ui.showError(__('No active chapter roles found. Please create roles first.'));
			return;
		}

		const dialog = this.ui.showDialog({
			title: __('Add New Board Member'),
			fields: [
				{
					fieldname: 'volunteer',
					fieldtype: 'Link',
					label: __('Volunteer'),
					options: 'Volunteer',
					reqd: 1,
					get_query: () => ({
						query: 'verenigingen.verenigingen.doctype.chapter.chapter.get_volunteers_for_chapter',
						filters: { chapter: this.frm.doc.name }
					})
				},
				{
					fieldname: 'chapter_role',
					fieldtype: 'Link',
					label: __('Board Role'),
					options: 'Chapter Role',
					reqd: 1
				},
				{
					fieldname: 'from_date',
					fieldtype: 'Date',
					label: __('From Date'),
					default: frappe.datetime.get_today(),
					reqd: 1
				},
				{
					fieldname: 'to_date',
					fieldtype: 'Date',
					label: __('To Date')
				}
			],
			primary_action_label: __('Add'),
			primary_action: async (values) => {
				await this.addBoardMemberToChapter(values);
				dialog.hide();
			}
		});
	}

	async addBoardMemberToChapter(values) {
		try {
			this.state.setLoading('addBoardMember', true);

			// Add to grid
			const child = this.frm.add_child('board_members');
			frappe.model.set_value(child.doctype, child.name, {
				volunteer: values.volunteer,
				chapter_role: values.chapter_role,
				from_date: values.from_date,
				to_date: values.to_date,
				is_active: 1
			});

			// Fetch volunteer details
			const volunteer = await this.api.getDoc('Volunteer', values.volunteer);
			frappe.model.set_value(child.doctype, child.name, {
				volunteer_name: volunteer.volunteer_name,
				email: volunteer.email
			});

			this.frm.refresh_field('board_members');

			// Add to chapter members
			await this.addBoardMemberToMembers(values.volunteer);

			// Check for duplicate roles
			this.checkForDuplicateRoles(child);

			this.ui.showAlert(__('Board member added successfully'), 'green');
		} catch (error) {
			this.ui.showError(__('Failed to add board member: {0}', [error.message]));
		} finally {
			this.state.setLoading('addBoardMember', false);
		}
	}

	async addBoardMemberToMembers(volunteerId) {
		try {
			const volunteer = await this.api.getValue('Volunteer', volunteerId, 'member');
			if (!volunteer?.member) {
				this.ui.showError(__('Could not find member associated with this volunteer'));
				return;
			}

			const memberId = volunteer.member;

			// Check if already a member
			const alreadyMember = this.frm.doc.members?.some(m => m.member === memberId);

			if (!alreadyMember) {
				const member = await this.api.getDoc('Member', memberId);

				const newMember = this.frm.add_child('members');
				frappe.model.set_value(newMember.doctype, newMember.name, {
					member: memberId,
					member_name: member.full_name,
					enabled: 1
				});

				this.frm.refresh_field('members');
				this.ui.showAlert(__('Board member {0} added to chapter members list', [member.full_name]), 'green');
			}
		} catch (error) {
			console.error('Error adding board member to members:', error);
		}
	}

	async checkForDuplicateRoles(currentRow) {
		const role = await this.api.getValue('Chapter Role', currentRow.chapter_role, 'is_unique');

		if (role?.is_unique) {
			const duplicates = this.frm.doc.board_members.filter(member =>
				member.is_active &&
                member.chapter_role === currentRow.chapter_role &&
                member.name !== currentRow.name
			);

			if (duplicates.length > 0) {
				const duplicate = duplicates[0];
				this.ui.showError(
					__('Role \'{0}\' is already assigned to {1}. This role can only be assigned to one person at a time.',
						[currentRow.chapter_role, duplicate.volunteer_name])
				);

				// Ask if user wants to deactivate the existing role
				this.ui.confirmAction(
					__('Do you want to deactivate the existing assignment to {0}?', [duplicate.volunteer_name]),
					() => {
						frappe.model.set_value(duplicate.doctype, duplicate.name, {
							is_active: 0,
							to_date: frappe.datetime.get_today()
						});
					}
				);
			} else {
				this.ui.showAlert(__('Role \'{0}\' assigned to {1}', [currentRow.chapter_role, currentRow.volunteer_name]), 'green', 3);
			}
		}
	}

	async showManageDialog() {
		const dialog = this.ui.showDialog({
			title: __('Manage Board Members'),
			fields: [
				{
					fieldname: 'member_section',
					fieldtype: 'Section Break',
					label: __('Add New Board Member')
				},
				{
					fieldname: 'volunteer',
					fieldtype: 'Link',
					label: __('Volunteer'),
					options: 'Volunteer',
					reqd: 1,
					get_query: () => ({
						query: 'verenigingen.verenigingen.doctype.chapter.chapter.get_volunteers_for_chapter',
						filters: { chapter: this.frm.doc.name }
					})
				},
				{
					fieldname: 'chapter_role',
					fieldtype: 'Link',
					label: __('Board Role'),
					options: 'Chapter Role',
					reqd: 1
				},
				{
					fieldname: 'from_date',
					fieldtype: 'Date',
					label: __('From Date'),
					default: frappe.datetime.get_today(),
					reqd: 1
				},
				{
					fieldname: 'to_date',
					fieldtype: 'Date',
					label: __('To Date')
				}
			],
			primary_action_label: __('Add Board Member'),
			primary_action: async (values) => {
				try {
					const result = await this.api.call('add_board_member', {
						doc: this.frm.doc,
						volunteer: values.volunteer,
						role: values.chapter_role,
						from_date: values.from_date,
						to_date: values.to_date
					});

					if (result) {
						dialog.hide();
						this.frm.reload_doc();
					}
				} catch (error) {
					this.ui.showError(__('Failed to add board member: {0}', [error.message]));
				}
			}
		});
	}

	async showTransitionDialog() {
		const activeMembers = this.getActiveBoardMembers();

		if (!activeMembers || activeMembers.length === 0) {
			this.ui.showError(__('No active board members found'));
			return;
		}

		const dialog = this.ui.showDialog({
			title: __('Transition Board Role'),
			fields: [
				{
					fieldname: 'current_volunteer',
					fieldtype: 'Select',
					label: __('Current Board Member'),
					options: activeMembers.map(m => `${m.volunteer} | ${m.volunteer_name} (${m.chapter_role})`).join('\n'),
					reqd: 1
				},
				{
					fieldname: 'new_role',
					fieldtype: 'Link',
					label: __('New Role'),
					options: 'Chapter Role',
					reqd: 1
				},
				{
					fieldname: 'transition_date',
					fieldtype: 'Date',
					label: __('Transition Date'),
					default: frappe.datetime.get_today(),
					reqd: 1
				}
			],
			primary_action_label: __('Transition Role'),
			primary_action: async (values) => {
				const volunteer = values.current_volunteer.split(' | ')[0];

				try {
					const result = await this.api.call('transition_board_role', {
						doc: this.frm.doc,
						volunteer: volunteer,
						new_role: values.new_role,
						transition_date: values.transition_date
					});

					if (result) {
						dialog.hide();
						this.frm.reload_doc();
					}
				} catch (error) {
					this.ui.showError(__('Failed to transition role: {0}', [error.message]));
				}
			}
		});
	}

	async showHistory() {
		try {
			this.state.setLoading('boardHistory', true);

			const history = await this.api.call('verenigingen.verenigingen.doctype.chapter.chapter.get_chapter_board_history', {
				chapter_name: this.frm.doc.name
			});

			if (!history || !history.length) {
				this.ui.showError(__('No board history found'));
				return;
			}

			const html = this.generateHistoryHTML(history);

			this.ui.showDialog({
				title: __('Board History - {0}', [this.frm.doc.name]),
				fields: [{
					fieldtype: 'HTML',
					options: html
				}],
				primary_action_label: __('Close'),
				primary_action: function() {
					this.hide();
				}
			});
		} catch (error) {
			this.ui.showError(__('Failed to load board history: {0}', [error.message]));
		} finally {
			this.state.setLoading('boardHistory', false);
		}
	}

	generateHistoryHTML(history) {
		let html = '<div class="board-history"><table class="table table-bordered">';
		html += '<thead><tr>';
		html += '<th>' + __('Member') + '</th>';
		html += '<th>' + __('Role') + '</th>';
		html += '<th>' + __('From Date') + '</th>';
		html += '<th>' + __('To Date') + '</th>';
		html += '<th>' + __('Status') + '</th>';
		html += '</tr></thead><tbody>';

		history.forEach(entry => {
			const status = entry.is_active ? __('Active') : __('Inactive');
			const statusColor = entry.is_active ? 'green' : 'gray';

			html += '<tr>';
			html += '<td>' + (entry.volunteer_name || entry.member_name) + '</td>';
			html += '<td>' + (entry.role || entry.chapter_role) + '</td>';
			html += '<td>' + this.ui.formatDate(entry.from_date) + '</td>';
			html += '<td>' + (entry.to_date ? this.ui.formatDate(entry.to_date) : '') + '</td>';
			html += '<td><span class="indicator ' + statusColor + '">' + status + '</span></td>';
			html += '</tr>';
		});

		html += '</tbody></table></div>';

		return html;
	}

	async syncWithVolunteerSystem() {
		try {
			this.state.setLoading('volunteerSync', true);
			this.ui.showLoadingIndicator(__('Syncing with volunteer system...'));

			const result = await this.api.call('verenigingen.verenigingen.doctype.volunteer.volunteer.sync_chapter_board_members');

			if (result?.updated_count !== undefined) {
				this.ui.showAlert(
					__('Synced {0} board members with volunteer system.', [result.updated_count]),
					'green'
				);
			}
		} catch (error) {
			this.ui.showError(__('Failed to sync with volunteer system: {0}', [error.message]));
		} finally {
			this.state.setLoading('volunteerSync', false);
			this.ui.hideLoadingIndicator();
		}
	}

	showBulkRemoveDialog() {
		const activeMembers = this.getActiveBoardMembers();

		if (!activeMembers || activeMembers.length === 0) {
			this.ui.showError(__('No active board members found'));
			return;
		}

		const memberOptions = activeMembers.map(member => ({
			label: member.volunteer_name + ' (' + member.chapter_role + ')',
			value: member.volunteer,
			description: 'From: ' + this.ui.formatDate(member.from_date)
		}));

		const dialog = this.ui.showDialog({
			title: __('Bulk Board Member Operations'),
			fields: [
				{
					fieldname: 'selected_members',
					fieldtype: 'MultiSelectPills',
					label: __('Select Board Members'),
					options: memberOptions,
					reqd: 1
				},
				{
					fieldname: 'action',
					fieldtype: 'Select',
					label: __('Action'),
					options: 'Deactivate\nRemove',
					default: 'Deactivate',
					reqd: 1
				},
				{
					fieldname: 'end_date',
					fieldtype: 'Date',
					label: __('End Date'),
					default: frappe.datetime.get_today(),
					reqd: 1
				},
				{
					fieldname: 'reason',
					fieldtype: 'Small Text',
					label: __('Reason'),
					description: __('Optional reason for this action')
				}
			],
			primary_action_label: __('Process Selected Members'),
			primary_action: async (values) => {
				await this.processBulkAction(values, activeMembers);
				dialog.hide();
			}
		});
	}

	async processBulkAction(values, activeMembers) {
		if (!values.selected_members || values.selected_members.length === 0) {
			this.ui.showError(__('Please select at least one board member'));
			return;
		}

		const selectedData = values.selected_members.map(volunteerId => {
			const member = activeMembers.find(m => m.volunteer === volunteerId);
			return {
				volunteer: member.volunteer,
				chapter_role: member.chapter_role,
				from_date: member.from_date,
				end_date: values.end_date,
				reason: values.reason
			};
		});

		const method = values.action === 'Remove'
			? 'verenigingen.verenigingen.doctype.chapter.chapter.bulk_remove_board_members'
			: 'verenigingen.verenigingen.doctype.chapter.chapter.bulk_deactivate_board_members';

		try {
			this.state.setLoading('bulkAction', true);

			const result = await this.api.call(method, {
				chapter_name: this.frm.doc.name,
				board_members: selectedData
			});

			if (result?.success) {
				this.ui.showAlert(
					__('{0} board members processed successfully', [result.processed]),
					'green'
				);

				this.frm.reload_doc();
			} else {
				this.ui.showError(__('Error processing board members. Please check the error log.'));
			}
		} catch (error) {
			this.ui.showError(__('Failed to process board members: {0}', [error.message]));
		} finally {
			this.state.setLoading('bulkAction', false);
		}
	}

	async bulkRemoveSelected() {
		const selectedMembers = this.getSelectedBoardMembers();

		if (selectedMembers.length === 0) {
			this.ui.showError(__('No board members selected'));
			return;
		}

		this.showBulkRemovalDialog(selectedMembers, 'remove');
	}

	async bulkDeactivateSelected() {
		const selectedMembers = this.getSelectedBoardMembers();

		if (selectedMembers.length === 0) {
			this.ui.showError(__('No board members selected'));
			return;
		}

		this.showBulkRemovalDialog(selectedMembers, 'deactivate');
	}

	showBulkRemovalDialog(selectedMembers, action) {
		const actionLabel = action === 'remove' ? __('Remove') : __('Deactivate');
		const actionDescription = action === 'remove'
			? __('This will permanently remove the selected board members from the chapter.')
			: __('This will deactivate the selected board members (they will remain in the list but marked as inactive).');

		const membersList = selectedMembers.map(member =>
			'• ' + member.volunteer_name + ' (' + member.chapter_role + ')'
		).join('\n');

		const dialog = this.ui.showDialog({
			title: actionLabel + ' ' + __('Board Members'),
			fields: [
				{
					fieldtype: 'HTML',
					options: `<div class="alert alert-warning">
                        <p>${actionDescription}</p>
                        <p><strong>${__('Selected Members:')}</strong></p>
                        <pre>${membersList}</pre>
                    </div>`
				},
				{
					fieldname: 'end_date',
					fieldtype: 'Date',
					label: __('End Date'),
					default: frappe.datetime.get_today(),
					reqd: 1
				},
				{
					fieldname: 'reason',
					fieldtype: 'Small Text',
					label: __('Reason for ') + actionLabel.toLowerCase(),
					description: __('Optional reason for this action')
				}
			],
			primary_action_label: actionLabel + ' ' + selectedMembers.length + ' ' + __('Members'),
			primary_action: async (values) => {
				await this.processBulkRemoval(selectedMembers, action, values);
				dialog.hide();
			}
		});
	}

	async processBulkRemoval(selectedMembers, action, values) {
		const bulkData = selectedMembers.map(member => ({
			volunteer: member.volunteer,
			chapter_role: member.chapter_role,
			from_date: member.from_date,
			end_date: values.end_date,
			reason: values.reason
		}));

		const method = action === 'remove'
			? 'verenigingen.verenigingen.doctype.chapter.chapter.bulk_remove_board_members'
			: 'verenigingen.verenigingen.doctype.chapter.chapter.bulk_deactivate_board_members';

		try {
			this.state.setLoading('bulkRemoval', true);

			const result = await this.api.call(method, {
				chapter_name: this.frm.doc.name,
				board_members: bulkData
			});

			if (result?.success) {
				this.ui.showAlert(
					__('{0} board members {1} successfully',
						[result.processed, action === 'remove' ? 'removed' : 'deactivated']),
					'green'
				);

				this.frm.reload_doc();
			} else {
				this.ui.showError(__('Error processing board members. Please check the error log.'));
			}
		} catch (error) {
			this.ui.showError(__('Failed to process board members: {0}', [error.message]));
		} finally {
			this.state.setLoading('bulkRemoval', false);
		}
	}

	showBulkOperationsInfo() {
		this.ui.showAlert(
			__('Use the checkboxes next to board members to select them, then use the bulk action buttons that appear above the grid.'),
			'blue'
		);
	}

	getActiveBoardMembers() {
		return this.frm.doc.board_members?.filter(member => member.is_active) || [];
	}

	getSelectedBoardMembers() {
		const selected = [];

		this.selectedMembers.forEach(idx => {
			const boardMember = this.frm.doc.board_members[parseInt(idx) - 1];
			if (boardMember) {
				selected.push({
					idx: idx,
					volunteer: boardMember.volunteer,
					volunteer_name: boardMember.volunteer_name,
					chapter_role: boardMember.chapter_role,
					from_date: boardMember.from_date,
					data: boardMember
				});
			}
		});

		return selected;
	}

	async validateBoardMembers() {
		const result = await ChapterValidation.validateBoardMembers(this.frm.doc.board_members);

		if (!result.isValid) {
			this.state.update('validation.boardMembers', result.errors);
		}

		return result;
	}
	// Event handlers
	onBoardMemberAdd(cdt, cdn) {
		const row = locals[cdt][cdn];

		// Set default values
		if (!row.from_date) {
			frappe.model.set_value(cdt, cdn, 'from_date', frappe.datetime.get_today());
		}

		if (!row.is_active) {
			frappe.model.set_value(cdt, cdn, 'is_active', 1);
		}

		// Refresh the grid to show selection checkboxes
		setTimeout(() => this.addSelectionCheckboxes(), 100);
	}

	onBoardMemberRemove(cdt, cdn) {
		const row = locals[cdt][cdn];

		// If this was an active board member with a volunteer, update history
		if (row.is_active && row.volunteer) {
			// Update volunteer history for removal
			this.updateVolunteerHistory({
				...row,
				to_date: frappe.datetime.get_today()
			});
		}

		// Refresh the grid
		setTimeout(() => this.addSelectionCheckboxes(), 100);
	}
	// Event handlers
	async onVolunteerChange(cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.volunteer) return;

		try {
			const volunteer = await this.api.getDoc('Volunteer', row.volunteer);

			frappe.model.set_value(cdt, cdn, {
				volunteer_name: volunteer.volunteer_name,
				email: volunteer.email
			});

			if (volunteer.member) {
				await this.addBoardMemberToMembers(row.volunteer);
			} else {
				this.ui.showAlert({
					message: __('Warning: This volunteer doesn\'t have an associated member record.'),
					indicator: 'orange'
				}, 5);
			}
		} catch (error) {
			console.error('Error fetching volunteer details:', error);
		}
	}

	onRoleChange(cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.chapter_role && row.is_active) {
			this.checkForDuplicateRoles(row);
		}
	}

	onDateChange(cdt, cdn, dateField) {
		const row = locals[cdt][cdn];

		if (dateField === 'from_date' && row.to_date && row.from_date > row.to_date) {
			this.ui.showError(__('Start date cannot be after end date'));
			frappe.model.set_value(cdt, cdn, 'from_date', row.to_date);
		} else if (dateField === 'to_date' && row.from_date && row.to_date < row.from_date) {
			this.ui.showError(__('End date cannot be before start date'));
			frappe.model.set_value(cdt, cdn, 'to_date', row.from_date);
		}
	}

	onActiveChange(cdt, cdn) {
		const row = locals[cdt][cdn];

		if (row.is_active) {
			this.checkForDuplicateRoles(row);
		} else {
			this.handleBoardMemberDeactivation(row);
		}
	}

	handleBoardMemberDeactivation(row) {
		if (!row.to_date) {
			frappe.model.set_value(row.doctype, row.name, 'to_date', frappe.datetime.get_today());
		}

		this.ui.showAlert({
			message: __('Board member deactivated. End date set to today.'),
			indicator: 'orange'
		}, 5);

		if (row.volunteer) {
			this.updateVolunteerHistory(row);
		}
	}

	async updateVolunteerHistory(boardMember) {
		try {
			const result = await this.api.call('verenigingen.verenigingen.doctype.chapter.chapter.update_volunteer_assignment_history', {
				volunteer_id: boardMember.volunteer,
				chapter_name: this.frm.doc.name,
				role: boardMember.chapter_role,
				start_date: boardMember.from_date,
				end_date: boardMember.to_date || frappe.datetime.get_today()
			});

			if (result) {
				this.ui.showAlert({
					message: __('Board assignment recorded in volunteer history'),
					indicator: 'green'
				}, 3);
			}
		} catch (error) {
			console.error('Error updating volunteer history:', error);
			this.ui.showAlert({
				message: __('Failed to update volunteer history. Please check the logs.'),
				indicator: 'red'
			}, 5);
		}
	}

	handleBoardMembersChange() {
		// Refresh the grid and update selection checkboxes
		this.ui.refreshGrid('board_members');
		setTimeout(() => this.addSelectionCheckboxes(), 100);
	}

	destroy() {
		// Clean up window reference
		delete window._chapterBoardManager;

		// Clear selected members
		this.selectedMembers.clear();

		// Clear references
		this.frm = null;
		this.state = null;
		this.ui = null;
		this.api = null;
	}
}
