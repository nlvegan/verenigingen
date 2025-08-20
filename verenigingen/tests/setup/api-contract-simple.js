/**
 * @fileoverview Simplified API Contract Testing Infrastructure
 *
 * Validates JavaScript-to-Python API calls without complex mock server setup.
 * Focuses on parameter validation and schema matching.
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 */

const Ajv = require('ajv');
const addFormats = require('ajv-formats');

// Standard patterns for consistency across all API contracts
const STANDARD_PATTERNS = {
	IBAN: '^[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{7,10}$', // Supports varying account length
	MEMBER_ID: '^(Assoc-)?Member-\\d{4}-\\d{2}-\\d{4}$',
	DUTCH_POSTAL_CODE: '^[1-9][0-9]{3}\\s?[A-Z]{2}$',
	BIC: '^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$'
};

/**
 * API Contract Schema Definitions
 * These schemas define what the Python backend expects
 */
const API_SCHEMAS = {
	// SEPA Direct Debit APIs
	'verenigingen.verenigingen_payments.utils.sepa_mandate.create_sepa_mandate': {
		args: {
			type: 'object',
			properties: {
				member: { type: 'string', pattern: '^(Assoc-)?Member-\\d{4}-\\d{2}-\\d{4}$' },
				iban: { type: 'string', pattern: STANDARD_PATTERNS.IBAN, minLength: 15, maxLength: 34 },
				bic: { type: 'string', pattern: '^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$' },
				mandate_type: { type: 'string', enum: ['CORE', 'B2B', 'FIRST', 'RCUR'], default: 'RCUR' },
				debtor_name: { type: 'string', minLength: 1, maxLength: 70 }
			},
			required: ['member', 'iban', 'bic'],
			additionalProperties: false
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				mandate_reference: { type: 'string', pattern: '^SEPA-\\d{4}-\\d{2}-\\d{4}$' },
				status: { type: 'string', enum: ['Active', 'Pending', 'Suspended', 'Cancelled'] },
				message: { type: 'string' },
				audit_log_id: { type: 'string' }
			},
			required: ['success', 'mandate_reference']
		}
	},

	'verenigingen.verenigingen_payments.utils.iban_validator.validate_iban': {
		args: {
			type: 'object',
			properties: {
				iban: { type: 'string', minLength: 15, maxLength: 34 },
				country_code: { type: 'string', pattern: '^[A-Z]{2}$' }
			},
			required: ['iban'],
			additionalProperties: false
		},
		response: {
			type: 'object',
			properties: {
				valid: { type: 'boolean' },
				country: { type: 'string' },
				bank_code: { type: 'string' },
				bank_name: { type: 'string' },
				branch_code: { type: 'string' },
				account_number: { type: 'string' },
				check_digits: { type: 'string' },
				formatted_iban: { type: 'string' },
				error: { type: 'string' }
			},
			required: ['valid', 'country', 'bank_code']
		}
	},

	'verenigingen.verenigingen_payments.utils.direct_debit_batch.create_dd_batch': {
		args: {
			type: 'object',
			properties: {
				collection_date: { type: 'string', format: 'date' },
				batch_type: { type: 'string', enum: ['FRST', 'RCUR', 'FNAL', 'OOFF'] },
				invoice_filters: {
					type: 'object',
					properties: {
						membership_type: { type: 'array', items: { type: 'string' } },
						due_date_range: {
							type: 'object',
							properties: {
								from: { type: 'string', format: 'date' },
								to: { type: 'string', format: 'date' }
							}
						},
						max_amount: { type: 'number', minimum: 0.01, maximum: 999999.99 }
					}
				},
				test_mode: { type: 'boolean', default: false }
			},
			required: ['collection_date', 'batch_type'],
			additionalProperties: false
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				batch_id: { type: 'string', pattern: '^DD-BATCH-\\d{8}-\\d{4}$' },
				transaction_count: { type: 'integer', minimum: 0 },
				total_amount: { type: 'number', minimum: 0 },
				status: { type: 'string', enum: ['Draft', 'Submitted', 'Processing', 'Completed', 'Failed', 'Cancelled'] },
				xml_file: { type: 'string' },
				validation_errors: {
					type: 'array',
					items: {
						type: 'object',
						properties: {
							invoice: { type: 'string' },
							error: { type: 'string' },
							severity: { type: 'string', enum: ['warning', 'error'] }
						}
					}
				}
			},
			required: ['success', 'batch_id', 'transaction_count', 'total_amount']
		}
	},

	// Mollie Payment APIs
	'verenigingen.verenigingen_payments.templates.pages.mollie_checkout.make_payment': {
		args: {
			type: 'object',
			properties: {
				data: {
					type: 'object',
					properties: {
						amount: {
							type: 'object',
							properties: {
								value: { type: 'string', pattern: '^[0-9]+\\.[0-9]{2}$' },
								currency: { type: 'string', pattern: '^[A-Z]{3}$', default: 'EUR' }
							},
							required: ['value', 'currency']
						},
						description: { type: 'string', minLength: 1, maxLength: 255 },
						metadata: {
							type: 'object',
							properties: {
								member_id: { type: 'string' },
								membership_type: { type: 'string' }
							}
						}
					},
					required: ['amount', 'description']
				},
				reference_doctype: { type: 'string', enum: ['Sales Invoice', 'Donation', 'Event Registration'] },
				reference_docname: { type: 'string', pattern: '^[A-Z\\-0-9]+$' },
				gateway_name: { type: 'string', default: 'Default' }
			},
			required: ['data', 'reference_doctype', 'reference_docname'],
			additionalProperties: false
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				payment_id: { type: 'string', pattern: '^tr_[A-Za-z0-9]+$' },
				checkout_url: { type: 'string', format: 'uri' },
				status: { type: 'string', enum: ['open', 'canceled', 'pending', 'paid', 'expired', 'failed'] },
				expires_at: { type: 'string', format: 'date-time' }
			},
			required: ['success', 'payment_id', 'checkout_url']
		}
	},

	'verenigingen.verenigingen_payments.integration.mollie_connector.test_mollie_connection': {
		args: {
			type: 'object',
			properties: {
				settings_name: { type: 'string' }
			},
			additionalProperties: false
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				status: { type: 'string' },
				message: { type: 'string' },
				api_key_valid: { type: 'boolean' },
				profile_id: { type: 'string' }
			},
			required: ['success', 'status']
		}
	},

	// Member Lifecycle APIs
	'verenigingen.verenigingen.doctype.member.member.process_payment': {
		args: {
			type: 'object',
			properties: {
				member_id: { type: 'string', pattern: '^(Assoc-)?Member-\\d{4}-\\d{2}-\\d{4}$' },
				payment_amount: { type: 'number', minimum: 0.01, maximum: 999999.99, multipleOf: 0.01 },
				payment_method: { type: 'string', enum: ['SEPA Direct Debit', 'Mollie', 'Bank Transfer', 'Cash', 'Other'] },
				payment_date: { type: 'string', format: 'date' },
				reference: { type: 'string', maxLength: 100 },
				invoice_id: { type: 'string', pattern: '^SI-\\d{4}-\\d{2}-\\d{4}$' },
				payment_gateway_id: { type: 'string' }
			},
			required: ['member_id', 'payment_amount', 'payment_method'],
			additionalProperties: false
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				payment_entry_id: { type: 'string', pattern: '^PE-\\d{4}-\\d{2}-\\d{4}$' },
				invoice_status: { type: 'string', enum: ['Paid', 'Partially Paid', 'Unpaid', 'Overdue', 'Cancelled'] },
				outstanding_amount: { type: 'number', minimum: 0 },
				payment_history_updated: { type: 'boolean' },
				member_status_updated: { type: 'boolean' },
				next_payment_due: { type: 'string', format: 'date' }
			},
			required: ['success', 'payment_entry_id', 'invoice_status']
		}
	},

	'verenigingen.verenigingen.doctype.member.member.create_member': {
		args: {
			type: 'object',
			properties: {
				first_name: { type: 'string', minLength: 1, maxLength: 50, pattern: '^[A-Za-z\\s\\-\']+$' },
				last_name: { type: 'string', minLength: 1, maxLength: 50, pattern: '^[A-Za-z\\s\\-\']+$' },
				tussenvoegsel: { type: 'string', maxLength: 15, pattern: '^(van|de|der|den|te|ten|tot|op|aan|in|onder|over|bij|voor|na|uit|vom|von|du|da|del|della|di|el|la|le|les|des)?( (van|de|der|den|te|ten|tot|op|aan|in|onder|over|bij|voor|na|uit|vom|von|du|da|del|della|di|el|la|le|les|des))*$' },
				email: { type: 'string', format: 'email' },
				birth_date: { type: 'string', format: 'date' },
				postal_code: { type: 'string', pattern: '^[1-9][0-9]{3}\\s?[A-Z]{2}$' },
				city: { type: 'string', minLength: 1, maxLength: 100 },
				phone: { type: 'string', pattern: '^(\\+31|0)[1-9][0-9]{8}$' },
				membership_type: { type: 'string', enum: ['Regular', 'Student', 'Senior', 'Family', 'Corporate', 'Honorary'] },
				chapter: { type: 'string' },
				preferred_language: { type: 'string', enum: ['nl', 'en', 'de', 'fr'], default: 'nl' }
			},
			required: ['first_name', 'last_name', 'email', 'birth_date'],
			additionalProperties: false
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				member_id: { type: 'string', pattern: '^(Assoc-)?Member-\\d{4}-\\d{2}-\\d{4}$' },
				customer_id: { type: 'string', pattern: '^(Assoc-)?Customer-\\d{4}-\\d{2}-\\d{4}$' },
				status: { type: 'string', enum: ['Pending', 'Active', 'Suspended', 'Terminated'] },
				member_since: { type: 'string', format: 'date' },
				next_invoice_date: { type: 'string', format: 'date' },
				validation_warnings: {
					type: 'array',
					items: {
						type: 'object',
						properties: {
							field: { type: 'string' },
							message: { type: 'string' },
							severity: { type: 'string', enum: ['info', 'warning', 'error'] }
						}
					}
				}
			},
			required: ['success', 'member_id', 'customer_id']
		}
	},

	'verenigingen.verenigingen.doctype.member.member.get_current_dues_schedule_details': {
		args: {
			type: 'object',
			properties: {
				member: { type: 'string', pattern: '^(Assoc-)?Member-\\d{4}-\\d{2}-\\d{4}$' }
			},
			required: ['member'],
			additionalProperties: false
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				schedule_id: { type: 'string', pattern: '^MDS-\\d{4}-\\d{2}-\\d{4}$' },
				dues_rate: { type: 'number', minimum: 0, maximum: 999999.99 },
				frequency: { type: 'string', enum: ['Monthly', 'Quarterly', 'Semi-annually', 'Annually'] },
				next_invoice_date: { type: 'string', format: 'date' },
				status: { type: 'string', enum: ['Active', 'Paused', 'Terminated'] },
				payment_method: { type: 'string', enum: ['SEPA Direct Debit', 'Mollie', 'Manual'] }
			},
			required: ['success']
		}
	},

	'verenigingen.verenigingen.doctype.member.member.update_member_status': {
		args: {
			type: 'object',
			properties: {
				member_id: { type: 'string', pattern: '^(Assoc-)?Member-\\d{4}-\\d{2}-\\d{4}$' },
				new_status: { type: 'string', enum: ['Active', 'Suspended', 'Terminated', 'Pending'] },
				reason: { type: 'string', maxLength: 500 },
				effective_date: { type: 'string', format: 'date' },
				termination_type: { type: 'string', enum: ['voluntary', 'involuntary', 'deceased', 'duplicate'] }
			},
			required: ['member_id', 'new_status'],
			additionalProperties: false
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				previous_status: { type: 'string' },
				new_status: { type: 'string' },
				effective_date: { type: 'string', format: 'date' },
				workflow_actions: {
					type: 'array',
					items: {
						type: 'object',
						properties: {
							action: { type: 'string' },
							status: { type: 'string' },
							timestamp: { type: 'string', format: 'date-time' }
						}
					}
				},
				audit_log_id: { type: 'string' }
			},
			required: ['success', 'previous_status', 'new_status']
		}
	},

	'verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban': {
		args: {
			type: 'object',
			properties: {
				iban: { type: 'string', pattern: STANDARD_PATTERNS.IBAN }
			},
			required: ['iban'],
			additionalProperties: false
		},
		response: {
			type: 'object',
			properties: {
				bic: { type: 'string', pattern: '^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$' },
				bank_name: { type: 'string' }
			},
			required: ['bic']
		}
	},

	'verenigingen.verenigingen.doctype.member.member.validate_mandate_creation': {
		args: {
			type: 'object',
			properties: {
				member: { type: 'string' },
				iban: { type: 'string', pattern: STANDARD_PATTERNS.IBAN },
				mandate_id: { type: 'string' }
			},
			required: ['member', 'iban'],
			additionalProperties: false
		},
		response: {
			type: 'object',
			properties: {
				valid: { type: 'boolean' },
				errors: { type: 'array', items: { type: 'string' } },
				warnings: { type: 'array', items: { type: 'string' } }
			},
			required: ['valid']
		}
	},

	// Chapter API Methods
	'verenigingen.verenigingen.doctype.chapter.chapter.assign_member_to_chapter_with_cleanup': {
		args: {
			type: 'object',
			properties: {
				member: { type: 'string' },
				chapter: { type: 'string' },
				note: { type: 'string' }
			},
			required: ['member', 'chapter'],
			additionalProperties: false
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				message: { type: 'string' },
				previous_chapters: { type: 'array' }
			},
			required: ['success']
		}
	},

	// Donation API Methods
	'verenigingen.templates.pages.donate.submit_donation': {
		args: {
			type: 'object',
			properties: {
				donor_name: { type: 'string', minLength: 1 },
				email: { type: 'string', format: 'email' },
				amount: { type: 'number', minimum: 1 },
				donation_type: { type: 'string', enum: ['one-time', 'recurring'] },
				anbi_consent: { type: 'boolean' }
			},
			required: ['donor_name', 'email', 'amount'],
			additionalProperties: true // Allow additional form fields
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				donation_id: { type: 'string' },
				payment_url: { type: 'string', format: 'uri' }
			},
			required: ['success']
		}
	},

	// Payment History APIs
	'verenigingen.verenigingen.doctype.member.member.get_payment_history': {
		args: {
			type: 'object',
			properties: {
				member_id: { type: 'string', pattern: '^(Assoc-)?Member-\\d{4}-\\d{2}-\\d{4}$' },
				date_range: {
					type: 'object',
					properties: {
						from: { type: 'string', format: 'date' },
						to: { type: 'string', format: 'date' }
					}
				},
				limit: { type: 'integer', minimum: 1, maximum: 1000, default: 50 }
			},
			required: ['member_id'],
			additionalProperties: false
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				total_count: { type: 'integer' },
				payment_history: {
					type: 'array',
					items: {
						type: 'object',
						properties: {
							date: { type: 'string', format: 'date' },
							amount: { type: 'number' },
							payment_method: { type: 'string' },
							status: { type: 'string', enum: ['Paid', 'Failed', 'Pending', 'Refunded'] },
							invoice_id: { type: 'string' },
							reference: { type: 'string' }
						}
					}
				}
			},
			required: ['success', 'total_count', 'payment_history']
		}
	},

	// Membership Dues Schedule APIs
	'verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule.create_dues_schedule': {
		args: {
			type: 'object',
			properties: {
				member: { type: 'string', pattern: '^(Assoc-)?Member-\\d{4}-\\d{2}-\\d{4}$' },
				membership_type: { type: 'string', enum: ['Regular', 'Student', 'Senior', 'Family', 'Corporate', 'Honorary'] },
				dues_rate: { type: 'number', minimum: 0, maximum: 999999.99, multipleOf: 0.01 },
				frequency: { type: 'string', enum: ['Monthly', 'Quarterly', 'Semi-annually', 'Annually'] },
				start_date: { type: 'string', format: 'date' },
				payment_method: { type: 'string', enum: ['SEPA Direct Debit', 'Mollie', 'Manual'] }
			},
			required: ['member', 'membership_type', 'dues_rate', 'frequency'],
			additionalProperties: false
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				schedule_id: { type: 'string', pattern: '^MDS-\\d{4}-\\d{2}-\\d{4}$' },
				next_invoice_date: { type: 'string', format: 'date' },
				annual_amount: { type: 'number', minimum: 0 },
				status: { type: 'string', enum: ['Active', 'Paused', 'Terminated'] }
			},
			required: ['success', 'schedule_id', 'next_invoice_date']
		}
	},

	// Bank Reconciliation APIs
	'verenigingen.verenigingen_payments.utils.sepa_reconciliation.import_bank_statement': {
		args: {
			type: 'object',
			properties: {
				bank_account: { type: 'string' },
				statement_data: { type: 'string', description: 'Base64 encoded CAMT.053 file or JSON' },
				auto_reconcile: { type: 'boolean', default: true },
				reconciliation_rules: {
					type: 'object',
					properties: {
						match_threshold: { type: 'number', minimum: 0, maximum: 1, default: 0.95 },
						date_tolerance_days: { type: 'integer', minimum: 0, maximum: 30, default: 3 }
					}
				}
			},
			required: ['bank_account', 'statement_data'],
			additionalProperties: false
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				transactions_imported: { type: 'integer' },
				reconciliation_status: {
					type: 'object',
					properties: {
						matched: { type: 'integer' },
						unmatched: { type: 'integer' },
						manual_review: { type: 'integer' }
					}
				},
				bank_transactions: {
					type: 'array',
					items: {
						type: 'object',
						properties: {
							transaction_id: { type: 'string' },
							date: { type: 'string', format: 'date' },
							amount: { type: 'number' },
							description: { type: 'string' },
							reference: { type: 'string' },
							matched_invoice: { type: 'string' },
							confidence_score: { type: 'number' }
						}
					}
				}
			},
			required: ['success', 'transactions_imported', 'reconciliation_status']
		}
	}
};

/**
 * Simple API Contract Validator with Performance Caching
 */
class SimpleAPIContractTester {
	constructor() {
		this.ajv = new Ajv({ allErrors: true });
		addFormats(this.ajv);

		// Performance optimization: Cache compiled validators with size limit
		this.compiledValidators = new Map();
		this.validationMetrics = new Map();
		this.MAX_CACHE_SIZE = 100; // Prevent memory leaks

		// Performance monitoring
		this.totalValidations = 0;
		this.cacheHits = 0;
		this.totalCompilationTime = 0;
		this.totalValidationTime = 0;
	}

	/**
     * Validate a frappe.call() against expected schema (with caching)
     */
	validateFrappeCall(callArgs) {
		const { method, args = {} } = callArgs;

		// Performance tracking
		const validationStartTime = performance.now();
		this.totalValidations++;

		if (!API_SCHEMAS[method]) {
			return {
				valid: false,
				errors: [{
					message: `No API schema defined for method: ${method}`,
					availableMethods: this.getAvailableMethods(),
					suggestion: this.findSimilarMethod(method)
				}],
				method,
				args,
				performance: {
					validationTime: performance.now() - validationStartTime,
					cacheHit: false,
					compilationTime: 0
				}
			};
		}

		// Use cached validator or compile new one
		let validator = this.compiledValidators.get(method);
		let compilationTime = 0;

		if (!validator) {
			const compilationStartTime = performance.now();
			const schema = API_SCHEMAS[method];
			validator = this.ajv.compile(schema.args);
			compilationTime = performance.now() - compilationStartTime;

			// Cache the compiled validator with size limit (LRU behavior)
			this._addToCache(method, validator);
			this.totalCompilationTime += compilationTime;

			// Initialize method metrics
			this.validationMetrics.set(method, {
				validations: 0,
				cacheHits: 0,
				totalValidationTime: 0,
				compilationTime
			});
		} else {
			this.cacheHits++;
			const methodMetrics = this.validationMetrics.get(method);
			methodMetrics.cacheHits++;
		}

		// Perform validation
		const isValid = validator(args);
		const validationTime = performance.now() - validationStartTime;

		// Update metrics
		const methodMetrics = this.validationMetrics.get(method);
		methodMetrics.validations++;
		methodMetrics.totalValidationTime += validationTime;
		this.totalValidationTime += validationTime;

		return {
			valid: isValid,
			errors: validator.errors || [],
			method,
			args,
			schema: API_SCHEMAS[method].args,
			performance: {
				validationTime,
				cacheHit: compilationTime === 0, // If no compilation time, it was cached
				compilationTime
			}
		};
	}

	/**
     * Generate test data that matches a schema
     */
	generateValidTestData(method) {
		if (!API_SCHEMAS[method]) {
			throw new Error(`No API schema defined for method: ${method}`);
		}

		const schema = API_SCHEMAS[method].args;
		const testData = {};

		if (schema.properties) {
			Object.entries(schema.properties).forEach(([key, propSchema]) => {
				if (schema.required && schema.required.includes(key)) {
					testData[key] = this.generateTestValue(propSchema);
				}
			});
		}

		return testData;
	}

	generateTestValue(schema) {
		switch (schema.type) {
			case 'string':
				// Member ID patterns
				if (schema.pattern && schema.pattern.includes('Member-\\d{4}-\\d{2}-\\d{4}')) {
					return 'Member-2024-01-0001';
				}
				// IBAN patterns (using standard pattern)
				if (schema.pattern === STANDARD_PATTERNS.IBAN
					|| (schema.pattern && (schema.pattern.includes('[A-Z]{2}[0-9]{2}[A-Z0-9]') || schema.pattern.includes('IBAN')))) {
					return 'NL91ABNA0417164300';
				}
				// BIC patterns
				if (schema.pattern && schema.pattern.includes('[A-Z]{6}[A-Z0-9]{2}')) {
					return 'ABNANL2A';
				}
				// Invoice ID patterns
				if (schema.pattern && schema.pattern.includes('SI-\\d{4}-\\d{2}-\\d{4}')) {
					return 'SI-2024-01-0001';
				}
				// Payment Entry patterns
				if (schema.pattern && schema.pattern.includes('PE-\\d{4}-\\d{2}-\\d{4}')) {
					return 'PE-2024-01-0001';
				}
				// SEPA Mandate patterns
				if (schema.pattern && schema.pattern.includes('SEPA-\\d{4}-\\d{2}-\\d{4}')) {
					return 'SEPA-2024-01-0001';
				}
				// Direct Debit Batch patterns
				if (schema.pattern && schema.pattern.includes('DD-BATCH-\\d{8}-\\d{4}')) {
					return 'DD-BATCH-20240101-0001';
				}
				// Mollie transaction patterns
				if (schema.pattern && schema.pattern.includes('tr_[A-Za-z0-9]+')) {
					return 'tr_WDqYK6vllg';
				}
				// Mollie amount format (decimal with 2 places)
				if (schema.pattern && schema.pattern.includes('^[0-9]+\\.[0-9]{2}$')) {
					return '25.00';
				}
				// Currency code (3 letter)
				if (schema.pattern && schema.pattern.includes('^[A-Z]{3}$')) {
					return 'EUR';
				}
				// Reference document names (uppercase, dashes, numbers)
				if (schema.pattern && schema.pattern.includes('^[A-Z\\-0-9]+$')) {
					return 'REF-DOC-001';
				}
				// Dutch postal codes
				if (schema.pattern && schema.pattern.includes('[1-9][0-9]{3}\\s?[A-Z]{2}')) {
					return '1012 AB';
				}
				// Dutch phone numbers
				if (schema.pattern && schema.pattern.includes('(\\+31|0)[1-9][0-9]{8}')) {
					return '0612345678';
				}
				// Name patterns
				if (schema.pattern && schema.pattern.includes('[A-Za-z\\s\\-\']+')) {
					return 'Test Name';
				}
				// Date format
				if (schema.format === 'date') {
					return '2024-01-15';
				}
				// Date-time format
				if (schema.format === 'date-time') {
					return '2024-01-15T10:30:00Z';
				}
				// Email format
				if (schema.format === 'email') {
					return 'test@example.org';
				}
				// URI format
				if (schema.format === 'uri') {
					return 'https://example.org/test';
				}
				// Enum values
				if (schema.enum) {
					return schema.enum[0];
				}
				// Handle minimum/maximum length constraints
				if (schema.minLength) {
					return 'a'.repeat(Math.max(schema.minLength, 1));
				}
				return 'test-value';
			case 'number':
				if (schema.minimum !== undefined) {
					return schema.minimum;
				}
				if (schema.multipleOf) {
					return schema.multipleOf;
				}
				return 1;
			case 'boolean':
				return true;
			case 'object':
				const obj = {};
				if (schema.properties) {
					Object.entries(schema.properties).forEach(([key, propSchema]) => {
						if (schema.required && schema.required.includes(key)) {
							obj[key] = this.generateTestValue(propSchema);
						}
					});
				}
				return obj;
			case 'array':
				return [];
			default:
				return null;
		}
	}

	/**
     * Validate API response against expected schema
     */
	validateAPIResponse(method, responseData) {
		const validationStartTime = performance.now();
		this.totalValidations++;

		if (!API_SCHEMAS[method]) {
			return {
				valid: false,
				errors: [{
					message: `No API schema defined for method: ${method}`,
					availableMethods: this.getAvailableMethods(),
					suggestion: this.findSimilarMethod(method)
				}],
				method,
				responseData,
				performance: {
					validationTime: performance.now() - validationStartTime,
					cacheHit: false,
					compilationTime: 0
				}
			};
		}

		if (!API_SCHEMAS[method].response) {
			return {
				valid: false,
				error: `No response schema defined for method: ${method}`,
				method,
				responseData
			};
		}

		// Use cached validator or compile new one
		const cacheKey = `${method}_response`;
		let validator = this.compiledValidators.get(cacheKey);
		let compilationTime = 0;

		if (!validator) {
			const compilationStartTime = performance.now();
			const schema = API_SCHEMAS[method].response;
			validator = this.ajv.compile(schema);
			compilationTime = performance.now() - compilationStartTime;

			// Cache the compiled validator
			this._addToCache(cacheKey, validator);
			this.totalCompilationTime += compilationTime;

			// Initialize method metrics
			this.validationMetrics.set(cacheKey, {
				validations: 0,
				cacheHits: 0,
				totalValidationTime: 0,
				compilationTime
			});
		} else {
			this.cacheHits++;
			const methodMetrics = this.validationMetrics.get(cacheKey);
			methodMetrics.cacheHits++;
		}

		// Perform validation
		const isValid = validator(responseData);
		const validationTime = performance.now() - validationStartTime;

		// Update metrics
		const methodMetrics = this.validationMetrics.get(cacheKey);
		methodMetrics.validations++;
		methodMetrics.totalValidationTime += validationTime;
		this.totalValidationTime += validationTime;

		return {
			valid: isValid,
			errors: validator.errors || [],
			method,
			responseData,
			schema: API_SCHEMAS[method].response,
			performance: {
				validationTime,
				cacheHit: compilationTime === 0,
				compilationTime
			}
		};
	}

	/**
     * Generic API validation for both request and response
     */
	validateAPICall(method, data, type = 'request') {
		if (type === 'request') {
			return this.validateFrappeCall({ method, args: data });
		} else if (type === 'response') {
			return this.validateAPIResponse(method, data);
		} else {
			throw new Error(`Invalid validation type: ${type}. Must be 'request' or 'response'`);
		}
	}

	/**
     * Get all available API methods for testing
     */
	getAvailableMethods() {
		return Object.keys(API_SCHEMAS);
	}

	/**
     * Get schema for a specific method
     */
	getMethodSchema(method) {
		return API_SCHEMAS[method];
	}

	/**
     * Find similar method name for better error messages
     */
	findSimilarMethod(method) {
		const availableMethods = this.getAvailableMethods();
		const methodParts = method.split('.');
		const lastPart = methodParts[methodParts.length - 1];

		// Find methods with similar endings
		const similar = availableMethods.filter(available => {
			const availableParts = available.split('.');
			const availableLastPart = availableParts[availableParts.length - 1];
			return availableLastPart === lastPart
                   || available.includes(lastPart)
                   || lastPart.includes(availableLastPart);
		});

		return similar.length > 0 ? similar[0] : null;
	}

	/**
     * Get performance metrics for monitoring
     */
	getPerformanceMetrics() {
		const cacheHitRate = this.totalValidations > 0
			? (this.cacheHits / this.totalValidations * 100).toFixed(2) : 0;

		const avgValidationTime = this.totalValidations > 0
			? (this.totalValidationTime / this.totalValidations).toFixed(3) : 0;

		const methodMetrics = {};
		this.validationMetrics.forEach((metrics, method) => {
			methodMetrics[method] = {
				...metrics,
				avgValidationTime: metrics.validations > 0
					? (metrics.totalValidationTime / metrics.validations).toFixed(3) : 0,
				cacheHitRate: metrics.validations > 0
					? `${(metrics.cacheHits / metrics.validations * 100).toFixed(2)}%` : '0%'
			};
		});

		return {
			overall: {
				totalValidations: this.totalValidations,
				totalCacheHits: this.cacheHits,
				cacheHitRate: `${cacheHitRate}%`,
				totalCompilationTime: `${this.totalCompilationTime.toFixed(3)}ms`,
				totalValidationTime: `${this.totalValidationTime.toFixed(3)}ms`,
				avgValidationTime: `${avgValidationTime}ms`,
				cachedValidators: this.compiledValidators.size
			},
			byMethod: methodMetrics
		};
	}

	/**
     * Clear cache and reset metrics (for testing)
     */
	/**
	 * Add validator to cache with LRU eviction to prevent memory leaks
	 * @private
	 */
	_addToCache(key, validator) {
		// If cache is at max size, remove oldest entry (LRU)
		if (this.compiledValidators.size >= this.MAX_CACHE_SIZE) {
			const oldestKey = this.compiledValidators.keys().next().value;
			this.compiledValidators.delete(oldestKey);
			this.validationMetrics.delete(oldestKey);
		}

		this.compiledValidators.set(key, validator);
	}

	clearCache() {
		this.compiledValidators.clear();
		this.validationMetrics.clear();
		this.totalValidations = 0;
		this.cacheHits = 0;
		this.totalCompilationTime = 0;
		this.totalValidationTime = 0;
	}
}

/**
 * Jest integration utilities
 */
function createSimpleAPIContractMatcher() {
	return {
		toMatchAPIContract(received, method) {
			const tester = new SimpleAPIContractTester();
			const result = tester.validateFrappeCall({
				method,
				args: received
			});

			if (result.valid) {
				return {
					message: () => `Expected ${method} NOT to match API contract`,
					pass: true
				};
			} else {
				const errors = result.errors.map(error =>
					`${error.instancePath} ${error.message}`
				).join('\n  ');

				return {
					message: () =>
						`Expected ${method} to match API contract.\n\n`
                        + `Validation errors:\n  ${errors}\n\n`
                        + `Received: ${JSON.stringify(received, null, 2)}\n`
                        + `Schema: ${JSON.stringify(result.schema, null, 2)}`,
					pass: false
				};
			}
		}
	};
}

module.exports = {
	API_SCHEMAS,
	SimpleAPIContractTester,
	createSimpleAPIContractMatcher
};
