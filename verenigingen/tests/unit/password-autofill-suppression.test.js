/**
 * @fileoverview Unit tests for the password-autofill suppression helper.
 *
 * Exercises the REAL module (verenigingen/public/js/utils/password_autofill_suppression.js)
 * via direct require. The form object and its jQuery `$input` are test doubles for
 * the DOM boundary (not business logic) — the attribute-setting, idempotency flag,
 * and "only clear genuinely-autofilled values" logic is the system under test.
 *
 * Business context: browsers ignore autocomplete="off" on password inputs and
 * autofill saved credentials into API-token / client-secret fields. This helper
 * defeats that without clobbering real saved values or in-progress user input.
 */

require('../../public/js/utils/password_autofill_suppression.js');
const suppress = window.verenigingen.suppressPasswordAutofill;

/**
 * Minimal jQuery-input double: tracks attributes, a data() key/value store, the
 * current value, and focus state. Mirrors only the surface the helper touches.
 */
function makeInput({ value = '', focused = false } = {}) {
	let val = value;
	const dataStore = {};
	const input = {
		length: 1,
		attrs: {},
		data: jest.fn((key, setValue) => {
			if (setValue === undefined) {
				return dataStore[key];
			}
			dataStore[key] = setValue;
			return input;
		}),
		attr: jest.fn((obj) => {
			Object.assign(input.attrs, obj);
			return input;
		}),
		is: jest.fn((selector) => (selector === ':focus' ? focused : false)),
		val: jest.fn((setValue) => {
			if (setValue === undefined) {
				return val;
			}
			val = setValue;
			return input;
		})
	};
	return input;
}

function makeForm(fields) {
	// fields: { fieldname: { $input } | {} }
	return { doc: {}, fields_dict: fields };
}

describe('suppressPasswordAutofill', () => {
	beforeEach(() => {
		jest.useFakeTimers();
	});
	afterEach(() => {
		jest.runOnlyPendingTimers();
		jest.useRealTimers();
	});

	test('applies the anti-autofill attribute set, with a randomised name', () => {
		const $input = makeInput({ value: '' });
		const frm = makeForm({ api_token: { $input } });

		suppress(frm, ['api_token']);

		expect($input.attrs.autocomplete).toBe('new-password');
		expect($input.attrs['data-lpignore']).toBe('true');
		expect($input.attrs['data-1p-ignore']).toBe('true');
		expect($input.attrs['data-form-type']).toBe('other');
		expect($input.attrs.name).toMatch(/^api_token_[a-z0-9]+$/);
	});

	test('marks the input suppressed and is idempotent on re-invocation', () => {
		const $input = makeInput({ value: '' });
		const frm = makeForm({ api_token: { $input } });

		suppress(frm, ['api_token']);
		expect($input.data('vv-autofill-suppressed')).toBe(true);
		$input.attr.mockClear();

		// Second call (e.g. Frappe re-renders the field) must NOT re-apply.
		suppress(frm, ['api_token']);
		expect($input.attr).not.toHaveBeenCalled();
	});

	test('clears a spuriously autofilled value when the doc has no saved value', () => {
		const $input = makeInput({ value: 'browser-autofilled-secret', focused: false });
		const frm = makeForm({ api_token: { $input } });
		frm.doc.api_token = ''; // no genuine saved value

		suppress(frm, ['api_token']);

		expect($input.val()).toBe('');
	});

	test('preserves a real saved value (doc has a value)', () => {
		const $input = makeInput({ value: 'masked-placeholder', focused: false });
		const frm = makeForm({ api_token: { $input } });
		frm.doc.api_token = 'real-stored-secret'; // genuine value on the saved doc

		suppress(frm, ['api_token']);

		expect($input.val()).toBe('masked-placeholder');
	});

	test('never clears a focused field (user may be typing)', () => {
		const $input = makeInput({ value: 'typing...', focused: true });
		const frm = makeForm({ api_token: { $input } });
		frm.doc.api_token = '';

		suppress(frm, ['api_token']);

		expect($input.val()).toBe('typing...');
	});

	test('the delayed (100ms) clear also fires to catch late autofill', () => {
		const $input = makeInput({ value: '', focused: false });
		const frm = makeForm({ api_token: { $input } });
		frm.doc.api_token = '';
		$input.is.mockClear();

		suppress(frm, ['api_token']);
		const callsBeforeTimer = $input.is.mock.calls.length;

		jest.advanceTimersByTime(100);

		// clear_if_spurious ran again after the timer -> extra :focus check
		expect($input.is.mock.calls.length).toBeGreaterThan(callsBeforeTimer);
	});

	test('processes every field name passed', () => {
		const tokenInput = makeInput({ value: '' });
		const secretInput = makeInput({ value: '' });
		const frm = makeForm({
			api_token: { $input: tokenInput },
			client_secret: { $input: secretInput }
		});

		suppress(frm, ['api_token', 'client_secret']);

		expect(tokenInput.attrs.name).toMatch(/^api_token_/);
		expect(secretInput.attrs.name).toMatch(/^client_secret_/);
	});

	test('skips fields with no rendered $input', () => {
		const frm = makeForm({ missing: {}, absent: undefined });
		expect(() => suppress(frm, ['missing', 'absent', 'not_in_dict'])).not.toThrow();
	});

	test('guards against invalid arguments', () => {
		expect(() => suppress(null, ['x'])).not.toThrow();
		expect(() => suppress(makeForm({}), 'not-an-array')).not.toThrow();
		expect(() => suppress(undefined, undefined)).not.toThrow();
	});
});
