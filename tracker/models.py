from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class Account(models.Model):
    class AccountType(models.TextChoices):
        CHECKING = "CHECKING", "Checking"
        CREDIT_CARD = "CREDIT_CARD", "Credit Card"
        MORTGAGE = "MORTGAGE", "Mortgage"
        PAYDAY_LOAN = "PAYDAY_LOAN", "Payday Loan"
        SAVINGS = "SAVINGS", "Savings"
        OTHER = "OTHER", "Other"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="accounts")
    name = models.CharField(max_length=150)
    institution = models.CharField(max_length=150, blank=True)
    account_type = models.CharField(
        max_length=20,
        choices=AccountType.choices,
        default=AccountType.CHECKING,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        unique_together = ("user", "name")

    def __str__(self) -> str:
        if self.institution:
            return f"{self.name} ({self.institution})"
        return self.name


class StatementImport(models.Model):
    class SourceType(models.TextChoices):
        PDF = "PDF", "PDF"
        CSV = "CSV", "CSV"

    class Status(models.TextChoices):
        IMPORTED = "IMPORTED", "Imported"
        BLOCKED_DUPLICATE = "BLOCKED_DUPLICATE", "Blocked duplicate"

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="statement_imports"
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="statement_imports",
    )
    source_type = models.CharField(max_length=10, choices=SourceType.choices)
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.IMPORTED,
    )
    filename = models.CharField(max_length=255)
    file_hash = models.CharField(max_length=64, db_index=True)
    statement_date = models.DateField(null=True, blank=True)
    rows_detected = models.PositiveIntegerField(default=0)
    rows_imported = models.PositiveIntegerField(default=0)
    rows_skipped = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.source_type} {self.filename} ({self.get_status_display()})"


class Expense(models.Model):
    class TransactionType(models.TextChoices):
        INCOME = "INCOME", "Income"
        EXPENSE = "EXPENSE", "Expense"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="expenses")
    account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expenses",
    )
    title = models.CharField(max_length=255)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    category = models.CharField(max_length=100)
    transaction_type = models.CharField(
        max_length=10,
        choices=TransactionType.choices,
        default=TransactionType.EXPENSE,
    )
    date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def clean(self) -> None:
        super().clean()
        if self.amount < 0:
            raise ValidationError({"amount": "Amount cannot be negative."})

    def __str__(self) -> str:
        return f"{self.title} ({self.transaction_type}) - {self.amount}"
