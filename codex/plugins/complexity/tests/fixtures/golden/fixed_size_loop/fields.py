def has_legacy_values(frappe):
    for fieldname in ("sharepoint_site_url", "sharepoint_document_library"):
        value = frappe.db.get_value("OneDrive Settings", "Settings", fieldname)
        if value:
            return True
    return False
