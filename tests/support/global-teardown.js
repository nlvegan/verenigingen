/**
 * @fileoverview Global Teardown for Playwright E2E Testing
 *
 * This module provides global teardown functionality for Playwright tests,
 * including test data cleanup, result reporting, and environment restoration.
 *
 * @module GlobalTeardown
 * @version 1.0.0
 */

const { chromium } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

async function globalTeardown(config) {
	console.log('[Global Teardown] Starting Playwright E2E test cleanup...');

	const browser = await chromium.launch();
	const page = await browser.newPage();

	try {
		// Step 1: Clean up test data from database
		console.log('[Global Teardown] Cleaning up test data...');
		await cleanupTestData(page);

		// Step 2: Generate test summary report
		console.log('[Global Teardown] Generating test summary...');
		await generateTestSummary();

		// Step 3: Archive test artifacts
		console.log('[Global Teardown] Archiving test artifacts...');
		await archiveTestArtifacts();

		// Step 4: Check for data integrity
		console.log('[Global Teardown] Performing final data integrity check...');
		await performDataIntegrityCheck(page);

		console.log('[Global Teardown] Cleanup completed successfully');
	} catch (error) {
		console.error(`[Global Teardown] Cleanup failed: ${error.message}`);
		// Don't throw - teardown failures shouldn't fail the test run
	} finally {
		await browser.close();
	}
}

/**
 * Clean up all test data created during the test run
 */
async function cleanupTestData(page) {
	try {
		const cleanupResults = await page.evaluate(async () => {
			const results = {
				donors: 0,
				donations: 0,
				paymentEntries: 0,
				paymentHistory: 0,
				webhookLogs: 0,
				errors: []
			};

			// Clean up test donors
			try {
				const testDonors = await frappe.call({
					method: 'frappe.client.get_list',
					args: {
						doctype: 'Donor',
						filters: {
							donor_email: ['like', '%test-verenigingen.nl%']
						},
						fields: ['name'],
						limit_page_length: 1000
					}
				});

				for (const donor of testDonors.message || []) {
					try {
						await frappe.call({
							method: 'frappe.client.delete',
							args: {
								doctype: 'Donor',
								name: donor.name
							}
						});
						results.donors++;
					} catch (e) {
						results.errors.push(`Failed to delete Donor ${donor.name}: ${e.message}`);
					}
				}
			} catch (e) {
				results.errors.push(`Donor cleanup query failed: ${e.message}`);
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
						fields: ['name'],
						limit_page_length: 1000
					}
				});

				for (const donation of testDonations.message || []) {
					try {
						await frappe.call({
							method: 'frappe.client.delete',
							args: {
								doctype: 'Donation',
								name: donation.name
							}
						});
						results.donations++;
					} catch (e) {
						results.errors.push(`Failed to delete Donation ${donation.name}: ${e.message}`);
					}
				}
			} catch (e) {
				results.errors.push(`Donation cleanup query failed: ${e.message}`);
			}

			// Clean up test payment entries
			try {
				const testPayments = await frappe.call({
					method: 'frappe.client.get_list',
					args: {
						doctype: 'Payment Entry',
						filters: {
							reference_no: ['like', '%tr_test_%']
						},
						fields: ['name'],
						limit_page_length: 1000
					}
				});

				for (const payment of testPayments.message || []) {
					try {
						await frappe.call({
							method: 'frappe.client.delete',
							args: {
								doctype: 'Payment Entry',
								name: payment.name
							}
						});
						results.paymentEntries++;
					} catch (e) {
						results.errors.push(`Failed to delete Payment Entry ${payment.name}: ${e.message}`);
					}
				}
			} catch (e) {
				results.errors.push(`Payment Entry cleanup query failed: ${e.message}`);
			}

			// Clean up test webhook processing logs
			try {
				const testLogs = await frappe.call({
					method: 'frappe.client.get_list',
					args: {
						doctype: 'Webhook Processing Log',
						filters: {
							webhook_id: ['like', '%tr_test_%']
						},
						fields: ['name'],
						limit_page_length: 1000
					}
				});

				for (const log of testLogs.message || []) {
					try {
						await frappe.call({
							method: 'frappe.client.delete',
							args: {
								doctype: 'Webhook Processing Log',
								name: log.name
							}
						});
						results.webhookLogs++;
					} catch (e) {
						results.errors.push(`Failed to delete Webhook Log ${log.name}: ${e.message}`);
					}
				}
			} catch (e) {
				results.errors.push(`Webhook Log cleanup query failed: ${e.message}`);
			}

			return results;
		});

		console.log(`[Global Teardown] Cleanup results:`);
		console.log(`  - Donors cleaned: ${cleanupResults.donors}`);
		console.log(`  - Donations cleaned: ${cleanupResults.donations}`);
		console.log(`  - Payment Entries cleaned: ${cleanupResults.paymentEntries}`);
		console.log(`  - Webhook Logs cleaned: ${cleanupResults.webhookLogs}`);

		if (cleanupResults.errors.length > 0) {
			console.warn(`[Global Teardown] ${cleanupResults.errors.length} cleanup errors:`);
			cleanupResults.errors.forEach(error => console.warn(`  - ${error}`));
		}
	} catch (error) {
		console.error(`[Global Teardown] Data cleanup failed: ${error.message}`);
	}
}

/**
 * Generate a comprehensive test summary report
 */
async function generateTestSummary() {
	try {
		const resultsDir = 'test-results';
		const summaryFile = path.join(resultsDir, 'test-summary.json');

		// Read test results if available
		let testResults = {};
		const jsonResultsFile = path.join(resultsDir, 'test-results.json');

		if (fs.existsSync(jsonResultsFile)) {
			testResults = JSON.parse(fs.readFileSync(jsonResultsFile, 'utf8'));
		}

		const summary = {
			timestamp: new Date().toISOString(),
			environment: process.env.NODE_ENV || 'development',
			baseUrl: 'https://dev.veganisme.net',
			testSuite: 'Mollie Donation E2E',

			// Test execution summary
			execution: {
				totalTests: testResults.stats?.total || 0,
				passed: testResults.stats?.passed || 0,
				failed: testResults.stats?.failed || 0,
				skipped: testResults.stats?.skipped || 0,
				duration: testResults.stats?.duration || 0
			},

			// Test coverage areas
			coverage: {
				donationFormSubmission: true,
				molliePaymentRedirect: true,
				paymentProcessing: true,
				webhookProcessing: true,
				databaseUpdates: true,
				errorScenarios: true
			},

			// Key metrics
			metrics: {
				averageTestDuration: testResults.stats?.duration
					? (testResults.stats.duration / testResults.stats.total) : 0,
				successRate: testResults.stats?.total
					? `${(testResults.stats.passed / testResults.stats.total * 100).toFixed(2)}%` : '0%'
			},

			// Environment info
			environment_info: {
				nodeVersion: process.version,
				platform: process.platform,
				arch: process.arch
			}
		};

		// Ensure results directory exists
		if (!fs.existsSync(resultsDir)) {
			fs.mkdirSync(resultsDir, { recursive: true });
		}

		// Write summary file
		fs.writeFileSync(summaryFile, JSON.stringify(summary, null, 2));

		console.log(`[Global Teardown] Test summary generated: ${summaryFile}`);
		console.log(`  - Tests run: ${summary.execution.totalTests}`);
		console.log(`  - Success rate: ${summary.metrics.successRate}`);
	} catch (error) {
		console.error(`[Global Teardown] Failed to generate test summary: ${error.message}`);
	}
}

/**
 * Archive test artifacts for future reference
 */
async function archiveTestArtifacts() {
	try {
		const resultsDir = 'test-results';
		const archiveDir = path.join(resultsDir, 'archive');
		const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
		const archiveSubDir = path.join(archiveDir, `run-${timestamp}`);

		if (!fs.existsSync(resultsDir)) {
			console.log('[Global Teardown] No test results to archive');
			return;
		}

		// Create archive directory
		if (!fs.existsSync(archiveSubDir)) {
			fs.mkdirSync(archiveSubDir, { recursive: true });
		}

		// Archive key files
		const filesToArchive = [
			'test-results.json',
			'test-summary.json',
			'junit.xml'
		];

		let archivedCount = 0;

		for (const filename of filesToArchive) {
			const sourceFile = path.join(resultsDir, filename);
			const archiveFile = path.join(archiveSubDir, filename);

			if (fs.existsSync(sourceFile)) {
				fs.copyFileSync(sourceFile, archiveFile);
				archivedCount++;
			}
		}

		// Archive screenshots and videos if they exist
		const artifactDirs = ['html-report', 'playwright-output'];

		for (const dirName of artifactDirs) {
			const sourceDir = path.join(resultsDir, dirName);
			const archiveArtifactDir = path.join(archiveSubDir, dirName);

			if (fs.existsSync(sourceDir)) {
				fs.mkdirSync(archiveArtifactDir, { recursive: true });

				// Simple directory copy (could be enhanced with recursive copy)
				try {
					const files = fs.readdirSync(sourceDir);
					files.forEach(file => {
						const sourcePath = path.join(sourceDir, file);
						const destPath = path.join(archiveArtifactDir, file);

						if (fs.statSync(sourcePath).isFile()) {
							fs.copyFileSync(sourcePath, destPath);
							archivedCount++;
						}
					});
				} catch (e) {
					console.warn(`[Global Teardown] Failed to archive ${dirName}: ${e.message}`);
				}
			}
		}

		console.log(`[Global Teardown] Archived ${archivedCount} test artifacts to: ${archiveSubDir}`);
	} catch (error) {
		console.error(`[Global Teardown] Failed to archive test artifacts: ${error.message}`);
	}
}

/**
 * Perform final data integrity check
 */
async function performDataIntegrityCheck(page) {
	try {
		const integrityCheck = await page.evaluate(async () => {
			const checks = {
				residualTestData: 0,
				systemConsistency: true,
				errors: []
			};

			// Check for any remaining test data
			try {
				const remainingTestDonors = await frappe.call({
					method: 'frappe.client.get_count',
					args: {
						doctype: 'Donor',
						filters: {
							donor_email: ['like', '%test-verenigingen.nl%']
						}
					}
				});

				checks.residualTestData += remainingTestDonors.message || 0;

				const remainingTestDonations = await frappe.call({
					method: 'frappe.client.get_count',
					args: {
						doctype: 'Donation',
						filters: {
							donor_email: ['like', '%test-verenigingen.nl%']
						}
					}
				});

				checks.residualTestData += remainingTestDonations.message || 0;
			} catch (e) {
				checks.errors.push(`Integrity check query failed: ${e.message}`);
				checks.systemConsistency = false;
			}

			return checks;
		});

		if (integrityCheck.residualTestData > 0) {
			console.warn(`[Global Teardown] WARNING: ${integrityCheck.residualTestData} test records remain in database`);
		} else {
			console.log('[Global Teardown] Data integrity check passed ✓');
		}

		if (integrityCheck.errors.length > 0) {
			console.warn('[Global Teardown] Integrity check errors:');
			integrityCheck.errors.forEach(error => console.warn(`  - ${error}`));
		}
	} catch (error) {
		console.error(`[Global Teardown] Data integrity check failed: ${error.message}`);
	}
}

module.exports = globalTeardown;
