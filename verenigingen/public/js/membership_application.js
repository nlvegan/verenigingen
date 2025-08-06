/**
 * @fileoverview Membership Application Form - Multi-Step Public Registration System
 *
 * This module provides a comprehensive, user-friendly membership application form
 * for public-facing member registration. Features a modern multi-step interface
 * with real-time validation, payment integration, and seamless backend processing.
 *
 * ## Core Business Functions
 * - **Multi-Step Registration**: Progressive form completion with validation at each step
 * - **Membership Type Selection**: Dynamic options based on organizational configuration
 * - **Payment Integration**: SEPA direct debit, iDEAL, and other Dutch payment methods
 * - **Chapter Assignment**: Geographic-based or preference-based chapter selection
 * - **ANBI Compliance**: Built-in tax benefit information and consent collection
 * - **Data Privacy**: GDPR-compliant data collection with explicit consent management
 *
 * ## Technical Architecture
 * - **Modular Components**: Service-oriented architecture with reusable components
 * - **State Management**: Centralized application state with persistence
 * - **Progressive Enhancement**: Works without JavaScript, enhanced with modern features
 * - **API Integration**: RESTful backend communication with error handling
 * - **Responsive Design**: Mobile-first interface with accessibility support
 * - **Auto-Save Functionality**: Prevents data loss during lengthy form completion
 *
 * ## Form Steps
 * 1. **Personal Information**: Basic contact details and identity data
 * 2. **Membership Type**: Selection of membership level and benefits
 * 3. **Chapter Selection**: Geographic or interest-based chapter assignment
 * 4. **Payment Method**: SEPA mandate setup or alternative payment selection
 * 5. **Consent & Privacy**: GDPR, ANBI, and communication preferences
 * 6. **Review & Submit**: Final validation and submission
 *
 * ## Payment Processing
 * - **SEPA Direct Debit**: Automated recurring payment setup with mandate management
 * - **iDEAL Integration**: Real-time bank payments for Dutch users
 * - **Payment Validation**: Real-time IBAN validation and bank verification
 * - **Dues Calculation**: Automatic calculation based on membership type and duration
 * - **Proration Support**: Mid-year membership adjustments
 *
 * ## Validation System
 * - **Real-time Validation**: Field-level validation with immediate feedback
 * - **Server-side Verification**: Critical validation performed on backend
 * - **IBAN Validation**: MOD-97 algorithm with bank lookup
 * - **Email Verification**: Domain validation and deliverability checks
 * - **Address Validation**: PostNL integration for Dutch addresses
 *
 * ## Data Management
 * - **Auto-Save**: Periodic state preservation to prevent data loss
 * - **Session Management**: Secure handling of multi-step form state
 * - **Error Recovery**: Graceful handling of network failures and timeouts
 * - **Progress Tracking**: Visual indicators and completion status
 * - **Draft Management**: Ability to save and resume incomplete applications
 *
 * ## Integration Points
 * - Verenigingen Member management system
 * - ERPNext Customer creation workflow
 * - SEPA mandate processing
 * - Email notification system
 * - Chapter management integration
 * - Membership dues scheduling
 *
 * ## Security Features
 * - **CSRF Protection**: Token-based request validation
 * - **Input Sanitization**: XSS prevention and data cleaning
 * - **Rate Limiting**: Prevents abuse and spam submissions
 * - **Data Encryption**: Sensitive data protection in transit and storage
 * - **Audit Logging**: Complete trail of application processing
 *
 * ## User Experience
 * - **Progressive Disclosure**: Information revealed as needed
 * - **Smart Defaults**: Intelligent form pre-population
 * - **Accessibility**: WCAG 2.1 AA compliance
 * - **Multi-language**: Dutch and English language support
 * - **Mobile Optimization**: Touch-friendly interface design
 *
 * @company R.S.P. (Verenigingen Association Management)
 * @version 2025.1.0
 * @since 2023.1.0
 * @license Proprietary
 *
 * @requires frappe>=15.0.0
 * @requires verenigingen.member
 * @requires verenigingen.chapter
 * @requires verenigingen.membership_type
 *
 * @see {@link /api/method/verenigingen.api.membership_application} Application API
 * @see {@link /membership_application} Public registration form
 */

/**
 * Refactored Membership Application JavaScript
 * Uses modular components and services for better maintainability
 * Updated to use the Membership Dues Schedule system.
 */

// Form Validator class - needed by BaseStep
class FormValidator {
	validateRequired(selector) {
		const element = $(selector);
		const value = element.val()?.trim();

		if (!value) {
			this.showError(selector, 'This field is required');
			return false;
		}

		this.showSuccess(selector);
		return true;
	}

	showError(selector, message) {
		const element = $(selector);
		element.addClass('is-invalid').removeClass('is-valid');

		let feedback = element.siblings('.invalid-feedback');
		if (feedback.length === 0) {
			feedback = $('<div class="invalid-feedback"></div>');
			element.after(feedback);
		}
		feedback.text(message).show();
	}

	showSuccess(selector) {
		const element = $(selector);
		element.addClass('is-valid').removeClass('is-invalid');
		element.siblings('.invalid-feedback').hide();
	}
}

// Base class for step components
class BaseStep {
	constructor(stepId) {
		this.stepId = stepId;
		this.validator = new FormValidator();
	}

	render(state) {
		// Override in subclasses
	}

	bindEvents() {
		// Override in subclasses
	}

	async validate() {
		// Override in subclasses
		return true;
	}

	getData() {
		// Override in subclasses
		return {};
	}
}

class _MembershipApplication {
	constructor(config = {}) {
		this.config = {
			maxSteps: 6,
			autoSaveInterval: 30000,
			enableErrorHandling: true,
			enableAutoSave: true,
			...config
		};

		// Wait for service classes to be available, then initialize
		this._initializeServices();

		// Legacy state for compatibility
		this.state = new ApplicationState();
		this.membershipTypes = [];
		this.paymentMethod = '';

		this.init();
	}

	_initializeServices() {
		// Initialize services when available
		if (typeof APIService !== 'undefined') {
			this.apiService = new APIService({
				timeout: 30000,
				retryCount: 3
			});
		} else {
			this.apiService = new MembershipAPI();
		}

		if (typeof ValidationService !== 'undefined') {
			this.validationService = new ValidationService(this.apiService);
		}

		if (typeof StorageService !== 'undefined') {
			this.storageService = new StorageService(this.apiService, {
				autoSaveInterval: this.config.autoSaveInterval
			});
		}

		if (typeof ErrorHandler !== 'undefined') {
			this.errorHandler = new ErrorHandler({
				enableLogging: true,
				enableUserFeedback: true
			});
		}

		if (typeof StepManager !== 'undefined' && this.validationService && this.storageService) {
			this.stepManager = new StepManager(
				this.validationService,
				this.storageService,
				{
					totalSteps: this.config.maxSteps,
					autoSave: this.config.enableAutoSave
				}
			);
		}
	}

	initializeSteps() {
		// Initialize step classes for form validation and interaction
		this.steps = [
			new PersonalInfoStep(),
			new AddressStep(),
			new MembershipStep(),
			new VolunteerStep(),
			new PaymentStep(),
			new ConfirmationStep()
		];

		// Bind events for all steps
		this.steps.forEach(step => {
			try {
				step.bindEvents();
				step.render(this.state);
			} catch (error) {
				console.warn(`Failed to initialize step ${step.stepId}:`, error);
			}
		});

		console.log('Initialized', this.steps.length, 'form steps');
	}

	async init() {
		try {
			console.log('Initializing refactored membership application...');

			// Initialize step classes
			this.initializeSteps();

			// Load initial data
			await this.loadInitialData();

			// Set up validation for form fields
			this.setupFieldValidation();

			// Bind events
			this.bindEvents();

			// Start auto-save if enabled
			if (this.config.enableAutoSave && this.storageService && typeof this.storageService.startAutoSave === 'function') {
				this.storageService.startAutoSave(() => this.getAllFormData());
			}

			// Try to load any existing draft
			await this.loadExistingDraft();

			console.log('Refactored membership application initialized successfully');
		} catch (error) {
			console.error('Failed to initialize application:', error);
			if (this.errorHandler && typeof this.errorHandler.handleError === 'function') {
				this.errorHandler.handleError(error, { context: 'initialization' });
			} else {
				console.warn('ErrorHandler not available, showing basic error message');
				// Show a simple error message to the user
				if (typeof frappe !== 'undefined' && frappe.msgprint) {
					frappe.msgprint({
						title: 'Initialization Error',
						message: 'Failed to initialize the membership application form. Please refresh the page.',
						indicator: 'red'
					});
				}
			}
		}
	}

	async loadInitialData() {
		try {
			console.log('Loading form data...');
			const data = await this.apiService.getFormData();

			// Store in both legacy state and new format
			this.state.setInitialData(data);
			this.membershipTypes = data.membership_types || [];

			console.log('Form data loaded:', data);

			// Load static data into form fields
			this.loadStaticData(data);
		} catch (error) {
			console.error('Failed to load initial data:', error);
			if (this.errorHandler && typeof this.errorHandler.handleAPIError === 'function') {
				this.errorHandler.handleAPIError(error, 'get_application_form_data');
			}
			throw error;
		}
	}

	loadStaticData(data) {
		// Load countries into address step
		const countries = data.countries || this.state.get('countries');
		if (countries && countries.length > 0) {
			const select = $('#country');
			if (select.length && select.children().length <= 1) {
				select.empty().append('<option value="">Select Country...</option>');

				countries.forEach(country => {
					select.append(`<option value="${country.name}">${country.name}</option>`);
				});

				// Set Netherlands as default
				select.val('Netherlands');
			}
		}

		// Load chapters - always try to load chapters
		const chapters = data.chapters || this.state.get('chapters');
		const select = $('#selected_chapter');

		if (select.length) {
			// Always populate chapter dropdown if chapters exist
			if (chapters && chapters.length > 0) {
				// Only rebuild if not already populated
				if (select.children().length <= 1) {
					select.empty().append('<option value="">Select a chapter...</option>');

					chapters.forEach(chapter => {
						let displayText = chapter.name;
						const locationInfo = [];

						if (chapter.region) { locationInfo.push(chapter.region); }

						if (locationInfo.length > 0) {
							displayText += ` (${locationInfo.join(', ')})`;
						}

						select.append(`<option value="${chapter.name}">${displayText}</option>`);
					});
				}
			} else {
				// No chapters available - show message
				select.empty().append('<option value="">No chapters available</option>');
			}

			// Chapter selection is always visible in the HTML now
			// No need to show/hide
		}

		// Load membership types
		this.loadMembershipTypes(data.membership_types || []);

		// Load payment methods
		this.loadPaymentMethods(data.payment_methods || []);
	}

	bindEvents() {
		// Navigation handled by StepManager, but we can add custom handlers
		$(document).on('step:change', (event, data) => {
			this.onStepChange(data.from, data.to);
		});

		$(document).on('application:submit', (event, data) => {
			this.submitApplication(data);
		});

		// Legacy form submit handler
		$('#membership-application-form').off('submit').on('submit', (e) => {
			e.preventDefault();
			if (this.stepManager && typeof this.stepManager.submitApplication === 'function') {
				this.stepManager.submitApplication();
			} else {
				this.submitApplication();
			}
		});

		// Bind step navigation buttons
		this.bindStepNavigation();

		// Custom validation events
		this.bindCustomValidationEvents();

		// Direct binding for age calculation since step system might not be working
		this.bindAgeCalculation();

		// Bind chapter suggestion based on postal code
		this.bindChapterSuggestion();
	}

	bindStepNavigation() {
		// Initialize step navigation
		this.currentStep = 1;
		this.maxSteps = 6; // Fixed: Match template which has 6 steps

		// Show first step
		this.showStep(1);

		// Next button
		$('#btn-next').off('click').on('click', async (e) => {
			e.preventDefault();
			console.log('Next button clicked, current step:', this.currentStep);

			// Disable button during validation
			$('#btn-next').prop('disabled', true).html('<i class="fa fa-spinner fa-spin"></i> Validating...');

			try {
				await this.nextStep();
			} finally {
				// Re-enable button
				$('#btn-next').prop('disabled', false).html('Next →');
			}
		});

		// Previous button
		$('#btn-prev').off('click').on('click', (e) => {
			e.preventDefault();
			console.log('Previous button clicked, current step:', this.currentStep);
			this.prevStep();
		});

		// Submit button
		$('#btn-submit').off('click').on('click', (e) => {
			e.preventDefault();
			console.log('Submit button clicked');
			this.submitApplication();
		});
	}

	async nextStep() {
		// Await validation before proceeding
		const isValid = await this.validateCurrentStep();
		if (isValid && this.currentStep < this.maxSteps) {
			this.currentStep++;
			this.showStep(this.currentStep);
		} else if (!isValid) {
			console.log('Validation failed for step:', this.currentStep);
		}
	}

	prevStep() {
		if (this.currentStep > 1) {
			this.currentStep--;
			this.showStep(this.currentStep);
		}
	}

	showStep(step) {
		console.log('Showing step:', step);

		// Hide all steps
		$('.form-step').hide().removeClass('active');

		// Show current step
		$(`.form-step[data-step="${step}"]`).show().addClass('active');

		// Update navigation buttons
		if (step > 1) {
			$('#btn-prev').removeClass('hidden').show();
		} else {
			$('#btn-prev').addClass('hidden').hide();
		}

		if (step < this.maxSteps) {
			$('#btn-next').removeClass('hidden').show();
			$('#btn-submit').addClass('hidden').hide();
		} else {
			$('#btn-next').addClass('hidden').hide();
			$('#btn-submit').removeClass('hidden').show();
		}

		// Update progress bar
		const progress = (step / this.maxSteps) * 100;
		$('#form-progress').css('width', `${progress}%`);

		// Update step indicators
		$('.step').removeClass('active completed');
		for (let i = 1; i < step; i++) {
			$(`.step[data-step="${i}"]`).addClass('completed');
		}
		$(`.step[data-step="${step}"]`).addClass('active');

		// Update internal state
		this.state.set('currentStep', step);

		// Set up step-specific content
		this.setupStepContent(step);

		// Scroll to top
		window.scrollTo(0, 0);
	}

	async validateCurrentStep() {
		console.log('Validating step:', this.currentStep);

		// Use basic validation for now (step-specific validation disabled)
		// TODO: Fix step-specific validation integration
		return this.validateStepBasic(this.currentStep);
	}

	validateStepBasic(step) {
		let isValid = true;

		// Clear previous errors only for current step
		$(`.form-step[data-step="${step}"] .is-invalid`).removeClass('is-invalid');
		$(`.form-step[data-step="${step}"] .invalid-feedback`).hide();

		switch (step) {
			case 1: { // Personal info
				const requiredFields = ['#first_name', '#last_name', '#email', '#birth_date'];
				requiredFields.forEach(field => {
					const $field = $(field);
					if (!$field.val() || $field.val().trim() === '') {
						$field.addClass('is-invalid');
						const feedback = $field.siblings('.invalid-feedback');
						if (feedback.length === 0) {
							$field.after('<div class="invalid-feedback">This field is required</div>');
						}
						$field.siblings('.invalid-feedback').show();
						isValid = false;
					}
				});

				// Email validation
				const email = $('#email').val();
				if (email && !this.isValidEmail(email)) {
					$('#email').addClass('is-invalid');
					$('#email').siblings('.invalid-feedback').text('Please enter a valid email').show();
					isValid = false;
				}
				break;
			}
			case 2: { // Address
				const addressFields = ['#address_line1', '#city', '#postal_code', '#country'];
				addressFields.forEach(field => {
					const $field = $(field);
					if (!$field.val() || $field.val().trim() === '') {
						$field.addClass('is-invalid');
						const feedback = $field.siblings('.invalid-feedback');
						if (feedback.length === 0) {
							$field.after('<div class="invalid-feedback">This field is required</div>');
						}
						$field.siblings('.invalid-feedback').show();
						isValid = false;
					}
				});
				break;
			}
			case 3: { // Membership type
				const selectedType = this.state.get('selected_membership_type');
				const membership = this.state.get('membership');

				if (!selectedType && (!membership || !membership.type)) {
					$('#membership-type-error').text('Please select a membership type').show();
					isValid = false;
				} else {
					// Check if custom amount is valid when used
					const membershipAmount = this.state.get('custom_contribution_fee') || (membership && membership.amount);
					const usesCustomAmount = this.state.get('uses_custom_amount') || (membership && membership.isCustom);

					if (usesCustomAmount && (!membershipAmount || membershipAmount <= 0)) {
						$('#membership-type-error').text('Please enter a valid membership amount').show();
						isValid = false;
					} else if (usesCustomAmount && membershipAmount > 0) {
						// Validate minimum fee requirement
						const currentType = selectedType || (membership && membership.type);
						if (currentType && this.membershipTypes && this.membershipTypes.length > 0) {
							const typeData = this.membershipTypes.find(t => t.name === currentType);
							if (typeData && typeData.amount) {
								const minAmount = typeData.amount * 0.5; // 50% minimum
								if (membershipAmount < minAmount) {
									const formattedMin = this.formatCurrency(minAmount);
									$('#membership-type-error').text(`Minimum contribution is ${formattedMin} (50% of standard amount)`).show();
									isValid = false;
								}
							}
						}
					}
				}
				break;
			}
			case 4: { // Volunteer (optional)
				// No required fields
				break;
			}
			case 5: { // Payment
				console.log('Validating step 5 - Payment');

				// Check payment method selection
				const paymentMethod = $('input[name="payment_method"]:checked').val();
				console.log('Payment method selected:', paymentMethod);
				if (!paymentMethod) {
					console.log('No payment method selected');
					if (typeof frappe !== 'undefined' && frappe.msgprint) {
						frappe.msgprint('Please select a payment method');
					}
					isValid = false;
				}

				// Check IBAN
				const iban = $('#iban').val();
				console.log('IBAN value:', iban);
				if (!iban || iban.trim() === '') {
					console.log('IBAN is empty');
					$('#iban').addClass('is-invalid');
					const feedback = $('#iban').siblings('.invalid-feedback');
					if (feedback.length === 0) {
						$('#iban').after('<div class="invalid-feedback">IBAN is required</div>');
					}
					$('#iban').siblings('.invalid-feedback').show();
					isValid = false;
				} else {
					// Perform comprehensive IBAN validation with checksum
					const validation = this.performIBANValidation(iban);
					if (!validation.valid) {
						console.log('IBAN validation failed:', validation.error);
						$('#iban').removeClass('is-valid').addClass('is-invalid');
						$('#iban').siblings('.invalid-feedback').remove();
						$('#iban').after(`<div class="invalid-feedback">${validation.error}</div>`);
						isValid = false;
					} else {
						// Format the IBAN if valid
						$('#iban').val(validation.formatted);
						$('#iban').removeClass('is-invalid').addClass('is-valid');
					}
				}

				// Check account holder name
				const accountHolder = $('#account_holder_name').val();
				console.log('Account holder name:', accountHolder);
				if (!accountHolder || accountHolder.trim() === '') {
					console.log('Account holder name is empty');
					$('#account_holder_name').addClass('is-invalid');
					const feedback = $('#account_holder_name').siblings('.invalid-feedback');
					if (feedback.length === 0) {
						$('#account_holder_name').after('<div class="invalid-feedback">Account holder name is required</div>');
					}
					$('#account_holder_name').siblings('.invalid-feedback').show();
					isValid = false;
				}

				console.log('Step 5 validation result:', isValid);
				break;
			}
			case 6: { // Confirmation
				// Check terms and privacy checkboxes
				if (!$('input[name="terms_accepted"]').is(':checked')) {
					if (typeof frappe !== 'undefined' && frappe.msgprint) {
						frappe.msgprint('Please accept the terms and conditions');
					}
					isValid = false;
				}

				if (!$('input[name="privacy_accepted"]').is(':checked')) {
					if (typeof frappe !== 'undefined' && frappe.msgprint) {
						frappe.msgprint('Please agree to the privacy policy');
					}
					isValid = false;
				}
				break;
			}
		}

		return isValid;
	}

	isValidEmail(email) {
		return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
	}

	// Step navigation now handled by StepManager
	onStepChange(fromStep, toStep) {
		console.log(`Step changed from ${fromStep} to ${toStep}`);

		// Update legacy state for compatibility
		this.state.set('currentStep', toStep);

		// Perform step-specific setup
		this.setupStepContent(toStep);
	}

	setupStepContent(stepNumber) {
		switch (stepNumber) {
			case 1:
				this.setupPersonalInfoStep();
				break;
			case 2:
				this.setupAddressStep();
				break;
			case 3:
				this.setupMembershipStep();
				break;
			case 4:
				this.setupVolunteerStep();
				break;
			case 5:
				this.setupPaymentStep();
				break;
			case 6:
				this.setupConfirmationStep();
				break;
		}
	}

	getCurrentStep() {
		if (this.stepManager && typeof this.stepManager.getCurrentStep === 'function') {
			return this.stepManager.getCurrentStep();
		}
		return this.currentStep || 1;
	}

	// New method to get all form data
	getAllFormData() {
		const formData = {};

		// Get data from step manager if available
		if (this.stepManager && typeof this.stepManager.getAllData === 'function') {
			try {
				const stepData = this.stepManager.getAllData();
				Object.assign(formData, stepData);
			} catch (error) {
				console.warn('StepManager.getAllData failed:', error);
			}
		}

		// Collect data directly from form fields (fallback and primary method)
		const directFormData = this.collectFormDataDirectly();
		Object.assign(formData, directFormData);

		// Get additional form data not handled by step manager
		const additionalData = this.getAdditionalFormData();
		Object.assign(formData, additionalData);

		return formData;
	}

	collectFormDataDirectly() {
		// Collect data directly from form fields
		return {
			// Step 1: Personal Information
			first_name: $('#first_name').val() || '',
			middle_name: $('#middle_name').val() || '',
			tussenvoegsel: $('#tussenvoegsel').val() || '',
			last_name: $('#last_name').val() || '',
			email: $('#email').val() || '',
			contact_number: $('#contact_number').val() || '',
			birth_date: $('#birth_date').val() || '',
			pronouns: $('#pronouns').val() || '',

			// Step 2: Address Information
			address_line1: $('#address_line1').val() || '',
			address_line2: $('#address_line2').val() || '',
			city: $('#city').val() || '',
			state: $('#state').val() || '',
			postal_code: $('#postal_code').val() || '',
			country: $('#country').val() || '',

			// Step 3: Membership and Chapter selection
			selected_membership_type: this.state.get('selected_membership_type') || '',
			custom_contribution_fee: this.state.get('custom_contribution_fee') || 0,
			uses_custom_amount: this.state.get('uses_custom_amount') || false,
			selected_chapter: $('#selected_chapter').val() || '',

			// Step 4: Volunteer Information
			interested_in_volunteering: $('#interested_in_volunteering').is(':checked'),
			volunteer_availability: $('#volunteer_availability').val() || '',
			volunteer_experience_level: $('#volunteer_experience_level').val() || '',
			newsletter_opt_in: $('#newsletter_opt_in').is(':checked'),
			application_source: $('#application_source').val() || '',
			application_source_details: $('#application_source_details').val() || '',

			// Step 5: Payment Details
			payment_method: $('input[name="payment_method"]:checked').val() || $('#payment_method').val() || '',


			// Bank Account Details (SEPA Direct Debit)
			iban: $('#iban').val() || '',
			bank_account_name: $('#account_holder_name').val() || $('#bank_account_name').val() || '',

			// Bank Transfer Account Details (for payment matching)
			// Note: These should map to the member IBAN fields when payment_method is 'Bank Transfer'
			transfer_iban: $('#transfer_iban').val() || '',
			transfer_account_name: $('#transfer_account_name').val() || '',

			// Step 6: Final Confirmation
			additional_notes: $('#additional_notes').val() || '',
			terms: $('#terms').is(':checked'),
			gdpr_consent: $('#gdpr_consent').is(':checked'),
			confirm_accuracy: $('#confirm_accuracy').is(':checked'),

			// Collect volunteer interests
			volunteer_interests: this.getSelectedVolunteerInterests(),

			// Collect volunteer skills
			volunteer_skills: this.getVolunteerSkills()
		};
	}

	getSelectedVolunteerInterests() {
		const interests = [];
		$('#volunteer-interests input[type="checkbox"]:checked').each(function () {
			interests.push($(this).val());
		});
		return interests;
	}

	getVolunteerSkills() {
		const skills = [];
		$('.skill-row').each(function () {
			const skillName = $(this).find('input[name="skill_name[]"]').val();
			const skillLevel = $(this).find('select[name="skill_level[]"]').val();

			if (skillName && skillName.trim() && skillLevel) {
				skills.push({
					skill_name: skillName.trim(),
					skill_level: skillLevel
				});
			}
		});
		return skills;
	}

	bindAgeCalculation() {
		// Bind age calculation to birth date field
		$('#birth_date').on('change blur', () => {
			this.calculateAndShowAge();
		});
	}

	bindChapterSuggestion() {
		// Bind chapter suggestion to postal code field changes
		$(document).on('change blur', '#postal_code', async () => {
			const postalCode = $('#postal_code').val();
			const city = $('#city').val();
			const country = $('#country').val();

			if (postalCode && postalCode.trim().length >= 4) {
				console.log('Checking chapter suggestion for postal code:', postalCode);
				await this.suggestChapterFromPostalCode(postalCode, city, country);
			} else {
				// Hide suggestion if postal code is too short
				$('#suggested-chapter').hide();
			}
		});

		// Also trigger when city changes (for better matching)
		$(document).on('change blur', '#city', async () => {
			const postalCode = $('#postal_code').val();
			const city = $('#city').val();
			const country = $('#country').val();

			if (postalCode && postalCode.trim().length >= 4 && city) {
				console.log('Checking chapter suggestion for city + postal code:', city, postalCode);
				await this.suggestChapterFromPostalCode(postalCode, city, country);
			}
		});
	}

	async suggestChapterFromPostalCode(postalCode, city, country) {
		try {
			console.log('Suggesting chapters for:', { postalCode, city, country });

			// Make API call to get chapter suggestions
			const result = await new Promise((resolve, reject) => {
				frappe.call({
					method: 'verenigingen.verenigingen.doctype.chapter.chapter.suggest_chapters_for_member',
					args: {
						member: null, // We don't have a member yet during application
						postal_code: postalCode,
						city,
						state: null // Could be derived from city if needed
					},
					callback: (r) => {
						if (r.message !== undefined) {
							resolve(r.message);
						} else {
							reject(new Error('No response'));
						}
					},
					error: reject
				});
			});

			console.log('Chapter suggestion result:', result);

			if (result && result.length > 0) {
				this.showChapterSuggestion(result[0]); // Show the best match
			} else {
				// Hide suggestion if no matches found
				$('#suggested-chapter').hide();
			}
		} catch (error) {
			console.error('Error suggesting chapters:', error);
			// Hide suggestion on error
			$('#suggested-chapter').hide();
		}
	}

	showChapterSuggestion(chapter) {
		const suggestionDiv = $('#suggested-chapter');

		if (suggestionDiv.length === 0) {
			// Create suggestion div if it doesn't exist
			$('#chapter-selection').append(`
                <div id="suggested-chapter" class="alert alert-info mt-3" style="display: none;">
                    <h6><i class="fa fa-lightbulb-o"></i> Suggested Chapter</h6>
                    <div id="chapter-suggestion-content"></div>
                    <div class="mt-2">
                        <button type="button" class="btn btn-sm btn-primary" id="accept-chapter-suggestion">
                            Select This Chapter
                        </button>
                        <button type="button" class="btn btn-sm btn-outline-secondary" id="dismiss-chapter-suggestion">
                            Dismiss
                        </button>
                    </div>
                </div>
            `);

			// Bind events for suggestion buttons
			$('#accept-chapter-suggestion').on('click', () => {
				$('#chapter').val(chapter.name).trigger('change');
				$('#suggested-chapter').hide();
			});

			$('#dismiss-chapter-suggestion').on('click', () => {
				$('#suggested-chapter').hide();
			});
		}

		// Update content
		const content = `
            <p><strong>${chapter.name}</strong></p>
            <p class="mb-1">Location: ${chapter.city || chapter.state || 'Not specified'}</p>
            <p class="mb-1 text-muted">Match score: ${chapter.match_score || 0}%</p>
        `;

		$('#chapter-suggestion-content').html(content);
		$('#suggested-chapter').show();
	}

	calculateAndShowAge() {
		const birthDate = $('#birth_date').val();
		const ageWarning = $('#age-warning');

		if (!birthDate) {
			ageWarning.hide();
			return;
		}

		const today = new Date();
		const birth = new Date(birthDate);
		let age = today.getFullYear() - birth.getFullYear();
		const monthDiff = today.getMonth() - birth.getMonth();

		if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birth.getDate())) {
			age--;
		}

		// Show age warnings
		if (age < 16) {
			ageWarning.html('<strong>Note:</strong> You must be at least 16 years old to become a member. Please contact us if you have questions.').show();
		} else if (age < 18) {
			ageWarning.html('<strong>Note:</strong> You are under 18. Parental consent may be required for membership.').show();
		} else if (age > 120) {
			ageWarning.html('<strong>Please check your birth date:</strong> The entered date would make you over 120 years old.').show();
		} else {
			ageWarning.hide();
		}

		return age;
	}

	bindCustomValidationEvents() {
		// Email validation
		$('#email').on('blur', () => {
			this.validateEmail();
		});

		// Postal code validation and chapter suggestion
		$('#postal_code').on('blur', () => {
			this.validatePostalCodeAndSuggestChapter();
		});

		// IBAN validation
		$('#iban').on('blur', () => {
			this.validateIBAN();
		});
	}

	validateEmail() {
		const email = $('#email').val();
		const emailField = $('#email');

		if (!email) { return; }

		// Basic email regex
		const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

		if (!emailRegex.test(email)) {
			emailField.addClass('is-invalid');
			emailField.siblings('.invalid-feedback').remove();
			emailField.after('<div class="invalid-feedback">Please enter a valid email address</div>');
		} else {
			emailField.removeClass('is-invalid').addClass('is-valid');
			emailField.siblings('.invalid-feedback').hide();
		}
	}

	validatePostalCodeAndSuggestChapter() {
		const postalCode = $('#postal_code').val();

		if (!postalCode || postalCode.length < 4) { return; }

		// Call API to validate postal code and suggest chapters
		frappe.call({
			method: 'verenigingen.api.membership_application.suggest_chapters_for_postal_code',
			args: { postal_code: postalCode },
			callback: (r) => {
				if (r.message && r.message.suggested_chapters && r.message.suggested_chapters.length > 0) {
					// Show chapter suggestions
					this.showChapterSuggestions(r.message.suggested_chapters);
				}
			}
		});
	}

	validateIBAN() {
		const iban = $('#iban').val();
		const ibanField = $('#iban');

		if (!iban) { return; }

		// Use comprehensive IBAN validation with mod-97 checksum
		const validation = this.performIBANValidation(iban);

		// Remove existing feedback
		ibanField.siblings('.invalid-feedback').remove();
		ibanField.siblings('.valid-feedback').remove();

		if (!validation.valid) {
			ibanField.removeClass('is-valid').addClass('is-invalid');
			ibanField.after(`<div class="invalid-feedback">${validation.error}</div>`);

			// Clear BIC field if IBAN is invalid
			$('#bic').val('');
		} else {
			ibanField.removeClass('is-invalid').addClass('is-valid');

			// Format the IBAN
			ibanField.val(validation.formatted);

			// Show success message with bank info if available
			const bankName = this.getBankNameFromIBAN(iban);
			if (bankName) {
				ibanField.after(`<div class="valid-feedback">Valid ${bankName} IBAN</div>`);
			} else {
				ibanField.after('<div class="valid-feedback">Valid IBAN</div>');
			}

			// Auto-derive BIC for Dutch IBANs
			const bic = this.deriveBICFromIBAN(iban);
			if (bic && $('#bic').length > 0) {
				$('#bic').val(bic);
				$('#bic').prop('readonly', true);
				$('#bic').addClass('is-valid');
			}
		}
	}

	performIBANValidation(iban) {
		if (!iban) {
			return { valid: false, error: 'IBAN is required' };
		}

		// Remove spaces and convert to uppercase
		const cleanIBAN = iban.replace(/\s/g, '').toUpperCase();

		// Check for invalid characters
		if (!/^[A-Z0-9]+$/.test(cleanIBAN)) {
			return { valid: false, error: 'IBAN contains invalid characters' };
		}

		// Basic format check
		if (!/^[A-Z]{2}[0-9]{2}[A-Z0-9]+$/.test(cleanIBAN)) {
			return { valid: false, error: 'Invalid IBAN format' };
		}

		// Extract country code
		const countryCode = cleanIBAN.substring(0, 2);

		// IBAN length specifications
		const ibanLengths = {
			AD: 24, AT: 20, BE: 16, CH: 21, CZ: 24,
			DE: 22, DK: 18, ES: 24, FI: 18, FR: 27,
			GB: 22, IE: 22, IT: 27, LU: 20, NL: 18,
			NO: 15, PL: 28, PT: 25, SE: 24
		};

		// Check if country is supported
		if (!(countryCode in ibanLengths)) {
			return { valid: false, error: `Unsupported country code: ${countryCode}` };
		}

		// Check length
		const expectedLength = ibanLengths[countryCode];
		if (cleanIBAN.length !== expectedLength) {
			const countryNames = {
				NL: 'Dutch', BE: 'Belgian', DE: 'German',
				FR: 'French', GB: 'British', IT: 'Italian',
				ES: 'Spanish', AT: 'Austrian', CH: 'Swiss'
			};
			const countryName = countryNames[countryCode] || countryCode;
			return {
				valid: false,
				error: `${countryName} IBAN must be ${expectedLength} characters (you have ${cleanIBAN.length})`
			};
		}

		// Perform mod-97 checksum validation
		const rearranged = cleanIBAN.substring(4) + cleanIBAN.substring(0, 4);
		const numeric = rearranged.replace(/[A-Z]/g, char => char.charCodeAt(0) - 55);
		const remainder = numeric.match(/.{1,9}/g).reduce((acc, chunk) => {
			return (parseInt(acc + chunk, 10) % 97).toString();
		}, '');

		if (remainder !== '1') {
			return { valid: false, error: 'Invalid IBAN checksum - please check for typos' };
		}

		// Format IBAN with spaces
		const formatted = cleanIBAN.match(/.{1,4}/g).join(' ');

		return { valid: true, error: null, formatted };
	}

	deriveBICFromIBAN(iban) {
		if (!iban) { return null; }

		const cleanIBAN = iban.replace(/\s/g, '').toUpperCase();

		if (!cleanIBAN.startsWith('NL') || cleanIBAN.length < 8) {
			return null;
		}

		const bankCode = cleanIBAN.substring(4, 8);
		const nlBicCodes = {
			INGB: 'INGBNL2A',
			ABNA: 'ABNANL2A',
			RABO: 'RABONL2U',
			TRIO: 'TRIONL2U',
			SNSB: 'SNSBNL2A',
			ASNB: 'ASNBNL21',
			KNAB: 'KNABNL2H',
			BUNQ: 'BUNQNL2A',
			REVO: 'REVOLT21',
			RBRB: 'RBRBNL21'
		};

		return nlBicCodes[bankCode] || null;
	}

	getBankNameFromIBAN(iban) {
		if (!iban) { return null; }

		const cleanIBAN = iban.replace(/\s/g, '').toUpperCase();

		if (!cleanIBAN.startsWith('NL') || cleanIBAN.length < 8) {
			return null;
		}

		const bankCode = cleanIBAN.substring(4, 8);
		const bankNames = {
			INGB: 'ING',
			ABNA: 'ABN AMRO',
			RABO: 'Rabobank',
			TRIO: 'Triodos Bank',
			SNSB: 'SNS Bank',
			ASNB: 'ASN Bank',
			KNAB: 'Knab',
			BUNQ: 'Bunq',
			RBRB: 'RegioBank'
		};

		return bankNames[bankCode] || null;
	}

	// Legacy method for compatibility
	collectAllData() {
		return this.getAllFormData();
	}

	getAdditionalFormData() {
		// Collect any additional form data not handled by step manager
		return {
			selected_membership_type: this.state.get('selected_membership_type') || '',
			custom_contribution_fee: this.state.get('custom_contribution_fee') || 0,
			uses_custom_amount: this.state.get('uses_custom_amount') || false,
			payment_method: this.getPaymentMethod() || ''
		};
	}

	// Helper methods for state management
	setPaymentMethod(method) {
		this.paymentMethod = method;
		this.state.set('payment_method', method);
		if (this.storageService) {
			this.storageService.markDirty(); // Mark for auto-save
		}
	}

	getPaymentMethod() {
		return this.paymentMethod || this.state.get('payment_method') || '';
	}

	// Auto-save now handled by StorageService
	async saveDraft() {
		try {
			const data = this.getAllFormData();
			const result = this.storageService ? await this.storageService.saveDraft(data) : { success: false, message: 'Storage service not available' };
			console.log('Draft saved:', result);
			return result;
		} catch (error) {
			console.warn('Draft save failed:', error);
			if (this.errorHandler && typeof this.errorHandler.handleError === 'function') {
				this.errorHandler.handleError(error, { context: 'draft_save' });
			}
			return { success: false, error: error.message };
		}
	}

	async loadExistingDraft() {
		if (!this.storageService) { return; }

		try {
			const result = await this.storageService.loadDraft();
			if (result.success && result.data) {
				console.log('Loading existing draft:', result);
				this.populateFormWithData(result.data);

				// Show notification about loaded draft
				if (result.source === 'local' && this.errorHandler && typeof this.errorHandler.showNotification === 'function') {
					this.errorHandler.showNotification('info', 'Draft Loaded',
						'Your previous application progress has been restored.');
				}
			}
		} catch (error) {
			console.warn('Failed to load draft:', error);
			// Don't show error to user as this is not critical
		}
	}

	populateFormWithData(data) {
		// Populate form fields with loaded data
		Object.entries(data).forEach(([key, value]) => {
			const $field = $(`[name="${key}"], #${key}`);
			if ($field.length) {
				if ($field.attr('type') === 'checkbox') {
					$field.prop('checked', Boolean(value));
				} else if ($field.attr('type') === 'radio') {
					$field.filter(`[value="${value}"]`).prop('checked', true);
				} else {
					$field.val(value);
				}
			}
		});

		// Update state
		Object.entries(data).forEach(([key, value]) => {
			this.state.set(key, value);
		});

		// Trigger change events to update UI
		setTimeout(() => {
			$('input, select, textarea').trigger('change');
		}, 100);
	}

	// Enhanced submit method using new services
	async submitApplication(data = null) {
		console.log('Application submission started');

		try {
			// Get form data
			const formData = data || this.getAllFormData();
			console.log('Submitting application data:', formData);

			// Validate we have required data
			if (!formData.first_name || !formData.last_name || !formData.email) {
				throw new Error('Missing required fields: name and email are required');
			}

			if (!formData.selected_membership_type) {
				throw new Error('No membership type selected');
			}

			console.log('Form data validation passed. API Service:', this.apiService);

			// Show loading state
			this.showSubmissionLoading(true);

			// Submit via API service
			const result = await this.apiService.submitApplication(formData);
			console.log('Application submitted successfully:', result);

			// Handle successful submission
			this.handleSubmissionSuccess(result);

			// Clear draft after successful submission
			if (this.storageService) {
				this.storageService.clearAllDrafts();
			}

			return result;
		} catch (error) {
			console.error('Application submission failed:', error);
			this.handleSubmissionError(error);
			throw error;
		} finally {
			this.showSubmissionLoading(false);
		}
	}

	handleSubmissionSuccess(result) {
		// Store application ID
		if (result.application_id && this.storageService) {
			this.storageService.setSessionData('last_application_id', result.application_id);
		}

		// Show success message
		this.showSuccessMessage(result);

		// Redirect to payment if needed
		if (result.payment_url) {
			this.redirectToPayment(result.payment_url);
		}
	}

	handleSubmissionError(error) {
		if (this.errorHandler && typeof this.errorHandler.handleAPIError === 'function') {
			this.errorHandler.handleAPIError(error, 'submit_application', {
				onRetry: () => this.submitApplication()
			});
		} else {
			console.error('Submission error:', error);
			if (typeof frappe !== 'undefined' && frappe.msgprint) {
				frappe.msgprint({
					title: 'Submission Error',
					message: error.message || 'An error occurred while submitting your application',
					indicator: 'red'
				});
			}
		}
	}

	showSubmissionLoading(isLoading) {
		const $submitBtn = $('#btn-submit, #submit-btn');
		if (isLoading) {
			$submitBtn.prop('disabled', true)
				.html('<i class="fa fa-spinner fa-spin"></i> Processing...');
		} else {
			$submitBtn.prop('disabled', false)
				.html('Submit Application');
		}
	}

	showSuccessMessage(result) {
		let successHTML = '<div class="text-center py-5">';
		successHTML += '<div class="success-icon mb-4">';
		successHTML += '<i class="fa fa-check-circle text-success" style="font-size: 4rem;"></i>';
		successHTML += '</div>';
		successHTML += '<h2 class="text-success">Application Submitted Successfully!</h2>';

		if (result.application_id) {
			successHTML += '<div class="alert alert-info mx-auto" style="max-width: 500px;">';
			successHTML += `<h4>Your Application ID: <strong>${result.application_id}</strong></h4>`;
			successHTML += '<p>Please save this ID for future reference.</p>';
			successHTML += '</div>';
		}

		successHTML += '<p class="lead">Thank you for your application.</p>';
		successHTML += '</div>';

		// Fix: Use ID selector instead of class selector
		$('#membership-application-form').html(successHTML);
		window.scrollTo(0, 0);
	}

	redirectToPayment(paymentUrl) {
		if (this.errorHandler && typeof this.errorHandler.showNotification === 'function') {
			this.errorHandler.showNotification('info', 'Redirecting to Payment',
				'You will be redirected to complete payment in 3 seconds.');
		}

		setTimeout(() => {
			window.location.href = paymentUrl;
		}, 3000);
	}
	// ====================
	// NEW METHODS FOR REFACTORED SYSTEM
	// ====================

	setupFieldValidation() {
		// Set up real-time validation for form fields
		if (!this.validationService || typeof this.validationService.setupRealTimeValidation !== 'function') {
			console.log('ValidationService not available, skipping real-time validation setup');
			return;
		}

		const fieldMappings = {
			first_name: 'firstName',
			last_name: 'lastName',
			email: 'email',
			birth_date: 'birthDate',
			address_line1: 'address',
			city: 'city',
			postal_code: 'postalCode',
			country: 'country',
			mobile_no: 'phone'
		};

		Object.entries(fieldMappings).forEach(([fieldId, validationKey]) => {
			const $field = $(`#${fieldId}`);
			if ($field.length) {
				try {
					this.validationService.setupRealTimeValidation($field[0], validationKey, {
						country: () => $('#country').val() || 'Netherlands'
					});
				} catch (error) {
					console.warn(`Failed to setup validation for ${fieldId}:`, error);
				}
			}
		});
	}


	setupPersonalInfoStep() {
		console.log('Setting up personal info step');
		// Any specific setup for personal info step
	}

	setupAddressStep() {
		console.log('Setting up address step');
		// Ensure country dropdown is populated
		if ($('#country option').length <= 1) {
			const countries = this.state.get('countries');
			this.loadCountries(countries);
		}
	}

	setupMembershipStep() {
		console.log('Setting up membership step');

		// Show chapter selection
		$('#chapter-selection').show();

		// Ensure membership types are loaded
		if ($('.membership-type-card').length === 0) {
			this.loadMembershipTypes(this.membershipTypes);
		}

		// Set up income calculator if enabled
		this.setupIncomeCalculator();
	}

	setupVolunteerStep() {
		console.log('Setting up volunteer step');
		// Set up volunteer interest toggle
		$('#interested_in_volunteering').off('change').on('change', function () {
			$('#volunteer-details').toggle($(this).is(':checked'));
		});

		// Set up volunteer skill add button
		this.setupVolunteerSkills();
	}

	setupVolunteerSkills() {
		// Add event handler for the add skill button
		$(document).off('click', '.add-skill').on('click', '.add-skill', (e) => {
			e.preventDefault();
			this.addSkillRow();
		});

		// Add event handler for remove skill buttons
		$(document).off('click', '.remove-skill').on('click', '.remove-skill', (e) => {
			e.preventDefault();
			$(e.target).closest('.skill-row').remove();
		});
	}

	addSkillRow() {
		const _skillContainer = $('.skill-row').parent();
		const newSkillRow = `
            <div class="skill-row" style="margin-bottom: 10px;">
                <div class="row">
                    <div class="col-md-6">
                        <input type="text" class="form-control" name="skill_name[]"
                               placeholder="${frappe._('Skill name (e.g. Event Planning, IT Support)')}" />
                    </div>
                    <div class="col-md-4">
                        <select class="form-control" name="skill_level[]">
                            <option value="">${frappe._('Level')}</option>
                            <option value="Beginner">${frappe._('Beginner')}</option>
                            <option value="Intermediate">${frappe._('Intermediate')}</option>
                            <option value="Advanced">${frappe._('Advanced')}</option>
                            <option value="Expert">${frappe._('Expert')}</option>
                        </select>
                    </div>
                    <div class="col-md-2">
                        <button type="button" class="btn btn-sm btn-danger remove-skill">−</button>
                    </div>
                </div>
            </div>
        `;

		// Find the existing skill rows and add after the last one
		const lastSkillRow = $('.skill-row').last();
		lastSkillRow.after(newSkillRow);

		console.log('Added new skill row');
	}

	setupPaymentStep() {
		// Setup payment method selection and bind events for showing/hiding payment details
		this.bindPaymentMethodEvents();

		if ($('.payment-method-option').length === 0) {
			const paymentMethods = this.state.get('paymentMethods');
			this.loadPaymentMethods(paymentMethods);
		}

		// Add a small delay to ensure DOM is ready, then set up field switching
		setTimeout(() => {
			console.log('SetupPaymentStep: Checking for existing elements');
			console.log('SetupPaymentStep: Payment method radios found:', $('input[name="payment_method_selection"]').length);
			console.log('SetupPaymentStep: Payment method options found:', $('.payment-method-option').length);
			console.log('SetupPaymentStep: Bank account details section found:', $('#bank-account-details').length);
			console.log('SetupPaymentStep: Bank account details section found:', $('#bank-account-details').length);
			console.log('SetupPaymentStep: Bank transfer notice section found:', $('#bank-transfer-notice').length);
			console.log('SetupPaymentStep: Bank transfer details section found:', $('#bank-transfer-details').length);

			// Ensure any pre-selected payment method shows the correct form fields
			const selectedMethod = $('input[name="payment_method_selection"]:checked').val() || $('#payment_method').val();
			if (selectedMethod) {
				console.log('Setting up payment step with pre-selected method:', selectedMethod);
				// Use the new handlePaymentMethodChange method for consistency
				this.handlePaymentMethodChange(selectedMethod);
			} else {
				console.log('SetupPaymentStep: No pre-selected payment method found');
			}
		}, 100);
	}

	setupConfirmationStep() {
		console.log('Setting up confirmation step');
		// Update confirmation step with form data
		this.updateConfirmationDisplay();

		// Ensure the summary is updated after a short delay to handle any async state updates
		setTimeout(() => {
			this.updateConfirmationDisplay();
		}, 100);
	}

	setupIncomeCalculator() {
		console.log('Setting up income calculator');

		// Check if income calculator is enabled and available
		if (!$('#income-calculator').length) {
			console.log('Income calculator not available in this form');
			return;
		}

		// Calculator is always visible when enabled, so just set up functionality
		this.bindIncomeCalculatorEvents();
	}

	bindIncomeCalculatorEvents() {
		// Income calculator variables
		const calculatorSettings = {
			enabled: true,
			percentage: parseFloat($('#calc-income-percentage').text()) || 0.5
		};
		let calculatedAmount = 0;

		function calculateContribution() {
			const monthlyIncome = parseFloat($('#calc-monthly-income').val()) || 0;
			const paymentInterval = $('#calc-payment-interval').val();

			if (monthlyIncome <= 0) {
				$('#calc-result').hide();
				$('#apply-calculated-amount').hide();
				calculatedAmount = 0;
				return;
			}

			// Calculate based on percentage of monthly income
			const monthlyContribution = monthlyIncome * (calculatorSettings.percentage / 100);
			let displayAmount; let displayFrequency;

			if (paymentInterval === 'quarterly') {
				displayAmount = monthlyContribution * 3; // 3 months worth
				displayFrequency = 'per quarter';
			} else if (paymentInterval === 'annually') {
				displayAmount = monthlyContribution * 12; // 12 months worth
				displayFrequency = 'per year';
			} else {
				displayAmount = monthlyContribution;
				displayFrequency = 'per month';
			}

			calculatedAmount = displayAmount;

			// Format currency
			const formattedAmount = `€${displayAmount.toFixed(2)}`;

			// Update display
			$('#calc-suggested-amount').text(formattedAmount);
			$('#calc-payment-frequency').text(` ${displayFrequency}`);
			$('#calc-result').show();
			$('#apply-calculated-amount').show();
		}

		// Bind calculator events
		$('#calc-monthly-income, #calc-payment-interval').on('input change', calculateContribution);

		// Apply calculated amount to main form
		$('#apply-calculated-amount').on('click', () => {
			if (calculatedAmount > 0) {
				this.applyCalculatedAmount(calculatedAmount, $('#calc-payment-interval').val());
			}
		});
	}

	applyCalculatedAmount(amount, paymentInterval) {
		console.log('Applying calculated amount:', amount, 'with interval:', paymentInterval);

		// Find the first applicable membership type based on payment interval
		const targetMembershipType = this.findMembershipTypeByInterval(paymentInterval);

		if (targetMembershipType) {
			// Select the matching membership type card
			const membershipCard = $(`.membership-type-card[data-type="${targetMembershipType.name}"]`);
			console.log('Found membership card:', membershipCard.length > 0, 'for type:', targetMembershipType.name);

			if (membershipCard.length) {
				// First select the membership type by clicking the standard select button
				const selectButton = membershipCard.find('.select-membership');
				if (selectButton.length) {
					selectButton.click();
					console.log('Clicked select button for membership type:', targetMembershipType.name);
				} else {
					// Fallback: click the card itself
					membershipCard.click();
					console.log('Clicked membership card for type:', targetMembershipType.name);
				}
			}

			// Wait a moment for the membership type selection to process
			setTimeout(() => {
				// Look for "Choose Amount" button (toggle-custom class) in the selected membership card
				const chooseAmountButton = membershipCard.find('.toggle-custom');
				console.log('Found choose amount button:', chooseAmountButton.length > 0);

				if (chooseAmountButton.length) {
					// Click the "Choose Amount" button to show custom amount section
					chooseAmountButton.click();
					console.log('Clicked choose amount button');

					// Wait for custom amount section to appear
					setTimeout(() => {
						// Set the calculated amount in the custom input
						const customInput = membershipCard.find('.custom-amount-input');
						console.log('Found custom input:', customInput.length > 0);

						if (customInput.length) {
							customInput.val(amount.toFixed(2)).trigger('input');
							console.log('Set custom amount:', amount.toFixed(2));

							// Trigger selection with the custom amount
							this.selectMembershipType(membershipCard, true, amount);
						}

						// Show confirmation message
						if (typeof frappe !== 'undefined' && frappe.show_alert) {
							frappe.show_alert({
								message: `Calculated amount (€${amount.toFixed(2)}) applied to ${targetMembershipType.name} membership`,
								indicator: 'green'
							});
						}

						// Scroll to the membership selection area
						$('html, body').animate({
							scrollTop: $('#membership-types').offset().top - 100
						}, 500);
					}, 300);
				} else {
					console.warn('Could not find choose amount button for membership type');
					// Fallback: try to set any custom amount input directly
					const customInput = membershipCard.find('.custom-amount-input');
					if (customInput.length) {
						customInput.val(amount.toFixed(2)).trigger('input');
						this.selectMembershipType(membershipCard, true, amount);
					}
				}
			}, 400);
		} else {
			console.warn('Could not find matching membership type for payment interval:', paymentInterval);

			// Fallback: Try to apply to first available membership type with custom amount support
			const firstCardWithCustom = $('.membership-type-card').filter((index, card) => {
				return $(card).find('.toggle-custom').length > 0;
			}).first();

			if (firstCardWithCustom.length) {
				console.log('Using fallback: first membership type with custom amount support');

				// Select the membership type first
				const selectButton = firstCardWithCustom.find('.select-membership');
				if (selectButton.length) {
					selectButton.click();
				}

				setTimeout(() => {
					const chooseAmountButton = firstCardWithCustom.find('.toggle-custom');
					if (chooseAmountButton.length) {
						chooseAmountButton.click();

						setTimeout(() => {
							const customInput = firstCardWithCustom.find('.custom-amount-input');
							if (customInput.length) {
								customInput.val(amount.toFixed(2)).trigger('input');
								this.selectMembershipType(firstCardWithCustom, true, amount);
							}
						}, 300);
					}
				}, 400);

				if (typeof frappe !== 'undefined' && frappe.show_alert) {
					frappe.show_alert({
						message: `Calculated amount (€${amount.toFixed(2)}) applied to available membership type`,
						indicator: 'green'
					});
				}
			} else {
				// Last resort fallback
				if (typeof frappe !== 'undefined' && frappe.show_alert) {
					frappe.show_alert({
						message: `Calculated amount (€${amount.toFixed(2)}) ready - please select a membership type and choose custom amount`,
						indicator: 'orange'
					});
				}
			}
		}
	}

	findMembershipTypeByInterval(paymentInterval) {
		console.log('Finding membership type for interval:', paymentInterval);

		// Get available membership types from state
		const membershipTypes = this.state.get('membershipTypes') || this.membershipTypes || [];
		console.log('Available membership types:', membershipTypes.length, membershipTypes);

		// Updated to use billing_period mapping
		const billingPeriodMapping = {
			monthly: 'Monthly',
			quarterly: 'Quarterly',
			annually: 'Annual'
		};

		// Uses billing_period instead of legacy subscription_period
		const targetPeriod = billingPeriodMapping[paymentInterval];
		if (targetPeriod) {
			for (const membershipType of membershipTypes) {
				// Updated to use billing_period
				const billingPeriod = membershipType.billing_period || membershipType.legacy_period;
				if (billingPeriod && billingPeriod.toLowerCase() === targetPeriod.toLowerCase()) {
					console.log('Found matching membership type by billing_period:', membershipType);
					return membershipType;
				}
			}
		}

		// Second try: Fallback to name/description matching for legacy support
		const intervalMatchers = {
			monthly: ['month', 'maand', 'monthly'],
			quarterly: ['quarter', 'kwartaal', 'quarterly', 'driemaandelijk'],
			annually: ['year', 'jaar', 'annual', 'yearly', 'jaarlijks']
		};

		const matchers = intervalMatchers[paymentInterval] || [];

		// Find first membership type that matches the interval in name or description
		for (const membershipType of membershipTypes) {
			const name = (membershipType.name || membershipType.membership_type_name || '').toLowerCase();
			const description = (membershipType.description || '').toLowerCase();

			for (const matcher of matchers) {
				if (name.includes(matcher) || description.includes(matcher)) {
					console.log('Found matching membership type by name/description:', membershipType);
					return membershipType;
				}
			}
		}

		// Third try: Smart fallback based on interval preference
		if (membershipTypes.length > 0) {
			// For annually, prefer the type with highest amount (typically annual)
			if (paymentInterval === 'annually') {
				const highestAmount = membershipTypes.reduce((prev, current) => {
					const prevAmount = parseFloat(prev.amount || 0);
					const currentAmount = parseFloat(current.amount || 0);
					return currentAmount > prevAmount ? current : prev;
				});
				console.log('Using highest amount membership type for annual:', highestAmount);
				return highestAmount;
			}

			// For monthly/quarterly, use first available
			console.log('Using first available membership type:', membershipTypes[0]);
			return membershipTypes[0];
		}

		console.warn('No membership types available');
		return null;
	}

	loadCountries(countries) {
		if (!countries || countries.length === 0) { return; }

		const select = $('#country');
		select.empty().append('<option value="">Select Country...</option>');

		countries.forEach(country => {
			select.append(`<option value="${country.name}">${country.name}</option>`);
		});

		select.val('Netherlands');
	}

	loadMembershipTypes(membershipTypes) {
		if (!membershipTypes || membershipTypes.length === 0) { return; }

		const container = $('#membership-types');
		container.empty();

		// Load detailed membership type information with custom amount support
		const loadPromises = membershipTypes.map(type => {
			return new Promise((resolve) => {
				if (this.apiService && typeof this.apiService.call === 'function') {
					this.apiService.call('verenigingen.api.membership_application.get_membership_type_details', { membership_type: type.name })
						.then(result => resolve(result || type))
						.catch(() => resolve(type)); // Fallback to basic type data
				} else {
					// Fallback - enhance basic type with custom amount support
					const baseAmount = parseFloat(type.amount) || 50; // fallback to 50 if amount is invalid
					const enhancedType = {
						...type,
						allow_custom_amount: true,
						minimum_amount: baseAmount * 0.5,
						maximum_amount: baseAmount * 5,
						suggested_amounts: [
							{ amount: baseAmount, label: 'Standard' },
							{ amount: baseAmount * 1.5, label: 'Supporter' },
							{ amount: baseAmount * 2, label: 'Patron' },
							{ amount: baseAmount * 3, label: 'Benefactor' }
						]
					};
					console.log('Enhanced type with suggested amounts:', enhancedType);
					resolve(enhancedType);
				}
			});
		});

		Promise.all(loadPromises).then(detailedTypes => {
			detailedTypes.forEach(type => {
				if (type.error) {
					console.error('Error loading membership type:', type.error);
					return;
				}

				const card = this.createMembershipCard(type);
				container.append(card);
			});

			this.bindMembershipEvents();
			console.log('Loaded', detailedTypes.length, 'membership types with custom amount support');
		});
	}

	loadPaymentMethods(paymentMethods) {
		if (!paymentMethods || paymentMethods.length === 0) {
			this.showPaymentMethodFallback();
			return;
		}

		const container = $('#payment-methods-list');
		container.empty();

		paymentMethods.forEach(method => {
			const card = this.createPaymentMethodCard(method);
			container.append(card);
		});

		this.bindPaymentEvents();

		// Also bind the payment method field switching events after DOM is updated
		console.log('Main app: Re-binding payment method events after loading methods');
		this.bindPaymentMethodEvents();

		// Auto-select first method to show appropriate fields
		if (paymentMethods.length > 0) {
			console.log('Main app: Auto-selecting first payment method:', paymentMethods[0].name);
			this.selectPaymentMethod(paymentMethods[0].name);
		}
	}

	updateApplicationSummary() {
		const summary = $('#application-summary');
		if (summary.length === 0) {
			console.warn('Application summary element not found');
			return;
		}

		const data = this.getAllFormData();

		let content = '<div class="row">';

		// Personal Information Column
		content += '<div class="col-md-6">';
		content += '<h6>Personal Information</h6>';
		content += `<p><strong>Name:</strong> ${data.first_name || ''} ${data.last_name || ''}</p>`;
		content += `<p><strong>Email:</strong> ${data.email || ''}</p>`;

		if (data.birth_date) {
			content += `<p><strong>Birth Date:</strong> ${data.birth_date}</p>`;
		}

		if (data.contact_number) {
			content += `<p><strong>Contact:</strong> ${data.contact_number}</p>`;
		}
		content += '</div>';

		// Address Information Column
		content += '<div class="col-md-6">';
		content += '<h6>Address</h6>';
		if (data.address_line1) {
			content += `<p><strong>Address:</strong> ${data.address_line1}</p>`;
			content += `<p>${data.city || ''} ${data.postal_code || ''}</p>`;
			content += `<p>${data.country || ''}</p>`;
		}
		content += '</div>';

		content += '</div>';

		// Membership Information Row
		content += '<div class="row mt-3">';
		content += '<div class="col-md-6">';
		content += '<h6>Membership</h6>';

		if (data.selected_membership_type) {
			const membershipType = this.membershipTypes && this.membershipTypes.find(t => t.name === data.selected_membership_type);

			if (membershipType) {
				const typeName = membershipType.membership_type_name || membershipType.name;
				content += `<p><strong>Type:</strong> ${typeName}</p>`;

				// Format amount with billing period
				const amount = data.custom_contribution_fee || membershipType.amount;
				const period = membershipType.billing_period || 'year';
				// Use simple currency formatting to avoid HTML structure issues
				const currency = membershipType.currency || 'EUR';
				const formattedAmount = `${currency} ${parseFloat(amount).toFixed(2)}`;
				const periodText = period.toLowerCase() === 'quarterly' ? 'Quarterly' : `per ${period}`;
				content += `<p><strong>Amount:</strong> ${formattedAmount} ${periodText}</p>`;

				if (data.uses_custom_amount) {
					content += '<p><em>Custom contribution amount</em></p>';
				}
			} else {
				content += `<p><strong>Type:</strong> ${data.selected_membership_type}</p>`;
				if (data.custom_contribution_fee) {
					const formattedAmount = `EUR ${parseFloat(data.custom_contribution_fee).toFixed(2)}`;
					content += `<p><strong>Amount:</strong> ${formattedAmount}</p>`;
				}
			}
		} else {
			content += '<p><em>No membership type selected</em></p>';
		}

		if (data.selected_chapter) {
			content += `<p><strong>Chapter:</strong> ${data.selected_chapter}</p>`;
		}
		content += '</div>';

		// Volunteer and Payment Information Column
		content += '<div class="col-md-6">';
		content += '<h6>Additional Information</h6>';

		if (data.interested_in_volunteering) {
			content += '<p><strong>Volunteering:</strong> Yes</p>';
			if (data.volunteer_availability) {
				content += `<p><strong>Availability:</strong> ${data.volunteer_availability}</p>`;
			}
		}

		if (data.payment_method) {
			content += `<p><strong>Payment Method:</strong> ${data.payment_method}</p>`;

			// Show bank details for SEPA Direct Debit
			if (data.payment_method === 'SEPA Direct Debit') {
				if (data.iban) {
					content += `<p><strong>IBAN:</strong> ${data.iban}</p>`;
				}
				if (data.bank_account_name) {
					content += `<p><strong>Account Holder:</strong> ${data.bank_account_name}</p>`;
				}
			}

			// Show bank transfer account details for Bank Transfer
			if (data.payment_method === 'Bank Transfer') {
				if (data.transfer_iban) {
					content += `<p><strong>Transfer Account (IBAN):</strong> ${data.transfer_iban}</p>`;
				}
				if (data.transfer_account_name) {
					content += `<p><strong>Account Holder:</strong> ${data.transfer_account_name}</p>`;
				}
				if (!data.transfer_iban && !data.transfer_account_name) {
					content += '<p><em>Account details will be provided via email</em></p>';
				}
			}
		} else {
			content += '<p><em>No payment method selected</em></p>';
		}

		content += '</div>';
		content += '</div>';

		summary.html(content);
	}

	bindPaymentMethodEvents() {
		console.log('Main app: Binding payment method events');

		// Bind events for payment method selection to show/hide appropriate form sections
		// Use a more robust selector to catch all payment method radio buttons
		const self = this;
		$(document).off('change', 'input[name="payment_method_selection"], .payment-method-radio').on('change', 'input[name="payment_method_selection"], .payment-method-radio', function () {
			const selectedMethod = $(this).val();
			console.log('Main app: Payment method selection changed to:', selectedMethod);

			// Use the new handlePaymentMethodChange method for consistent behavior
			self.handlePaymentMethodChange(selectedMethod);
		});

		// Format card number input
		$('#card_number').off('input').on('input', function () {
			const value = $(this).val().replace(/\s+/g, '').replace(/[^0-9]/gi, '');
			const formattedValue = value.match(/.{1,4}/g)?.join(' ') || value;
			$(this).val(formattedValue);
		});

		// Format IBAN inputs (for both direct debit and bank transfer)
		$('#iban, #transfer_iban').off('input').on('input', function () {
			const value = $(this).val().replace(/\s+/g, '').toUpperCase();
			const formattedValue = value.match(/.{1,4}/g)?.join(' ') || value;
			$(this).val(formattedValue);
		});
	}

	updateConfirmationDisplay() {
		console.log('Updating confirmation display');
		const data = this.getAllFormData();
		console.log('Form data for confirmation:', data);

		// Personal Information
		const fullName = `${data.first_name || ''} ${data.middle_name ? `${data.middle_name} ` : ''}${data.last_name || ''}`.trim();
		$('#confirm-name').text(fullName || 'Not provided');
		$('#confirm-email').text(data.email || 'Not provided');
		$('#confirm-phone').text(data.mobile_no || 'Not provided');

		// Address Information
		const address = `${data.address_line1 || ''}, ${data.city || ''}, ${data.postal_code || ''}`.replace(/^,\s*|,\s*$/g, '');
		$('#confirm-address').text(address || 'Not provided');
		$('#confirm-city').text(`${data.city || ''}, ${data.postal_code || ''}`.replace(/^,\s*|,\s*$/g, '') || 'Not provided');
		$('#confirm-country').text(data.country || 'Not provided');

		// Membership Information
		const membershipType = this.state.get('selected_membership_type') || 'Not selected';
		const membershipAmount = this.state.get('custom_contribution_fee') || 0;
		$('#confirm-membership-type').text(membershipType);
		$('#confirm-membership-fee').text(membershipAmount ? `€${membershipAmount}` : 'Not set');

		// Payment Information
		const paymentMethod = $('input[name="payment_method"]:checked').val() || 'Not selected';
		$('#confirm-payment-method').text(paymentMethod.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase()));

		// Bank Details for bank transfer or SEPA direct debit
		if (paymentMethod === 'bank_transfer' || paymentMethod === 'sepa_direct_debit') {
			const iban = data.iban || '';
			// Use bank_account_name since that's what gets stored in the database
			const accountHolder = data.bank_account_name || '';

			if (iban || accountHolder) {
				let bankInfo = '';
				if (iban) {
					// Validate IBAN when showing in confirmation
					const validation = this.performIBANValidation(iban);
					if (validation.valid) {
						// Show formatted IBAN with bank info
						const bankName = this.getBankNameFromIBAN(iban);
						bankInfo += `IBAN: ${validation.formatted}`;
						if (bankName) {
							bankInfo += ` (${bankName})`;
						}

						// Also show BIC if derivable
						const bic = this.deriveBICFromIBAN(iban);
						if (bic) {
							bankInfo += `<br>BIC: ${bic}`;
						}
					} else {
						// Show IBAN with error indication
						bankInfo += `<span class="text-danger">IBAN: ${iban} - ${validation.error}</span>`;
						// Optionally, you could prevent form submission here
						if (typeof frappe !== 'undefined' && frappe.msgprint) {
							frappe.msgprint({
								title: 'Invalid IBAN',
								message: `The IBAN you entered is invalid: ${validation.error}. Please go back to the payment step to correct it.`,
								indicator: 'red'
							});
						}
					}
				}
				if (accountHolder) {
					if (bankInfo) { bankInfo += '<br>'; }
					bankInfo += `Account Holder: ${accountHolder}`;
				}
				$('#confirm-bank-info').html(bankInfo);
				$('#confirm-bank-details').show();
			} else {
				$('#confirm-bank-details').hide();
			}
		} else {
			$('#confirm-bank-details').hide();
		}

		// Volunteering Information
		const volunteering = $('#interested_in_volunteering').is(':checked') ? 'Yes, interested in volunteering' : 'Not interested in volunteering';
		$('#confirm-volunteering').text(volunteering);
	}

	updateFinalApplicationSummary() {
		// Legacy function - now redirects to new confirmation display
		this.updateConfirmationDisplay();
	}

	// Legacy method implementations for compatibility
	createMembershipCard(type) {
		// Ensure we have a valid amount
		const amount = type.amount || 0;
		const membershipTypeName = type.membership_type_name || type.name || 'Unknown';
		const billingPeriod = type.billing_period || 'year';

		console.log('Creating membership card for:', { name: type.name, amount, type });

		let cardHTML = `<div class="membership-type-card" data-type="${type.name || ''}" data-amount="${amount}">`;
		cardHTML += `<h5>${membershipTypeName}</h5>`;
		cardHTML += '<div class="membership-price">';
		cardHTML += `${frappe.format(amount, { fieldtype: 'Currency' })} / ${billingPeriod}`;
		cardHTML += '</div>';
		cardHTML += `<p class="membership-description">${type.description || ''}</p>`;

		// Add custom amount section if allowed
		if (type.allow_custom_amount) {
			cardHTML += '<div class="custom-amount-section" style="display: none;">';
			cardHTML += '<label>Choose Your Contribution:</label>';
			cardHTML += '<div class="amount-suggestion-pills">';

			if (type.suggested_amounts && type.suggested_amounts.length > 0) {
				type.suggested_amounts.forEach((suggestion) => {
					const suggestionAmount = parseFloat(suggestion.amount) || 0;
					console.log('Creating amount pill:', { label: suggestion.label, amount: suggestionAmount });
					cardHTML += `<span class="amount-pill" data-amount="${suggestionAmount}">`;
					cardHTML += frappe.format(suggestionAmount, { fieldtype: 'Currency' });
					cardHTML += `<br><small>${suggestion.label}</small>`;
					cardHTML += '</span>';
				});
			}

			cardHTML += '</div>';
			cardHTML += '<div class="mt-3">';
			cardHTML += '<label>Or enter custom amount:</label>';
			const minAmount = type.minimum_amount || amount;
			cardHTML += '<input type="number" class="form-control custom-amount-input" ';
			cardHTML += `min="${minAmount}" step="0.01" placeholder="Enter amount">`;
			cardHTML += `<small class="text-muted">Minimum: ${frappe.format(minAmount, { fieldtype: 'Currency' })}</small>`;
			cardHTML += '</div>';
			cardHTML += '</div>';
		}

		cardHTML += '<div class="btn-group mt-3">';
		cardHTML += '<button type="button" class="btn btn-primary select-membership">';
		cardHTML += `Select${type.allow_custom_amount ? ' Standard' : ''}`;
		cardHTML += '</button>';

		if (type.allow_custom_amount) {
			cardHTML += '<button type="button" class="btn btn-outline-secondary toggle-custom">';
			cardHTML += 'Choose Amount';
			cardHTML += '</button>';
		}
		cardHTML += '</div>';

		if (type.allow_custom_amount && type.custom_amount_note) {
			cardHTML += '<div class="mt-2">';
			cardHTML += `<small class="text-muted">${type.custom_amount_note}</small>`;
			cardHTML += '</div>';
		}

		cardHTML += '</div>';

		return $(cardHTML);
	}

	createPaymentMethodCard(method) {
		let methodCardHTML = `<div class="payment-method-option" data-method="${method.name}">`;
		methodCardHTML += '<div class="d-flex align-items-center">';
		methodCardHTML += '<div class="payment-method-icon">';
		methodCardHTML += `<i class="fa ${method.icon || 'fa-university'}"></i>`;
		methodCardHTML += '</div>';
		methodCardHTML += '<div class="payment-method-info flex-grow-1">';
		methodCardHTML += `<h6>${method.name}</h6>`;
		methodCardHTML += '<div class="text-muted">';
		methodCardHTML += `${method.description}<br>`;
		methodCardHTML += `<small><strong>Processing:</strong> ${method.processing_time}</small>`;

		if (method.requires_mandate) {
			methodCardHTML += `<br><small class="text-warning"><strong>Note:</strong> ${method.note}</small>`;
		}

		methodCardHTML += '</div>';
		methodCardHTML += '</div>';
		methodCardHTML += '<div class="payment-method-selector">';
		methodCardHTML += '<div class="form-check">';

		const radioId = `payment_${method.name.replace(/\s+/g, '_').toLowerCase()}`;
		methodCardHTML += '<input class="form-check-input payment-method-radio" type="radio" ';
		methodCardHTML += `name="payment_method_selection" value="${method.name}" id="${radioId}">`;
		methodCardHTML += `<label class="form-check-label" for="${radioId}">`;
		methodCardHTML += 'Select';
		methodCardHTML += '</label>';
		methodCardHTML += '</div>';
		methodCardHTML += '</div>';
		methodCardHTML += '</div>';
		methodCardHTML += '</div>';

		return $(methodCardHTML);
	}

	bindMembershipEvents() {
		console.log('Binding membership type events - START');
		console.trace('bindMembershipEvents called from:');

		// Standard selection
		$('.select-membership').off('click').on('click', (e) => {
			const card = $(e.target).closest('.membership-type-card');
			this.selectMembershipType(card, false);
		});

		// Toggle custom amount section
		$('.toggle-custom').off('click').on('click', (e) => {
			const card = $(e.target).closest('.membership-type-card');
			const customSection = card.find('.custom-amount-section');
			const button = $(e.target);

			if (customSection.is(':visible')) {
				customSection.hide();
				button.text('Choose Amount');
				card.find('.custom-amount-input').val('');
				card.find('.amount-pill').removeClass('selected');
				this.selectMembershipType(card, false);
			} else {
				$('.custom-amount-section').hide();
				$('.toggle-custom').text('Choose Amount');

				customSection.show();
				button.text('Standard Amount');

				const standardAmount = parseFloat(card.data('amount'));
				if (!isNaN(standardAmount) && standardAmount > 0) {
					card.find(`.amount-pill[data-amount="${standardAmount}"]`).addClass('selected');
					card.find('.custom-amount-input').val(standardAmount);
					this.selectMembershipType(card, true, standardAmount);
				}
			}
		});

		// Amount pill selection
		$(document).off('click', '.amount-pill').on('click', '.amount-pill', (e) => {
			e.preventDefault();
			e.stopPropagation();

			console.log('Amount pill clicked');
			const pill = $(e.target).closest('.amount-pill'); // Use closest to handle clicks on nested elements
			const card = pill.closest('.membership-type-card');
			const rawAmount = pill.data('amount');
			const amount = parseFloat(rawAmount);

			console.log('Pill selection details:', {
				pillText: pill.text().trim(),
				rawAmount,
				parsedAmount: amount,
				isValid: !isNaN(amount),
				cardType: card.data('type'),
				pillHtml: pill[0].outerHTML
			});

			if (isNaN(amount) || amount <= 0) {
				console.error('Invalid amount from pill:', rawAmount, 'pill:', pill[0]);
				return;
			}

			card.find('.amount-pill').removeClass('selected');
			pill.addClass('selected');

			// Set input value with the valid amount
			card.find('.custom-amount-input').val(amount);

			this.selectMembershipType(card, true, amount);
		});

		// Custom amount input
		$('.custom-amount-input').off('input blur').on('input blur', (e) => {
			const input = $(e.target);
			const card = input.closest('.membership-type-card');
			const amount = parseFloat(input.val());
			const minAmount = parseFloat(input.attr('min'));

			card.find('.amount-pill').removeClass('selected');

			if (isNaN(amount) || amount <= 0) {
				input.addClass('is-invalid');
				input.siblings('.invalid-feedback').remove();
				input.after('<div class="invalid-feedback">Please enter a valid amount</div>');
				return;
			}

			if (amount < minAmount) {
				input.addClass('is-invalid');
				input.siblings('.invalid-feedback').remove();
				input.after(`<div class="invalid-feedback">Amount must be at least ${frappe.format(minAmount, { fieldtype: 'Currency' })}</div>`);
				return;
			}

			input.removeClass('is-invalid').addClass('is-valid');
			input.siblings('.invalid-feedback').remove();

			this.selectMembershipType(card, true, amount);
		});
	}

	selectMembershipType(card, isCustom = false, customAmount = null) {
		const membershipType = card.data('type');
		const cardAmount = card.data('amount');

		console.log('selectMembershipType called with:', {
			membershipType,
			cardAmount,
			isCustom,
			customAmount
		});

		// Handle null/undefined amounts
		if (!cardAmount && cardAmount !== 0) {
			console.error('Card amount is null/undefined for type:', membershipType);
			return;
		}

		const standardAmount = parseFloat(cardAmount);
		if (isNaN(standardAmount)) {
			console.error('Invalid standard amount for type:', membershipType, 'amount:', cardAmount);
			return;
		}

		let finalAmount = standardAmount;
		let usesCustomAmount = false;

		if (isCustom && customAmount !== null && customAmount !== undefined) {
			const parsedCustomAmount = parseFloat(customAmount);
			if (!isNaN(parsedCustomAmount) && parsedCustomAmount > 0) {
				finalAmount = parsedCustomAmount;
				usesCustomAmount = finalAmount !== standardAmount;
			} else {
				console.error('Invalid custom amount:', customAmount, 'parsed:', parsedCustomAmount);
				console.error('Falling back to standard amount:', standardAmount);
				// Fall back to standard amount instead of returning early
				finalAmount = standardAmount;
				usesCustomAmount = false;
			}
		}

		console.log('Selecting membership type:', { membershipType, finalAmount, usesCustomAmount });

		$('.membership-type-card').removeClass('selected');
		card.addClass('selected');

		// Update state - both new and legacy formats
		this.state.set('membership', {
			type: membershipType,
			amount: finalAmount,
			isCustom: usesCustomAmount
		});

		// Legacy compatibility
		this.state.set('selected_membership_type', membershipType);
		this.state.set('custom_contribution_fee', finalAmount);
		this.state.set('uses_custom_amount', usesCustomAmount);

		$('#membership-type-error').hide();

		// Update membership fee display
		this.updateMembershipFeeDisplay(membershipType, finalAmount, usesCustomAmount);

		if (usesCustomAmount) {
			this.validateCustomAmount(membershipType, finalAmount);
		}
	}

	updateMembershipFeeDisplay(membershipType, amount, isCustom) {
		const feeDisplay = $('#membership-fee-display');
		const feeDetails = $('#fee-details');

		if (!membershipType || !amount) {
			feeDisplay.hide();
			return;
		}

		// Find the membership type details
		const membershipTypeDetails = this.membershipTypes && this.membershipTypes.find(t => t.name === membershipType);
		const membershipTypeName = membershipTypeDetails
			? (membershipTypeDetails.membership_type_name || membershipTypeDetails.name)
			: membershipType;

		const billingPeriod = membershipTypeDetails
			? (membershipTypeDetails.billing_period || 'year')
			: 'year';

		const periodText = billingPeriod.toLowerCase() === 'quarterly' ? 'Quarterly' : `per ${billingPeriod}`;

		// Format the amount
		const formattedAmount = `EUR ${parseFloat(amount).toFixed(2)}`;

		// Build the display content
		let content = `<p><strong>Type:</strong> ${membershipTypeName}</p>`;
		content += `<p><strong>Amount:</strong> ${formattedAmount} ${periodText}`;

		if (isCustom) {
			content += ' <span class="badge badge-secondary">Custom Amount</span>';
		}

		content += '</p>';

		if (membershipTypeDetails && membershipTypeDetails.description) {
			content += `<p><strong>Description:</strong> ${membershipTypeDetails.description}</p>`;
		}

		feeDetails.html(content);
		feeDisplay.show();

		console.log('Updated membership fee display:', { membershipType, amount, isCustom });
	}

	async validateCustomAmount(membershipType, amount) {
		try {
			const result = await this.apiService.validateCustomAmount(membershipType, amount);
			if (result && !result.valid) {
				$('#membership-type-error').show().text(result.message);
			} else {
				$('#membership-type-error').hide();
			}
		} catch (error) {
			console.error('Custom amount validation error:', error);
		}
	}

	bindPaymentEvents() {
		$('.payment-method-option').off('click').on('click', (e) => {
			const methodName = $(e.target).closest('.payment-method-option').data('method');
			this.selectPaymentMethod(methodName);
		});

		$('.payment-method-radio').off('change').on('change', (e) => {
			if ($(e.target).is(':checked')) {
				this.selectPaymentMethod($(e.target).val());
			}
		});
	}

	selectPaymentMethod(methodName) {
		if (!methodName) { return; }

		console.log('Selecting payment method:', methodName);

		// Update state
		this.setPaymentMethod(methodName);

		// Update UI
		if ($('#payment-method-fallback').is(':visible')) {
			$('#payment_method').val(methodName);
		} else {
			$('.payment-method-option').removeClass('selected');
			$(`.payment-method-option[data-method="${methodName}"]`).addClass('selected');

			// Update radio button and trigger change event for field switching
			const radioButton = $(`.payment-method-radio[value="${methodName}"]`);
			console.log('Main app: Found radio button for', methodName, ':', radioButton.length);
			radioButton.prop('checked', true).trigger('change');
		}

		// Apply the working pattern from member doctype for dynamic field switching
		this.handlePaymentMethodChange(methodName);

		// Show/hide SEPA notice
		if (methodName === 'SEPA Direct Debit') {
			$('#sepa-mandate-notice').show();
		} else {
			$('#sepa-mandate-notice').hide();
		}
	}

	// Implement payment method field switching similar to member doctype UIUtils.handle_payment_method_change
	handlePaymentMethodChange(methodName) {
		const is_direct_debit = methodName === 'SEPA Direct Debit';
		const is_bank_transfer = methodName === 'Bank Transfer';
		const _show_bank_details = ['SEPA Direct Debit', 'Bank Transfer'].includes(methodName);

		console.log('Main app: Handling payment method change to:', methodName);
		console.log('Main app: is_direct_debit:', is_direct_debit, 'is_bank_transfer:', is_bank_transfer);

		// Hide all payment detail sections first
		$('#bank-account-details').hide();
		$('#bank-transfer-notice').hide();
		$('#bank-transfer-details').hide();

		// Show appropriate section based on payment method
		if (is_direct_debit) {
			console.log('Main app: Showing bank account details for SEPA Direct Debit');
			$('#bank-account-details').show();

			// Set required attributes for bank account fields
			$('#iban, #bank_account_name, #account_holder_name').prop('required', true);
		} else if (is_bank_transfer) {
			console.log('Main app: Showing bank transfer details with account fields');
			$('#bank-transfer-details').show();

			// Bank transfer fields are optional (for payment matching purposes)
			$('#iban, #bank_account_name, #account_holder_name').prop('required', false);
			$('#transfer_iban, #transfer_account_name').prop('required', false);
		}

		// Clear validation errors when switching payment methods
		$('#bank-account-details input, #bank-transfer-details input').removeClass('is-invalid is-valid');
		$('.invalid-feedback').hide();
	}

	showPaymentMethodFallback() {
		const container = $('#payment-methods-list');
		const fallback = $('#payment-method-fallback');

		container.hide();
		fallback.show();

		const select = $('#payment_method');
		select.empty();

		const fallbackMethods = [
			{
				name: 'Bank Transfer',
				description: 'One-time bank transfer',
				icon: 'fa-university',
				processing_time: '1-3 business days',
				requires_mandate: false
			},
			{
				name: 'SEPA Direct Debit',
				description: 'SEPA Direct Debit (recurring)',
				icon: 'fa-repeat',
				processing_time: '5-7 days first collection',
				requires_mandate: true
			}
		];

		fallbackMethods.forEach(method => {
			select.append(`<option value="${method.name}">${method.name} - ${method.description}</option>`);
		});

		// Bind change event
		select.off('change').on('change', (e) => {
			const selectedMethod = $(e.target).val();
			if (selectedMethod) {
				this.selectPaymentMethod(selectedMethod);
			}
		});

		// Auto-select first option
		if (fallbackMethods.length > 0) {
			const defaultMethod = fallbackMethods[0].name;
			select.val(defaultMethod);
			this.selectPaymentMethod(defaultMethod);
		}
	}
}


// ===================================
// 2. STATE MANAGEMENT (LEGACY COMPATIBILITY)
// ===================================

class ApplicationState {
	constructor() {
		this.data = {
			currentStep: 1,
			personalInfo: {},
			address: {},
			membership: {},
			volunteer: {},
			payment: {},
			// Legacy compatibility
			selected_membership_type: '',
			custom_contribution_fee: 0,
			uses_custom_amount: false
		};

		this.listeners = [];
	}

	subscribe(listener) {
		this.listeners.push(listener);
	}

	notify(change) {
		this.listeners.forEach(listener => {
			try {
				listener(change);
			} catch (error) {
				console.error('State listener error:', error);
			}
		});
	}

	set(key, value) {
		const oldValue = this.data[key];
		this.data[key] = value;
		this.notify({ key, oldValue, newValue: value });
	}

	get(key) {
		return this.data[key];
	}

	getData() {
		return { ...this.data };
	}

	setInitialData(data) {
		this.data.membershipTypes = data.membership_types || [];
		this.data.countries = data.countries || [];
		this.data.chapters = data.chapters || [];
		this.data.volunteerAreas = data.volunteer_areas || [];
		this.data.paymentMethods = data.payment_methods || [];
	}

	get currentStep() {
		return this.data.currentStep;
	}

	incrementStep() {
		if (this.data.currentStep < 5) {
			this.set('currentStep', this.data.currentStep + 1);
		}
	}

	decrementStep() {
		if (this.data.currentStep > 1) {
			this.set('currentStep', this.data.currentStep - 1);
		}
	}
}

// ===================================
// 3. UTILITY CLASSES FOR COMPATIBILITY
// ===================================

// FormValidator already defined at the top of the file

class PersonalInfoStep extends BaseStep {
	constructor() {
		super('personal-info');
	}

	render(state) {
		// Ensure age warning element exists only if birth_date field exists
		const birthDateField = $('#birth_date');
		if (birthDateField.length > 0 && $('#age-warning').length === 0) {
			birthDateField.after('<div id="age-warning" class="alert mt-2" style="display: none;"></div>');
		}
	}

	bindEvents() {
		// Use delegated event handlers to avoid null reference errors
		$(document).off('blur', '#email').on('blur', '#email', () => this.validateEmail());
		$(document).off('change blur', '#birth_date').on('change blur', '#birth_date', () => this.validateAge());
	}

	async validateEmail() {
		const emailField = $('#email');
		if (emailField.length === 0) {
			console.warn('Email field not found');
			return true;
		}

		const email = emailField.val();
		if (!email) { return true; }

		try {
			// Check if membershipApp and its API are available
			if (typeof membershipApp === 'undefined' || !membershipApp.apiService) {
				console.warn('MembershipApp API not available, skipping email validation');
				return true;
			}

			const result = await membershipApp.apiService.validateEmail(email);

			if (!result.valid) {
				if (this.validator) {
					this.validator.showError('#email', result.message);
				}
				return false;
			}

			if (this.validator) {
				this.validator.showSuccess('#email');
			}
			return true;
		} catch (error) {
			console.error('Email validation error:', error);
			return true; // Don't block on API errors
		}
	}

	validateAge() {
		const birthDateField = $('#birth_date');
		if (birthDateField.length === 0) {
			console.warn('Birth date field not found');
			return true;
		}

		const birthDate = birthDateField.val();
		if (!birthDate) { return true; }

		const age = this.calculateAge(birthDate);
		let warningDiv = $('#age-warning');

		// Create warning div if it doesn't exist
		if (warningDiv.length === 0) {
			birthDateField.after('<div id="age-warning" class="alert mt-2" style="display: none;"></div>');
			warningDiv = $('#age-warning');
		}

		// Clear previous states
		birthDateField.removeClass('is-invalid is-valid');
		birthDateField.siblings('.invalid-feedback').remove();
		warningDiv.hide().removeClass('alert-info alert-warning alert-danger');

		if (age < 0) {
			if (this.validator) {
				this.validator.showError('#birth_date', 'Birth date cannot be in the future');
			}
			return false;
		}

		birthDateField.addClass('is-valid');

		// Show warnings for edge cases
		if (age < 12) {
			warningDiv
				.addClass('alert-info')
				.html('<i class="fa fa-info-circle"></i> Applicants under 12 may require parental consent')
				.show();
		} else if (age > 100) {
			warningDiv
				.addClass('alert-warning')
				.html(`<i class="fa fa-exclamation-triangle"></i> Please verify birth date - applicant would be ${age} years old`)
				.show();
		}

		return true;
	}

	calculateAge(birthDate) {
		if (!birthDate) { return 0; }

		try {
			const birth = new Date(birthDate);
			const today = new Date();

			// Check for invalid dates
			if (isNaN(birth.getTime())) {
				console.warn('Invalid birth date:', birthDate);
				return -1;
			}

			if (birth > today) {
				return -1; // Future date
			}

			let age = today.getFullYear() - birth.getFullYear();

			// Adjust for birthday not yet reached this year
			if (today.getMonth() < birth.getMonth()
                || (today.getMonth() === birth.getMonth() && today.getDate() < birth.getDate())) {
				age--;
			}

			return Math.max(0, age); // Ensure non-negative age
		} catch (error) {
			console.error('Error calculating age:', error);
			return 0;
		}
	}

	async validate() {
		const fields = ['first_name', 'last_name', 'email', 'birth_date'];
		let valid = true;

		for (const field of fields) {
			if (!this.validator.validateRequired(`#${field}`)) {
				valid = false;
			}
		}

		if ($('#email').val() && !await this.validateEmail()) {
			valid = false;
		}

		if ($('#birth_date').val() && !this.validateAge()) {
			valid = false;
		}

		return valid;
	}

	getData() {
		return {
			first_name: $('#first_name').val() || '',
			middle_name: $('#middle_name').val() || '',
			last_name: $('#last_name').val() || '',
			email: $('#email').val() || '',
			mobile_no: $('#mobile_no').val() || '',
			phone: $('#phone').val() || '',
			birth_date: $('#birth_date').val() || '',
			pronouns: $('#pronouns').val() || ''
		};
	}
}

class AddressStep extends BaseStep {
	constructor() {
		super('address');
	}

	render(state) {
		// Load countries into dropdown
		if (state.get('countries')) {
			this.loadCountries(state.get('countries'));
		}
	}

	loadCountries(countries) {
		const select = $('#country');

		// Only populate if empty (avoid duplicate loading)
		if (select.children().length <= 1) {
			select.empty().append('<option value="">Select Country...</option>');

			countries.forEach(country => {
				select.append(`<option value="${country.name}">${country.name}</option>`);
			});

			// Set Netherlands as default
			select.val('Netherlands');
		}
	}

	bindEvents() {
		$('#postal_code').off('blur').on('blur', () => this.suggestChapter());
	}

	async suggestChapter() {
		const postalCode = $('#postal_code').val();
		const country = $('#country').val() || 'Netherlands';

		if (!postalCode) { return; }

		try {
			if (typeof membershipApp === 'undefined' || !membershipApp.apiService) {
				console.warn('MembershipApp API not available, skipping postal code validation');
				return;
			}

			const result = await membershipApp.apiService.validatePostalCode(postalCode, country);

			if (result.suggested_chapters && result.suggested_chapters.length > 0) {
				const suggestion = result.suggested_chapters[0];
				$('#suggested-chapter-name').text(suggestion.name);
				$('#suggested-chapter').show();

				$('#accept-suggestion').off('click').on('click', () => {
					$('#selected_chapter').val(suggestion.name);
					$('#suggested-chapter').hide();
				});
			} else {
				$('#suggested-chapter').hide();
			}
		} catch (error) {
			console.error('Chapter suggestion error:', error);
		}
	}

	async validate() {
		const fields = ['address_line1', 'city', 'postal_code', 'country'];
		let valid = true;

		for (const field of fields) {
			if (!this.validator.validateRequired(`#${field}`)) {
				valid = false;
			}
		}

		return valid;
	}

	getData() {
		return {
			address_line1: $('#address_line1').val() || '',
			address_line2: $('#address_line2').val() || '',
			city: $('#city').val() || '',
			state: $('#state').val() || '',
			postal_code: $('#postal_code').val() || '',
			country: $('#country').val() || '',
			selected_chapter: $('#selected_chapter').val() || ''
		};
	}
}

class MembershipStep extends BaseStep {
	constructor() {
		super('membership');
	}

	render(state) {
		if (state.get('membershipTypes')) {
			this.renderMembershipTypes(state.get('membershipTypes'));
		}
	}

	renderMembershipTypes(membershipTypes) {
		const container = $('#membership-types');
		container.empty();

		// Get detailed information for each membership type
		const loadPromises = membershipTypes.map(type => {
			return new Promise((resolve) => {
				frappe.call({
					method: 'verenigingen.api.membership_application.get_membership_type_details',
					args: { membership_type: type.name },
					callback(r) {
						resolve(r.message || type);
					},
					error() {
						resolve(type); // Fallback to basic type data
					}
				});
			});
		});

		Promise.all(loadPromises).then(detailedTypes => {
			detailedTypes.forEach(type => {
				if (type.error) {
					console.error('Error loading membership type:', type.error);
					return;
				}

				const card = this.createMembershipCard(type);
				container.append(card);
			});

			this.bindMembershipEvents();
		});
	}
}

class VolunteerStep extends BaseStep {
	constructor() {
		super('volunteer');
	}

	render(state) {
		if (state.get('volunteerAreas')) {
			this.renderVolunteerAreas(state.get('volunteerAreas'));
		}

		// Load chapters into dropdown
		if (state.get('chapters')) {
			this.loadChapters(state.get('chapters'));
		}
	}

	loadChapters(chapters) {
		const select = $('#selected_chapter');

		// Only populate if empty (avoid duplicate loading)
		if (select.children().length <= 1) {
			select.empty().append('<option value="">Select a chapter...</option>');

			chapters.forEach(chapter => {
				const displayText = chapter.region ? `${chapter.name} - ${chapter.region}` : chapter.name;
				select.append(`<option value="${chapter.name}">${displayText}</option>`);
			});

			// Show chapter selection section if chapters are available
			if (chapters.length > 0) {
				$('#chapter-selection').show();
			}
		}
	}

	renderVolunteerAreas(areas) {
		const container = $('#volunteer-interests');
		container.empty();

		areas.forEach(area => {
			const checkboxId = `interest_${area.name.replace(/\s+/g, '_')}`;
			let checkboxHTML = '<div class="form-check">';
			checkboxHTML += '<input class="form-check-input" type="checkbox" ';
			checkboxHTML += `value="${area.name}" id="${checkboxId}">`;
			checkboxHTML += `<label class="form-check-label" for="${checkboxId}">`;
			checkboxHTML += area.name;

			if (area.description) {
				checkboxHTML += `<small class="text-muted d-block">${area.description}</small>`;
			}

			checkboxHTML += '</label>';
			checkboxHTML += '</div>';

			container.append($(checkboxHTML));
		});
	}

	bindEvents() {
		$('#interested_in_volunteering').off('change').on('change', function () {
			$('#volunteer-details').toggle($(this).is(':checked'));
		});

		$('#application_source').off('change').on('change', function () {
			$('#source-details-container').toggle($(this).val() === 'Other');
		});
	}

	async validate() {
		// Volunteer step is mostly optional, just return true
		return true;
	}

	getData() {
		const interests = [];
		$('#volunteer-interests input[type="checkbox"]:checked').each(function () {
			interests.push($(this).val());
		});

		return {
			interested_in_volunteering: $('#interested_in_volunteering').is(':checked'),
			volunteer_availability: $('#volunteer_availability').val() || '',
			volunteer_experience_level: $('#volunteer_experience_level').val() || '',
			volunteer_interests: interests,
			newsletter_opt_in: $('#newsletter_opt_in').is(':checked'),
			application_source: $('#application_source').val() || '',
			application_source_details: $('#application_source_details').val() || ''
		};
	}
}

class PaymentStep extends BaseStep {
	constructor() {
		super('payment');
	}

	render(state) {
		if (state.get('paymentMethods')) {
			this.renderPaymentMethods(state.get('paymentMethods'));
		}
		this.updateSummary(state);
	}

	renderPaymentMethods(paymentMethods) {
		const container = $('#payment-methods-list');
		const fallback = $('#payment-method-fallback');

		if (!paymentMethods || paymentMethods.length === 0) {
			this.showPaymentMethodFallback();
			return;
		}

		container.empty().show();
		fallback.hide();

		paymentMethods.forEach(method => {
			const methodCard = this.createPaymentMethodCard(method);
			container.append(methodCard);
		});

		this.bindPaymentEvents();

		// Also ensure main app payment method events are bound after DOM update
		if (typeof membershipApp !== 'undefined' && membershipApp.bindPaymentMethodEvents) {
			console.log('PaymentStep: Re-binding main app payment method events after loading methods');
			membershipApp.bindPaymentMethodEvents();
		}

		// Auto-select first method
		if (paymentMethods.length > 0) {
			this.selectPaymentMethod(paymentMethods[0].name);
		}
	}

	createPaymentMethodCard(method) {
		let methodCardHTML = `<div class="payment-method-option" data-method="${method.name}">`;
		methodCardHTML += '<div class="d-flex align-items-center">';
		methodCardHTML += '<div class="payment-method-icon">';
		methodCardHTML += `<i class="fa ${method.icon || 'fa-university'}"></i>`;
		methodCardHTML += '</div>';
		methodCardHTML += '<div class="payment-method-info flex-grow-1">';
		methodCardHTML += `<h6>${method.name}</h6>`;
		methodCardHTML += '<div class="text-muted">';
		methodCardHTML += `${method.description}<br>`;
		methodCardHTML += `<small><strong>Processing:</strong> ${method.processing_time}</small>`;

		if (method.requires_mandate) {
			methodCardHTML += `<br><small class="text-warning"><strong>Note:</strong> ${method.note}</small>`;
		}

		methodCardHTML += '</div>';
		methodCardHTML += '</div>';
		methodCardHTML += '<div class="payment-method-selector">';
		methodCardHTML += '<div class="form-check">';

		const radioId = `payment_${method.name.replace(/\s+/g, '_').toLowerCase()}`;
		methodCardHTML += '<input class="form-check-input payment-method-radio" type="radio" ';
		methodCardHTML += `name="payment_method_selection" value="${method.name}" id="${radioId}">`;
		methodCardHTML += `<label class="form-check-label" for="${radioId}">`;
		methodCardHTML += 'Select';
		methodCardHTML += '</label>';
		methodCardHTML += '</div>';
		methodCardHTML += '</div>';
		methodCardHTML += '</div>';
		methodCardHTML += '</div>';

		return $(methodCardHTML);
	}

	showPaymentMethodFallback() {
		const container = $('#payment-methods-list');
		const fallback = $('#payment-method-fallback');

		container.hide();
		fallback.show();

		const select = $('#payment_method');
		select.empty();

		const fallbackMethods = [
			{
				name: 'Bank Transfer',
				description: 'One-time bank transfer',
				icon: 'fa-university',
				processing_time: '1-3 business days',
				requires_mandate: false
			},
			{
				name: 'SEPA Direct Debit',
				description: 'SEPA Direct Debit (recurring)',
				icon: 'fa-repeat',
				processing_time: '5-7 days first collection',
				requires_mandate: true
			}
		];

		fallbackMethods.forEach(method => {
			select.append(`<option value="${method.name}">${method.name} - ${method.description}</option>`);
		});

		// Bind change event
		select.off('change').on('change', (e) => {
			const selectedMethod = $(e.target).val();
			if (selectedMethod) {
				this.selectPaymentMethod(selectedMethod);
			}
		});

		// Auto-select first option
		if (fallbackMethods.length > 0) {
			const defaultMethod = fallbackMethods[0].name;
			select.val(defaultMethod);
			this.selectPaymentMethod(defaultMethod);
		}
	}

	bindEvents() {
		// Main binding happens in bindPaymentEvents after rendering
	}

	bindPaymentEvents() {
		console.log('PaymentStep: Binding payment events');

		$('.payment-method-option').off('click').on('click', (e) => {
			const target = $(e.target).closest('.payment-method-option');
			const methodName = target.data('method');
			console.log('PaymentStep: Payment method clicked:', methodName, 'Target:', target);
			this.selectPaymentMethod(methodName);
		});

		$('.payment-method-radio').off('change').on('change', (e) => {
			if ($(e.target).is(':checked')) {
				console.log('PaymentStep: Payment method radio changed:', $(e.target).val());
				this.selectPaymentMethod($(e.target).val());
			}
		});

		// Also bind to the main app's payment method events for field switching
		if (typeof membershipApp !== 'undefined' && membershipApp.bindPaymentMethodEvents) {
			console.log('PaymentStep: Calling main app bindPaymentMethodEvents');
			membershipApp.bindPaymentMethodEvents();
		}

		console.log('PaymentStep: Found payment method options:', $('.payment-method-option').length);
		console.log('PaymentStep: Found payment method radios:', $('.payment-method-radio').length);
	}

	selectPaymentMethod(methodName) {
		if (!methodName) { return; }

		console.log('Selecting payment method:', methodName);

		// Update state
		membershipApp.setPaymentMethod(methodName);

		// Update UI
		if ($('#payment-method-fallback').is(':visible')) {
			$('#payment_method').val(methodName);
		} else {
			$('.payment-method-option').removeClass('selected');
			$(`.payment-method-option[data-method="${methodName}"]`).addClass('selected');

			// Update radio button and trigger change event
			const radioButton = $(`.payment-method-radio[value="${methodName}"]`);
			console.log('PaymentStep: Found radio button for', methodName, ':', radioButton.length);
			radioButton.prop('checked', true).trigger('change');
		}

		// Use the main app's handlePaymentMethodChange for consistent behavior
		if (typeof membershipApp !== 'undefined' && membershipApp.handlePaymentMethodChange) {
			console.log('PaymentStep: Using main app handlePaymentMethodChange for:', methodName);
			membershipApp.handlePaymentMethodChange(methodName);
		} else {
			// Fallback for standalone operation
			console.log('PaymentStep: Fallback - showing fields for payment method:', methodName);
			// Payment method sections hidden by default
			$('#bank-account-details').hide();
			$('#bank-transfer-notice').hide();
			$('#bank-transfer-details').hide();

			if (methodName === 'SEPA Direct Debit') {
				console.log('PaymentStep: Showing bank account fields');
				$('#bank-account-details').show();
			} else if (methodName === 'Bank Transfer') {
				console.log('PaymentStep: Showing bank transfer details with account fields');
				$('#bank-transfer-details').show();
			}
		}
	}

	updateSummary(state) {
		// Use the main application's comprehensive updateApplicationSummary method
		// which includes detailed financial information and proper data handling
		if (typeof membershipApp !== 'undefined' && membershipApp.updateApplicationSummary) {
			membershipApp.updateApplicationSummary();
		} else {
			// Fallback to basic summary if main app method is not available
			this.updateBasicSummary(state);
		}
	}

	updateBasicSummary(state) {
		const summary = $('#application-summary');

		let content = '<div class="row">';
		content += '<div class="col-md-6">';
		content += '<h6>Personal Information</h6>';
		content += `<p><strong>Name:</strong> ${$('#first_name').val() || ''} ${$('#last_name').val() || ''}</p>`;
		content += `<p><strong>Email:</strong> ${$('#email').val() || ''}</p>`;

		const age = this.calculateAge($('#birth_date').val());
		if (age > 0) {
			content += `<p><strong>Age:</strong> ${age} years</p>`;
		}

		content += '</div>';
		content += '<div class="col-md-6">';
		content += '<h6>Membership</h6>';

		const membership = state.get('membership');
		if (membership && membership.type) {
			const membershipTypes = state.get('membershipTypes') || [];
			const membershipType = membershipTypes.find(t => t.name === membership.type);
			if (membershipType) {
				content += `<p><strong>Type:</strong> ${membershipType.membership_type_name}</p>`;
				content += `<p><strong>Amount:</strong> ${frappe.format(membership.amount, { fieldtype: 'Currency' })}</p>`;
				if (membership.isCustom) {
					content += '<p><em>Custom contribution selected</em></p>';
				}
			}
		}

		content += '</div>';
		content += '</div>';

		if ($('#selected_chapter').val()) {
			content += `<p><strong>Chapter:</strong> ${$('#selected_chapter option:selected').text()}</p>`;
		}

		if ($('#interested_in_volunteering').is(':checked')) {
			content += '<p><strong>Interested in volunteering:</strong> Yes</p>';
		}

		const paymentMethod = $('input[name="payment_method_selection"]:checked').val() || $('#payment_method').val();
		if (paymentMethod) {
			content += `<p><strong>Payment Method:</strong> ${paymentMethod}</p>`;
		}

		summary.html(content);
	}

	calculateAge(birthDate) {
		if (!birthDate) { return 0; }

		try {
			const birth = new Date(birthDate);
			const today = new Date();

			if (isNaN(birth.getTime())) {
				console.warn('Invalid birth date in PaymentStep:', birthDate);
				return 0;
			}

			let age = today.getFullYear() - birth.getFullYear();

			if (today.getMonth() < birth.getMonth()
                || (today.getMonth() === birth.getMonth() && today.getDate() < birth.getDate())) {
				age--;
			}

			return Math.max(0, age);
		} catch (error) {
			console.error('Error calculating age in PaymentStep:', error);
			return 0;
		}
	}

	async validate() {
		let valid = true;

		// Clear previous validation
		$('.invalid-feedback').remove();
		$('.is-invalid').removeClass('is-invalid');

		// Payment method validation
		const paymentMethod = $('input[name="payment_method_selection"]:checked').val() || $('#payment_method').val();
		if (!paymentMethod) {
			if ($('#payment-method-fallback').is(':visible')) {
				$('#payment_method').addClass('is-invalid');
				$('#payment_method').after('<div class="invalid-feedback">Please select a payment method</div>');
			} else {
				const errorDiv = $('<div class="invalid-feedback d-block text-danger mb-3">Please select a payment method</div>');
				$('#payment-methods-list').after(errorDiv);
			}
			valid = false;
		} else {
			// Validate payment-specific fields based on selected method
			if (paymentMethod === 'SEPA Direct Debit') {
				// Bank account validation
				if (!$('#iban').val()) {
					$('#iban').addClass('is-invalid');
					$('#iban').after('<div class="invalid-feedback">IBAN is required</div>');
					valid = false;
				}

				const bankAccountName = $('#bank_account_name').val() || $('#account_holder_name').val();
				if (!bankAccountName) {
					const $field = $('#bank_account_name').length ? $('#bank_account_name') : $('#account_holder_name');
					$field.addClass('is-invalid');
					$field.after('<div class="invalid-feedback">Account holder name is required</div>');
					valid = false;
				}

				// Basic IBAN validation (at least country code + 2 check digits + account identifier)
				const iban = $('#iban').val().replace(/\s/g, '');
				if (iban && (iban.length < 15 || iban.length > 34 || !/^[A-Z]{2}[0-9]{2}[A-Z0-9]+$/i.test(iban))) {
					$('#iban').addClass('is-invalid');
					$('#iban').after('<div class="invalid-feedback">Please enter a valid IBAN</div>');
					valid = false;
				}
			}
			// Bank Transfer doesn't require additional fields
		}

		return valid;
	}

	getData() {
		return {
			payment_method: membershipApp.getPaymentMethod() || '',
			additional_notes: $('#additional_notes').val() || '',
			terms: $('#terms').is(':checked'),
			gdpr_consent: $('#gdpr_consent').is(':checked')
		};
	}
}

// ===================================
// 4. UTILITY CLASSES
// ===================================

// FormValidator already defined above

class MembershipAPI {
	async getFormData() {
		return await this.call('verenigingen.api.membership_application.get_application_form_data');
	}

	async validateEmail(email) {
		return await this.call('verenigingen.api.membership_application.validate_email', { email });
	}

	async validatePostalCode(postalCode, country) {
		return await this.call('verenigingen.api.membership_application.validate_postal_code', {
			postal_code: postalCode,
			country
		});
	}

	async validateCustomAmount(membershipType, amount) {
		return await this.call('verenigingen.api.membership_application.validate_custom_amount', {
			membership_type: membershipType,
			amount
		});
	}

	async submitApplication(data) {
		return new Promise((resolve, reject) => {
			console.log('Submitting application data:', data);

			// Use direct AJAX call instead of frappe.call to avoid URL issues
			$.ajax({
				url: '/api/method/verenigingen.api.membership_application.submit_application_with_tracking',
				type: 'POST',
				data: {
					data: JSON.stringify(data)
				},
				headers: {
					'X-Frappe-CSRF-Token': frappe.csrf_token || ''
				},
				dataType: 'json',
				success(response) {
					console.log('Direct AJAX response:', response);
					if (response.message && response.message.success) {
						resolve(response.message);
					} else if (response.message) {
						console.log('Full error response:', response.message);
						const errorMsg = response.message.message || response.message.error || 'Submission failed';
						reject(new Error(errorMsg));
					} else {
						reject(new Error('Unknown response format'));
					}
				},
				error(xhr, status, error) {
					console.error('Direct AJAX error:', { xhr, status, error });
					let errorMsg = 'Network error occurred';

					if (xhr.responseJSON && xhr.responseJSON.exc) {
						errorMsg = xhr.responseJSON.exc;
					} else if (xhr.responseText) {
						try {
							const parsed = JSON.parse(xhr.responseText);
							errorMsg = parsed.message || parsed.exc || errorMsg;
						} catch (e) {
							errorMsg = `Server error: ${xhr.status} ${xhr.statusText}`;
						}
					} else {
						errorMsg = `Server error: ${xhr.status} ${xhr.statusText}`;
					}

					reject(new Error(errorMsg));
				}
			});
		});
	}

	async saveDraft(data) {
		return await this.call('verenigingen.api.membership_application.save_draft_application', { data });
	}

	async call(method, args = {}) {
		return new Promise((resolve, reject) => {
			// Add timeout to prevent hanging requests
			const timeoutId = setTimeout(() => {
				reject(new Error('Request timeout - server did not respond'));
			}, 30000); // 30 second timeout

			frappe.call({
				method,
				args,
				callback: (r) => {
					clearTimeout(timeoutId);

					if (r.message !== undefined) {
						resolve(r.message);
					} else if (r.exc) {
						reject(new Error(r.exc));
					} else {
						// Sometimes frappe returns success with no message
						resolve(r);
					}
				},
				error: (r) => {
					clearTimeout(timeoutId);
					console.error('API call error:', r);

					let errorMsg = 'Network error';
					if (r.responseJSON?.exc) {
						errorMsg = r.responseJSON.exc;
					} else if (r.statusText) {
						errorMsg = `${r.status}: ${r.statusText}`;
					} else if (r.message) {
						errorMsg = r.message;
					}

					reject(new Error(errorMsg));
				}
			});
		});
	}

	// Alternative submit method using direct AJAX if frappe.call continues to fail
	async submitApplicationDirect(data) {
		return new Promise((resolve, reject) => {
			console.log('Using direct AJAX submission');

			$.ajax({
				url: '/api/method/verenigingen.api.membership_application.submit_application_with_tracking',
				type: 'POST',
				data: {
					data: JSON.stringify(data)
				},
				headers: {
					'X-Frappe-CSRF-Token': frappe.csrf_token
				},
				success(response) {
					console.log('Direct AJAX response:', response);

					// Check if response contains an error message (even in "success" response)
					if (response.error_message || (response.server_messages && response.server_messages.includes('does not have permission'))) {
						let errorMsg = response.error_message || 'Permission denied';

						// Try to extract clean error from server_messages
						if (response.server_messages) {
							try {
								const messages = JSON.parse(response.server_messages);
								if (messages && messages.length > 0) {
									const firstMessage = typeof messages[0] === 'string' ? JSON.parse(messages[0]) : messages[0];
									if (firstMessage.message) {
										errorMsg = firstMessage.message.replace(/<[^>]*>/g, ''); // Strip HTML
									}
								}
							} catch (e) {
								console.warn('Could not parse server messages:', e);
							}
						}

						reject(new Error(errorMsg));
						return;
					}

					if (response.message && response.message.success) {
						resolve(response.message);
					} else if (response.message && response.message.error) {
						reject(new Error(response.message.message || response.message.error));
					} else {
						reject(new Error(response.message || 'Unknown error occurred'));
					}
				},
				error(xhr, status, error) {
					console.error('Direct AJAX error:', xhr, status, error);
					let errorMsg = `Server error: ${xhr.status}`;

					if (xhr.responseJSON) {
						if (xhr.responseJSON.exc) {
							errorMsg = xhr.responseJSON.exc;
						} else if (xhr.responseJSON.error_message) {
							errorMsg = xhr.responseJSON.error_message;
						} else if (xhr.responseJSON.message && xhr.responseJSON.message.error) {
							errorMsg = xhr.responseJSON.message.error;
						}
					} else if (error) {
						errorMsg = error;
					}

					reject(new Error(errorMsg));
				}
			});
		});
	}
}

class _UIManager {
	hideAllSteps() {
		$('.form-step').hide().removeClass('active');
	}

	showStep(stepNumber) {
		$(`.form-step[data-step="${stepNumber}"]`).show().addClass('active');
	}

	updateProgress(current, total) {
		const progress = (current / total) * 100;
		$('#form-progress').css('width', `${progress}%`);

		$('.step').removeClass('active completed');
		for (let i = 1; i < current; i++) {
			$(`.step[data-step="${i}"]`).addClass('completed');
		}
		$(`.step[data-step="${current}"]`).addClass('active');
	}

	updateNavigation(current, total) {
		$('#prev-btn').toggle(current > 1);
		$('#next-btn').toggle(current < total);
		$('#submit-btn').toggle(current === total);
	}

	setSubmitting(isSubmitting) {
		const btn = $('#submit-btn');
		if (isSubmitting) {
			btn.prop('disabled', true).html('<i class="fa fa-spinner fa-spin"></i> Processing...');
		} else {
			btn.prop('disabled', false).html('Submit Application & Pay');
		}
	}

	showSuccess(result) {
		// Create success message with application ID prominently displayed
		let successHTML = '<div class="text-center py-5">';
		successHTML += '<div class="success-icon mb-4">';
		successHTML += '<i class="fa fa-check-circle text-success" style="font-size: 4rem;"></i>';
		successHTML += '</div>';
		successHTML += '<h2 class="text-success">Application Submitted Successfully!</h2>';

		// Display application ID if available
		if (result.application_id) {
			successHTML += '<div class="alert alert-info mx-auto" style="max-width: 500px;">';
			successHTML += `<h4>Your Application ID: <strong>${result.application_id}</strong></h4>`;
			successHTML += '<p>Please save this ID for future reference.</p>';
			successHTML += '</div>';
		}

		successHTML += '<p class="lead">Thank you for your application. ';

		if (result.payment_url) {
			successHTML += 'You will be redirected to complete payment.</p>';
			successHTML += '<div class="mt-4">';
			successHTML += '<div class="spinner-border text-primary" role="status">';
			successHTML += '<span class="sr-only">Loading...</span>';
			successHTML += '</div>';
			successHTML += '</div>';
		} else {
			successHTML += 'You will receive an email with next steps.</p>';
			successHTML += '<div class="mt-4">';
			successHTML += `<a href="/application-status?id=${result.application_id}" class="btn btn-primary">`;
			successHTML += 'Check Application Status';
			successHTML += '</a>';
			successHTML += '</div>';
		}

		successHTML += '</div>';

		$('.membership-application-form').html(successHTML);

		// Scroll to top
		window.scrollTo(0, 0);
	}

	showError(title, error) {
		const message = error.message || error.toString();
		frappe.msgprint({
			title,
			message,
			indicator: 'red'
		});
	}
}

// ===================================
// 5. INITIALIZATION
// ===================================

// Global debug functions for beta testing (available after initialization)
window.debugApp = () => {
	if (!window.membershipApp) {
		console.error('membershipApp not initialized yet');
		return null;
	}
	console.log('=== APPLICATION DEBUG ===');
	console.log('State:', window.membershipApp.state.getData());
	console.log('Current step:', window.membershipApp.state.currentStep);
	console.log('Selected membership:', window.membershipApp.state.get('membership'));
	console.log('========================');
	return window.membershipApp.state.getData();
};

window.debugMembershipSelection = () => {
	if (!window.membershipApp) {
		console.error('membershipApp not initialized yet');
		return;
	}
	console.log('=== MEMBERSHIP SELECTION DEBUG ===');
	const membership = window.membershipApp.state.get('membership');
	console.log('Membership data:', membership);
	console.log('Legacy compatibility:');
	console.log('  - selected_membership_type:', window.membershipApp.state.get('selected_membership_type'));
	console.log('  - custom_contribution_fee:', window.membershipApp.state.get('custom_contribution_fee'));
	console.log('  - uses_custom_amount:', window.membershipApp.state.get('uses_custom_amount'));

	// Check visible custom sections
	$('.custom-amount-section:visible').each(function () {
		const card = $(this).closest('.membership-type-card');
		console.log('Visible custom section for:', card.data('type'));
		console.log('Input value:', $(this).find('.custom-amount-input').val());
	});

	// Check selected membership cards
	$('.membership-type-card.selected').each(function () {
		console.log('Selected card:', $(this).data('type'), 'amount:', $(this).data('amount'));
	});

	// Test form data collection
	console.log('All form data:', membershipApp.getAllFormData());

	console.log('=================================');
	return membership;
};

window.debugAge = (birthDate) => {
	try {
		const testBirthDate = birthDate || $('#birth_date').val();
		const age = membershipApp.calculateAge(testBirthDate);
		console.log('Age calculation:', { birthDate: testBirthDate, age });

		if (age > 100) {
			console.log('Should show >100 warning');
		} else if (age < 12) {
			console.log('Should show <12 warning');
		} else {
			console.log('No age warning needed');
		}

		// Test the validation display
		if (testBirthDate) {
			$('#birth_date').val(testBirthDate).trigger('change');
		}

		return age;
	} catch (error) {
		console.error('Error in debugAge:', error);
		return 0;
	}
};

// Debug commands available:
// - debugApp() - Show full application state
// - debugMembershipSelection() - Check membership selection
// - debugAge(birthDate) - Test age validation

// ConfirmationStep class for step 6
class ConfirmationStep extends BaseStep {
	constructor() {
		super('confirmation');
	}

	render(state) {
		// Update final summary when rendered
		if (typeof membershipApp !== 'undefined' && membershipApp.updateFinalApplicationSummary) {
			membershipApp.updateFinalApplicationSummary();
		}
	}

	async validate() {
		let valid = true;

		// Clear previous validation
		$('.invalid-feedback').remove();
		$('.is-invalid').removeClass('is-invalid');

		// Terms validation
		if (!$('#terms').is(':checked')) {
			$('#terms').addClass('is-invalid');
			$('#terms').closest('.form-check').after('<div class="invalid-feedback d-block">You must accept the terms and conditions</div>');
			valid = false;
		}

		// GDPR consent validation
		if (!$('#gdpr_consent').is(':checked')) {
			$('#gdpr_consent').addClass('is-invalid');
			$('#gdpr_consent').closest('.form-check').after('<div class="invalid-feedback d-block">You must consent to data processing</div>');
			valid = false;
		}

		// Accuracy confirmation validation
		if (!$('#confirm_accuracy').is(':checked')) {
			$('#confirm_accuracy').addClass('is-invalid');
			$('#confirm_accuracy').closest('.form-check').after('<div class="invalid-feedback d-block">You must confirm the accuracy of your information</div>');
			valid = false;
		}

		return valid;
	}

	formatCurrency(amount) {
		// Format currency with EUR symbol and 2 decimal places
		if (typeof amount !== 'number' || isNaN(amount)) {
			return '€0.00';
		}
		return `€${amount.toFixed(2)}`;
	}
}

// Add this debug function to test the backend method
window.testBackendMethod = async function () {
	console.log('Testing backend method availability...');

	try {
		const result = await new Promise((resolve, reject) => {
			frappe.call({
				method: 'verenigingen.api.membership_application.get_application_form_data',
				callback: (r) => {
					if (r.message !== undefined) {
						resolve(r.message);
					} else {
						reject(new Error('No response'));
					}
				},
				error: reject
			});
		});

		console.log('Backend method test successful:', result);
		return result;
	} catch (error) {
		console.error('Backend method test failed:', error);
		return null;
	}
};

// Export the MembershipApplication class for use in templates
window.MembershipApplication = _MembershipApplication;
