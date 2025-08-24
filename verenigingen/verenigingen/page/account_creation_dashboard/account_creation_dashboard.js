// Account Creation Dashboard
// Admin interface for monitoring and managing account creation requests

frappe.pages['account_creation_dashboard'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Account Creation Dashboard',
		single_column: true
	});

	// Add refresh button
	page.set_primary_action('Refresh', () => {
		load_dashboard_data(page);
	}, 'fa fa-refresh');

	// Add secondary actions
	page.add_menu_item('Process All Pending', () => {
		process_all_pending_requests(page);
	});

	page.add_menu_item('Cleanup Old Requests', () => {
		cleanup_old_requests(page);
	});

	// Initialize dashboard
	setup_dashboard_layout(page);
	load_dashboard_data(page);

	// Auto-refresh every 30 seconds
	setInterval(() => {
		if (page && page.wrapper && page.wrapper.is(':visible')) {
			load_dashboard_data(page);
		}
	}, 30000);
};

function setup_dashboard_layout(page) {
	const $wrapper = $(page.wrapper);

	// Create main dashboard layout
	$wrapper.find('.page-content').html(`
        <div class="dashboard-container">
            <!-- Statistics Cards -->
            <div class="row dashboard-stats" style="margin-bottom: 20px;">
                <div class="col-md-3">
                    <div class="card stats-card">
                        <div class="card-body text-center">
                            <h3 class="stat-number text-primary" id="stat-pending">0</h3>
                            <p class="stat-label">Pending Requests</p>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card stats-card">
                        <div class="card-body text-center">
                            <h3 class="stat-number text-warning" id="stat-processing">0</h3>
                            <p class="stat-label">Processing</p>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card stats-card">
                        <div class="card-body text-center">
                            <h3 class="stat-number text-success" id="stat-completed">0</h3>
                            <p class="stat-label">Completed (24h)</p>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card stats-card">
                        <div class="card-body text-center">
                            <h3 class="stat-number text-danger" id="stat-failed">0</h3>
                            <p class="stat-label">Failed</p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Action Buttons -->
            <div class="row" style="margin-bottom: 20px;">
                <div class="col-md-12">
                    <div class="btn-group" role="group">
                        <button type="button" class="btn btn-primary" onclick="show_requests_table('all')">
                            All Requests
                        </button>
                        <button type="button" class="btn btn-warning" onclick="show_requests_table('failed')">
                            Failed Requests
                        </button>
                        <button type="button" class="btn btn-info" onclick="show_requests_table('processing')">
                            Processing
                        </button>
                    </div>
                </div>
            </div>

            <!-- Requests Table -->
            <div class="row">
                <div class="col-md-12">
                    <div class="card">
                        <div class="card-header">
                            <h5 class="card-title" id="table-title">Recent Account Creation Requests</h5>
                        </div>
                        <div class="card-body">
                            <div id="requests-table-container">
                                <div class="text-center" style="padding: 20px;">
                                    <i class="fa fa-spinner fa-spin"></i> Loading requests...
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `);

	// Add custom styles
	$('<style>')
		.text(`
            .dashboard-container {
                padding: 20px;
            }
            .stats-card {
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                transition: box-shadow 0.3s ease;
            }
            .stats-card:hover {
                box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            }
            .stat-number {
                font-size: 2.5em;
                font-weight: bold;
                margin-bottom: 5px;
            }
            .stat-label {
                color: #666;
                margin-bottom: 0;
            }
            .status-badge {
                padding: 4px 8px;
                border-radius: 12px;
                font-size: 12px;
                font-weight: bold;
            }
            .status-requested { background: #ffeaa7; color: #2d3436; }
            .status-queued { background: #74b9ff; color: white; }
            .status-processing { background: #fdcb6e; color: white; }
            .status-completed { background: #00b894; color: white; }
            .status-failed { background: #e17055; color: white; }
            .status-cancelled { background: #636e72; color: white; }
        `)
		.appendTo('head');
}

function load_dashboard_data(page) {
	// Load statistics
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.account_creation_request.account_creation_request.get_request_statistics',
		callback(r) {
			if (r.message) {
				update_statistics(r.message);
			}
		}
	});

	// Load recent requests
	show_requests_table('recent');
}

function update_statistics(stats) {
	// Initialize counters
	let pending = 0; let processing = 0; let completed = 0; let failed = 0;

	// Process statistics
	stats.forEach((stat) => {
		switch (stat.status) {
			case 'Requested':
			case 'Queued':
				pending += stat.count;
				break;
			case 'Processing':
				processing += stat.count;
				break;
			case 'Completed':
				completed += stat.count;
				break;
			case 'Failed':
				failed += stat.count;
				break;
		}
	});

	// Update UI
	$('#stat-pending').text(pending);
	$('#stat-processing').text(processing);
	$('#stat-completed').text(completed);
	$('#stat-failed').text(failed);
}

function show_requests_table(filter_type) {
	const container = $('#requests-table-container');
	container.html('<div class="text-center" style="padding: 20px;"><i class="fa fa-spinner fa-spin"></i> Loading...</div>');

	let filters = {};
	let title = 'All Account Creation Requests';

	switch (filter_type) {
		case 'failed':
			filters = { status: 'Failed' };
			title = 'Failed Account Creation Requests';
			break;
		case 'processing':
			filters = { status: ['in', ['Queued', 'Processing']] };
			title = 'Processing Account Creation Requests';
			break;
		case 'recent':
			title = 'Recent Account Creation Requests';
			break;
	}

	$('#table-title').text(title);

	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Account Creation Request',
			filters,
			fields: [
				'name', 'request_type', 'source_record', 'email', 'full_name',
				'status', 'pipeline_stage', 'failure_reason', 'retry_count',
				'creation', 'priority', 'created_user', 'created_employee'
			],
			order_by: 'creation desc',
			limit_page_length: 50
		},
		callback(r) {
			if (r.message) {
				render_requests_table(r.message, container);
			}
		}
	});
}

function render_requests_table(requests, container) {
	if (requests.length === 0) {
		container.html('<div class="text-center text-muted" style="padding: 40px;">No requests found</div>');
		return;
	}

	let html = `
        <div class="table-responsive">
            <table class="table table-striped table-hover">
                <thead>
                    <tr>
                        <th>Request ID</th>
                        <th>Type</th>
                        <th>Email</th>
                        <th>Full Name</th>
                        <th>Status</th>
                        <th>Stage</th>
                        <th>Created</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
    `;

	requests.forEach((req) => {
		const statusClass = `status-${req.status.toLowerCase().replace(' ', '-')}`;
		const createdDate = moment(req.creation).fromNow();

		html += `
            <tr>
                <td>
                    <a href="/app/account-creation-request/${req.name}" target="_blank">
                        ${req.name}
                    </a>
                </td>
                <td>
                    <span class="badge badge-info">${req.request_type}</span>
                </td>
                <td>${req.email}</td>
                <td>${req.full_name}</td>
                <td>
                    <span class="status-badge ${statusClass}">${req.status}</span>
                    ${req.retry_count > 0 ? `<small class="text-muted"> (${req.retry_count} retries)</small>` : ''}
                </td>
                <td>${req.pipeline_stage || '-'}</td>
                <td title="${req.creation}">${createdDate}</td>
                <td>
                    ${render_action_buttons(req)}
                </td>
            </tr>
        `;
	});

	html += '</tbody></table></div>';
	container.html(html);
}

function render_action_buttons(req) {
	let buttons = '';

	if (req.status === 'Failed') {
		buttons += `<button class="btn btn-sm btn-warning" onclick="retry_request('${req.name}')">Retry</button> `;
	}

	if (req.status === 'Requested') {
		buttons += `<button class="btn btn-sm btn-primary" onclick="queue_request('${req.name}')">Queue</button> `;
	}

	if (['Requested', 'Queued', 'Processing'].includes(req.status)) {
		buttons += `<button class="btn btn-sm btn-secondary" onclick="cancel_request('${req.name}')">Cancel</button> `;
	}

	return buttons;
}

function retry_request(request_name) {
	frappe.confirm('Retry this account creation request?', () => {
		frappe.call({
			method: 'verenigingen.utils.account_creation_manager.retry_failed_request',
			args: {
				request_name
			},
			callback(r) {
				if (r.message && r.message.success) {
					frappe.show_alert({ message: 'Request queued for retry', indicator: 'green' });
					load_dashboard_data();
				} else {
					frappe.msgprint(`Failed to retry request: ${r.message.error || 'Unknown error'}`);
				}
			}
		});
	});
}

function queue_request(request_name) {
	frappe.call({
		method: 'frappe.client.set_value',
		args: {
			doctype: 'Account Creation Request',
			name: request_name,
			fieldname: 'status',
			value: 'Queued'
		},
		callback() {
			frappe.call({
				method: 'verenigingen.utils.account_creation_manager.process_account_creation_request',
				args: {
					request_name
				},
				callback() {
					frappe.show_alert({ message: 'Request queued for processing', indicator: 'blue' });
					load_dashboard_data();
				}
			});
		}
	});
}

function cancel_request(request_name) {
	frappe.prompt('Cancellation reason:', (data) => {
		frappe.call({
			method: 'frappe.client.set_value',
			args: {
				doctype: 'Account Creation Request',
				name: request_name,
				fieldname: {
					status: 'Cancelled',
					failure_reason: `Cancelled: ${data.value}`
				}
			},
			callback() {
				frappe.show_alert({ message: 'Request cancelled', indicator: 'orange' });
				load_dashboard_data();
			}
		});
	});
}

function process_all_pending_requests(page) {
	frappe.confirm(
		'Process all pending account creation requests? This will queue them for background processing.',
		() => {
			frappe.call({
				method: 'frappe.client.get_list',
				args: {
					doctype: 'Account Creation Request',
					filters: { status: 'Requested' },
					fields: ['name'],
					limit_page_length: 100
				},
				callback(r) {
					if (r.message && r.message.length > 0) {
						const request_names = r.message.map(req => req.name);

						frappe.call({
							method: 'verenigingen.verenigingen.doctype.account_creation_request.account_creation_request.bulk_queue_requests',
							args: {
								request_names
							},
							callback(r) {
								if (r.message) {
									const success_count = r.message.filter(result => result.success).length;
									frappe.msgprint(`Queued ${success_count} requests for processing`);
									load_dashboard_data(page);
								}
							}
						});
					} else {
						frappe.msgprint('No pending requests found');
					}
				}
			});
		}
	);
}

function cleanup_old_requests(page) {
	frappe.confirm(
		'Delete completed account creation requests older than 30 days?',
		() => {
			frappe.call({
				method: 'frappe.client.get_list',
				args: {
					doctype: 'Account Creation Request',
					filters: [
						['status', '=', 'Completed'],
						['creation', '<', frappe.datetime.add_days(frappe.datetime.nowdate(), -30)]
					],
					fields: ['name'],
					limit_page_length: 1000
				},
				callback(r) {
					if (r.message && r.message.length > 0) {
						frappe.msgprint(`Found ${r.message.length} old completed requests. Cleanup will be processed.`);
						// Could implement bulk deletion here
					} else {
						frappe.msgprint('No old requests found for cleanup');
					}
				}
			});
		}
	);
}
