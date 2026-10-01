# SECURE TECH SOLUTIONS

A pharmacy operations application built with Streamlit, using Supabase/PostgreSQL for relational records and Firebase Firestore for required audit-event storage.

## Start

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open `http://localhost:8501`.

## Required database setup

Both Firebase and Supabase are required for the application to start.

### Firebase Firestore

Create a Firebase service account with Firestore access and enable Cloud Firestore in the project. Download its JSON key, then add it in Render under the service's **Environment > Secret Files** as `firebase-service-account.json`. The app reads it from Render's `/etc/secrets/` directory. Keep this file private and never commit it.

For local development, set `FIREBASE_SERVICE_ACCOUNT_FILE` to the JSON file path. Alternatively, provide the complete JSON through `FIREBASE_SERVICE_ACCOUNT_JSON`. The app verifies Firestore connectivity at startup and writes audit events to the `audit_log` collection.

### Supabase / Postgres
Set these in Render or your hosting environment:

```bash
SUPABASE_DATABASE_URL=postgresql://postgres:your-password@db.project-ref.supabase.co:5432/postgres
```

Get the connection string from your Supabase project's **Connect** panel. Enter it as `SUPABASE_DATABASE_URL` in Render's Environment settings. The app uses this Supabase PostgreSQL database for pharmacy, inventory, sales, and user records; Firebase is required for audit-event storage. Local SQLite and Render-managed Postgres are not used as fallbacks.

## Modules

- Dashboard: inventory value, today's revenue, low-stock queue, expiry watch, and stock charts.
- Point of Sale: cart, stock validation, discount, payment method, cashier, stock deduction, on-screen receipt, and Excel receipt download.
- Inventory & Stock: complete product register, add drug form, status filters, and Excel export.
- Daily Sales: date-based transaction log and revenue export.
- Suppliers: contacts, lead times, and payment terms.
- Audit Log: traceable product, supplier, and sale activity.
- Login and permissions: administrator `Stephen` with password `Stephen@12k`; members can be created as sales-only users with optional rights.
- Dashboard data refreshes every 60 seconds while the dashboard is open; other pages rerun only when interacted with. Audit entries record the signed-in user and event time.
- Excel stock exchange: download the canonical inventory workbook, edit it, and upload it to add products or update stock by Product ID. The sheet uses exactly: Product ID, Product Name, Supplier Name, Batch No, Expiry Date, Initial Stock, QTY Sold, Current Stock, Reorder Level, Unit Cost (KSh), Total Cost (KSh), Markup %, Selling Price (KSh), Expiry Status, Stock Status.
- All extracted reports are Excel workbooks: inventory, daily sales, audit log, and receipts.

The app keeps the same Streamlit/Render hosting model and connects to both live services through environment variables.