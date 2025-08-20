/**
 * @fileoverview External API Contract Tests
 *
 * Tests for eBoekhouden and Mollie API integration contracts. These tests
 * validate that our API integration calls conform to the expected schemas
 * and handle Dutch business requirements correctly.
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 */

const { ExternalAPIContractTester } = require('../setup/external-api-contracts');

describe('External API Contracts', () => {
	let tester;

	beforeAll(() => {
		tester = new ExternalAPIContractTester();
	});

	describe('eBoekhouden API Contracts', () => {
		describe('Customer Management', () => {
			it('should validate correct customer creation data', () => {
				const validData = {
					customer_data: {
						Naam: 'Vereniging voor Duurzaamheid',
						Email: 'info@duurzaam.nl',
						Adres: 'Plantage Middenlaan 45',
						Postcode: '1018 DB',
						Plaats: 'Amsterdam',
						Telefoon: '020-5551234',
						BTWNummer: 'NL123456789B01',
						KvKNummer: '12345678',
						IBAN: 'NL91ABNA0417164300'
					}
				};

				const result = tester.validateArgs('verenigingen.e_boekhouden.api.create_customer', validData);
				expect(result.valid).toBe(true);
				expect(result.errors).toHaveLength(0);
			});

			it('should reject invalid Dutch postal code', () => {
				const invalidData = {
					customer_data: {
						Naam: 'Test Vereniging',
						Email: 'test@example.nl',
						Postcode: '12345' // Invalid format
					}
				};

				const result = tester.validateArgs('verenigingen.e_boekhouden.api.create_customer', invalidData);
				expect(result.valid).toBe(false);
				expect(result.errors.some(err => err.field.includes('Postcode'))).toBe(true);
			});

			it('should reject invalid Dutch IBAN', () => {
				const invalidData = {
					customer_data: {
						Naam: 'Test Vereniging',
						Email: 'test@example.nl',
						IBAN: 'GB82WEST12345698765432' // UK IBAN, not Dutch
					}
				};

				const result = tester.validateArgs('verenigingen.e_boekhouden.api.create_customer', invalidData);
				expect(result.valid).toBe(false);
				expect(result.errors.some(err => err.field.includes('IBAN'))).toBe(true);
			});

			it('should reject invalid Dutch VAT number', () => {
				const invalidData = {
					customer_data: {
						Naam: 'Test Vereniging',
						Email: 'test@example.nl',
						BTWNummer: 'INVALID123' // Invalid format
					}
				};

				const result = tester.validateArgs('verenigingen.e_boekhouden.api.create_customer', invalidData);
				expect(result.valid).toBe(false);
				expect(result.errors.some(err => err.field.includes('BTWNummer'))).toBe(true);
			});
		});

		describe('Invoice Management', () => {
			it('should validate correct invoice data with Dutch VAT rates', () => {
				const validData = {
					invoice_data: {
						Relatiecode: 'REL001',
						Datum: '2024-07-15',
						Factuurnummer: 'INV2024001',
						Betreft: 'Lidmaatschapsbijdrage Q3 2024',
						Boekingsperiode: '202407',
						Regels: [
							{
								Omschrijving: 'Kwartaalbijdrage lidmaatschap',
								Aantal: 1,
								Prijs: 25.00,
								BTWPercentage: 21, // Dutch high VAT rate
								Grootboekrekening: '8000'
							},
							{
								Omschrijving: 'Vrijstelling donatie',
								Aantal: 1,
								Prijs: 10.00,
								BTWPercentage: 0, // Tax-exempt
								Grootboekrekening: '8100'
							}
						]
					}
				};

				const result = tester.validateArgs('verenigingen.e_boekhouden.api.create_invoice', validData);
				expect(result.valid).toBe(true);
				expect(result.errors).toHaveLength(0);
			});

			it('should reject invalid Dutch VAT rate', () => {
				const invalidData = {
					invoice_data: {
						Relatiecode: 'REL001',
						Datum: '2024-07-15',
						Regels: [{
							Omschrijving: 'Test item',
							Aantal: 1,
							Prijs: 25.00,
							BTWPercentage: 19 // German VAT rate, not Dutch
						}]
					}
				};

				const result = tester.validateArgs('verenigingen.e_boekhouden.api.create_invoice', invalidData);
				expect(result.valid).toBe(false);
				expect(result.errors.some(err =>
					err.field.includes('BTWPercentage') || err.message.includes('enum')
				)).toBe(true);
			});

			it('should reject invalid date format', () => {
				const invalidData = {
					invoice_data: {
						Relatiecode: 'REL001',
						Datum: '15-07-2024', // DD-MM-YYYY instead of YYYY-MM-DD
						Regels: [{
							Omschrijving: 'Test item',
							Aantal: 1,
							Prijs: 25.00
						}]
					}
				};

				const result = tester.validateArgs('verenigingen.e_boekhouden.api.create_invoice', invalidData);
				expect(result.valid).toBe(false);
				expect(result.errors.some(err => err.field.includes('Datum'))).toBe(true);
			});

			it('should reject invalid booking period format', () => {
				const invalidData = {
					invoice_data: {
						Relatiecode: 'REL001',
						Datum: '2024-07-15',
						Boekingsperiode: '2024/07', // Invalid format
						Regels: [{
							Omschrijving: 'Test item',
							Aantal: 1,
							Prijs: 25.00
						}]
					}
				};

				const result = tester.validateArgs('verenigingen.e_boekhouden.api.create_invoice', invalidData);
				expect(result.valid).toBe(false);
				expect(result.errors.some(err => err.field.includes('Boekingsperiode'))).toBe(true);
			});
		});

		describe('Payment Processing', () => {
			it('should validate correct payment data', () => {
				const validData = {
					payment_data: {
						Datum: '2024-07-15',
						Bedrag: 25.50,
						Rekening: 'NL91ABNA0417164300',
						Omschrijving: 'SEPA incasso lidmaatschapsbijdrage',
						TegenRekening: 'NL20INGB0001234567',
						Boekingsperiode: '202407'
					}
				};

				const result = tester.validateArgs('verenigingen.e_boekhouden.api.process_payment', validData);
				expect(result.valid).toBe(true);
				expect(result.errors).toHaveLength(0);
			});

			it('should accept European IBAN formats for TegenRekening', () => {
				const validData = {
					payment_data: {
						Datum: '2024-07-15',
						Bedrag: 25.00,
						Rekening: 'NL91ABNA0417164300',
						Omschrijving: 'International transfer',
						TegenRekening: 'DE89370400440532013000', // German IBAN
						Boekingsperiode: '202407'
					}
				};

				const result = tester.validateArgs('verenigingen.e_boekhouden.api.process_payment', validData);
				expect(result.valid).toBe(true);
				expect(result.errors).toHaveLength(0);
			});
		});
	});

	describe('Mollie API Contracts', () => {
		describe('Customer Management', () => {
			it('should validate correct customer creation with Dutch locale', () => {
				const validData = {
					customer_data: {
						name: 'Jan van der Berg',
						email: 'jan.van.der.berg@vereniging.nl',
						locale: 'nl_NL',
						metadata: {
							member_id: 'ASSOC-MEMBER-2025-001',
							chapter: 'Amsterdam',
							membership_type: 'Regular'
						}
					}
				};

				const result = tester.validateArgs('verenigingen.mollie_integration.create_customer', validData);
				expect(result.valid).toBe(true);
				expect(result.errors).toHaveLength(0);
			});

			it('should reject invalid locale', () => {
				const invalidData = {
					customer_data: {
						name: 'Test User',
						email: 'test@example.com',
						locale: 'es_ES' // Spanish locale not supported
					}
				};

				const result = tester.validateArgs('verenigingen.mollie_integration.create_customer', invalidData);
				expect(result.valid).toBe(false);
				expect(result.errors.some(err => err.field.includes('locale'))).toBe(true);
			});

			it('should reject invalid email format', () => {
				const invalidData = {
					customer_data: {
						name: 'Test User',
						email: 'not-an-email'
					}
				};

				const result = tester.validateArgs('verenigingen.mollie_integration.create_customer', invalidData);
				expect(result.valid).toBe(false);
				expect(result.errors.some(err => err.field.includes('email'))).toBe(true);
			});
		});

		describe('Subscription Management', () => {
			it('should validate correct subscription with monthly interval', () => {
				const validData = {
					subscription_data: {
						customer_id: 'cst_stTC2WHAuS',
						amount: {
							currency: 'EUR',
							value: '25.00'
						},
						interval: '1 month',
						description: 'Maandelijkse lidmaatschapsbijdrage',
						method: ['directdebit'],
						webhookUrl: 'https://dev.veganisme.net/api/method/verenigingen.mollie_integration.process_webhook',
						metadata: {
							member_id: 'ASSOC-MEMBER-2025-001',
							billing_cycle: 'monthly'
						}
					}
				};

				const result = tester.validateArgs('verenigingen.mollie_integration.create_subscription', validData);
				expect(result.valid).toBe(true);
				expect(result.errors).toHaveLength(0);
			});

			it('should validate quarterly subscription interval', () => {
				const validData = {
					subscription_data: {
						customer_id: 'cst_stTC2WHAuS',
						amount: {
							currency: 'EUR',
							value: '75.00'
						},
						interval: '3 months', // Quarterly billing
						description: 'Kwartaalbijdrage lidmaatschap',
						method: ['directdebit']
					}
				};

				const result = tester.validateArgs('verenigingen.mollie_integration.create_subscription', validData);
				expect(result.valid).toBe(true);
			});

			it('should reject invalid customer ID format', () => {
				const invalidData = {
					subscription_data: {
						customer_id: 'invalid_id_format',
						amount: { currency: 'EUR', value: '25.00' },
						interval: '1 month',
						description: 'Test subscription'
					}
				};

				const result = tester.validateArgs('verenigingen.mollie_integration.create_subscription', invalidData);
				expect(result.valid).toBe(false);
				expect(result.errors.some(err => err.field.includes('customer_id'))).toBe(true);
			});

			it('should reject invalid amount format', () => {
				const invalidData = {
					subscription_data: {
						customer_id: 'cst_stTC2WHAuS',
						amount: {
							currency: 'EUR',
							value: '25' // Missing decimal places
						},
						interval: '1 month',
						description: 'Test subscription'
					}
				};

				const result = tester.validateArgs('verenigingen.mollie_integration.create_subscription', invalidData);
				expect(result.valid).toBe(false);
				expect(result.errors.some(err => err.field.includes('value'))).toBe(true);
			});

			it('should reject invalid subscription interval', () => {
				const invalidData = {
					subscription_data: {
						customer_id: 'cst_stTC2WHAuS',
						amount: { currency: 'EUR', value: '25.00' },
						interval: '2 months', // Not a valid interval
						description: 'Test subscription'
					}
				};

				const result = tester.validateArgs('verenigingen.mollie_integration.create_subscription', invalidData);
				expect(result.valid).toBe(false);
				expect(result.errors.some(err => err.field.includes('interval'))).toBe(true);
			});
		});

		describe('Payment Processing', () => {
			it('should validate one-time donation payment', () => {
				const validData = {
					payment_data: {
						amount: {
							currency: 'EUR',
							value: '50.00'
						},
						description: 'Eenmalige donatie klimaatactie',
						redirectUrl: 'https://dev.veganisme.net/donation/success',
						webhookUrl: 'https://dev.veganisme.net/api/method/verenigingen.mollie_integration.process_webhook',
						method: 'ideal',
						locale: 'nl_NL',
						metadata: {
							donation_type: 'climate_action',
							campaign: 'annual_drive_2024',
							anonymous: 'false'
						}
					}
				};

				const result = tester.validateArgs('verenigingen.mollie_integration.create_payment', validData);
				expect(result.valid).toBe(true);
				expect(result.errors).toHaveLength(0);
			});

			it('should validate credit card payment with customer', () => {
				const validData = {
					payment_data: {
						amount: { currency: 'EUR', value: '25.00' },
						description: 'Membership fee payment',
						redirectUrl: 'https://dev.veganisme.net/payment/success',
						method: 'creditcard',
						customer_id: 'cst_stTC2WHAuS',
						locale: 'en_GB' // English for international member
					}
				};

				const result = tester.validateArgs('verenigingen.mollie_integration.create_payment', validData);
				expect(result.valid).toBe(true);
			});

			it('should reject invalid payment method', () => {
				const invalidData = {
					payment_data: {
						amount: { currency: 'EUR', value: '25.00' },
						description: 'Test payment',
						redirectUrl: 'https://example.com/success',
						method: 'bitcoin' // Not a supported method
					}
				};

				const result = tester.validateArgs('verenigingen.mollie_integration.create_payment', invalidData);
				expect(result.valid).toBe(false);
				expect(result.errors.some(err => err.field.includes('method'))).toBe(true);
			});

			it('should reject invalid URL format', () => {
				const invalidData = {
					payment_data: {
						amount: { currency: 'EUR', value: '25.00' },
						description: 'Test payment',
						redirectUrl: 'not-a-url'
					}
				};

				const result = tester.validateArgs('verenigingen.mollie_integration.create_payment', invalidData);
				expect(result.valid).toBe(false);
				expect(result.errors.some(err => err.field.includes('redirectUrl'))).toBe(true);
			});
		});

		describe('Webhook Processing', () => {
			it('should validate payment webhook data', () => {
				const validData = {
					webhook_data: {
						id: 'tr_WDqYK6vllg' // Payment transaction ID
					}
				};

				const result = tester.validateArgs('verenigingen.mollie_integration.process_webhook', validData);
				expect(result.valid).toBe(true);
				expect(result.errors).toHaveLength(0);
			});

			it('should validate subscription webhook data', () => {
				const validData = {
					webhook_data: {
						id: 'sub_rVKGtNd6s3' // Subscription ID
					}
				};

				const result = tester.validateArgs('verenigingen.mollie_integration.process_webhook', validData);
				expect(result.valid).toBe(true);
			});

			it('should validate customer webhook data', () => {
				const validData = {
					webhook_data: {
						id: 'cst_stTC2WHAuS' // Customer ID
					}
				};

				const result = tester.validateArgs('verenigingen.mollie_integration.process_webhook', validData);
				expect(result.valid).toBe(true);
			});

			it('should reject invalid webhook ID format', () => {
				const invalidData = {
					webhook_data: {
						id: 'invalid_format_123'
					}
				};

				const result = tester.validateArgs('verenigingen.mollie_integration.process_webhook', invalidData);
				expect(result.valid).toBe(false);
				expect(result.errors.some(err => err.field.includes('id'))).toBe(true);
			});
		});
	});

	describe('Test Data Generation', () => {
		it('should generate valid test data for all eBoekhouden methods', () => {
			const eBoekhoudentMethods = tester.getAvailableMethods().filter(method =>
				method.includes('e_boekhouden'));

			eBoekhoudentMethods.forEach(method => {
				const testData = tester.generateValidTestData(method);
				const result = tester.validateArgs(method, testData);

				expect(result.valid).toBe(true);
				expect(testData).toBeDefined();
			});
		});

		it('should generate valid test data for all Mollie methods', () => {
			const mollieMethods = tester.getAvailableMethods().filter(method =>
				method.includes('mollie_integration'));

			mollieMethods.forEach(method => {
				const testData = tester.generateValidTestData(method);
				const result = tester.validateArgs(method, testData);

				expect(result.valid).toBe(true);
				expect(testData).toBeDefined();
			});
		});

		it('should generate Dutch-compliant test data', () => {
			const customerData = tester.generateValidTestData('verenigingen.e_boekhouden.api.create_customer');

			// Verify Dutch postal code format
			expect(customerData.customer_data.Postcode).toMatch(/^[1-9][0-9]{3}\s[A-Z]{2}$/);

			// Verify Dutch IBAN format
			expect(customerData.customer_data.IBAN).toMatch(/^NL[0-9]{2}[A-Z]{4}[0-9]{10}$/);

			// Verify Dutch VAT number format
			expect(customerData.customer_data.BTWNummer).toMatch(/^NL[0-9]{9}B[0-9]{2}$/);
		});
	});

	describe('Comprehensive Validation', () => {
		it('should validate all methods successfully', () => {
			const results = tester.validateAllMethods();
			const methods = Object.keys(results);

			expect(methods.length).toBeGreaterThan(5);

			// All methods should have successful validation
			methods.forEach(method => {
				expect(results[method].success).toBe(true);
				expect(results[method].errors).toHaveLength(0);
				expect(results[method].testData).toBeDefined();
			});
		});

		it('should cover both eBoekhouden and Mollie integrations', () => {
			const methods = tester.getAvailableMethods();

			const eBoekhoudentMethods = methods.filter(m => m.includes('e_boekhouden'));
			const mollieMethods = methods.filter(m => m.includes('mollie_integration'));

			expect(eBoekhoudentMethods.length).toBeGreaterThanOrEqual(3);
			expect(mollieMethods.length).toBeGreaterThanOrEqual(4);
		});

		it('should provide detailed schema information', () => {
			const customerSchema = tester.getMethodSchema('verenigingen.e_boekhouden.api.create_customer');

			expect(customerSchema).toBeDefined();
			expect(customerSchema.args).toBeDefined();
			expect(customerSchema.response).toBeDefined();
			expect(customerSchema.args.properties.customer_data.required).toContain('Naam');
			expect(customerSchema.args.properties.customer_data.required).toContain('Email');
		});
	});
});
