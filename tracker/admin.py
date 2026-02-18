from django.contrib import admin

from .models import Account, Expense, StatementImport


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "institution", "account_type", "is_active")
    list_filter = ("account_type", "is_active")
    search_fields = ("name", "institution", "user__username")


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "user",
        "account",
        "amount",
        "category",
        "transaction_type",
        "date",
    )
    list_filter = ("transaction_type", "category", "date", "account")
    search_fields = ("title", "category", "account__name", "user__username")


@admin.register(StatementImport)
class StatementImportAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "user",
        "source_type",
        "status",
        "filename",
        "account",
        "rows_imported",
        "rows_skipped",
    )
    list_filter = ("source_type", "status", "created_at")
    search_fields = ("filename", "file_hash", "user__username", "account__name")
