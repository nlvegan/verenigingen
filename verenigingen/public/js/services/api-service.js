/**
 * API Service for Membership Application
 * Handles all backend communication with error handling and retry logic
 */

class APIService {
	constructor(options = {}) {
		this.options = {
			timeout: 30000,
			retryCount: 3,
			retryDelay: 1000,
			...options
		};

		this.cache = new Map();
		this.requestQueue = new Map();
	}

	/**
     * Main API call method with error handling and caching
     */
	async call(method, args = {}, options = {}) {
		const cacheKey = this._getCacheKey(method, args);

		// Return cached result if available and not expired
		if (options.cache && this.cache.has(cacheKey)) {
			const cached = this.cache.get(cacheKey);
			if (Date.now() - cached.timestamp < (options.cacheTimeout || 300000)) {
				return cached.data;
			}
		}

		// Prevent duplicate requests
		if (this.requestQueue.has(cacheKey)) {
			return this.requestQueue.get(cacheKey);
		}

		const requestPromise = this._makeRequest(method, args, options);
		this.requestQueue.set(cacheKey, requestPromise);

		try {
			const result = await requestPromise;

			// Cache successful results
			if (options.cache && result) {
				this.cache.set(cacheKey, {
					data: result,
					timestamp: Date.now()
				});
			}

			return result;
		} finally {
			this.requestQueue.delete(cacheKey);
		}
	}

	/**
     * Make HTTP request with retry logic
     */
	async _makeRequest(method, args, options) {
		let lastError;

		for (let attempt = 0; attempt <= this.options.retryCount; attempt++) {
			try {
				return await this._singleRequest(method, args, options);
			} catch (error) {
				lastError = error;

				// Don't retry on client errors (4xx)
				if (error.httpStatus >= 400 && error.httpStatus < 500) {
					throw error;
				}

				// Don't retry on last attempt
				if (attempt === this.options.retryCount) {
					throw error;
				}

				// Wait before retry with exponential backoff
				const delay = this.options.retryDelay * Math.pow(2, attempt);
				await this._delay(delay);

				console.warn(`API retry ${attempt + 1}/${this.options.retryCount} for ${method}:`, error.message);
			}
		}

		throw lastError;
	}

	/**
     * Single HTTP request
     */
	_singleRequest(method, args, options) {
		return new Promise((resolve, reject) => {
			const timeoutId = setTimeout(() => {
				reject(new Error(`Request timeout after ${this.options.timeout}ms`));
			}, options.timeout || this.options.timeout);

			frappe.call({
				method,
				args,
				callback: (response) => {
					clearTimeout(timeoutId);

					if (response.message !== undefined) {
						resolve(response.message);
					} else if (response.exc) {
						reject(new Error(response.exc));
					} else {
						resolve(response);
					}
				},
				error: (response) => {
					clearTimeout(timeoutId);

					const error = new Error(response.statusText || 'Network error');
					error.httpStatus = response.status;
					error.response = response;

					console.error('API call failed:', {
						method,
						args,
						status: response.status,
						statusText: response.statusText
					});

					reject(error);
				}
			});
		});
	}

	/**
     * Get form initialization data
     */
	async getFormData() {
		return this.call(
			'verenigingen.api.membership_application.get_application_form_data',
			{},
			{ cache: true, cacheTimeout: 600000 } // Cache for 10 minutes
		);
	}

	/**
     * Validate email address
     */
	async validateEmail(email) {
		if (!email || email.length < 3) {
			return { valid: false, message: 'Email is too short' };
		}

		return this.call(
			'verenigingen.api.membership_application.validate_email',
			{ email },
			{ cache: true, cacheTimeout: 60000 } // Cache for 1 minute
		);
	}

	/**
     * Validate postal code
     */
	async validatePostalCode(postalCode, country = 'Netherlands') {
		if (!postalCode) {
			return { valid: false, message: 'Postal code is required' };
		}

		return this.call(
			'verenigingen.api.membership_application.validate_postal_code',
			{ postal_code: postalCode, country },
			{ cache: true, cacheTimeout: 300000 } // Cache for 5 minutes
		);
	}

	/**
     * Validate phone number
     */
	async validatePhoneNumber(phone, country = 'Netherlands') {
		if (!phone) {
			return { valid: true, message: 'Phone number is optional' };
		}

		return this.call(
			'verenigingen.api.membership_application.validate_phone_number',
			{ phone, country }
		);
	}

	/**
     * Validate birth date
     */
	async validateBirthDate(birthDate) {
		if (!birthDate) {
			return { valid: false, message: 'Birth date is required' };
		}

		return this.call(
			'verenigingen.api.membership_application.validate_birth_date',
			{ birth_date: birthDate }
		);
	}

	/**
     * Validate custom membership amount
     */
	async validateCustomAmount(membershipType, amount) {
		if (!membershipType || !amount) {
			return { valid: false, message: 'Membership type and amount are required' };
		}

		return this.call(
			'verenigingen.api.membership_application.validate_custom_amount',
			{ membership_type: membershipType, amount }
		);
	}

	/**
     * Get detailed membership type information
     */
	async getMembershipTypeDetails(membershipType) {
		return this.call(
			'verenigingen.api.membership_application.get_membership_type_details',
			{ membership_type: membershipType },
			{ cache: true, cacheTimeout: 300000 } // Cache for 5 minutes
		);
	}

	/**
     * Get suggested membership amounts
     */
	async getSuggestedAmounts(membershipTypeName) {
		return this.call(
			'verenigingen.api.membership_application.suggest_membership_amounts',
			{ membership_type_name: membershipTypeName },
			{ cache: true, cacheTimeout: 300000 }
		);
	}

	/**
     * Get available payment methods
     */
	async getPaymentMethods() {
		return this.call(
			'verenigingen.api.membership_application.get_payment_methods',
			{},
			{ cache: true, cacheTimeout: 600000 } // Cache for 10 minutes
		);
	}

	/**
     * Save application draft
     */
	async saveDraft(data) {
		return this.call(
			'verenigingen.api.membership_application.save_draft_application',
			{ data }
		);
	}

	/**
     * Load application draft
     */
	async loadDraft(draftId) {
		return this.call(
			'verenigingen.api.membership_application.load_draft_application',
			{ draft_id: draftId }
		);
	}

	/**
     * Submit membership application
     */
	async submitApplication(data) {
		// Clear any cached data to ensure fresh submission
		this.clearCache();

		return this.call(
			'verenigingen.api.membership_application.submit_application_with_tracking',
			{ data },
			{ timeout: 60000 } // Longer timeout for submission
		);
	}

	/**
     * Check application status
     */
	async checkApplicationStatus(applicationId) {
		return this.call(
			'verenigingen.api.membership_application.check_application_status',
			{ application_id: applicationId }
		);
	}

	/**
     * Check application eligibility
     */
	async checkEligibility(data) {
		return this.call(
			'verenigingen.api.membership_application.check_application_eligibility',
			{ data }
		);
	}

	/**
     * Test API connectivity
     */
	async testConnection() {
		return this.call(
			'verenigingen.api.membership_application.test_connection',
			{}
		);
	}

	/**
     * Utility methods
     */
	_getCacheKey(method, args) {
		return `${method}:${JSON.stringify(args)}`;
	}

	_delay(ms) {
		return new Promise(resolve => setTimeout(resolve, ms));
	}

	/**
     * Clear cache
     */
	clearCache(pattern = null) {
		if (pattern) {
			for (const key of this.cache.keys()) {
				if (key.includes(pattern)) {
					this.cache.delete(key);
				}
			}
		} else {
			this.cache.clear();
		}
	}

	/**
     * Get cache statistics
     */
	getCacheStats() {
		return {
			size: this.cache.size,
			keys: Array.from(this.cache.keys()),
			memoryUsage: JSON.stringify(Array.from(this.cache.entries())).length
		};
	}

	/**
     * Batch API calls for efficiency
     */
	async batchCall(requests) {
		const promises = requests.map(({ method, args, options }) =>
			this.call(method, args, options).catch(error => ({ error }))
		);

		return Promise.all(promises);
	}
}

// Export for use in other modules
window.APIService = APIService;
