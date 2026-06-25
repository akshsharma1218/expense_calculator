from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from expense.models import Account, EntryType, LedgerEntry


class Command(BaseCommand):
    help = (
        "Rebuild account balances and ledger running balances "
        "from immutable ledger entries."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        accounts = {
            account.id: account
            for account in Account.objects.only(
                "id",
                "opening_balance",
                "current_balance",
            )
        }

        running_balances = {
            account_id: account.opening_balance
            for account_id, account in accounts.items()
        }

        account_updates = []
        ledger_updates = []

        ledgers = (
            LedgerEntry.objects
            .select_related("account")
            .order_by(
                "account_id",
                "created_at",
                "id",
            )
            .iterator(chunk_size=2000)
        )

        for entry in ledgers:
            balance = running_balances[entry.account_id]

            if entry.entry_type == EntryType.CREDIT:
                balance += entry.amount
            else:
                balance -= entry.amount

            running_balances[entry.account_id] = balance

            entry.running_balance = balance
            ledger_updates.append(entry)

        if ledger_updates:
            LedgerEntry.objects.bulk_update(
                ledger_updates,
                ["running_balance"],
                batch_size=1000,
            )

        for account_id, account in accounts.items():
            account.current_balance = running_balances[account_id]
            account_updates.append(account)

        if account_updates:
            Account.objects.bulk_update(
                account_updates,
                ["current_balance"],
                batch_size=500,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully reconciled "
                f"{len(account_updates)} accounts and "
                f"{len(ledger_updates)} ledger entries."
            )
        )