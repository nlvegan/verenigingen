from frappe.model.document import Document


class MijnRoodDocumentFolderMapping(Document):
    # No validate() — organization_type and document_type are intentionally
    # optional at save time. The workflow is:
    #   1. "Fetch Folders" populates rows with folder_id/name only
    #   2. Admin fills in organization_type + entity + document_type
    #   3. "Import Documents" skips any rows that are still incomplete
    pass
