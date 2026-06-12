frappe.pages['chapter-dues-allocation'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Chapter Dues Allocation',
		single_column: true
	});

	page.allocation_tool = new ChapterDuesAllocationTool(page);
};

class ChapterDuesAllocationTool {
	constructor(page) {
		this.page = page;
		this.make();
	}

	make() {
		this.make_form();
		this.make_result_area();
		this.setup_actions();
	}

	make_form() {
		this.form_container = $('<div class="frappe-control">').appendTo(this.page.main);

		this.from_date = frappe.ui.form.make_control({
			parent: this.form_container,
			df: {
				fieldtype: 'Date',
				label: __('From Date'),
				fieldname: 'from_date',
				default: frappe.datetime.month_start(),
				reqd: 1
			},
			render_input: true
		});

		this.to_date = frappe.ui.form.make_control({
			parent: this.form_container,
			df: {
				fieldtype: 'Date',
				label: __('To Date'),
				fieldname: 'to_date',
				default: frappe.datetime.month_end(),
				reqd: 1
			},
			render_input: true
		});

		this.chapter = frappe.ui.form.make_control({
			parent: this.form_container,
			df: {
				fieldtype: 'Link',
				label: __('Chapter (Optional)'),
				fieldname: 'chapter',
				options: 'Chapter'
			},
			render_input: true
		});

		this.company = frappe.ui.form.make_control({
			parent: this.form_container,
			df: {
				fieldtype: 'Link',
				label: __('Company'),
				fieldname: 'company',
				options: 'Company',
				default: frappe.defaults.get_user_default('Company')
			},
			render_input: true
		});

		this.posting_date = frappe.ui.form.make_control({
			parent: this.form_container,
			df: {
				fieldtype: 'Date',
				label: __('Journal Entry Posting Date'),
				fieldname: 'posting_date',
				default: frappe.datetime.get_today(),
				reqd: 1
			},
			render_input: true
		});
	}

	make_result_area() {
		this.result_area = $('<div class="result-area" style="margin-top: 20px;">').appendTo(this.page.main);
	}

	setup_actions() {
		const me = this;

		this.page.set_primary_action(__('Preview Allocation'), () => {
			me.preview_allocation();
		});

		this.page.add_inner_button(__('Generate Journal Entries'), () => {
			me.generate_journal_entries();
		}, __('Actions'));

		this.page.add_inner_button(__('View Chapter Dues Split Report'), () => {
			frappe.set_route('query-report', 'Chapter Dues Split');
		}, __('Reports'));
	}

	get_filters() {
		return {
			from_date: this.from_date.get_value(),
			to_date: this.to_date.get_value(),
			chapter: this.chapter.get_value(),
			company: this.company.get_value()
		};
	}

	preview_allocation() {
		const me = this;
		const filters = this.get_filters();

		if (!filters.from_date || !filters.to_date) {
			frappe.msgprint(__('Please select From Date and To Date'));
			return;
		}

		// Validate date range
		if (filters.from_date > filters.to_date) {
			frappe.msgprint({
				title: __('Invalid Date Range'),
				message: __('From Date cannot be after To Date'),
				indicator: 'red'
			});
			return;
		}

		frappe.call({
			method: 'verenigingen.verenigingen.page.chapter_dues_allocation.chapter_dues_allocation.get_allocation_preview',
			args: filters,
			freeze: true,
			freeze_message: __('Loading allocation preview...'),
			callback(r) {
				if (r.message) {
					try {
						me.render_preview(r.message);
					} catch (error) {
						console.error('Error rendering preview:', error);
						frappe.msgprint({
							title: __('Rendering Error'),
							message: __('Failed to display allocation preview. Check browser console for details.'),
							indicator: 'red'
						});
					}
				} else {
					frappe.msgprint({
						title: __('No Data'),
						message: __('No allocation data returned from server'),
						indicator: 'orange'
					});
				}
			},
			error(r) {
				console.error('API error:', r);

				// Try to extract error message from response
				let error_message = __('Failed to load allocation preview');
				if (r && r.message) {
					error_message = r.message;
				} else if (r && r._server_messages) {
					try {
						const messages = JSON.parse(r._server_messages);
						if (messages && messages.length > 0) {
							const parsed = JSON.parse(messages[0]);
							error_message = parsed.message || error_message;
						}
					} catch (e) {
						// Ignore JSON parse errors
					}
				}

				frappe.msgprint({
					title: __('Error'),
					message: error_message,
					indicator: 'red'
				});
			}
		});
	}

	render_preview(data) {
		// Validate data structure
		if (!data || typeof data !== 'object') {
			throw new Error('Invalid data structure: expected object');
		}

		if (!Array.isArray(data.allocations)) {
			throw new Error('Invalid data structure: allocations must be an array');
		}

		let html = '<div class="allocation-preview">';
		html += `<h4>${__('Allocation Preview')}</h4>`;

		if (data.allocations.length === 0) {
			html += `<p class="text-muted">${__('No dues invoices found for the selected period')}</p>`;
			this.result_area.html(`${html}</div>`);
			return;
		}

		// Validate accounts object exists
		if (!data.accounts || typeof data.accounts !== 'object') {
			console.warn('Missing accounts data in preview response');
			data.accounts = {};
		}

		// Account configuration warning
		if (!data.accounts.chapter_account || !data.accounts.national_account) {
			html += '<div class="alert alert-warning">';
			html += `<strong>${__('Warning')}:</strong> `;
			html += __('Chapter and National Dues Income Accounts are not configured in Verenigingen Settings. ');
			html += __('Please configure these before generating journal entries.');
			html += '</div>';
		}

		// Summary table
		html += '<table class="table table-bordered">';
		html += '<thead><tr>';
		html += `<th>${__('Chapter')}</th>`;
		html += `<th class="text-right">${__('Invoices')}</th>`;
		html += `<th class="text-right">${__('Total Dues')}</th>`;
		html += `<th class="text-right">${__('Chapter %')}</th>`;
		html += `<th class="text-right">${__('Chapter Amount')}</th>`;
		html += `<th class="text-right">${__('National Amount')}</th>`;
		html += '</tr></thead><tbody>';

		data.allocations.forEach((row) => {
			html += '<tr>';
			html += `<td>${row.chapter}</td>`;
			html += `<td class="text-right">${row.invoice_count}</td>`;
			html += `<td class="text-right">${format_currency(row.total_amount)}</td>`;
			html += `<td class="text-right">${row.chapter_percentage.toFixed(1)}%</td>`;
			html += `<td class="text-right">${format_currency(row.chapter_amount)}</td>`;
			html += `<td class="text-right">${format_currency(row.national_amount)}</td>`;
			html += '</tr>';
		});

		// Totals row
		html += '<tr class="font-weight-bold">';
		html += `<td colspan="4">${__('Grand Total')}</td>`;
		html += `<td class="text-right">${format_currency(data.summary.total_chapter_amount)}</td>`;
		html += `<td class="text-right">${format_currency(data.summary.total_national_amount)}</td>`;
		html += '</tr>';

		html += '</tbody></table>';

		// Account info
		if (data.accounts.chapter_account && data.accounts.national_account) {
			html += '<div class="mt-3">';
			html += `<h5>${__('Journal Entry Accounts')}</h5>`;
			html += '<ul>';
			html += `<li><strong>${__('Source')}:</strong> ${data.accounts.source_account || __('Not configured')}</li>`;
			html += `<li><strong>${__('Chapter Account')}:</strong> ${data.accounts.chapter_account}</li>`;
			html += `<li><strong>${__('National Account')}:</strong> ${data.accounts.national_account}</li>`;
			html += '</ul>';
			html += '</div>';
		}

		html += '</div>';

		this.result_area.html(html);
	}

	generate_journal_entries() {
		const me = this;
		const filters = this.get_filters();
		filters.posting_date = this.posting_date.get_value();

		if (!filters.from_date || !filters.to_date || !filters.posting_date) {
			frappe.msgprint(__('Please fill all required fields'));
			return;
		}

		// Validate date range
		if (filters.from_date > filters.to_date) {
			frappe.msgprint({
				title: __('Invalid Date Range'),
				message: __('From Date cannot be after To Date'),
				indicator: 'red'
			});
			return;
		}

		// Validate posting date is not in future (warn only)
		const today = frappe.datetime.get_today();
		if (filters.posting_date > today) {
			frappe.msgprint({
				title: __('Future Posting Date'),
				message: __('Warning: Posting date is in the future. This is allowed but unusual.'),
				indicator: 'orange'
			});
		}

		frappe.confirm(
			__('This will create Journal Entry(s) to allocate membership dues income. Continue?'),
			() => {
				frappe.call({
					method: 'verenigingen.verenigingen.page.chapter_dues_allocation.chapter_dues_allocation.generate_allocation_journal_entries',
					args: filters,
					freeze: true,
					freeze_message: __('Creating journal entries...'),
					callback(r) {
						if (r.message && r.message.success) {
							frappe.msgprint({
								title: __('Success'),
								message: r.message.message,
								indicator: 'green'
							});

							// Show links to created journal entries
							if (r.message.journal_entries && r.message.journal_entries.length > 0) {
								let msg = `${__('Created Journal Entries')}:<br>`;
								r.message.journal_entries.forEach((name) => {
									msg += `<a href="/app/journal-entry/${name}">${name}</a><br>`;
								});
								frappe.msgprint(msg);
							}

							// Refresh preview
							try {
								me.preview_allocation();
							} catch (error) {
								console.error('Error refreshing preview:', error);
								// Don't show error to user - journal entries were created successfully
							}
						} else if (r.message && !r.message.success) {
							// Server returned response but operation failed
							frappe.msgprint({
								title: __('Operation Failed'),
								message: r.message.message || __('Failed to create journal entries'),
								indicator: 'red'
							});
						}
					},
					error(r) {
						console.error('API error:', r);

						// Try to extract error message from response
						let error_message = __('Failed to create journal entries');
						if (r && r.message) {
							error_message = r.message;
						} else if (r && r._server_messages) {
							try {
								const messages = JSON.parse(r._server_messages);
								if (messages && messages.length > 0) {
									const parsed = JSON.parse(messages[0]);
									error_message = parsed.message || error_message;
								}
							} catch (e) {
								// Ignore JSON parse errors
							}
						}

						frappe.msgprint({
							title: __('Error'),
							message: error_message,
							indicator: 'red'
						});
					}
				});
			}
		);
	}
}
