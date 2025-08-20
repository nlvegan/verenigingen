/**
 * @fileoverview API Contract Performance Tests
 *
 * Tests the performance improvements from validator caching
 * and validates that the optimization works as expected.
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 */

const { SimpleAPIContractTester } = require('../setup/api-contract-simple');

require('../setup/frappe-mocks').setupTestMocks();

describe('API Contract Performance Tests', () => {
	let tester;

	beforeEach(() => {
		tester = new SimpleAPIContractTester();
	});

	describe('Validator Caching', () => {
		it('should cache compiled validators for repeated use', () => {
			const method = 'verenigingen.verenigingen.doctype.member.member.process_payment';
			const validArgs = { member_id: 'Assoc-Member-2025-07-0001', payment_amount: 25.00, payment_method: 'SEPA Direct Debit' };

			// First validation - should compile and cache
			const result1 = tester.validateFrappeCall({ method, args: validArgs });
			expect(result1.valid).toBe(true);
			expect(result1.performance.cacheHit).toBe(false);
			expect(result1.performance.compilationTime).toBeGreaterThan(0);

			// Second validation - should use cache
			const result2 = tester.validateFrappeCall({ method, args: validArgs });
			expect(result2.valid).toBe(true);
			expect(result2.performance.cacheHit).toBe(true);
			expect(result2.performance.compilationTime).toBe(0);
		});

		it('should show significant performance improvement with caching', () => {
			const method = 'verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban';
			const validArgs = { iban: 'NL91ABNA0417164300' };

			// Measure performance without cache (first call)
			const startTime1 = performance.now();
			const result1 = tester.validateFrappeCall({ method, args: validArgs });
			const firstCallTime = performance.now() - startTime1;

			expect(result1.valid).toBe(true);
			expect(result1.performance.cacheHit).toBe(false);

			// Measure performance with cache (subsequent calls)
			const startTime2 = performance.now();
			const result2 = tester.validateFrappeCall({ method, args: validArgs });
			const cachedCallTime = performance.now() - startTime2;

			expect(result2.valid).toBe(true);
			expect(result2.performance.cacheHit).toBe(true);

			// Cached call should be significantly faster
			expect(cachedCallTime).toBeLessThan(firstCallTime * 0.5); // At least 50% faster
		});

		it('should maintain separate cache entries for different methods', () => {
			const method1 = 'verenigingen.verenigingen.doctype.member.member.process_payment';
			const method2 = 'verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban';

			const args1 = { member_id: 'Assoc-Member-2025-07-0001', payment_amount: 25.00, payment_method: 'SEPA Direct Debit' };
			const args2 = { iban: 'NL91ABNA0417164300' };

			// Validate different methods
			tester.validateFrappeCall({ method: method1, args: args1 });
			tester.validateFrappeCall({ method: method2, args: args2 });

			const metrics = tester.getPerformanceMetrics();

			expect(metrics.overall.cachedValidators).toBe(2);
			expect(metrics.byMethod[method1]).toBeDefined();
			expect(metrics.byMethod[method2]).toBeDefined();
		});
	});

	describe('Performance Metrics', () => {
		it('should track overall performance metrics', () => {
			const method = 'verenigingen.verenigingen.doctype.member.member.process_payment';
			const validArgs = { member_id: 'Assoc-Member-2025-07-0001', payment_amount: 25.00, payment_method: 'SEPA Direct Debit' };

			// Perform multiple validations
			for (let i = 0; i < 5; i++) {
				tester.validateFrappeCall({ method, args: validArgs });
			}

			const metrics = tester.getPerformanceMetrics();

			expect(metrics.overall.totalValidations).toBe(5);
			expect(metrics.overall.totalCacheHits).toBe(4); // All but the first
			expect(metrics.overall.cacheHitRate).toBe('80.00%');
			expect(metrics.overall.cachedValidators).toBe(1);
		});

		it('should track per-method performance metrics', () => {
			const method = 'verenigingen.verenigingen.doctype.member.member.process_payment';
			const validArgs = { member_id: 'Assoc-Member-2025-07-0001', payment_amount: 25.00, payment_method: 'SEPA Direct Debit' };

			// Perform multiple validations
			for (let i = 0; i < 3; i++) {
				tester.validateFrappeCall({ method, args: validArgs });
			}

			const metrics = tester.getPerformanceMetrics();
			const methodMetrics = metrics.byMethod[method];

			expect(methodMetrics.validations).toBe(3);
			expect(methodMetrics.cacheHits).toBe(2);
			expect(methodMetrics.cacheHitRate).toBe('66.67%');
			expect(methodMetrics.compilationTime).toBeGreaterThan(0);
			expect(methodMetrics.avgValidationTime).toBeDefined();
		});

		it('should clear cache and reset metrics', () => {
			const method = 'verenigingen.verenigingen.doctype.member.member.process_payment';
			const validArgs = { member_id: 'Assoc-Member-2025-07-0001', payment_amount: 25.00, payment_method: 'SEPA Direct Debit' };

			// Perform validation to populate cache
			tester.validateFrappeCall({ method, args: validArgs });

			let metrics = tester.getPerformanceMetrics();
			expect(metrics.overall.totalValidations).toBe(1);
			expect(metrics.overall.cachedValidators).toBe(1);

			// Clear cache
			tester.clearCache();

			metrics = tester.getPerformanceMetrics();
			expect(metrics.overall.totalValidations).toBe(0);
			expect(metrics.overall.totalCacheHits).toBe(0);
			expect(metrics.overall.cachedValidators).toBe(0);
		});
	});

	describe('Performance Benchmarking', () => {
		it('should demonstrate cache performance gains', () => {
			const methods = [
				'verenigingen.verenigingen.doctype.member.member.process_payment',
				'verenigingen.verenigingen.doctype.member.member.get_current_dues_schedule_details',
				'verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban'
			];

			const testData = {
				'verenigingen.verenigingen.doctype.member.member.process_payment':
                    { member_id: 'Assoc-Member-2025-07-0001', payment_amount: 25.00, payment_method: 'SEPA Direct Debit' },
				'verenigingen.verenigingen.doctype.member.member.get_current_dues_schedule_details':
                    { member: 'ASSOC-MEMBER-2025-002' },
				'verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban':
                    { iban: 'NL91ABNA0417164300' }
			};

			// Perform initial validations (cache misses)
			const initialStart = performance.now();
			methods.forEach(method => {
				tester.validateFrappeCall({ method, args: testData[method] });
			});
			const initialTime = performance.now() - initialStart;

			// Perform cached validations
			const cachedStart = performance.now();
			methods.forEach(method => {
				tester.validateFrappeCall({ method, args: testData[method] });
			});
			const cachedTime = performance.now() - cachedStart;

			// Cached execution should be significantly faster
			expect(cachedTime).toBeLessThan(initialTime * 0.6); // At least 40% improvement

			const metrics = tester.getPerformanceMetrics();
			console.log('🚀 Performance Benchmark Results:');
			console.log(`   Initial (no cache): ${initialTime.toFixed(3)}ms`);
			console.log(`   Cached: ${cachedTime.toFixed(3)}ms`);
			console.log(`   Performance improvement: ${((initialTime - cachedTime) / initialTime * 100).toFixed(1)}%`);
			console.log(`   Cache hit rate: ${metrics.overall.cacheHitRate}`);
		});

		it('should maintain performance under load', () => {
			const method = 'verenigingen.verenigingen.doctype.member.member.process_payment';
			const validArgs = { member_id: 'Assoc-Member-2025-07-0001', payment_amount: 25.00, payment_method: 'SEPA Direct Debit' };

			// Perform many validations to test sustained performance
			const iterations = 100;
			const startTime = performance.now();

			for (let i = 0; i < iterations; i++) {
				const result = tester.validateFrappeCall({ method, args: validArgs });
				expect(result.valid).toBe(true);
			}

			const totalTime = performance.now() - startTime;
			const avgTimePerValidation = totalTime / iterations;

			// Should maintain reasonable performance (less than 5ms per validation with caching)
			expect(avgTimePerValidation).toBeLessThan(5.0);

			const metrics = tester.getPerformanceMetrics();
			expect(metrics.overall.cacheHitRate).toBe('99.00%'); // 99/100 cache hits

			console.log('📊 Load Performance Results:');
			console.log(`   Total validations: ${iterations}`);
			console.log(`   Total time: ${totalTime.toFixed(3)}ms`);
			console.log(`   Average per validation: ${avgTimePerValidation.toFixed(3)}ms`);
			console.log(`   Cache hit rate: ${metrics.overall.cacheHitRate}`);
		});
	});

	describe('Enhanced Error Messages', () => {
		it('should provide similar method suggestions for unknown methods', () => {
			const result = tester.validateFrappeCall({
				method: 'verenigingen.verenigingen.doctype.member.member.process_payments', // Wrong: 'payments' instead of 'payment'
				args: { member_id: 'Assoc-Member-2025-07-0001', payment_amount: 25.00, payment_method: 'SEPA Direct Debit' }
			});

			expect(result.valid).toBe(false);
			expect(result.errors[0].message).toContain('No API schema defined');
			expect(result.errors[0].availableMethods).toBeInstanceOf(Array);
			expect(result.errors[0].suggestion).toBe('verenigingen.verenigingen.doctype.member.member.process_payment');
		});

		it('should include performance data in validation results', () => {
			const result = tester.validateFrappeCall({
				method: 'verenigingen.verenigingen.doctype.member.member.process_payment',
				args: { member_id: 'Assoc-Member-2025-07-0001', payment_amount: 25.00, payment_method: 'SEPA Direct Debit' }
			});

			expect(result.performance).toBeDefined();
			expect(result.performance.validationTime).toBeGreaterThan(0);
			expect(result.performance.cacheHit).toBe(false); // First call
			expect(result.performance.compilationTime).toBeGreaterThan(0);
		});
	});
});
