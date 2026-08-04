def execute(frappe):
    for fieldname in ("legacy_url", "legacy_library"):
        frappe.db.get_value("Settings", "default", fieldname)
