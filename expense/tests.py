from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .models import Account, Budget, Category, Transaction
from .services import BudgetService, TransactionService


User = get_user_model()


class BudgetServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", password="strong-pass")
        self.account = Account.objects.create(
            user=self.user,
            name="Main Wallet",
            account_type=Account.AccountType.WALLET,
            opening_balance=Decimal("100.00"),
            current_balance=Decimal("100.00"),
        )
        self.category = Category.objects.create(
            name="Food",
            category_type=Category.CategoryType.EXPENSE,
            created_by=self.user,
            is_system=False,
        )
        self.budget = Budget.objects.create(
            user=self.user,
            category=self.category,
            month=6,
            year=2026,
            amount=Decimal("100.00"),
        )

    def test_budget_status_reports_spent_and_remaining(self):
        TransactionService.create_transaction(
            user=self.user,
            account=self.account,
            category=self.category,
            amount=Decimal("35.50"),
            transaction_type=Transaction.TransactionType.EXPENSE,
            transaction_date="2026-06-15",
        )

        status = BudgetService.get_budget_status(self.budget)

        self.assertEqual(status["spent"], Decimal("35.50"))
        self.assertEqual(status["remaining"], Decimal("64.50"))
        self.assertEqual(status["percentage_used"], 35.5)
        self.assertFalse(status["is_over_budget"])

    def test_transfer_transaction_updates_both_accounts(self):
        transfer_account = Account.objects.create(
            user=self.user,
            name="Savings",
            account_type=Account.AccountType.BANK,
            opening_balance=Decimal("20.00"),
            current_balance=Decimal("20.00"),
        )

        TransactionService.create_transaction(
            user=self.user,
            account=self.account,
            transfer_account=transfer_account,
            category=self.category,
            amount=Decimal("10.00"),
            transaction_type=Transaction.TransactionType.TRANSFER,
            transaction_date="2026-06-15",
        )

        self.account.refresh_from_db()
        transfer_account.refresh_from_db()

        self.assertEqual(self.account.current_balance, Decimal("90.00"))
        self.assertEqual(transfer_account.current_balance, Decimal("30.00"))


class GroupPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="group-user", password="strong-pass")

    def test_group_list_page_renders_for_authenticated_user(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("group-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Groups")


class NightlyReconcileCommandTests(TestCase):
    def test_reconcile_command_rebuilds_account_balances_from_ledger(self):
        user = User.objects.create_user(username="reconcile-user", password="strong-pass")
        account = Account.objects.create(
            user=user,
            name="Main Wallet",
            account_type=Account.AccountType.WALLET,
            opening_balance=Decimal("100.00"),
            current_balance=Decimal("100.00"),
        )
        category = Category.objects.create(
            name="Food",
            category_type=Category.CategoryType.EXPENSE,
            created_by=user,
            is_system=False,
        )

        TransactionService.create_transaction(
            user=user,
            account=account,
            category=category,
            amount=Decimal("10.00"),
            transaction_type=Transaction.TransactionType.EXPENSE,
            transaction_date="2026-06-15",
        )

        account.current_balance = Decimal("999.00")
        account.save(update_fields=["current_balance"])

        call_command("nightly_reconcile")

        account.refresh_from_db()
        self.assertEqual(account.current_balance, Decimal("90.00"))
