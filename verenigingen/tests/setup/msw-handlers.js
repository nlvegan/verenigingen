/**
 * @fileoverview MSW (Mock Service Worker) Handlers for API Testing
 *
 * This module provides HTTP request mocking for external API integrations,
 * specifically targeting Mollie payment gateway API calls. MSW enables
 * testing of network-dependent code without requiring actual API connections.
 *
 * Key Features:
 * - Mollie API v2 endpoint mocking
 * - Realistic response data generation
 * - Error scenario simulation
 * - Network condition testing
 * - Payment webhook simulation
 *
 * @author Verenigingen Development Team
 * @version 2025-08-26
 */

const { rest } = require('msw');

/**
 * Generate realistic Mollie payment data
 * @param {string} id Payment ID
 * @param {string} status Payment status
 * @param {string} amount Amount value
 * @returns {Object} Payment object
 */
function generateMolliePayment(id = 'tr_test_12345', status = 'paid', amount = '25.00') {
	return {
		resource: 'payment',
		id,
		mode: 'test',
		amount: {
			value: amount,
			currency: 'EUR'
		},
		status,
		description: 'Membership dues payment',
		method: 'directdebit',
		metadata: {
			member_id: 'Assoc-Member-2024-001',
			dues_schedule_id: 'MDS-2024-001',
			invoice_number: 'SINV-2024-001'
		},
		details:
			status === 'paid'
				? {
						transferReference: 'RF18 5390 0754 7034',
						creditorIdentifier: 'NL08ZZZ123456780000',
						consumerName: 'Jan de Vries',
						consumerAccount: 'NL55RABO0123456789'
					}
				: null,
		profileId: 'pfl_test_12345',
		sequenceType: 'recurring',
		subscriptionId: 'sub_test_67890',
		mandateId: 'mdt_test_abcde',
		createdAt: '2025-08-26T10:30:00+00:00',
		paidAt: status === 'paid' ? '2025-08-26T10:31:00+00:00' : null,
		failedAt: status === 'failed' ? '2025-08-26T10:31:00+00:00' : null,
		expiresAt: '2025-08-26T11:30:00+00:00',
		_links: {
			self: {
				href: `https://api.mollie.com/v2/payments/${id}`,
				type: 'application/hal+json'
			},
			checkout:
				status === 'open'
					? {
							href: `https://www.mollie.com/checkout/select-method/${id}`,
							type: 'text/html'
						}
					: null
		}
	};
}

/**
 * Generate realistic Mollie balance data
 * @param {string} id Balance ID
 * @param {string} availableAmount Available amount
 * @param {string} pendingAmount Pending amount
 * @returns {Object} Balance object
 */
function generateMollieBalance(id = 'primary', availableAmount = '150.00', pendingAmount = '25.00') {
	return {
		resource: 'balance',
		id,
		currency: 'EUR',
		availableAmount: {
			value: availableAmount,
			currency: 'EUR'
		},
		pendingAmount: {
			value: pendingAmount,
			currency: 'EUR'
		},
		transferThreshold: {
			value: '10.00',
			currency: 'EUR'
		},
		createdAt: '2025-01-01T00:00:00+00:00',
		_links: {
			self: {
				href: `https://api.mollie.com/v2/balances/${id}`,
				type: 'application/hal+json'
			}
		}
	};
}

/**
 * Generate realistic Mollie settlement data
 * @param {string} id Settlement ID
 * @param {string} status Settlement status
 * @param {string} amount Settlement amount
 * @returns {Object} Settlement object
 */
function generateMollieSettlement(id = 'stl_test_12345', status = 'paidout', amount = '123.45') {
	return {
		resource: 'settlement',
		id,
		reference: `REF-${id}`,
		amount: {
			value: amount,
			currency: 'EUR'
		},
		status,
		createdAt: '2025-08-25T00:00:00+00:00',
		settledAt: status === 'paidout' ? '2025-08-26T00:00:00+00:00' : null,
		periods: {
			2025: {
				8: {
					revenue: [
						{
							description: 'iDEAL',
							method: 'ideal',
							count: 15,
							amountNet: {
								value: '120.00',
								currency: 'EUR'
							},
							amountVat: {
								value: '3.45',
								currency: 'EUR'
							},
							amountGross: {
								value: '123.45',
								currency: 'EUR'
							}
						}
					]
				}
			}
		},
		_links: {
			self: {
				href: `https://api.mollie.com/v2/settlements/${id}`,
				type: 'application/hal+json'
			}
		}
	};
}

/**
 * MSW handlers for Mollie API endpoints
 */
const mollieHandlers = [
	// Payment creation endpoint
	rest.post('https://api.mollie.com/v2/payments', (req, res, ctx) => {
		const requestBody = req.body;
		const description = requestBody.description || 'Membership dues payment';
		const amount = requestBody.amount?.value || '25.00';

		return res(
			ctx.status(201),
			ctx.json({
				...generateMolliePayment(`tr_test_${Date.now()}`, 'open', amount),
				description
			})
		);
	}),

	// Payment status check endpoint
	rest.get('https://api.mollie.com/v2/payments/:paymentId', (req, res, ctx) => {
		const { paymentId } = req.params;

		// Simulate different payment statuses based on ID patterns
		let status = 'paid';
		if (paymentId.includes('failed')) {
			status = 'failed';
		} else if (paymentId.includes('pending')) {
			status = 'pending';
		} else if (paymentId.includes('open')) {
			status = 'open';
		} else if (paymentId.includes('canceled')) {
			status = 'canceled';
		}

		return res(ctx.json(generateMolliePayment(paymentId, status, '25.00')));
	}),

	// Balance endpoints
	rest.get('https://api.mollie.com/v2/balances/:balanceId', (req, res, ctx) => {
		const { balanceId } = req.params;
		return res(ctx.json(generateMollieBalance(balanceId, '150.00', '25.00')));
	}),

	rest.get('https://api.mollie.com/v2/balances', (req, res, ctx) => {
		return res(
			ctx.json({
				_embedded: {
					balances: [
						generateMollieBalance('primary', '150.00', '25.00'),
						generateMollieBalance('secondary', '75.00', '10.00')
					]
				},
				count: 2,
				_links: {
					self: {
						href: 'https://api.mollie.com/v2/balances',
						type: 'application/hal+json'
					}
				}
			})
		);
	}),

	// Settlement endpoints
	rest.get('https://api.mollie.com/v2/settlements/:settlementId', (req, res, ctx) => {
		const { settlementId } = req.params;
		return res(ctx.json(generateMollieSettlement(settlementId, 'paidout', '123.45')));
	}),

	rest.get('https://api.mollie.com/v2/settlements', (req, res, ctx) => {
		const url = new URL(req.url);
		const from = url.searchParams.get('from');
		const until = url.searchParams.get('until');

		// Generate settlements based on date range
		const settlements = [
			generateMollieSettlement('stl_test_001', 'paidout', '123.45'),
			generateMollieSettlement('stl_test_002', 'paidout', '87.20')
		];

		return res(
			ctx.json({
				_embedded: {
					settlements
				},
				count: settlements.length,
				_links: {
					self: {
						href: `https://api.mollie.com/v2/settlements${url.search}`,
						type: 'application/hal+json'
					}
				}
			})
		);
	}),

	// Methods endpoint (for connectivity testing)
	rest.get('https://api.mollie.com/v2/methods', (req, res, ctx) => {
		return res(
			ctx.json({
				_embedded: {
					methods: [
						{
							resource: 'method',
							id: 'ideal',
							description: 'iDEAL',
							minimumAmount: { value: '0.01', currency: 'EUR' },
							maximumAmount: { value: '50000.00', currency: 'EUR' },
							image: {
								size1x: 'https://www.mollie.com/external/icons/payment-methods/ideal.png'
							}
						}
					]
				},
				count: 1
			})
		);
	})
];

/**
 * Error simulation handlers for testing failure scenarios
 */
const errorHandlers = [
	// Simulate API timeout
	rest.get('https://api.mollie.com/v2/payments/tr_timeout_test', (req, res, ctx) => {
		return new Promise(() => {
			// Never resolve to simulate timeout
		});
	}),

	// Simulate 401 Unauthorized
	rest.get('https://api.mollie.com/v2/payments/tr_auth_error', (req, res, ctx) => {
		return res(
			ctx.status(401),
			ctx.json({
				status: 401,
				title: 'Unauthorized Request',
				detail: 'Missing or invalid API key.',
				_links: {
					documentation: {
						href: 'https://docs.mollie.com/guides/authentication',
						type: 'text/html'
					}
				}
			})
		);
	}),

	// Simulate 422 Validation Error
	rest.post('https://api.mollie.com/v2/payments/invalid', (req, res, ctx) => {
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
	}),

	// Simulate 500 Internal Server Error
	rest.get('https://api.mollie.com/v2/payments/tr_server_error', (req, res, ctx) => {
		return res(
			ctx.status(500),
			ctx.json({
				status: 500,
				title: 'Internal Server Error',
				detail: 'An internal server error occurred while processing your request.'
			})
		);
	})
];

/**
 * Network condition simulation handlers
 */
const networkHandlers = [
	// Slow network simulation
	rest.get('https://api.mollie.com/v2/payments/tr_slow_network', (req, res, ctx) => {
		return new Promise((resolve) => {
			setTimeout(() => {
				resolve(res(ctx.json(generateMolliePayment('tr_slow_network', 'paid', '25.00'))));
			}, 2000); // 2 second delay
		});
	}),

	// Intermittent failure simulation
	rest.get('https://api.mollie.com/v2/payments/tr_flaky_network', (req, res, ctx) => {
		// Randomly succeed or fail
		if (Math.random() > 0.5) {
			return res(ctx.json(generateMolliePayment('tr_flaky_network', 'paid', '25.00')));
		} else {
			return res(ctx.status(503));
		}
	})
];

module.exports = {
	mollieHandlers,
	errorHandlers,
	networkHandlers,
	generateMolliePayment,
	generateMollieBalance,
	generateMollieSettlement
};
