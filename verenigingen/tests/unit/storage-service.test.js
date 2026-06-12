/**
 * @fileoverview Unit tests for the REAL StorageService class.
 *
 * Requires the shipped module (verenigingen/public/js/services/storage-service.js)
 * so its draft persistence, server/local fallback, sanitisation, cleanup, stats and
 * session helpers are measured. Runs against the jsdom localStorage/sessionStorage
 * doubles (the storage browser boundary). The optional API service is injected as a
 * test double for the server-draft path; all draft/sanitise/cleanup logic is real.
 */

require('../../public/js/services/storage-service.js');
const StorageService = window.StorageService;

beforeEach(() => {
	window.localStorage.clear();
	window.sessionStorage.clear();
});

/** Build a StorageService with no server API (local-only) unless one is supplied. */
function makeStorage(api = null, options = {}) {
	return new StorageService(api, options);
}

describe('StorageService', () => {
	describe('initialisation', () => {
		test('detects available storage backends', () => {
			const storage = makeStorage();
			expect(storage.storageAvailable.localStorage).toBe(true);
			expect(storage.storageAvailable.sessionStorage).toBe(true);
		});

		test('honours custom options merged over defaults', () => {
			const storage = makeStorage(null, { maxDrafts: 2, storagePrefix: 'test_' });
			expect(storage.options.maxDrafts).toBe(2);
			expect(storage.options.storagePrefix).toBe('test_');
			expect(storage.options.autoSaveInterval).toBe(30000); // default preserved
		});
	});

	describe('dirty state', () => {
		test('markDirty / markClean flip the flag and stamp lastSaved', () => {
			const storage = makeStorage();
			storage.markDirty();
			expect(storage.isDirty).toBe(true);
			storage.markClean();
			expect(storage.isDirty).toBe(false);
			expect(storage.lastSaved).toBeInstanceOf(Date);
		});
	});

	describe('saveDraft (local only)', () => {
		test('persists data to localStorage and reports success', async () => {
			const storage = makeStorage();
			const result = await storage.saveDraft({ firstName: 'Jan' }, false);

			expect(result.success).toBe(true);
			expect(storage.isDirty).toBe(false); // markClean ran
			const drafts = storage.getAllDrafts();
			expect(drafts.length).toBeGreaterThanOrEqual(1);
		});

		test('refuses to save empty data', async () => {
			const storage = makeStorage();
			const result = await storage.saveDraft({}, false);
			expect(result.success).toBe(false);
			expect(result.message).toBe('No data to save');
		});

		test('uses the getData callback when no explicit data is passed', async () => {
			const storage = makeStorage();
			storage.getDataCallback = () => ({ city: 'Utrecht' });
			const result = await storage.saveDraft(null, false);
			expect(result.success).toBe(true);
		});
	});

	describe('saveDraft (with server API)', () => {
		test('records the server draft id on a successful server save', async () => {
			const api = { saveDraft: jest.fn(async () => ({ success: true, draft_id: 'SRV-1' })) };
			const storage = makeStorage(api);

			const result = await storage.saveDraft({ firstName: 'Jan' }, true);

			expect(api.saveDraft).toHaveBeenCalled();
			expect(storage.currentDraftId).toBe('SRV-1');
			expect(result.success).toBe(true);
		});

		test('degrades gracefully to local-only when the server save throws', async () => {
			const api = {
				saveDraft: jest.fn(async () => {
					throw new Error('offline');
				})
			};
			const storage = makeStorage(api);

			const result = await storage.saveDraft({ firstName: 'Jan' }, true);

			// local save still succeeded
			expect(result.success).toBe(true);
			expect(result.server.success).toBe(false);
		});
	});

	describe('loadDraft', () => {
		test('loads the most recent draft from localStorage', async () => {
			const storage = makeStorage();
			await storage.saveDraft({ firstName: 'Saved' }, false);

			const result = await storage.loadDraft();

			expect(result.success).toBe(true);
			expect(result.source).toBe('local');
			expect(result.data.firstName).toBe('Saved');
		});

		test('returns not-found when there is no draft', async () => {
			const storage = makeStorage();
			const result = await storage.loadDraft();
			expect(result.success).toBe(false);
			expect(result.message).toBe('No draft found');
		});

		test('prefers the server when a draft id and API are supplied', async () => {
			const api = { loadDraft: jest.fn(async () => ({ success: true, data: { fromServer: true } })) };
			const storage = makeStorage(api);

			const result = await storage.loadDraft('SRV-9');

			expect(api.loadDraft).toHaveBeenCalledWith('SRV-9');
			expect(result.source).toBe('server');
			expect(result.data.fromServer).toBe(true);
		});

		test('falls back to local storage when the server load throws', async () => {
			const api = {
				loadDraft: jest.fn(async () => {
					throw new Error('boom');
				})
			};
			const storage = makeStorage(api);
			await storage.saveDraft({ local: true }, false);

			const result = await storage.loadDraft('SRV-9');

			expect(result.source).toBe('local');
			expect(result.data.local).toBe(true);
		});
	});

	describe('sanitisation', () => {
		test('strips sensitive fields before local persistence (encryptSensitive on)', async () => {
			const storage = makeStorage(null, { encryptSensitive: true });
			await storage.saveDraft({ firstName: 'Jan', bankAccount: 'NL..', ssn: '123' }, false);

			const loaded = await storage.loadDraft();
			expect(loaded.data.firstName).toBe('Jan');
			expect(loaded.data.bankAccount).toBeUndefined();
			expect(loaded.data.ssn).toBeUndefined();
		});

		test('keeps all fields when encryptSensitive is off', () => {
			const storage = makeStorage(null, { encryptSensitive: false });
			const sanitised = storage._sanitizeData({ bankAccount: 'NL..', x: 1 });
			expect(sanitised.bankAccount).toBe('NL..');
		});
	});

	describe('draft management', () => {
		test('getAllDrafts returns drafts newest-first', async () => {
			const storage = makeStorage();
			await storage.saveDraft({ n: 1 }, false);
			await storage.saveDraft({ n: 2 }, false);

			const drafts = storage.getAllDrafts();
			expect(drafts.length).toBeGreaterThanOrEqual(2);
			expect(drafts[0].timestamp >= drafts[1].timestamp).toBe(true);
		});

		test('deleteDraft removes a specific draft and clears the current ref', async () => {
			const storage = makeStorage();
			await storage.saveDraft({ n: 1 }, false);
			const draftId = storage.currentDraftId;

			storage.deleteDraft(draftId);

			expect(storage.currentDraftId).toBeNull();
			expect(storage.getAllDrafts().find((d) => d.id === draftId)).toBeUndefined();
		});

		test('clearAllDrafts removes everything under the prefix', async () => {
			const storage = makeStorage();
			await storage.saveDraft({ n: 1 }, false);
			await storage.saveDraft({ n: 2 }, false);

			storage.clearAllDrafts();

			expect(storage.getAllDrafts()).toHaveLength(0);
			expect(storage.currentDraftId).toBeNull();
		});

		test('_cleanupOldDrafts trims down to maxDrafts on construction', async () => {
			// Seed 4 drafts, then a fresh service with maxDrafts:2 prunes the oldest.
			const seeder = makeStorage(null, { maxDrafts: 100 });
			for (let i = 0; i < 4; i++) {
				await seeder.saveDraft({ n: i }, false);
			}
			expect(seeder.getAllDrafts().length).toBe(4);

			const pruned = makeStorage(null, { maxDrafts: 2 });
			expect(pruned.getAllDrafts().length).toBe(2);
		});
	});

	describe('getStorageStats', () => {
		test('reports usage, draft count and live flags', async () => {
			const storage = makeStorage();
			await storage.saveDraft({ n: 1 }, false);

			const stats = storage.getStorageStats();
			expect(stats.draftCount).toBeGreaterThanOrEqual(1);
			expect(stats.usedSpace).toBeGreaterThan(0);
			expect(stats.isDirty).toBe(false);
			expect(stats.autoSaveActive).toBe(false);
		});
	});

	describe('session storage helpers', () => {
		test('round-trips a value through session storage', () => {
			const storage = makeStorage();
			storage.setSessionData('wizardStep', 3);
			expect(storage.getSessionData('wizardStep')).toBe(3);
		});

		test('returns null for a missing session key', () => {
			const storage = makeStorage();
			expect(storage.getSessionData('nope')).toBeNull();
		});

		test('clearSessionData(key) removes a single key', () => {
			const storage = makeStorage();
			storage.setSessionData('a', 1);
			storage.setSessionData('b', 2);
			storage.clearSessionData('a');
			expect(storage.getSessionData('a')).toBeNull();
			expect(storage.getSessionData('b')).toBe(2);
		});

		test('clearSessionData() removes all app session keys', () => {
			const storage = makeStorage();
			storage.setSessionData('a', 1);
			storage.setSessionData('b', 2);
			storage.clearSessionData();
			expect(storage.getSessionData('a')).toBeNull();
			expect(storage.getSessionData('b')).toBeNull();
		});
	});

	describe('auto-save lifecycle', () => {
		beforeEach(() => jest.useFakeTimers());
		afterEach(() => {
			jest.clearAllTimers();
			jest.useRealTimers();
		});

		test('startAutoSave persists dirty data on each interval, stopAutoSave halts it', async () => {
			const storage = makeStorage(null, { autoSaveInterval: 1000 });
			const saveSpy = jest.spyOn(storage, 'saveDraft');
			storage.startAutoSave(() => ({ x: 1 }));
			storage.markDirty();

			await jest.advanceTimersByTimeAsync(1000);
			expect(saveSpy).toHaveBeenCalled();
			expect(storage.autoSaveTimer).not.toBeNull();

			storage.stopAutoSave();
			expect(storage.autoSaveTimer).toBeNull();
		});

		test('restarting auto-save clears the previous interval', () => {
			const storage = makeStorage();
			storage.startAutoSave(() => ({}));
			const firstTimer = storage.autoSaveTimer;
			storage.startAutoSave(() => ({}));
			expect(storage.autoSaveTimer).not.toBe(firstTimer);
		});
	});

	describe('draft id generation', () => {
		test('produces a prefixed, reasonably unique id', () => {
			const storage = makeStorage();
			const a = storage._generateDraftId();
			const b = storage._generateDraftId();
			expect(a).toMatch(/^local_\d+_[a-z0-9]+$/);
			expect(a).not.toBe(b);
		});
	});

	describe('beforeunload safety net', () => {
		test('a dirty document is flushed to localStorage on page unload', () => {
			const storage = makeStorage();
			storage.markDirty();
			const flushSpy = jest.spyOn(storage, '_saveToLocalStorage');

			window.dispatchEvent(new window.Event('beforeunload'));

			expect(flushSpy).toHaveBeenCalled();
		});
	});

	describe('resilience when localStorage is unavailable', () => {
		/** A service that believes no web storage exists. */
		function unavailableStorage() {
			const storage = makeStorage();
			storage.storageAvailable = { localStorage: false, sessionStorage: false, indexedDB: false };
			return storage;
		}

		test('saveDraft reports the unavailable local backend instead of throwing', async () => {
			const storage = unavailableStorage();
			const result = await storage.saveDraft({ x: 1 }, false);
			// The local leg reports unavailable. (Overall success still defaults true
			// because the skipped server leg is initialised optimistically.)
			expect(result.local.success).toBe(false);
			expect(result.local.message).toBe('localStorage not available');
		});

		test('loadDraft, getAllDrafts and stats stay safe', async () => {
			const storage = unavailableStorage();
			await expect(storage.loadDraft()).resolves.toMatchObject({ success: false });
			expect(storage.getAllDrafts()).toEqual([]);
			expect(storage.getStorageStats().draftCount).toBe(0);
		});

		test('session helpers no-op without sessionStorage', () => {
			const storage = unavailableStorage();
			expect(() => storage.setSessionData('a', 1)).not.toThrow();
			expect(storage.getSessionData('a')).toBeNull();
			expect(() => storage.clearSessionData()).not.toThrow();
			expect(() => storage.clearSessionData('a')).not.toThrow();
		});
	});

	describe('corrupt / failing storage', () => {
		test('getAllDrafts skips entries with unparseable JSON', () => {
			const storage = makeStorage();
			window.localStorage.setItem(`${storage.options.storagePrefix}draft_bad`, '{not valid json');
			expect(() => storage.getAllDrafts()).not.toThrow();
		});

		test('_saveToLocalStorage returns an error result when setItem throws', () => {
			const storage = makeStorage();
			const original = window.localStorage.setItem;
			window.localStorage.setItem = jest.fn(() => {
				throw new Error('QuotaExceeded');
			});
			try {
				const result = storage._saveToLocalStorage({ x: 1 });
				expect(result.success).toBe(false);
				expect(result.error).toBe('QuotaExceeded');
			} finally {
				window.localStorage.setItem = original;
			}
		});

		test('_storageAvailable returns false when the backend throws', () => {
			const storage = makeStorage();
			const original = window.localStorage.setItem;
			window.localStorage.setItem = jest.fn(() => {
				throw new Error('disabled');
			});
			try {
				expect(storage._storageAvailable('localStorage')).toBe(false);
			} finally {
				window.localStorage.setItem = original;
			}
		});
	});
});
