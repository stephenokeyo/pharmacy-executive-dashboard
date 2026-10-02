# SECURE TECH SOLUTIONS

A pharmacy operations application built with Streamlit, using Supabase/PostgreSQL as the source of truth and Firebase Firestore as a mirror of operational records.

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

For local development, set `FIREBASE_SERVICE_ACCOUNT_FILE` to the JSON file path. Alternatively, provide the complete JSON through `FIREBASE_SERVICE_ACCOUNT_JSON`. The app mirrors pharmacy, supplier, product, sale, sale-item, and audit records into Firestore collections named `securetech_<table>` using a PostgreSQL transactional outbox. Existing rows are queued once during setup; later inserts, updates, and deletes are queued in the same Supabase transaction and delivered to Firestore after commit. Supabase remains authoritative, and Firestore catches up automatically if temporarily unavailable. User password hashes are intentionally not copied to Firestore.

### Supabase / Postgres
Set these in Render or your hosting environment:

```bash
SUPABASE_DATABASE_URL=postgresql://postgres:your-password@db.project-ref.supabase.co:5432/postgres
```

Get the connection string from your Supabase project's **Connect** panel. Enter it as `SUPABASE_DATABASE_URL` in Render's Environment settings. The app uses this Supabase PostgreSQL database for pharmacy, inventory, sales, and user records; Firebase is required for audit-event storage. Local SQLite and Render-managed Postgres are not used as fallbacks.

### Initial administrator
When the `users` table is empty, set `BOOTSTRAP_ADMIN_USERNAME` and `BOOTSTRAP_ADMIN_PASSWORD` in the hosting environment before starting the app. Use a unique password of at least 16 characters and store it as a secret; do not put it in source code or this README. These values are used only to create the first super-admin and do not reset existing accounts. On Render, configure both variables under the service's Environment settings. Existing deployments with users already in Supabase do not need them.

## Modules

- Dashboard: inventory value, today's revenue, low-stock queue, expiry watch, and stock charts.
- Point of Sale: cart, stock validation, discount, payment method, cashier, stock deduction, on-screen receipt, and Excel receipt download.
- Inventory & Stock: complete product register, add drug form, status filters, and Excel export.
- Daily Sales: date-based transaction log and revenue export.
- Suppliers: contacts, lead times, and payment terms.
- Audit Log: traceable product, supplier, and sale activity.
- Login and permissions: the initial administrator is configured through bootstrap environment secrets; members can be created as sales-only users with optional rights.
- Dashboard data refreshes every 60 seconds while the dashboard is open; other pages rerun only when interacted with. Audit entries record the signed-in user and event time.
- Excel stock exchange: download the canonical inventory workbook, edit it, and upload it to add products or update stock by Product ID. The sheet uses exactly: Product ID, Product Name, Supplier Name, Batch No, Expiry Date, Initial Stock, QTY Sold, Current Stock, Reorder Level, Unit Cost (KSh), Total Cost (KSh), Markup %, Selling Price (KSh), Expiry Status, Stock Status.
- All extracted reports are Excel workbooks: inventory, daily sales, audit log, and receipts.

The app keeps the same Streamlit/Render hosting model and connects to both live services through environment variables.