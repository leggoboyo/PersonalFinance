import csv
import hashlib
import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import StringIO
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import (
    CSVImportForm,
    PDFImportForm,
    AccountForm,
    CustomUserRegistrationForm,
    ExpenseForm,
)
from .models import Account, Expense, StatementImport
from .pdf_import import extract_transactions_from_pdf

PDF_PREVIEW_PAGE_SIZE = 100


def _parse_date(raw_date: str) -> date:
    raw_date = (raw_date or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw_date, fmt).date()
        except ValueError:
            continue
    raise ValueError("Unsupported date format. Use YYYY-MM-DD or MM/DD/YYYY.")


def _parse_amount(raw_amount: str) -> Decimal:
    cleaned = (raw_amount or "").replace("$", "").replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except (InvalidOperation, TypeError):
        raise ValueError("Amount is not a valid decimal number.")


def _next_month_start(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1)
    return date(month_start.year, month_start.month + 1, 1)


def _recent_month_starts(count: int) -> list[date]:
    today = timezone.localdate()
    year = today.year
    month = today.month
    starts: list[date] = []
    for _ in range(count):
        starts.append(date(year, month, 1))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    starts.reverse()
    return starts


def _infer_statement_date_from_filename(filename: str) -> date | None:
    match = re.search(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", filename or "")
    if not match:
        return None

    try:
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        return date(year, month, day)
    except ValueError:
        return None


def _compute_file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def _find_existing_import(user, file_hash: str) -> StatementImport | None:
    return (
        StatementImport.objects.filter(
            user=user,
            file_hash=file_hash,
            status=StatementImport.Status.IMPORTED,
        )
        .order_by("-created_at")
        .first()
    )


def _maybe_block_duplicate_statement(
    *,
    user,
    account,
    source_type: str,
    filename: str,
    file_hash: str,
    statement_date: date | None,
    allow_duplicate_statement: bool,
) -> StatementImport | None:
    existing_import = _find_existing_import(user, file_hash)
    if existing_import is None or allow_duplicate_statement:
        return None

    StatementImport.objects.create(
        user=user,
        account=account,
        source_type=source_type,
        status=StatementImport.Status.BLOCKED_DUPLICATE,
        filename=filename,
        file_hash=file_hash,
        statement_date=statement_date,
        notes=(
            "Blocked duplicate upload. Matching file was already imported on "
            f"{existing_import.created_at:%Y-%m-%d %H:%M}."
        ),
    )
    return existing_import


def _upsert_expense_from_row(
    *,
    user,
    account,
    title: str,
    amount: Decimal,
    category: str,
    transaction_type: str,
    tx_date: date,
) -> bool:
    duplicate = Expense.objects.filter(
        user=user,
        account=account,
        title=title,
        amount=amount,
        category=category,
        transaction_type=transaction_type,
        date=tx_date,
    ).exists()
    if duplicate:
        return False

    Expense.objects.create(
        user=user,
        account=account,
        title=title,
        amount=amount,
        category=category,
        transaction_type=transaction_type,
        date=tx_date,
    )
    return True


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        form = CustomUserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Account created successfully.")
            return redirect("dashboard")
    else:
        form = CustomUserRegistrationForm()

    return render(request, "registration/register.html", {"form": form})


@login_required
def dashboard(request):
    user_expenses = Expense.objects.filter(user=request.user)
    total_income = (
        user_expenses.filter(transaction_type=Expense.TransactionType.INCOME).aggregate(
            total=Sum("amount")
        )["total"]
        or Decimal("0.00")
    )
    total_expenses = (
        user_expenses.filter(
            transaction_type=Expense.TransactionType.EXPENSE
        ).aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )
    net_balance = total_income - total_expenses
    recent_expenses = user_expenses[:5]

    context = {
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_balance": net_balance,
        "recent_expenses": recent_expenses,
    }
    return render(request, "tracker/dashboard.html", context)


@login_required
def expense_list(request):
    expenses = Expense.objects.filter(user=request.user).select_related("account")
    accounts = Account.objects.filter(user=request.user)

    q = request.GET.get("q", "").strip()
    tx_type = request.GET.get("transaction_type", "").strip().upper()
    account_id = request.GET.get("account", "").strip()
    category = request.GET.get("category", "").strip()
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()

    if q:
        expenses = expenses.filter(title__icontains=q)
    if tx_type in {Expense.TransactionType.INCOME, Expense.TransactionType.EXPENSE}:
        expenses = expenses.filter(transaction_type=tx_type)
    if account_id.isdigit():
        expenses = expenses.filter(account_id=int(account_id))
    if category:
        expenses = expenses.filter(category__icontains=category)
    if start_date:
        try:
            expenses = expenses.filter(date__gte=_parse_date(start_date))
        except ValueError:
            messages.warning(request, "Invalid start date filter ignored.")
    if end_date:
        try:
            expenses = expenses.filter(date__lte=_parse_date(end_date))
        except ValueError:
            messages.warning(request, "Invalid end date filter ignored.")

    paginator = Paginator(expenses, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    query_params = request.GET.copy()
    query_params.pop("page", None)
    base_query = query_params.urlencode()

    context = {
        "expenses": page_obj,
        "accounts": accounts,
        "filters": {
            "q": q,
            "transaction_type": tx_type,
            "account": account_id,
            "category": category,
            "start_date": start_date,
            "end_date": end_date,
        },
        "base_query": base_query,
    }
    return render(request, "tracker/expense_list.html", context)


@login_required
def expense_create(request):
    if request.method == "POST":
        form = ExpenseForm(request.POST, user=request.user)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.user = request.user
            expense.save()
            messages.success(request, "Transaction created.")
            return redirect("expense_list")
    else:
        form = ExpenseForm(
            user=request.user,
            initial={"date": timezone.now().date()},
        )

    return render(
        request,
        "tracker/expense_form.html",
        {"form": form, "page_title": "Add Transaction", "submit_label": "Create"},
    )


@login_required
def expense_update(request, pk):
    expense = get_object_or_404(Expense, pk=pk, user=request.user)

    if request.method == "POST":
        form = ExpenseForm(request.POST, instance=expense, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Transaction updated.")
            return redirect("expense_list")
    else:
        form = ExpenseForm(instance=expense, user=request.user)

    return render(
        request,
        "tracker/expense_form.html",
        {"form": form, "page_title": "Edit Transaction", "submit_label": "Save"},
    )


@login_required
def expense_delete(request, pk):
    expense = get_object_or_404(Expense, pk=pk, user=request.user)

    if request.method == "POST":
        expense.delete()
        messages.success(request, "Transaction deleted.")
        return redirect("expense_list")

    return render(request, "tracker/expense_confirm_delete.html", {"expense": expense})


@login_required
def account_list(request):
    accounts = Account.objects.filter(user=request.user)
    return render(request, "tracker/account_list.html", {"accounts": accounts})


@login_required
def account_create(request):
    if request.method == "POST":
        form = AccountForm(request.POST)
        if form.is_valid():
            account = form.save(commit=False)
            account.user = request.user
            account.save()
            messages.success(request, "Account created.")
            return redirect("account_list")
    else:
        form = AccountForm()

    return render(
        request,
        "tracker/account_form.html",
        {"form": form, "page_title": "Add Account", "submit_label": "Create"},
    )


@login_required
def account_update(request, pk):
    account = get_object_or_404(Account, pk=pk, user=request.user)
    if request.method == "POST":
        form = AccountForm(request.POST, instance=account)
        if form.is_valid():
            form.save()
            messages.success(request, "Account updated.")
            return redirect("account_list")
    else:
        form = AccountForm(instance=account)

    return render(
        request,
        "tracker/account_form.html",
        {"form": form, "page_title": "Edit Account", "submit_label": "Save"},
    )


@login_required
def import_csv(request):
    if request.method == "POST":
        form = CSVImportForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            selected_account = form.cleaned_data["account"]
            csv_file = form.cleaned_data["csv_file"]
            has_header = form.cleaned_data["has_header"]
            allow_duplicate_statement = form.cleaned_data["allow_duplicate_statement"]
            statement_date = _infer_statement_date_from_filename(csv_file.name)

            file_bytes = csv_file.read()
            file_hash = _compute_file_hash(file_bytes)
            existing_import = _maybe_block_duplicate_statement(
                user=request.user,
                account=selected_account,
                source_type=StatementImport.SourceType.CSV,
                filename=csv_file.name,
                file_hash=file_hash,
                statement_date=statement_date,
                allow_duplicate_statement=allow_duplicate_statement,
            )
            if existing_import is not None:
                messages.error(
                    request,
                    "This statement file was already imported. "
                    "Use the override checkbox only if you intentionally want to re-process it.",
                )
                return render(request, "tracker/import_csv.html", {"form": form})

            decoded = file_bytes.decode("utf-8-sig")
            stream = StringIO(decoded)

            created_count = 0
            skipped_count = 0
            error_rows: list[str] = []

            with transaction.atomic():
                if has_header:
                    reader = csv.DictReader(stream)
                    rows = list(reader)
                else:
                    reader = csv.reader(stream)
                    rows = [
                        {
                            "date": row[0] if len(row) > 0 else "",
                            "title": row[1] if len(row) > 1 else "",
                            "amount": row[2] if len(row) > 2 else "",
                            "category": row[3] if len(row) > 3 else "",
                            "transaction_type": row[4] if len(row) > 4 else "",
                            "account": row[5] if len(row) > 5 else "",
                        }
                        for row in reader
                    ]

                for index, row in enumerate(rows, start=2):
                    try:
                        tx_date = _parse_date(row.get("date", ""))
                        title = (row.get("title", "") or "").strip()
                        if not title:
                            raise ValueError("Title is required.")

                        raw_amount = _parse_amount(row.get("amount", ""))
                        tx_type = (row.get("transaction_type", "") or "").strip().upper()
                        if tx_type not in {
                            Expense.TransactionType.INCOME,
                            Expense.TransactionType.EXPENSE,
                        }:
                            tx_type = (
                                Expense.TransactionType.INCOME
                                if raw_amount > 0
                                else Expense.TransactionType.EXPENSE
                            )

                        amount = abs(raw_amount)
                        category = (row.get("category", "") or "").strip() or "Uncategorized"

                        row_account_name = (row.get("account", "") or "").strip()
                        account = selected_account
                        if row_account_name:
                            account = Account.objects.filter(
                                user=request.user,
                                name__iexact=row_account_name,
                            ).first()
                            if account is None:
                                account = Account.objects.create(
                                    user=request.user,
                                    name=row_account_name,
                                    account_type=Account.AccountType.OTHER,
                                )

                        created = _upsert_expense_from_row(
                            user=request.user,
                            account=account,
                            title=title,
                            amount=amount,
                            category=category,
                            transaction_type=tx_type,
                            tx_date=tx_date,
                        )
                        if not created:
                            skipped_count += 1
                            continue
                        created_count += 1
                    except ValueError as exc:
                        error_rows.append(f"Row {index}: {exc}")

            notes = ""
            if error_rows:
                notes = " | ".join(error_rows[:5])
            StatementImport.objects.create(
                user=request.user,
                account=selected_account,
                source_type=StatementImport.SourceType.CSV,
                status=StatementImport.Status.IMPORTED,
                filename=csv_file.name,
                file_hash=file_hash,
                statement_date=statement_date,
                rows_detected=len(rows),
                rows_imported=created_count,
                rows_skipped=skipped_count + len(error_rows),
                notes=notes,
            )

            if created_count:
                messages.success(request, f"Imported {created_count} transactions.")
            if skipped_count:
                messages.info(request, f"Skipped {skipped_count} duplicates.")
            if error_rows:
                messages.warning(
                    request,
                    "Some rows were not imported: " + " | ".join(error_rows[:5]),
                )
            return redirect("expense_list")
    else:
        form = CSVImportForm(user=request.user)

    return render(request, "tracker/import_csv.html", {"form": form})


@login_required
def import_pdf(request):
    if request.method == "POST":
        form = PDFImportForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            account = form.cleaned_data["account"]
            pdf_file = form.cleaned_data["pdf_file"]
            statement_date = form.cleaned_data.get("statement_date")
            allow_duplicate_statement = form.cleaned_data["allow_duplicate_statement"]
            if statement_date is None:
                statement_date = _infer_statement_date_from_filename(pdf_file.name)
            if statement_date is None:
                statement_date = timezone.localdate()

            file_bytes = pdf_file.read()
            file_hash = _compute_file_hash(file_bytes)
            existing_import = _maybe_block_duplicate_statement(
                user=request.user,
                account=account,
                source_type=StatementImport.SourceType.PDF,
                filename=pdf_file.name,
                file_hash=file_hash,
                statement_date=statement_date,
                allow_duplicate_statement=allow_duplicate_statement,
            )
            if existing_import is not None:
                messages.error(
                    request,
                    "This statement file was already imported. "
                    "Use the override checkbox only if you intentionally want to re-process it.",
                )
                return render(request, "tracker/import_pdf.html", {"form": form})

            rows, warnings = extract_transactions_from_pdf(
                file_bytes,
                reference_date=statement_date,
            )

            for warning in warnings[:3]:
                messages.warning(request, warning)

            if not rows:
                messages.error(
                    request,
                    "No transactions could be extracted from this PDF. Try another statement or install pdfplumber/pypdf locally.",
                )
                return render(request, "tracker/import_pdf.html", {"form": form})

            normalized_rows = [{**row, "include": True} for row in rows]
            request.session["pdf_import_preview"] = {
                "account_id": account.id,
                "rows": normalized_rows,
                "filename": pdf_file.name,
                "statement_date": statement_date.isoformat(),
                "file_hash": file_hash,
            }
            return redirect("import_pdf_preview")
    else:
        form = PDFImportForm(user=request.user)

    return render(request, "tracker/import_pdf.html", {"form": form})


@login_required
def import_pdf_preview(request):
    payload = request.session.get("pdf_import_preview")
    if not payload:
        messages.info(request, "No PDF import is in progress.")
        return redirect("import_pdf")

    account = get_object_or_404(Account, pk=payload["account_id"], user=request.user)
    rows = payload.get("rows", [])
    statement_date_value = payload.get("statement_date")
    statement_date = None
    if statement_date_value:
        try:
            statement_date = _parse_date(statement_date_value)
        except ValueError:
            statement_date = None
    file_hash = payload.get("file_hash")
    if not file_hash:
        file_hash = hashlib.sha256(
            f"{payload.get('filename', '')}|{statement_date_value or ''}".encode("utf-8")
        ).hexdigest()
    if not isinstance(rows, list):
        rows = []
    total_rows = len(rows)
    total_pages = max(1, math.ceil(total_rows / PDF_PREVIEW_PAGE_SIZE))

    try:
        page = int(request.GET.get("page", request.POST.get("page", "1")))
    except (TypeError, ValueError):
        page = 1
    page = max(1, min(page, total_pages))

    page_start = (page - 1) * PDF_PREVIEW_PAGE_SIZE
    page_end = min(page_start + PDF_PREVIEW_PAGE_SIZE, total_rows)

    if request.method == "POST":
        action = request.POST.get("action", "confirm")
        if action == "cancel":
            request.session.pop("pdf_import_preview", None)
            messages.info(request, "PDF import canceled.")
            return redirect("import_pdf")

        # Persist the edits and include/exclude flags for the current page.
        for index in range(page_start, page_end):
            row = rows[index]
            row["include"] = request.POST.get(f"include_{index}") == "on"
            row["date"] = request.POST.get(f"date_{index}", row.get("date", ""))
            row["title"] = request.POST.get(f"title_{index}", row.get("title", ""))
            row["amount"] = request.POST.get(f"amount_{index}", row.get("amount", ""))
            row["category"] = request.POST.get(
                f"category_{index}", row.get("category", "")
            )
            row["transaction_type"] = request.POST.get(
                f"transaction_type_{index}",
                row.get("transaction_type", Expense.TransactionType.EXPENSE),
            ).upper()

        payload["rows"] = rows
        request.session["pdf_import_preview"] = payload
        request.session.modified = True

        if action == "next":
            next_page = min(page + 1, total_pages)
            return redirect(f"{reverse('import_pdf_preview')}?{urlencode({'page': next_page})}")
        if action == "prev":
            prev_page = max(page - 1, 1)
            return redirect(f"{reverse('import_pdf_preview')}?{urlencode({'page': prev_page})}")

        created_count = 0
        skipped_count = 0
        error_rows: list[str] = []

        with transaction.atomic():
            for index, row in enumerate(rows):
                if not row.get("include", True):
                    continue

                try:
                    tx_date = _parse_date(row.get("date", ""))
                    title = (row.get("title", "") or "").strip()
                    if not title:
                        raise ValueError("Title is required.")
                    raw_amount = _parse_amount(row.get("amount", ""))
                    amount = abs(raw_amount)
                    category = (row.get("category", "").strip() or "Uncategorized")
                    tx_type = (row.get("transaction_type", "") or "").strip().upper()
                    if tx_type not in {
                        Expense.TransactionType.INCOME,
                        Expense.TransactionType.EXPENSE,
                    }:
                        raise ValueError("transaction_type must be INCOME or EXPENSE.")

                    created = _upsert_expense_from_row(
                        user=request.user,
                        account=account,
                        title=title,
                        amount=amount,
                        category=category,
                        transaction_type=tx_type,
                        tx_date=tx_date,
                    )
                    if created:
                        created_count += 1
                    else:
                        skipped_count += 1
                except ValueError as exc:
                    error_rows.append(f"Row {index + 1}: {exc}")

        request.session.pop("pdf_import_preview", None)
        notes = ""
        if error_rows:
            notes = " | ".join(error_rows[:5])
        StatementImport.objects.create(
            user=request.user,
            account=account,
            source_type=StatementImport.SourceType.PDF,
            status=StatementImport.Status.IMPORTED,
            filename=payload.get("filename", "statement.pdf"),
            file_hash=file_hash,
            statement_date=statement_date,
            rows_detected=len(rows),
            rows_imported=created_count,
            rows_skipped=skipped_count + len(error_rows),
            notes=notes,
        )
        if created_count:
            messages.success(request, f"Imported {created_count} transactions from PDF.")
        if skipped_count:
            messages.info(request, f"Skipped {skipped_count} duplicates.")
        if error_rows:
            messages.warning(
                request,
                "Some rows were not imported: " + " | ".join(error_rows[:5]),
            )
        return redirect("expense_list")

    context = {
        "account": account,
        "filename": payload.get("filename", "statement.pdf"),
        "statement_date": statement_date_value,
        "rows": list(enumerate(rows[page_start:page_end], start=page_start)),
        "page": page,
        "total_pages": total_pages,
        "total_rows": total_rows,
        "page_start": page_start + 1 if total_rows else 0,
        "page_end": page_end,
    }
    return render(request, "tracker/import_pdf_preview.html", context)


def _to_float(value) -> float:
    if value is None:
        return 0.0
    return float(value)


@login_required
def import_history(request):
    imports = StatementImport.objects.filter(user=request.user).select_related("account")
    paginator = Paginator(imports, 30)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "tracker/import_history.html", {"imports": page_obj})


@login_required
def analytics_hub(request):
    period = request.GET.get("period", "365d")
    account_filter = request.GET.get("account", "all")
    period_days = {"30d": 30, "90d": 90, "180d": 180, "365d": 365}

    accounts = Account.objects.filter(user=request.user)
    transactions = Expense.objects.filter(user=request.user).select_related("account")
    selected_account = None
    if account_filter != "all":
        selected_account = accounts.filter(pk=account_filter).first()
        if selected_account is not None:
            transactions = transactions.filter(account=selected_account)

    today = timezone.localdate()
    start_date = None
    if period in period_days:
        start_date = today - timedelta(days=period_days[period])
        transactions = transactions.filter(date__gte=start_date)
    elif period != "all":
        period = "365d"
        start_date = today - timedelta(days=period_days[period])
        transactions = transactions.filter(date__gte=start_date)

    total_income = (
        transactions.filter(transaction_type=Expense.TransactionType.INCOME).aggregate(
            total=Sum("amount")
        )["total"]
        or Decimal("0.00")
    )
    total_expenses = (
        transactions.filter(transaction_type=Expense.TransactionType.EXPENSE).aggregate(
            total=Sum("amount")
        )["total"]
        or Decimal("0.00")
    )
    net_balance = total_income - total_expenses
    savings_rate = Decimal("0.00")
    if total_income > 0:
        savings_rate = (net_balance / total_income) * Decimal("100")

    chart_months = 6 if period in {"30d", "90d", "180d"} else 12
    month_starts = _recent_month_starts(chart_months)
    trend_labels: list[str] = []
    trend_income: list[float] = []
    trend_expenses: list[float] = []
    trend_net: list[float] = []

    for month_start in month_starts:
        month_end = _next_month_start(month_start)
        month_qs = transactions.filter(date__gte=month_start, date__lt=month_end)
        month_income = (
            month_qs.filter(transaction_type=Expense.TransactionType.INCOME).aggregate(
                total=Sum("amount")
            )["total"]
            or Decimal("0.00")
        )
        month_expense = (
            month_qs.filter(transaction_type=Expense.TransactionType.EXPENSE).aggregate(
                total=Sum("amount")
            )["total"]
            or Decimal("0.00")
        )
        trend_labels.append(month_start.strftime("%b %Y"))
        trend_income.append(_to_float(month_income))
        trend_expenses.append(_to_float(month_expense))
        trend_net.append(_to_float(month_income - month_expense))

    category_rows = list(
        transactions.filter(transaction_type=Expense.TransactionType.EXPENSE)
        .values("category")
        .annotate(total=Sum("amount"))
        .order_by("-total")[:8]
    )
    category_labels = [row["category"] for row in category_rows]
    category_values = [_to_float(row["total"]) for row in category_rows]

    transaction_count = transactions.count()
    expense_transaction_count = transactions.filter(
        transaction_type=Expense.TransactionType.EXPENSE
    ).count()
    average_transaction = Decimal("0.00")
    if expense_transaction_count:
        average_transaction = total_expenses / expense_transaction_count
    largest_expense = (
        transactions.filter(transaction_type=Expense.TransactionType.EXPENSE)
        .order_by("-amount")
        .first()
    )

    import_qs = StatementImport.objects.filter(user=request.user).select_related("account")
    recent_imports = import_qs[:8]
    imported_count = import_qs.filter(status=StatementImport.Status.IMPORTED).count()
    blocked_count = import_qs.filter(
        status=StatementImport.Status.BLOCKED_DUPLICATE
    ).count()

    context = {
        "period": period,
        "account_filter": account_filter,
        "accounts": accounts,
        "selected_account": selected_account,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_balance": net_balance,
        "savings_rate": savings_rate,
        "transaction_count": transaction_count,
        "average_transaction": average_transaction,
        "largest_expense": largest_expense,
        "recent_imports": recent_imports,
        "imported_count": imported_count,
        "blocked_count": blocked_count,
        "trend_data": {
            "labels": trend_labels,
            "income": trend_income,
            "expenses": trend_expenses,
            "net": trend_net,
        },
        "category_data": {"labels": category_labels, "values": category_values},
    }
    return render(request, "tracker/analytics_hub.html", context)


@login_required
def visualizations(request):
    period = request.GET.get("period", "365d")
    account_filter = request.GET.get("account", "all")
    period_days = {"30d": 30, "90d": 90, "180d": 180, "365d": 365, "730d": 730}

    accounts = Account.objects.filter(user=request.user)
    transactions = Expense.objects.filter(user=request.user).select_related("account")
    selected_account = None
    if account_filter != "all":
        selected_account = accounts.filter(pk=account_filter).first()
        if selected_account is None:
            account_filter = "all"
        else:
            transactions = transactions.filter(account=selected_account)

    today = timezone.localdate()
    start_date = None
    if period in period_days:
        start_date = today - timedelta(days=period_days[period])
        transactions = transactions.filter(date__gte=start_date)
    elif period != "all":
        period = "365d"
        start_date = today - timedelta(days=period_days[period])
        transactions = transactions.filter(date__gte=start_date)

    income_qs = transactions.filter(transaction_type=Expense.TransactionType.INCOME)
    expense_qs = transactions.filter(transaction_type=Expense.TransactionType.EXPENSE)

    total_income = income_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    total_expenses = expense_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    net_balance = total_income - total_expenses

    savings_rate = Decimal("0.00")
    if total_income > 0:
        savings_rate = (net_balance / total_income) * Decimal("100")

    oldest_tx = transactions.order_by("date").first()
    if start_date is not None:
        days_in_scope = max((today - start_date).days, 1)
    elif oldest_tx is not None:
        days_in_scope = max((today - oldest_tx.date).days, 1)
    else:
        days_in_scope = 1
    avg_daily_expense = total_expenses / Decimal(days_in_scope)

    chart_months = 12 if period not in {"30d", "90d"} else 6
    month_starts = _recent_month_starts(chart_months)
    if start_date is not None:
        month_starts = [
            month_start
            for month_start in month_starts
            if _next_month_start(month_start) > start_date
        ]
    if not month_starts:
        month_starts = [date(today.year, today.month, 1)]

    monthly_labels: list[str] = []
    monthly_income: list[float] = []
    monthly_expenses: list[float] = []
    monthly_net: list[float] = []
    for month_start in month_starts:
        month_end = _next_month_start(month_start)
        month_qs = transactions.filter(date__gte=month_start, date__lt=month_end)
        month_income = (
            month_qs.filter(transaction_type=Expense.TransactionType.INCOME).aggregate(
                total=Sum("amount")
            )["total"]
            or Decimal("0.00")
        )
        month_expense = (
            month_qs.filter(transaction_type=Expense.TransactionType.EXPENSE).aggregate(
                total=Sum("amount")
            )["total"]
            or Decimal("0.00")
        )
        monthly_labels.append(month_start.strftime("%b %Y"))
        monthly_income.append(_to_float(month_income))
        monthly_expenses.append(_to_float(month_expense))
        monthly_net.append(_to_float(month_income - month_expense))

    category_rows = list(
        expense_qs.values("category").annotate(total=Sum("amount")).order_by("-total")[:9]
    )
    for row in category_rows:
        row["share"] = (
            ((row["total"] / total_expenses) * Decimal("100"))
            if total_expenses > 0
            else Decimal("0.00")
        )

    account_rows = list(
        expense_qs.values("account__name").annotate(total=Sum("amount")).order_by("-total")
    )
    for row in account_rows:
        row["account_label"] = row["account__name"] or "Unassigned"
        row["share"] = (
            ((row["total"] / total_expenses) * Decimal("100"))
            if total_expenses > 0
            else Decimal("0.00")
        )

    weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weekday_totals = [0.0] * 7
    weekday_rows = list(expense_qs.values("date").annotate(total=Sum("amount")))
    for row in weekday_rows:
        weekday_index = row["date"].weekday()
        weekday_totals[weekday_index] += _to_float(row["total"])

    heatmap_days = 140
    heatmap_start = today - timedelta(days=heatmap_days - 1)
    heatmap_rows = list(
        expense_qs.filter(date__gte=heatmap_start)
        .values("date")
        .annotate(total=Sum("amount"))
    )
    daily_totals = {row["date"]: _to_float(row["total"]) for row in heatmap_rows}
    heatmap_points = []
    for offset in range(heatmap_days):
        point_date = heatmap_start + timedelta(days=offset)
        heatmap_points.append(
            {
                "date": point_date.isoformat(),
                "total": daily_totals.get(point_date, 0.0),
            }
        )

    top_transactions = list(expense_qs.order_by("-amount")[:7])
    top_merchants = list(
        expense_qs.values("title").annotate(total=Sum("amount"), count=Count("id")).order_by(
            "-total"
        )[:7]
    )
    for merchant in top_merchants:
        merchant["total_f"] = _to_float(merchant["total"])

    context = {
        "period": period,
        "account_filter": account_filter,
        "accounts": accounts,
        "selected_account": selected_account,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_balance": net_balance,
        "savings_rate": savings_rate,
        "avg_daily_expense": avg_daily_expense,
        "top_transactions": top_transactions,
        "top_merchants": top_merchants,
        "category_rows": category_rows,
        "account_rows": account_rows,
        "viz_data": {
            "monthly": {
                "labels": monthly_labels,
                "income": monthly_income,
                "expenses": monthly_expenses,
                "net": monthly_net,
            },
            "categories": {
                "labels": [row["category"] for row in category_rows],
                "values": [_to_float(row["total"]) for row in category_rows],
            },
            "accounts": {
                "labels": [row["account_label"] for row in account_rows],
                "values": [_to_float(row["total"]) for row in account_rows],
            },
            "weekdays": {"labels": weekday_labels, "values": weekday_totals},
            "heatmap": heatmap_points,
        },
    }
    return render(request, "tracker/visualizations.html", context)


@login_required
def reports(request):
    period = request.GET.get("period", "90d")
    account_filter = request.GET.get("account", "all")
    period_days = {"30d": 30, "90d": 90, "365d": 365}
    today = timezone.localdate()
    user_accounts = Account.objects.filter(user=request.user)
    expenses = Expense.objects.filter(user=request.user).select_related("account")
    selected_account = None

    if account_filter != "all":
        selected_account = user_accounts.filter(pk=account_filter).first()
        if selected_account is not None:
            expenses = expenses.filter(account=selected_account)

    start_date = None
    if period in period_days:
        start_date = today - timedelta(days=period_days[period])
        expenses = expenses.filter(date__gte=start_date)
    elif period != "all":
        period = "90d"
        start_date = today - timedelta(days=90)
        expenses = expenses.filter(date__gte=start_date)

    total_income = (
        expenses.filter(transaction_type=Expense.TransactionType.INCOME).aggregate(
            total=Sum("amount")
        )["total"]
        or Decimal("0.00")
    )
    total_expenses = (
        expenses.filter(transaction_type=Expense.TransactionType.EXPENSE).aggregate(
            total=Sum("amount")
        )["total"]
        or Decimal("0.00")
    )
    net_balance = total_income - total_expenses
    savings_rate = Decimal("0.00")
    if total_income > 0:
        savings_rate = (net_balance / total_income) * Decimal("100")
    monthly_expense_target = Decimal("0.00")
    if savings_rate < 15 and total_income > 0:
        required_net = total_income * Decimal("0.15")
        monthly_expense_target = required_net - net_balance
        if monthly_expense_target < 0:
            monthly_expense_target = Decimal("0.00")

    expense_breakdown = list(
        expenses.filter(transaction_type=Expense.TransactionType.EXPENSE)
        .values("category")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )
    for row in expense_breakdown:
        if total_expenses > 0:
            row["percentage"] = (row["total"] / total_expenses) * Decimal("100")
        else:
            row["percentage"] = Decimal("0.00")

    merchant_breakdown = list(
        expenses.filter(transaction_type=Expense.TransactionType.EXPENSE)
        .values("title")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("-total")[:10]
    )

    account_breakdown = list(
        expenses.filter(transaction_type=Expense.TransactionType.EXPENSE)
        .values("account__name")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )
    for row in account_breakdown:
        row["account_name"] = row["account__name"] or "Unassigned"
        if total_expenses > 0:
            row["percentage"] = (row["total"] / total_expenses) * Decimal("100")
        else:
            row["percentage"] = Decimal("0.00")

    month_rows: list[dict[str, Decimal | str]] = []
    for month_start in _recent_month_starts(6):
        month_end = _next_month_start(month_start)
        month_qs = Expense.objects.filter(
            user=request.user,
            date__gte=month_start,
            date__lt=month_end,
        )
        if selected_account is not None:
            month_qs = month_qs.filter(account=selected_account)
        month_income = (
            month_qs.filter(transaction_type=Expense.TransactionType.INCOME).aggregate(
                total=Sum("amount")
            )["total"]
            or Decimal("0.00")
        )
        month_expense = (
            month_qs.filter(transaction_type=Expense.TransactionType.EXPENSE).aggregate(
                total=Sum("amount")
            )["total"]
            or Decimal("0.00")
        )
        month_rows.append(
            {
                "month": month_start.strftime("%b %Y"),
                "income": month_income,
                "expenses": month_expense,
                "net": month_income - month_expense,
            }
        )

    recurring_map: dict[str, dict[str, object]] = defaultdict(
        lambda: {"title": "", "months": set(), "amounts": []}
    )
    recurring_source = expenses.filter(
        transaction_type=Expense.TransactionType.EXPENSE
    ).values("title", "amount", "date")
    for row in recurring_source:
        title = row["title"]
        key = title.strip().lower()
        recurring_map[key]["title"] = title
        recurring_map[key]["months"].add(row["date"].strftime("%Y-%m"))
        recurring_map[key]["amounts"].append(row["amount"])

    recurring_expenses: list[dict[str, object]] = []
    for data in recurring_map.values():
        months = data["months"]
        amounts = data["amounts"]
        if len(months) >= 3:
            avg_amount = sum(amounts, Decimal("0.00")) / len(amounts)
            recurring_expenses.append(
                {
                    "title": data["title"],
                    "months_count": len(months),
                    "average_amount": avg_amount,
                }
            )
    recurring_expenses.sort(key=lambda item: item["average_amount"], reverse=True)

    debt_keywords = ("mortgage", "loan", "payday", "interest", "credit card")
    debt_filter = Q(
        account__account_type__in=[
            Account.AccountType.CREDIT_CARD,
            Account.AccountType.MORTGAGE,
            Account.AccountType.PAYDAY_LOAN,
        ]
    )
    for keyword in debt_keywords:
        debt_filter |= Q(category__icontains=keyword)

    debt_total = (
        expenses.filter(transaction_type=Expense.TransactionType.EXPENSE)
        .filter(debt_filter)
        .aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )

    essential_keywords = (
        "housing",
        "mortgage",
        "rent",
        "utilities",
        "insurance",
        "debt",
        "loan",
        "medical",
        "transport",
        "fuel",
        "groceries",
        "food",
    )
    essential_total = Decimal("0.00")
    discretionary_total = Decimal("0.00")
    for row in expense_breakdown:
        category_name = row["category"].lower()
        if any(keyword in category_name for keyword in essential_keywords):
            essential_total += row["total"]
        else:
            discretionary_total += row["total"]

    insights: list[str] = []
    if total_income == 0 and total_expenses > 0:
        insights.append(
            "No income has been recorded in this period. Import income transactions first to see meaningful cash-flow guidance."
        )
    if savings_rate < 0:
        insights.append(
            "You are spending more than you earn in this period. Focus on cutting the top 1-2 spending categories immediately."
        )
    elif savings_rate < 10:
        insights.append(
            "Your savings rate is below 10%. A good next target is 15-20% by reducing discretionary categories."
        )
    elif savings_rate >= 20:
        insights.append(
            "Savings rate is at or above 20%, which is a strong baseline. Prioritize high-interest debt next."
        )

    if expense_breakdown:
        top_category = expense_breakdown[0]
        if top_category["percentage"] >= 30:
            insights.append(
                f"{top_category['category']} is {top_category['percentage']:.1f}% of your spending. Start there for the biggest impact."
            )

    if total_income > 0 and debt_total > 0:
        debt_ratio = (debt_total / total_income) * Decimal("100")
        if debt_ratio >= 25:
            insights.append(
                f"Debt-related categories are {debt_ratio:.1f}% of income. Prioritize extra payments toward the highest-interest balances first."
            )
    if monthly_expense_target > 0:
        insights.append(
            f"To reach a 15% savings rate, reduce monthly spending by about ${monthly_expense_target:.2f}."
        )
    if discretionary_total > 0 and total_expenses > 0:
        discretionary_ratio = (discretionary_total / total_expenses) * Decimal("100")
        if discretionary_ratio >= 35:
            insights.append(
                f"Discretionary spending is {discretionary_ratio:.1f}% of total expenses. Start cuts there before touching essentials."
            )

    if recurring_expenses:
        recurring_names = ", ".join(item["title"] for item in recurring_expenses[:3])
        insights.append(
            f"Detected recurring expenses: {recurring_names}. Review these for renegotiation or cancellation opportunities."
        )

    if not insights:
        insights.append(
            "Your cash flow looks stable in this range. Keep importing monthly statements to improve trend accuracy."
        )

    context = {
        "period": period,
        "start_date": start_date,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_balance": net_balance,
        "savings_rate": savings_rate,
        "monthly_expense_target": monthly_expense_target,
        "essential_total": essential_total,
        "discretionary_total": discretionary_total,
        "expense_breakdown": expense_breakdown,
        "merchant_breakdown": merchant_breakdown,
        "account_breakdown": account_breakdown,
        "month_rows": month_rows,
        "recurring_expenses": recurring_expenses[:10],
        "insights": insights,
        "user_accounts": user_accounts,
        "account_filter": account_filter,
        "selected_account": selected_account,
    }
    return render(request, "tracker/reports.html", context)
