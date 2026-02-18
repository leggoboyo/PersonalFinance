import re
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from .models import Account, Expense, StatementImport
from .pdf_import import _parse_date_token


class ExpenseModelTests(TestCase):
    def test_amount_cannot_be_negative(self):
        user = User.objects.create_user(username="user1", password="pw-strong-123")
        expense = Expense(
            user=user,
            title="Invalid",
            amount=Decimal("-1.00"),
            category="Test",
            transaction_type=Expense.TransactionType.EXPENSE,
            date=date.today(),
        )
        with self.assertRaises(ValidationError):
            expense.full_clean()


class OwnershipTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(username="alice", password="pw-strong-123")
        self.user2 = User.objects.create_user(username="bob", password="pw-strong-123")
        self.account1 = Account.objects.create(user=self.user1, name="Checking A")
        self.account2 = Account.objects.create(user=self.user2, name="Checking B")
        Expense.objects.create(
            user=self.user1,
            account=self.account1,
            title="Groceries",
            amount=Decimal("50.00"),
            category="Food",
            transaction_type=Expense.TransactionType.EXPENSE,
            date=date.today(),
        )
        Expense.objects.create(
            user=self.user2,
            account=self.account2,
            title="Fuel",
            amount=Decimal("40.00"),
            category="Transport",
            transaction_type=Expense.TransactionType.EXPENSE,
            date=date.today(),
        )
        self.client = Client()

    def test_expense_list_only_shows_logged_in_users_data(self):
        self.client.login(username="alice", password="pw-strong-123")
        response = self.client.get(reverse("expense_list"))
        self.assertContains(response, "Groceries")
        self.assertNotContains(response, "Fuel")

    def test_cannot_edit_another_users_expense(self):
        self.client.login(username="alice", password="pw-strong-123")
        bobs_expense = Expense.objects.get(user=self.user2)
        response = self.client.get(reverse("expense_update", args=[bobs_expense.pk]))
        self.assertEqual(response.status_code, 404)

    def test_expense_list_filter_by_type(self):
        Expense.objects.create(
            user=self.user1,
            account=self.account1,
            title="Paycheck",
            amount=Decimal("1000.00"),
            category="Income",
            transaction_type=Expense.TransactionType.INCOME,
            date=date.today(),
        )
        self.client.login(username="alice", password="pw-strong-123")
        response = self.client.get(reverse("expense_list"), {"transaction_type": "INCOME"})
        self.assertContains(response, "Paycheck")
        self.assertNotContains(response, "Groceries")

    def test_cannot_edit_another_users_account(self):
        self.client.login(username="alice", password="pw-strong-123")
        response = self.client.get(reverse("account_update", args=[self.account2.pk]))
        self.assertEqual(response.status_code, 404)


class ReportPageTests(TestCase):
    def test_reports_requires_authentication(self):
        response = self.client.get(reverse("reports"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_analytics_requires_authentication(self):
        response = self.client.get(reverse("analytics_hub"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_visualizations_requires_authentication(self):
        response = self.client.get(reverse("visualizations"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)


class PDFDateInferenceTests(TestCase):
    def test_yearless_december_date_uses_previous_year_in_january_statement(self):
        token = re.search(
            r"\b(?P<month>\d{1,2})/(?P<day>\d{1,2})(?:/(?P<year>\d{2,4}))?\b",
            "12/31",
        )
        self.assertIsNotNone(token)
        parsed = _parse_date_token(token, reference_date=date(2026, 1, 14))
        self.assertEqual(parsed, date(2025, 12, 31))


class ImportDuplicateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="importer", password="pw-strong-123")
        self.account = Account.objects.create(user=self.user, name="Checking")
        self.client = Client()
        self.client.login(username="importer", password="pw-strong-123")

    def _csv_payload(self):
        content = (
            "date,title,amount,category,transaction_type,account\n"
            "2025-12-01,Groceries,-42.20,Food,EXPENSE,Checking\n"
        ).encode("utf-8")
        return SimpleUploadedFile("sample.csv", content, content_type="text/csv")

    def test_duplicate_csv_file_is_blocked_by_default(self):
        response1 = self.client.post(
            reverse("import_csv"),
            data={
                "account": self.account.id,
                "csv_file": self._csv_payload(),
                "has_header": "on",
            },
            follow=True,
        )
        self.assertEqual(response1.status_code, 200)
        self.assertEqual(Expense.objects.filter(user=self.user).count(), 1)
        self.assertEqual(
            StatementImport.objects.filter(
                user=self.user, status=StatementImport.Status.IMPORTED
            ).count(),
            1,
        )

        response2 = self.client.post(
            reverse("import_csv"),
            data={
                "account": self.account.id,
                "csv_file": self._csv_payload(),
                "has_header": "on",
            },
            follow=True,
        )
        self.assertEqual(response2.status_code, 200)
        self.assertContains(response2, "already imported")
        self.assertEqual(Expense.objects.filter(user=self.user).count(), 1)
        self.assertEqual(
            StatementImport.objects.filter(
                user=self.user, status=StatementImport.Status.BLOCKED_DUPLICATE
            ).count(),
            1,
        )
