#!/usr/bin/env node
/**
 * @fileoverview API Contract Report Generation Script
 *
 * Generates comprehensive reports on API contract testing
 * for CI/CD pipeline analysis and team visibility.
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 */

const { SimpleAPIContractTester } = require('../verenigingen/tests/setup/api-contract-simple');
const fs = require('fs');
const path = require('path');

class ContractReportGenerator {
	constructor() {
		this.tester = new SimpleAPIContractTester();
		this.reportDir = 'reports/contracts';
		this.ensureReportDirectory();
	}

	ensureReportDirectory() {
		if (!fs.existsSync('reports')) {
			fs.mkdirSync('reports', { recursive: true });
		}
		if (!fs.existsSync(this.reportDir)) {
			fs.mkdirSync(this.reportDir, { recursive: true });
		}
	}

	generateComprehensiveReport() {
		console.log('📊 Generating API Contract Report');
		console.log('=================================');

		const timestamp = new Date().toISOString();
		const methods = this.tester.getAvailableMethods();

		// Test all contracts
		const contractResults = [];
		let totalValidations = 0;
		let passedValidations = 0;

		console.log('\n🧪 Testing All API Contracts:');

		methods.forEach(method => {
			console.log(`   Testing ${method}...`);

			try {
				const testData = this.tester.generateValidTestData(method);
				const result = this.tester.validateFrappeCall({ method, args: testData });

				const contractResult = {
					method,
					valid: result.valid,
					testData,
					errors: result.errors,
					performance: result.performance,
					schema: result.schema
				};

				contractResults.push(contractResult);
				totalValidations++;

				if (result.valid) {
					passedValidations++;
					console.log(`     ✅ Valid`);
				} else {
					console.log(`     ❌ Failed: ${result.errors[0]?.message}`);
				}
			} catch (error) {
				console.log(`     ⚠️  Error: ${error.message}`);
				contractResults.push({
					method,
					valid: false,
					error: error.message
				});
				totalValidations++;
			}
		});

		// Get performance metrics
		const performanceMetrics = this.tester.getPerformanceMetrics();

		// Generate comprehensive report
		const report = {
			metadata: {
				timestamp,
				reportType: 'API Contract Validation',
				version: '1.0.0',
				generator: 'Verenigingen Contract Reporter'
			},

			summary: {
				totalContracts: methods.length,
				validContracts: passedValidations,
				failedContracts: totalValidations - passedValidations,
				successRate: `${((passedValidations / totalValidations) * 100).toFixed(2)}%`,
				performanceMetrics
			},

			contracts: contractResults,

			analysis: {
				criticalAPIs: this.analyzeCriticalAPIs(contractResults),
				coverageGaps: this.identifyCoverageGaps(methods),
				performanceInsights: this.analyzePerformance(performanceMetrics),
				recommendations: this.generateRecommendations(contractResults)
			}
		};

		// Save reports
		this.saveReport('comprehensive-contract-report.json', report);
		this.generateMarkdownReport(report);
		this.generateCoverageMatrix(contractResults);

		console.log('\n📄 Reports Generated:');
		console.log(`   - JSON Report: ${this.reportDir}/comprehensive-contract-report.json`);
		console.log(`   - Markdown Report: ${this.reportDir}/contract-report.md`);
		console.log(`   - Coverage Matrix: ${this.reportDir}/coverage-matrix.json`);

		// Return summary for CI/CD
		return {
			passed: passedValidations === totalValidations,
			totalContracts: totalValidations,
			passedContracts: passedValidations,
			successRate: report.summary.successRate
		};
	}

	analyzeCriticalAPIs(contractResults) {
		const criticalKeywords = ['payment', 'sepa', 'mandate', 'mollie', 'financial', 'member'];

		const criticalAPIs = contractResults.filter(result =>
			criticalKeywords.some(keyword =>
				result.method.toLowerCase().includes(keyword)
			)
		);

		return {
			total: criticalAPIs.length,
			valid: criticalAPIs.filter(api => api.valid).length,
			apis: criticalAPIs.map(api => ({
				method: api.method,
				status: api.valid ? 'valid' : 'failed',
				criticality: this.assessCriticality(api.method)
			}))
		};
	}

	assessCriticality(method) {
		if (method.includes('payment') || method.includes('mollie')) { return 'high'; }
		if (method.includes('sepa') || method.includes('mandate')) { return 'high'; }
		if (method.includes('member') || method.includes('financial')) { return 'medium'; }
		return 'low';
	}

	identifyCoverageGaps(methods) {
		const gaps = {
			missing: [
				'SEPA mandate creation and validation',
				'Direct debit batch processing',
				'Mollie payment integration',
				'Membership lifecycle management',
				'Chapter assignment workflows'
			],
			priority: 'high',
			impact: 'These gaps may allow integration issues to reach production'
		};

		return gaps;
	}

	analyzePerformance(metrics) {
		return {
			cacheEfficiency: metrics.overall.cacheHitRate,
			avgValidationTime: metrics.overall.avgValidationTime,
			compilationOverhead: metrics.overall.totalCompilationTime,
			recommendations: metrics.overall.cacheHitRate.includes('0')
				? ['Implement validator caching for better performance']
				: ['Performance is optimized with caching']
		};
	}

	generateRecommendations(contractResults) {
		const recommendations = [];

		const failedContracts = contractResults.filter(r => !r.valid);
		if (failedContracts.length > 0) {
			recommendations.push({
				type: 'critical',
				message: `Fix ${failedContracts.length} failed contract validations`,
				action: 'Review schema definitions and test data generation'
			});
		}

		const criticalMissing = [
			'verenigingen.verenigingen.doctype.sepa_mandate.sepa_mandate.create_mandate',
			'verenigingen.verenigingen_payments.utils.mollie_integration.create_payment'
		];

		recommendations.push({
			type: 'enhancement',
			message: 'Expand coverage to critical financial APIs',
			action: 'Add contracts for SEPA and Mollie operations'
		});

		recommendations.push({
			type: 'maintenance',
			message: 'Regular contract validation',
			action: 'Run contract validation in CI/CD pipeline'
		});

		return recommendations;
	}

	generateMarkdownReport(report) {
		const markdown = `# API Contract Validation Report
        
## 📊 Summary
- **Generated**: ${report.metadata.timestamp}
- **Total Contracts**: ${report.summary.totalContracts}
- **Success Rate**: ${report.summary.successRate}
- **Performance**: ${report.summary.performanceMetrics.overall.avgValidationTime} avg validation time

## 🎯 Contract Status

| Method | Status | Performance |
|--------|--------|-------------|
${report.contracts.map(contract =>
		`| ${contract.method} | ${contract.valid ? '✅ Valid' : '❌ Failed'} | ${contract.performance?.validationTime || 'N/A'}ms |`
	).join('\n')}

## 🔍 Critical APIs Analysis
- **Total Critical APIs**: ${report.analysis.criticalAPIs.total}
- **Valid Critical APIs**: ${report.analysis.criticalAPIs.valid}
- **Critical Success Rate**: ${((report.analysis.criticalAPIs.valid / report.analysis.criticalAPIs.total) * 100).toFixed(1)}%

## 📈 Performance Insights
- **Cache Hit Rate**: ${report.summary.performanceMetrics.overall.cacheHitRate}
- **Average Validation Time**: ${report.summary.performanceMetrics.overall.avgValidationTime}
- **Cached Validators**: ${report.summary.performanceMetrics.overall.cachedValidators}

## 💡 Recommendations
${report.analysis.recommendations.map(rec =>
		`- **${rec.type.toUpperCase()}**: ${rec.message}\n  - Action: ${rec.action}`
	).join('\n')}

## 📋 Coverage Gaps
${report.analysis.coverageGaps.missing.map(gap => `- ${gap}`).join('\n')}

---
*Generated by Verenigingen Contract Reporter v${report.metadata.version}*
`;

		this.saveReport('contract-report.md', markdown);
	}

	generateCoverageMatrix(contractResults) {
		const matrix = {
			domains: {
				financial: contractResults.filter(r =>
					r.method.includes('payment') || r.method.includes('mollie')
				),
				sepa: contractResults.filter(r =>
					r.method.includes('sepa') || r.method.includes('mandate')
				),
				membership: contractResults.filter(r =>
					r.method.includes('member') && !r.method.includes('payment')
				),
				chapter: contractResults.filter(r =>
					r.method.includes('chapter')
				),
				donation: contractResults.filter(r =>
					r.method.includes('donation')
				)
			},

			maturity: {
				production: contractResults.filter(r => r.valid).length,
				development: contractResults.filter(r => !r.valid).length,
				missing: 0 // Would need analysis of actual codebase
			}
		};

		this.saveReport('coverage-matrix.json', matrix);
	}

	saveReport(filename, data) {
		const filePath = path.join(this.reportDir, filename);
		const content = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
		fs.writeFileSync(filePath, content);
	}
}

// Execute report generation
const generator = new ContractReportGenerator();

try {
	const result = generator.generateComprehensiveReport();

	console.log('\n🏁 Report Generation Complete');
	console.log(`   Success Rate: ${result.successRate}`);
	console.log(`   Contracts: ${result.passedContracts}/${result.totalContracts}`);

	if (!result.passed) {
		console.log('❌ Some contracts failed validation');
		process.exit(1);
	} else {
		console.log('✅ All contracts validated successfully');
		process.exit(0);
	}
} catch (error) {
	console.error('❌ Report generation failed:', error.message);
	process.exit(1);
}
