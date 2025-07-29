/**
 * Sample test file to ensure Jest configuration works
 */

describe('Sample Tests', () => {
	test('basic test should pass', () => {
		expect(true).toBe(true);
	});

	test('frappe globals should be available', () => {
		expect(typeof frappe).toBe('object');
		expect(typeof frappe._).toBe('function');
	});

	test('jQuery should be mocked', () => {
		expect(typeof $).toBe('function');
	});

	test('console methods should be mocked', () => {
		// Test that console methods don't throw errors
		console.log('test');
		console.warn('test');
		console.error('test');
    
		expect(console.log).toHaveBeenCalledWith('test');
		expect(console.warn).toHaveBeenCalledWith('test');
		expect(console.error).toHaveBeenCalledWith('test');
	});
});