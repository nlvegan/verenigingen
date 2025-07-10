/**
 * Donation Form JavaScript
 * Handles multi-step form functionality and payment method integration
 */

let currentStep = 1;
const totalSteps = 5;
let formData = {};

document.addEventListener('DOMContentLoaded', function() {
	// Initialize form
	updateProgress();

	// Set up form validation
	setupFormValidation();

	// Initialize payment method handlers
	initializePaymentMethods();
});

function nextStep() {
	if (validateCurrentStep()) {
		collectStepData();

		if (currentStep < totalSteps) {
			currentStep++;
			showStep(currentStep);
			updateProgress();

			// Special handling for confirmation step
			if (currentStep === 5) {
				populateConfirmation();
			}
		}
	}
}

function prevStep() {
	if (currentStep > 1) {
		currentStep--;
		showStep(currentStep);
		updateProgress();
	}
}

function showStep(stepNumber) {
	// Hide all steps
	document.querySelectorAll('.form-step').forEach(step => {
		step.classList.remove('active');
	});

	// Show current step
	const currentStepElement = document.querySelector(`[data-step="${stepNumber}"]`);
	if (currentStepElement) {
		currentStepElement.classList.add('active');
	}

	// Update step indicators
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
	const progress = (currentStep / totalSteps) * 100;
	document.getElementById('form-progress').style.width = progress + '%';
}

function validateCurrentStep() {
	const currentStepElement = document.querySelector(`[data-step="${currentStep}"]`);
	const requiredFields = currentStepElement.querySelectorAll('[required]');
	let isValid = true;

	// Clear previous errors
	clearErrors();

	requiredFields.forEach(field => {
		if (!field.value.trim()) {
			showFieldError(field, __('This field is required'));
			isValid = false;
		}
	});

	// Step-specific validation
	if (currentStep === 1) {
		const amount = parseFloat(document.getElementById('amount').value);
		if (amount <= 0) {
			showFieldError(document.getElementById('amount'), __('Amount must be greater than zero'));
			isValid = false;
		}
	}

	if (currentStep === 3) {
		const email = document.querySelector('[name="donor_email"]').value;
		if (!isValidEmail(email)) {
			showFieldError(document.querySelector('[name="donor_email"]'), __('Please enter a valid email address'));
			isValid = false;
		}
	}

	if (currentStep === 4) {
		const selectedPayment = document.querySelector('[name="payment_method"]:checked');
		if (!selectedPayment) {
			showAlert(__('Please select a payment method'), 'danger');
			isValid = false;
		}
	}

	if (currentStep === 5) {
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
	const currentStepElement = document.querySelector(`[data-step="${currentStep}"]`);
	const inputs = currentStepElement.querySelectorAll('input, select, textarea');

	inputs.forEach(input => {
		if (input.type === 'checkbox') {
			formData[input.name] = input.checked;
		} else if (input.type === 'radio') {
			if (input.checked) {
				formData[input.name] = input.value;
			}
		} else {
			formData[input.name] = input.value;
		}
	});
}

function setupFormValidation() {
	// Add real-time validation for amount
	const amountField = document.getElementById('amount');
	if (amountField) {
		amountField.addEventListener('input', function() {
			const value = parseFloat(this.value);
			if (value > 0) {
				clearFieldError(this);
			}
		});
	}

	// Add real-time validation for email
	const emailField = document.querySelector('[name="donor_email"]');
	if (emailField) {
		emailField.addEventListener('blur', function() {
			if (isValidEmail(this.value)) {
				clearFieldError(this);
			}
		});
	}
}

function initializePaymentMethods() {
	// Set up payment method selection handlers
	document.querySelectorAll('.payment-method').forEach(method => {
		method.addEventListener('click', function() {
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
	// Collect all form data
	collectStepData();

	// Generate summary
	const summaryHtml = `
        <div class="summary-row">
            <span>${__('Donation Amount')}:</span>
            <span><strong>€${parseFloat(formData.amount || 0).toFixed(2)}</strong></span>
        </div>
        <div class="summary-row">
            <span>${__('Donation Type')}:</span>
            <span>${document.querySelector('[name="donation_type"] option:checked').textContent}</span>
        </div>
        <div class="summary-row">
            <span>${__('Frequency')}:</span>
            <span>${document.querySelector('[name="donation_status"] option:checked').textContent}</span>
        </div>
        <div class="summary-row">
            <span>${__('Purpose')}:</span>
            <span>${getPurposeSummary()}</span>
        </div>
        <div class="summary-row">
            <span>${__('Donor')}:</span>
            <span>${formData.donor_name || ''} (${formData.donor_email || ''})</span>
        </div>
        <div class="summary-row">
            <span>${__('Payment Method')}:</span>
            <span>${document.querySelector('[name="payment_method"]:checked + h5')?.textContent || formData.payment_method}</span>
        </div>
        <div class="summary-row">
            <span>${__('Total Amount')}:</span>
            <span><strong>€${parseFloat(formData.amount || 0).toFixed(2)}</strong></span>
        </div>
    `;

	document.getElementById('donation-summary').innerHTML = summaryHtml;
}

function getPurposeSummary() {
	const purposeType = formData.donation_purpose_type || 'General';

	switch (purposeType) {
		case 'Campaign':
			return `${__('Campaign')}: ${formData.campaign_reference || __('Not specified')}`;
		case 'Chapter':
			return `${__('Chapter')}: ${formData.chapter_reference || __('Not specified')}`;
		case 'Specific Goal':
			return `${__('Specific Goal')}: ${formData.specific_goal_description || __('Not specified')}`;
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

	// Collect final form data
	collectStepData();

	// Submit to backend
	frappe.call({
		method: 'verenigingen.templates.pages.donate.submit_donation',
		args: formData,
		callback: function(response) {
			submitBtn.disabled = false;
			submitText.style.display = 'inline-block';
			submitLoading.style.display = 'none';

			if (response.message.success) {
				showSuccessStep(response.message);
			} else {
				showAlert(response.message.message || __('An error occurred'), 'danger');
			}
		},
		error: function(error) {
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
	currentStep = 'success';
	showStep('success');

	// Update progress to 100%
	document.getElementById('form-progress').style.width = '100%';

	// Populate success details
	let successContent = `
        <div class="alert alert-success">
            <strong>${__('Donation ID')}:</strong> ${response.donation_id}<br>
            <strong>${__('Amount')}:</strong> €${parseFloat(formData.amount).toFixed(2)}
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
				callback: function(response) {
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
	navigator.clipboard.writeText(text).then(function() {
		showAlert(__('Copied to clipboard!'), 'success');
	});
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
