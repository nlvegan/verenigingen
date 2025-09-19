// Mollie Settings Client-side JavaScript
// Provides form enhancements, validation, and user interface features

frappe.ui.form.on('Mollie Settings', {
	refresh(frm) {
		// Add custom buttons and form enhancements
		add_custom_buttons(frm);
		setup_form_indicators(frm);
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
			if (r.message && r.message.success) {
				frappe.show_alert({
					message: r.message.message,
					indicator: 'green'
				});
			} else {
				frappe.show_alert({
					message: r.message ? r.message.message : __('Connection test failed'),
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
