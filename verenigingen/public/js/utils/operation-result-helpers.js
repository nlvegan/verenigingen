/**
 * OperationResult Helper Utilities
 *
 * Centralized utilities for handling OperationResult API responses.
 * APIs migrated to OperationResult pattern return: {success, data, message, timestamp}
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
	const div = document.createElement('div');
	div.textContent = String(str);
	return div.innerHTML;
};

/**
 * Unwrap OperationResult format responses to get the data payload
 * @param {*} message - Response from frappe.call (r.message)
 * @returns {*} The data payload if success, null if failed, or original value if not OperationResult
 */
verenigingen.utils.unwrapOperationResult = function (message) {
	if (message && typeof message === 'object' && 'success' in message && 'data' in message) {
		return message.success ? message.data : null;
	}
	return message;
};

/**
 * Get error message from OperationResult or plain response
 * Handles multiple error formats: error_message, errors[], message
 * @param {*} message - Response from frappe.call (r.message)
 * @param {string} defaultMsg - Default message if none found
 * @returns {string} Error message
 */
verenigingen.utils.getErrorMessage = function (message, defaultMsg) {
	if (message && typeof message === 'object') {
		if ('success' in message && !message.success) {
			// Check for error_message (common in OperationResult)
			if (message.error_message) {
				return message.error_message;
			}
			// Check for errors array (common in validation results)
			if (message.errors && Array.isArray(message.errors) && message.errors.length > 0) {
				return message.errors.join('; ');
			}
			// Fall back to generic message field
			return message.message || defaultMsg;
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

// Also expose as global functions for backward compatibility with HTML templates
// that may have inline scripts without access to frappe namespace at load time
if (typeof window !== 'undefined') {
	window.escapeHtml = verenigingen.utils.escapeHtml;
	window.unwrapOperationResult = verenigingen.utils.unwrapOperationResult;
	window.getErrorMessage = verenigingen.utils.getErrorMessage;
}
