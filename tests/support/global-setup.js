/**
 * @fileoverview Global Setup for Playwright E2E Testing
 *
 * This module provides global setup functionality for Playwright tests,
 * including environment preparation, test data initialization, and
 * system configuration validation.
 *
 * @module GlobalSetup
 * @version 1.0.0
 */

const { chromium } = require('@playwright/test');

async function globalSetup(config) {
	console.log('[Global Setup] Starting Playwright E2E test environment setup...');

	// Defensive check for config structure
	const baseURL = config?.use?.baseURL || 'https://dev.veganisme.net';
	console.log(`[Global Setup] Using baseURL: ${baseURL}`);

	const browser = await chromium.launch();
	const page = await browser.newPage();

	try {
		// Step 1: Verify development environment is accessible
		console.log('[Global Setup] Verifying development environment...');
		await page.goto(baseURL, { timeout: 30000 });

		const title = await page.title();
		console.log(`[Global Setup] Environment accessible: ${title}`);

		// Step 2: Verify required Mollie settings are configured
		console.log('[Global Setup] Checking Mollie configuration...');
		try {
			await verifyMollieConfiguration(page);
			console.log('[Global Setup] Mollie configuration verified ✓');
		} catch (error) {
			console.warn(`[Global Setup] Mollie configuration issue: ${error.message}`);
			console.warn('[Global Setup] Continuing with limited Mollie testing capabilities');
		}

		// Step 3: Prepare test database state
		console.log('[Global Setup] Preparing test database...');
		await prepareTestDatabase(page);

		// Step 4: Validate webhook endpoints
		console.log('[Global Setup] Validating webhook endpoints...');
		await validateWebhookEndpoints(page);

		console.log('[Global Setup] Environment setup completed successfully');
	} catch (error) {
		console.error(`[Global Setup] Setup failed: ${error.message}`);
		throw error;
	} finally {
		await browser.close();
	}
}

/**
 * Verify Mollie configuration is properly set up for testing
 */
async function verifyMollieConfiguration(page) {
	try {
		const mollieConfig = await page.evaluate(async () => {
			// Check if we can access Mollie settings
			const response = await fetch('/api/method/frappe.client.get_doc', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					'X-Frappe-CSRF-Token': frappe.csrf_token
				},
				body: JSON.stringify({
					doctype: 'Mollie Settings',
					name: 'Mollie Settings'
				})
			});

			if (response.ok) {
				const data = await response.json();
				return {
					configured: true,
					testMode: data.message?.is_test_mode || false,
					apiKeyConfigured: !!data.message?.api_key
				};
			}

			return { configured: false };
		});

		if (!mollieConfig.configured) {
			throw new Error('Mollie Settings not found - please configure Mollie integration');
		}

		if (!mollieConfig.testMode) {
			console.warn('[Global Setup] WARNING: Mollie not in test mode - tests may affect production data');
		}

		if (!mollieConfig.apiKeyConfigured) {
			throw new Error('Mollie API key not configured');
		}

		console.log('[Global Setup] Mollie configuration verified ✓');
	} catch (error) {
		throw new Error(`Mollie configuration check failed: ${error.message}`);
	}
}

/**
 * Prepare test database by cleaning up any existing test data
 */
async function prepareTestDatabase(page) {
	try {
		const cleanup = await page.evaluate(async () => {
			const testDataCleanup = [];

			// Clean up existing test donors
			try {
				const testDonors = await frappe.call({
					method: 'frappe.client.get_list',
					args: {
						doctype: 'Donor',
						filters: {
							donor_email: ['like', '%test-verenigingen.nl%']
						},
						fields: ['name']
					}
				});

				for (const donor of testDonors.message || []) {
					await frappe.call({
						method: 'frappe.client.delete',
						args: {
							doctype: 'Donor',
							name: donor.name
						}
					});
					testDataCleanup.push(`Donor: ${donor.name}`);
				}
			} catch (e) {
				console.warn('Test donor cleanup failed:', e.message);
			}

			// Clean up test donations
			try {
				const testDonations = await frappe.call({
					method: 'frappe.client.get_list',
					args: {
						doctype: 'Donation',
						filters: {
							donor_email: ['like', '%test-verenigingen.nl%']
						},
						fields: ['name']
					}
				});

				for (const donation of testDonations.message || []) {
					await frappe.call({
						method: 'frappe.client.delete',
						args: {
							doctype: 'Donation',
							name: donation.name
						}
					});
					testDataCleanup.push(`Donation: ${donation.name}`);
				}
			} catch (e) {
				console.warn('Test donation cleanup failed:', e.message);
			}

			return testDataCleanup;
		});

		if (cleanup.length > 0) {
			console.log(`[Global Setup] Cleaned up ${cleanup.length} test records`);
		}

		console.log('[Global Setup] Test database prepared ✓');
	} catch (error) {
		throw new Error(`Database preparation failed: ${error.message}`);
	}
}

/**
 * Validate that webhook endpoints are accessible
 */
async function validateWebhookEndpoints(page) {
	const webhookEndpoints = [
		'/api/method/verenigingen.utils.payment_gateways.mollie_subscription_webhook',
		'/api/method/verenigingen.verenigingen_payments.utils.secure_webhook_handler.process_mollie_webhook'
	];

	for (const endpoint of webhookEndpoints) {
		try {
			const response = await page.evaluate(async (endpointUrl) => {
				// Send a test OPTIONS request to check if endpoint exists
				const res = await fetch(endpointUrl, {
					method: 'OPTIONS',
					headers: {
						'Content-Type': 'application/json'
					}
				});
				return { status: res.status, endpoint: endpointUrl };
			}, endpoint);

			// Endpoint should exist (not 404)
			if (response.status === 404) {
				throw new Error(`Webhook endpoint not found: ${endpoint}`);
			}

			console.log(`[Global Setup] Webhook endpoint verified: ${endpoint} ✓`);
		} catch (error) {
			throw new Error(`Webhook endpoint validation failed for ${endpoint}: ${error.message}`);
		}
	}

	console.log('[Global Setup] Webhook endpoints validated ✓');
}

module.exports = globalSetup;
