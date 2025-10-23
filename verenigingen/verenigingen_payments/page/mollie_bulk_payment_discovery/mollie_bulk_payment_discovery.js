// Copyright (c) 2025, Molecular Bits and contributors
// For license information, please see license.txt

frappe.pages['mollie-bulk-payment-discovery'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Mollie Bulk Payment Discovery',
		single_column: true
	});

	// Store filter values
	page.filter_values = {
		retrieval_mode: 'balance_transactions',
		days_back: 7,
		date_offset: 0,
		max_members: null
	};

	// Add action buttons
	page.set_primary_action('Run Discovery', function() {
		run_discovery(page);
	});

	page.add_inner_button('Refresh', function() {
		run_discovery(page);
	});

	// Build the page UI
	$(page.body).html(`
		<div class="mollie-discovery-container">
			<div class="filter-section" style="margin-bottom: 20px; padding: 20px; background: #f8f9fa; border-radius: 4px;">
				<h5>Search Filters</h5>
				<div class="row">
					<div class="col-md-3">
						<div class="form-group">
							<label>Search Method</label>
							<select class="form-control" id="retrieval_mode">
								<option value="balance_transactions">By Balance Transactions (systematic)</option>
								<option value="customer">By Member (iterate through each member)</option>
							</select>
						</div>
					</div>
					<div class="col-md-2">
						<div class="form-group">
							<label>Days Back</label>
							<input type="number" class="form-control" id="days_back" value="7" min="1" max="90">
						</div>
					</div>
					<div class="col-md-2">
						<div class="form-group">
							<label>Date Offset (Days)</label>
							<input type="number" class="form-control" id="date_offset" value="0" min="0">
							<small class="text-muted">Start N days ago</small>
						</div>
					</div>
					<div class="col-md-2" id="max_members_wrapper" style="display: none;">
						<div class="form-group">
							<label>Max Members</label>
							<input type="number" class="form-control" id="max_members" value="" min="1">
							<small class="text-muted">Optional limit</small>
						</div>
					</div>
				</div>
			</div>
			<div class="results-summary" style="display: none;"></div>
			<div class="results-table" style="margin-top: 20px;"></div>
		</div>
	`);

	// Handle search method change to show/hide max_members
	$(page.body).on('change', '#retrieval_mode', function() {
		const mode = $(this).val();
		if (mode === 'customer') {
			$('#max_members_wrapper').show();
		} else {
			$('#max_members_wrapper').hide();
		}
	});
};

function run_discovery(page) {
	const filters = {
		retrieval_mode: $('#retrieval_mode').val() || 'balance_transactions',
		days_back: parseInt($('#days_back').val()) || 7,
		date_offset: parseInt($('#date_offset').val()) || 0,
		max_members: $('#max_members').val() ? parseInt($('#max_members').val()) : null
	};

	frappe.dom.freeze(__('Discovering payments...'));

	frappe.call({
		method: 'verenigingen.verenigingen_payments.page.mollie_bulk_payment_discovery.mollie_bulk_payment_discovery.run_discovery',
		args: filters,
		callback: function(r) {
			frappe.dom.unfreeze();

			if (r.message && r.message.success) {
				render_results(page, r.message.data, filters);
			} else {
				frappe.msgprint({
					title: __('Discovery Failed'),
					message: r.message.error || 'Unknown error occurred',
					indicator: 'red'
				});
			}
		},
		error: function(r) {
			frappe.dom.unfreeze();
			frappe.msgprint({
				title: __('Error'),
				message: __('Failed to run discovery. Check error log for details.'),
				indicator: 'red'
			});
		}
	});
}

function render_results(page, data, filters) {
	const $container = $(page.body).find('.mollie-discovery-container');
	const $summary = $container.find('.results-summary');
	const $table = $container.find('.results-table');

	// Render summary
	const orphaned_count = data.orphaned_transactions ? data.orphaned_transactions.length : 0;
	const error_details = data.error_details || [];

	let summary_html = `
		<div style="padding: 15px; background-color: #e7f3ff; border-left: 4px solid #007bff;">
			<h4 style="margin-top: 0;">Discovery Summary</h4>
			<p><strong>Retrieval Mode:</strong> ${data.retrieval_mode}</p>
			<p><strong>Summary:</strong> ${data.summary}</p>

			<h5>Statistics:</h5>
			<ul>
				<li><strong>Total Payments Found:</strong> ${data.total_payments_found || 0}</li>
				<li><strong>New/Unprocessed:</strong> ${data.total_new_payments || 0}</li>
				<li><strong>Orphaned (no member match):</strong> ${orphaned_count}</li>
				<li><strong>Errors:</strong> ${data.errors || 0}</li>
			</ul>
	`;

	// Add error details if any errors occurred
	if (error_details.length > 0) {
		summary_html += `
			<div style="margin-top: 15px; padding: 10px; background-color: #fff3cd; border-left: 3px solid #ffc107;">
				<h5 style="color: #856404; margin-top: 0;">⚠️ Error Details (${error_details.length})</h5>
				<div style="max-height: 200px; overflow-y: auto;">
					<table class="table table-sm" style="margin-bottom: 0;">
						<thead>
							<tr>
								<th>Item</th>
								<th>Step</th>
								<th>Error Message</th>
							</tr>
						</thead>
						<tbody>
		`;

		error_details.forEach(error => {
			// Format item display based on what data is available
			let item_display = '';
			if (error.payment_id) {
				item_display = `Payment: ${error.payment_id}`;
			} else if (error.member) {
				item_display = `Member: ${error.member}`;
				if (error.member_full_name) {
					item_display += ` (${error.member_full_name})`;
				}
			} else {
				item_display = 'Unknown';
			}

			summary_html += `
				<tr>
					<td style="font-family: monospace; font-size: 0.9em;">${item_display}</td>
					<td><code>${error.step || 'unknown'}</code></td>
					<td style="color: #721c24;">${error.error}</td>
				</tr>
			`;
		});

		summary_html += `
						</tbody>
					</table>
				</div>
			</div>
		`;
	}

	summary_html += `
			<p style="margin-top: 15px; color: #6c757d;">
				<em>This is discovery only - no records created. Review results and use
				"Process Payment" button to process selected payments.</em>
			</p>
		</div>
	`;

	$summary.html(summary_html).show();

	// Build payments array from results
	let payments = [];

	if (data.retrieval_mode === 'customer' && data.customers) {
		// Customer mode: extract from customers array
		data.customers.forEach(customer => {
			customer.payments.forEach(payment => {
				if (payment.processable || payment.already_processed) {
					payments.push({
						payment_id: payment.id,
						member: customer.member,
						member_full_name: customer.member_full_name || '',
						status: payment.status,
						amount: payment.amount_display,
						currency: payment.currency,
						payment_type: payment.payment_type,
						paid_at: payment.paid_at,
						already_processed: payment.already_processed ? 'Yes' : 'No',
						payment_entry: payment.payment_entry || '',
						bank_transaction: payment.bank_transaction || '',
						processable: payment.processable ? 'Yes' : 'No'
					});
				}
			});
		});
	} else if (data.retrieval_mode === 'balance_transactions' && data.balance_transactions) {
		// Balance mode: payments data is in balance_transactions array
		// This needs to be extracted from the backend result
		// For now, show message
		payments = [];
	}

	// Add orphaned transactions
	if (data.orphaned_transactions) {
		data.orphaned_transactions.forEach(orphan => {
			payments.push({
				payment_id: orphan.payment_id,
				member: '⚠️ ORPHANED',
				member_full_name: orphan.reason,
				status: orphan.status,
				amount: orphan.amount,
				currency: 'EUR',
				payment_type: orphan.payment_type,
				paid_at: orphan.paid_at,
				already_processed: 'No',
				payment_entry: '',
				bank_transaction: '',
				processable: 'No - Orphaned'
			});
		});
	}

	// Render table
	if (payments.length === 0) {
		$table.html('<p class="text-muted">No payments found.</p>');
		return;
	}

	let html = `
		<table class="table table-bordered">
			<thead>
				<tr>
					<th>Payment ID</th>
					<th>Member</th>
					<th>Member Name</th>
					<th>Status</th>
					<th>Amount</th>
					<th>Type</th>
					<th>Paid At</th>
					<th>Processed</th>
					<th>Processable</th>
					<th>Actions</th>
				</tr>
			</thead>
			<tbody>
	`;

	payments.forEach(payment => {
		const is_orphaned = payment.member === '⚠️ ORPHANED';
		const row_class = is_orphaned ? 'table-danger' : '';

		html += `
			<tr class="${row_class}">
				<td>${payment.payment_id}</td>
				<td>${payment.member}</td>
				<td>${payment.member_full_name}</td>
				<td>${format_status(payment.status)}</td>
				<td>${payment.amount}</td>
				<td>${payment.payment_type}</td>
				<td>${payment.paid_at || ''}</td>
				<td>${format_processed(payment.already_processed)}</td>
				<td>${format_processable(payment.processable)}</td>
				<td>
					${payment.processable === 'Yes' && !is_orphaned ?
						`<button class="btn btn-sm btn-primary process-payment" data-payment-id="${payment.payment_id}">
							Process
						</button>` :
						'<span class="text-muted">N/A</span>'
					}
				</td>
			</tr>
		`;
	});

	html += '</tbody></table>';
	$table.html(html);

	// Attach click handlers
	$table.find('.process-payment').on('click', function() {
		const payment_id = $(this).data('payment-id');
		process_single_payment(payment_id, page);
	});
}

function format_status(status) {
	const colors = {
		'paid': 'success',
		'pending': 'warning',
		'failed': 'danger',
		'expired': 'danger',
		'canceled': 'danger'
	};
	const color = colors[status] || 'secondary';
	return `<span class="badge badge-${color}">${status}</span>`;
}

function format_processed(value) {
	if (value === 'Yes') {
		return '<span style="color: #6c757d;">✓ Yes</span>';
	}
	return '<span style="color: #17a2b8; font-weight: bold;">○ No</span>';
}

function format_processable(value) {
	if (value === 'Yes') {
		return '<span style="color: #28a745; font-weight: bold;">✓ Yes</span>';
	} else if (value && value.includes('Orphaned')) {
		return '<span style="color: #dc3545; font-weight: bold;">✗ ' + value + '</span>';
	}
	return '<span style="color: #6c757d;">✗ No</span>';
}

function process_single_payment(payment_id, page) {
	frappe.confirm(
		__('Process payment {0}?', [payment_id]),
		function() {
			frappe.dom.freeze(__('Processing payment...'));

			frappe.call({
				method: 'verenigingen.verenigingen_payments.page.mollie_bulk_payment_discovery.mollie_bulk_payment_discovery.process_payment',
				args: {
					payment_id: payment_id
				},
				callback: function(r) {
					frappe.dom.unfreeze();

					if (r.message && r.message.success) {
						frappe.msgprint({
							title: __('Success'),
							message: __('Payment processed successfully'),
							indicator: 'green'
						});
						// Refresh the results
						run_discovery(page);
					} else {
						frappe.msgprint({
							title: __('Processing Failed'),
							message: r.message.error || r.message.data.error || 'Unknown error',
							indicator: 'red'
						});
					}
				}
			});
		}
	);
}
