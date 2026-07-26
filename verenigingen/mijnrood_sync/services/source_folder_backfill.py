"""Backfill source_folder_id on Organization Documents via SHA256 lookup.

Bench-execute only. Idempotent — safe to re-run; rows already with
source_folder_id set are skipped without a MijnRood query.

Usage:
    bench --site veg11.veganisme.org execute \\
      verenigingen.mijnrood_sync.services.source_folder_backfill.backfill_source_folder_ids \\
      --kwargs '{"dry_run": true}'

Implementation note: if MijnRood does not store SHA256 hashes alongside
documents, _fetch_mijnrood_hash_to_folder must compute them via SFTP per
file. The current implementation tries the DB column first and falls back
to SFTP only if the column doesn't exist or returns no rows.
"""

import frappe

from verenigingen.utils.service_logger import get_service_logger

logger = get_service_logger("verenigingen.mijnrood_sync", prefix="source_folder_backfill")


def backfill_source_folder_ids(dry_run: bool = False, batch_size: int = 200) -> dict:
    """Populate source_folder_id by matching file_hash against MijnRood docs.

    Returns a summary dict with counts.
    """
    if not isinstance(batch_size, int) or batch_size <= 0:
        raise ValueError(f"batch_size must be a positive integer, got {batch_size!r}")

    # Find all Organization Documents missing source_folder_id but having a hash.
    # source_folder_id is an Int NOT NULL DEFAULT 0 column, so "not set" means
    # value = 0 (Frappe's ["is", "not set"] translates to IS NULL which won't match).
    rows = frappe.db.get_all(
        "Organization Document",
        filters={"source_folder_id": ["=", 0], "file_hash": ["is", "set"]},
        fields=["name", "file_hash"],
    )

    already_set = frappe.db.count(
        "Organization Document",
        filters={"source_folder_id": [">", 0]},
    )

    if not rows:
        return {
            "matched": 0,
            "no_hash_match": 0,
            "already_set": already_set,
            "errors": [],
            "dry_run": dry_run,
        }

    # Fetch MijnRood hash → folder_id mapping
    try:
        hash_to_folder = _fetch_mijnrood_hash_to_folder()
    except Exception as e:
        return {
            "matched": 0,
            "no_hash_match": 0,
            "already_set": already_set,
            "errors": [f"MijnRood fetch failed: {e}"],
            "dry_run": dry_run,
        }

    matched = 0
    no_hash_match = 0
    errors: list[str] = []

    for idx, row in enumerate(rows, 1):
        folder_id = hash_to_folder.get(row["file_hash"])
        if folder_id is None:
            no_hash_match += 1
            continue

        matched += 1
        if not dry_run:
            try:
                frappe.db.set_value(
                    "Organization Document",
                    row["name"],
                    "source_folder_id",
                    folder_id,
                    update_modified=False,
                )
            except Exception as e:
                errors.append(f"{row['name']}: {e}")

        # Commit per batch
        if not dry_run and idx % batch_size == 0:
            frappe.db.commit()

    if not dry_run:
        frappe.db.commit()

    return {
        "matched": matched,
        "no_hash_match": no_hash_match,
        "already_set": already_set,
        "errors": errors,
        "dry_run": dry_run,
    }


def _fetch_mijnrood_hash_to_folder() -> dict[str, int]:
    """Return {sha256_hex: folder_id} for all MijnRood documents.

    Tries the MijnRood DB first (looking for a hash column); falls back
    to SFTP-and-hash if the DB doesn't expose hashes.
    """
    from verenigingen.mijnrood_sync.client import MijnRoodDatabaseClient

    settings = frappe.get_single("MijnRood Sync Settings")
    client = MijnRoodDatabaseClient(settings=settings)
    with client:
        if hasattr(client, "fetch_document_hash_to_folder"):
            try:
                return client.fetch_document_hash_to_folder()
            except Exception as e:
                logger.warning("MijnRood DB hash fetch failed (%s); falling back to SFTP", e)

    return _sftp_hash_to_folder(settings)


def _sftp_hash_to_folder(settings) -> dict[str, int]:
    """Fallback: download each MijnRood file via SFTP, compute sha256, build map."""
    import hashlib

    from verenigingen.mijnrood_sync.client import MijnRoodDatabaseClient
    from verenigingen.mijnrood_sync.sftp_client import MijnRoodSFTPClient

    db_client = MijnRoodDatabaseClient(settings=settings)
    with db_client:
        documents = db_client.fetch_documents()

    sftp_client = MijnRoodSFTPClient(settings=settings)
    out: dict[str, int] = {}
    with sftp_client:
        for doc in documents:
            upload_filename = doc.get("upload_file_name")
            folder_id = doc.get("folder_id")
            if not upload_filename or folder_id is None:
                continue
            try:
                content = sftp_client.download_file(upload_filename)
            except Exception as e:
                logger.warning("SFTP download failed for %s: %s", upload_filename, e)
                continue
            file_hash = hashlib.sha256(content).hexdigest()
            out[file_hash] = folder_id

    return out
