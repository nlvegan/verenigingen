/**
 * @fileoverview Comprehensive Playwright E2E Test for Mollie Donation Flow
 *
 * This test suite validates the complete end-to-end Mollie donation process
 * from form submission through payment completion and database updates.
 *
 * Test Coverage:
 * - Donation form submission with Dutch test data
 * - Mollie payment page redirect and processing
 * - Webhook verification and processing
 * - Database validation (Donation, Payment Entry, Donor records)
 * - Payment history tracking validation
 * - Error scenarios and edge cases
 *
 * Key Features:
 * - Realistic Dutch test data (names with tussenvoegsel, postal codes)
 * - Comprehensive error handling and retries
 * - Detailed logging and debugging capabilities
 * - Integration with Enhanced Test Factory patterns
 * - Mollie test environment integration
 * - Production-ready validation patterns
 *
 * @module MollieDonationFlowE2E
 * @version 1.0.0
 * @requires @playwright/test
 */

const { test, expect } = require('@playwright/test');
const { DutchTestDataGenerator } = require('../support/dutch-test-data');
const { MollieTestHelpers } = require('../support/mollie-test-helpers');
const { DatabaseValidator } = require('../support/database-validator');
const { WebhookSimulator } = require('../support/webhook-simulator');

/**
 * Mollie Donation Flow Test Suite
 *
 * Comprehensive end-to-end testing of the complete donation workflow
 * from initial form interaction through final database verification.
 */
test.describe('Mollie Donation Flow E2E', () => {
	/** @type {DutchTestDataGenerator} */
	let testDataGenerator;

	/** @type {MollieTestHelpers} */
	let mollieHelpers;

	/** @type {DatabaseValidator} */
	let dbValidator;

	/** @type {WebhookSimulator} */
	let webhookSimulator;

	/** @type {Object} Test data for current test */
	let testData;

	/**
	 * Test setup - Initialize test helpers and generate test data
	 */
	test.beforeEach(async ({ page }) => {
		// Initialize test helpers
		testDataGenerator = new DutchTestDataGenerator({ seed: Date.now() });
		mollieHelpers = new MollieTestHelpers(page);
		dbValidator = new DatabaseValidator(page);
		webhookSimulator = new WebhookSimulator(page);

		// Generate realistic Dutch test data
		testData = testDataGenerator.generateDonorData({
			includeDetails: true,
			donationType: 'recurring',
			useTussenvoegsel: true
		});

		console.log(`[E2E] Generated test data for: ${testData.fullName}`);
		console.log(`[E2E] Test email: ${testData.email}`);
	});

	/**
	 * Test cleanup - Clean up test data and verify no side effects
	 */
	test.afterEach(async ({ page }) => {
		// Clean up any created test data
		if (testData?.generatedRecords) {
			await dbValidator.cleanupTestRecords(testData.generatedRecords);
		}

		// Capture final screenshot for debugging
		await page.screenshot({
			path: `test-results/mollie-donation-${testData.testId}-final.png`,
			fullPage: true
		});
	});

	/**
	 * Happy Path: Complete recurring donation flow with Mollie
	 *
	 * This test validates the complete flow from form submission to
	 * successful payment processing and database updates.
	 */
	test('Complete recurring donation flow - Happy Path', async ({ page }) => {
		test.setTimeout(120000); // 2 minutes for complete flow

		console.log('[E2E] Starting complete recurring donation flow test');

		// Step 1: Navigate to donation form
		await test.step('Navigate to donation form', async () => {
			await page.goto('/donate', { waitUntil: 'networkidle' });

			// Verify page loaded correctly
			await expect(page.locator('h1')).toContainText('Make a Donation');
			await expect(page.locator('.donation-form')).toBeVisible();

			// Take screenshot of initial form
			await page.screenshot({
				path: `test-results/donation-form-initial-${testData.testId}.png`
			});
		});

		// Step 2: Fill donation form with Dutch test data
		await test.step('Fill donation form with recurring donation', async () => {
			// Fill donor information
			await page.fill('[name="donor_first_name"]', testData.firstName);

			if (testData.tussenvoegsel) {
				await page.fill('[name="donor_tussenvoegsel"]', testData.tussenvoegsel);
			}

			await page.fill('[name="donor_last_name"]', testData.lastName);
			await page.fill('[name="donor_email"]', testData.email);
			await page.fill('[name="donor_phone"]', testData.phone);

			// Fill address information
			await page.fill('[name="donor_street"]', testData.address.street);
			await page.fill('[name="donor_postal_code"]', testData.address.postalCode);
			await page.fill('[name="donor_city"]', testData.address.city);

			// Set donation details
			await page.fill('[name="donation_amount"]', '25.00');

			// Select recurring donation
			await page.check('[name="donation_type"][value="recurring"]');
			await page.selectOption('[name="recurring_frequency"]', 'Monthly');

			// Select Mollie payment method
			await page.click('[data-payment-method="Mollie"]');

			// Verify form fields are filled correctly
			await expect(page.locator('[name="donor_email"]')).toHaveValue(testData.email);
			await expect(page.locator('[name="donation_amount"]')).toHaveValue('25.00');

			console.log('[E2E] Form filled with test data');
		});

		// Step 3: Submit donation form and handle redirect
		await test.step('Submit donation form and verify Mollie redirect', async () => {
			// Set up navigation promise to catch redirect
			const navigationPromise = page.waitForURL(/mollie\.com|payments\.mollie\.com/);

			// Submit the form
			await page.click('[type="submit"]', { timeout: 5000 });

			// Wait for redirect to Mollie
			try {
				await navigationPromise;
				console.log('[E2E] Successfully redirected to Mollie payment page');
			} catch (error) {
				// If not redirected, check for error messages
				const errorMessage = await page
					.locator('.error-message')
					.textContent()
					.catch(() => null);
				if (errorMessage) {
					console.error(`[E2E] Form submission error: ${errorMessage}`);
					throw new Error(`Form submission failed: ${errorMessage}`);
				}
				throw error;
			}

			// Verify we're on Mollie payment page
			await expect(page).toHaveURL(/mollie\.(com|nl)/);

			// Take screenshot of Mollie payment page
			await page.screenshot({
				path: `test-results/mollie-payment-page-${testData.testId}.png`
			});
		});

		// Step 4: Complete Mollie payment (test mode)
		await test.step('Complete Mollie payment in test mode', async () => {
			// Use Mollie test helpers to complete payment
			const paymentResult = await mollieHelpers.completeTestPayment({
				paymentMethod: 'ideal',
				amount: 25.0,
				testScenario: 'success'
			});

			expect(paymentResult.status).toBe('paid');
			console.log(`[E2E] Mollie payment completed: ${paymentResult.id}`);

			// Store payment ID for webhook simulation
			testData.molliePaymentId = paymentResult.id;
		});

		// Step 5: Simulate webhook processing
		await test.step('Process Mollie webhook', async () => {
			// Wait a moment for any redirect/processing
			await page.waitForTimeout(2000);

			// Simulate webhook with payment completion
			const webhookResult = await webhookSimulator.sendMollieWebhook({
				paymentId: testData.molliePaymentId,
				status: 'paid',
				amount: 25.0,
				metadata: {
					donor_email: testData.email,
					donation_type: 'recurring'
				}
			});

			expect(webhookResult.processed).toBe(true);
			console.log('[E2E] Webhook processed successfully');
		});

		// Step 6: Verify database updates
		await test.step('Verify donation and payment records created', async () => {
			// Allow time for database operations
			await page.waitForTimeout(3000);

			// Verify Donor record was created
			const donorRecord = await dbValidator.verifyDonorExists({
				email: testData.email,
				firstName: testData.firstName,
				lastName: testData.lastName
			});
			expect(donorRecord).toBeTruthy();
			console.log(`[E2E] Donor record verified: ${donorRecord.name}`);

			// Verify Donation record was created with Mollie fields
			const donationRecord = await dbValidator.verifyDonationExists({
				donorEmail: testData.email,
				amount: 25.0,
				status: 'Recurring'
			});
			expect(donationRecord).toBeTruthy();
			expect(donationRecord.mollie_customer_id).toBeTruthy();
			expect(donationRecord.paid).toBe(1);
			console.log(`[E2E] Donation record verified: ${donationRecord.name}`);

			// Verify Payment Entry was created
			const paymentEntry = await dbValidator.verifyPaymentEntryExists({
				paidAmount: 25.0,
				reference: testData.molliePaymentId
			});
			expect(paymentEntry).toBeTruthy();
			console.log(`[E2E] Payment Entry verified: ${paymentEntry.name}`);

			// Store created records for cleanup
			testData.generatedRecords = {
				donor: donorRecord.name,
				donation: donationRecord.name,
				paymentEntry: paymentEntry.name
			};
		});

		// Step 7: Verify payment history tracking
		await test.step('Verify payment history is updated', async () => {
			const paymentHistory = await dbValidator.verifyPaymentHistoryExists({
				donorName: testData.generatedRecords.donor,
				amount: 25.0,
				paymentMethod: 'Mollie'
			});

			expect(paymentHistory).toBeTruthy();
			expect(paymentHistory.status).toBe('Completed');
			console.log(`[E2E] Payment history verified: ${paymentHistory.name}`);
		});

		console.log('[E2E] Complete recurring donation flow test PASSED');
	});

	/**
	 * Single donation flow test
	 *
	 * Validates one-time donation processing with different test data
	 */
	test('Single donation flow with different payment method', async ({ page }) => {
		test.setTimeout(90000);

		console.log('[E2E] Starting single donation flow test');

		// Generate different test data for single donation
		const singleTestData = testDataGenerator.generateDonorData({
			includeDetails: true,
			donationType: 'single',
			useTussenvoegsel: false
		});

		await test.step('Fill and submit single donation form', async () => {
			await page.goto('/donate');

			// Fill form for single donation
			await page.fill('[name="donor_first_name"]', singleTestData.firstName);
			await page.fill('[name="donor_last_name"]', singleTestData.lastName);
			await page.fill('[name="donor_email"]', singleTestData.email);
			await page.fill('[name="donation_amount"]', '50.00');

			// Select single donation (should be default)
			await page.check('[name="donation_type"][value="single"]');
			await page.click('[data-payment-method="Mollie"]');

			// Submit and verify redirect
			const navigationPromise = page.waitForURL(/mollie\.com/);
			await page.click('[type="submit"]');
			await navigationPromise;

			console.log('[E2E] Single donation form submitted successfully');
		});

		await test.step('Complete payment and verify processing', async () => {
			const paymentResult = await mollieHelpers.completeTestPayment({
				paymentMethod: 'creditcard',
				amount: 50.0,
				testScenario: 'success'
			});

			expect(paymentResult.status).toBe('paid');

			// Simulate webhook
			await webhookSimulator.sendMollieWebhook({
				paymentId: paymentResult.id,
				status: 'paid',
				amount: 50.0,
				metadata: {
					donor_email: singleTestData.email,
					donation_type: 'single'
				}
			});

			// Verify single donation record
			await page.waitForTimeout(2000);
			const donationRecord = await dbValidator.verifyDonationExists({
				donorEmail: singleTestData.email,
				amount: 50.0,
				status: 'One-time'
			});

			expect(donationRecord).toBeTruthy();
			expect(donationRecord.paid).toBe(1);

			console.log('[E2E] Single donation processing verified');
		});
	});

	/**
	 * Error scenario testing
	 *
	 * Tests various failure scenarios and error handling
	 */
	test('Error scenarios - Payment failures and validation', async ({ page }) => {
		test.setTimeout(60000);

		console.log('[E2E] Starting error scenario tests');

		await test.step('Test form validation errors', async () => {
			await page.goto('/donate');

			// Try to submit empty form
			await page.click('[type="submit"]');

			// Verify validation errors appear
			await expect(page.locator('.field-error')).toHaveCount(3, {
				timeout: 5000
			});
			console.log('[E2E] Form validation errors displayed correctly');
		});

		await test.step('Test invalid email format', async () => {
			await page.fill('[name="donor_first_name"]', 'Test');
			await page.fill('[name="donor_last_name"]', 'User');
			await page.fill('[name="donor_email"]', 'invalid-email');
			await page.fill('[name="donation_amount"]', '25.00');

			await page.click('[type="submit"]');

			// Verify email validation error
			await expect(page.locator('[name="donor_email"]:invalid')).toBeVisible();
			console.log('[E2E] Email validation working correctly');
		});

		await test.step('Test Mollie payment failure', async () => {
			// Fill valid form
			const errorTestData = testDataGenerator.generateDonorData({});

			await page.fill('[name="donor_first_name"]', errorTestData.firstName);
			await page.fill('[name="donor_last_name"]', errorTestData.lastName);
			await page.fill('[name="donor_email"]', errorTestData.email);
			await page.fill('[name="donation_amount"]', '10.00');
			await page.click('[data-payment-method="Mollie"]');

			// Submit and redirect to Mollie
			const navigationPromise = page.waitForURL(/mollie\.com/);
			await page.click('[type="submit"]');
			await navigationPromise;

			// Simulate payment failure
			const failedPaymentResult = await mollieHelpers.completeTestPayment({
				paymentMethod: 'ideal',
				amount: 10.0,
				testScenario: 'failed'
			});

			expect(failedPaymentResult.status).toBe('failed');

			// Simulate webhook for failed payment
			await webhookSimulator.sendMollieWebhook({
				paymentId: failedPaymentResult.id,
				status: 'failed',
				amount: 10.0,
				metadata: {
					donor_email: errorTestData.email
				}
			});

			// Verify donation exists but is not paid
			await page.waitForTimeout(2000);
			const donationRecord = await dbValidator.verifyDonationExists({
				donorEmail: errorTestData.email,
				amount: 10.0
			});

			expect(donationRecord).toBeTruthy();
			expect(donationRecord.paid).toBe(0);
			expect(donationRecord.payment_status).toBe('Error');

			console.log('[E2E] Failed payment scenario handled correctly');
		});
	});

	/**
	 * Performance and stress testing
	 *
	 * Tests system behavior under various load conditions
	 */
	test('Performance validation - Multiple concurrent donations', async ({ page, browser }) => {
		test.setTimeout(180000); // 3 minutes

		console.log('[E2E] Starting performance validation test');

		await test.step('Process multiple donations concurrently', async () => {
			const concurrentDonations = 3; // Reduced for test environment
			const donationPromises = [];

			for (let i = 0; i < concurrentDonations; i++) {
				const context = await browser.newContext();
				const testPage = await context.newPage();

				const donationPromise = (async () => {
					const perfTestData = testDataGenerator.generateDonorData({
						seed: Date.now() + i
					});

					await testPage.goto('/donate');

					// Fill form
					await testPage.fill('[name="donor_first_name"]', perfTestData.firstName);
					await testPage.fill('[name="donor_last_name"]', perfTestData.lastName);
					await testPage.fill('[name="donor_email"]', perfTestData.email);
					await testPage.fill('[name="donation_amount"]', '15.00');
					await testPage.click('[data-payment-method="Mollie"]');

					// Submit
					const navigationPromise = testPage.waitForURL(/mollie\.com/);
					await testPage.click('[type="submit"]');
					await navigationPromise;

					// Complete payment
					const mollieHelper = new MollieTestHelpers(testPage);
					const paymentResult = await mollieHelper.completeTestPayment({
						paymentMethod: 'ideal',
						amount: 15.0,
						testScenario: 'success'
					});

					await context.close();
					return { perfTestData, paymentResult };
				})();

				donationPromises.push(donationPromise);
			}

			// Wait for all donations to complete
			const results = await Promise.all(donationPromises);

			console.log(`[E2E] ${results.length} concurrent donations processed successfully`);

			// Verify all donations were processed
			for (const result of results) {
				expect(result.paymentResult.status).toBe('paid');
			}
		});
	});

	/**
	 * Integration testing - Full webhook processing validation
	 *
	 * Tests the complete webhook processing pipeline with detailed logging
	 */
	test('Webhook processing validation with detailed logging', async ({ page }) => {
		test.setTimeout(90000);

		console.log('[E2E] Starting detailed webhook processing validation');

		let webhookTestData;
		let paymentId;

		await test.step('Create donation for webhook testing', async () => {
			webhookTestData = testDataGenerator.generateDonorData({
				includeDetails: true,
				donationType: 'recurring'
			});

			await page.goto('/donate');

			// Fill and submit form
			await page.fill('[name="donor_first_name"]', webhookTestData.firstName);
			await page.fill('[name="donor_last_name"]', webhookTestData.lastName);
			await page.fill('[name="donor_email"]', webhookTestData.email);
			await page.fill('[name="donation_amount"]', '30.00');
			await page.check('[name="donation_type"][value="recurring"]');
			await page.click('[data-payment-method="Mollie"]');

			const navigationPromise = page.waitForURL(/mollie\.com/);
			await page.click('[type="submit"]');
			await navigationPromise;

			// Complete payment
			const paymentResult = await mollieHelpers.completeTestPayment({
				paymentMethod: 'ideal',
				amount: 30.0,
				testScenario: 'success'
			});

			paymentId = paymentResult.id;
			console.log(`[E2E] Payment created for webhook testing: ${paymentId}`);
		});

		await test.step('Test webhook processing with logging validation', async () => {
			// Send webhook with comprehensive data
			const webhookResult = await webhookSimulator.sendMollieWebhook({
				paymentId,
				status: 'paid',
				amount: 30.0,
				metadata: {
					donor_email: webhookTestData.email,
					donation_type: 'recurring',
					test_identifier: `e2e-${Date.now()}`
				}
			});

			// Verify webhook processing
			expect(webhookResult.processed).toBe(true);
			expect(webhookResult.logEntries).toHaveLength.greaterThan(0);

			// Verify webhook processing log was created
			const processingLog = await dbValidator.verifyWebhookProcessingLogExists({
				webhookId: paymentId,
				status: 'processed'
			});

			expect(processingLog).toBeTruthy();
			console.log(`[E2E] Webhook processing log verified: ${processingLog.name}`);
		});

		await test.step('Verify comprehensive database updates', async () => {
			await page.waitForTimeout(3000); // Allow processing time

			// Verify all related records
			const donorRecord = await dbValidator.verifyDonorExists({
				email: webhookTestData.email
			});

			const donationRecord = await dbValidator.verifyDonationExists({
				donorEmail: webhookTestData.email,
				amount: 30.0
			});

			const paymentEntry = await dbValidator.verifyPaymentEntryExists({
				reference: paymentId
			});

			// Verify Mollie integration fields are populated
			expect(donationRecord.mollie_customer_id).toBeTruthy();
			expect(donationRecord.mollie_subscription_id).toBeTruthy();
			expect(donationRecord.payment_status).toBe('Completed');

			// Verify accounting integration
			expect(donationRecord.sales_invoice).toBeTruthy();

			console.log('[E2E] Comprehensive database validation completed successfully');
		});
	});
});
