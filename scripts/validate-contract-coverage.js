#!/usr/bin/env node
/**
 * @fileoverview API Contract Coverage Validation Script
 *
 * Validates that API contract coverage meets minimum requirements
 * for CI/CD pipeline quality gates.
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 */

const { SimpleAPIContractTester } = require('../verenigingen/tests/setup/api-contract-simple');
const fs = require('fs');
const path = require('path');

class ContractCoverageValidator {
	constructor() {
		this.tester = new SimpleAPIContractTester();
		this.minimumCoverage = 5; // Minimum number of API methods with contracts
		this.targetCoverage = 80; // Target percentage of critical APIs covered
	}

	validateCoverage() {
		console.log('🔍 API Contract Coverage Validation');
		console.log('=====================================');

		const methods = this.tester.getAvailableMethods();
		const totalMethods = methods.length;

		console.log(`📊 Current API Contract Coverage:`);
		console.log(`   - Total methods with contracts: ${totalMethods}`);
		console.log(`   - Minimum required: ${this.minimumCoverage}`);
		console.log(`   - Target coverage: ${this.targetCoverage}% of critical APIs`);

		// List all covered methods
		console.log('\n📋 Covered API Methods:');
		methods.forEach((method, index) => {
			console.log(`   ${index + 1}. ${method}`);
		});

		// Validate each contract
		console.log('\n🧪 Validating Contract Integrity:');
		let allValid = true;
		let validMethods = 0;

		methods.forEach(method => {
			try {
				const testData = this.tester.generateValidTestData(method);
				const result = this.tester.validateFrappeCall({ method, args: testData });

				if (result.valid) {
					console.log(`   ✅ ${method}`);
					validMethods++;
				} else {
					console.log(`   ❌ ${method}: ${result.errors[0]?.message || 'Validation failed'}`);
					allValid = false;
				}
			} catch (error) {
				console.log(`   ⚠️  ${method}: ${error.message}`);
				allValid = false;
			}
		});

		// Analysis and validation
		console.log('\n📈 Coverage Analysis:');
		console.log(`   - Valid contracts: ${validMethods}/${totalMethods}`);
		console.log(`   - Integrity rate: ${((validMethods / totalMethods) * 100).toFixed(1)}%`);

		// Check critical APIs (financial operations)
		const criticalMethods = methods.filter(method =>
			method.includes('payment')
            || method.includes('sepa')
            || method.includes('mandate')
            || method.includes('mollie')
            || method.includes('member')
		);

		console.log(`   - Critical API coverage: ${criticalMethods.length} methods`);

		// Quality gate validation
		let passed = true;
		const issues = [];

		if (totalMethods < this.minimumCoverage) {
			issues.push(`Insufficient contract coverage: ${totalMethods} < ${this.minimumCoverage}`);
			passed = false;
		}

		if (!allValid) {
			issues.push('Some API contracts failed validation');
			passed = false;
		}

		if (validMethods !== totalMethods) {
			issues.push(`Contract integrity issues: ${validMethods}/${totalMethods} valid`);
			passed = false;
		}

		// Generate coverage report
		const report = {
			timestamp: new Date().toISOString(),
			totalMethods,
			validMethods,
			criticalMethods: criticalMethods.length,
			coveragePercentage: ((validMethods / totalMethods) * 100).toFixed(1),
			passed,
			issues,
			methods,
			criticalMethods
		};

		fs.writeFileSync('reports/coverage/contract-coverage-report.json', JSON.stringify(report, null, 2));

		// Final result
		console.log('\n🏁 Coverage Validation Result:');
		if (passed) {
			console.log('✅ API Contract Coverage: PASSED');
			console.log('🎯 All quality gates met');
			process.exit(0);
		} else {
			console.log('❌ API Contract Coverage: FAILED');
			issues.forEach(issue => console.log(`   - ${issue}`));
			console.log('\n🚫 Quality gate blocked');
			process.exit(1);
		}
	}

	generateCoverageRecommendations() {
		console.log('\n💡 Recommendations for Expanding Coverage:');
		console.log('==========================================');

		const highPriorityAPIs = [
			'verenigingen.verenigingen.doctype.sepa_mandate.sepa_mandate.create_mandate',
			'verenigingen.verenigingen.doctype.direct_debit_batch.direct_debit_batch.process_batch',
			'verenigingen.verenigingen_payments.utils.mollie_integration.create_payment',
			'verenigingen.verenigingen.doctype.membership.membership.create_membership',
			'verenigingen.verenigingen.doctype.chapter.chapter.assign_member_with_cleanup'
		];

		highPriorityAPIs.forEach((api, index) => {
			console.log(`   ${index + 1}. ${api}`);
		});

		console.log('\n🎯 Focus on financial and membership operations for maximum impact.');
	}
}

// Execute validation
const validator = new ContractCoverageValidator();

try {
	validator.validateCoverage();
	validator.generateCoverageRecommendations();
} catch (error) {
	console.error('❌ Coverage validation failed:', error.message);
	process.exit(1);
}
