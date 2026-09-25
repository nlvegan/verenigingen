/**
 * @fileoverview Unit tests for the OperationResult helper utilities.
 *
 * Exercises the REAL module (verenigingen/public/js/utils/operation-result-helpers.js)
 * by requiring it directly so the coverage instrumenter measures it. The only
 * things stubbed are framework globals (frappe.provide / window) — the actual
 * unwrapping, error-extraction and XSS-escaping logic is the system under test.
 *
 * Business context: these helpers normalise the two backend response shapes the
 * app emits (OperationResult envelopes {success,data,message} vs legacy plain
 * payloads) and provide XSS-safe HTML escaping for member-facing UI. A regression
 * here silently corrupts every migrated API consumer.
 */

// --- Framework boundary setup (must run before requiring the module, which has
// load-time side effects: frappe.provide('verenigingen.utils')) ---
global.frappe = global.frappe || {};
global.frappe.provide = function provide(path) {
	const parts = path.split('.');
	let obj = global;
	for (const part of parts) {
		obj[part] = obj[part] || {};
		obj = obj[part];
	}
	return obj;
};

// Minimal translate stub: real `__(text, args)` substitutes {0}/{1}/... from
// args into text. The mock in tests/setup/frappe-mocks.js ignores args
// entirely (`(text) => text`), which would hide a wrong placeholder/arg-order
// bug in formatLoadedInvoicesAlert, so this one actually substitutes.
global.__ = function (text, args) {
	if (!args) {
		return text;
	}
	return text.replace(/\{(\d+)\}/g, (match, index) => {
		const value = args[Number(index)];
		return value === undefined ? match : String(value);
	});
};

require('../../public/js/utils/operation-result-helpers.js');
const utils = global.verenigingen.utils;

describe('OperationResult helpers', () => {
	describe('escapeHtml', () => {
		test('escapes angle brackets and ampersands to defeat XSS', () => {
			const escaped = utils.escapeHtml('<script>alert("x")&</script>');
			expect(escaped).not.toContain('<script>');
			expect(escaped).toContain('&lt;script&gt;');
			expect(escaped).toContain('&amp;');
		});

		test('returns empty string for null and undefined (no crash)', () => {
			expect(utils.escapeHtml(null)).toBe('');
			expect(utils.escapeHtml(undefined)).toBe('');
		});

		test('coerces non-string values to their string form', () => {
			expect(utils.escapeHtml(42)).toBe('42');
			expect(utils.escapeHtml(0)).toBe('0');
			expect(utils.escapeHtml(false)).toBe('false');
		});

		test('leaves plain text untouched', () => {
			expect(utils.escapeHtml('Jan de Vries')).toBe('Jan de Vries');
		});
	});

	describe('unwrapOperationResult', () => {
		test('returns the data payload for a successful envelope', () => {
			const envelope = { success: true, data: { member: 'M-001' }, message: 'ok' };
			expect(utils.unwrapOperationResult(envelope)).toEqual({ member: 'M-001' });
		});

		test('returns null for a failed envelope', () => {
			const envelope = { success: false, data: { member: 'M-001' }, message: 'nope' };
			expect(utils.unwrapOperationResult(envelope)).toBeNull();
		});

		test('passes legacy (non-envelope) responses through unchanged', () => {
			expect(utils.unwrapOperationResult({ foo: 'bar' })).toEqual({ foo: 'bar' });
			expect(utils.unwrapOperationResult('plain string')).toBe('plain string');
			expect(utils.unwrapOperationResult(null)).toBeNull();
		});

		test('treats an object missing the data key as legacy', () => {
			// success present but no data key -> not a full OperationResult
			expect(utils.unwrapOperationResult({ success: true })).toEqual({ success: true });
		});

		test('returns null for a REAL OperationResult.to_dict() nested-schema failure (#674)', () => {
			// This is the actual on-the-wire shape of OperationResult.to_dict() (the
			// default, nested=True) for a failure -- verified empirically via
			// `bench execute verenigingen.api.volunteer_application.submit_volunteer_application`:
			// there is no top-level "data" key on failure, only "error". The previous
			// `'data' in message` check made this fall through to `return message`
			// (the whole envelope, which is truthy), so every failure was read as a
			// success by callers doing `if (unwrapOperationResult(...))`.
			const nestedFailure = {
				success: false,
				timestamp: '2026-09-03 04:01:57.295664',
				error: {
					message: 'Missing required fields: first_name, last_name, email, birth_date, motivation',
					code: 'MISSING_REQUIRED_FIELDS'
				}
			};
			expect(utils.unwrapOperationResult(nestedFailure)).toBeNull();
		});
	});

	describe('getErrorMessage', () => {
		test('prefers error_message on a failed envelope', () => {
			const msg = { success: false, error_message: 'IBAN invalid', message: 'generic' };
			expect(utils.getErrorMessage(msg, 'default')).toBe('IBAN invalid');
		});

		test('joins an errors[] array when no error_message', () => {
			const msg = { success: false, errors: ['Email required', 'Name required'] };
			expect(utils.getErrorMessage(msg, 'default')).toBe('Email required; Name required');
		});

		test('falls back to message field, then to the default', () => {
			expect(utils.getErrorMessage({ success: false, message: 'boom' }, 'd')).toBe('boom');
			expect(utils.getErrorMessage({ success: false }, 'fallback')).toBe('fallback');
		});

		test('extracts fields even without a success flag', () => {
			expect(utils.getErrorMessage({ error_message: 'x' }, 'd')).toBe('x');
			expect(utils.getErrorMessage({ errors: ['a', 'b'] }, 'd')).toBe('a; b');
			expect(utils.getErrorMessage({ message: 'm' }, 'd')).toBe('m');
		});

		test('stringifies non-object input or uses default', () => {
			expect(utils.getErrorMessage('literal', 'd')).toBe('literal');
			expect(utils.getErrorMessage(null, 'default msg')).toBe('default msg');
		});

		test('ignores an empty errors array', () => {
			const msg = { success: false, errors: [], message: 'fallback message' };
			expect(utils.getErrorMessage(msg, 'd')).toBe('fallback message');
		});

		test('extracts the message from a REAL OperationResult.to_dict() nested-schema failure (#674)', () => {
			// Same real shape as the unwrapOperationResult test above. Neither
			// `error_message`, `errors` (top-level), nor `message` exist on this
			// envelope -- the text lives at `error.message` -- so the previous
			// implementation always fell through to defaultMsg here.
			const nestedFailure = {
				success: false,
				error: {
					message: 'Volunteers must be at least 21 years old (current age: 18)',
					code: 'AGE_REQUIREMENT_NOT_MET'
				}
			};
			expect(utils.getErrorMessage(nestedFailure, 'Submission failed')).toBe(
				'Volunteers must be at least 21 years old (current age: 18)'
			);
		});

		test('extracts a plain string "error" as a last resort (a hand-rolled dict, not an OperationResult)', () => {
			// A real OperationResult never emits this shape -- `to_dict(nested=False)`
			// is exercised nowhere in production, only in this app's own tests --
			// but plenty of hand-rolled `{success, error, message}` dicts exist
			// elsewhere in the app, and `error` here is a bare string, which is
			// legitimately ambiguous (message vs. machine code). It is checked
			// last, after `message`, precisely because of that ambiguity.
			const handRolled = { success: false, error: 'Legacy failure text', errors: [] };
			expect(utils.getErrorMessage(handRolled, 'default')).toBe('Legacy failure text');
		});

		test('a populated errors[] wins over an ambiguous string "error" (precedence)', () => {
			const msg = { success: false, error: 'permission_denied', errors: ['Field a', 'Field b'] };
			expect(utils.getErrorMessage(msg, 'd')).toBe('Field a; Field b');
		});

		test('a translated "message" wins over a machine-readable string "error" code', () => {
			// Real shape from verenigingen/api/document_portal.py: {success:false,
			// error:"permission_denied", message:_("You do not have permission...")}.
			// The object-shaped `error` branch above must not fire for a string
			// `error`, or a board member would see the raw code instead of the
			// translated sentence.
			const msg = { success: false, error: 'permission_denied', message: 'You do not have permission.' };
			expect(utils.getErrorMessage(msg, 'd')).toBe('You do not have permission.');
		});

		test('a success-flagged object is never mined for an unrelated "error" field', () => {
			// Real shape from verenigingen/utils/security/csrf_protection.py:
			// {success:true, valid:false, error:str(e), message:"CSRF token
			// validation failed"}. This function is only asked for an error
			// message on a genuine failure; when success is true, `error` must
			// not outrank `message`.
			const msg = {
				success: true,
				valid: false,
				error: 'Traceback (most recent call last)...',
				message: 'CSRF token validation failed'
			};
			expect(utils.getErrorMessage(msg, 'd')).toBe('CSRF token validation failed');
		});

		test('joins error.errors[] when the nested error object has no message', () => {
			// Defensive branch: OperationResult.fail() always sets error.message
			// (defaulting to "Operation failed"), so a genuine OperationResult
			// failure never reaches this, but a hand-rolled dict following the
			// same nested shape and omitting "message" should still surface its
			// per-field detail rather than falling through to the default.
			const msg = { success: false, error: { errors: ['Email required', 'Name required'] } };
			expect(utils.getErrorMessage(msg, 'd')).toBe('Email required; Name required');
		});
	});

	describe('isSuccessResult / isFailureResult', () => {
		test('distinguishes success from failure envelopes', () => {
			expect(utils.isSuccessResult({ success: true })).toBe(true);
			expect(utils.isSuccessResult({ success: false })).toBe(false);
			expect(utils.isFailureResult({ success: false })).toBe(true);
			expect(utils.isFailureResult({ success: true })).toBe(false);
		});

		test('returns falsy for non-envelopes', () => {
			expect(utils.isSuccessResult(null)).toBeFalsy();
			expect(utils.isSuccessResult('str')).toBeFalsy();
			expect(utils.isFailureResult(undefined)).toBeFalsy();
		});
	});

	describe('handleOperationResult', () => {
		test('invokes onSuccess with the data payload for a success envelope', () => {
			const onSuccess = jest.fn();
			const onFailure = jest.fn();
			const envelope = { success: true, data: { id: 1 } };
			utils.handleOperationResult(envelope, { onSuccess, onFailure });
			expect(onSuccess).toHaveBeenCalledWith({ id: 1 }, envelope);
			expect(onFailure).not.toHaveBeenCalled();
		});

		test('invokes onFailure with the message for a failed envelope', () => {
			const onFailure = jest.fn();
			utils.handleOperationResult({ success: false, message: 'denied' }, { onFailure });
			expect(onFailure).toHaveBeenCalledWith('denied', { success: false, message: 'denied' });
		});

		test('failed envelope without message uses a generic failure text', () => {
			const onFailure = jest.fn();
			utils.handleOperationResult({ success: false }, { onFailure });
			expect(onFailure).toHaveBeenCalledWith('Operation failed', { success: false });
		});

		test('routes legacy responses to onLegacy when provided', () => {
			const onLegacy = jest.fn();
			const onSuccess = jest.fn();
			utils.handleOperationResult({ plain: true }, { onLegacy, onSuccess });
			expect(onLegacy).toHaveBeenCalledWith({ plain: true });
			expect(onSuccess).not.toHaveBeenCalled();
		});

		test('legacy response with no onLegacy is treated as success', () => {
			const onSuccess = jest.fn();
			utils.handleOperationResult('legacy', { onSuccess });
			expect(onSuccess).toHaveBeenCalledWith('legacy');
		});

		test('tolerates being called with no options object', () => {
			expect(() => utils.handleOperationResult({ success: true, data: 1 })).not.toThrow();
		});
	});

	describe('formatLoadedInvoicesAlert (#1219)', () => {
		test('plain "Loaded N invoices" when nothing was truncated', () => {
			const result = utils.formatLoadedInvoicesAlert(5, 5);
			expect(result.message).toBe('Loaded 5 invoices');
			expect(result.indicator).toBe('green');
		});

		test('plain message when totalEligible is not a number (legacy/absent response key)', () => {
			const result = utils.formatLoadedInvoicesAlert(5, undefined);
			expect(result.message).toBe('Loaded 5 invoices');
			expect(result.indicator).toBe('green');
		});

		test('truncation message when totalEligible exceeds the loaded count', () => {
			const result = utils.formatLoadedInvoicesAlert(2, 3);
			expect(result.message).toContain('2');
			expect(result.message).toContain('3');
			expect(result.message).not.toBe('Loaded 2 invoices');
			expect(result.indicator).toBe('orange');
		});

		test('plain message when totalEligible equals the loaded count (not "> loadedCount")', () => {
			const result = utils.formatLoadedInvoicesAlert(4, 4);
			expect(result.message).toBe('Loaded 4 invoices');
			expect(result.indicator).toBe('green');
		});

		test('plain message when totalEligible is somehow less than loaded (defensive, never truncated)', () => {
			const result = utils.formatLoadedInvoicesAlert(4, 1);
			expect(result.message).toBe('Loaded 4 invoices');
			expect(result.indicator).toBe('green');
		});
	});

	describe('backward-compatible window globals', () => {
		test('exposes escapeHtml / unwrapOperationResult / getErrorMessage on window', () => {
			expect(window.escapeHtml).toBe(utils.escapeHtml);
			expect(window.unwrapOperationResult).toBe(utils.unwrapOperationResult);
			expect(window.getErrorMessage).toBe(utils.getErrorMessage);
		});

		test('exposes parseDonorExistsResponse on window', () => {
			expect(window.parseDonorExistsResponse).toBe(utils.parseDonorExistsResponse);
		});
	});

	describe('parseDonorExistsResponse (#1400)', () => {
		// Real wire shapes, taken from `check_donor_exists`'s OperationResult.to_dict()
		// output (empirically confirmed via real dispatch on test_site_2, not
		// synthesised): donor_name/donor_display_name live under `data`,
		// exists/ambiguous live under `meta` -- never at the top level.

		test('no donor found: status "none", no donor name', () => {
			const message = {
				success: true,
				timestamp: '2026-09-25 23:48:41.999885',
				data: null,
				meta: { exists: false }
			};
			expect(utils.parseDonorExistsResponse(message)).toEqual({ status: 'none', donorName: null });
		});

		test('donor exists: status "exists", donor name read from data (not top-level)', () => {
			const message = {
				success: true,
				timestamp: '2026-09-25 23:48:53.208053',
				data: { donor_name: 'DN-26-00057', donor_display_name: 'Probe Donor 1400' },
				meta: { exists: true }
			};
			expect(utils.parseDonorExistsResponse(message)).toEqual({
				status: 'exists',
				donorName: 'DN-26-00057'
			});
		});

		test('the previous (flat) reads are undefined against the real envelope -- proves the bug', () => {
			const message = {
				success: true,
				data: { donor_name: 'DN-26-00057', donor_display_name: 'Probe Donor 1400' },
				meta: { exists: true }
			};
			// This is exactly what the old member.js code read: r.message.exists /
			// r.message.donor_name. Both are undefined, which is why the "existing
			// donor" branch never fired.
			expect(message.exists).toBeUndefined();
			expect(message.donor_name).toBeUndefined();
		});

		test('ambiguous match (#1389): status "ambiguous", never a null/undefined donor name treated as real', () => {
			const message = {
				success: true,
				data: { donor_name: null, donor_display_name: null },
				meta: { exists: true, ambiguous: true, ambiguous_count: 2 }
			};
			expect(utils.parseDonorExistsResponse(message)).toEqual({ status: 'ambiguous', donorName: null });
		});

		test('failed OperationResult: fails closed to "none" (Create branch), not "exists"', () => {
			const message = {
				success: false,
				error: { message: 'Failed to check donor existence: boom' }
			};
			expect(utils.parseDonorExistsResponse(message)).toEqual({ status: 'none', donorName: null });
		});

		test('member not found: still "none" (member_not_found is metadata, not exists)', () => {
			const message = {
				success: true,
				data: null,
				meta: { member_not_found: true }
			};
			expect(utils.parseDonorExistsResponse(message)).toEqual({ status: 'none', donorName: null });
		});

		test('missing/malformed message: "none", never throws', () => {
			expect(utils.parseDonorExistsResponse(null)).toEqual({ status: 'none', donorName: null });
			expect(utils.parseDonorExistsResponse(undefined)).toEqual({ status: 'none', donorName: null });
			expect(utils.parseDonorExistsResponse('unexpected string')).toEqual({
				status: 'none',
				donorName: null
			});
			expect(utils.parseDonorExistsResponse({})).toEqual({ status: 'none', donorName: null });
		});

		test('exists=true but no meaningful donor_name in data: does not report "exists" with an empty name', () => {
			const message = {
				success: true,
				data: { donor_name: '', donor_display_name: '' },
				meta: { exists: true }
			};
			expect(utils.parseDonorExistsResponse(message)).toEqual({ status: 'none', donorName: null });
		});
	});
});
