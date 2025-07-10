// verenigingen/verenigingen/doctype/chapter/modules/ChapterUI.js

export class ChapterUI {
	constructor(frm, state) {
		this.frm = frm;
		this.state = state;
		this.customButtons = [];
		this.eventHandlers = new Map();
		this.activeDialogs = new Set();

		this.initializeStyles();
	}

	initializeStyles() {
		// Add custom styles if not already present
		if (!$('#chapter-custom-styles').length) {
			$('<style id="chapter-custom-styles">')
				.html(`
                    .board-member-selected { background-color: #e8f4fd !important; }
                    .board-member-checkbox { margin-right: 10px; }
                    .bulk-actions-bar {
                        background: #f8f9fa;
                        padding: 10px;
                        margin-bottom: 10px;
                        border-radius: 4px;
                    }
                    .unreconciled-row {
                        background-color: #f5f7fa;
                        font-style: italic;
                    }
                    .donation-row {
                        background-color: #fcf8e3;
                        font-style: italic;
                    }
                    .chapter-suggestion-container {
                        margin-top: 10px;
                        padding: 10px;
                    }
                    .suggested-chapter {
                        font-weight: bold;
                        color: var(--primary);
                    }
                    .board-memberships {
                        margin-top: 15px;
                        padding: 10px;
                        background: #f8f9fa;
                        border-radius: 4px;
                    }
                    .board-history table {
                        margin-top: 10px;
                    }
                    .chapter-stats .stat-item {
                        text-align: center;
                        padding: 20px;
                        background: white;
                        border-radius: 4px;
                        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                    }
                    .chapter-stats .stat-number {
                        font-size: 2em;
                        font-weight: bold;
                        color: var(--primary);
                    }
                    .chapter-stats .stat-label {
                        color: #6c757d;
                        margin-top: 5px;
                    }
                    .postal-code-preview {
                        margin-top: 10px;
                    }
                    .no-idx-column .row-index {
                        display: none !important;
                    }
                `)
				.appendTo('head');
		}
	}

	clearCustomButtons() {
		this.customButtons = [];
	}

	addButton(label, action, group) {
		this.customButtons.push({ label, action, group });
		this.frm.add_custom_button(label, action, group);
	}

	showBoardMemberships(memberships) {
		if (!memberships || !memberships.length) return;

		let html = '<div class="board-memberships"><h4>' + __('Board Positions') + '</h4><ul>';

		memberships.forEach(board => {
			html += `<li><strong>${board.chapter_role}</strong> at
                     <a href="/app/chapter/${board.parent}">${board.parent}</a></li>`;
		});

		html += '</ul></div>';

		if (this.frm.fields_dict.board_memberships_html) {
			$(this.frm.fields_dict.board_memberships_html.wrapper).html(html);
		}
	}

	updateMembersSummary() {
		if (!this.frm.doc.name) return;

		// Count members from Chapter Member child table instead
		const enabledMembers = this.frm.doc.members?.filter(m => m.enabled) || [];
		const memberCount = enabledMembers.length;

		const $header = this.frm.fields_dict.chapter_members?.$wrapper.find('.form-section-heading');
		if ($header.length) {
			const summary = ` <span class="text-muted">(${memberCount} members)</span>`;

			if ($header.find('.member-count').length) {
				$header.find('.member-count').html(summary);
			} else {
				$header.append(`<span class="member-count">${summary}</span>`);
			}
		}
	}

	updatePostalCodePreview() {
		if (!this.frm.doc.postal_codes) return;

		const $wrapper = this.frm.get_field('postal_codes')?.$wrapper;
		if (!$wrapper) return;

		let $preview = $wrapper.find('.postal-code-preview');
		if (!$preview.length) {
			$preview = $('<div class="postal-code-preview alert alert-info mt-3"></div>');
			$wrapper.append($preview);
		}

		const patterns = this.frm.doc.postal_codes.split(',').map(p => p.trim());
		let html = '<strong>' + __('Chapter covers the following areas:') + '</strong><ul class="mt-2">';

		patterns.forEach(pattern => {
			if (pattern.includes('-')) {
				const [start, end] = pattern.split('-');
				html += `<li>${__('Range: {0} to {1}', [start, end])}</li>`;
			} else if (pattern.includes('*')) {
				const base = pattern.replace('*', '');
				html += `<li>${__('All codes starting with: {0}', [base])}</li>`;
			} else {
				html += `<li>${__('Exact code: {0}', [pattern])}</li>`;
			}
		});

		html += '</ul>';
		$preview.html(html);
	}

	showPostalCodeWarning(invalidPatterns) {
		if (!invalidPatterns || !invalidPatterns.length) return;

		frappe.msgprint({
			title: __('Invalid Postal Code Patterns'),
			indicator: 'orange',
			message: __('The following postal code patterns are invalid and will be ignored: {0}',
				[invalidPatterns.join(', ')])
		});
	}

	toggleBulkActions(visible) {
		const $grid = this.frm.fields_dict.board_members?.grid.wrapper;
		if (!$grid) return;

		const $bulkBar = $grid.find('.bulk-actions-bar');
		if (visible) {
			$bulkBar.show();
		} else {
			$bulkBar.hide();
		}
	}

	showLoadingIndicator(message = __('Loading...')) {
		this.frm.dashboard.set_headline_alert(
			`<div class="text-center">
                <i class="fa fa-spinner fa-spin"></i> ${message}
            </div>`
		);
	}

	hideLoadingIndicator() {
		this.frm.dashboard.clear_headline();
	}

	showAlert(message, indicator = 'green', duration = 5) {
		frappe.show_alert({
			message: message,
			indicator: indicator
		}, duration);
	}

	showError(message, title = __('Error')) {
		frappe.msgprint({
			title: title,
			indicator: 'red',
			message: message
		});
	}

	showDialog(options) {
		const dialog = new frappe.ui.Dialog(options);
		this.activeDialogs.add(dialog);

		// Track dialog closure
		const originalHide = dialog.hide.bind(dialog);
		dialog.hide = () => {
			this.activeDialogs.delete(dialog);
			originalHide();
		};

		dialog.show();
		return dialog;
	}

	confirmAction(message, onConfirm, onCancel) {
		frappe.confirm(message, onConfirm, onCancel);
	}

	promptInput(title, fieldname, fieldtype = 'Data', onSubmit) {
		const dialog = this.showDialog({
			title: title,
			fields: [{
				fieldname: fieldname,
				fieldtype: fieldtype,
				reqd: 1
			}],
			primary_action_label: __('Submit'),
			primary_action: (values) => {
				dialog.hide();
				onSubmit(values[fieldname]);
			}
		});
	}

	addGridButton(gridFieldname, label, action) {
		const grid = this.frm.fields_dict[gridFieldname]?.grid;
		if (grid) {
			grid.add_custom_button(label, action);
		}
	}

	refreshGrid(gridFieldname) {
		const grid = this.frm.fields_dict[gridFieldname]?.grid;
		if (grid) {
			grid.refresh();
		}
	}

	addEventListener(element, event, handler) {
		const key = `${element}-${event}`;

		// Remove any existing handler
		if (this.eventHandlers.has(key)) {
			const oldHandler = this.eventHandlers.get(key);
			$(element).off(event, oldHandler);
		}

		// Add new handler
		this.eventHandlers.set(key, handler);
		$(element).on(event, handler);
	}

	removeEventListener(element, event) {
		const key = `${element}-${event}`;
		if (this.eventHandlers.has(key)) {
			const handler = this.eventHandlers.get(key);
			$(element).off(event, handler);
			this.eventHandlers.delete(key);
		}
	}

	// Format currency value
	formatCurrency(amount) {
		return format_currency(amount, this.frm.doc.currency || 'EUR');
	}

	// Format date value
	formatDate(date) {
		return frappe.datetime.str_to_user(date);
	}

	// Create a progress bar
	showProgress(title, current, total) {
		const percentage = Math.round((current / total) * 100);

		if (!this.progressDialog) {
			this.progressDialog = this.showDialog({
				title: title,
				fields: [{
					fieldtype: 'HTML',
					options: `
                        <div class="progress">
                            <div class="progress-bar" role="progressbar"
                                 style="width: ${percentage}%"
                                 aria-valuenow="${current}"
                                 aria-valuemin="0"
                                 aria-valuemax="${total}">
                                ${percentage}%
                            </div>
                        </div>
                        <p class="text-center mt-2">${current} / ${total}</p>
                    `
				}]
			});
		} else {
			// Update existing progress
			const $progressBar = this.progressDialog.$wrapper.find('.progress-bar');
			$progressBar.css('width', `${percentage}%`).text(`${percentage}%`);
			this.progressDialog.$wrapper.find('.text-center').text(`${current} / ${total}`);
		}

		if (current >= total) {
			setTimeout(() => {
				this.progressDialog.hide();
				this.progressDialog = null;
			}, 1000);
		}
	}

	// Clean up resources
	destroy() {
		// Remove all event listeners
		this.eventHandlers.forEach((handler, key) => {
			const [element, event] = key.split('-');
			$(element).off(event, handler);
		});
		this.eventHandlers.clear();

		// Close all dialogs
		this.activeDialogs.forEach(dialog => {
			dialog.hide();
		});
		this.activeDialogs.clear();

		// Clear references
		this.frm = null;
		this.state = null;
	}
}
