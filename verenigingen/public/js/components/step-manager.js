/**
 * Step Manager for Membership Application
 * Handles step navigation, validation, and progress tracking
 */

class StepManager {
	constructor(validationService, storageService, options = {}) {
		this.validation = validationService;
		this.storage = storageService;
		this.options = {
			totalSteps: 5,
			allowSkipping: false,
			autoSave: true,
			...options
		};

		this.currentStep = 1;
		this.stepHistory = [1];
		this.stepData = {};
		this.stepValidationResults = {};

		this.steps = this._initializeSteps();
		this._initializeUI();
	}

	/**
     * Initialize step definitions
     */
	_initializeSteps() {
		return {
			1: {
				id: 'personal-info',
				title: 'Personal Information',
				description: 'Tell us about yourself',
				fields: ['firstName', 'lastName', 'email', 'birthDate'],
				required: true,
				icon: 'fas fa-user',
				estimatedTime: '2 minutes'
			},
			2: {
				id: 'address',
				title: 'Address Information',
				description: 'Where can we reach you?',
				fields: ['address', 'city', 'postalCode', 'country', 'phone'],
				required: true,
				icon: 'fas fa-home',
				estimatedTime: '1 minute'
			},
			3: {
				id: 'membership',
				title: 'Membership Type',
				description: 'Choose your membership',
				fields: ['membershipType', 'customAmount'],
				required: true,
				icon: 'fas fa-id-card',
				estimatedTime: '2 minutes'
			},
			4: {
				id: 'volunteer',
				title: 'Volunteer Interest',
				description: 'Help us grow (optional)',
				fields: ['volunteerInterest', 'volunteerAreas', 'volunteerSkills'],
				required: false,
				icon: 'fas fa-hands-helping',
				estimatedTime: '1 minute'
			},
			5: {
				id: 'review',
				title: 'Review & Submit',
				description: 'Confirm your application',
				fields: [],
				required: true,
				icon: 'fas fa-check-circle',
				estimatedTime: '1 minute'
			}
		};
	}

	/**
     * Initialize UI elements
     */
	_initializeUI() {
		this._createStepIndicator();
		this._createNavigationButtons();
		this._bindEvents();
	}

	/**
     * Create step indicator UI
     */
	_createStepIndicator() {
		const $container = $('.step-indicator-container');
		if ($container.length === 0) return;

		let indicatorHTML = '<div class="step-indicator">';

		for (let i = 1; i <= this.options.totalSteps; i++) {
			const step = this.steps[i];
			const isActive = i === this.currentStep;
			const isCompleted = this.stepValidationResults[i]?.valid;
			const isAccessible = this._isStepAccessible(i);

			indicatorHTML += `
                <div class="step-item ${isActive ? 'active' : ''} ${isCompleted ? 'completed' : ''} ${isAccessible ? 'accessible' : 'disabled'}"
                     data-step="${i}">
                    <div class="step-icon">
                        <i class="${step.icon}"></i>
                        <span class="step-number">${i}</span>
                    </div>
                    <div class="step-content">
                        <div class="step-title">${step.title}</div>
                        <div class="step-description">${step.description}</div>
                        <div class="step-time">${step.estimatedTime}</div>
                    </div>
                    <div class="step-status">
                        <i class="fas fa-check completion-check"></i>
                        <i class="fas fa-exclamation-triangle error-icon"></i>
                    </div>
                </div>
            `;
		}

		indicatorHTML += '</div>';
		$container.html(indicatorHTML);
	}

	/**
     * Create navigation buttons
     */
	_createNavigationButtons() {
		const $container = $('.step-navigation-container');
		if ($container.length === 0) return;

		const navigationHTML = `
            <div class="step-navigation">
                <button type="button" class="btn btn-secondary btn-prev" id="btn-previous">
                    <i class="fas fa-chevron-left"></i> Previous
                </button>
                <div class="step-progress-text">
                    Step <span class="current-step">${this.currentStep}</span> of ${this.options.totalSteps}
                </div>
                <button type="button" class="btn btn-primary btn-next" id="btn-next">
                    Next <i class="fas fa-chevron-right"></i>
                </button>
                <button type="button" class="btn btn-success btn-submit" id="btn-submit" style="display: none;">
                    Submit Application <i class="fas fa-paper-plane"></i>
                </button>
            </div>
        `;

		$container.html(navigationHTML);
	}

	/**
     * Bind events
     */
	_bindEvents() {
		// Navigation buttons
		$(document).on('click', '#btn-next', () => this.nextStep());
		$(document).on('click', '#btn-previous', () => this.previousStep());
		$(document).on('click', '#btn-submit', () => this.submitApplication());

		// Step indicator clicks
		$(document).on('click', '.step-item.accessible', (e) => {
			const stepNumber = parseInt($(e.currentTarget).data('step'));
			this.goToStep(stepNumber);
		});

		// Keyboard navigation
		$(document).on('keydown', (e) => {
			if (e.ctrlKey || e.metaKey) {
				if (e.key === 'ArrowLeft') {
					e.preventDefault();
					this.previousStep();
				} else if (e.key === 'ArrowRight') {
					e.preventDefault();
					this.nextStep();
				}
			}
		});
	}

	/**
     * Navigate to next step
     */
	async nextStep() {
		if (this.currentStep >= this.options.totalSteps) return;

		// Validate current step
		const isValid = await this.validateCurrentStep();
		if (!isValid && !this.options.allowSkipping) {
			this._showStepError('Please fix the errors before continuing');
			return;
		}

		// Save current step data
		if (this.options.autoSave) {
			await this._saveCurrentStepData();
		}

		this.goToStep(this.currentStep + 1);
	}

	/**
     * Navigate to previous step
     */
	async previousStep() {
		if (this.currentStep <= 1) return;

		// Save current step data without validation
		if (this.options.autoSave) {
			await this._saveCurrentStepData();
		}

		this.goToStep(this.currentStep - 1);
	}

	/**
     * Go directly to a specific step
     */
	async goToStep(stepNumber) {
		if (!this._isValidStepNumber(stepNumber)) return;
		if (!this._isStepAccessible(stepNumber)) return;

		// Hide current step
		this._hideStep(this.currentStep);

		// Update current step
		const previousStep = this.currentStep;
		this.currentStep = stepNumber;

		// Update step history
		if (!this.stepHistory.includes(stepNumber)) {
			this.stepHistory.push(stepNumber);
		}

		// Show new step
		this._showStep(stepNumber);

		// Update UI
		this._updateStepIndicator();
		this._updateNavigationButtons();
		this._updateProgressText();

		// Trigger step change event
		this._triggerStepChangeEvent(previousStep, stepNumber);

		// Load step data if available
		await this._loadStepData(stepNumber);

		// Focus first input
		this._focusFirstInput();

		// Update URL hash (for bookmarking)
		this._updateURLHash();
	}

	/**
     * Validate current step
     */
	async validateCurrentStep() {
		const step = this.steps[this.currentStep];
		if (!step) return false;

		// Get current step data
		const stepData = this._getCurrentStepData();

		// Validate step fields
		const validationResult = await this.validation.validateStep(this.currentStep, stepData);

		// Store validation results
		this.stepValidationResults[this.currentStep] = validationResult;

		// Update UI based on validation
		this._updateStepValidationUI(validationResult);

		return validationResult.valid;
	}

	/**
     * Submit application
     */
	async submitApplication() {
		// Validate all steps
		const allValid = await this._validateAllSteps();
		if (!allValid) {
			this._showSubmissionError('Please complete all required steps before submitting');
			return;
		}

		// Collect all data
		const applicationData = this._collectAllData();

		// Trigger submission event
		$(document).trigger('application:submit', applicationData);
	}

	/**
     * Get current step data from form
     */
	_getCurrentStepData() {
		const $currentStepContainer = $(`.step-content[data-step="${this.currentStep}"]`);
		const data = {};

		$currentStepContainer.find('input, select, textarea').each((index, element) => {
			const $element = $(element);
			const name = $element.attr('name');
			if (name) {
				if ($element.attr('type') === 'checkbox') {
					data[name] = $element.is(':checked');
				} else if ($element.attr('type') === 'radio') {
					if ($element.is(':checked')) {
						data[name] = $element.val();
					}
				} else {
					data[name] = $element.val();
				}
			}
		});

		return data;
	}

	/**
     * Save current step data
     */
	async _saveCurrentStepData() {
		const stepData = this._getCurrentStepData();
		this.stepData[this.currentStep] = stepData;

		// Save to storage service
		if (this.storage) {
			this.storage.markDirty();
		}
	}

	/**
     * Load step data
     */
	async _loadStepData(stepNumber) {
		const savedData = this.stepData[stepNumber];
		if (!savedData) return;

		const $stepContainer = $(`.step-content[data-step="${stepNumber}"]`);

		// Populate form fields
		Object.entries(savedData).forEach(([name, value]) => {
			const $field = $stepContainer.find(`[name="${name}"]`);
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
	}

	/**
     * UI update methods
     */
	_showStep(stepNumber) {
		$(`.step-content[data-step="${stepNumber}"]`).show().addClass('active');
		$('body').attr('data-current-step', stepNumber);
	}

	_hideStep(stepNumber) {
		$(`.step-content[data-step="${stepNumber}"]`).hide().removeClass('active');
	}

	_updateStepIndicator() {
		$('.step-item').removeClass('active');
		$(`.step-item[data-step="${this.currentStep}"]`).addClass('active');

		// Update completed status
		Object.entries(this.stepValidationResults).forEach(([step, result]) => {
			const $stepItem = $(`.step-item[data-step="${step}"]`);
			$stepItem.toggleClass('completed', result.valid);
			$stepItem.toggleClass('has-errors', !result.valid && result.errors?.length > 0);
		});
	}

	_updateNavigationButtons() {
		const $prevBtn = $('#btn-previous');
		const $nextBtn = $('#btn-next');
		const $submitBtn = $('#btn-submit');

		// Previous button
		$prevBtn.prop('disabled', this.currentStep <= 1);

		// Next/Submit button
		if (this.currentStep >= this.options.totalSteps) {
			$nextBtn.hide();
			$submitBtn.show();
		} else {
			$nextBtn.show();
			$submitBtn.hide();
		}
	}

	_updateProgressText() {
		$('.current-step').text(this.currentStep);

		// Update progress bar if exists
		const progressPercent = (this.currentStep / this.options.totalSteps) * 100;
		$('.progress-bar').css('width', `${progressPercent}%`);
	}

	_updateStepValidationUI(validationResult) {
		const $stepItem = $(`.step-item[data-step="${this.currentStep}"]`);

		$stepItem.removeClass('completed has-errors has-warnings');

		if (validationResult.valid) {
			$stepItem.addClass('completed');
			if (validationResult.summary?.warnings > 0) {
				$stepItem.addClass('has-warnings');
			}
		} else {
			$stepItem.addClass('has-errors');
		}
	}

	/**
     * Utility methods
     */
	_isValidStepNumber(stepNumber) {
		return stepNumber >= 1 && stepNumber <= this.options.totalSteps;
	}

	_isStepAccessible(stepNumber) {
		if (this.options.allowSkipping) return true;

		// Can access current step, previous steps, or next step if current is valid
		if (stepNumber <= this.currentStep) return true;
		if (stepNumber === this.currentStep + 1 && this.stepValidationResults[this.currentStep]?.valid) return true;

		return false;
	}

	async _validateAllSteps() {
		let allValid = true;

		for (let i = 1; i <= this.options.totalSteps; i++) {
			const step = this.steps[i];
			if (step.required) {
				// Go to step to validate it
				if (i !== this.currentStep) {
					await this.goToStep(i);
				}

				const isValid = await this.validateCurrentStep();
				if (!isValid) {
					allValid = false;
				}
			}
		}

		return allValid;
	}

	_collectAllData() {
		return Object.values(this.stepData).reduce((acc, stepData) => {
			return { ...acc, ...stepData };
		}, {});
	}

	_focusFirstInput() {
		setTimeout(() => {
			const $firstInput = $(`.step-content[data-step="${this.currentStep}"] input, .step-content[data-step="${this.currentStep}"] select`).first();
			if ($firstInput.length && $firstInput.is(':visible')) {
				$firstInput.focus();
			}
		}, 100);
	}

	_updateURLHash() {
		if (history.replaceState) {
			history.replaceState(null, null, `#step-${this.currentStep}`);
		}
	}

	_triggerStepChangeEvent(fromStep, toStep) {
		$(document).trigger('step:change', {
			from: fromStep,
			to: toStep,
			step: this.steps[toStep],
			data: this.stepData[toStep] || {}
		});
	}

	_showStepError(message) {
		// Show error message (could be integrated with ErrorHandler)
		frappe.msgprint({
			title: 'Validation Error',
			message: message,
			indicator: 'red'
		});
	}

	_showSubmissionError(message) {
		// Show submission error
		frappe.msgprint({
			title: 'Submission Error',
			message: message,
			indicator: 'red'
		});
	}

	/**
     * Public API
     */
	getCurrentStep() {
		return this.currentStep;
	}

	getStepData(stepNumber = null) {
		return stepNumber ? this.stepData[stepNumber] : this.stepData;
	}

	getAllData() {
		return this._collectAllData();
	}

	getValidationResults() {
		return this.stepValidationResults;
	}

	getProgress() {
		const completedSteps = Object.values(this.stepValidationResults).filter(r => r.valid).length;
		return {
			current: this.currentStep,
			total: this.options.totalSteps,
			completed: completedSteps,
			percentage: (completedSteps / this.options.totalSteps) * 100
		};
	}

	// Reset the form
	reset() {
		this.currentStep = 1;
		this.stepHistory = [1];
		this.stepData = {};
		this.stepValidationResults = {};
		this.goToStep(1);
	}
}

// Export for use in other modules
window.StepManager = StepManager;
