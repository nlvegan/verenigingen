/**
 * Suppress browser autofill on form Password fields.
 *
 * Chrome/Firefox/Safari aggressively autofill saved credentials into any
 * <input type="password">. `autocomplete="off"` is ignored by Chrome on
 * password fields (deliberate browser policy); `autocomplete="new-password"`
 * IS respected for autofill suppression.
 *
 * This helper applies a defensive combination of:
 *   - autocomplete="new-password"  — Chrome respects this for autofill
 *   - randomised `name` attribute  — defeats saved-cred URL+name matching
 *   - data-lpignore / data-1p-ignore / data-form-type="other"  — cover the
 *     LastPass and 1Password browser extensions
 *   - immediate + 100ms-delayed value-clear  — defeats Chrome's late autofill
 *     (only clears if the field isn't focused and the doc has no value, so
 *     user input and existing values are preserved)
 *
 * Note: this addresses AUTOFILL only. Browser "save password?" prompts on
 * form save are not suppressible via attributes — they require the password
 * input to not be in a rendered form at all. If you need that, move the
 * field to `hidden: 1` in the DocType and edit it via a dialog button.
 *
 * Usage (inside a DocType JS refresh handler):
 *
 *   refresh(frm) {
 *       verenigingen.suppressPasswordAutofill(frm, [
 *           "api_token",
 *           "client_secret",
 *       ]);
 *   }
 *
 * @param {object} frm - Frappe form object
 * @param {string[]} fieldnames - list of Password fieldnames to protect
 */
window.verenigingen = window.verenigingen || {};
window.verenigingen.suppressPasswordAutofill = function (frm, fieldnames) {
	if (!frm || !Array.isArray(fieldnames)) { return; }

	fieldnames.forEach((fn) => {
		const field = frm.fields_dict[fn];
		const $input = field && field.$input;
		if (!$input || !$input.length) { return; }

		// Flag so we don't re-apply on every refresh (Frappe re-renders
		// fields on various events; re-randomising the name on each call
		// would churn the DOM unnecessarily).
		if ($input.data('vv-autofill-suppressed')) { return; }
		$input.data('vv-autofill-suppressed', true);

		const random_name = `${fn}_${Math.random().toString(36).slice(2)}`;
		$input.attr({
			autocomplete: 'new-password',
			name: random_name,
			'data-lpignore': 'true',
			'data-form-type': 'other',
			'data-1p-ignore': 'true'
		});

		// Clear any value the browser autofilled before the attribute change
		// took effect. Preserve real values (from the saved doc) and anything
		// the user has started typing. A second 100ms clear catches Chrome's
		// delayed autofill which sometimes fires after DOM attach.
		const clear_if_spurious = () => {
			if ($input.is(':focus')) { return; }
			const input_val = $input.val();
			if (!input_val) { return; }
			const doc_val = frm.doc[fn] || '';
			// Frappe renders Password fields with masked placeholder text
			// when a value exists on the saved doc; only clear if the doc
			// has no value (genuine autofill case) — NOT if doc has a value
			// and the input shows the browser's autofilled substitute.
			if (!doc_val) {
				$input.val('');
			}
		};
		clear_if_spurious();
		setTimeout(clear_if_spurious, 100);
	});
};
