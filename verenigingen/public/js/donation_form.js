/**
 * @fileoverview Public Donation Form Frontend Controller for Verenigingen Association Management
 *
 * This script manages the public-facing donation form interface, providing a multi-step
 * donation process with payment method integration, validation, and user experience
 * optimization. The form enables external supporters and members to contribute financially
 * to association activities and campaigns.
 *
 * @description Business Context:
 * The donation form is a critical component for fundraising activities, enabling the
 * association to collect financial contributions from supporters, members, and the
 * general public. It supports various donation types, payment methods, and provides
 * proper receipting for tax deduction purposes (ANBI compliance).
 *
 * @description Key Features:
 * - Multi-step donation workflow with progress tracking
 * - Payment method integration (SEPA, credit cards, online banking)
 * - Real-time form validation and error handling
 * - Donor information collection and management
 * - ANBI compliance for Dutch tax benefits
 * - Responsive design for mobile and desktop
 * - Integration with backend donation processing
 *
 * @description Form Workflow:
 * 1. Donation Type Selection: Choose donation purpose and amount
 * 2. Donor Information: Collect contact and personal details
 * 3. Payment Method: Select and configure payment preferences
 * 4. Additional Options: Tax receipt preferences and communication settings
 * 5. Confirmation: Review and submit donation request
 *
 * @description Integration Points:
 * - Connects to Donation DocType for record creation
 * - Integrates with payment processing systems
 * - Links to Donor management for supporter tracking
 * - Coordinates with ANBI reporting requirements
 * - Interfaces with email notification systems
 *
 * @author Verenigingen Development Team
 * @version 2025-01-13
 * @since 1.0.0
 *
 * @requires frappe - Frappe Framework client-side API (if available)
 * @requires payment-processors - External payment integration libraries
 *
 * @example
 * // Script is automatically loaded on donation form pages
 * // Initialization happens on DOMContentLoaded:
 * document.addEventListener('DOMContentLoaded', function() {
 *   // Form initialization and event binding
 * });
 */

// Global state management for donation form
window.currentStep = 1;
window.totalSteps = 5;
window.formData = {};

/**
 * Document Ready Event Handler
 *
 * Initializes the donation form when the DOM is fully loaded.
 * Sets up form validation, payment method handlers, and progress tracking.
 *
 * @description Initialization Process:
 * - Sets up progress indicator for multi-step workflow
 * - Configures form validation rules and error handling
 * - Initializes payment method selection and integration
 * - Binds event handlers for form interaction
 *
 * @example
 * // Automatically executed when page loads:
 * // - Form validation setup
 * // - Payment method configuration
 * // - Progress tracking initialization
 */
document.addEventListener('DOMContentLoaded', () => {
	// Initialize form state
	window.currentStep = 1;

	// Ensure step 1 is visible and others are hidden
	showStep(1);
	updateProgress();

	// Set up form validation
	setupFormValidation();

	// Initialize payment method handlers
	initializePaymentMethods();

	console.log('Donation form initialized, currentStep:', window.currentStep);
});

/**
 * Advance to Next Form Step
 *
 * Validates the current step and advances to the next step in the
 * multi-step donation process. Handles data collection and special
 * step-specific logic including confirmation step population.
 *
 * @description Step Progression Logic:
 * - Validates current step data before advancing
 * - Collects and stores step data in global form state
 * - Updates progress indicator and UI state
 * - Handles special logic for confirmation step
 * - Prevents advancement if validation fails
 *
 * @throws {ValidationError} If current step validation fails
 *
 * @example
 * // Called when user clicks "Next" button:
 * // Validates step 1 data, advances to step 2
 * nextStep();
 */
function nextStep() {
	console.log('nextStep called, current step:', window.currentStep);

	if (validateCurrentStep()) {
		console.log('Validation passed, advancing step');
		collectStepData();

		if (window.currentStep < window.totalSteps) {
			window.currentStep++;
			console.log('New step:', window.currentStep);
			showStep(window.currentStep);
			updateProgress();

			// Special handling for confirmation step
			if (window.currentStep === 5) {
				populateConfirmation();
			}
		}
	} else {
		console.log('Validation failed, staying on current step');
	}
}

/**
 * Return to Previous Form Step
 *
 * Navigates back to the previous step in the multi-step donation process.
 * Maintains form state and allows users to modify previously entered data.
 *
 * @description Navigation Logic:
 * - Moves back one step if not on first step
 * - Preserves existing form data
 * - Updates progress indicator
 * - Re-displays previous step with saved data
 *
 * @example
 * // Called when user clicks "Back" button:
 * // Returns from step 3 to step 2
 * prevStep();
 */
function prevStep() {
	if (window.currentStep > 1) {
		window.currentStep--;
		showStep(window.currentStep);
		updateProgress();
	}
}

function showStep(stepNumber) {
	console.log('showStep called with:', stepNumber, 'type:', typeof stepNumber);

	// Hide all form steps (use .form-step class, not just any element with data-step)
	document.querySelectorAll('.form-step').forEach(step => {
		step.style.display = 'none';
		step.classList.remove('active');
	});

	// Show current step - handle both numbered steps and special steps like 'success'
	let currentStepElement;

	// Check for success step - handle both string and any truthy value
	if (stepNumber === 'success' || stepNumber === 6) {
		console.log('Looking for success step...');
		// Find success step by data-step attribute
		currentStepElement = document.querySelector('.form-step[data-step="success"]');
		if (!currentStepElement) {
			console.warn('Success step not found with data-step="success", trying step 6...');
			// Try as step 6 since it's the 6th form step
			currentStepElement = document.querySelector('.form-step[data-step="6"]');
		}
		if (!currentStepElement) {
			console.warn('Still not found, checking all form steps...');
			// Log all available form steps for debugging
			const allSteps = document.querySelectorAll('.form-step');
			console.log('Available form steps:', allSteps.length);
			allSteps.forEach((step, i) => {
				console.log(`Step ${i}:`, step.getAttribute('data-step'), step.id || 'no-id');
			});
		}
	} else {
		// Regular numbered step
		currentStepElement = document.querySelector(`.form-step[data-step="${stepNumber}"]`);
	}

	if (currentStepElement) {
		currentStepElement.style.display = 'block';
		currentStepElement.classList.add('active');
		console.log(`Successfully activated form step ${stepNumber}`);
	} else {
		console.error(`Form step ${stepNumber} not found in DOM. Available steps:`,
			Array.from(document.querySelectorAll('.form-step')).map(s => s.getAttribute('data-step')));
		// As a fallback for success, just show a simple success message
		if (stepNumber === 'success') {
			console.log('Creating fallback success message...');
			const container = document.querySelector('.donation-form-container');
			if (container) {
				container.innerHTML = `
					<div style="text-align: center; padding: 50px;">
						<h2 style="color: #28a745;">Thank You!</h2>
						<p>Your donation has been submitted successfully.</p>
						<p>You will receive a confirmation email shortly.</p>
					</div>
				`;
			}
		}
	}

	// Update step indicators in the progress bar
	document.querySelectorAll('.step').forEach((step, index) => {
		step.classList.remove('active', 'completed');
		if (index + 1 < stepNumber) {
			step.classList.add('completed');
		} else if (index + 1 === stepNumber) {
			step.classList.add('active');
		}
	});
}

function updateProgress() {
	const progress = (window.currentStep / window.totalSteps) * 100;
	document.getElementById('form-progress').style.width = `${progress}%`;
}

function validateCurrentStep() {
	// Get the correct form step element (not the progress indicator)
	const formSteps = document.querySelectorAll('.form-step');
	const currentStepElement = formSteps[window.currentStep - 1]; // Convert 1-indexed to 0-indexed

	if (!currentStepElement) {
		console.error('Current step element not found:', window.currentStep);
		return false;
	}

	const requiredFields = currentStepElement.querySelectorAll('[required]');
	let isValid = true;

	// Clear previous errors
	clearErrors();

	console.log(`Validating step ${window.currentStep}, found ${requiredFields.length} required fields`);

	requiredFields.forEach(field => {
		if (!field.value.trim()) {
			console.log('Required field missing value:', field.name || field.id);
			showFieldError(field, __('This field is required'));
			isValid = false;
		}
	});

	// Step-specific validation
	if (window.currentStep === 1) {
		const amount = parseFloat(document.getElementById('amount').value);
		console.log('Step 1 validation - amount:', amount);
		if (!amount || amount <= 0) {
			showFieldError(document.getElementById('amount'), __('Amount must be greater than zero'));
			isValid = false;
		}
	}

	if (window.currentStep === 3) {
		const email = document.querySelector('[name="donor_email"]').value;
		if (!isValidEmail(email)) {
			showFieldError(document.querySelector('[name="donor_email"]'), __('Please enter a valid email address'));
			isValid = false;
		}
	}

	if (window.currentStep === 4) {
		const selectedPayment = document.querySelector('[name="payment_method"]:checked');
		if (!selectedPayment) {
			showAlert(__('Please select a payment method'), 'danger');
			isValid = false;
		}
	}

	if (window.currentStep === 5) {
		const termsAccepted = document.getElementById('terms_accepted').checked;
		const privacyAccepted = document.getElementById('privacy_accepted').checked;

		if (!termsAccepted) {
			showAlert(__('Please accept the terms and conditions'), 'danger');
			isValid = false;
		}

		if (!privacyAccepted) {
			showAlert(__('Please accept the privacy policy'), 'danger');
			isValid = false;
		}
	}

	return isValid;
}

function collectStepData() {
	// Get the correct form step element (not the progress indicator)
	const formSteps = document.querySelectorAll('.form-step');
	const currentStepElement = formSteps[window.currentStep - 1]; // Convert 1-indexed to 0-indexed

	if (!currentStepElement) {
		console.error('Could not find current step element for step:', window.currentStep);
		return;
	}

	const inputs = currentStepElement.querySelectorAll('input, select, textarea');
	console.log(`Collecting data from step ${window.currentStep}, found ${inputs.length} inputs`);

	inputs.forEach(input => {
		if (input.name) { // Only collect inputs that have a name attribute
			if (input.type === 'checkbox') {
				window.formData[input.name] = input.checked;
				console.log(`Collected ${input.name}: ${input.checked} (checkbox)`);
			} else if (input.type === 'radio') {
				if (input.checked) {
					window.formData[input.name] = input.value;
					console.log(`Collected ${input.name}: ${input.value} (radio)`);
				}
			} else {
				window.formData[input.name] = input.value;
				console.log(`Collected ${input.name}: ${input.value} (${input.type})`);
			}
		}
	});

	console.log('Current formData:', window.formData);
}

function collectAllStepData() {
	// Collect data from all form steps, not just the current one
	const formSteps = document.querySelectorAll('.form-step');

	console.log('Collecting data from all steps...');

	formSteps.forEach((step, index) => {
		const stepNumber = index + 1;
		const inputs = step.querySelectorAll('input, select, textarea');

		console.log(`Step ${stepNumber}: found ${inputs.length} inputs`);

		inputs.forEach(input => {
			if (input.name) { // Only collect inputs that have a name attribute
				if (input.type === 'checkbox') {
					window.formData[input.name] = input.checked;
				} else if (input.type === 'radio') {
					if (input.checked) {
						window.formData[input.name] = input.value;
					}
				} else if (input.value) { // Only collect non-empty values
					window.formData[input.name] = input.value;
				}
			}
		});
	});

	console.log('All form data collected:', window.formData);
}

function setupFormValidation() {
	// Add real-time validation for amount
	const amountField = document.getElementById('amount');
	if (amountField) {
		amountField.addEventListener('input', function () {
			const value = parseFloat(this.value);
			if (value > 0) {
				clearFieldError(this);
			}
		});
	}

	// Add real-time validation for email
	const emailField = document.querySelector('[name="donor_email"]');
	if (emailField) {
		emailField.addEventListener('blur', function () {
			if (isValidEmail(this.value)) {
				clearFieldError(this);
			}
		});
	}
}

function initializePaymentMethods() {
	// Set up payment method selection handlers
	document.querySelectorAll('.payment-method').forEach(method => {
		method.addEventListener('click', function () {
			selectPaymentMethod(this);
		});
	});
}

function selectPaymentMethod(element) {
	// Remove selection from all methods
	document.querySelectorAll('.payment-method').forEach(method => {
		method.classList.remove('selected');
	});

	// Select clicked method
	element.classList.add('selected');

	// Set radio button value
	const radio = element.querySelector('input[type="radio"]');
	if (radio) {
		radio.checked = true;
	}

	// Show method-specific fields
	showPaymentDetails(radio.value);
}

function showPaymentDetails(method) {
	const detailsContainer = document.getElementById('payment-details');
	let content = '';

	switch (method) {
		case 'SEPA Direct Debit':
			content = `
                <div style="margin-top: 20px; padding: 15px; background-color: #f8f9fa; border-radius: 4px;">
                    <h5>${__('SEPA Direct Debit')}</h5>
                    <p>${__('You will need to provide your IBAN and authorize us to collect the donation amount.')}</p>
                    <div class="form-group">
                        <label for="donor_iban">${__('IBAN')}</label>
                        <input type="text" class="form-control" name="donor_iban" placeholder="NL00 BANK 0000 0000 00">
                    </div>
                    <div class="form-check">
                        <input type="checkbox" class="form-check-input" id="sepa_consent" required>
                        <label class="form-check-label" for="sepa_consent">
                            ${__('I authorize the collection of this amount via SEPA Direct Debit')}
                        </label>
                    </div>
                </div>
            `;
			break;

		case 'Bank Transfer':
			content = `
                <div style="margin-top: 20px; padding: 15px; background-color: #f8f9fa; border-radius: 4px;">
                    <h5>${__('Bank Transfer')}</h5>
                    <p>${__('You will receive bank details after submitting this form.')}</p>
                    <p class="text-muted">${__('Please include the payment reference in your transfer description.')}</p>
                </div>
            `;
			break;

		case 'Mollie':
			content = `
                <div style="margin-top: 20px; padding: 15px; background-color: #f8f9fa; border-radius: 4px;">
                    <h5>${__('Online Payment')}</h5>
                    <p>${__('You will be redirected to our secure payment provider to complete your donation.')}</p>
                    <p class="text-muted">${__('Supports iDEAL, credit cards, and other payment methods.')}</p>
                </div>
            `;
			break;

		case 'Cash':
			content = `
                <div style="margin-top: 20px; padding: 15px; background-color: #f8f9fa; border-radius: 4px;">
                    <h5>${__('Cash Payment')}</h5>
                    <p>${__('You can pay in cash at our office or during events.')}</p>
                    <p class="text-muted">${__('We will provide you with contact information for payment arrangements.')}</p>
                </div>
            `;
			break;
	}

	detailsContainer.innerHTML = content;
}

function populateConfirmation() {
	// Collect data from all form steps before showing confirmation
	collectAllStepData();

	// Generate summary with better error handling
	const amount = parseFloat(window.formData.amount || 0);
	const donationType = window.formData.donation_type || 'Not specified';
	const donationStatus = window.formData.donation_status || 'One-time';
	const donorName = window.formData.donor_name || 'Not provided';
	const donorEmail = window.formData.donor_email || 'Not provided';

	// Get payment method text
	let paymentMethodText = window.formData.payment_method || 'Not selected';
	const selectedPaymentElement = document.querySelector('[name="payment_method"]:checked');
	if (selectedPaymentElement) {
		const paymentMethodContainer = selectedPaymentElement.closest('.payment-method');
		if (paymentMethodContainer) {
			const labelElement = paymentMethodContainer.querySelector('h5');
			if (labelElement) {
				paymentMethodText = labelElement.textContent;
			}
		}
	}

	const summaryHtml = `
        <div class="summary-row">
            <span>${__('Donation Amount')}:</span>
            <span><strong>€${amount.toFixed(2)}</strong></span>
        </div>
        <div class="summary-row">
            <span>${__('Donation Type')}:</span>
            <span>${donationType}</span>
        </div>
        <div class="summary-row">
            <span>${__('Frequency')}:</span>
            <span>${donationStatus}</span>
        </div>
        <div class="summary-row">
            <span>${__('Purpose')}:</span>
            <span>${getPurposeSummary()}</span>
        </div>
        <div class="summary-row">
            <span>${__('Donor')}:</span>
            <span>${donorName} (${donorEmail})</span>
        </div>
        <div class="summary-row">
            <span>${__('Payment Method')}:</span>
            <span>${paymentMethodText}</span>
        </div>
        <div class="summary-row">
            <span>${__('Total Amount')}:</span>
            <span><strong>€${amount.toFixed(2)}</strong></span>
        </div>
    `;

	document.getElementById('donation-summary').innerHTML = summaryHtml;
	console.log('Populated confirmation with data:', window.formData);
}

function getPurposeSummary() {
	const purposeType = window.formData.donation_purpose_type || 'General';

	switch (purposeType) {
		case 'Campaign':
			return `${__('Campaign')}: ${window.formData.campaign_reference || __('Not specified')}`;
		case 'Chapter':
			return `${__('Chapter')}: ${window.formData.chapter_reference || __('Not specified')}`;
		case 'Specific Goal':
			return `${__('Specific Goal')}: ${window.formData.specific_goal_description || __('Not specified')}`;
		default:
			return __('General Fund');
	}
}

function submitDonation() {
	if (!validateCurrentStep()) {
		return;
	}

	// Show loading state
	const submitBtn = document.getElementById('submit-btn');
	const submitText = document.getElementById('submit-text');
	const submitLoading = document.getElementById('submit-loading');

	submitBtn.disabled = true;
	submitText.style.display = 'none';
	submitLoading.style.display = 'inline-block';

	// Collect final form data from all steps
	collectAllStepData();

	// Submit to backend
	frappe.call({
		method: 'verenigingen.templates.pages.donate.submit_donation',
		args: window.formData,
		type: 'POST',
		callback(response) {
			submitBtn.disabled = false;
			submitText.style.display = 'inline-block';
			submitLoading.style.display = 'none';

			if (response.message.success) {
				showSuccessStep(response.message);
			} else {
				showAlert(response.message.message || __('An error occurred'), 'danger');
			}
		},
		error(error) {
			submitBtn.disabled = false;
			submitText.style.display = 'inline-block';
			submitLoading.style.display = 'none';

			showAlert(__('An error occurred while submitting your donation. Please try again.'), 'danger');
			console.error('Donation submission error:', error);
		}
	});
}

function showSuccessStep(response) {
	// Show success step
	window.currentStep = 'success';
	showStep('success');

	// Update progress to 100%
	document.getElementById('form-progress').style.width = '100%';

	// Populate success details
	let successContent = `
        <div class="alert alert-success">
            <strong>${__('Donation ID')}:</strong> ${response.donation_id}<br>
            <strong>${__('Amount')}:</strong> €${parseFloat(window.formData.amount).toFixed(2)}
        </div>
    `;

	// Add payment-specific instructions
	if (response.payment_info) {
		if (response.payment_info.status === 'awaiting_transfer') {
			successContent += `
                <div class="bank-details">
                    <h5>${__('Bank Transfer Details')}</h5>
                    <p><strong>${__('Account Holder')}:</strong> ${response.payment_info.bank_details.account_holder}</p>
                    <p><strong>${__('IBAN')}:</strong> ${response.payment_info.bank_details.iban}
                       <button class="copy-button" onclick="copyToClipboard('${response.payment_info.bank_details.iban}')">${__('Copy')}</button></p>
                    <p><strong>${__('BIC')}:</strong> ${response.payment_info.bank_details.bic}</p>
                    <p><strong>${__('Reference')}:</strong> ${response.payment_info.bank_details.reference}
                       <button class="copy-button" onclick="copyToClipboard('${response.payment_info.bank_details.reference}')">${__('Copy')}</button></p>
                    <p><strong>${__('Amount')}:</strong> €${response.payment_info.bank_details.amount}</p>
                </div>
                <p class="text-info">${response.payment_info.instructions}</p>
            `;
		} else if (response.payment_info.status === 'redirect_required' && response.payment_info.payment_url) {
			// Handle Mollie payment redirect
			successContent += `
                <div class="alert alert-info">
                    <h5>${__('Redirecting to Payment Provider')}</h5>
                    <p>${response.payment_info.message}</p>
                    <p>${response.payment_info.info}</p>
                    <div style="margin-top: 15px;">
                        <button type="button" class="btn btn-primary" onclick="window.open('${response.payment_info.payment_url}', '_self')">
                            ${__('Complete Payment')} →
                        </button>
                    </div>
                    ${response.payment_info.expires_at ? `<p class="text-muted"><small>${__('Payment link expires')}: ${new Date(response.payment_info.expires_at).toLocaleString()}</small></p>` : ''}
                </div>
            `;

			// Auto-redirect after a short delay
			setTimeout(() => {
				window.open(response.payment_info.payment_url, '_self');
			}, 3000);

		} else {
			successContent += `
                <div class="alert alert-info">
                    ${response.payment_info.message}
                    ${response.payment_info.info ? `<br><small>${response.payment_info.info}</small>` : ''}
                </div>
            `;
		}
	}

	successContent += `
        <p>${__('You will receive a confirmation email shortly with all the details.')}</p>
    `;

	document.getElementById('success-details').innerHTML = successContent;
}

// Utility functions
function setAmount(amount) {
	document.getElementById('amount').value = amount;
	clearFieldError(document.getElementById('amount'));
}

function togglePurposeFields() {
	const purposeType = document.getElementById('donation_purpose_type').value;

	// Hide all purpose-specific fields
	document.getElementById('campaign-field').style.display = 'none';
	document.getElementById('chapter-field').style.display = 'none';
	document.getElementById('goal-field').style.display = 'none';

	// Show relevant field
	switch (purposeType) {
		case 'Campaign':
			document.getElementById('campaign-field').style.display = 'block';
			break;
		case 'Chapter':
			document.getElementById('chapter-field').style.display = 'block';
			break;
		case 'Specific Goal':
			document.getElementById('goal-field').style.display = 'block';
			break;
	}
}

function toggleAnbiFields() {
	const checkbox = document.getElementById('request_anbi');
	const fields = document.getElementById('anbi-fields');

	if (checkbox.checked) {
		fields.style.display = 'block';
		// Auto-generate ANBI agreement number if empty
		const numberField = document.querySelector('[name="anbi_agreement_number"]');
		if (!numberField.value) {
			frappe.call({
				method: 'verenigingen.verenigingen.doctype.donation.donation.generate_anbi_agreement_number',
				callback(response) {
					if (response.message) {
						numberField.value = response.message;
					}
				}
			});
		}
	} else {
		fields.style.display = 'none';
	}
}

function isValidEmail(email) {
	const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
	return emailRegex.test(email);
}

function showAlert(message, type = 'info') {
	const alertContainer = document.getElementById('alert-container');
	const alert = document.createElement('div');
	alert.className = `alert alert-${type}`;
	alert.innerHTML = `
        ${message}
        <button type="button" style="float: right; background: none; border: none; font-size: 18px; line-height: 1; opacity: 0.7;" onclick="this.parentElement.remove()">×</button>
    `;

	alertContainer.innerHTML = '';
	alertContainer.appendChild(alert);

	// Auto-remove after 5 seconds
	setTimeout(() => {
		if (alert.parentElement) {
			alert.remove();
		}
	}, 5000);
}

function showFieldError(field, message) {
	// Remove existing error
	clearFieldError(field);

	// Add error styling
	field.style.borderColor = '#dc3545';

	// Add error message
	const errorDiv = document.createElement('div');
	errorDiv.className = 'field-error';
	errorDiv.style.color = '#dc3545';
	errorDiv.style.fontSize = '12px';
	errorDiv.style.marginTop = '4px';
	errorDiv.textContent = message;

	field.parentElement.appendChild(errorDiv);
}

function clearFieldError(field) {
	field.style.borderColor = '';
	const errorDiv = field.parentElement.querySelector('.field-error');
	if (errorDiv) {
		errorDiv.remove();
	}
}

function clearErrors() {
	document.querySelectorAll('.field-error').forEach(error => error.remove());
	document.querySelectorAll('.form-control').forEach(field => {
		field.style.borderColor = '';
	});
}

function copyToClipboard(text) {
	navigator.clipboard.writeText(text).then(() => {
		showAlert(__('Copied to clipboard!'), 'success');
	});
}

// Initialize the donation form when DOM is ready
function initializeDonationForm() {
	// Initialize global variables
	window.currentStep = 1;
	window.formData = {};

	// Show step 1
	showStep(1);

	// Set up form validation
	setupFormValidation();

	// Initialize payment methods
	initializePaymentMethods();

	console.log('Donation form initialized successfully');
}

// Initialize on DOM content loaded
document.addEventListener('DOMContentLoaded', function() {
	initializeDonationForm();
});

// Also initialize if DOM is already loaded (for dynamic loading)
if (document.readyState === 'loading') {
	document.addEventListener('DOMContentLoaded', initializeDonationForm);
} else {
	initializeDonationForm();
}

// Expose functions globally for inline event handlers
window.nextStep = nextStep;
window.prevStep = prevStep;
window.setAmount = setAmount;
window.selectPaymentMethod = selectPaymentMethod;
window.togglePurposeFields = togglePurposeFields;
window.toggleAnbiFields = toggleAnbiFields;
window.submitDonation = submitDonation;
window.copyToClipboard = copyToClipboard;
window.initializeDonationForm = initializeDonationForm;
