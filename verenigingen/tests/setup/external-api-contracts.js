/**
 * @fileoverview External API Contract Definitions
 *
 * Defines API contract schemas for external service integrations including
 * eBoekhouden REST API and Mollie payment API. These contracts ensure
 * proper data formatting and validation for critical financial integrations.
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 */

const Ajv = require('ajv');
const addFormats = require('ajv-formats');

/**
 * eBoekhouden REST API Contract Schemas
 * Based on https://api.e-boekhouden.nl/swagger/v1/swagger.json
 */
const eBoekhoudentContracts = {
	// Customer/Relatie management
	'verenigingen.e_boekhouden.api.create_customer': {
		args: {
			type: 'object',
			required: ['customer_data'],
			properties: {
				customer_data: {
					type: 'object',
					required: ['Naam', 'Email'],
					properties: {
						Naam: { type: 'string', minLength: 1 },
						Email: { type: 'string', format: 'email' },
						Adres: { type: 'string' },
						Postcode: {
							type: 'string',
							pattern: '^[1-9][0-9]{3}\\s?[A-Za-z]{2}$' // Dutch postal code
						},
						Plaats: { type: 'string' },
						Telefoon: { type: 'string' },
						Mobiel: { type: 'string' },
						BTWNummer: {
							type: 'string',
							pattern: '^(NL)?[0-9]{9}B[0-9]{2}$' // Dutch VAT number
						},
						KvKNummer: {
							type: 'string',
							pattern: '^[0-9]{8}$' // Dutch Chamber of Commerce number
						},
						IBAN: {
							type: 'string',
							pattern: '^NL[0-9]{2}[A-Z]{4}[0-9]{10}$' // Dutch IBAN
						}
					}
				}
			}
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				customer_id: { type: 'string' },
				message: { type: 'string' }
			}
		}
	},

	// Invoice management
	'verenigingen.e_boekhouden.api.create_invoice': {
		args: {
			type: 'object',
			required: ['invoice_data'],
			properties: {
				invoice_data: {
					type: 'object',
					required: ['Relatiecode', 'Datum', 'Regels'],
					properties: {
						Relatiecode: { type: 'string', minLength: 1 },
						Datum: {
							type: 'string',
							format: 'date',
							pattern: '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
						},
						Factuurnummer: { type: 'string' },
						Betreft: { type: 'string' },
						Boekingsperiode: {
							type: 'string',
							pattern: '^[0-9]{4}(0[1-9]|1[0-2])$' // YYYYMM format
						},
						Regels: {
							type: 'array',
							minItems: 1,
							items: {
								type: 'object',
								required: ['Omschrijving', 'Aantal', 'Prijs'],
								properties: {
									Omschrijving: { type: 'string', minLength: 1 },
									Aantal: { type: 'number', minimum: 0 },
									Prijs: { type: 'number' },
									BTWPercentage: {
										type: 'number',
										enum: [0, 9, 21] // Dutch VAT rates
									},
									Grootboekrekening: {
										type: 'string',
										pattern: '^[0-9]{4,6}$'
									}
								}
							}
						}
					}
				}
			}
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				invoice_id: { type: 'string' },
				invoice_number: { type: 'string' },
				message: { type: 'string' }
			}
		}
	},

	// Payment processing
	'verenigingen.e_boekhouden.api.process_payment': {
		args: {
			type: 'object',
			required: ['payment_data'],
			properties: {
				payment_data: {
					type: 'object',
					required: ['Datum', 'Bedrag', 'Rekening'],
					properties: {
						Datum: {
							type: 'string',
							format: 'date',
							pattern: '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
						},
						Bedrag: {
							type: 'number',
							multipleOf: 0.01 // Euro cents precision
						},
						Rekening: {
							type: 'string',
							pattern: '^NL[0-9]{2}[A-Z]{4}[0-9]{10}$' // Dutch IBAN
						},
						Omschrijving: { type: 'string', minLength: 1 },
						TegenRekening: {
							type: 'string',
							pattern: '^[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{7,}$' // Any EU IBAN
						},
						Boekingsperiode: {
							type: 'string',
							pattern: '^[0-9]{4}(0[1-9]|1[0-2])$' // YYYYMM format
						}
					}
				}
			}
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				transaction_id: { type: 'string' },
				message: { type: 'string' }
			}
		}
	}
};

/**
 * Mollie Payment API Contract Schemas
 * Based on Mollie API v2 documentation
 */
const mollieContracts = {
	// Customer management
	'verenigingen.mollie_integration.create_customer': {
		args: {
			type: 'object',
			required: ['customer_data'],
			properties: {
				customer_data: {
					type: 'object',
					required: ['name', 'email'],
					properties: {
						name: { type: 'string', minLength: 1, maxLength: 255 },
						email: {
							type: 'string',
							format: 'email',
							maxLength: 320
						},
						locale: {
							type: 'string',
							enum: ['nl_NL', 'nl_BE', 'en_US', 'en_GB', 'de_DE', 'fr_FR']
						},
						metadata: {
							type: 'object',
							additionalProperties: { type: 'string' }
						}
					}
				}
			}
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				customer_id: {
					type: 'string',
					pattern: '^cst_[a-zA-Z0-9]{10,}$'
				},
				message: { type: 'string' }
			}
		}
	},

	// Subscription management
	'verenigingen.mollie_integration.create_subscription': {
		args: {
			type: 'object',
			required: ['subscription_data'],
			properties: {
				subscription_data: {
					type: 'object',
					required: ['customer_id', 'amount', 'interval', 'description'],
					properties: {
						customer_id: {
							type: 'string',
							pattern: '^cst_[a-zA-Z0-9]{10,}$'
						},
						amount: {
							type: 'object',
							required: ['currency', 'value'],
							properties: {
								currency: {
									type: 'string',
									enum: ['EUR', 'USD', 'GBP']
								},
								value: {
									type: 'string',
									pattern: '^[0-9]+\\.[0-9]{2}$' // e.g., "25.00"
								}
							}
						},
						interval: {
							type: 'string',
							enum: ['1 week', '2 weeks', '1 month', '3 months', '6 months', '12 months']
						},
						description: {
							type: 'string',
							minLength: 1,
							maxLength: 255
						},
						method: {
							type: 'array',
							items: {
								type: 'string',
								enum: ['directdebit', 'creditcard']
							}
						},
						webhookUrl: {
							type: 'string',
							format: 'uri'
						},
						metadata: {
							type: 'object',
							additionalProperties: { type: 'string' }
						}
					}
				}
			}
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				subscription_id: {
					type: 'string',
					pattern: '^sub_[a-zA-Z0-9]{10,}$'
				},
				status: {
					type: 'string',
					enum: ['pending', 'active', 'canceled', 'suspended', 'completed']
				},
				next_payment_date: {
					type: 'string',
					format: 'date'
				},
				message: { type: 'string' }
			}
		}
	},

	// Payment processing
	'verenigingen.mollie_integration.create_payment': {
		args: {
			type: 'object',
			required: ['payment_data'],
			properties: {
				payment_data: {
					type: 'object',
					required: ['amount', 'description', 'redirectUrl'],
					properties: {
						amount: {
							type: 'object',
							required: ['currency', 'value'],
							properties: {
								currency: {
									type: 'string',
									enum: ['EUR', 'USD', 'GBP']
								},
								value: {
									type: 'string',
									pattern: '^[0-9]+\\.[0-9]{2}$' // e.g., "25.00"
								}
							}
						},
						description: {
							type: 'string',
							minLength: 1,
							maxLength: 255
						},
						redirectUrl: {
							type: 'string',
							format: 'uri'
						},
						webhookUrl: {
							type: 'string',
							format: 'uri'
						},
						method: {
							type: 'string',
							enum: ['directdebit', 'creditcard', 'banktransfer', 'ideal', 'paypal']
						},
						customer_id: {
							type: 'string',
							pattern: '^cst_[a-zA-Z0-9]{10,}$'
						},
						metadata: {
							type: 'object',
							additionalProperties: { type: 'string' }
						},
						issuer: { type: 'string' }, // For iDEAL bank selection
						locale: {
							type: 'string',
							enum: ['nl_NL', 'nl_BE', 'en_US', 'en_GB', 'de_DE', 'fr_FR']
						}
					}
				}
			}
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				payment_id: {
					type: 'string',
					pattern: '^tr_[a-zA-Z0-9]{10,}$'
				},
				status: {
					type: 'string',
					enum: ['open', 'pending', 'authorized', 'expired', 'failed', 'canceled', 'paid']
				},
				checkout_url: {
					type: 'string',
					format: 'uri'
				},
				message: { type: 'string' }
			}
		}
	},

	// Webhook handling
	'verenigingen.mollie_integration.process_webhook': {
		args: {
			type: 'object',
			required: ['webhook_data'],
			properties: {
				webhook_data: {
					type: 'object',
					required: ['id'],
					properties: {
						id: {
							type: 'string',
							pattern: '^(tr_|sub_|cst_)[a-zA-Z0-9]{10,}$'
						}
					}
				}
			}
		},
		response: {
			type: 'object',
			properties: {
				success: { type: 'boolean' },
				processed: { type: 'boolean' },
				message: { type: 'string' }
			}
		}
	}
};

/**
 * Enhanced External API Contract Tester
 */
class ExternalAPIContractTester {
	constructor() {
		this.ajv = new Ajv({
			allErrors: true,
			verbose: true,
			strict: false
		});
		addFormats(this.ajv);

		// Combine all contract schemas
		this.contracts = {
			...eBoekhoudentContracts,
			...mollieContracts
		};

		// Compile all schemas
		this.compiledSchemas = {};
		Object.entries(this.contracts).forEach(([method, contract]) => {
			this.compiledSchemas[method] = {
				args: this.ajv.compile(contract.args),
				response: this.ajv.compile(contract.response)
			};
		});
	}

	/**
     * Validate API call arguments
     */
	validateArgs(method, args) {
		if (!this.compiledSchemas[method]) {
			return {
				valid: false,
				errors: [`Unknown API method: ${method}`]
			};
		}

		const validate = this.compiledSchemas[method].args;
		const valid = validate(args);

		return {
			valid,
			errors: valid ? [] : validate.errors.map(err => ({
				field: err.instancePath || err.dataPath,
				message: err.message,
				value: err.data
			}))
		};
	}

	/**
     * Validate API response
     */
	validateResponse(method, response) {
		if (!this.compiledSchemas[method]) {
			return {
				valid: false,
				errors: [`Unknown API method: ${method}`]
			};
		}

		const validate = this.compiledSchemas[method].response;
		const valid = validate(response);

		return {
			valid,
			errors: valid ? [] : validate.errors.map(err => ({
				field: err.instancePath || err.dataPath,
				message: err.message,
				value: err.data
			}))
		};
	}

	/**
     * Get all available API methods
     */
	getAvailableMethods() {
		return Object.keys(this.contracts);
	}

	/**
     * Get contract schema for specific method
     */
	getMethodSchema(method) {
		return this.contracts[method];
	}

	/**
     * Generate valid test data for a method
     */
	generateValidTestData(method) {
		const testDataGenerators = {
			// eBoekhouden test data
			'verenigingen.e_boekhouden.api.create_customer': () => ({
				customer_data: {
					Naam: 'Test Vereniging BV',
					Email: 'test@vereniging.nl',
					Adres: 'Teststraat 123',
					Postcode: '1012 AB',
					Plaats: 'Amsterdam',
					Telefoon: '020-1234567',
					BTWNummer: 'NL123456789B01',
					KvKNummer: '12345678',
					IBAN: 'NL91ABNA0417164300'
				}
			}),

			'verenigingen.e_boekhouden.api.create_invoice': () => ({
				invoice_data: {
					Relatiecode: 'REL001',
					Datum: '2024-07-15',
					Factuurnummer: 'INV2024001',
					Betreft: 'Lidmaatschap contributie',
					Boekingsperiode: '202407',
					Regels: [{
						Omschrijving: 'Jaarbijdrage 2024',
						Aantal: 1,
						Prijs: 25.00,
						BTWPercentage: 21,
						Grootboekrekening: '8000'
					}]
				}
			}),

			'verenigingen.e_boekhouden.api.process_payment': () => ({
				payment_data: {
					Datum: '2024-07-15',
					Bedrag: 25.00,
					Rekening: 'NL91ABNA0417164300',
					Omschrijving: 'Lidmaatschap betaling',
					TegenRekening: 'NL20INGB0001234567',
					Boekingsperiode: '202407'
				}
			}),

			// Mollie test data
			'verenigingen.mollie_integration.create_customer': () => ({
				customer_data: {
					name: 'Jan van der Berg',
					email: 'jan.van.der.berg@example.org',
					locale: 'nl_NL',
					metadata: {
						member_id: 'ASSOC-MEMBER-2025-001',
						chapter: 'Amsterdam'
					}
				}
			}),

			'verenigingen.mollie_integration.create_subscription': () => ({
				subscription_data: {
					customer_id: 'cst_stTC2WHAuS',
					amount: {
						currency: 'EUR',
						value: '25.00'
					},
					interval: '1 month',
					description: 'Monthly membership fee',
					method: ['directdebit'],
					webhookUrl: 'https://dev.veganisme.net/api/method/verenigingen.mollie_integration.process_webhook',
					metadata: {
						member_id: 'ASSOC-MEMBER-2025-001'
					}
				}
			}),

			'verenigingen.mollie_integration.create_payment': () => ({
				payment_data: {
					amount: {
						currency: 'EUR',
						value: '50.00'
					},
					description: 'One-time donation',
					redirectUrl: 'https://dev.veganisme.net/donation/success',
					webhookUrl: 'https://dev.veganisme.net/api/method/verenigingen.mollie_integration.process_webhook',
					method: 'ideal',
					locale: 'nl_NL',
					metadata: {
						donation_type: 'general',
						campaign: 'annual_drive'
					}
				}
			}),

			'verenigingen.mollie_integration.process_webhook': () => ({
				webhook_data: {
					id: 'tr_WDqYK6vllg'
				}
			})
		};

		const generator = testDataGenerators[method];
		if (!generator) {
			throw new Error(`No test data generator available for method: ${method}`);
		}

		return generator();
	}

	/**
     * Run comprehensive validation for all methods
     */
	validateAllMethods() {
		const results = {};

		this.getAvailableMethods().forEach(method => {
			try {
				const testData = this.generateValidTestData(method);
				const validation = this.validateArgs(method, testData);

				results[method] = {
					success: validation.valid,
					errors: validation.errors,
					testData
				};
			} catch (error) {
				results[method] = {
					success: false,
					errors: [error.message],
					testData: null
				};
			}
		});

		return results;
	}
}

module.exports = {
	ExternalAPIContractTester,
	eBoekhoudentContracts,
	mollieContracts
};
