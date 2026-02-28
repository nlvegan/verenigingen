"""
Detect document category from folder path segments.

Used by the MijnRood document import to auto-categorize documents when the
folder mapping has "Other" as the document_type but the folder name itself
contains recognizable keywords (e.g. "bestuursvergadering" → Meeting Minutes).

Keywords are configured per category in Verenigingen Settings →
Board Document Categories → Folder Keywords field.
"""

import frappe

# Hardcoded fallback used only when Settings is unreachable (e.g. during
# installation before after_install runs). Matches the seed defaults.
_FALLBACK_KEYWORDS: dict[str, list[str]] = {
    "Meeting Minutes": [
        "bestuursvergadering",
        "ledenvergadering",
        "conferentie",
        "congres",
        "kaderdag",
        "notulen",
    ],
    "Intern Bulletin": [
        "intern bulletin",
    ],
    "Policy": [
        "programmacommissie",
        "minimumprogramma",
    ],
}


def _load_keyword_map() -> dict[str, list[str]]:
    """Load category → keywords mapping from Verenigingen Settings.

    Parses the comma-separated ``folder_keywords`` field on each
    Board Document Category row. Falls back to hardcoded defaults
    if Settings can't be read.
    """
    try:
        settings = frappe.get_single("Verenigingen Settings")
        if not settings or not getattr(settings, "board_document_categories", None):
            return dict(_FALLBACK_KEYWORDS)

        keyword_map: dict[str, list[str]] = {}
        for row in settings.board_document_categories:
            if not row.category_name or not row.folder_keywords:
                continue
            keywords = [kw.strip().lower() for kw in row.folder_keywords.split(",") if kw.strip()]
            if keywords:
                keyword_map[row.category_name] = keywords

        return keyword_map if keyword_map else dict(_FALLBACK_KEYWORDS)
    except Exception:
        return dict(_FALLBACK_KEYWORDS)


def detect_category_from_folder_path(folder_path: str, current_category: str = "Other") -> str:
    """Detect a document category from folder path keywords.

    If ``current_category`` is already something specific (not "Other"),
    it is returned as-is — explicit mappings always win.

    Keywords are read from the ``folder_keywords`` field on each
    Board Document Category row in Verenigingen Settings.

    Args:
        folder_path: Slash-separated folder path, e.g. "Landelijk / bestuursvergadering / 2024".
        current_category: The category already assigned (from folder mapping table).

    Returns:
        Detected category string, or ``current_category`` unchanged.
    """
    if current_category and current_category != "Other":
        return current_category

    if not folder_path:
        return current_category

    keyword_map = _load_keyword_map()

    # Normalize to lowercase for matching
    path_lower = folder_path.lower()

    for category, keywords in keyword_map.items():
        for keyword in keywords:
            if keyword in path_lower:
                return category

    return current_category
