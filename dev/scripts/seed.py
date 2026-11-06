# Makes the development site usable for the round trip: completes ERPNext's setup wizard (a company and its accounts), then a supplier, three items
# with different stock, and two demo users. Safe to run again. Run with:
#   .\dev\exec.ps1 bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/seed.py
from frappe.desk.page.setup_wizard.setup_wizard import setup_complete
from frappe.utils import add_days, nowdate

COMPANY, ABBR = "Munimji Demo Co", "MDC"
WAREHOUSE = f"Stores - {ABBR}"
SUPPLIER = "Munimji Demo Supplier"
ITEMS = {"MD-BOLT-M8": ("Bolt M8 x 40", 3), "MD-NUT-M8": ("Nut M8", 50), "MD-WASHER-M8": ("Washer M8", 8)}  # item code: (name, quantity in stock)
USERS = {
	"munimji.approver@example.com": ("Approver", ("Munimji Approver", "Purchase User", "Purchase Manager", "Stock User")),
	"munimji.viewer@example.com": ("Viewer", ("Munimji Viewer",)),
	"munimji.manager@example.com": ("Manager", ("Munimji Manager",)),
}
PASSWORD = "Munimji-dev-1!"

if not frappe.is_setup_complete():
	setup_complete(
		{
			"language": "English",
			"country": "India",
			"timezone": "Asia/Kolkata",
			"currency": "INR",
			"full_name": "Administrator",
			"email": "admin@example.com",
			"password": "admin",
			"company_name": COMPANY,
			"company_abbr": ABBR,
			"chart_of_accounts": "Standard",
			"fy_start_date": "2026-04-01",
			"fy_end_date": "2027-03-31",
		}
	)
	frappe.db.commit()  # the wizard works in its own transactions
	print("setup wizard completed")

if not frappe.db.exists("Supplier", SUPPLIER):
	frappe.get_doc({"doctype": "Supplier", "supplier_name": SUPPLIER, "supplier_group": "All Supplier Groups"}).insert()

for code, (name, quantity) in ITEMS.items():
	if not frappe.db.exists("Item", code):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": name,
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"standard_rate": 5,
				"item_defaults": [{"company": COMPANY, "default_supplier": SUPPLIER, "default_warehouse": WAREHOUSE}],
			}
		).insert()
		from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry

		make_stock_entry(item_code=code, qty=quantity, to_warehouse=WAREHOUSE, rate=5, company=COMPANY)

for email, (first_name, roles) in USERS.items():
	if not frappe.db.exists("User", email):
		user = frappe.get_doc({"doctype": "User", "email": email, "first_name": first_name, "send_welcome_email": 0, "roles": [{"role": r} for r in roles]})
		user.flags.ignore_password_policy = True
		user.new_password = PASSWORD
		user.insert(ignore_permissions=True)

# The placeholder job (jobs.py, replaced in Phase 5) asks for a purchase where stock is at or below min_qty, and a new site has 0 there ("not used") and the monitor OFF.
# For the demo both are set, as a person would after reviewing the thresholds.
settings = frappe.get_doc("AI Munimji Settings")
settings.min_qty = 10
settings.enabled = 1
settings.save()

print("items and stock:", frappe.db.sql("SELECT item_code, warehouse, actual_qty FROM tabBin WHERE item_code LIKE 'MD-%%' ORDER BY item_code"))
