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
				__('Test Mode is enabled. Use test API keys and no real transactions will be processed.'),
				'orange',
				true
			);
		} else {
			frm.dashboard.clear_comment();
		}
	},

	secret_key(frm) {
		// Validate secret key format
		if (frm.doc.secret_key) {
			validate_secret_key_format(frm);
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
	// Add Test Connection button
	if (frm.doc.name && frm.doc.profile_id && frm.doc.secret_key) {
		frm.add_custom_button(__('Test Connection'), () => {
			test_mollie_connection(frm);
		}, __('Actions'));
	}

	// Add View Documentation button
	frm.add_custom_button(__('Mollie Documentation'), () => {
		window.open('https://docs.mollie.com/', '_blank');
	}, __('Help'));

	// Add Dashboard button if profile_id exists
	if (frm.doc.profile_id) {
		frm.add_custom_button(__('Mollie Dashboard'), () => {
			window.open('https://www.mollie.com/dashboard', '_blank');
		}, __('Help'));
	}
}

function setup_form_indicators(frm) {
	// Show test mode indicator
	if (frm.doc.test_mode) {
		frm.dashboard.set_headline_alert(
			__('Test Mode Active - No real transactions will be processed'),
			'orange'
		);
	}

	// Show configuration status
	if (frm.doc.name && frm.doc.profile_id && frm.doc.secret_key) {
		frm.dashboard.add_indicator(__('Configured'), 'green');
	} else {
		frm.dashboard.add_indicator(__('Incomplete Configuration'), 'red');
	}
}

function test_mollie_connection(frm) {
	frappe.call({
		method: 'verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings.test_mollie_connection',
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
				message: __('Error testing connection: ') + (r.message || 'Unknown error'),
				indicator: 'red'
			});
		}
	});
}

function validate_secret_key_format(frm) {
	const secret_key = frm.doc.secret_key;

	// Basic validation for Mollie secret key format
	if (secret_key) {
		if (frm.doc.test_mode && !secret_key.startsWith('test_')) {
			frappe.msgprint({
				title: __('Secret Key Warning'),
				message: __('Test mode is enabled but the secret key does not appear to be a test key (should start with "test_")'),
				indicator: 'orange'
			});
		} else if (!frm.doc.test_mode && secret_key.startsWith('test_')) {
			frappe.msgprint({
				title: __('Secret Key Warning'),
				message: __('Test mode is disabled but the secret key appears to be a test key'),
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
			message: __('Mollie Profile ID should start with "pfl_" followed by 10 characters (e.g., pfl_v9hTwCuEmJ)'),
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
	if (!frm.doc.profile_id || !frm.doc.secret_key) {
		frappe.throw(__('Profile ID and Secret Key are required for Mollie integration'));
	}
});
