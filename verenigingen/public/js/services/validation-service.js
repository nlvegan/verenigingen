/**
 * Validation Service for Membership Application
 * Handles all form validation with consistent error handling and UI feedback
 */

class ValidationService {
	constructor(apiService) {
		this.api = apiService;
		this.validationRules = this._initializeRules();
		this.validationCache = new Map();
		this.debounceTimers = new Map();
	}

	/**
     * Initialize validation rules
     */
	_initializeRules() {
		return {
			email: {
				required: true,
				pattern: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
				minLength: 5,
				maxLength: 255,
				async: true
			},
			firstName: {
				required: true,
				minLength: 2,
				maxLength: 50,
				pattern: /^[a-zA-ZÀ-ÿ\s-'.]+$/
			},
			lastName: {
				required: true,
				minLength: 2,
				maxLength: 50,
				pattern: /^[a-zA-ZÀ-ÿ\s-'.]+$/
			},
			birthDate: {
				required: true,
				async: true,
				customValidation: this._validateAge.bind(this)
			},
			postalCode: {
				required: true,
				async: true,
				customValidation: this._validatePostalCodeFormat.bind(this)
			},
			phone: {
				required: false,
				async: true,
				pattern: /^[+]?[0-9\s-()]{8,20}$/
			},
			address: {
				required: true,
				minLength: 5,
				maxLength: 255
			},
			city: {
				required: true,
				minLength: 2,
				maxLength: 100,
				pattern: /^[a-zA-ZÀ-ÿ\s-'.]+$/
			},
			country: {
				required: true,
				minLength: 2
			}
		};
	}

	/**
     * Validate a single field
     */
	async validateField(fieldName, value, context = {}) {
		const rule = this.validationRules[fieldName];
		if (!rule) {
			return { valid: true };
		}

		// Basic validations
		const basicValidation = this._validateBasic(fieldName, value, rule);
		if (!basicValidation.valid) {
			return basicValidation;
		}

		// Async validation with debouncing
		if (rule.async) {
			return await this._validateAsync(fieldName, value, rule, context);
		}

		return { valid: true };
	}

	/**
     * Validate multiple fields
     */
	async validateFields(data, fieldNames = null) {
		const fieldsToValidate = fieldNames || Object.keys(this.validationRules);
		const results = {};
		const errors = [];

		for (const fieldName of fieldsToValidate) {
			const result = await this.validateField(fieldName, data[fieldName], data);
			results[fieldName] = result;

			if (!result.valid) {
				errors.push({
					field: fieldName,
					message: result.message,
					value: data[fieldName]
				});
			}
		}

		return {
			valid: errors.length === 0,
			results,
			errors,
			summary: this._generateValidationSummary(results)
		};
	}

	/**
     * Validate a complete step
     */
	async validateStep(stepNumber, data) {
		const stepFields = this._getStepFields(stepNumber);
		return await this.validateFields(data, stepFields);
	}

	/**
     * Basic synchronous validation
     */
	_validateBasic(fieldName, value, rule) {
		// Required check
		if (rule.required && (!value || value.toString().trim() === '')) {
			return {
				valid: false,
				message: `${this._getFieldLabel(fieldName)} is required`,
				type: 'required'
			};
		}

		// Skip other validations if field is empty and not required
		if (!value && !rule.required) {
			return { valid: true };
		}

		const stringValue = value.toString().trim();

		// Length validations
		if (rule.minLength && stringValue.length < rule.minLength) {
			return {
				valid: false,
				message: `${this._getFieldLabel(fieldName)} must be at least ${rule.minLength} characters`,
				type: 'minLength'
			};
		}

		if (rule.maxLength && stringValue.length > rule.maxLength) {
			return {
				valid: false,
				message: `${this._getFieldLabel(fieldName)} must not exceed ${rule.maxLength} characters`,
				type: 'maxLength'
			};
		}

		// Pattern validation
		if (rule.pattern && !rule.pattern.test(stringValue)) {
			return {
				valid: false,
				message: this._getPatternErrorMessage(fieldName),
				type: 'pattern'
			};
		}

		return { valid: true };
	}

	/**
     * Async validation with debouncing and caching
     */
	async _validateAsync(fieldName, value, rule, context) {
		const cacheKey = `${fieldName}:${value}`;

		// Return cached result if available
		if (this.validationCache.has(cacheKey)) {
			return this.validationCache.get(cacheKey);
		}

		// Debounce async validations
		return new Promise((resolve) => {
			// Clear existing timer
			if (this.debounceTimers.has(fieldName)) {
				clearTimeout(this.debounceTimers.get(fieldName));
			}

			// Set new timer
			const timer = setTimeout(async () => {
				try {
					let result;

					// Custom validation function
					if (rule.customValidation) {
						result = await rule.customValidation(value, context);
					}
					// API validation
					else {
						result = await this._performAPIValidation(fieldName, value, context);
					}

					// Cache successful results
					if (result) {
						this.validationCache.set(cacheKey, result);
						// Clear cache after 5 minutes
						setTimeout(() => this.validationCache.delete(cacheKey), 300000);
					}

					resolve(result || { valid: true });
				} catch (error) {
					console.error(`Async validation failed for ${fieldName}:`, error);
					resolve({
						valid: false,
						message: 'Validation temporarily unavailable',
						type: 'network'
					});
				}
			}, 500); // 500ms debounce

			this.debounceTimers.set(fieldName, timer);
		});
	}

	/**
     * Perform API-based validation
     */
	async _performAPIValidation(fieldName, value, context) {
		switch (fieldName) {
			case 'email':
				return await this.api.validateEmail(value);

			case 'postalCode':
				return await this.api.validatePostalCode(value, context.country);

			case 'phone':
				return await this.api.validatePhoneNumber(value, context.country);

			case 'birthDate':
				return await this.api.validateBirthDate(value);

			default:
				return { valid: true };
		}
	}

	/**
     * Custom validation functions
     */
	async _validateAge(birthDate, context) {
		const result = await this.api.validateBirthDate(birthDate);

		if (!result.valid) {
			return result;
		}

		// Additional age-specific checks
		if (result.age !== undefined) {
			if (result.age < 12) {
				return {
					valid: true,
					message: 'Valid birth date',
					warning: 'Applicants under 12 may require parental consent',
					age: result.age
				};
			}

			if (result.age > 100) {
				return {
					valid: true,
					message: 'Valid birth date',
					age: result.age
				};
			}
		}

		return result;
	}

	_validatePostalCodeFormat(postalCode, context) {
		return this.api.validatePostalCode(postalCode, context.country);
	}

	/**
     * Real-time validation for UI
     */
	setupRealTimeValidation(element, fieldName, context = {}) {
		this._ensureFeedbackElement(element);

		// Store validation state
		element.dataset.validationState = 'pending';

		// Validation on input/change
		const handleValidation = async (event) => {
			const value = element.value;

			// Show loading state on blur
			if (event.type === 'blur' && value) {
				this._showValidationState(element, 'validating');
			}

			const result = await this.validateField(fieldName, value, typeof context === 'function' ? context() : context);
			this._showValidationResult(element, result);
		};

		element.addEventListener('input', handleValidation);
		element.addEventListener('change', handleValidation);
		element.addEventListener('blur', handleValidation);

		return element;
	}

	/**
     * Show validation result in UI
     */
	_showValidationResult(element, result) {
		const feedback = this._ensureFeedbackElement(element);

		// Remove existing classes
		element.classList.remove('is-valid', 'is-invalid', 'is-validating');
		feedback.classList.remove('valid-feedback', 'invalid-feedback', 'text-warning');

		if (result.valid) {
			element.classList.add('is-valid');
			feedback.classList.add('valid-feedback');
			feedback.textContent = result.message || 'Looks good!';

			// Show warnings if any
			if (result.warning) {
				feedback.classList.remove('valid-feedback');
				feedback.classList.add('text-warning');
				feedback.textContent = result.warning;
			}
		} else {
			element.classList.add('is-invalid');
			feedback.classList.add('invalid-feedback');
			feedback.textContent = result.message;
		}

		element.dataset.validationState = result.valid ? 'valid' : 'invalid';
		element.dataset.validationResult = JSON.stringify(result);
	}

	_showValidationState(element, state) {
		element.classList.remove('is-valid', 'is-invalid', 'is-validating');

		if (state === 'validating') {
			element.classList.add('is-validating');
			const feedback = this._ensureFeedbackElement(element);
			feedback.classList.remove('valid-feedback', 'invalid-feedback', 'text-warning');
			feedback.classList.add('text-muted');
			feedback.textContent = 'Validating...';
		}
	}

	_ensureFeedbackElement(element) {
		let feedback = element.parentNode.querySelector('.feedback');

		if (!feedback) {
			feedback = document.createElement('div');
			feedback.className = 'feedback';
			element.parentNode.insertBefore(feedback, element.nextSibling);
		}

		return feedback;
	}

	/**
     * Utility functions
     */
	_getStepFields(stepNumber) {
		const stepFieldMap = {
			1: ['firstName', 'lastName', 'email', 'birthDate'], // Personal Info
			2: ['address', 'city', 'postalCode', 'country'], // Address
			3: [], // Membership (validated separately)
			4: [], // Volunteer (optional)
			5: [] // Payment (handled by payment processor)
		};

		return stepFieldMap[stepNumber] || [];
	}

	_getFieldLabel(fieldName) {
		const labels = {
			email: 'Email address',
			firstName: 'First name',
			lastName: 'Last name',
			birthDate: 'Birth date',
			postalCode: 'Postal code',
			phone: 'Phone number',
			address: 'Address',
			city: 'City',
			country: 'Country'
		};

		return labels[fieldName] || fieldName;
	}

	_getPatternErrorMessage(fieldName) {
		const messages = {
			email: 'Please enter a valid email address',
			firstName: 'Name can only contain letters, spaces, hyphens, and apostrophes',
			lastName: 'Name can only contain letters, spaces, hyphens, and apostrophes',
			phone: 'Please enter a valid phone number',
			city: 'City name can only contain letters, spaces, hyphens, and apostrophes'
		};

		return messages[fieldName] || `Please enter a valid ${this._getFieldLabel(fieldName).toLowerCase()}`;
	}

	_generateValidationSummary(results) {
		const summary = {
			total: Object.keys(results).length,
			valid: 0,
			invalid: 0,
			warnings: 0
		};

		Object.values(results).forEach(result => {
			if (result.valid) {
				summary.valid++;
				if (result.warning) {
					summary.warnings++;
				}
			} else {
				summary.invalid++;
			}
		});

		return summary;
	}

	/**
     * Clear validation cache
     */
	clearCache(pattern = null) {
		if (pattern) {
			for (const key of this.validationCache.keys()) {
				if (key.includes(pattern)) {
					this.validationCache.delete(key);
				}
			}
		} else {
			this.validationCache.clear();
		}
	}

	/**
     * Get validation statistics
     */
	getValidationStats() {
		return {
			cacheSize: this.validationCache.size,
			activeTimers: this.debounceTimers.size,
			rules: Object.keys(this.validationRules).length
		};
	}
}

// Export for use in other modules
window.ValidationService = ValidationService;
