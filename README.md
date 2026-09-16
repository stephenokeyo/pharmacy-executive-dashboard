# MediShelf Pharmacy

A complete local pharmacy operations website built with Python, Streamlit, SQLite, and pandas.

## Start

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open `http://localhost:8501`.

## Modules

- Dashboard: inventory value, today's revenue, low-stock queue, expiry watch, and stock charts.
- Point of Sale: cart, stock validation, discount, payment method, cashier, stock deduction, on-screen receipt, and Excel receipt download.
- Inventory & Stock: complete product register, add drug form, status filters, and Excel export.
- Daily Sales: date-based transaction log and revenue export.
- Suppliers: contacts, lead times, and payment terms.
- Audit Log: traceable product, supplier, and sale activity.
- Login and permissions: administrator `Stephen` with password `Stephen@12k`; members can be created as sales-only users with optional rights.
- Real-time updates: the app refreshes every 10 seconds and records the signed-in user and event time.
- Excel stock exchange: download the canonical inventory workbook, edit it, and upload it to add products or update stock by Product ID. The sheet uses exactly: Product ID, Product Name, Supplier Name, Batch No, Expiry Date, Initial Stock, QTY Sold, Current Stock, Reorder Level, Unit Cost (KSh), Total Cost (KSh), Markup %, Selling Price (KSh), Expiry Status, Stock Status.
- All extracted reports are Excel workbooks: inventory, daily sales, audit log, and receipts.

The database is stored locally in `pharmacy.db` and is created automatically with starter data on first run.