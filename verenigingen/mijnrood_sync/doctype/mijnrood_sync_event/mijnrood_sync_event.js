// MijnRood Sync Event — rich diff rendering and review actions

// Field labels for display (mirrors Python MIJNROOD_FIELD_LABELS)
const FIELD_LABELS = {
	id: 'MijnRood ID',
	first_name: 'First Name',
	middle_name: 'Middle Name',
	last_name: 'Last Name',
	email: 'Email',
	phone: 'Phone',
	iban: 'IBAN',
	address: 'Address',
	city: 'City',
	post_code: 'Postal Code',
	country: 'Country',
	date_of_birth: 'Date of Birth',
	division_id: 'Chapter',
	registration_time: 'Registration Date',
	current_membership_status_id: 'Membership Status',
	contribution_per_period_in_cents: 'Contribution (cents/period)',
	contribution_period: 'Payment Period',
	mollie_customer_id: 'Mollie Customer ID',
	mollie_subscription_id: 'Mollie Subscription ID',
	roles: 'Roles',
	accept_use_personal_information: 'Privacy Consent',
	comments: 'Comments',
	original_id: 'Original Member ID',
	original_registration_time: 'Original Registration Date',
	name: 'Division Name',
	email_id: 'Division Email',
	facebook: 'Facebook',
	instagram: 'Instagram',
	twitter: 'Twitter',
	can_be_selected_on_application: 'Selectable on Application',
	preferred_division_id: 'Preferred Chapter',
	paid: 'Paid',
	has_sent_initial_email: 'Initial Email Sent'
};

// Key fields to show prominently in New record summary cards
const MEMBER_SUMMARY_FIELDS = [
	'first_name', 'middle_name', 'last_name', 'email', 'phone',
	'address', 'city', 'post_code', 'country',
	'division_id', 'current_membership_status_id',
	'contribution_per_period_in_cents', 'contribution_period', 'date_of_birth',
	'iban', 'registration_time',
	'mollie_customer_id', 'mollie_subscription_id',
	'comments'
];

const APPLICATION_SUMMARY_FIELDS = [
	'first_name', 'middle_name', 'last_name', 'email', 'phone',
	'address', 'city', 'post_code', 'country',
	'preferred_division_id', 'contribution_per_period_in_cents', 'contribution_period',
	'date_of_birth', 'iban', 'registration_time',
	'mollie_customer_id',
	'paid', 'has_sent_initial_email'
];

const DIVISION_SUMMARY_FIELDS = [
	'name', 'city', 'email_id', 'phone',
	'address', 'post_code',
	'facebook', 'instagram', 'twitter',
	'can_be_selected_on_application'
];

// Status mapping loaded from MijnRood Sync Settings (configurable child table).
// Cached after first load to avoid repeated server calls.
let _status_mapping_cache = null;

function load_status_mapping(callback) {
	if (_status_mapping_cache) {
		callback(_status_mapping_cache);
		return;
	}
	frappe.call({
		method: 'verenigingen.mijnrood_sync.doctype.mijnrood_sync_settings.mijnrood_sync_settings.get_status_mapping_for_client',
		async: true,
		callback(r) {
			_status_mapping_cache = r.message || {};
			callback(_status_mapping_cache);
		},
		error() {
			_status_mapping_cache = {};
			callback(_status_mapping_cache);
		}
	});
}

function get_status_label(status_id) {
	if (!_status_mapping_cache) { return String(status_id); }
	const entry = _status_mapping_cache[String(status_id)];
	return entry ? entry.label : String(status_id);
}

function is_terminated_status(status_id) {
	if (!_status_mapping_cache) { return false; }
	const entry = _status_mapping_cache[String(status_id)];
	return entry ? entry.is_terminated : false;
}

function get_label(field) {
	return FIELD_LABELS[field] || field;
}

/**
 * Resolve raw DB values to display values for known special fields.
 * Used in the New record card where we only have raw new_data.
 */
function resolve_display_value(field, val) {
	if (val === null || val === undefined || val === '') { return ''; }
	if (field === 'current_membership_status_id') {
		const int_val = parseInt(val, 10);
		return get_status_label(int_val);
	}
	if (field === 'contribution_period') {
		const period_map = { 0: 'Maandelijks (Monthly)', 1: 'Per kwartaal (Quarterly)', 2: 'Jaarlijks (Annually)' };
		const period_int = parseInt(val, 10);
		return period_map[period_int] || String(val);
	}
	return String(val);
}

function esc(val) {
	if (val === null || val === undefined || val === '') { return ''; }
	const s = String(val);
	const div = document.createElement('div');
	div.appendChild(document.createTextNode(s));
	return div.innerHTML;
}

function truncate(val, max_len) {
	if (!val) { return ''; }
	const s = String(val);
	if (s.length > max_len) { return `${s.substring(0, max_len)}\u2026`; }
	return s;
}

/**
 * Build a color-coded diff table for Changed events.
 */
function render_changed_table(changed_fields) {
	if (!changed_fields || !changed_fields.length) {
		return '<p class="text-muted">No field changes detected.</p>';
	}

	let html = '<table class="table table-bordered table-sm" style="margin-top:10px">';
	html += '<thead><tr>'
        + '<th style="width:25%">Field</th>'
        + '<th style="width:37%">Old Value</th>'
        + '<th style="width:37%">New Value</th>'
        + '</tr></thead><tbody>';

	for (let i = 0; i < changed_fields.length; i++) {
		const c = changed_fields[i];
		const label = c.label || get_label(c.field);
		const old_val = c.old_display || resolve_display_value(c.field, c.old);
		const new_val = c.new_display || resolve_display_value(c.field, c.new);

		html += `<tr>`
            + `<td><strong>${esc(label)}</strong></td>`
            + `<td style="background-color:#fff0f0; color:#a94442">${
            	esc(truncate(old_val, 120))}</td>`
            + `<td style="background-color:#f0fff0; color:#3c763d">${
            	esc(truncate(new_val, 120))}</td>`
            + `</tr>`;
	}

	html += '</tbody></table>';
	return html;
}

/**
 * Build a summary card for New record events.
 */
function render_new_card(table, new_data) {
	if (!new_data) {
		return '<p class="text-muted">No data available.</p>';
	}

	let fields = MEMBER_SUMMARY_FIELDS;
	if (table === 'admin_division') {
		fields = DIVISION_SUMMARY_FIELDS;
	} else if (table === 'admin_membership_application') {
		fields = APPLICATION_SUMMARY_FIELDS;
	}

	// Build name header
	let name_parts = [];
	if (new_data.first_name) { name_parts.push(new_data.first_name); }
	if (new_data.middle_name) { name_parts.push(new_data.middle_name); }
	if (new_data.last_name) { name_parts.push(new_data.last_name); }
	if (table === 'admin_division' && new_data.name) {
		name_parts = [new_data.name];
	}
	const display_name = name_parts.join(' ') || 'Unknown';

	let html = '<div style="border:1px solid #d1d8dd; border-radius:4px; padding:15px; margin-top:10px; background:#fafbfc">';
	html += `<h5 style="margin-top:0">${esc(display_name)}</h5>`;
	html += '<table class="table table-sm" style="margin-bottom:0">';

	for (let i = 0; i < fields.length; i++) {
		const field = fields[i];
		const val = new_data[field];
		if (val === null || val === undefined || val === '') { continue; }

		// Skip name fields already shown in header
		if (table !== 'admin_division' && (field === 'first_name' || field === 'middle_name' || field === 'last_name')) { continue; }
		if (table === 'admin_division' && field === 'name') { continue; }

		const display_val = resolve_display_value(field, val);

		html += `<tr>`
            + `<td style='width:35%; color:#6c757d'><strong>${esc(get_label(field))}</strong></td>`
            + `<td>${esc(truncate(display_val, 120))}</td>`
            + `</tr>`;
	}

	html += '</table></div>';
	return html;
}

/**
 * Build a three-column comparison table: Field | Current Frappe | Proposed MijnRood | Status
 */
function render_comparison_table(changed_fields, frappe_data) {
	if (!changed_fields || !changed_fields.length) { return ''; }

	let html = '<h6 style="margin-top:15px">Comparison with Current Frappe Data</h6>';
	html += '<table class="table table-bordered table-sm">';
	html += '<thead><tr>'
        + '<th style="width:20%">Field</th>'
        + '<th style="width:25%">Current (Frappe)</th>'
        + '<th style="width:25%">Proposed (MijnRood)</th>'
        + '<th style="width:15%">Status</th>'
        + '</tr></thead><tbody>';

	for (let i = 0; i < changed_fields.length; i++) {
		const c = changed_fields[i];
		const label = c.label || get_label(c.field);
		const proposed = c.new_display || c.new;
		const current = frappe_data[c.field] || '';

		// Determine if already applied
		const proposed_str = String(proposed || '');
		const current_str = String(current || '');
		const already_applied = proposed_str === current_str;

		var status_html;
		if (already_applied) {
			status_html = '<span class="indicator-pill green">Already applied</span>';
		} else {
			status_html = '<span class="indicator-pill orange">Needs update</span>';
		}

		html += `<tr>`
            + `<td><strong>${esc(label)}</strong></td>`
            + `<td>${esc(truncate(current, 80))}</td>`
            + `<td>${esc(truncate(proposed, 80))}</td>`
            + `<td>${status_html}</td>`
            + `</tr>`;
	}

	html += '</tbody></table>';
	return html;
}

/**
 * Render a summary for Deleted events.
 */
function render_deleted_card(table, old_data) {
	if (!old_data) {
		return '<p class="text-muted">No data available for deleted record.</p>';
	}

	let name_parts = [];
	if (old_data.first_name) { name_parts.push(old_data.first_name); }
	if (old_data.middle_name) { name_parts.push(old_data.middle_name); }
	if (old_data.last_name) { name_parts.push(old_data.last_name); }
	if (table === 'admin_division' && old_data.name) {
		name_parts = [old_data.name];
	}
	const display_name = name_parts.join(' ') || 'Unknown';

	let html = '<div style="border:1px solid #f5c6cb; border-radius:4px; padding:15px; margin-top:10px; background:#fff5f5">';
	html += `<h5 style="margin-top:0; color:#a94442">Deleted: ${esc(display_name)}</h5>`;

	const details = [];
	if (old_data.email) { details.push(`Email: ${old_data.email}`); }
	if (old_data.city) { details.push(`City: ${old_data.city}`); }
	if (old_data.id) { details.push(`MijnRood ID: ${old_data.id}`); }

	if (details.length) {
		html += `<p class="text-muted" style="margin-bottom:0">${esc(details.join(' | '))}</p>`;
	}

	html += '</div>';
	return html;
}

function safe_parse_json(val) {
	if (!val) { return null; }
	if (typeof val === 'object') { return val; }
	try {
		return JSON.parse(val);
	} catch (e) {
		return null;
	}
}


// ─── Frappe form event handlers ──────────────────────────────────

frappe.ui.form.on('MijnRood Sync Event', {
	refresh(frm) {
		// Action buttons for Pending events
		if (frm.doc.status === 'Pending') {
			frm.add_custom_button(__('Approve'), () => {
				frappe.call({
					method: 'approve',
					doc: frm.doc,
					callback() {
						frm.reload_doc();
					}
				});
			}, __('Actions'));

			frm.add_custom_button(__('Reject'), () => {
				frappe.call({
					method: 'reject',
					doc: frm.doc,
					callback() {
						frm.reload_doc();
					}
				});
			}, __('Actions'));

			frm.add_custom_button(__('Ignore'), () => {
				frappe.call({
					method: 'ignore_event',
					doc: frm.doc,
					callback() {
						frm.reload_doc();
					}
				});
			}, __('Actions'));

			frm.add_custom_button(__('Approve & Apply'), () => {
				frappe.confirm(
					__('Approve and immediately apply this change? This will modify member data.'),
					() => {
						frappe.call({
							method: 'approve_and_apply',
							doc: frm.doc,
							freeze: true,
							freeze_message: __('Approving and applying...'),
							callback(r) {
								if (r.message && r.message.success) {
									frappe.show_alert({
										message: __('Changes approved and applied'),
										indicator: 'green'
									});
								} else {
									frappe.msgprint({
										title: __('Application Failed'),
										indicator: 'red',
										message: r.message ? r.message.message : __('Unknown error')
									});
								}
								frm.reload_doc();
							}
						});
					}
				);
			}).addClass('btn-primary');
		}

		// Apply button for Approved events
		if (frm.doc.status === 'Approved') {
			frm.add_custom_button(__('Apply'), () => {
				frappe.confirm(
					__('Apply this change to Verenigingen? This will modify member data.'),
					() => {
						frappe.call({
							method: 'apply_event',
							doc: frm.doc,
							freeze: true,
							freeze_message: __('Applying changes...'),
							callback(r) {
								if (r.message && r.message.success) {
									frappe.show_alert({
										message: __('Changes applied successfully'),
										indicator: 'green'
									});
								} else {
									frappe.msgprint({
										title: __('Application Failed'),
										indicator: 'red',
										message: r.message ? r.message.message : __('Unknown error')
									});
								}
								frm.reload_doc();
							}
						});
					}
				);
			}).addClass('btn-primary');
		}

		// Color-code the status indicator
		const status_colors = {
			Pending: 'orange',
			Approved: 'blue',
			Applied: 'green',
			Rejected: 'red',
			Ignored: 'grey'
		};
		if (status_colors[frm.doc.status]) {
			frm.page.set_indicator(__(frm.doc.status), status_colors[frm.doc.status]);
		}

		// Load status mapping then render rich change details
		load_status_mapping(() => {
			render_change_details(frm);
		});
	}
});

/**
 * Compute a list of human-readable implications describing what will happen
 * when this event is applied.
 */
function compute_implications(event_type, table, new_data, changed_fields) {
	const items = [];

	if (event_type === 'New') {
		if (table === 'admin_member') {
			items.push('Will create a new active Member via import service');
		} else if (table === 'admin_membership_application') {
			items.push('Will create a new pending membership application');
			if (new_data && new_data.preferred_division_id) {
				items.push(`Will assign to preferred chapter (Division ID ${new_data.preferred_division_id})`);
			}
		} else if (table === 'admin_division') {
			const div_name = (new_data && new_data.name) ? new_data.name : 'unknown';
			items.push(`Will create/update Chapter '${div_name}'`);
		}
	} else if (event_type === 'Changed') {
		if (!Array.isArray(changed_fields) || !changed_fields.length) { return items; }

		if (table === 'admin_member') {
			let has_status_change = false;
			let has_division_change = false;
			let other_field_count = 0;

			for (let i = 0; i < changed_fields.length; i++) {
				const c = changed_fields[i];
				if (c.field === 'current_membership_status_id') {
					has_status_change = true;
					const new_id = parseInt(c.new, 10);
					if (is_terminated_status(new_id)) {
						const type_label = get_status_label(new_id);
						items.push(`Will create and execute a Membership Termination Request (${type_label})`);
					} else {
						const new_label = c.new_display || get_status_label(new_id);
						items.push(`Will update membership status to ${new_label}`);
					}
				} else if (c.field === 'division_id') {
					has_division_change = true;
					const chapter_name = c.new_display || (`Division ID ${c.new}`);
					items.push(`Will transfer member to chapter '${chapter_name}'`);
				} else {
					other_field_count++;
				}
			}
			if (other_field_count > 0) {
				items.push(`Will update ${other_field_count} member field(s) via import service`);
			}
		} else if (table === 'admin_membership_application') {
			let has_div_change = false;
			let app_field_count = 0;

			for (let j = 0; j < changed_fields.length; j++) {
				const cf = changed_fields[j];
				if (cf.field === 'preferred_division_id') {
					has_div_change = true;
					const ch_name = cf.new_display || (`Division ID ${cf.new}`);
					items.push(`Will reassign to preferred chapter '${ch_name}'`);
				} else {
					app_field_count++;
				}
			}
			if (app_field_count > 0) {
				items.push(`Will update ${app_field_count} pending application field(s)`);
			}
		} else if (table === 'admin_division') {
			items.push('Will update Chapter fields');
		}
	} else if (event_type === 'Deleted') {
		items.push('Deleted events require manual review (no auto-action)');
	}

	return items;
}

/**
 * Render an implications panel as an alert-info box with bullet list.
 */
function render_implications(event_type, table, new_data, changed_fields) {
	const items = compute_implications(event_type, table, new_data, changed_fields);
	if (!items.length) { return ''; }

	let html = '<div class="alert alert-info" style="margin-top:10px; margin-bottom:10px">';
	html += '<strong>What will happen</strong>';
	html += '<ul style="margin-bottom:0; margin-top:5px">';
	for (let i = 0; i < items.length; i++) {
		html += `<li>${esc(items[i])}</li>`;
	}
	html += '</ul></div>';
	return html;
}

function render_change_details(frm) {
	const wrapper = frm.fields_dict.change_detail_html;
	if (!wrapper) { return; }

	const event_type = frm.doc.event_type;
	const table = frm.doc.mijnrood_table;
	const changed_fields = safe_parse_json(frm.doc.changed_fields);
	const new_data = safe_parse_json(frm.doc.new_data);
	const old_data = safe_parse_json(frm.doc.old_data);

	let html = '';

	// Implications panel — shows what will happen when event is applied
	html += render_implications(event_type, table, new_data, changed_fields);

	if (event_type === 'Changed') {
		html += render_changed_table(changed_fields);

		// If there's a linked member, fetch comparison data
		if (frm.doc.linked_member && changed_fields && changed_fields.length) {
			html += '<div class="member-comparison-container">'
                + '<p class="text-muted">Loading Frappe comparison data...</p>'
                + '</div>';
			wrapper.$wrapper.html(html);

			frappe.call({
				method: 'verenigingen.mijnrood_sync.doctype.mijnrood_sync_event.mijnrood_sync_event.get_member_comparison_data',
				args: { event_name: frm.doc.name },
				callback(r) {
					if (r.message) {
						const comparison_html = render_comparison_table(changed_fields, r.message);
						wrapper.$wrapper.find('.member-comparison-container').html(comparison_html);
					} else {
						wrapper.$wrapper.find('.member-comparison-container').html('');
					}
				},
				error() {
					wrapper.$wrapper.find('.member-comparison-container').html(
						'<p class="text-muted">Could not load comparison data.</p>'
					);
				}
			});
			return;
		}
	} else if (event_type === 'New') {
		html += render_new_card(table, new_data);
	} else if (event_type === 'Deleted') {
		html += render_deleted_card(table, old_data);
	}

	wrapper.$wrapper.html(html);
}
