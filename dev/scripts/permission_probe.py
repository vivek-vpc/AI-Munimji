# Probe: what does reading stock look like for a signed-in user who only has the Munimji Viewer role?
#   frappe.get_all ignores permissions (it is get_list with ignore_permissions=True); frappe.get_list applies them.
frappe.set_user("munimji.viewer@example.com")
print("session user:", frappe.session.user, "| roles:", sorted(set(frappe.get_roles()) - {"All", "Guest"}))
print("get_all('Bin') rows:", len(frappe.get_all("Bin")))
try:
	print("get_list('Bin') rows:", len(frappe.get_list("Bin")))
except frappe.PermissionError as e:
	print("get_list('Bin') -> PermissionError:", e)
print("has_permission('Bin', 'read'):", frappe.has_permission("Bin", "read"))
print("has_permission('Item', 'read'):", frappe.has_permission("Item", "read"))
print("has_permission('Stock Ledger Entry', 'read'):", frappe.has_permission("Stock Ledger Entry", "read"))
frappe.set_user("munimji.approver@example.com")
print("approver roles:", sorted(set(frappe.get_roles()) - {"All", "Guest"}))
print("approver get_list('Bin') rows:", len(frappe.get_list("Bin")))
print("approver has_permission('Stock Ledger Entry', 'read'):", frappe.has_permission("Stock Ledger Entry", "read"))
frappe.set_user("Administrator")
