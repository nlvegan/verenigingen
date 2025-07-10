/**
 * Error Handler for Membership Application
 * Provides consistent error handling, logging, and user feedback
 */

class ErrorHandler {
	constructor(options = {}) {
		this.options = {
			enableLogging: true,
			enableUserFeedback: true,
			enableRetries: true,
			maxRetries: 3,
			logEndpoint: null,
			showStackTrace: false,
			autoHideDelay: 5000,
			...options
		};

		this.errorLog = [];
		this.errorCounts = new Map();
		this.lastErrors = new Map();

		this._initializeErrorHandling();
		this._createErrorUI();
	}

	/**
     * Initialize global error handling
     */
	_initializeErrorHandling() {
		// Global JavaScript error handler
		window.addEventListener('error', (event) => {
			this.handleError({
				type: 'javascript',
				message: event.message,
				filename: event.filename,
				lineno: event.lineno,
				colno: event.colno,
				error: event.error,
				stack: event.error?.stack
			});
		});

		// Unhandled promise rejection handler
		window.addEventListener('unhandledrejection', (event) => {
			this.handleError({
				type: 'promise',
				message: event.reason?.message || 'Unhandled Promise Rejection',
				reason: event.reason,
				stack: event.reason?.stack
			});
		});

		// Network error detection
		window.addEventListener('offline', () => {
			this.showNotification('warning', 'Connection Lost', 'You appear to be offline. Your progress will be saved locally.');
		});

		window.addEventListener('online', () => {
			this.showNotification('success', 'Connection Restored', 'You are back online. Attempting to sync data...');
		});
	}

	/**
     * Create error UI elements
     */
	_createErrorUI() {
		// Error container for notifications
		if ($('#error-notification-container').length === 0) {
			$('body').append(`
                <div id="error-notification-container"
                     style="position: fixed; top: 20px; right: 20px; z-index: 9999; max-width: 400px;">
                </div>
            `);
		}

		// Global error modal
		if ($('#error-modal').length === 0) {
			$('body').append(`
                <div class="modal fade" id="error-modal" tabindex="-1" role="dialog">
                    <div class="modal-dialog" role="document">
                        <div class="modal-content">
                            <div class="modal-header bg-danger text-white">
                                <h5 class="modal-title">
                                    <i class="fas fa-exclamation-triangle"></i> Error
                                </h5>
                                <button type="button" class="close text-white" data-dismiss="modal">
                                    <span>&times;</span>
                                </button>
                            </div>
                            <div class="modal-body">
                                <div id="error-modal-content"></div>
                            </div>
                            <div class="modal-footer">
                                <button type="button" class="btn btn-secondary" data-dismiss="modal">Close</button>
                                <button type="button" class="btn btn-primary" id="error-retry-btn" style="display: none;">
                                    Retry
                                </button>
                                <button type="button" class="btn btn-info" id="error-report-btn">
                                    Report Issue
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            `);
		}
	}

	/**
     * Main error handling method
     */
	handleError(error, context = {}) {
		// Normalize error object
		const normalizedError = this._normalizeError(error);

		// Add context information
		normalizedError.context = {
			timestamp: new Date().toISOString(),
			userAgent: navigator.userAgent,
			url: window.location.href,
			userId: frappe.session?.user,
			...context
		};

		// Log the error
		if (this.options.enableLogging) {
			this._logError(normalizedError);
		}

		// Determine error severity
		const severity = this._determineSeverity(normalizedError);

		// Handle based on severity
		switch (severity) {
			case 'critical':
				this._handleCriticalError(normalizedError);
				break;
			case 'high':
				this._handleHighSeverityError(normalizedError);
				break;
			case 'medium':
				this._handleMediumSeverityError(normalizedError);
				break;
			case 'low':
				this._handleLowSeverityError(normalizedError);
				break;
		}

		// Update error statistics
		this._updateErrorStats(normalizedError);

		// Trigger error event for other components
		$(document).trigger('error:handled', normalizedError);

		return normalizedError.id;
	}

	/**
     * Handle validation errors
     */
	handleValidationError(field, error, context = {}) {
		const validationError = {
			type: 'validation',
			field: field,
			message: error.message || error,
			context: context
		};

		// Show field-specific error
		this._showFieldError(field, validationError);

		// Log validation error
		this.handleError(validationError, { category: 'validation' });
	}

	/**
     * Handle API errors
     */
	handleAPIError(error, endpoint, options = {}) {
		const apiError = {
			type: 'api',
			endpoint: endpoint,
			status: error.status || error.httpStatus,
			message: error.message,
			response: error.response,
			retryable: this._isRetryableError(error)
		};

		// Show appropriate user feedback
		if (apiError.retryable && options.retry !== false) {
			this._showRetryableError(apiError, options.onRetry);
		} else {
			this._showAPIError(apiError);
		}

		return this.handleError(apiError, { category: 'api', endpoint });
	}

	/**
     * Handle network errors
     */
	handleNetworkError(error, context = {}) {
		const networkError = {
			type: 'network',
			message: 'Network connection error',
			online: navigator.onLine,
			...error
		};

		if (!navigator.onLine) {
			this.showNotification('warning', 'Offline', 'Please check your internet connection');
		} else {
			this.showNotification('error', 'Network Error', 'Failed to connect to server');
		}

		return this.handleError(networkError, { category: 'network', ...context });
	}

	/**
     * Show user notifications
     */
	showNotification(type, title, message, options = {}) {
		const notification = {
			id: this._generateId(),
			type: type, // success, info, warning, error
			title: title,
			message: message,
			timestamp: new Date(),
			autoHide: options.autoHide !== false,
			actions: options.actions || []
		};

		this._renderNotification(notification);

		if (notification.autoHide) {
			setTimeout(() => {
				this._hideNotification(notification.id);
			}, options.delay || this.options.autoHideDelay);
		}

		return notification.id;
	}

	/**
     * Show modal error dialog
     */
	showErrorModal(error, options = {}) {
		const $modal = $('#error-modal');
		const $content = $('#error-modal-content');
		const $retryBtn = $('#error-retry-btn');

		// Build error content
		let content = '<div class="error-details">';
		content += `<h6>${error.title || 'An error occurred'}</h6>`;
		content += `<p>${error.message}</p>`;

		if (error.details) {
			content += '<div class="error-technical-details mt-3">';
			content += `<button class="btn btn-sm btn-outline-secondary" type="button" data-toggle="collapse" data-target="#error-stack">
                            Show Technical Details
                        </button>`;
			content += '<div class="collapse mt-2" id="error-stack">';
			content += `<pre class="bg-light p-2 small">${error.details}</pre>`;
			content += '</div></div>';
		}

		content += '</div>';
		$content.html(content);

		// Setup retry button
		if (options.onRetry) {
			$retryBtn.show().off('click').on('click', () => {
				$modal.modal('hide');
				options.onRetry();
			});
		} else {
			$retryBtn.hide();
		}

		// Setup report button
		$('#error-report-btn').off('click').on('click', () => {
			this._reportError(error);
		});

		$modal.modal('show');
	}

	/**
     * Error severity handling
     */
	_handleCriticalError(error) {
		// Critical errors require immediate user attention
		this.showErrorModal({
			title: 'Critical Error',
			message: 'A critical error has occurred. Please refresh the page and try again.',
			details: this.options.showStackTrace ? error.stack : null
		});

		// Disable form if necessary
		this._disableForm();
	}

	_handleHighSeverityError(error) {
		// High severity errors should be shown prominently
		this.showNotification('error', 'Error', error.message, {
			autoHide: false,
			actions: [
				{
					text: 'Retry',
					action: () => this._retryLastAction(error)
				}
			]
		});
	}

	_handleMediumSeverityError(error) {
		// Medium severity errors can be shown as notifications
		this.showNotification('warning', 'Warning', error.message);
	}

	_handleLowSeverityError(error) {
		// Low severity errors can be logged silently or shown briefly
		if (this.options.enableUserFeedback) {
			this.showNotification('info', 'Notice', error.message, { delay: 3000 });
		}
	}

	/**
     * Utility methods
     */
	_normalizeError(error) {
		const normalized = {
			id: this._generateId(),
			timestamp: new Date().toISOString(),
			type: 'unknown',
			message: 'An unknown error occurred',
			stack: null
		};

		if (typeof error === 'string') {
			normalized.message = error;
			normalized.type = 'string';
		} else if (error instanceof Error) {
			normalized.message = error.message;
			normalized.stack = error.stack;
			normalized.type = 'javascript';
		} else if (typeof error === 'object') {
			Object.assign(normalized, error);
		}

		return normalized;
	}

	_determineSeverity(error) {
		// Critical: JavaScript errors, system failures
		if (error.type === 'javascript' || error.type === 'system') {
			return 'critical';
		}

		// High: API errors, network failures
		if (error.type === 'api' || error.type === 'network') {
			return 'high';
		}

		// Medium: Validation errors, business logic errors
		if (error.type === 'validation' || error.type === 'business') {
			return 'medium';
		}

		// Low: Info messages, warnings
		return 'low';
	}

	_isRetryableError(error) {
		const retryableStatuses = [408, 429, 500, 502, 503, 504];
		return retryableStatuses.includes(error.status) || !navigator.onLine;
	}

	_logError(error) {

		this.errorLog.push({
			...error,
			timestamp: new Date().toISOString()
		});

		// Keep only last 100 errors in memory
		if (this.errorLog.length > 100) {
			this.errorLog = this.errorLog.slice(-100);
		}

		// Send to logging endpoint if configured
		if (this.options.logEndpoint) {
			this._sendErrorLog(error);
		}
	}

	_updateErrorStats(error) {
		const key = `${error.type}:${error.message}`;
		const count = this.errorCounts.get(key) || 0;
		this.errorCounts.set(key, count + 1);
		this.lastErrors.set(error.type, error);
	}

	_renderNotification(notification) {
		const iconMap = {
			success: 'fas fa-check-circle',
			info: 'fas fa-info-circle',
			warning: 'fas fa-exclamation-triangle',
			error: 'fas fa-times-circle'
		};

		const colorMap = {
			success: 'alert-success',
			info: 'alert-info',
			warning: 'alert-warning',
			error: 'alert-danger'
		};

		let actionsHTML = '';
		if (notification.actions && notification.actions.length > 0) {
			actionsHTML = '<div class="notification-actions mt-2">';
			notification.actions.forEach(action => {
				actionsHTML += `<button class="btn btn-sm btn-outline-primary me-2" onclick="(${action.action})()">${action.text}</button>`;
			});
			actionsHTML += '</div>';
		}

		const notificationHTML = `
            <div class="alert ${colorMap[notification.type]} alert-dismissible fade show"
                 id="notification-${notification.id}"
                 style="margin-bottom: 10px;">
                <div class="d-flex align-items-start">
                    <i class="${iconMap[notification.type]} me-2 mt-1"></i>
                    <div class="flex-grow-1">
                        <strong>${notification.title}</strong>
                        <div class="small">${notification.message}</div>
                        ${actionsHTML}
                    </div>
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                </div>
            </div>
        `;

		$('#error-notification-container').append(notificationHTML);
	}

	_hideNotification(notificationId) {
		$(`#notification-${notificationId}`).fadeOut(() => {
			$(`#notification-${notificationId}`).remove();
		});
	}

	_showFieldError(field, error) {
		const $field = $(`[name="${field}"], #${field}`);
		if ($field.length === 0) return;

		$field.addClass('is-invalid');

		let $feedback = $field.siblings('.invalid-feedback');
		if ($feedback.length === 0) {
			$feedback = $('<div class="invalid-feedback"></div>');
			$field.after($feedback);
		}

		$feedback.text(error.message);
	}

	_showRetryableError(error, onRetry) {
		this.showNotification('warning', 'Temporary Error',
			`${error.message}. Click retry to try again.`, {
				autoHide: false,
				actions: [
					{
						text: 'Retry',
						action: onRetry
					}
				]
			});
	}

	_showAPIError(error) {
		let message = error.message;
		if (error.status) {
			message += ` (Error ${error.status})`;
		}

		this.showNotification('error', 'Server Error', message);
	}

	_generateId() {
		return 'err_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
	}

	_disableForm() {
		$('.membership-application-form input, .membership-application-form button, .membership-application-form select').prop('disabled', true);
	}

	_sendErrorLog(error) {
		// Send error to logging endpoint (implement based on your needs)
		if (this.options.logEndpoint) {
			fetch(this.options.logEndpoint, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json'
				},
				body: JSON.stringify(error)
			}).catch(() => {
				// Silent fail for logging
			});
		}
	}

	_reportError(error) {
		// Open error reporting interface
		// Error data would be sent to reporting service here
		// const reportData = {
		//     error: error,
		//     userAgent: navigator.userAgent,
		//     url: window.location.href,
		//     timestamp: new Date().toISOString()
		// };

		// You could open a modal form or external reporting tool

		this.showNotification('info', 'Thank You', 'Error report has been generated. Please contact support if the issue persists.');
	}

	/**
     * Public API
     */
	getErrorStats() {
		return {
			totalErrors: this.errorLog.length,
			errorCounts: Object.fromEntries(this.errorCounts),
			lastErrors: Object.fromEntries(this.lastErrors),
			recentErrors: this.errorLog.slice(-10)
		};
	}

	clearErrors() {
		this.errorLog = [];
		this.errorCounts.clear();
		this.lastErrors.clear();
		$('#error-notification-container').empty();
	}

	isOnline() {
		return navigator.onLine;
	}
}

// Export for use in other modules
window.ErrorHandler = ErrorHandler;
