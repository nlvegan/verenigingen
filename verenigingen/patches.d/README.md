# Patch fragments (#2407)

**`patches.txt`'s `[post_model_sync]` section is frozen.** Register a new post_model_sync patch as
one file here instead:

```
verenigingen/patches.d/post_model_sync/<YYYYMMDDTHHMM>-<slug>.txt
```

The file holds exactly the line you would have appended to `patches.txt`, for example
`verenigingen.patches.v2_2.my_patch_1234`. Comment lines starting with `#` are allowed. Use the
current UTC time for the timestamp.

## Why

Every PR that appended to `patches.txt` conflicted with the next one to merge. The merge queue then
dropped it, and its full CI had to run again: 13 times in two days (#2376). Two new files never
conflict.

## How it runs

`verenigingen.setup.patch_fragments.install` (a `before_migrate` and `before_install` hook) wraps
Frappe's `patch_handler.get_patches_from_app`. As a result:

- `bench migrate` runs fragments inside the post_model_sync pass, right after this app's
  `patches.txt` entries, in filename (timestamp) order. That is before fixtures and
  `after_migrate`, exactly where a `patches.txt` line would run.
- `install-app` marks them complete without running them, like every `patches.txt` entry.
- Patch Log records the fragment's line, as it would a `patches.txt` line.

A malformed fragment fails the migrate with the file named:
- a bad name;
- not exactly one entry;
- a duplicate of another entry.

`test_patch_fragments_2407` also checks that every committed fragment's dotted module imports
with an `execute()`. That check is not run at migrate time, because an already-executed fragment
must keep working after its module is gone, as a `patches.txt` line does. **If you delete a
patch module, delete its fragment in the same PR.**

## Notes

- **Order:** a patch that must run after another one needs a later timestamp.
- **pre_model_sync:** rare (5 entries), so it still goes in `patches.txt`.
- **Testing registration:** in a test, assert your entry is in
  `frappe.modules.patch_handler.get_patches_from_app("verenigingen")` after calling
  `verenigingen.setup.patch_fragments.install()`. Do not read `patches.txt` directly.
