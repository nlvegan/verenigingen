// Mollie Settings Client-side JavaScript
// Provides form enhancements, validation, and user interface features

frappe.ui.form.on('Mollie Settings', {
	refresh(frm) {
		// Add custom buttons and form enhancements
		add_custom_buttons(frm);
		setup_form_indicators(frm);

		// Render credentials status + secret-setting buttons. The actual
		// Password fields are `hidden: 1` in the DocType so browsers can't
		// autofill them or prompt to save on form save.
		render_credentials_status(frm);
		add_credential_buttons(frm);

		// Suppress autofill on adjacent non-Password fields (profile_id,
		// organization_id) that browsers' "looks like a login form"
		// heuristics may otherwise target.
		verenigingen.suppressPasswordAutofill(frm, ['profile_id', 'organization_id']);
	},

	test_mode(frm) {
		// Show warning when test mode is enabled
		if (frm.doc.test_mode) {
			frm.dashboard.add_comment(
				__(
					'Test Mode is enabled. Test API key will be used and no real transactions will be processed.'
				),
				'orange',
				true
			);
		} else {
			frm.dashboard.add_comment(
				__(
					'Live Mode is active. Live API key will be used for real transactions.'
				),
				'red',
				true
			);
		}
		// Refresh buttons and indicators when mode changes
		add_custom_buttons(frm);
		setup_form_indicators(frm);
	},

	test_secret_key(frm) {
		// Validate test secret key format
		if (frm.doc.test_secret_key) {
			validate_key_format(frm, frm.doc.test_secret_key, 'test');
		}
	},

	live_secret_key(frm) {
		// Validate live secret key format
		if (frm.doc.live_secret_key) {
			validate_key_format(frm, frm.doc.live_secret_key, 'live');
		}
	},

	profile_id(frm) {
		// Validate profile ID format
		if (frm.doc.profile_id) {
			validate_profile_id_format(frm);
		}
	}
});

function add_custom_buttons(frm) {
	// Clear existing custom buttons
	frm.clear_custom_buttons();

	// Check if we have the required configuration for current mode
	const has_required_key = frm.doc.test_mode
		? frm.doc.test_secret_key
		: frm.doc.live_secret_key;

	// Add Test Connection button
	if (frm.doc.name && frm.doc.profile_id && has_required_key) {
		frm.add_custom_button(
			__('Test Connection'),
			() => {
				test_mollie_connection(frm);
			},
			__('Actions')
		);
	}

	// Add View Documentation button
	frm.add_custom_button(
		__('Mollie Documentation'),
		() => {
			window.open('https://docs.mollie.com/', '_blank');
		},
		__('Help')
	);

	// Add Dashboard button if profile_id exists
	if (frm.doc.profile_id) {
		frm.add_custom_button(
			__('Mollie Dashboard'),
			() => {
				window.open('https://www.mollie.com/dashboard', '_blank');
			},
			__('Help')
		);
	}
}

function setup_form_indicators(frm) {
	// Clear existing dashboard content
	frm.dashboard.clear_headline();

	// Show test mode indicator
	if (frm.doc.test_mode) {
		frm.dashboard.set_headline_alert(
			__('Test Mode Active - No real transactions will be processed'),
			'orange'
		);
	} else {
		frm.dashboard.set_headline_alert(
			__('Live Mode Active - Real transactions will be processed'),
			'red'
		);
	}

	// Show configuration status based on current mode
	const has_required_key = frm.doc.test_mode
		? frm.doc.test_secret_key
		: frm.doc.live_secret_key;
	const mode = frm.doc.test_mode ? 'Test' : 'Live';

	if (frm.doc.name && frm.doc.profile_id && has_required_key) {
		frm.dashboard.add_indicator(__(`${mode} Mode Configured`), 'green');
	} else {
		frm.dashboard.add_indicator(__(`${mode} Mode Incomplete`), 'red');
	}

	// Show key availability
	if (frm.doc.test_secret_key) {
		frm.dashboard.add_indicator(__('Test Key Available'), 'blue');
	}
	if (frm.doc.live_secret_key) {
		frm.dashboard.add_indicator(__('Live Key Available'), 'blue');
	}
}

function test_mollie_connection(_frm) {
	frappe.call({
		method:
      'verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings.test_mollie_connection',
		args: {
			// For singleton, no args needed - method will use frappe.get_single()
		},
		callback(r) {
			// Unwrap OperationResult format
			const data = unwrapOperationResult(r.message);
			if (data && data.success) {
				frappe.show_alert({
					message: data.message,
					indicator: 'green'
				});
			} else {
				frappe.show_alert({
					message: data ? data.message : __('Connection test failed'),
					indicator: 'red'
				});
			}
		},
		error(r) {
			frappe.show_alert({
				message:
          __('Error testing connection: ') + (r.message || 'Unknown error'),
				indicator: 'red'
			});
		}
	});
}

function validate_key_format(frm, key, expected_type) {
	// Basic validation for Mollie secret key format
	if (key) {
		if (expected_type === 'test' && !key.startsWith('test_')) {
			frappe.msgprint({
				title: __('Test Key Warning'),
				message: __(
					'This appears to be a live key, but it should be a test key (should start with "test_")'
				),
				indicator: 'orange'
			});
		} else if (expected_type === 'live' && key.startsWith('test_')) {
			frappe.msgprint({
				title: __('Live Key Warning'),
				message: __(
					'This appears to be a test key, but it should be a live key (should start with "live_")'
				),
				indicator: 'red'
			});
		} else if (expected_type === 'live' && !key.startsWith('live_')) {
			frappe.msgprint({
				title: __('Live Key Warning'),
				message: __(
					'Live keys should start with "live_". Please verify this is the correct key.'
				),
				indicator: 'orange'
			});
		}
	}
}

function validate_profile_id_format(frm) {
	const profile_id = frm.doc.profile_id;

	// Basic validation for Mollie profile ID format
	if (profile_id && !/^pfl_[a-zA-Z0-9]{10}$/.test(profile_id)) {
		frappe.msgprint({
			title: __('Profile ID Format'),
			message: __(
				'Mollie Profile ID should start with "pfl_" followed by 10 characters (e.g., pfl_v9hTwCuEmJ)'
			),
			indicator: 'yellow'
		});
	}
}

// Auto-refresh form when test mode changes
frappe.ui.form.on('Mollie Settings', 'test_mode', (frm) => {
	// Refresh form to update indicators and warnings
	setTimeout(() => {
		setup_form_indicators(frm);
	}, 100);
});

// Form validation before save
frappe.ui.form.on('Mollie Settings', 'before_save', (frm) => {
	// For singleton, name is automatically set to DocType name
	// No need to validate gateway_name since it's not used in singleton pattern

	// Validate required fields
	if (!frm.doc.profile_id) {
		frappe.throw(__('Profile ID is required for Mollie integration'));
	}

	// Validate that we have the appropriate key for the selected mode
	if (frm.doc.test_mode && !frm.doc.test_secret_key) {
		frappe.throw(__('Test Secret Key is required when Test Mode is enabled'));
	} else if (!frm.doc.test_mode && !frm.doc.live_secret_key) {
		frappe.throw(__('Live Secret Key is required when Test Mode is disabled'));
	}
});

function render_credentials_status(frm) {
	const wrapper = frm.get_field('credentials_status')?.$wrapper;
	if (!wrapper) { return; }
	const dot = (set) => `<span style="color:${set ? '#28a745' : '#adb5bd'}">●</span>`;
	const row = (label, set) =>
		`<div style="margin:2px 0">${dot(set)} ${label}: <b>${set ? __('set') : __('not set')}</b></div>`;
	wrapper.html(
		`<div class="text-muted" style="padding:6px 0">
			${row(__('Test API key'), !!frm.doc.test_secret_key)}
			${row(__('Live API key'), !!frm.doc.live_secret_key)}
			${row(__('Test webhook secret'), !!frm.doc.testing_webhook_secret_key)}
			${row(__('Live webhook secret'), !!frm.doc.live_webhook_secret_key)}
			${row(__('Organization access token'), !!frm.doc.organization_access_token)}
			${row(__('Backend webhook secret'), !!frm.doc.backend_webhook_secret)}
		</div>`
	);
}

function add_credential_buttons(frm) {
	frm.add_custom_button(__('Set API Keys'), () => {
		open_credentials_dialog(frm, __('Set Mollie API Keys'), [
			{ fieldname: 'test_secret_key', label: __('Test Secret Key') },
			{ fieldname: 'live_secret_key', label: __('Live Secret Key') }
		]);
	}, __('Credentials'));

	frm.add_custom_button(__('Set Webhook Secrets'), () => {
		open_credentials_dialog(frm, __('Set Mollie Webhook Secrets'), [
			{ fieldname: 'testing_webhook_secret_key', label: __('Testing Webhook Secret Key') },
			{ fieldname: 'live_webhook_secret_key', label: __('Live Webhook Secret Key') }
		]);
	}, __('Credentials'));

	frm.add_custom_button(__('Set Backend Credentials'), () => {
		open_credentials_dialog(frm, __('Set Mollie Backend Credentials'), [
			{ fieldname: 'organization_access_token', label: __('Organization Access Token') },
			{ fieldname: 'backend_webhook_secret', label: __('Backend Webhook Secret') }
		]);
	}, __('Credentials'));
}

function open_credentials_dialog(frm, title, specs) {
	// Build a dialog whose fields mirror the hidden DocType Password fields.
	// Browser autofill is blocked per-input via autocomplete="new-password",
	// randomised `name`, and data-* flags for LastPass/1Password.
	const fields = specs.map((s) => ({
		fieldname: s.fieldname,
		fieldtype: 'Password',
		label: s.label,
		description: __('Leave blank to keep existing value.')
	}));

	const d = new frappe.ui.Dialog({
		title,
		fields,
		primary_action_label: __('Save'),
		primary_action(values) {
			let dirty = false;
			specs.forEach((s) => {
				const new_val = (values[s.fieldname] || '').trim();
				if (new_val) {
					frm.set_value(s.fieldname, new_val);
					dirty = true;
				}
			});
			if (dirty) { frm.dirty(); }
			d.hide();
			render_credentials_status(frm);
			frappe.show_alert({
				message: __('Credentials updated. Save the document to store them encrypted.'),
				indicator: 'green'
			});
		}
	});
	d.show();

	// Apply anti-autofill to each password input in the dialog.
	specs.forEach((s) => {
		const $input = d.fields_dict[s.fieldname]?.$input;
		if (!$input) { return; }
		const random_name = `${s.fieldname}_${Math.random().toString(36).slice(2)}`;
		$input.attr({
			autocomplete: 'new-password',
			name: random_name,
			'data-lpignore': 'true',
			'data-form-type': 'other',
			'data-1p-ignore': 'true'
		});
		const clear_if_spurious = () => {
			if (!$input.is(':focus')) { $input.val(''); }
		};
		clear_if_spurious();
		setTimeout(clear_if_spurious, 100);
	});
}
