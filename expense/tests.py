from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from .models import Account, Budget, Category, EntryType, LedgerEntry, Transaction, Transfer
from .services import BudgetService, DashboardService, ServiceError, TransactionService, TransferService, BulkTransactionUploadService


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
            normal_side=EntryType.DEBIT,
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

        Category.objects.create(
            name="Transfer Out",
            category_type=Category.CategoryType.TRANSFER,
            normal_side=EntryType.DEBIT,
            created_by=None,
            is_system=True,
        )
        Category.objects.create(
            name="Transfer In",
            category_type=Category.CategoryType.TRANSFER,
            normal_side=EntryType.CREDIT,
            created_by=None,
            is_system=True,
        )

    def test_budget_status_reports_spent_and_remaining(self):
        TransactionService.create_transaction(
            user=self.user,
            account=self.account,
            category=self.category,
            amount=Decimal("35.50"),
            transaction_date="2026-06-15",
        )

        status = BudgetService.get_budget_status(self.budget)

        self.assertEqual(status["spent"], Decimal("35.50"))
        self.assertEqual(status["remaining"], Decimal("64.50"))
        self.assertEqual(status["percentage_used"], 35.5)
        self.assertFalse(status["is_over_budget"])

    def test_transfer_creates_two_transactions_in_one_group(self):
        transfer_account = Account.objects.create(
            user=self.user,
            name="Savings",
            account_type=Account.AccountType.BANK,
            opening_balance=Decimal("20.00"),
            current_balance=Decimal("20.00"),
        )

        group = TransferService.create_transfer(
            user=self.user,
            from_account=self.account,
            to_account=transfer_account,
            amount=Decimal("10.00"),
            transaction_date="2026-06-15",
        )

        self.account.refresh_from_db()
        transfer_account.refresh_from_db()

        self.assertEqual(group.transfer_type, Transfer.Type.TRANSFER)
        self.assertEqual(group.transactions.count(), 2)
        self.assertEqual(self.account.current_balance, Decimal("90.00"))
        self.assertEqual(transfer_account.current_balance, Decimal("30.00"))


class TransactionUpdateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="txn-user", password="strong-pass")
        self.account = Account.objects.create(
            user=self.user,
            name="Wallet",
            account_type=Account.AccountType.WALLET,
            opening_balance=Decimal("500.00"),
            current_balance=Decimal("500.00"),
        )
        self.category = Category.objects.create(
            name="Groceries",
            category_type=Category.CategoryType.EXPENSE,
            normal_side=EntryType.DEBIT,
            created_by=self.user,
            is_system=False,
        )
        self.transaction = TransactionService.create_transaction(
            user=self.user,
            account=self.account,
            category=self.category,
            amount=Decimal("100.00"),
            transaction_date="2026-06-10",
            description="Weekly shop",
            items=[
                {
                    "name": "Milk",
                    "quantity": Decimal("2"),
                    "unit_price": Decimal("30.00"),
                    "total_price": Decimal("60.00"),
                },
                {
                    "name": "Bread",
                    "quantity": Decimal("1"),
                    "unit_price": Decimal("40.00"),
                    "total_price": Decimal("40.00"),
                },
            ],
        )

    def test_update_transaction_replaces_items_and_amount(self):
        TransactionService.update_transaction(
            transaction_obj=self.transaction,
            description="Updated shop",
            items=[
                {
                    "name": "Eggs",
                    "quantity": Decimal("1"),
                    "unit_price": Decimal("80.00"),
                    "total_price": Decimal("80.00"),
                },
            ],
        )

        self.transaction.refresh_from_db()
        self.account.refresh_from_db()
        items = list(self.transaction.items.order_by("name"))

        self.assertEqual(self.transaction.amount, Decimal("80.00"))
        self.assertEqual(self.transaction.description, "Updated shop")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].name, "Eggs")
        self.assertEqual(self.account.current_balance, Decimal("420.00"))

    def test_update_creates_reversal_ledger_entries(self):
        initial_entries = LedgerEntry.objects.filter(transaction=self.transaction).count()

        TransactionService.update_transaction(
            transaction_obj=self.transaction,
            description="Updated shop",
            items=[
                {
                    "name": "Eggs",
                    "quantity": Decimal("1"),
                    "unit_price": Decimal("80.00"),
                    "total_price": Decimal("80.00"),
                },
            ],
        )

        entries = LedgerEntry.objects.filter(transaction=self.transaction)
        self.assertEqual(entries.count(), initial_entries + 2)
        self.assertTrue(entries.filter(is_reversal=True).exists())

    def test_update_transaction_requires_at_least_one_item(self):
        with self.assertRaisesMessage(ServiceError, "At least one transaction item is required."):
            TransactionService.update_transaction(
                transaction_obj=self.transaction,
                items=[],
            )

    def test_update_rejects_immutable_fields(self):
        other_account = Account.objects.create(
            user=self.user,
            name="Other",
            account_type=Account.AccountType.CASH,
            opening_balance=Decimal("0.00"),
            current_balance=Decimal("0.00"),
        )
        with self.assertRaisesMessage(ServiceError, "Cannot update immutable fields"):
            TransactionService.update_transaction(
                transaction_obj=self.transaction,
                account=other_account,
            )

    def test_transaction_update_page_renders_existing_items(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("transaction-update", kwargs={"pk": self.transaction.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edit Transaction")
        self.assertContains(response, "Milk")

    def test_transaction_update_post_syncs_items(self):
        self.client.force_login(self.user)
        items_by_name = {item.name: item for item in self.transaction.items.all()}

        response = self.client.post(
            reverse("transaction-update", kwargs={"pk": self.transaction.pk}),
            {
                "category": str(self.category.pk),
                "merchant": "",
                "transaction_date": "2026-06-10",
                "description": "Updated via form",
                "reference_number": "",
                "tags": [],
                "items-TOTAL_FORMS": "2",
                "items-INITIAL_FORMS": "2",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-id": str(items_by_name["Milk"].pk),
                "items-0-name": "Milk",
                "items-0-quantity": "2",
                "items-0-unit_price": "30.00",
                "items-0-DELETE": "on",
                "items-1-id": str(items_by_name["Bread"].pk),
                "items-1-name": "Rice",
                "items-1-quantity": "3",
                "items-1-unit_price": "25.00",
            },
        )

        self.assertRedirects(response, reverse("transaction-list"))
        self.transaction.refresh_from_db()
        self.account.refresh_from_db()
        items = list(self.transaction.items.all())

        self.assertEqual(self.transaction.description, "Updated via form")
        self.assertEqual(self.transaction.amount, Decimal("75.00"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].name, "Rice")
        self.assertEqual(self.account.current_balance, Decimal("425.00"))


class BulkTransactionUploadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="bulk-user", password="strong-pass")
        self.account = Account.objects.create(
            user=self.user,
            name="Wallet",
            account_type=Account.AccountType.WALLET,
            opening_balance=Decimal("500.00"),
            current_balance=Decimal("500.00"),
        )

    def test_upload_rolls_back_all_rows_when_one_row_fails(self):
        csv_content = (
            "account,category,merchant,amount,transaction_date,description\n"
            "Wallet,Food,Shop One,100.00,2026-06-10,First\n"
            "Wallet,Food,Shop Two,200.00,2026-06-11,Second\n"
        ).encode("utf-8")
        upload_file = SimpleUploadedFile(
            "bulk.csv",
            csv_content,
            content_type="text/csv",
        )

        original_create_transaction = TransactionService.create_transaction
        call_count = {"value": 0}

        def create_then_fail(*args, **kwargs):
            call_count["value"] += 1
            if call_count["value"] == 1:
                return original_create_transaction(*args, **kwargs)
            raise ServiceError("forced bulk failure")

        service = BulkTransactionUploadService()

        with patch(
            "expense.services.bulk_transaction_upload.TransactionService.create_transaction",
            side_effect=create_then_fail,
        ):
            with self.assertRaisesMessage(ServiceError, "forced bulk failure"):
                service.upload(self.user, upload_file)

        self.assertEqual(Transaction.objects.count(), 0)
        self.assertEqual(LedgerEntry.objects.count(), 0)
        self.account.refresh_from_db()
        self.assertEqual(self.account.current_balance, Decimal("500.00"))


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
            normal_side=EntryType.DEBIT,
            created_by=user,
            is_system=False,
        )

        TransactionService.create_transaction(
            user=user,
            account=account,
            category=category,
            amount=Decimal("10.00"),
            transaction_date="2026-06-15",
        )

        account.current_balance = Decimal("999.00")
        account.save(update_fields=["current_balance"])

        call_command("nightly_reconcile")

        account.refresh_from_db()
        self.assertEqual(account.current_balance, Decimal("90.00"))


class CreditCardBalanceBehaviorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="cc-user", password="strong-pass")
        self.credit_card = Account.objects.create(
            user=self.user,
            name="Credit Card",
            account_type=Account.AccountType.CREDIT_CARD,
            opening_balance=Decimal("0.00"),
            current_balance=Decimal("0.00"),
        )
        self.wallet = Account.objects.create(
            user=self.user,
            name="Wallet",
            account_type=Account.AccountType.WALLET,
            opening_balance=Decimal("100.00"),
            current_balance=Decimal("100.00"),
        )
        self.expense_category = Category.objects.create(
            name="Shopping",
            category_type=Category.CategoryType.EXPENSE,
            normal_side=EntryType.DEBIT,
            created_by=self.user,
            is_system=False,
        )
        self.income_category = Category.objects.create(
            name="Refund",
            category_type=Category.CategoryType.REFUND,
            normal_side=EntryType.CREDIT,
            created_by=self.user,
            is_system=False,
        )

    def test_credit_card_debit_increases_due_and_credit_reduces_due(self):
        TransactionService.create_transaction(
            user=self.user,
            account=self.credit_card,
            category=self.expense_category,
            amount=Decimal("100.00"),
            transaction_date="2026-06-20",
        )
        self.credit_card.refresh_from_db()
        self.assertEqual(self.credit_card.current_balance, Decimal("100.00"))

        TransactionService.create_transaction(
            user=self.user,
            account=self.credit_card,
            category=self.income_category,
            amount=Decimal("40.00"),
            transaction_date="2026-06-21",
        )
        self.credit_card.refresh_from_db()
        self.assertEqual(self.credit_card.current_balance, Decimal("60.00"))

    def test_total_balance_subtracts_credit_card_due(self):
        self.credit_card.current_balance = Decimal("30.00")
        self.credit_card.save(update_fields=["current_balance"])

        total = DashboardService.total_balance(self.user)

        self.assertEqual(total, Decimal("70.00"))
