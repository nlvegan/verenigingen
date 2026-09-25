/**
 * OperationResult Helper Utilities
 *
 * Centralized utilities for handling OperationResult API responses.
 * OperationResult.to_dict() (the real, empirically-verified wire shape -- see
 * #674) is nested: {success, data, meta} on success, {success, error: {message,
 * errors, code, http_status}, meta} on failure. There is NO top-level "data" on
 * failure and no top-level "message" at all -- the failure text lives at
 * `error.message`. A legacy flat schema (`to_dict(nested=False)`) instead puts
 * a plain string directly under "error".
 *
 * These helpers provide:
 * - XSS-safe HTML escaping
 * - Consistent response unwrapping
 * - Error message extraction
 *
 * Usage: Available globally via verenigingen.utils namespace
 */

// Ensure namespace exists
frappe.provide('verenigingen.utils');

/**
 * Escape HTML to prevent XSS attacks
 * @param {*} str - Value to escape (handles null/undefined)
 * @returns {string} HTML-escaped string
 */
verenigingen.utils.escapeHtml = function (str) {
	if (str == null) {
		return '';
	}
	// Escape quotes too, so output is safe in attribute contexts (e.g. value="...").
	return String(str)
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;')
		.replace(/'/g, '&#39;');
};

/**
 * Unwrap OperationResult format responses to get the data payload
 * @param {*} message - Response from frappe.call (r.message)
 * @returns {*} The data payload if success, null if failed, or original value if not OperationResult
 */
verenigingen.utils.unwrapOperationResult = function (message) {
	if (message && typeof message === 'object' && 'success' in message) {
		// OperationResult.to_dict()'s nested schema (the default) puts a failure's
		// details under "error", not "data" -- there is no top-level "data" key at
		// all on failure. Checking 'data' in message here used to make every
		// failure fall through to `return message` below (the whole envelope,
		// which is truthy), so callers doing `if (unwrapOperationResult(...))`
		// read every failure as a success (#674).
		if (!message.success) {
			return null;
		}
		if ('data' in message) {
			return message.data;
		}
	}
	return message;
};

/**
 * Get error message from OperationResult or plain response
 * Handles multiple error formats: error (nested object or string), error_message,
 * errors[], message
 * @param {*} message - Response from frappe.call (r.message)
 * @param {string} defaultMsg - Default message if none found
 * @returns {string} Error message
 */
verenigingen.utils.getErrorMessage = function (message, defaultMsg) {
	if (message && typeof message === 'object') {
		if ('success' in message && !message.success) {
			// OperationResult.to_dict()'s nested schema puts the failure text
			// under "error" as an object {message, errors, code, http_status}
			// (#674). Checked first because it is the one shape a real
			// OperationResult failure actually produces, but only inside the
			// success===false guard: a success-flagged response that happens to
			// carry an unrelated `error` field (e.g. a validation sub-result)
			// must not have that field mined for the top-level message.
			if (message.error && typeof message.error === 'object') {
				if (message.error.message) {
					return message.error.message;
				}
				if (Array.isArray(message.error.errors) && message.error.errors.length > 0) {
					return message.error.errors.join('; ');
				}
			}
			// Check for error_message (common in OperationResult)
			if (message.error_message) {
				return message.error_message;
			}
			// Check for errors array (common in validation results)
			if (message.errors && Array.isArray(message.errors) && message.errors.length > 0) {
				return message.errors.join('; ');
			}
			// Fall back to the generic message field, then to a string `error`
			// (the legacy flat schema, to_dict(nested=False)) -- `error` is
			// ambiguous between a human message and a machine code, so it is
			// the last resort, after the fields more likely to hold prose.
			return message.message || (typeof message.error === 'string' ? message.error : defaultMsg);
		}
		// Check individual fields even without success flag
		if (message.error_message) {
			return message.error_message;
		}
		if (message.errors && Array.isArray(message.errors) && message.errors.length > 0) {
			return message.errors.join('; ');
		}
		if (message.message) {
			return message.message;
		}
	}
	return String(message || defaultMsg);
};

/**
 * Check if response is a successful OperationResult
 * @param {*} message - Response from frappe.call (r.message)
 * @returns {boolean} True if successful OperationResult
 */
verenigingen.utils.isSuccessResult = function (message) {
	return message && typeof message === 'object' && message.success === true;
};

/**
 * Check if response is a failed OperationResult
 * @param {*} message - Response from frappe.call (r.message)
 * @returns {boolean} True if failed OperationResult
 */
verenigingen.utils.isFailureResult = function (message) {
	return message && typeof message === 'object' && message.success === false;
};

/**
 * Handle OperationResult response with success/failure callbacks
 * @param {*} message - Response from frappe.call (r.message)
 * @param {Object} options - Handler options
 * @param {Function} options.onSuccess - Called with data on success
 * @param {Function} options.onFailure - Called with error message on failure
 * @param {Function} options.onLegacy - Called for non-OperationResult responses
 */
verenigingen.utils.handleOperationResult = function (message, options) {
	options = options || {};

	if (message && typeof message === 'object' && 'success' in message) {
		// OperationResult format
		if (message.success) {
			if (options.onSuccess) {
				options.onSuccess(message.data, message);
			}
		} else {
			if (options.onFailure) {
				options.onFailure(message.message || 'Operation failed', message);
			}
		}
	} else {
		// Legacy format - pass through
		if (options.onLegacy) {
			options.onLegacy(message);
		} else if (options.onSuccess) {
			// Treat legacy responses as success by default
			options.onSuccess(message);
		}
	}
};

/**
 * Format the "Loaded N invoices" alert for the SEPA batch loader dialog (#1219).
 *
 * `load_unpaid_invoices` / `load_unpaid_invoices_secure` report the true eligible
 * count as a sibling response key (`r.total_eligible`, NOT folded into `r.message`
 * -- see the endpoints' docstrings), so a truncated load can be told apart from a
 * complete one. `totalEligible` is only ever compared, never trusted blindly: a
 * missing/non-numeric value (legacy caller, older cached JS) or one that is not
 * actually greater than what was loaded falls back to the plain message.
 *
 * @param {number} loadedCount - invoices actually returned (data.length)
 * @param {*} totalEligible - r.total_eligible from the response, or undefined
 * @returns {{message: string, indicator: string}}
 */
verenigingen.utils.formatLoadedInvoicesAlert = function (loadedCount, totalEligible) {
	const truncated = typeof totalEligible === 'number' && totalEligible > loadedCount;
	if (!truncated) {
		return { message: __('Loaded {0} invoices', [loadedCount]), indicator: 'green' };
	}
	return {
		message: __('Loaded {0} of {1} eligible invoices — raise "Maximum Invoices" to load the rest', [
			loadedCount,
			totalEligible
		]),
		indicator: 'orange'
	};
};

/**
 * Parse `check_donor_exists`'s OperationResult envelope into a UI-ready shape (#1400).
 *
 * `general_api.check_donor_exists` returns `DonorManagementService.check_donor_exists`'s
 * `OperationResult`, and the whitelisted endpoint's `@standard_api` decorator serializes
 * it via `to_dict(scrub_sensitive=True)` -- the NESTED schema (default `nested=True`),
 * not the flat one. So `donor_name`/`donor_display_name` live under `data`, and
 * `exists`/`ambiguous` live under `meta` -- never at the top level. Reading
 * `message.exists`/`message.donor_name` directly (the previous member.js code) always
 * read `undefined`, so the "existing donor" branch never fired.
 *
 * Also handles the ambiguous-match shape (more than one Donor record matches, see
 * #1389): `meta.ambiguous === true` with `data.donor_name` set to `null`. That must
 * never be treated as "exists" -- routing to a Donor form with a null/undefined name
 * would either error or open the wrong record.
 *
 * @param {*} message - r.message from frappe.call to check_donor_exists
 * @returns {{status: 'exists'|'ambiguous'|'none', donorName: string|null}}
 *   status is 'none' for a failed OperationResult or any unrecognised shape --
 *   fails closed to the "Create Donor Record" branch rather than the "View" one.
 */
verenigingen.utils.parseDonorExistsResponse = function (message) {
	if (!message || typeof message !== 'object' || message.success !== true) {
		return { status: 'none', donorName: null };
	}
	const meta = message.meta && typeof message.meta === 'object' ? message.meta : {};
	const data = message.data && typeof message.data === 'object' ? message.data : {};

	if (meta.ambiguous === true) {
		return { status: 'ambiguous', donorName: null };
	}
	if (meta.exists === true && data.donor_name) {
		return { status: 'exists', donorName: data.donor_name };
	}
	return { status: 'none', donorName: null };
};

// Also expose as global functions for backward compatibility with HTML templates
// that may have inline scripts without access to frappe namespace at load time
if (typeof window !== 'undefined') {
	window.escapeHtml = verenigingen.utils.escapeHtml;
	window.unwrapOperationResult = verenigingen.utils.unwrapOperationResult;
	window.getErrorMessage = verenigingen.utils.getErrorMessage;
	window.parseDonorExistsResponse = verenigingen.utils.parseDonorExistsResponse;
}
