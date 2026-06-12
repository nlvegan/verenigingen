/**
 * @fileoverview Unit tests for the REAL APIService class.
 *
 * Requires the shipped module (verenigingen/public/js/services/api-service.js) so
 * its caching, request deduplication, retry/backoff, OperationResult unwrapping and
 * per-endpoint helpers are measured.
 *
 * The HTTP boundary — `frappe.call` — is stubbed (it is the framework/network edge,
 * not business logic). Every test drives the real APIService code through that stub;
 * retry timing uses a tiny retryDelay with real timers so the actual backoff path runs.
 */

require('../../public/js/services/api-service.js');
const APIService = window.APIService;

let lastCallOpts;

beforeEach(() => {
	lastCallOpts = null;
	global.frappe = {
		csrf_token: undefined,
		// Default behaviour: echo a legacy message containing the method name.
		call: jest.fn((opts) => {
			lastCallOpts = opts;
			opts.callback({ message: { echoed: opts.method } });
		})
	};
});

/** Make frappe.call resolve its callback with the given response object. */
function respondWith(response) {
	frappe.call.mockImplementation((opts) => {
		lastCallOpts = opts;
		opts.callback(response);
	});
}

/** Make frappe.call invoke its error handler with the given HTTP status. */
function failWith(status, statusText = 'Error') {
	frappe.call.mockImplementation((opts) => {
		lastCallOpts = opts;
		opts.error({ status, statusText });
	});
}

describe('APIService', () => {
	describe('client-side short-circuit validators (no network)', () => {
		let api;
		beforeEach(() => {
			api = new APIService();
		});

		test('validateEmail rejects too-short input without calling the backend', async () => {
			await expect(api.validateEmail('ab')).resolves.toEqual({ valid: false, message: 'Email is too short' });
			expect(frappe.call).not.toHaveBeenCalled();
		});

		test('validatePostalCode requires a value', async () => {
			await expect(api.validatePostalCode('')).resolves.toEqual({ valid: false, message: 'Postal code is required' });
			expect(frappe.call).not.toHaveBeenCalled();
		});

		test('validatePhoneNumber treats an empty number as optional/valid', async () => {
			await expect(api.validatePhoneNumber('')).resolves.toEqual({ valid: true, message: 'Phone number is optional' });
			expect(frappe.call).not.toHaveBeenCalled();
		});

		test('validateBirthDate requires a value', async () => {
			await expect(api.validateBirthDate('')).resolves.toEqual({ valid: false, message: 'Birth date is required' });
		});

		test('validateCustomAmount requires both type and amount', async () => {
			await expect(api.validateCustomAmount(null, null)).resolves.toEqual({
				valid: false,
				message: 'Membership type and amount are required'
			});
		});
	});

	describe('response handling in _singleRequest', () => {
		let api;
		beforeEach(() => {
			// retryCount:0 isolates a single attempt: a rejected OperationResult/exc
			// carries no httpStatus, which the retry logic otherwise treats as
			// retryable (covered separately in the retry/backoff describe).
			api = new APIService({ retryCount: 0 });
		});

		test('unwraps a successful OperationResult to its data payload', async () => {
			respondWith({ message: { success: true, data: { member: 'M-001' }, message: 'ok' } });
			await expect(api.call('some.method', { a: 1 })).resolves.toEqual({ member: 'M-001' });
		});

		test('rejects a failed OperationResult with its message', async () => {
			respondWith({ message: { success: false, data: null, message: 'Validation failed' } });
			await expect(api.call('some.method')).rejects.toThrow('Validation failed');
		});

		test('returns a legacy (non-envelope) message as-is', async () => {
			respondWith({ message: { legacy: true } });
			await expect(api.call('some.method')).resolves.toEqual({ legacy: true });
		});

		test('rejects when the response carries a server exception', async () => {
			respondWith({ exc: 'Traceback: boom' });
			await expect(api.call('some.method')).rejects.toThrow('Traceback: boom');
		});

		test('resolves the raw response when there is no message and no exc', async () => {
			respondWith({ rawShape: 42 });
			await expect(api.call('some.method')).resolves.toEqual({ rawShape: 42 });
		});

		test('includes CSRF headers when a token is present', async () => {
			frappe.csrf_token = 'tok-123';
			respondWith({ message: 'ok' });
			await api.call('some.method');
			expect(lastCallOpts.headers['X-CSRF-Token']).toBe('tok-123');
			expect(lastCallOpts.headers['X-Frappe-CSRF-Token']).toBe('tok-123');
		});

		test('omits CSRF headers when no token is set', async () => {
			respondWith({ message: 'ok' });
			await api.call('some.method');
			expect(lastCallOpts.headers['X-CSRF-Token']).toBeUndefined();
		});
	});

	describe('retry / backoff in _makeRequest', () => {
		test('does NOT retry on a 4xx client error', async () => {
			const api = new APIService({ retryCount: 3, retryDelay: 1 });
			failWith(404, 'Not Found');

			await expect(api.call('some.method')).rejects.toMatchObject({ httpStatus: 404 });
			expect(frappe.call).toHaveBeenCalledTimes(1);
		});

		test('retries on a 5xx error up to retryCount then throws', async () => {
			const api = new APIService({ retryCount: 2, retryDelay: 1 });
			failWith(503, 'Unavailable');

			await expect(api.call('some.method')).rejects.toMatchObject({ httpStatus: 503 });
			// initial attempt + 2 retries = 3 calls
			expect(frappe.call).toHaveBeenCalledTimes(3);
		});

		test('recovers when a retry succeeds', async () => {
			const api = new APIService({ retryCount: 3, retryDelay: 1 });
			let attempt = 0;
			frappe.call.mockImplementation((opts) => {
				attempt += 1;
				if (attempt === 1) {
					opts.error({ status: 500, statusText: 'Server Error' });
				} else {
					opts.callback({ message: { recovered: true } });
				}
			});

			await expect(api.call('some.method')).resolves.toEqual({ recovered: true });
			expect(frappe.call).toHaveBeenCalledTimes(2);
		});
	});

	describe('caching and deduplication', () => {
		test('a cached call hits the backend only once', async () => {
			const api = new APIService();
			respondWith({ message: { value: 1 } });

			const first = await api.call('cached.method', {}, { cache: true });
			const second = await api.call('cached.method', {}, { cache: true });

			expect(first).toEqual({ value: 1 });
			expect(second).toEqual({ value: 1 });
			expect(frappe.call).toHaveBeenCalledTimes(1);
		});

		test('an expired cache entry triggers a refetch', async () => {
			const api = new APIService();
			respondWith({ message: { value: 1 } });

			await api.call('m', {}, { cache: true });
			// Age the cached entry past the default TTL to force a refetch.
			api.cache.get(api._getCacheKey('m', {})).timestamp = 0;
			await api.call('m', {}, { cache: true });

			expect(frappe.call).toHaveBeenCalledTimes(2);
		});

		test('deduplicates identical in-flight requests', async () => {
			const api = new APIService();
			// Defer the callback so both calls are queued before resolution.
			frappe.call.mockImplementation((opts) => {
				Promise.resolve().then(() => opts.callback({ message: { v: 1 } }));
			});

			const [a, b] = await Promise.all([api.call('dup.method'), api.call('dup.method')]);

			expect(a).toEqual({ v: 1 });
			expect(b).toEqual({ v: 1 });
			expect(frappe.call).toHaveBeenCalledTimes(1);
		});
	});

	describe('cache utilities', () => {
		test('_getCacheKey is method + serialised args', () => {
			const api = new APIService();
			expect(api._getCacheKey('m', { b: 2, a: 1 })).toBe('m:{"b":2,"a":1}');
		});

		test('clearCache(pattern) removes only matching keys', () => {
			const api = new APIService();
			api.cache.set('a.method:{}', { data: 1, timestamp: 0 });
			api.cache.set('b.method:{}', { data: 2, timestamp: 0 });

			api.clearCache('a.method');

			expect(api.cache.has('a.method:{}')).toBe(false);
			expect(api.cache.has('b.method:{}')).toBe(true);
		});

		test('clearCache() empties the whole cache', () => {
			const api = new APIService();
			api.cache.set('x', { data: 1, timestamp: 0 });
			api.clearCache();
			expect(api.cache.size).toBe(0);
		});

		test('getCacheStats reports size, keys and a memory estimate', () => {
			const api = new APIService();
			api.cache.set('x:{}', { data: 1, timestamp: 0 });
			const stats = api.getCacheStats();
			expect(stats.size).toBe(1);
			expect(stats.keys).toContain('x:{}');
			expect(typeof stats.memoryUsage).toBe('number');
		});
	});

	describe('endpoint helpers delegate to the correct backend method', () => {
		let api;
		beforeEach(() => {
			api = new APIService();
			respondWith({ message: { ok: true } });
		});

		const cases = [
			['getFormData', [], 'get_application_form_data'],
			['validateEmail', ['jan@example.com'], 'validate_email'],
			['validatePostalCode', ['3511AB', 'Netherlands'], 'validate_postal_code'],
			['validatePhoneNumber', ['+31612345678'], 'validate_phone_number'],
			['validateBirthDate', ['1990-01-01'], 'validate_birth_date'],
			['validateCustomAmount', ['Regular', 25], 'validate_custom_amount'],
			['getMembershipTypeDetails', ['Regular'], 'get_membership_type_details'],
			['getSuggestedAmounts', ['Regular'], 'suggest_membership_amounts'],
			['getPaymentMethods', [], 'get_payment_methods'],
			['saveDraft', [{ x: 1 }], 'save_draft_application'],
			['loadDraft', ['D-1'], 'load_draft_application'],
			['submitApplication', [{ x: 1 }], 'submit_application_with_tracking'],
			['checkApplicationStatus', ['A-1'], 'check_application_status'],
			['checkEligibility', [{ x: 1 }], 'check_application_eligibility']
		];

		test.each(cases)('%s -> %s', async (methodName, args, backendSuffix) => {
			await api[methodName](...args);
			expect(lastCallOpts.method).toContain(backendSuffix);
		});

		test('submitApplication clears the cache before submitting', async () => {
			const clearSpy = jest.spyOn(api, 'clearCache');
			await api.submitApplication({ x: 1 });
			expect(clearSpy).toHaveBeenCalled();
		});
	});

	describe('batchCall', () => {
		test('returns each result, capturing per-request errors', async () => {
			const api = new APIService({ retryCount: 0, retryDelay: 1 });
			frappe.call.mockImplementation((opts) => {
				if (opts.method === 'good') {
					opts.callback({ message: { ok: 1 } });
				} else {
					opts.error({ status: 400, statusText: 'Bad' });
				}
			});

			const results = await api.batchCall([
				{ method: 'good', args: {}, options: {} },
				{ method: 'bad', args: {}, options: {} }
			]);

			expect(results[0]).toEqual({ ok: 1 });
			expect(results[1].error).toBeInstanceOf(Error);
		});
	});
});
