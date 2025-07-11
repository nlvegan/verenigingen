describe('Sample Test', () => {
	it('should pass a basic test', () => {
		expect(1 + 1).toBe(2);
	});

	it('should test string concatenation', () => {
		const result = 'Hello' + ' ' + 'World';
		expect(result).toBe('Hello World');
	});
});
