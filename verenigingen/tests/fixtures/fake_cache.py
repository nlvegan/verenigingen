# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
In-process, dict-backed cache isolation for ``frappe.cache``.

WHY THIS EXISTS
---------------
"Server Tests" CI runs 8 test shards as parallel PROCESSES against ONE shared
MariaDB and ONE shared redis. When any sibling shard calls
``frappe.clear_cache()`` it FLUSHES the entire shared redis db -- wiping every
key regardless of how unique that key's name is. Tests that assert "a value I
just put in ``frappe.cache()`` is readable a moment later" therefore fail
non-deterministically: a sibling's flush can evict the value between the
``set_value`` and the ``get_value``, even with a per-test unique key.

A per-process in-memory dict is immune to a redis FLUSH issued by another OS
process (they share no memory). Routing a small allow-list of cache keys
through such a dict for the duration of one test makes the set->get / lock
round-trip deterministic while still exercising the REAL caching/locking
*logic* under test (the code still calls get_value/set_value/delete_value and
branches on the results).

IMPORTANT IMPLEMENTATION NOTES
------------------------------
``frappe.cache`` is a MODULE GLOBAL holding a ``RedisWrapper`` instance. It is
used both as an object (``frappe.cache.hget(...)`` -- e.g. the translation
machinery) AND as a call (``frappe.cache().get_value(...)`` -- RedisWrapper
.__call__ returns ``self`` for backward-compat). The Frappe framework itself
relies on the full RedisWrapper API constantly (translations, messages,
``frappe.throw``, doctype meta, ...). So we must NOT swap in a bare Mock and we
must preserve BOTH access styles.

This wrapper therefore:
  * is itself callable and returns ``self`` (so ``frappe.cache()`` works),
  * delegates every attribute to the real RedisWrapper via ``__getattr__``
    (so ``frappe.cache.hget`` / framework internals keep working against real
    redis),
  * overrides get_value/set_value/delete_value ONLY for keys in the supplied
    allow-list, routing those to an in-process dict; all other keys still hit
    real redis.

We patch the module global ``frappe.cache`` with this wrapper INSTANCE (not a
Mock), keeping the framework fully functional while isolating exactly the keys
the test cares about from a sibling's FLUSH.
"""

from contextlib import contextmanager

import frappe


class _IsolatingCacheWrapper:
    """Wrap the real cache object; route allow-listed keys to an in-process dict."""

    def __init__(self, real_cache, isolated_prefixes, store):
        # Use object.__setattr__-free plain assignment but guard __getattr__
        # against these names by storing them as instance attributes that exist
        # before any delegation can occur (they are set in __dict__ directly).
        self.__dict__["_real"] = real_cache
        self.__dict__["_prefixes"] = tuple(isolated_prefixes)
        self.__dict__["_store"] = store

    def __call__(self):
        # frappe.cache() -> self (mirrors RedisWrapper.__call__).
        return self

    def _is_isolated(self, key):
        return isinstance(key, str) and key.startswith(self._prefixes)

    def get_value(self, key, *args, **kwargs):
        if self._is_isolated(key):
            return self._store.get(key)
        return self._real.get_value(key, *args, **kwargs)

    def set_value(self, key, value, *args, **kwargs):
        if self._is_isolated(key):
            # ``expires_in_sec`` and other extras are accepted and ignored --
            # in-memory storage has no TTL; the isolated tests assert on value
            # presence/branching, not redis-level expiry.
            self._store[key] = value
            return None
        return self._real.set_value(key, value, *args, **kwargs)

    def delete_value(self, key, *args, **kwargs):
        if self._is_isolated(key):
            self._store.pop(key, None)
            return None
        return self._real.delete_value(key, *args, **kwargs)

    def __getattr__(self, name):
        # Everything else (hget, hset, sadd, delete_keys, the framework's own
        # cache usage, ...) delegates to the real RedisWrapper unchanged.
        return getattr(self.__dict__["_real"], name)


@contextmanager
def isolate_cache_keys(*key_prefixes):
    """Isolate cache keys matching ``key_prefixes`` to a per-process dict.

    Inside the ``with`` block, ``frappe.cache`` is a wrapper whose
    get/set/delete_value route any key starting with one of ``key_prefixes``
    through an in-process dict (immune to a sibling shard's redis FLUSH), while
    every other key and every other cache method/attribute hit real redis
    normally so the framework keeps working. Both ``frappe.cache`` (object) and
    ``frappe.cache()`` (call -> self) resolve to the wrapper.
    """
    store = {}
    real_cache = frappe.cache  # the live RedisWrapper instance
    wrapper = _IsolatingCacheWrapper(real_cache, key_prefixes, store)
    frappe.cache = wrapper
    try:
        yield store
    finally:
        frappe.cache = real_cache
