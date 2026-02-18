# Personal Finance (Local-Only Django App)

A local personal finance web application built with Django and SQLite.

## Stack
- Django 6
- SQLite
- Bootstrap 5 (Django templates)
- No Docker
- No cloud services
- No external APIs

## Core Features
- User authentication: register, login, logout
- Account management (checking, credit cards, mortgage, payday loans, savings, other)
- Transaction CRUD (income + expenses)
- Transaction filters (account, date range, type, category, title) with pagination
- PDF statement import with review screen before final save
- Statement-level duplicate protection using file hash checks
- CSV statement import (manual monthly uploads)
- User-isolated data (each user sees only their own data)
- Import history audit log
- Analytics hub with cash-flow and category charts
- Visualizations page with a design-focused analytics dashboard:
  - cash flow pulse chart
  - category distribution (donut)
  - account distribution (donut)
  - spending heatmap
  - weekday spending rhythm
  - top merchants and largest transactions
- Reports:
  - income/expense/net summary
  - savings rate
  - essential vs discretionary spending split
  - monthly cut target to improve savings rate
  - top spending categories
  - spending by account
  - top merchants by spend
  - 6-month cash flow trend
  - recurring expense detection
  - rule-based recommendations

## Quick Start
1. Create virtual environment and activate it:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run migrations:
   ```bash
   python manage.py migrate
   ```
4. Create admin user:
   ```bash
   python manage.py createsuperuser
   ```
5. Start server:
   ```bash
   python manage.py runserver
   ```
6. Open app:
   - http://127.0.0.1:8000/
   - http://127.0.0.1:8000/admin/

## Quality Checks
Run before committing:

```bash
python manage.py check
python manage.py test
```

## Monthly Workflow
1. Add your accounts from `Accounts` page.
2. Download monthly statements as PDF from each institution.
3. Import each statement from `Import PDF`.
4. Review and clean up transactions in `Transactions`.
5. Use `Reports` to identify spending reduction opportunities.
6. Use `Visualizations` and `Analytics` for trend analysis.

## PDF Import Notes
- Upload one monthly statement PDF per account.
- The app extracts candidate transactions, then opens a review table where you can edit before saving.
- This review step helps prevent bad imports.
- Large imports are split into pages during review.
- You can provide an optional statement date on upload to improve year inference for short dates like `12/31`.
- Duplicate statement uploads are blocked by default (override available in the import form).
- Some scanned/image-only PDFs may need local OCR tooling for best results.

### Optional OCR setup for scanned PDFs
Install system tools:

```bash
brew install poppler tesseract
```

Then reinstall Python dependencies:

```bash
pip install -r requirements.txt
```

## CSV Format
Use this header format:
```csv
date,title,amount,category,transaction_type,account
```

Example is included at:
- `samples/statement_template.csv`

Notes:
- Date formats supported: `YYYY-MM-DD`, `MM/DD/YYYY`, `DD/MM/YYYY`
- If `transaction_type` is missing, importer infers it from amount sign.
- Duplicate rows are skipped.

## Public GitHub Safety
This repo is configured to avoid committing sensitive local data:
- `db.sqlite3` ignored
- `.env` ignored
- `media/` ignored
- `.venv/` ignored
- common private data folders ignored (`private_data/`, `statements/`, `exports/`)

Still recommended:
- never commit real statement files
- avoid committing screenshots with personal financial data
- use sanitized demo data for portfolio screenshots

## Repair Tool (future-dated import fixes)
If a statement import produced dates in the future by one year, run a dry-run:

```bash
python manage.py fix_future_transaction_dates --username <your_username> --account "Checking account"
```

Then apply:

```bash
python manage.py fix_future_transaction_dates --username <your_username> --account "Checking account" --apply
```
