/**
 * @fileoverview Webhook Simulator for E2E Testing
 *
 * This module provides comprehensive webhook simulation capabilities for
 * testing the complete webhook processing pipeline, including signature
 * generation, payload formatting, and processing verification.
 *
 * Features:
 * - Mollie webhook signature generation
 * - Comprehensive webhook payload simulation
 * - Direct webhook endpoint testing
 * - Processing verification and logging
 * - Error scenario simulation
 * - Rate limiting and security testing
 *
 * @module WebhookSimulator
 * @version 1.0.0
 */

const crypto = require('crypto');

class WebhookSimulator {
	constructor(page) {
		this.page = page;
		this.webhookEndpoint = '/api/method/verenigingen.utils.payment_gateways.mollie_subscription_webhook';
		this.testWebhookSecret = process.env.MOLLIE_WEBHOOK_SECRET || 'test_webhook_secret_key';

		// Standard webhook payloads for different scenarios
		this.webhookTemplates = {
			payment_paid: {
				resource: 'payment',
				id: null, // Will be filled
				mode: 'test',
				status: 'paid',
				amount: { value: '25.00', currency: 'EUR' },
				description: 'Test donation',
				method: 'ideal',
				metadata: {},
				details: {
					bankName: 'Test Bank',
					consumerName: 'Test Consumer',
					consumerAccount: 'NL44TEST0123456789'
				}
			},

			payment_failed: {
				resource: 'payment',
				id: null,
				mode: 'test',
				status: 'failed',
				amount: { value: '25.00', currency: 'EUR' },
				description: 'Test donation',
				method: 'ideal',
				metadata: {},
				failureReason: 'Payment failed at bank'
			},

			subscription_active: {
				resource: 'subscription',
				id: null,
				mode: 'test',
				status: 'active',
				amount: { value: '25.00', currency: 'EUR' },
				interval: '1 month',
				description: 'Monthly donation',
				method: 'directdebit',
				metadata: {},
				customerId: null
			},

			subscription_cancelled: {
				resource: 'subscription',
				id: null,
				mode: 'test',
				status: 'cancelled',
				amount: { value: '25.00', currency: 'EUR' },
				interval: '1 month',
				description: 'Monthly donation',
				method: 'directdebit',
				metadata: {},
				customerId: null
			}
		};
	}

	/**
   * Generate Mollie webhook signature for payload verification
   *
   * @param {string} payload - JSON payload string
   * @param {string} secret - Webhook secret key
   * @returns {string} Generated signature
   */
	generateWebhookSignature(payload, secret = null) {
		const webhookSecret = secret || this.testWebhookSecret;

		// Create HMAC SHA256 signature as Mollie does
		const hmac = crypto.createHmac('sha256', webhookSecret);
		hmac.update(payload);
		const signature = hmac.digest('hex');

		console.log(`[Webhook] Generated signature for payload length: ${payload.length}`);
		return signature;
	}

	/**
   * Send a Mollie webhook to the application
   *
   * @param {Object} webhookData - Webhook payload data
   * @returns {Object} Webhook processing result
   */
	async sendMollieWebhook(webhookData) {
		const {
			paymentId,
			status = 'paid',
			amount = 25.00,
			subscriptionId = null,
			customerId = null,
			metadata = {},
			resource = 'payment'
		} = webhookData;

		console.log(`[Webhook] Sending Mollie webhook: ${resource} ${paymentId} (${status})`);

		try {
			// Build webhook payload
			const payload = this.buildWebhookPayload({
				resource,
				id: paymentId,
				status,
				amount,
				subscriptionId,
				customerId,
				metadata
			});

			const payloadString = JSON.stringify(payload);
			const signature = this.generateWebhookSignature(payloadString);

			// Send webhook to application
			const webhookResult = await this.page.evaluate(async ({ endpoint, payload, signature }) => {
				const response = await fetch(endpoint, {
					method: 'POST',
					headers: {
						'Content-Type': 'application/json',
						'X-Mollie-Signature': signature,
						'User-Agent': 'Mollie/1.0 (Test Webhook)',
						'X-Forwarded-For': '127.0.0.1'
					},
					body: payload
				});

				let responseData;
				try {
					responseData = await response.json();
				} catch (e) {
					responseData = { message: 'No JSON response' };
				}

				return {
					status: response.status,
					statusText: response.statusText,
					data: responseData,
					headers: Object.fromEntries(response.headers.entries())
				};
			}, { endpoint: this.webhookEndpoint, payload: payloadString, signature });

			console.log(`[Webhook] Webhook response: ${webhookResult.status} ${webhookResult.statusText}`);

			// Process and return result
			return this.processWebhookResult(webhookResult, payload);
		} catch (error) {
			console.error(`[Webhook] Failed to send webhook: ${error.message}`);
			throw new Error(`Webhook simulation failed: ${error.message}`);
		}
	}

	/**
   * Build webhook payload based on template and parameters
   */
	buildWebhookPayload(params) {
		const template = this.webhookTemplates[`${params.resource}_${params.status}`]
                    || this.webhookTemplates.payment_paid;

		const payload = {
			...template,
			id: params.id,
			status: params.status,
			createdAt: new Date().toISOString(),
			metadata: {
				test: true,
				timestamp: Date.now(),
				...params.metadata
			}
		};

		// Set amount if provided
		if (params.amount) {
			payload.amount = {
				value: params.amount.toFixed(2),
				currency: 'EUR'
			};
		}

		// Add subscription-specific fields
		if (params.resource === 'subscription') {
			payload.customerId = params.customerId;
			if (params.subscriptionId) {
				payload.id = params.subscriptionId;
			}
		}

		// Add Mollie API links
		payload._links = this.generateMollieLinks(params.resource, payload.id);

		console.log(`[Webhook] Built ${params.resource} payload for ${payload.id}`);
		return payload;
	}

	/**
   * Generate Mollie API links for webhook payload
   */
	generateMollieLinks(resource, resourceId) {
		const baseUrl = 'https://api.mollie.com/v2';

		return {
			self: {
				href: `${baseUrl}/${resource}s/${resourceId}`,
				type: 'application/hal+json'
			},
			checkout: resource === 'payment' ? {
				href: `https://www.mollie.com/payscreen/select-method/${resourceId}`,
				type: 'text/html'
			} : undefined,
			dashboard: {
				href: `https://www.mollie.com/dashboard/${resource}s/${resourceId}`,
				type: 'text/html'
			}
		};
	}

	/**
   * Process webhook result and extract meaningful information
   */
	processWebhookResult(webhookResult, originalPayload) {
		const success = webhookResult.status >= 200 && webhookResult.status < 300;

		const result = {
			processed: success,
			statusCode: webhookResult.status,
			statusText: webhookResult.statusText,
			responseData: webhookResult.data,
			originalPayload,
			logEntries: [],
			errors: []
		};

		// Extract processing information from response
		if (webhookResult.data) {
			if (webhookResult.data.message) {
				result.processingMessage = webhookResult.data.message;
			}

			if (webhookResult.data.exc) {
				result.errors.push(webhookResult.data.exc);
			}

			if (webhookResult.data.logs) {
				result.logEntries = webhookResult.data.logs;
			}
		}

		// Determine processing status
		if (!success) {
			result.errors.push(`HTTP ${webhookResult.status}: ${webhookResult.statusText}`);
		}

		console.log(`[Webhook] Processing result: ${success ? 'SUCCESS' : 'FAILED'}`);
		return result;
	}

	/**
   * Send multiple webhooks in sequence (for testing processing order)
   *
   * @param {Array} webhookSequence - Array of webhook configurations
   * @returns {Array} Results for each webhook
   */
	async sendWebhookSequence(webhookSequence) {
		console.log(`[Webhook] Sending sequence of ${webhookSequence.length} webhooks`);

		const results = [];

		for (let i = 0; i < webhookSequence.length; i++) {
			const webhookConfig = webhookSequence[i];

			console.log(`[Webhook] Sending webhook ${i + 1}/${webhookSequence.length}`);

			try {
				const result = await this.sendMollieWebhook(webhookConfig);
				results.push(result);

				// Wait between webhooks if specified
				if (webhookConfig.delay) {
					await new Promise(resolve => setTimeout(resolve, webhookConfig.delay));
				}
			} catch (error) {
				console.error(`[Webhook] Sequence webhook ${i + 1} failed: ${error.message}`);
				results.push({
					processed: false,
					error: error.message,
					webhookConfig
				});
			}
		}

		console.log(`[Webhook] Sequence completed: ${results.filter(r => r.processed).length}/${results.length} successful`);
		return results;
	}

	/**
   * Test webhook signature verification
   *
   * @param {Object} testData - Test data for signature verification
   * @returns {Object} Verification test results
   */
	async testWebhookSignatureVerification(testData = {}) {
		console.log('[Webhook] Testing signature verification');

		const testPayload = JSON.stringify({
			resource: 'payment',
			id: 'tr_test_signature_verification',
			status: 'paid',
			...testData
		});

		const tests = [
			{
				name: 'Valid signature',
				signature: this.generateWebhookSignature(testPayload),
				shouldPass: true
			},
			{
				name: 'Invalid signature',
				signature: 'invalid_signature_12345',
				shouldPass: false
			},
			{
				name: 'Missing signature',
				signature: '',
				shouldPass: false
			},
			{
				name: 'Wrong secret signature',
				signature: this.generateWebhookSignature(testPayload, 'wrong_secret'),
				shouldPass: false
			}
		];

		const results = [];

		for (const test of tests) {
			console.log(`[Webhook] Testing: ${test.name}`);

			try {
				const result = await this.page.evaluate(async ({ endpoint, payload, signature }) => {
					const response = await fetch(endpoint, {
						method: 'POST',
						headers: {
							'Content-Type': 'application/json',
							'X-Mollie-Signature': signature,
							'User-Agent': 'Mollie/1.0 (Signature Test)'
						},
						body: payload
					});

					return {
						status: response.status,
						ok: response.ok
					};
				}, { endpoint: this.webhookEndpoint, payload: testPayload, signature: test.signature });

				const passed = test.shouldPass ? result.ok : !result.ok;

				results.push({
					test: test.name,
					expected: test.shouldPass,
					actual: result.ok,
					passed,
					statusCode: result.status
				});

				console.log(`[Webhook] ${test.name}: ${passed ? 'PASS' : 'FAIL'}`);
			} catch (error) {
				console.error(`[Webhook] Signature test failed: ${error.message}`);
				results.push({
					test: test.name,
					expected: test.shouldPass,
					actual: false,
					passed: false,
					error: error.message
				});
			}
		}

		return results;
	}

	/**
   * Test webhook rate limiting
   *
   * @param {number} requestCount - Number of requests to send rapidly
   * @returns {Object} Rate limiting test results
   */
	async testWebhookRateLimiting(requestCount = 10) {
		console.log(`[Webhook] Testing rate limiting with ${requestCount} rapid requests`);

		const testPayload = JSON.stringify({
			resource: 'payment',
			id: 'tr_test_rate_limiting',
			status: 'paid',
			metadata: { test: 'rate_limiting' }
		});

		const signature = this.generateWebhookSignature(testPayload);
		const requests = [];

		// Send requests rapidly
		for (let i = 0; i < requestCount; i++) {
			requests.push(
				this.page.evaluate(async ({ endpoint, payload, signature, requestId }) => {
					const startTime = Date.now();
					const response = await fetch(endpoint, {
						method: 'POST',
						headers: {
							'Content-Type': 'application/json',
							'X-Mollie-Signature': signature,
							'User-Agent': 'Mollie/1.0 (Rate Limit Test)',
							'X-Request-ID': `rate_test_${requestId}`
						},
						body: payload
					});

					return {
						requestId,
						status: response.status,
						responseTime: Date.now() - startTime,
						rateLimited: response.status === 429
					};
				}, { endpoint: this.webhookEndpoint, payload: testPayload, signature, requestId: i })
			);
		}

		// Wait for all requests to complete
		const results = await Promise.all(requests);

		const summary = {
			totalRequests: requestCount,
			successfulRequests: results.filter(r => r.status >= 200 && r.status < 300).length,
			rateLimitedRequests: results.filter(r => r.rateLimited).length,
			averageResponseTime: results.reduce((sum, r) => sum + r.responseTime, 0) / results.length,
			results
		};

		console.log(`[Webhook] Rate limiting test completed: ${summary.rateLimitedRequests}/${summary.totalRequests} rate limited`);
		return summary;
	}

	/**
   * Simulate webhook processing delays and timeouts
   *
   * @param {Object} options - Simulation options
   * @returns {Object} Processing simulation results
   */
	async simulateWebhookProcessingDelay(options = {}) {
		const {
			paymentId = 'tr_test_processing_delay',
			simulatedProcessingTime = 5000,
			expectTimeout = false
		} = options;

		console.log(`[Webhook] Simulating webhook processing delay: ${simulatedProcessingTime}ms`);

		const webhookPayload = {
			paymentId,
			status: 'paid',
			amount: 25.00,
			metadata: {
				simulate_processing_delay: simulatedProcessingTime,
				test_timeout: expectTimeout
			}
		};

		const startTime = Date.now();

		try {
			const result = await this.sendMollieWebhook(webhookPayload);
			const actualProcessingTime = Date.now() - startTime;

			return {
				expectedDelay: simulatedProcessingTime,
				actualProcessingTime,
				webhookResult: result,
				timedOut: expectTimeout && !result.processed
			};
		} catch (error) {
			const actualProcessingTime = Date.now() - startTime;

			return {
				expectedDelay: simulatedProcessingTime,
				actualProcessingTime,
				error: error.message,
				timedOut: true
			};
		}
	}

	/**
   * Generate comprehensive webhook test suite
   *
   * @returns {Object} Complete test suite results
   */
	async runComprehensiveWebhookTests() {
		console.log('[Webhook] Running comprehensive webhook test suite');

		const testSuite = {
			signatureVerification: null,
			rateLimiting: null,
			processingDelay: null,
			sequenceProcessing: null,
			errorScenarios: null,
			startTime: Date.now()
		};

		try {
			// Test 1: Signature verification
			console.log('[Webhook] Running signature verification tests...');
			testSuite.signatureVerification = await this.testWebhookSignatureVerification();

			// Test 2: Rate limiting (smaller batch for test environment)
			console.log('[Webhook] Running rate limiting tests...');
			testSuite.rateLimiting = await this.testWebhookRateLimiting(5);

			// Test 3: Processing delay simulation
			console.log('[Webhook] Running processing delay tests...');
			testSuite.processingDelay = await this.simulateWebhookProcessingDelay({
				simulatedProcessingTime: 2000
			});

			// Test 4: Sequence processing
			console.log('[Webhook] Running sequence processing tests...');
			testSuite.sequenceProcessing = await this.sendWebhookSequence([
				{ paymentId: 'tr_seq_1', status: 'pending', amount: 10.00 },
				{ paymentId: 'tr_seq_2', status: 'paid', amount: 20.00, delay: 1000 },
				{ paymentId: 'tr_seq_3', status: 'failed', amount: 15.00, delay: 500 }
			]);

			testSuite.completionTime = Date.now() - testSuite.startTime;
			testSuite.success = true;

			console.log(`[Webhook] Comprehensive test suite completed in ${testSuite.completionTime}ms`);
		} catch (error) {
			console.error(`[Webhook] Test suite failed: ${error.message}`);
			testSuite.error = error.message;
			testSuite.success = false;
		}

		return testSuite;
	}
}

module.exports = { WebhookSimulator };
