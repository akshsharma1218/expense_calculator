from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F, Sum

from expense.models import Account, LedgerEntry, Transaction


class Command(BaseCommand):
    help = "Rebuild account balances and aggregate values from ledger entries for nightly reconciliation."

    def handle(self, *args, **options):
        with transaction.atomic():
            accounts = Account.objects.only("id", "current_balance", "opening_balance")
            for account in accounts:
                ledger_total = (
                    LedgerEntry.objects.filter(account=account)
                    .aggregate(total=Sum("amount"))[
                        "total"
                    ]
                    or Decimal("0.00")
                )

                balance = account.opening_balance
                for entry in LedgerEntry.objects.filter(account=account).order_by("created_at", "id"):
                    if entry.entry_type == LedgerEntry.EntryType.CREDIT:
                        balance += entry.amount
                    else:
                        balance -= entry.amount

                Account.objects.filter(pk=account.pk).update(current_balance=balance)

            self.stdout.write(self.style.SUCCESS("Nightly reconciliation complete."))
