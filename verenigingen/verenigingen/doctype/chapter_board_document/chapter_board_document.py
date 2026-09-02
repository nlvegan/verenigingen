# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ChapterBoardDocument(Document):
    """Child table (istable: 1) of Chapter.board_documents.

    #596: this class used to define validate() (document_name required, path-
    traversal check, document_file required, file-extension allowlist, upload_date
    default). Frappe never runs it -- there is no d.run_method("validate") for
    children anywhere in insert()/save(). Not moved to the parent: Chapter's own
    board_documents field is `"hidden": 1`, labelled "Board Documents (Deprecated)"
    in chapter.json, and ChapterBoardService.populate_board_document_fields() (the
    only other code that ever touched this table) is itself a documented no-op --
    "Board documents are now managed via the Organization Document doctype and
    Document Browser portal." No code creates a Chapter Board Document row today.
    """
