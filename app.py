from __future__ import annotations

import html
import hashlib
import io
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh


APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR / "pharmacy.db"
CURRENCY = "KSh"
EAT = ZoneInfo("Africa/Nairobi")
INVENTORY_EXCEL_COLUMNS = [
    "Product ID", "Product Name", "Supplier Name", "Batch No", "Expiry Date", "Initial Stock",
    "QTY Sold", "Current Stock", "Reorder Level", "Unit Cost (KSh)", "Total Cost (KSh)", "Markup %",
    "Selling Price (KSh)", "Expiry Status", "Stock Status",
]

st.set_page_config(page_title="Eashers Pharmacy", page_icon="+", layout="wide", initial_sidebar_state="expanded")


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def now_text() -> str:
    return datetime.now(EAT).strftime("%Y-%m-%d %H:%M:%S")


def password_hash(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def is_admin(user: dict) -> bool:
    return str(user.get("role", "")).strip().lower() in {"admin", "super_admin"}


def is_super_admin(user: dict) -> bool:
    return str(user.get("role", "")).strip().lower() == "super_admin"


def active_pharmacy_id() -> int | None:
    if "user" not in st.session_state:
        return None
    return st.session_state.user.get("pharmacy_id")


def write_pharmacy_id() -> int | None:
    if is_super_admin(st.session_state.get("user", {})):
        return st.session_state.get("selected_pharmacy_id")
    return active_pharmacy_id()


def pharmacy_scope(alias: str = "") -> tuple[str, tuple]:
    if is_super_admin(st.session_state.get("user", {})):
        return "", ()
    column = f"{alias}.pharmacy_id" if alias else "pharmacy_id"
    return f" WHERE {column}=?", (active_pharmacy_id(),)


def authenticate(username: str, password: str) -> sqlite3.Row | None:
    rows = query("SELECT u.*, p.name AS pharmacy_name FROM users u LEFT JOIN pharmacies p ON p.id=u.pharmacy_id WHERE u.username=? AND u.password_hash=? AND u.active=1", (username.strip(), password_hash(password)))
    return rows[0] if rows else None


def money(value: float | int | None) -> str:
    return f"{CURRENCY} {float(value or 0):,.2f}"


def setup_database() -> None:
    with db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS pharmacies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE, location TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, contact_person TEXT DEFAULT '', phone TEXT DEFAULT '',
                email TEXT DEFAULT '', lead_time_days INTEGER DEFAULT 0, payment_terms TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT, product_code TEXT NOT NULL,
                name TEXT NOT NULL, category TEXT NOT NULL, supplier_id INTEGER, batch_no TEXT DEFAULT 'N/A',
                expiry_date TEXT, initial_stock REAL NOT NULL DEFAULT 0, quantity_sold REAL NOT NULL DEFAULT 0,
                current_stock REAL NOT NULL DEFAULT 0, reorder_level REAL NOT NULL DEFAULT 5,
                unit_cost REAL NOT NULL DEFAULT 0, selling_price REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT, receipt_no TEXT NOT NULL UNIQUE,
                customer_name TEXT NOT NULL, payment_method TEXT NOT NULL, subtotal REAL NOT NULL,
                discount REAL NOT NULL DEFAULT 0, total REAL NOT NULL, cashier TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sale_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
                quantity REAL NOT NULL, unit_price REAL NOT NULL, line_total REAL NOT NULL,
                FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(id)
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, action_type TEXT NOT NULL, entity TEXT NOT NULL,
                details TEXT NOT NULL, performed_by TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'member', can_manage_inventory INTEGER NOT NULL DEFAULT 0,
                can_manage_suppliers INTEGER NOT NULL DEFAULT 0, can_view_reports INTEGER NOT NULL DEFAULT 0,
                can_view_audit INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
            );
            """
        )
        default_pharmacy = connection.execute("SELECT id FROM pharmacies ORDER BY id LIMIT 1").fetchone()
        if default_pharmacy is None:
            connection.execute("INSERT INTO pharmacies(name,location,created_at) VALUES(?,?,?)", ("Eashers Pharmacy", "Ruiru Town, Kiambu", now_text()))
            default_pharmacy = connection.execute("SELECT id FROM pharmacies ORDER BY id LIMIT 1").fetchone()
        default_pharmacy_id = default_pharmacy[0]
        for table in ("suppliers", "products", "sales", "audit_log", "users"):
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
            if "pharmacy_id" not in columns:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN pharmacy_id INTEGER")
            connection.execute(f"UPDATE {table} SET pharmacy_id=? WHERE pharmacy_id IS NULL", (default_pharmacy_id,))
        migrate_tenant_constraints(connection)
        connection.execute("UPDATE users SET role='super_admin', pharmacy_id=NULL WHERE username='Stephen'")
        if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            connection.execute(
                "INSERT INTO users(username,password_hash,role,can_manage_inventory,can_manage_suppliers,can_view_reports,can_view_audit,created_at,pharmacy_id) VALUES(?,?,?,?,?,?,?,?,?)",
                ("Stephen", password_hash("Stephen@12k"), "super_admin", 1, 1, 1, 1, now_text(), None),
            )
        if connection.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0] == 0:
            suppliers = [
                ("Liyana Pharma", "John Mwangi", "+254 712 345 678", "orders@liyanapharm.co.ke", 3, "30 Days Credit"),
                ("Jellings Healthcare", "Sarah Otieno", "+254 722 987 654", "sales@jellings.co.ke", 2, "Cash on Delivery"),
                ("Philmed Distributors", "David Kamau", "+254 733 456 789", "info@philmed.co.ke", 5, "14 Days Credit"),
            ]
            connection.executemany("INSERT INTO suppliers(name,contact_person,phone,email,lead_time_days,payment_terms,created_at) VALUES(?,?,?,?,?,?,?)", [row + (now_text(),) for row in suppliers])
        if connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            supplier = connection.execute("SELECT id FROM suppliers ORDER BY id LIMIT 1").fetchone()[0]
            products = [
                ("PRD-1001", "Albendazole Susp 400mg", "Antiparasitic", supplier, "B-2401", "2027-05-01", 10, 2, 8, 5, 16, 50),
                ("PRD-1002", "Amoxicillin 100ml Susp", "Antibiotic", supplier, "B-2402", "2027-08-01", 12, 4, 8, 5, 75, 150),
                ("PRD-1003", "Panadol Advance 100s", "Analgesic", supplier, "B-2403", "2028-01-01", 50, 5, 45, 10, 16, 30),
                ("PRD-1004", "Cetirizine Syrup 60ml", "Antihistamine", supplier, "B-2404", "2026-10-15", 8, 6, 2, 5, 40, 80),
                ("PRD-1005", "Cefuroxime 500mg", "Antibiotic", supplier, "B-2405", "2026-12-20", 6, 6, 0, 3, 250, 500),
                ("PRD-1006", "ORS Sachets", "Rehydration", supplier, "B-2406", "2028-03-01", 80, 20, 60, 15, 8, 20),
            ]
            connection.executemany("INSERT INTO products(product_code,name,category,supplier_id,batch_no,expiry_date,initial_stock,quantity_sold,current_stock,reorder_level,unit_cost,selling_price,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [row + (now_text(), now_text()) for row in products])
            connection.execute("INSERT INTO audit_log(action_type,entity,details,performed_by,created_at) VALUES(?,?,?,?,?)", ("Initial setup", "Inventory", "Seeded starter pharmacy inventory", "System", now_text()))
        for table in ("suppliers", "products", "sales", "audit_log"):
            connection.execute(f"UPDATE {table} SET pharmacy_id=? WHERE pharmacy_id IS NULL", (default_pharmacy_id,))


def migrate_tenant_constraints(connection: sqlite3.Connection) -> None:
    """Replace legacy global supplier/SKU uniqueness with pharmacy-scoped indexes."""
    supplier_sql = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='suppliers'").fetchone()[0] or ""
    product_sql = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='products'").fetchone()[0] or ""
    if "name TEXT NOT NULL UNIQUE" in supplier_sql or "product_code TEXT NOT NULL UNIQUE" in product_sql:
        connection.commit()
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("ALTER TABLE sale_items RENAME TO sale_items_legacy")
        connection.execute("ALTER TABLE products RENAME TO products_legacy")
        connection.execute("ALTER TABLE suppliers RENAME TO suppliers_legacy")
        connection.executescript(
            """
            CREATE TABLE suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, contact_person TEXT DEFAULT '', phone TEXT DEFAULT '',
                email TEXT DEFAULT '', lead_time_days INTEGER DEFAULT 0, payment_terms TEXT DEFAULT '',
                created_at TEXT NOT NULL, pharmacy_id INTEGER, UNIQUE(name, pharmacy_id)
            );
            CREATE TABLE products (
                id INTEGER PRIMARY KEY AUTOINCREMENT, product_code TEXT NOT NULL,
                name TEXT NOT NULL, category TEXT NOT NULL, supplier_id INTEGER, batch_no TEXT DEFAULT 'N/A',
                expiry_date TEXT, initial_stock REAL NOT NULL DEFAULT 0, quantity_sold REAL NOT NULL DEFAULT 0,
                current_stock REAL NOT NULL DEFAULT 0, reorder_level REAL NOT NULL DEFAULT 5,
                unit_cost REAL NOT NULL DEFAULT 0, selling_price REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, pharmacy_id INTEGER,
                UNIQUE(product_code, pharmacy_id), FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE SET NULL
            );
            CREATE TABLE sale_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
                quantity REAL NOT NULL, unit_price REAL NOT NULL, line_total REAL NOT NULL,
                FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE CASCADE, FOREIGN KEY (product_id) REFERENCES products(id)
            );
            INSERT INTO suppliers SELECT id,name,contact_person,phone,email,lead_time_days,payment_terms,created_at,pharmacy_id FROM suppliers_legacy;
            INSERT INTO products SELECT id,product_code,name,category,supplier_id,batch_no,expiry_date,initial_stock,quantity_sold,current_stock,reorder_level,unit_cost,selling_price,created_at,updated_at,pharmacy_id FROM products_legacy;
            INSERT INTO sale_items SELECT id,sale_id,product_id,quantity,unit_price,line_total FROM sale_items_legacy;
            DROP TABLE sale_items_legacy;
            DROP TABLE products_legacy;
            DROP TABLE suppliers_legacy;
            """
        )
        connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS suppliers_name_pharmacy_idx ON suppliers(name, pharmacy_id)")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS products_code_pharmacy_idx ON products(product_code, pharmacy_id)")


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with db() as connection:
        return connection.execute(sql, params).fetchall()


def add_audit(action: str, entity: str, details: str, user: str = "Pharmacy Admin") -> None:
    with db() as connection:
        connection.execute("INSERT INTO audit_log(action_type,entity,details,performed_by,created_at,pharmacy_id) VALUES(?,?,?,?,?,?)", (action, entity, details, user, now_text(), write_pharmacy_id()))


def load_products() -> pd.DataFrame:
    where, params = pharmacy_scope("p")
    return pd.read_sql_query(f"SELECT p.*, COALESCE(s.name, 'Unassigned') AS supplier FROM products p LEFT JOIN suppliers s ON s.id = p.supplier_id{where} ORDER BY p.name", db(), params=params)


def inventory_excel_bytes() -> bytes:
    products_frame = load_products()
    products_frame["Expiry Status"] = products_frame["expiry_date"].apply(expiry_status)
    products_frame["Stock Status"] = products_frame.apply(lambda row: status(row["current_stock"], row["reorder_level"]), axis=1)
    products_frame["Total Cost (KSh)"] = products_frame["current_stock"] * products_frame["unit_cost"]
    products_frame["Markup %"] = products_frame.apply(
        lambda row: ((row["selling_price"] - row["unit_cost"]) / row["unit_cost"] * 100) if row["unit_cost"] else 0,
        axis=1,
    )
    export = pd.DataFrame({
        "Product ID": products_frame["product_code"], "Product Name": products_frame["name"],
        "Supplier Name": products_frame["supplier"],
        "Batch No": products_frame["batch_no"], "Expiry Date": products_frame["expiry_date"],
        "Initial Stock": products_frame["initial_stock"], "QTY Sold": products_frame["quantity_sold"],
        "Current Stock": products_frame["current_stock"], "Reorder Level": products_frame["reorder_level"],
        "Unit Cost (KSh)": products_frame["unit_cost"], "Total Cost (KSh)": products_frame["Total Cost (KSh)"],
        "Markup %": products_frame["Markup %"], "Selling Price (KSh)": products_frame["selling_price"],
        "Expiry Status": products_frame["Expiry Status"], "Stock Status": products_frame["Stock Status"],
    })
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        export.to_excel(writer, index=False, sheet_name="Inventory")
    return output.getvalue()


def dataframe_excel_bytes(frame: pd.DataFrame, sheet_name: str = "Report") -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    return output.getvalue()


def receipt_excel_bytes(receipt: str) -> bytes:
    sale = query("SELECT * FROM sales WHERE receipt_no=?", (receipt,))[0]
    items = query("SELECT si.quantity, si.unit_price, si.line_total, p.name FROM sale_items si JOIN products p ON p.id=si.product_id WHERE si.sale_id=?", (sale["id"],))
    rows = pd.DataFrame([{
        "Product Name": item["name"], "Quantity": item["quantity"], "Unit Price (KSh)": item["unit_price"], "Line Total (KSh)": item["line_total"],
    } for item in items])
    summary = pd.DataFrame([
        {"Field": "Receipt No", "Value": sale["receipt_no"]}, {"Field": "Date & Time", "Value": sale["created_at"]},
        {"Field": "Customer", "Value": sale["customer_name"]}, {"Field": "Payment Method", "Value": sale["payment_method"]},
        {"Field": "Cashier", "Value": sale["cashier"]}, {"Field": "Subtotal (KSh)", "Value": sale["subtotal"]},
        {"Field": "Discount (KSh)", "Value": sale["discount"]}, {"Field": "Grand Total (KSh)", "Value": sale["total"]},
    ])
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary.to_excel(writer, index=False, sheet_name="Receipt Summary")
        rows.to_excel(writer, index=False, sheet_name="Receipt Items")
    return output.getvalue()


def normalize_excel_header(value: object) -> str:
    return " ".join(str(value).replace("\n", " ").replace("%", "%").strip().lower().split())


EXCEL_HEADER_ALIASES = {
    "supplier name": {"supplier name", "supplier", "suppliername", "vendor", "vendor name"},
    "initial stock": {"initial stock", "initial stock qty", "initial stock quantity", "opening stock", "opening quantity", "starting stock"},
    "qty sold": {"qty sold", "quantity sold", "sold", "qtysale", "qty sales"},
    "current stock": {"current stock", "current qty", "current quantity", "stock balance", "balance"},
    "reorder level": {"reorder level", "reorder point", "minimum stock", "min stock", "threshold"},
    "unit cost (ksh)": {"unit cost (ksh)", "unit cost", "cost price", "purchase price", "buying price"},
    "selling price (ksh)": {"selling price (ksh)", "selling price", "retail price", "sale price"},
}


def read_inventory_sheet(content: bytes) -> pd.DataFrame:
    workbook = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None)
    expected = {normalize_excel_header(column) for column in INVENTORY_EXCEL_COLUMNS}
    candidates = []
    for sheet_name, raw in workbook.items():
        header_index = None
        for index in range(min(40, len(raw))):
            found = {normalize_excel_header(value) for value in raw.iloc[index].tolist()}
            has_product_headers = bool(found & {"product id", "product code", "sku"}) and bool(found & {"product name", "medicine", "drug", "item"})
            if len(found & expected) >= 5 and has_product_headers:
                header_index = index
                break
        if header_index is None:
            continue
        headers = [str(value).strip() for value in raw.iloc[header_index].tolist()]
        sheet = raw.iloc[header_index + 1:].copy()
        sheet.columns = headers
        sheet = sheet.dropna(how="all").reset_index(drop=True)
        aliases = {normalize_excel_header(column): column for column in sheet.columns}
        renamed = {}
        for required in INVENTORY_EXCEL_COLUMNS:
            normalized_required = normalize_excel_header(required)
            accepted_headers = EXCEL_HEADER_ALIASES.get(normalized_required, {normalized_required})
            if required == "Product ID":
                accepted_headers |= {"product code", "sku"}
            if required == "Product Name":
                accepted_headers |= {"medicine", "drug", "item"}
            source = next((aliases[header] for header in accepted_headers if header in aliases), None)
            if source is None:
                if required == "Supplier Name": sheet[required] = "Unassigned"
                elif required in {"Initial Stock", "QTY Sold"}: sheet[required] = 0
                elif required == "Current Stock": sheet[required] = pd.NA
                elif required == "Reorder Level": sheet[required] = 5
                elif required in {"Unit Cost (KSh)", "Selling Price (KSh)"}: sheet[required] = 0
                elif required in {"Total Cost (KSh)", "Markup %", "Expiry Status", "Stock Status"}: sheet[required] = ""
                else: raise ValueError(f"Missing required column: {required}")
            else:
                renamed[source] = required
        sheet = sheet.rename(columns=renamed)
        product_ids = sheet["Product ID"].fillna("").astype(str).str.strip()
        product_names = sheet["Product Name"].fillna("").astype(str).str.strip()
        usable = (product_ids != "") & (product_names != "")
        if usable.any():
            candidates.append(sheet.loc[usable].reset_index(drop=True))
    if not candidates:
        raise ValueError("The workbook does not contain any product rows. Check that the inventory sheet has Product ID and Product Name values below its headers.")
    return max(candidates, key=len)


def import_inventory_excel(content: bytes, performed_by: str) -> tuple[int, int]:
    uploaded = read_inventory_sheet(content)
    uploaded = uploaded[INVENTORY_EXCEL_COLUMNS].copy()
    uploaded["Product ID"] = uploaded["Product ID"].fillna("").astype(str).str.strip()
    uploaded["Product Name"] = uploaded["Product Name"].fillna("").astype(str).str.strip()
    blank_rows = uploaded["Product ID"].eq("") & uploaded["Product Name"].eq("")
    uploaded = uploaded.loc[~blank_rows].reset_index(drop=True)
    incomplete_rows = uploaded["Product ID"].eq("") | uploaded["Product Name"].eq("")
    if incomplete_rows.any():
        rows = ", ".join(str(index + 2) for index in uploaded.index[incomplete_rows][:10])
        raise ValueError(f"Every product row must have Product ID and Product Name. Check Excel row(s): {rows}")
    if uploaded.empty:
        raise ValueError("The Excel sheet does not contain any product rows.")
    for column in ["Initial Stock", "QTY Sold", "Reorder Level", "Unit Cost (KSh)", "Total Cost (KSh)", "Markup %", "Selling Price (KSh)"]:
        uploaded[column] = pd.to_numeric(uploaded[column], errors="coerce").fillna(0)
    uploaded["Current Stock"] = pd.to_numeric(uploaded["Current Stock"], errors="coerce")
    uploaded["Current Stock"] = uploaded["Current Stock"].fillna(uploaded["Initial Stock"] - uploaded["QTY Sold"])
    uploaded["Expiry Date"] = pd.to_datetime(uploaded["Expiry Date"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
    inserted = updated = 0
    with db() as connection:
        for row in uploaded.to_dict("records"):
            supplier_name = "Unassigned" if pd.isna(row["Supplier Name"]) else str(row["Supplier Name"]).strip() or "Unassigned"
            supplier = connection.execute("SELECT id FROM suppliers WHERE name=? AND pharmacy_id=?", (supplier_name, write_pharmacy_id())).fetchone()
            if not supplier:
                supplier = connection.execute("INSERT INTO suppliers(name,created_at,pharmacy_id) VALUES(?,?,?)", (supplier_name, now_text(), write_pharmacy_id()))
                supplier_id = supplier.lastrowid
            else:
                supplier_id = supplier["id"]
            values = (row["Product Name"], "Medicine", supplier_id, row["Batch No"] or "N/A", row["Expiry Date"], row["Initial Stock"], row["QTY Sold"], row["Current Stock"], row["Reorder Level"], row["Unit Cost (KSh)"], row["Selling Price (KSh)"], now_text(), row["Product ID"])
            existing = connection.execute("SELECT id FROM products WHERE product_code=? AND pharmacy_id=?", (row["Product ID"], write_pharmacy_id())).fetchone()
            if existing:
                connection.execute("UPDATE products SET name=?,category=?,supplier_id=?,batch_no=?,expiry_date=?,initial_stock=?,quantity_sold=?,current_stock=?,reorder_level=?,unit_cost=?,selling_price=?,updated_at=? WHERE product_code=? AND pharmacy_id=?", values + (write_pharmacy_id(),))
                updated += 1
            else:
                connection.execute("INSERT INTO products(name,category,supplier_id,batch_no,expiry_date,initial_stock,quantity_sold,current_stock,reorder_level,unit_cost,selling_price,updated_at,product_code,created_at,pharmacy_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values[:-1] + (row["Product ID"], now_text(), write_pharmacy_id()))
                inserted += 1
    add_audit("Inventory Excel imported", "Inventory", f"Accepted {inserted} new and {updated} updated rows", performed_by)
    return inserted, updated


def status(stock: float, reorder: float) -> str:
    return "OUT OF STOCK" if stock <= 0 else "LOW STOCK" if stock <= reorder else "OK"


def expiry_status(value: str | None) -> str:
    if not value:
        return "N/A"
    expiry = datetime.strptime(value, "%Y-%m-%d").date()
    return "EXPIRED" if expiry < date.today() else "EXPIRING SOON" if expiry <= date.today() + timedelta(days=90) else "OK"


def add_product(data: dict) -> None:
    with db() as connection:
        connection.execute("INSERT INTO products(product_code,name,category,supplier_id,batch_no,expiry_date,initial_stock,current_stock,reorder_level,unit_cost,selling_price,created_at,updated_at,pharmacy_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (data["code"], data["name"], data["category"], data["supplier_id"], data["batch"], data["expiry"], data["stock"], data["stock"], data["reorder"], data["cost"], data["price"], now_text(), now_text(), write_pharmacy_id()))
    add_audit("Product added", "Inventory", f"Added {data['code']} - {data['name']}")


def create_sale(cart: list[dict], customer: str, payment: str, discount: float, cashier: str) -> tuple[str, float]:
    subtotal = sum(item["quantity"] * item["unit_price"] for item in cart)
    total = max(0, subtotal - discount)
    current_time = datetime.now(EAT)
    receipt = f"POS-{current_time:%Y%m%d}-{current_time.microsecond // 1000:03d}"
    with db() as connection:
        sale_id = connection.execute("INSERT INTO sales(receipt_no,customer_name,payment_method,subtotal,discount,total,cashier,created_at,pharmacy_id) VALUES(?,?,?,?,?,?,?,?,?)", (receipt, customer, payment, subtotal, discount, total, cashier, now_text(), write_pharmacy_id())).lastrowid
        for item in cart:
            connection.execute("INSERT INTO sale_items(sale_id,product_id,quantity,unit_price,line_total) VALUES(?,?,?,?,?)", (sale_id, item["id"], item["quantity"], item["unit_price"], item["quantity"] * item["unit_price"]))
            connection.execute("UPDATE products SET current_stock=current_stock-?, quantity_sold=quantity_sold+?, updated_at=? WHERE id=?", (item["quantity"], item["quantity"], now_text(), item["id"]))
    add_audit("Sale completed", receipt, f"{len(cart)} line items, total {money(total)}", cashier)
    return receipt, total


def receipt_html(receipt: str) -> str:
    sale = query("SELECT * FROM sales WHERE receipt_no=?", (receipt,))[0]
    items = query("SELECT si.*, p.name FROM sale_items si JOIN products p ON p.id=si.product_id WHERE si.sale_id=?", (sale["id"],))
    rows = "".join(f"<tr><td>{html.escape(item['name'])}</td><td>{item['quantity']:g}</td><td>{money(item['line_total'])}</td></tr>" for item in items)
    return f"""<div class='receipt'><h2>MEDISHELF PHARMACY</h2><p>Ruiru Town, Kiambu · +254 700 000 000</p><hr><p><b>Receipt:</b> {receipt}<br><b>Date:</b> {sale['created_at']}<br><b>Customer:</b> {html.escape(sale['customer_name'])}<br><b>Payment:</b> {sale['payment_method']}</p><table><tr><th>Item</th><th>Qty</th><th>Total</th></tr>{rows}</table><hr><p class='total'>TOTAL: {money(sale['total'])}</p><p>Thank you for choosing MediShelf Pharmacy.</p></div>"""


setup_database()

if "user" not in st.session_state:
    st.markdown("<div class='hero'><div class='section-kicker' style='color:#9ce3ca'>Secure pharmacy operations</div><h1>Welcome to Eashers Pharmacy.</h1><p>Sign in to manage stock, sales, suppliers, and reports.</p></div>", unsafe_allow_html=True)
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
    if submitted:
        authenticated = authenticate(username, password)
        if authenticated:
            st.session_state.user = dict(authenticated)
            st.session_state.selected_pharmacy_id = authenticated["pharmacy_id"]
            st.rerun()
        st.error("Invalid username or password.")
    st.stop()

current_user = st.session_state.user
admin_access = is_admin(current_user)
if is_super_admin(current_user) and st.session_state.get("selected_pharmacy_id") is None:
    first_pharmacy = query("SELECT id FROM pharmacies WHERE active=1 ORDER BY name LIMIT 1")
    if first_pharmacy:
        st.session_state.selected_pharmacy_id = first_pharmacy[0]["id"]
st_autorefresh(interval=10000, limit=None, key="realtime_refresh")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
:root { --navy:#102c3b; --teal:#087f75; --mint:#dff4ea; --paper:#f4f7f5; --ink:#16282d; --muted:#698087; --orange:#e77b32; }
.stApp { background:var(--paper); color:var(--ink); font-family:'DM Sans',sans-serif; }
h1,h2,h3 { font-family:'Space Grotesk',sans-serif; letter-spacing:0; }
[data-testid='stSidebar'] { background:var(--navy); } [data-testid='stSidebar'] * { color:#eff8f4 !important; }
.brand { padding:1rem .2rem 1.3rem; border-bottom:1px solid #31505a; margin-bottom:1.2rem; } .brand small { color:#7dd7bd; letter-spacing:.12em; text-transform:uppercase; font-weight:700; } .brand h2 { margin:.3rem 0 0; color:white; }
.hero { background:linear-gradient(105deg,#103d45,#087f75); color:white; border-radius:12px; padding:1.5rem 1.7rem; margin-bottom:1.3rem; } .hero h1 { margin:.15rem 0 .35rem; font-size:2.1rem; } .hero p { opacity:.82; margin:0; }
.metric { background:white; border:1px solid #dfe9e4; border-radius:10px; padding:1rem 1.1rem; min-height:112px; } .metric .label { color:var(--muted); font-size:.74rem; text-transform:uppercase; letter-spacing:.1em; } .metric .value { font-family:'Space Grotesk'; font-size:1.55rem; font-weight:700; margin-top:.45rem; } .metric .note { color:var(--muted); font-size:.8rem; }
.receipt { max-width:520px; margin:auto; padding:24px; background:white; color:#17282d; font-family:Arial,sans-serif; } .receipt h2 { text-align:center; margin:0; } .receipt p { font-size:13px; line-height:1.5; } .receipt table { width:100%; border-collapse:collapse; font-size:13px; } .receipt th,.receipt td { padding:7px 3px; border-bottom:1px solid #ddd; text-align:left; } .receipt td:last-child,.receipt th:last-child { text-align:right; } .receipt .total { text-align:right; font-size:18px; font-weight:bold; }
.section-kicker { color:var(--teal); text-transform:uppercase; letter-spacing:.11em; font-size:.75rem; font-weight:700; }
</style>
""", unsafe_allow_html=True)


with st.sidebar:
    st.markdown("<div class='brand'><small>Pharmacy operations</small><h2>MediShelf</h2></div>", unsafe_allow_html=True)
    allowed_pages = ["Dashboard", "Point of Sale", "Daily Sales", "Inventory & Stock", "Suppliers", "Audit Log"]
    if admin_access:
        allowed_pages.append("Members")
    if is_super_admin(current_user):
        allowed_pages.append("Pharmacies")
    page = st.radio("Navigate", allowed_pages, label_visibility="collapsed")
    st.divider()
    if is_super_admin(current_user):
        pharmacy_options = query("SELECT id,name FROM pharmacies WHERE active=1 ORDER BY name")
        selected_name = st.selectbox("Manage pharmacy", [row["name"] for row in pharmacy_options], index=next((index for index, row in enumerate(pharmacy_options) if row["id"] == st.session_state.selected_pharmacy_id), 0))
        st.session_state.selected_pharmacy_id = next(row["id"] for row in pharmacy_options if row["name"] == selected_name)
    pharmacy_label = "All pharmacies" if is_super_admin(current_user) else current_user.get("pharmacy_name", "Assigned pharmacy")
    st.caption(f"Signed in: {current_user['username']} · {current_user['role'].replace('_', ' ').title()}")
    st.caption(f"Scope: {pharmacy_label}")
    st.caption(f"Live sync: {now_text()} EAT")
    if st.button("Sign out", use_container_width=True):
        del st.session_state["user"]
        st.rerun()


def header(kicker: str, title: str, subtitle: str) -> None:
    st.markdown(f"<div class='hero'><div class='section-kicker' style='color:#9ce3ca'>{kicker}</div><h1>{title}</h1><p>{subtitle}</p></div>", unsafe_allow_html=True)


products = load_products()

if page == "Dashboard":
    header("Executive view", "A clearer shelf, every day.", "Track stock health, revenue, expiry exposure, and the work that needs attention.")
    sales_where, sales_params = pharmacy_scope("sales")
    sales = query(f"SELECT COALESCE(SUM(total),0) AS total, COUNT(*) AS count FROM sales{sales_where} AND date(created_at)=date('now')" if sales_where else "SELECT COALESCE(SUM(total),0) AS total, COUNT(*) AS count FROM sales WHERE date(created_at)=date('now')", sales_params)[0]
    metrics = [("Inventory value", money((products.current_stock * products.unit_cost).sum()), "current stock at cost"), ("Today's revenue", money(sales["total"]), f"{sales['count']} completed sales"), ("Low-stock items", f"{sum(status(r.current_stock, r.reorder_level) == 'LOW STOCK' for r in products.itertuples())}", "need replenishment"), ("Expiry watch", f"{sum(expiry_status(r.expiry_date) in ('EXPIRED','EXPIRING SOON') for r in products.itertuples())}", "expired or within 90 days")]
    columns = st.columns(4)
    for column, (label, value, note) in zip(columns, metrics):
        column.markdown(f"<div class='metric'><div class='label'>{label}</div><div class='value'>{value}</div><div class='note'>{note}</div></div>", unsafe_allow_html=True)
    st.subheader("Needs attention")
    left, right = st.columns(2)
    with left:
        st.markdown("#### Replenishment queue")
        risk = products[products.apply(lambda row: status(row.current_stock, row.reorder_level) != "OK", axis=1)].copy()
        risk["Status"] = risk.apply(lambda row: status(row.current_stock, row.reorder_level), axis=1)
        st.dataframe(risk[["product_code", "name", "current_stock", "reorder_level", "Status"]].rename(columns={"product_code":"Code", "name":"Product", "current_stock":"Stock", "reorder_level":"Reorder at"}), use_container_width=True, hide_index=True)
    with right:
        st.markdown("#### Expiry watch")
        expiry = products[products.expiry_date.notna()].copy()
        expiry["Expiry status"] = expiry.expiry_date.apply(expiry_status)
        st.dataframe(expiry[expiry["Expiry status"] != "OK"][["name", "expiry_date", "Expiry status", "current_stock"]].rename(columns={"name":"Product", "expiry_date":"Expiry", "current_stock":"Stock"}), use_container_width=True, hide_index=True)
    st.subheader("Stock mix")
    chart_a, chart_b = st.columns(2)
    with chart_a:
        st.bar_chart(products.groupby("category").current_stock.sum().sort_values(ascending=False), height=260)
    with chart_b:
        counts = products.apply(lambda row: status(row.current_stock, row.reorder_level), axis=1).value_counts()
        st.bar_chart(counts, height=260)

elif page == "Point of Sale":
    header("Sales counter", "Point of sale.", "Build a sale, keep stock accurate, and issue a clean printable receipt.")
    if "cart" not in st.session_state: st.session_state.cart = []
    available_products = products[products.current_stock > 0]
    if available_products.empty:
        st.warning("No products with available stock. Upload inventory or add products before starting a sale.")
        choice = None
    else:
        product_options = [f"{r.product_code} · {r.name} · {r.current_stock:g} available" for r in available_products.itertuples()]
        with st.form("pos_form"):
            choice = st.selectbox("Add product", product_options)
            code = choice.split(" · ")[0]
            selected = products[products.product_code == code].iloc[0]
            quantity = st.number_input("Quantity", min_value=1.0, step=1.0, value=1.0)
            unit_price = st.number_input("Unit price (KSh)", min_value=0.0, step=1.0, value=float(selected.selling_price), help="Enter the actual selling price for this sale.")
            add = st.form_submit_button("Add to cart", use_container_width=True)
        if add and choice:
            existing = next((item for item in st.session_state.cart if item["id"] == int(selected.id)), None)
            current_qty = (existing["quantity"] if existing else 0) + quantity
            if current_qty > selected.current_stock: st.error("Quantity exceeds available stock.")
            elif existing:
                existing["quantity"] = current_qty
                existing["unit_price"] = unit_price
            else:
                st.session_state.cart.append({"id": int(selected.id), "name": selected.name, "quantity": quantity, "unit_price": unit_price})
    st.markdown("#### Current cart")
    if st.session_state.cart:
        cart_frame = pd.DataFrame(st.session_state.cart); cart_frame["Line total"] = cart_frame.quantity * cart_frame.unit_price
        st.dataframe(cart_frame[["name", "quantity", "unit_price", "Line total"]].rename(columns={"name":"Product", "quantity":"Qty", "unit_price":"Unit price"}), use_container_width=True, hide_index=True)
        subtotal = sum(item["quantity"] * item["unit_price"] for item in st.session_state.cart)
        pos_left, pos_right = st.columns(2)
        with pos_left:
            customer = st.text_input("Customer name", value="Walk-in Customer")
            payment = st.selectbox("Payment method", ["Cash", "M-Pesa", "Card", "Insurance"])
            cashier = current_user["username"]
            st.text_input("Cashier / user", value=cashier, disabled=True)
        with pos_right:
            discount = st.number_input("Discount (KSh)", min_value=0.0, max_value=float(subtotal), step=10.0)
            st.metric("Grand total", money(subtotal - discount))
            if st.button("Complete sale & generate receipt", type="primary", use_container_width=True):
                receipt, total = create_sale(st.session_state.cart, customer, payment, discount, cashier)
                st.session_state.cart = []
                st.session_state.last_receipt = receipt
                st.success(f"Sale completed: {receipt} · {money(total)}")
                st.rerun()
        if st.button("Clear cart"): st.session_state.cart = []; st.rerun()
    else: st.info("Your cart is empty. Add an in-stock product above to begin.")
    if st.session_state.get("last_receipt"):
        receipt = st.session_state.last_receipt
        st.markdown(receipt_html(receipt), unsafe_allow_html=True)
        st.download_button("Download receipt Excel", receipt_excel_bytes(receipt), f"{receipt}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

elif page == "Inventory & Stock":
    header("Stock register", "Inventory that stays current.", "Add products, monitor replenishment levels, and export the live register.")
    if admin_access:
        st.markdown("#### Excel stock exchange")
        st.caption("Download the exact template, add or edit rows, then upload it. Existing product codes are updated and new codes are added automatically.")
        excel_left, excel_right = st.columns(2)
        with excel_left:
            st.download_button("Download inventory Excel template", inventory_excel_bytes(), "eashers_inventory_template.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        with excel_right:
            inventory_upload = st.file_uploader("Upload completed inventory Excel", type=["xlsx"], key="inventory_excel_upload")
            if inventory_upload is not None and st.button("Accept Excel and update stock", type="primary", use_container_width=True):
                try:
                    inserted, updated = import_inventory_excel(inventory_upload.getvalue(), current_user["username"])
                    st.success(f"Excel accepted: {inserted} new products added and {updated} products updated.")
                    st.rerun()
                except (ValueError, KeyError) as error:
                    st.error(str(error))
        product_form = st.expander("Add new drug product", expanded=False)
    else:
        st.info("Member access is read-only here. An administrator can add, import, update, or delete products.")
        product_form = None
    if product_form:
        with product_form:
            supplier_where, supplier_params = pharmacy_scope()
            supplier_rows = [dict(row) for row in query(f"SELECT id,name FROM suppliers{supplier_where} ORDER BY name", supplier_params)]
            with st.form("new_product"):
                a, b, c = st.columns(3)
                with a: code = st.text_input("Product code *"); name = st.text_input("Drug name *"); category = st.text_input("Category", value="Medicine")
                with b: supplier = st.selectbox("Supplier", supplier_rows, format_func=lambda row: row["name"]); batch = st.text_input("Batch number", value="N/A"); expiry = st.date_input("Expiry date", value=date.today() + timedelta(days=365))
                with c: stock = st.number_input("Initial stock", min_value=0.0, step=1.0); reorder = st.number_input("Reorder level", min_value=0.0, value=5.0, step=1.0); cost = st.number_input("Unit cost (KSh)", min_value=0.0, step=1.0); price = st.number_input("Selling price (KSh)", min_value=0.0, step=1.0)
                save = st.form_submit_button("Save product", type="primary")
            if save:
                try:
                    if not code.strip() or not name.strip(): raise ValueError("Product code and drug name are required.")
                    add_product({"code":code.strip(),"name":name.strip(),"category":category.strip() or "Medicine","supplier_id":supplier["id"],"batch":batch.strip() or "N/A","expiry":expiry.isoformat(),"stock":stock,"reorder":reorder,"cost":cost,"price":price})
                    st.success(f"Added {name.strip()} to inventory."); st.rerun()
                except sqlite3.IntegrityError: st.error("That product code already exists.")
                except ValueError as error: st.error(str(error))
    view = products.copy(); view["Status"] = view.apply(lambda row: status(row.current_stock, row.reorder_level), axis=1); view["Expiry"] = view.expiry_date.apply(expiry_status)
    filter_status = st.multiselect("Filter status", ["OK", "LOW STOCK", "OUT OF STOCK", "EXPIRED", "EXPIRING SOON"])
    if filter_status: view = view[view.Status.isin(filter_status) | view.Expiry.isin(filter_status)]
    st.dataframe(view[["product_code", "name", "category", "supplier", "batch_no", "expiry_date", "current_stock", "reorder_level", "unit_cost", "selling_price", "Status", "Expiry"]].rename(columns={"product_code":"Code","name":"Product","category":"Category","supplier":"Supplier","batch_no":"Batch","expiry_date":"Expiry date","current_stock":"Current stock","reorder_level":"Reorder level","unit_cost":"Cost","selling_price":"Selling price"}), use_container_width=True, hide_index=True)
    st.download_button("Export inventory Excel", dataframe_excel_bytes(view, "Inventory"), "inventory_register.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

elif page == "Daily Sales":
    header("Sales intelligence", "Daily sales log.", "Review every transaction, payment method, cashier, and revenue total.")
    selected_date = st.date_input("Sales date", value=date.today())
    sales_where, sales_params = pharmacy_scope("sales")
    sales_sql = "SELECT receipt_no, created_at, customer_name, payment_method, subtotal, discount, total, cashier FROM sales"
    sales_sql += sales_where + (" AND " if sales_where else " WHERE ") + "date(created_at)=? ORDER BY created_at DESC"
    sales = pd.read_sql_query(sales_sql, db(), params=sales_params + (selected_date.isoformat(),))
    st.metric("Revenue", money(sales.total.sum() if not sales.empty else 0)); st.dataframe(sales.rename(columns={"receipt_no":"Receipt","created_at":"Date & time","customer_name":"Customer","payment_method":"Payment","subtotal":"Subtotal","discount":"Discount","total":"Total","cashier":"Cashier"}), use_container_width=True, hide_index=True)
    st.download_button("Export daily sales Excel", dataframe_excel_bytes(sales, "Daily Sales"), f"sales-{selected_date.isoformat()}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

elif page == "Suppliers":
    header("Supply chain", "Supplier directory.", "Keep contacts, lead times, and payment terms close to the stock they support.")
    if admin_access:
        supplier_form = st.form("new_supplier")
    else:
        st.info("Member access is read-only here. An administrator can add or change supplier records.")
        supplier_form = None
    if supplier_form:
        with supplier_form:
            a,b,c = st.columns(3)
            with a: supplier_name = st.text_input("Supplier name *"); contact = st.text_input("Contact person")
            with b: phone = st.text_input("Phone number"); email = st.text_input("Email address")
            with c: lead = st.number_input("Lead time (days)", min_value=0, step=1); terms = st.text_input("Payment terms")
            save_supplier = st.form_submit_button("Add supplier", type="primary")
    if supplier_form and save_supplier:
        try:
            with db() as connection: connection.execute("INSERT INTO suppliers(name,contact_person,phone,email,lead_time_days,payment_terms,created_at,pharmacy_id) VALUES(?,?,?,?,?,?,?,?)", (supplier_name.strip(),contact,phone,email,lead,terms,now_text(),write_pharmacy_id()))
            add_audit("Supplier added", "Suppliers", f"Added {supplier_name.strip()}"); st.success("Supplier added."); st.rerun()
        except sqlite3.IntegrityError: st.error("That supplier already exists.")
    suppliers_where, suppliers_params = pharmacy_scope()
    suppliers = pd.read_sql_query(f"SELECT name,contact_person,phone,email,lead_time_days,payment_terms FROM suppliers{suppliers_where} ORDER BY name", db(), params=suppliers_params)
    st.dataframe(suppliers.rename(columns={"name":"Supplier","contact_person":"Contact","phone":"Phone","email":"Email","lead_time_days":"Lead days","payment_terms":"Terms"}), use_container_width=True, hide_index=True)

elif page == "Audit Log":
    header("Traceability", "System activity.", "A searchable record of stock, sales, products, and supplier changes.")
    audit_where, audit_params = pharmacy_scope()
    audit = pd.read_sql_query(f"SELECT created_at, action_type, entity, details, performed_by FROM audit_log{audit_where} ORDER BY id DESC", db(), params=audit_params)
    st.dataframe(audit.rename(columns={"created_at":"Date & time","action_type":"Action","entity":"Entity","details":"Details","performed_by":"Performed by"}), use_container_width=True, hide_index=True)
    st.download_button("Export audit log Excel", dataframe_excel_bytes(audit, "Audit Log"), "audit-log.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

elif page == "Pharmacies":
    header("Global administration", "Pharmacy systems.", "Create isolated pharmacy workspaces and assign an administrator to each one.")
    with st.form("new_pharmacy"):
        pharmacy_name = st.text_input("Pharmacy name *")
        pharmacy_location = st.text_input("Location")
        admin_name = st.text_input("Pharmacy admin username *")
        admin_password = st.text_input("Pharmacy admin temporary password *", type="password")
        create_pharmacy = st.form_submit_button("Create pharmacy system", type="primary")
    if create_pharmacy:
        if not pharmacy_name.strip() or not admin_name.strip() or not admin_password:
            st.error("Pharmacy name, admin username, and password are required.")
        else:
            try:
                with db() as connection:
                    pharmacy_id = connection.execute("INSERT INTO pharmacies(name,location,created_at) VALUES(?,?,?)", (pharmacy_name.strip(), pharmacy_location.strip(), now_text())).lastrowid
                    connection.execute("INSERT INTO users(username,password_hash,role,can_manage_inventory,can_manage_suppliers,can_view_reports,can_view_audit,created_at,pharmacy_id) VALUES(?,?,?,?,?,?,?,?,?)", (admin_name.strip(), password_hash(admin_password), "admin", 1, 1, 1, 1, now_text(), pharmacy_id))
                st.success(f"Created {pharmacy_name.strip()} with admin {admin_name.strip()}.")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("The pharmacy name or admin username already exists.")
    pharmacies = pd.read_sql_query("SELECT name,location,active,created_at FROM pharmacies ORDER BY name", db())
    st.dataframe(pharmacies.rename(columns={"name":"Pharmacy","location":"Location","active":"Active","created_at":"Created"}), use_container_width=True, hide_index=True)

elif page == "Members":
    header("Access control", "Team members.", "Create accounts and manage passwords within the current pharmacy scope.")
    with st.form("new_member"):
        member_left, member_right = st.columns(2)
        with member_left:
            member_name = st.text_input("Member username *")
            member_password = st.text_input("Temporary password *", type="password")
        with member_right:
            st.info("Members can view all operational pages and sell, but cannot add/import/update/delete products or change suppliers.")
            manage_inventory = False
            manage_suppliers = False
            view_reports = True
            view_audit = True
        create_member = st.form_submit_button("Create member", type="primary")
    if create_member:
        if not member_name.strip() or not member_password:
            st.error("Username and password are required.")
        else:
            try:
                with db() as connection:
                    connection.execute("INSERT INTO users(username,password_hash,role,can_manage_inventory,can_manage_suppliers,can_view_reports,can_view_audit,created_at,pharmacy_id) VALUES(?,?,?,?,?,?,?,?,?)", (member_name.strip(), password_hash(member_password), "member", int(manage_inventory), int(manage_suppliers), int(view_reports), int(view_audit), now_text(), write_pharmacy_id()))
                add_audit("Member added", "Users", f"Created member account {member_name.strip()}", current_user["username"])
                st.success(f"Member {member_name.strip()} created."); st.rerun()
            except sqlite3.IntegrityError:
                st.error("That username already exists.")
    members_where, members_params = pharmacy_scope()
    members = pd.read_sql_query(f"SELECT username,role,active,can_manage_inventory,can_manage_suppliers,can_view_reports,can_view_audit,created_at FROM users{members_where} ORDER BY username", db(), params=members_params)
    st.dataframe(members.rename(columns={"username":"Username","role":"Role","active":"Active","can_manage_inventory":"Inventory rights","can_manage_suppliers":"Supplier rights","can_view_reports":"Report rights","can_view_audit":"Audit rights","created_at":"Created"}), use_container_width=True, hide_index=True)
    st.markdown("#### Reset a user password")
    reset_where, reset_params = pharmacy_scope("u")
    reset_users = query(f"SELECT u.id, u.username, u.role FROM users u{reset_where} ORDER BY u.username", reset_params)
    reset_users = [row for row in reset_users if row["username"] != current_user["username"]]
    if reset_users:
        with st.form("reset_user_password"):
            reset_target = st.selectbox("User account", reset_users, format_func=lambda row: f"{row['username']} ({row['role'].replace('_', ' ').title()})")
            reset_password = st.text_input("New password *", type="password")
            reset_password_confirmation = st.text_input("Confirm new password *", type="password")
            reset_submitted = st.form_submit_button("Reset password", type="primary")
        if reset_submitted:
            if not reset_password:
                st.error("A new password is required.")
            elif reset_password != reset_password_confirmation:
                st.error("The passwords do not match.")
            else:
                with db() as connection:
                    connection.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash(reset_password), reset_target["id"]))
                add_audit("Password reset", "Users", f"Reset password for {reset_target['username']}", current_user["username"])
                st.success(f"Password reset for {reset_target['username']}.")
    else:
        st.info("No other user accounts are available in this scope.")