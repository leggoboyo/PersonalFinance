from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tracker.models import Expense


class Command(BaseCommand):
    help = (
        "Shifts clearly future transaction dates back by one year. "
        "Use --apply to persist changes."
    )

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True, help="Username to target.")
        parser.add_argument(
            "--account",
            default="",
            help="Optional account name filter (case-insensitive exact match).",
        )
        parser.add_argument(
            "--days-ahead",
            type=int,
            default=30,
            help="Only dates beyond today + this many days are considered future.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply updates. Without this flag, runs as dry-run.",
        )

    def handle(self, *args, **options):
        username = options["username"]
        account_name = options["account"].strip()
        days_ahead = options["days_ahead"]
        apply_changes = options["apply"]

        user_model = get_user_model()
        try:
            user = user_model.objects.get(username=username)
        except user_model.DoesNotExist as exc:
            raise CommandError(f"User '{username}' not found.") from exc

        today = timezone.localdate()
        threshold = today + timedelta(days=days_ahead)

        qs = Expense.objects.filter(user=user, date__gt=threshold).select_related("account")
        if account_name:
            qs = qs.filter(account__name__iexact=account_name)

        candidates = list(qs.order_by("date", "id"))
        if not candidates:
            self.stdout.write(self.style.SUCCESS("No future-dated transactions found."))
            return

        updated = []
        skipped = 0
        for expense in candidates:
            try:
                new_date = expense.date.replace(year=expense.date.year - 1)
            except ValueError:
                # Handles Feb 29 -> Feb 28 on non-leap year.
                if expense.date.month == 2 and expense.date.day == 29:
                    new_date = date(expense.date.year - 1, 2, 28)
                else:
                    skipped += 1
                    continue

            if new_date > today:
                skipped += 1
                continue

            updated.append((expense, new_date))

        self.stdout.write(
            f"Found {len(candidates)} candidate future-dated rows; "
            f"{len(updated)} would be updated, {skipped} skipped."
        )
        for expense, new_date in updated[:20]:
            account_name = expense.account.name if expense.account else "-"
            self.stdout.write(
                f"  id={expense.id} | {expense.date} -> {new_date} | "
                f"{account_name} | {expense.title}"
            )

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING("Dry-run only. Re-run with --apply to save changes.")
            )
            return

        for expense, new_date in updated:
            expense.date = new_date
            expense.save(update_fields=["date"])

        self.stdout.write(self.style.SUCCESS(f"Updated {len(updated)} transactions."))
