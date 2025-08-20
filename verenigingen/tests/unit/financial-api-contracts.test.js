/**
 * @fileoverview Financial API Contract Tests
 *
 * Comprehensive tests for SEPA, Mollie, and Member financial operation API contracts.
 * Tests validate parameter schemas, response formats, and business rule compliance.
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 */

const { SimpleAPIContractTester } = require('../setup/api-contract-simple');

describe('Financial API Contract Tests', () => {
	let tester;

	beforeEach(() => {
		tester = new SimpleAPIContractTester();
	});

	describe('SEPA Mandate APIs', () => {
		describe('create_sepa_mandate', () => {
			const apiName = 'verenigingen.verenigingen_payments.utils.sepa_mandate.create_sepa_mandate';

			test('validates valid SEPA mandate creation request', () => {
				const validRequest = {
					member: 'Assoc-Member-2024-07-0001',
					iban: 'NL91ABNA0417164300',
					bic: 'ABNANL2A',
					mandate_type: 'RCUR',
					debtor_name: 'Jan de Vries'
				};

				const result = tester.validateAPICall(apiName, validRequest, 'request');
				expect(result.valid).toBe(true);
				expect(result.errors).toHaveLength(0);
			});

			test('rejects invalid IBAN format', () => {
				const invalidRequest = {
					member: 'Assoc-Member-2024-07-0001',
					iban: 'INVALID_IBAN',
					bic: 'ABNANL2A',
					debtor_name: 'Jan de Vries'
				};

				const result = tester.validateAPICall(apiName, invalidRequest, 'request');
				expect(result.valid).toBe(false);
				expect(result.errors).toContainEqual(
					expect.objectContaining({
						instancePath: '/iban',
						message: expect.stringMatching(/pattern/)
					})
				);
			});

			test('validates valid SEPA mandate response', () => {
				const validResponse = {
					success: true,
					mandate_reference: 'SEPA-2024-07-0001',
					status: 'Active',
					message: 'Mandate created successfully',
					audit_log_id: 'AL-2024-001'
				};

				const result = tester.validateAPICall(apiName, validResponse, 'response');
				expect(result.valid).toBe(true);
				expect(result.errors).toHaveLength(0);
			});

			test('rejects response missing required fields', () => {
				const invalidResponse = {
					success: true
					// Missing mandate_reference
				};

				const result = tester.validateAPICall(apiName, invalidResponse, 'response');
				expect(result.valid).toBe(false);
				expect(result.errors).toContainEqual(
					expect.objectContaining({
						instancePath: '',
						message: 'must have required property \'mandate_reference\''
					})
				);
			});

			test('validates Dutch IBAN specifically', () => {
				const dutchIbanRequest = {
					member: 'Member-2024-01-0001',
					iban: 'NL20INGB0001234567',
					bic: 'INGBNL2A',
					debtor_name: 'Anna van der Berg'
				};

				const result = tester.validateAPICall(apiName, dutchIbanRequest, 'request');
				expect(result.valid).toBe(true);
			});
		});

		describe('validate_iban', () => {
			const apiName = 'verenigingen.verenigingen_payments.utils.iban_validator.validate_iban';

			test('validates IBAN validation request', () => {
				const validRequest = {
					iban: 'BE71096123456769',
					country_code: 'BE'
				};

				const result = tester.validateAPICall(apiName, validRequest, 'request');
				expect(result.valid).toBe(true);
			});

			test('validates IBAN validation response for valid IBAN', () => {
				const validResponse = {
					valid: true,
					country: 'Netherlands',
					bank_code: 'ABNA',
					bank_name: 'ABN AMRO Bank',
					branch_code: '0417',
					account_number: '164300',
					check_digits: '91',
					formatted_iban: 'NL91 ABNA 0417 1643 00'
				};

				const result = tester.validateAPICall(apiName, validResponse, 'response');
				expect(result.valid).toBe(true);
			});

			test('validates IBAN validation response for invalid IBAN', () => {
				const invalidIbanResponse = {
					valid: false,
					country: 'Unknown',
					bank_code: '',
					error: 'Invalid IBAN check digits'
				};

				const result = tester.validateAPICall(apiName, invalidIbanResponse, 'response');
				expect(result.valid).toBe(true);
			});
		});

		describe('create_dd_batch', () => {
			const apiName = 'verenigingen.verenigingen_payments.utils.direct_debit_batch.create_dd_batch';

			test('validates direct debit batch creation request', () => {
				const validRequest = {
					collection_date: '2024-07-15',
					batch_type: 'RCUR',
					invoice_filters: {
						membership_type: ['Regular', 'Student'],
						due_date_range: {
							from: '2024-06-01',
							to: '2024-06-30'
						},
						max_amount: 100.00
					},
					test_mode: true
				};

				const result = tester.validateAPICall(apiName, validRequest, 'request');
				expect(result.valid).toBe(true);
			});

			test('validates DD batch response with validation errors', () => {
				const responseWithErrors = {
					success: true,
					batch_id: 'DD-BATCH-20240715-0001',
					transaction_count: 48,
					total_amount: 1200.00,
					status: 'Draft',
					xml_file: '/path/to/batch.xml',
					validation_errors: [
						{
							invoice: 'SI-2024-001',
							error: 'No valid SEPA mandate',
							severity: 'error'
						},
						{
							invoice: 'SI-2024-002',
							error: 'Amount exceeds mandate limit',
							severity: 'warning'
						}
					]
				};

				const result = tester.validateAPICall(apiName, responseWithErrors, 'response');
				expect(result.valid).toBe(true);
			});
		});
	});

	describe('Mollie Payment APIs', () => {
		describe('make_payment', () => {
			const apiName = 'verenigingen.verenigingen_payments.templates.pages.mollie_checkout.make_payment';

			test('validates Mollie payment creation request', () => {
				const validRequest = {
					data: {
						amount: {
							value: '25.00',
							currency: 'EUR'
						},
						description: 'Membership dues payment',
						metadata: {
							member_id: 'Member-2024-01-0001',
							membership_type: 'Regular'
						}
					},
					reference_doctype: 'Sales Invoice',
					reference_docname: 'SI-2024-001',
					gateway_name: 'Mollie'
				};

				const result = tester.validateAPICall(apiName, validRequest, 'request');
				expect(result.valid).toBe(true);
			});

			test('rejects invalid amount format', () => {
				const invalidRequest = {
					data: {
						amount: {
							value: '25.5', // Should be 25.50
							currency: 'EUR'
						},
						description: 'Membership dues'
					},
					reference_doctype: 'Sales Invoice',
					reference_docname: 'SI-2024-001'
				};

				const result = tester.validateAPICall(apiName, invalidRequest, 'request');
				expect(result.valid).toBe(false);
				expect(result.errors).toContainEqual(
					expect.objectContaining({
						instancePath: '/data/amount/value',
						message: expect.stringMatching(/pattern/)
					})
				);
			});

			test('validates Mollie payment response', () => {
				const validResponse = {
					success: true,
					payment_id: 'tr_WDqYK6vllg',
					checkout_url: 'https://www.mollie.com/payscreen/select-method/WDqYK6vllg',
					status: 'open',
					expires_at: '2024-07-15T14:30:00Z'
				};

				const result = tester.validateAPICall(apiName, validResponse, 'response');
				expect(result.valid).toBe(true);
			});
		});

		describe('test_mollie_connection', () => {
			const apiName = 'verenigingen.verenigingen_payments.integration.mollie_connector.test_mollie_connection';

			test('validates connection test response success', () => {
				const successResponse = {
					success: true,
					status: 'connected',
					message: 'Successfully connected to Mollie API',
					api_key_valid: true,
					profile_id: 'pfl_QkEhN94Ba'
				};

				const result = tester.validateAPICall(apiName, successResponse, 'response');
				expect(result.valid).toBe(true);
			});

			test('validates connection test response failure', () => {
				const failureResponse = {
					success: false,
					status: 'failed',
					message: 'Invalid API key provided'
				};

				const result = tester.validateAPICall(apiName, failureResponse, 'response');
				expect(result.valid).toBe(true);
			});
		});
	});

	describe('Member Lifecycle APIs', () => {
		describe('create_member', () => {
			const apiName = 'verenigingen.verenigingen.doctype.member.member.create_member';

			test('validates complete member creation request', () => {
				const validRequest = {
					first_name: 'Jan',
					last_name: 'Janssen',
					tussenvoegsel: 'van der',
					email: 'jan.vanderjanssen@example.nl',
					birth_date: '1985-06-15',
					postal_code: '1012 AB',
					city: 'Amsterdam',
					phone: '0612345678',
					membership_type: 'Regular',
					chapter: 'Amsterdam',
					preferred_language: 'nl'
				};

				const result = tester.validateAPICall(apiName, validRequest, 'request');
				expect(result.valid).toBe(true);
			});

			test('validates Dutch postal code format', () => {
				const validRequest = {
					first_name: 'Marie',
					last_name: 'de Boer',
					email: 'marie.deboer@example.nl',
					birth_date: '1992-03-20',
					postal_code: '2511CV' // Without space
				};

				const result = tester.validateAPICall(apiName, validRequest, 'request');
				expect(result.valid).toBe(true);
			});

			test('rejects invalid Dutch postal code', () => {
				const invalidRequest = {
					first_name: 'Test',
					last_name: 'User',
					email: 'test@example.nl',
					birth_date: '1990-01-01',
					postal_code: '12345' // Invalid format
				};

				const result = tester.validateAPICall(apiName, invalidRequest, 'request');
				expect(result.valid).toBe(false);
				expect(result.errors).toContainEqual(
					expect.objectContaining({
						instancePath: '/postal_code',
						message: expect.stringMatching(/pattern/)
					})
				);
			});

			test('validates member creation response with warnings', () => {
				const responseWithWarnings = {
					success: true,
					member_id: 'Member-2024-07-0050',
					customer_id: 'Customer-2024-07-0050',
					status: 'Active',
					member_since: '2024-07-15',
					next_invoice_date: '2024-08-01',
					validation_warnings: [
						{
							field: 'phone',
							message: 'Phone number format could not be verified',
							severity: 'warning'
						}
					]
				};

				const result = tester.validateAPICall(apiName, responseWithWarnings, 'response');
				expect(result.valid).toBe(true);
			});
		});

		describe('process_payment', () => {
			const apiName = 'verenigingen.verenigingen.doctype.member.member.process_payment';

			test('validates payment processing request', () => {
				const validRequest = {
					member_id: 'Member-2024-01-0001',
					payment_amount: 25.00,
					payment_method: 'SEPA Direct Debit',
					payment_date: '2024-07-15',
					reference: 'SEPA-DD-240715-001',
					invoice_id: 'SI-2024-07-0001'
				};

				const result = tester.validateAPICall(apiName, validRequest, 'request');
				expect(result.valid).toBe(true);
			});

			test('validates payment processing response', () => {
				const validResponse = {
					success: true,
					payment_entry_id: 'PE-2024-07-0001',
					invoice_status: 'Paid',
					outstanding_amount: 0.00,
					payment_history_updated: true,
					member_status_updated: false,
					next_payment_due: '2024-08-15'
				};

				const result = tester.validateAPICall(apiName, validResponse, 'response');
				expect(result.valid).toBe(true);
			});
		});

		describe('get_payment_history', () => {
			const apiName = 'verenigingen.verenigingen.doctype.member.member.get_payment_history';

			test('validates payment history request with filters', () => {
				const validRequest = {
					member_id: 'Member-2024-01-0001',
					date_range: {
						from: '2024-01-01',
						to: '2024-06-30'
					},
					limit: 25
				};

				const result = tester.validateAPICall(apiName, validRequest, 'request');
				expect(result.valid).toBe(true);
			});

			test('validates payment history response', () => {
				const validResponse = {
					success: true,
					total_count: 6,
					payment_history: [
						{
							date: '2024-06-15',
							amount: 25.00,
							payment_method: 'SEPA Direct Debit',
							status: 'Paid',
							invoice_id: 'SI-2024-06-0001',
							reference: 'SEPA-DD-001'
						},
						{
							date: '2024-05-15',
							amount: 25.00,
							payment_method: 'Mollie',
							status: 'Failed',
							invoice_id: 'SI-2024-05-0002',
							reference: 'tr_failure123'
						}
					]
				};

				const result = tester.validateAPICall(apiName, validResponse, 'response');
				expect(result.valid).toBe(true);
			});
		});
	});

	describe('Performance and Caching', () => {
		test('validates caching works correctly', () => {
			const apiName = 'verenigingen.verenigingen_payments.utils.iban_validator.validate_iban';
			const validRequest = { iban: 'NL91ABNA0417164300' };

			// First call
			const result1 = tester.validateAPICall(apiName, validRequest, 'request');
			expect(result1.valid).toBe(true);

			// Second call should use cache
			const result2 = tester.validateAPICall(apiName, validRequest, 'request');
			expect(result2.valid).toBe(true);

			// Check metrics show cache usage
			const metrics = tester.getPerformanceMetrics();
			const cacheHitRate = parseFloat(metrics.overall.cacheHitRate);
			expect(cacheHitRate).toBeGreaterThan(0);
		});

		test('measures validation performance', () => {
			const apiName = 'verenigingen.verenigingen.doctype.member.member.create_member';
			const validRequest = {
				first_name: 'Performance',
				last_name: 'Test',
				email: 'perf@test.nl',
				birth_date: '1990-01-01'
			};

			const startTime = performance.now();
			const result = tester.validateAPICall(apiName, validRequest, 'request');
			const endTime = performance.now();

			expect(result.valid).toBe(true);
			expect(endTime - startTime).toBeLessThan(100); // Should be very fast with caching
		});
	});

	describe('Error Handling and Edge Cases', () => {
		test('handles malformed schema gracefully', () => {
			const result = tester.validateAPICall('non.existent.api', {}, 'request');
			expect(result.valid).toBe(false);
			expect(result.errors[0].message).toContain('No API schema defined for method');
		});

		test('validates complex nested objects', () => {
			const apiName = 'verenigingen.verenigingen_payments.utils.sepa_reconciliation.import_bank_statement';
			const complexRequest = {
				bank_account: 'NL-Bank-Account-001',
				statement_data: 'base64encodeddata==',
				auto_reconcile: true,
				reconciliation_rules: {
					match_threshold: 0.85,
					date_tolerance_days: 5
				}
			};

			const result = tester.validateAPICall(apiName, complexRequest, 'request');
			expect(result.valid).toBe(true);
		});

		test('validates comprehensive reconciliation response', () => {
			const apiName = 'verenigingen.verenigingen_payments.utils.sepa_reconciliation.import_bank_statement';
			const complexResponse = {
				success: true,
				transactions_imported: 25,
				reconciliation_status: {
					matched: 22,
					unmatched: 2,
					manual_review: 1
				},
				bank_transactions: [
					{
						transaction_id: 'TXN-001',
						date: '2024-07-15',
						amount: 25.00,
						description: 'Membership payment',
						reference: 'REF-001',
						matched_invoice: 'SI-2024-001',
						confidence_score: 0.95
					}
				]
			};

			const result = tester.validateAPICall(apiName, complexResponse, 'response');
			expect(result.valid).toBe(true);
		});
	});
});
