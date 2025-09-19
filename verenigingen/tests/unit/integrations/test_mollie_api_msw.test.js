/**
 * @fileoverview Mollie API Integration Tests with MSW
 *
 * Comprehensive testing of Mollie API integration using Mock Service Worker (MSW)
 * to simulate real HTTP requests and responses. This approach provides better
 * integration testing compared to mocking the HTTP client directly.
 *
 * Test Coverage:
 * - Payment creation and status checking
 * - Balance retrieval and listing
 * - Settlement processing
 * - Error handling scenarios
 * - Network condition simulation
 * - Dutch SEPA compliance validation
 *
 * @author Verenigingen Development Team
 * @version 2025-08-26
 */

const {
	setupTestMocks,
	cleanupTestMocks
} = require('../../setup/frappe-mocks');
const {
	setupMSW,
	resetMSW,
	teardownMSW,
	server
} = require('../../setup/msw-setup');
const {
	mollieHandlers,
	errorHandlers,
	networkHandlers,
	generateMolliePayment,
	generateMollieBalance
} = require('../../setup/msw-handlers');
const { rest } = require('msw');

// Initialize test environment
setupTestMocks();

/**
 * Mock Mollie Base Client for testing
 * Simulates the actual client behavior for testing purposes
 */
class TestMollieClient {
	constructor(apiKey = 'test_api_key') {
		this.apiKey = apiKey;
		this.baseUrl = 'https://api.mollie.com/v2';
	}

	/**
   * Make HTTP request using fetch (which MSW will intercept)
   */
	async request(method, endpoint, data = null) {
		const url = `${this.baseUrl}${endpoint}`;
		const options = {
			method,
			headers: {
				Authorization: `Bearer ${this.apiKey}`,
				'Content-Type': 'application/json'
			}
		};

		if (data && (method === 'POST' || method === 'PATCH')) {
			options.body = JSON.stringify(data);
		}

		const response = await fetch(url, options);

		if (!response.ok) {
			let errorData;
			try {
				errorData = await response.json();
			} catch (e) {
				errorData = { detail: 'API request failed', status: response.status };
			}
			const error = new Error(errorData.detail || 'API request failed');
			error.status = response.status;
			error.data = errorData;
			throw error;
		}

		return response.json();
	}

	// Payment methods
	async createPayment(amount, currency, description, metadata = {}) {
		return this.request('POST', '/payments', {
			amount: { value: amount, currency },
			description,
			metadata,
			redirectUrl: 'https://example.com/success',
			webhookUrl: 'https://example.com/webhook'
		});
	}

	async getPayment(paymentId) {
		return this.request('GET', `/payments/${paymentId}`);
	}

	// Balance methods
	async getBalance(balanceId = 'primary') {
		return this.request('GET', `/balances/${balanceId}`);
	}

	async listBalances() {
		return this.request('GET', '/balances');
	}

	// Settlement methods
	async getSettlement(settlementId) {
		return this.request('GET', `/settlements/${settlementId}`);
	}

	async listSettlements(params = {}) {
		const queryString = Object.entries(params)
			.map(([key, value]) => `${key}=${encodeURIComponent(value)}`)
			.join('&');
		const endpoint = queryString
			? `/settlements?${queryString}`
			: '/settlements';
		return this.request('GET', endpoint);
	}

	// Test connectivity
	async testConnection() {
		return this.request('GET', '/methods?limit=1');
	}
}

describe('Mollie API Integration with MSW', () => {
	let mollieClient;

	beforeAll(() => {
		setupMSW();
		mollieClient = new TestMollieClient('test_api_key_12345');
	});

	beforeEach(() => {
		cleanupTestMocks();
		setupTestMocks();
	});

	afterEach(() => {
		cleanupTestMocks();
		resetMSW();
	});

	afterAll(() => {
		teardownMSW();
	});

	describe('Payment Operations', () => {
		it('should create a payment successfully', async () => {
			const paymentData = await mollieClient.createPayment(
				'25.00',
				'EUR',
				'Membership dues payment',
				{ member_id: 'Assoc-Member-2024-001' }
			);

			expect(paymentData).toHaveProperty('resource', 'payment');
			expect(paymentData).toHaveProperty('id');
			expect(paymentData.id).toMatch(/^tr_test_/);
			expect(paymentData.status).toBe('open');
			expect(paymentData.amount.value).toBe('25.00');
			expect(paymentData.amount.currency).toBe('EUR');
			expect(paymentData.description).toBe('Membership dues payment');
			expect(paymentData._links.self.href).toContain(
				'https://api.mollie.com/v2/payments/'
			);
		});

		it('should get payment status - paid', async () => {
			const paymentId = 'tr_test_paid_12345';
			const payment = await mollieClient.getPayment(paymentId);

			expect(payment.id).toBe(paymentId);
			expect(payment.status).toBe('paid');
			expect(payment.paidAt).toBeTruthy();
			expect(payment.details).toBeTruthy();
			expect(payment.details.consumerName).toBe('Jan de Vries');
			expect(payment.details.consumerAccount).toMatch(
				/^NL\d{2}[A-Z]{4}\d{10}$/
			);
		});

		it('should get payment status - failed', async () => {
			const paymentId = 'tr_test_failed_12345';
			const payment = await mollieClient.getPayment(paymentId);

			expect(payment.id).toBe(paymentId);
			expect(payment.status).toBe('failed');
			expect(payment.failedAt).toBeTruthy();
			expect(payment.paidAt).toBeNull();
			expect(payment.details).toBeNull();
		});

		it('should get payment status - pending', async () => {
			const paymentId = 'tr_test_pending_12345';
			const payment = await mollieClient.getPayment(paymentId);

			expect(payment.id).toBe(paymentId);
			expect(payment.status).toBe('pending');
			expect(payment.paidAt).toBeNull();
		});

		it('should validate Dutch SEPA details in payment', async () => {
			const paymentId = 'tr_test_paid_sepa';
			const payment = await mollieClient.getPayment(paymentId);

			expect(payment.status).toBe('paid');
			expect(payment.method).toBe('directdebit');
			expect(payment.details.creditorIdentifier).toMatch(/^NL\d{2}ZZZ\d{12}$/);
			expect(payment.details.transferReference).toMatch(
				/^RF\d{2}\s\d{4}\s\d{4}\s\d{4}$/
			);
			expect(payment.details.consumerAccount).toMatch(
				/^NL\d{2}[A-Z]{4}\d{10}$/
			);
			expect(payment.sequenceType).toBe('recurring');
			expect(payment.mandateId).toMatch(/^mdt_test_/);
		});
	});

	describe('Balance Operations', () => {
		it('should get primary balance', async () => {
			const balance = await mollieClient.getBalance('primary');

			expect(balance).toHaveProperty('resource', 'balance');
			expect(balance.id).toBe('primary');
			expect(balance.currency).toBe('EUR');
			expect(balance.availableAmount.value).toBe('150.00');
			expect(balance.pendingAmount.value).toBe('25.00');
			expect(balance.transferThreshold.value).toBe('10.00');
		});

		it('should list all balances', async () => {
			const response = await mollieClient.listBalances();

			expect(response._embedded.balances).toHaveLength(2);
			expect(response.count).toBe(2);

			const primaryBalance = response._embedded.balances.find(
				(b) => b.id === 'primary'
			);
			const secondaryBalance = response._embedded.balances.find(
				(b) => b.id === 'secondary'
			);

			expect(primaryBalance).toBeTruthy();
			expect(secondaryBalance).toBeTruthy();
			expect(primaryBalance.availableAmount.value).toBe('150.00');
			expect(secondaryBalance.availableAmount.value).toBe('75.00');
		});
	});

	describe('Settlement Operations', () => {
		it('should get settlement details', async () => {
			const settlementId = 'stl_test_12345';
			const settlement = await mollieClient.getSettlement(settlementId);

			expect(settlement).toHaveProperty('resource', 'settlement');
			expect(settlement.id).toBe(settlementId);
			expect(settlement.status).toBe('paidout');
			expect(settlement.amount.value).toBe('123.45');
			expect(settlement.settledAt).toBeTruthy();
			expect(settlement.periods).toBeTruthy();
		});

		it('should list settlements', async () => {
			const response = await mollieClient.listSettlements();

			expect(response._embedded.settlements).toHaveLength(2);
			expect(response.count).toBe(2);

			const settlement = response._embedded.settlements[0];
			expect(settlement.resource).toBe('settlement');
			expect(settlement.status).toBe('paidout');
		});

		it('should list settlements with date filter', async () => {
			const response = await mollieClient.listSettlements({
				from: '2025-08-01',
				until: '2025-08-31'
			});

			expect(response._embedded.settlements).toHaveLength(2);
			expect(response._links.self.href).toContain('from=2025-08-01');
			expect(response._links.self.href).toContain('until=2025-08-31');
		});
	});

	describe('Error Handling Scenarios', () => {
		it('should handle authentication error (401)', async () => {
			try {
				await mollieClient.getPayment('tr_auth_error');
				fail('Should have thrown authentication error');
			} catch (error) {
				expect(error.status).toBe(401);
				expect(error.data.title).toBe('Unauthorized Request');
				expect(error.data.detail).toContain('Missing or invalid API key');
				expect(error.data._links.documentation.href).toContain(
					'authentication'
				);
			}
		});

		it('should handle validation error (422)', async () => {
			// Use server.use() to override handler for this specific test
			server.use(
				rest.post('https://api.mollie.com/v2/payments', (req, res, ctx) => {
					return res(
						ctx.status(422),
						ctx.json({
							status: 422,
							title: 'Unprocessable Entity',
							detail: 'The amount is higher than the maximum allowed amount.',
							field: 'amount',
							_links: {
								documentation: {
									href: 'https://docs.mollie.com/reference/v2/payments-api/create-payment',
									type: 'text/html'
								}
							}
						})
					);
				})
			);

			try {
				await mollieClient.createPayment('99999.00', 'EUR', 'Invalid amount');
				fail('Should have thrown validation error');
			} catch (error) {
				expect(error.status).toBe(422);
				expect(error.data.title).toBe('Unprocessable Entity');
				expect(error.data.field).toBe('amount');
				expect(error.data.detail).toContain('maximum allowed amount');
			}
		});

		it('should handle server error (500)', async () => {
			try {
				await mollieClient.getPayment('tr_server_error');
				fail('Should have thrown server error');
			} catch (error) {
				expect(error.status).toBe(500);
				expect(error.data.title).toBe('Internal Server Error');
			}
		});
	});

	describe('Network Condition Simulation', () => {
		it('should handle slow network conditions', async () => {
			const startTime = Date.now();
			const payment = await mollieClient.getPayment('tr_slow_network');
			const endTime = Date.now();

			// Should take at least 2 seconds due to simulated delay
			expect(endTime - startTime).toBeGreaterThan(1900);
			expect(payment.id).toBe('tr_slow_network');
			expect(payment.status).toBe('paid');
		}, 5000); // 5 second timeout for slow network test

		it('should handle flaky network connections with retry logic', async () => {
			let attempts = 0;
			const maxAttempts = 3;

			const makeRequestWithRetry = async () => {
				while (attempts < maxAttempts) {
					try {
						attempts++;
						return await mollieClient.getPayment('tr_flaky_network');
					} catch (error) {
						if (attempts >= maxAttempts) {
							throw error;
						}
						// Wait before retry
						await new Promise((resolve) => setTimeout(resolve, 100));
					}
				}
			};

			// This should eventually succeed due to randomized success/failure
			const result = await makeRequestWithRetry();
			expect(result).toBeDefined();
			expect(attempts).toBeGreaterThan(0);
			expect(attempts).toBeLessThanOrEqual(maxAttempts);
		});
	});

	describe('Integration Test Scenarios', () => {
		it('should test complete payment workflow', async () => {
			// 1. Create payment
			const createdPayment = await mollieClient.createPayment(
				'30.00',
				'EUR',
				'Monthly membership dues',
				{
					member_id: 'Assoc-Member-2024-002',
					dues_schedule_id: 'MDS-2024-002'
				}
			);

			expect(createdPayment.status).toBe('open');
			expect(createdPayment._links.checkout).toBeTruthy();

			// 2. Check payment status (simulate as paid)
			const paidPaymentId = createdPayment.id.replace(
				'tr_test_',
				'tr_test_paid_'
			);
			const paidPayment = await mollieClient.getPayment(paidPaymentId);

			expect(paidPayment.status).toBe('paid');
			expect(paidPayment.paidAt).toBeTruthy();
			expect(paidPayment.details.consumerName).toBeTruthy();
		});

		it('should test balance and settlement reconciliation', async () => {
			// 1. Get current balance
			const balance = await mollieClient.getBalance('primary');
			const availableAmount = parseFloat(balance.availableAmount.value);
			const pendingAmount = parseFloat(balance.pendingAmount.value);

			expect(availableAmount).toBeGreaterThan(0);
			expect(pendingAmount).toBeGreaterThan(0);

			// 2. Get recent settlements
			const settlements = await mollieClient.listSettlements({
				from: '2025-08-01'
			});

			expect(settlements._embedded.settlements.length).toBeGreaterThan(0);

			// 3. Verify settlement amounts are reasonable
			const totalSettled = settlements._embedded.settlements.reduce(
				(total, settlement) => {
					return total + parseFloat(settlement.amount.value);
				},
				0
			);

			expect(totalSettled).toBeGreaterThan(0);
		});

		it('should validate API connectivity', async () => {
			const methods = await mollieClient.testConnection();

			expect(methods._embedded.methods).toHaveLength(1);
			expect(methods._embedded.methods[0].id).toBe('ideal');
			expect(methods._embedded.methods[0].description).toBe('iDEAL');
			expect(methods._embedded.methods[0].minimumAmount.value).toBe('0.01');
		});
	});

	describe('Dutch Business Logic Validation', () => {
		it('should validate EUR currency requirement', async () => {
			const payment = await mollieClient.createPayment(
				'25.00',
				'EUR',
				'Test payment'
			);

			expect(payment.amount.currency).toBe('EUR');
			// All generated payments should be in EUR for Dutch association
		});

		it('should validate SEPA direct debit details', async () => {
			const payment = await mollieClient.getPayment(
				'tr_test_paid_sepa_validation'
			);

			expect(payment.method).toBe('directdebit');
			expect(payment.sequenceType).toBe('recurring');

			// Dutch SEPA validation
			expect(payment.details.creditorIdentifier).toMatch(/^NL\d{2}ZZZ\d{12}$/);
			expect(payment.details.consumerAccount).toMatch(
				/^NL\d{2}[A-Z]{4}\d{10}$/
			);
			expect(payment.mandateId).toMatch(/^mdt_test_/);
		});

		it('should handle membership-specific metadata', async () => {
			const payment = await mollieClient.createPayment(
				'25.00',
				'EUR',
				'Membership dues',
				{
					member_id: 'Assoc-Member-2024-001',
					dues_schedule_id: 'MDS-2024-001',
					invoice_number: 'SINV-2024-001',
					member_type: 'regular'
				}
			);

			expect(payment.metadata.member_id).toBe('Assoc-Member-2024-001');
			expect(payment.metadata.dues_schedule_id).toBe('MDS-2024-001');
			expect(payment.metadata.invoice_number).toBe('SINV-2024-001');
		});
	});

	describe('Performance and Load Testing', () => {
		it('should handle multiple concurrent API calls', async () => {
			const promises = [];
			const paymentCount = 10;

			// Create multiple payment requests simultaneously
			for (let i = 0; i < paymentCount; i++) {
				promises.push(
					mollieClient.createPayment(`${25 + i}.00`, 'EUR', `Payment ${i}`)
				);
			}

			const results = await Promise.all(promises);

			expect(results).toHaveLength(paymentCount);
			results.forEach((payment, index) => {
				expect(payment.resource).toBe('payment');
				expect(payment.amount.value).toBe(`${25 + index}.00`);
				expect(payment.description).toBe(`Payment ${index}`);
			});
		});

		it('should maintain performance under load', async () => {
			const startTime = Date.now();
			const requestCount = 20;
			const requests = [];

			// Mix of different API calls
			for (let i = 0; i < requestCount; i++) {
				if (i % 3 === 0) {
					requests.push(mollieClient.getBalance('primary'));
				} else if (i % 3 === 1) {
					requests.push(mollieClient.listSettlements());
				} else {
					requests.push(mollieClient.getPayment(`tr_test_paid_${i}`));
				}
			}

			const results = await Promise.all(requests);
			const endTime = Date.now();

			expect(results).toHaveLength(requestCount);
			expect(endTime - startTime).toBeLessThan(1000); // Should complete within 1 second
		});
	});
});

describe('MSW Handler Validation', () => {
	it('should provide realistic payment data structure', () => {
		const payment = generateMolliePayment(
			'tr_test_validation',
			'paid',
			'35.75'
		);

		// Validate required Mollie payment fields
		expect(payment).toHaveProperty('resource', 'payment');
		expect(payment).toHaveProperty('id', 'tr_test_validation');
		expect(payment).toHaveProperty('status', 'paid');
		expect(payment).toHaveProperty('amount');
		expect(payment.amount).toHaveProperty('value', '35.75');
		expect(payment.amount).toHaveProperty('currency', 'EUR');
		expect(payment).toHaveProperty('createdAt');
		expect(payment).toHaveProperty('_links');
		expect(payment._links).toHaveProperty('self');

		// Validate Dutch SEPA fields
		expect(payment.details.creditorIdentifier).toMatch(/^NL\d{2}ZZZ\d{12}$/);
		expect(payment.details.consumerAccount).toMatch(/^NL\d{2}[A-Z]{4}\d{10}$/);
	});

	it('should provide realistic balance data structure', () => {
		const balance = generateMollieBalance('test_balance', '200.50', '15.25');

		expect(balance).toHaveProperty('resource', 'balance');
		expect(balance).toHaveProperty('id', 'test_balance');
		expect(balance).toHaveProperty('currency', 'EUR');
		expect(balance.availableAmount.value).toBe('200.50');
		expect(balance.pendingAmount.value).toBe('15.25');
		expect(balance.transferThreshold.value).toBe('10.00');
	});
});
