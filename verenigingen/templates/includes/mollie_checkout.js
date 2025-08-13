/**
 * Mollie Checkout Client-Side JavaScript
 *
 * Handles the interactive payment checkout process including:
 * - Payment initialization and status polling
 * - Real-time UI updates and user feedback
 * - Automatic redirections and error handling
 * - Payment retry logic for failed/cancelled payments
 *
 * This script coordinates the client-side payment experience to provide
 * seamless interaction with the Mollie payment gateway while maintaining
 * proper error handling and user communication.
 */

$(document).ready(() => {
	// Get page configuration and payment data
	const pageConfig = JSON.parse(document.getElementById('page-config').textContent);
	const paymentData = JSON.parse(document.getElementById('payment-data').textContent);

	// Payment state management
	let currentPayment = null;
	let isProcessing = false;
	let statusCheckInterval = null;

	// UI element references
	const form = document.getElementById('payment-form');
	const statusInput = document.getElementById('status');
	const submitButton = document.getElementById('submit');
	const loadingIndicator = document.getElementById('loading-indicator');
	const errorMessage = document.getElementById('error-message');
	const successMessage = document.getElementById('success-message');

	// Initialize payment process
	initializePayment();

	// Set up form submission handler
	form.addEventListener('submit', handleFormSubmit);

	/**
     * Initialize the payment process
     * Starts by calling the server to create or check payment status
     */
	function initializePayment() {
		updateStatus('loading', __('Initializing payment...'));
		updateButton('loading', __('Loading...'));
		showLoading();

		// Call server to initialize/check payment
		frappe.call({
			method: 'verenigingen.templates.pages.mollie_checkout.make_payment',
			freeze: false,
			headers: {
				'X-Requested-With': 'XMLHttpRequest'
			},
			args: {
				data: JSON.stringify(paymentData),
				reference_doctype: pageConfig.reference_doctype,
				reference_docname: pageConfig.reference_docname,
				gateway_name: pageConfig.gateway_name || 'Default'
			},
			callback(response) {
				hideLoading();

				if (response.message) {
					currentPayment = response.message;
					handlePaymentResponse(currentPayment);
				} else {
					handleError(__('Failed to initialize payment. Please try again.'));
				}
			},
			error(xhr, status, error) {
				hideLoading();
				console.error('Payment initialization error:', error);
				handleError(__('Connection error. Please check your internet connection and try again.'));
			}
		});
	}

	/**
     * Handle form submission (payment button click)
     */
	function handleFormSubmit(e) {
		e.preventDefault();

		if (isProcessing) {
			return;
		}

		if (!currentPayment) {
			handleError(__('No payment information available. Please refresh the page.'));
			return;
		}

		const status = currentPayment.status;

		if (status === 'Completed') {
			// Payment completed, redirect to success
			redirectToSuccess();
		} else if (status === 'Cancelled' || status === 'Error') {
			// Payment failed, retry
			retryPayment();
		} else if (currentPayment.paymentUrl) {
			// Payment ready, redirect to Mollie
			redirectToMollie();
		} else {
			handleError(__('Payment URL not available. Please try again.'));
		}
	}

	/**
     * Handle payment response from server
     */
	function handlePaymentResponse(payment) {
		const status = payment.status;
		const message = payment.message || '';

		console.log('Payment response:', payment);

		switch (status) {
			case 'Open':
				updateStatus('open', __('Ready to pay'));
				updateButton('ready', __('Pay {0}').format(paymentData.amount));
				hideMessages();
				break;

			case 'Pending':
				updateStatus('pending', __('Payment processing...'));
				updateButton('processing', __('Processing...'));
				hideMessages();
				startStatusPolling();
				break;

			case 'Completed':
				updateStatus('completed', __('Payment completed'));
				updateButton('completed', __('Continue'));
				showSuccess(__('Payment completed successfully!'));
				break;

			case 'Cancelled':
				updateStatus('cancelled', __('Payment cancelled'));
				updateButton('retry', __('Try Again'));
				showError(__('Payment was cancelled. Click "Try Again" to create a new payment.'));
				break;

			case 'Error':
			default:
				updateStatus('error', __('Payment error'));
				updateButton('retry', __('Try Again'));
				showError(message || __('Payment failed. Please try again.'));
				break;
		}
	}

	/**
     * Start polling payment status for pending payments
     */
	function startStatusPolling() {
		if (statusCheckInterval) {
			clearInterval(statusCheckInterval);
		}

		statusCheckInterval = setInterval(() => {
			checkPaymentStatus();
		}, 3000); // Check every 3 seconds

		// Stop polling after 5 minutes
		setTimeout(() => {
			if (statusCheckInterval) {
				clearInterval(statusCheckInterval);
				statusCheckInterval = null;
			}
		}, 300000);
	}

	/**
     * Check current payment status
     */
	function checkPaymentStatus() {
		if (!currentPayment || !currentPayment.paymentID) {
			return;
		}

		frappe.call({
			method: 'verenigingen.templates.pages.mollie_checkout.get_payment_status_only',
			args: {
				reference_doctype: pageConfig.reference_doctype,
				reference_docname: pageConfig.reference_docname
			},
			callback(response) {
				if (response.message) {
					const status = response.message.status;

					if (status === 'Completed') {
						// Payment completed
						clearInterval(statusCheckInterval);
						currentPayment.status = 'Completed';
						handlePaymentResponse(currentPayment);
					} else if (status === 'Cancelled' || status === 'Error') {
						// Payment failed
						clearInterval(statusCheckInterval);
						currentPayment.status = status;
						handlePaymentResponse(currentPayment);
					}
					// Continue polling for other statuses
				}
			},
			error() {
				// Ignore polling errors, continue trying
				console.warn('Status polling error, continuing...');
			}
		});
	}

	/**
     * Redirect to Mollie payment page
     */
	function redirectToMollie() {
		if (!currentPayment.paymentUrl) {
			handleError(__('Payment URL not available'));
			return;
		}

		isProcessing = true;
		updateButton('redirecting', __('Redirecting...'));
		showLoading();

		// Small delay for better UX
		setTimeout(() => {
			window.location.href = currentPayment.paymentUrl;
		}, 1000);
	}

	/**
     * Redirect to success page
     */
	function redirectToSuccess() {
		isProcessing = true;
		updateButton('redirecting', __('Redirecting...'));
		showLoading();

		const successUrl = `/payment-success?doctype=${pageConfig.reference_doctype}&docname=${pageConfig.reference_docname}`;

		setTimeout(() => {
			window.location.href = successUrl;
		}, 1500);
	}

	/**
     * Retry payment (create new payment)
     */
	function retryPayment() {
		isProcessing = true;
		updateStatus('loading', __('Creating new payment...'));
		updateButton('loading', __('Loading...'));
		showLoading();
		hideMessages();

		// Reset current payment
		currentPayment = null;

		// Reinitialize payment
		setTimeout(() => {
			isProcessing = false;
			initializePayment();
		}, 1000);
	}

	/**
     * Update status display
     */
	function updateStatus(type, message) {
		if (statusInput) {
			statusInput.value = message;
			statusInput.className = statusInput.className.replace(/status-\w+/g, '');
			statusInput.classList.add(`status-${type}`);
			statusInput.classList.add('status-changed');

			setTimeout(() => {
				statusInput.classList.remove('status-changed');
			}, 500);
		}
	}

	/**
     * Update button appearance and text
     */
	function updateButton(type, text) {
		if (submitButton) {
			submitButton.textContent = text;
			submitButton.disabled = (type === 'loading' || type === 'processing' || type === 'redirecting');

			// Update button styling based on type
			submitButton.className = submitButton.className.replace(/btn-\w+/g, '');

			switch (type) {
				case 'ready':
					submitButton.classList.add('btn-primary');
					break;
				case 'completed':
					submitButton.classList.add('btn-success');
					break;
				case 'retry':
					submitButton.classList.add('btn-warning');
					break;
				case 'loading':
				case 'processing':
				case 'redirecting':
				default:
					submitButton.classList.add('btn-secondary');
					break;
			}
		}
	}

	/**
     * Show loading indicator
     */
	function showLoading() {
		if (loadingIndicator) {
			loadingIndicator.style.display = 'block';
		}
	}

	/**
     * Hide loading indicator
     */
	function hideLoading() {
		if (loadingIndicator) {
			loadingIndicator.style.display = 'none';
		}
	}

	/**
     * Show error message
     */
	function showError(message) {
		if (errorMessage) {
			document.getElementById('error-text').textContent = message;
			errorMessage.style.display = 'block';
		}
		if (successMessage) {
			successMessage.style.display = 'none';
		}
	}

	/**
     * Show success message
     */
	function showSuccess(message) {
		if (successMessage) {
			document.getElementById('success-text').textContent = message;
			successMessage.style.display = 'block';
		}
		if (errorMessage) {
			errorMessage.style.display = 'none';
		}
	}

	/**
     * Hide all messages
     */
	function hideMessages() {
		if (errorMessage) {
			errorMessage.style.display = 'none';
		}
		if (successMessage) {
			successMessage.style.display = 'none';
		}
	}

	/**
     * Handle errors
     */
	function handleError(message) {
		console.error('Payment error:', message);
		updateStatus('error', __('Error'));
		updateButton('retry', __('Try Again'));
		showError(message);
		hideLoading();
		isProcessing = false;

		// Clear any status polling
		if (statusCheckInterval) {
			clearInterval(statusCheckInterval);
			statusCheckInterval = null;
		}
	}

	// Cleanup on page unload
	window.addEventListener('beforeunload', () => {
		if (statusCheckInterval) {
			clearInterval(statusCheckInterval);
		}
	});
});
