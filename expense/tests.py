import csv
import json
from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from .forms import FavoriteDescriptionForm, QuickTransactionForm, TransactionForm
from .models import Account, Budget, Category, EntryType, ExpenseGroup, FavoriteDescription, GroupBalance, GroupExpenseSplit, GroupInvitation, GroupMember, Merchant, Transaction, Transfer
from .services import BudgetService, DashboardService, GroupService, ServiceError, SettlementService, TransactionService, TransferService, BulkTransactionUploadService


User = get_user_model()


class DashboardQuickEntryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="quick-entry@example.com",
            username="quick-entry-user",
            password="strong-pass",
        )
        self.client.force_login(self.user)
        self.account = Account.objects.create(
            user=self.user,
            name="Everyday",
            account_type=Account.AccountType.WALLET,
            opening_balance=Decimal("100.00"),
            current_balance=Decimal("100.00"),
        )
        self.category = Category.objects.create(
            name="Food",
            category_type=Category.CategoryType.EXPENSE,
            normal_side=EntryType.DEBIT,
            created_by=self.user,
        )
        self.merchant = Merchant.objects.create(name="Cafe", created_by=self.user)
        self.favorite = FavoriteDescription.objects.create(
            user=self.user,
            name="Lunch",
            account=self.account,
            category=self.category,
            merchant=self.merchant,
        )

    def test_quick_add_uses_favorite_preset_resources(self):
        response = self.client.post(
            reverse("dashboard"),
            {
                "action": "quick_add",
                "favorite": str(self.favorite.pk),
                "amount": "12.50",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        transaction = Transaction.objects.get(user=self.user)
        self.assertEqual(transaction.account, self.account)
        self.assertEqual(transaction.category, self.category)
        self.assertEqual(transaction.merchant, self.merchant)
        self.assertEqual(transaction.amount, Decimal("12.50"))
        self.assertEqual(transaction.description, self.favorite.name)
        self.assertEqual(transaction.transaction_date, timezone.localdate())
        self.account.refresh_from_db()
        self.assertEqual(self.account.current_balance, Decimal("87.50"))
        self.assertNotIn("account", QuickTransactionForm(user=self.user).fields)
        self.assertNotIn("description", QuickTransactionForm(user=self.user).fields)

    def test_quick_add_accepts_negative_amount_without_refund_field(self):
        favorite = FavoriteDescription.objects.create(
            user=self.user,
            name="Returned lunch",
            account=self.account,
            category=self.category,
        )
        response = self.client.post(
            reverse("dashboard"),
            {
                "action": "quick_add",
                "favorite": str(favorite.pk),
                "amount": "-12.50",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        transaction = Transaction.objects.get(user=self.user, description="Returned lunch")
        self.assertEqual(transaction.amount, Decimal("12.50"))
        self.assertEqual(transaction.entry_type, EntryType.CREDIT)
        self.assertNotIn("refund", TransactionForm(user=self.user).fields)

    def test_transaction_create_accepts_negative_amount(self):
        response = self.client.post(
            reverse("transaction-create"),
            {
                "amount": "-19.75",
                "description": "Returned item",
                "account": str(self.account.pk),
                "category": str(self.category.pk),
                "transaction_date": "2026-10-01",
            },
        )

        self.assertRedirects(response, reverse("transaction-list"))
        transaction = Transaction.objects.get(user=self.user, description="Returned item")
        self.assertEqual(transaction.amount, Decimal("19.75"))
        self.assertEqual(transaction.entry_type, EntryType.CREDIT)

    def test_favorites_support_create_update_and_delete(self):
        create_response = self.client.post(
            reverse("favorite-list"),
            {
                "action": "create",
                "name": "Coffee",
            },
        )
        self.assertRedirects(create_response, reverse("favorite-list"))
        favorite = FavoriteDescription.objects.get(user=self.user)

        update_response = self.client.post(
            reverse("favorite-list"),
            {
                "action": "update",
                "favorite_id": str(favorite.id),
                f"{favorite.id}-name": "Morning coffee",
                f"{favorite.id}-account": str(self.account.pk),
                f"{favorite.id}-category": str(self.category.pk),
                f"{favorite.id}-merchant": "",
            },
        )
        self.assertRedirects(update_response, reverse("favorite-list"))
        favorite.refresh_from_db()
        self.assertEqual(favorite.name, "Morning coffee")
        self.assertEqual(favorite.account, self.account)
        self.assertEqual(favorite.category, self.category)
        self.assertContains(self.client.get(reverse("favorite-list")), "Morning coffee")

        delete_response = self.client.post(
            reverse("favorite-list"),
            {
                "action": "delete",
                "favorite_id": str(favorite.id),
            },
        )
        self.assertRedirects(delete_response, reverse("favorite-list"))
        self.assertFalse(FavoriteDescription.objects.filter(pk=favorite.pk).exists())

    def test_favorite_page_exposes_transaction_use_link(self):
        FavoriteDescription.objects.create(
            user=self.user,
            name="Coffee",
        )

        response = self.client.get(reverse("favorite-list"))

        self.assertContains(response, f"transaction-create?favorite={response.context['favorite_rows'][0]['favorite'].pk}")

    def test_favorite_reuses_saved_transaction_fields(self):
        favorite = FavoriteDescription.objects.create(
            user=self.user,
            name="Coffee",
            account=self.account,
            category=self.category,
        )
        response = self.client.get(reverse("transaction-create"), {"favorite": str(favorite.pk)})

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form.initial["description"], favorite.name)
        self.assertEqual(form.initial["account"], self.account.pk)
        self.assertEqual(form.initial["category"], self.category.pk)
        self.assertEqual(form.initial["transaction_date"], timezone.localdate())
        self.assertNotIn("transaction_date", FavoriteDescriptionForm().fields)
        self.assertNotIn("tags", form.fields)

    def test_dashboard_does_not_render_favorite_management(self):
        FavoriteDescription.objects.create(
            user=self.user,
            name="Coffee",
        )

        response = self.client.get(reverse("dashboard"))

        self.assertNotContains(response, "Favorite descriptions")
        self.assertContains(response, reverse("favorite-list"))

    def test_favorite_update_cannot_modify_another_users_favorite(self):
        other_user = User.objects.create_user(
            email="another-user@example.com",
            username="another-user",
            password="strong-pass",
        )
        favorite = FavoriteDescription.objects.create(
            user=other_user,
            name="Private",
        )

        response = self.client.post(
            reverse("favorite-list"),
            {
                "action": "delete",
                "favorite_id": str(favorite.id),
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(FavoriteDescription.objects.filter(pk=favorite.pk).exists())

    def test_account_csv_import_and_templates(self):
        upload = SimpleUploadedFile(
            "accounts.csv",
            b"name,account_type,opening_balance\nSavings,bank,250.00\n",
            content_type="text/csv",
        )
        response = self.client.post(reverse("account-upload"), {"csv_file": upload})

        self.assertRedirects(response, reverse("account-list"))
        imported_account = Account.objects.get(user=self.user, name="Savings")
        self.assertEqual(imported_account.account_type, Account.AccountType.BANK)
        self.assertEqual(imported_account.current_balance, Decimal("250.00"))

        account_template = self.client.get(reverse("account-template"))
        transaction_template = self.client.get(reverse("transaction-template"))
        self.assertContains(account_template, "name,account_type,opening_balance")
        self.assertContains(transaction_template, "account,category,category_type,category_normal_side")
        self.assertContains(transaction_template, "merchant,amount,transaction_date,description")

    def test_account_csv_import_is_all_or_nothing_for_duplicates(self):
        upload = SimpleUploadedFile(
            "accounts.csv",
            b"name,account_type,opening_balance\nSavings,bank,250.00\nEveryday,cash,5.00\n",
            content_type="text/csv",
        )

        self.client.post(reverse("account-upload"), {"csv_file": upload})

        self.assertFalse(Account.objects.filter(user=self.user, name="Savings").exists())

    def test_login_lands_on_favorites_when_user_has_favorites(self):
        FavoriteDescription.objects.create(
            user=self.user,
            name="Coffee",
        )
        self.client.logout()

        response = self.client.post(
            reverse("users:login"),
            {"email": self.user.email, "password": "strong-pass"},
        )

        self.assertRedirects(response, reverse("favorite-list"))

    def test_login_uses_valid_next_destination_before_favorites(self):
        FavoriteDescription.objects.create(
            user=self.user,
            name="Coffee",
        )
        self.client.logout()

        response = self.client.post(
            reverse("users:login"),
            {
                "email": self.user.email,
                "password": "strong-pass",
                "next": reverse("account-list"),
            },
        )

        self.assertRedirects(response, reverse("account-list"))


class TransactionAccountGateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="no-account@example.com",
            username="no-account",
            password="strong-pass",
        )
        self.client.force_login(self.user)

    def test_transaction_fields_are_hidden_without_an_active_account(self):
        response = self.client.get(reverse("transaction-create"))

        self.assertContains(response, "No active account")
        self.assertContains(response, reverse("account-create"))
        self.assertNotContains(response, 'id="id_amount"')
        self.assertNotContains(response, 'id="id_category"')

    def test_direct_transaction_post_is_rejected_without_an_account(self):
        category = Category.objects.create(
            name="Food",
            category_type=Category.CategoryType.EXPENSE,
            normal_side=EntryType.DEBIT,
            created_by=self.user,
        )
        response = self.client.post(
            reverse("transaction-create"),
            {
                "amount": "25.00",
                "description": "Lunch",
                "account": "",
                "category": str(category.pk),
                "transaction_date": "2026-10-01",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create an account before adding a transaction.")
        self.assertFalse(Transaction.objects.filter(user=self.user).exists())


class AuthenticationLandingTests(TestCase):
    def test_login_without_favorites_lands_on_dashboard(self):
        user = User.objects.create_user(
            email="new-user@example.com",
            username="new-user",
            password="strong-pass",
        )

        response = self.client.post(
            reverse("users:login"),
            {"email": user.email, "password": "strong-pass"},
        )

        self.assertRedirects(response, reverse("dashboard"))


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


class TransferUpdateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="transfer-editor@example.com",
            username="transfer-editor",
            password="strong-pass",
        )
        self.source = Account.objects.create(
            user=self.user,
            name="Everyday",
            account_type=Account.AccountType.WALLET,
            opening_balance=Decimal("100.00"),
            current_balance=Decimal("100.00"),
        )
        self.destination = Account.objects.create(
            user=self.user,
            name="Savings",
            account_type=Account.AccountType.BANK,
            opening_balance=Decimal("20.00"),
            current_balance=Decimal("20.00"),
        )
        self.investment = Account.objects.create(
            user=self.user,
            name="Investments",
            account_type=Account.AccountType.INVESTMENT,
            opening_balance=Decimal("200.00"),
            current_balance=Decimal("200.00"),
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
        self.transfer = TransferService.create_transfer(
            user=self.user,
            from_account=self.source,
            to_account=self.destination,
            amount=Decimal("10.00"),
            transaction_date="2026-06-15",
            notes="Original transfer",
        )

    def test_edit_page_renders_existing_transfer_details(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("transfer-update", kwargs={"pk": self.transfer.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edit Transfer")
        self.assertContains(response, "Original transfer")
        self.assertContains(response, 'value="2026-06-15"')

    def test_update_changes_accounts_and_keeps_investment_type(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("transfer-update", kwargs={"pk": self.transfer.pk}),
            {
                "from_account": str(self.investment.pk),
                "to_account": str(self.destination.pk),
                "amount": "15.00",
                "transaction_date": "2026-07-01",
                "notes": "Updated investment transfer",
            },
        )

        self.assertRedirects(response, reverse("transfer-list"))
        self.transfer.refresh_from_db()
        self.source.refresh_from_db()
        self.destination.refresh_from_db()
        self.investment.refresh_from_db()

        self.assertEqual(self.transfer.from_account, self.investment)
        self.assertEqual(self.transfer.to_account, self.destination)
        self.assertEqual(self.transfer.amount, Decimal("15.00"))
        self.assertEqual(self.transfer.transaction_date.isoformat(), "2026-07-01")
        self.assertEqual(self.transfer.notes, "Updated investment transfer")
        self.assertEqual(self.transfer.transfer_type, Transfer.Type.INVESTMENT)
        self.assertEqual(self.source.current_balance, Decimal("100.00"))
        self.assertEqual(self.destination.current_balance, Decimal("35.00"))
        self.assertEqual(self.investment.current_balance, Decimal("185.00"))


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

    def test_update_transaction_requires_at_least_one_item(self):
        with self.assertRaisesMessage(ServiceError, "At least one transaction item is required."):
            TransactionService.update_transaction(
                transaction_obj=self.transaction,
                items=[],
            )

    def test_delete_transaction_reverses_account_balance(self):
        TransactionService.delete_transaction(self.transaction)

        self.transaction.refresh_from_db()
        self.account.refresh_from_db()
        self.assertTrue(self.transaction.is_deleted)
        self.assertEqual(self.account.current_balance, Decimal("500.00"))

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

    def test_transaction_update_page_hides_item_breakdown(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("transaction-update", kwargs={"pk": self.transaction.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edit Transaction")
        self.assertNotContains(response, "Item breakdown")
        self.assertNotContains(response, "Milk")

    def test_transaction_update_without_item_form_preserves_existing_items(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("transaction-update", kwargs={"pk": self.transaction.pk}),
            {
                "category": str(self.category.pk),
                "merchant": "",
                "transaction_date": "2026-06-10",
                "description": "Updated via form",
                "amount": "75.00",
                "account": str(self.account.pk),
            },
        )

        self.assertRedirects(response, reverse("transaction-list"))
        self.transaction.refresh_from_db()
        self.account.refresh_from_db()
        items = list(self.transaction.items.all())

        self.assertEqual(self.transaction.description, "Updated via form")
        self.assertEqual(self.transaction.amount, Decimal("75.00"))
        self.assertEqual({item.name for item in items}, {"Milk", "Bread"})
        self.assertEqual(self.account.current_balance, Decimal("425.00"))


class GroupSplitSettlementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="payer", password="strong-pass")
        self.debtor = User.objects.create_user(username="debtor", password="strong-pass")
        self.group = GroupService.create_group(name="Trip", created_by=self.user)
        GroupMember.objects.create(group=self.group, user=self.debtor)

    def test_settlement_rejects_amount_above_outstanding_balance(self):
        GroupBalance.objects.create(
            group=self.group,
            from_user=self.debtor,
            to_user=self.user,
            balance_amount=Decimal("50.00"),
        )

        with self.assertRaisesMessage(ServiceError, "Settlement amount exceeds the outstanding balance."):
            SettlementService.settle(
                group=self.group,
                payer=self.debtor,
                receiver=self.user,
                amount=Decimal("75.00"),
                notes="too much",
            )

    def test_settlement_exact_amount_clears_balance(self):
        GroupBalance.objects.create(
            group=self.group,
            from_user=self.debtor,
            to_user=self.user,
            balance_amount=Decimal("60.00"),
        )

        settlement = SettlementService.settle(
            group=self.group,
            payer=self.debtor,
            receiver=self.user,
            amount=Decimal("60.00"),
            notes="settled",
        )

        self.assertEqual(settlement.amount, Decimal("60.00"))
        self.assertFalse(GroupBalance.objects.filter(group=self.group, from_user=self.debtor, to_user=self.user).exists())

    def test_equal_group_split_updates_balances(self):
        other_user = User.objects.create_user(username="friend", password="strong-pass")
        GroupMember.objects.create(group=self.group, user=other_user)

        transaction = Transaction.objects.create(
            user=self.user,
            account=Account.objects.create(
                user=self.user,
                name="Cash",
                account_type=Account.AccountType.CASH,
                opening_balance=Decimal("200.00"),
                current_balance=Decimal("200.00"),
            ),
            category=Category.objects.create(
                name="Trip",
                category_type=Category.CategoryType.EXPENSE,
                normal_side=EntryType.DEBIT,
                created_by=self.user,
                is_system=False,
            ),
            amount=Decimal("120.00"),
            entry_type=EntryType.DEBIT,
            transaction_date="2026-06-15",
            description="Shared lunch",
        )

        GroupService.create_equal_split_expense(
            group=self.group,
            paid_by=self.user,
            transaction_obj=transaction,
            members=[self.user, self.debtor, other_user],
        )

        self.assertEqual(
            GroupBalance.objects.get(group=self.group, from_user=self.debtor, to_user=self.user).balance_amount,
            Decimal("40.00"),
        )
        self.assertEqual(
            GroupBalance.objects.get(group=self.group, from_user=other_user, to_user=self.user).balance_amount,
            Decimal("40.00"),
        )


class TransactionSplitFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="split-owner@example.com",
            username="split-owner",
            password="strong-pass",
        )
        self.friend = User.objects.create_user(
            email="split-friend@example.com",
            username="split-friend",
            password="strong-pass",
        )
        self.group = GroupService.create_group(name="Weekend trip", created_by=self.user)
        GroupMember.objects.create(group=self.group, user=self.friend)
        self.account = Account.objects.create(
            user=self.user,
            name="Everyday",
            account_type=Account.AccountType.WALLET,
            opening_balance=Decimal("200.00"),
            current_balance=Decimal("200.00"),
        )
        self.category = Category.objects.create(
            name="Travel",
            category_type=Category.CategoryType.EXPENSE,
            normal_side=EntryType.DEBIT,
            created_by=self.user,
        )

    def test_transaction_service_creates_equal_split_for_group_members(self):
        transaction = TransactionService.create_transaction(
            user=self.user,
            account=self.account,
            category=self.category,
            amount=Decimal("80.00"),
            transaction_date="2026-09-30",
            description="Taxi",
        )
        GroupService.split_existing_transaction(
            transaction_obj=transaction,
            group=self.group,
            split_mode="equal",
            paid_by=self.user,
        )

        shares = list(GroupExpenseSplit.objects.filter(expense__transaction=transaction))
        self.assertEqual(len(shares), 2)
        self.assertEqual({share.share_amount for share in shares}, {Decimal("40.00")})
        self.assertEqual(
            GroupBalance.objects.get(group=self.group, from_user=self.friend, to_user=self.user).balance_amount,
            Decimal("40.00"),
        )

    def test_transaction_service_creates_custom_split_from_member_ids(self):
        transaction = TransactionService.create_transaction(
            user=self.user,
            account=self.account,
            category=self.category,
            amount=Decimal("80.00"),
            transaction_date="2026-09-30",
            description="Dinner",
        )
        GroupService.split_existing_transaction(
            transaction_obj=transaction,
            group=self.group,
            split_mode="custom",
            paid_by=self.user,
            splits=[
                {"user": self.user, "amount": "30.00"},
                {"user": self.friend, "amount": "50.00"},
            ],
        )

        shares = {
            share.user_id: share.share_amount
            for share in GroupExpenseSplit.objects.filter(expense__transaction=transaction)
        }
        self.assertEqual(shares, {
            self.user.id: Decimal("30.00"),
            self.friend.id: Decimal("50.00"),
        })
        self.assertEqual(
            GroupBalance.objects.get(group=self.group, from_user=self.friend, to_user=self.user).balance_amount,
            Decimal("50.00"),
        )

    def test_custom_split_api_creates_shares_after_transaction_exists(self):
        transaction = TransactionService.create_transaction(
            user=self.user,
            account=self.account,
            category=self.category,
            amount=Decimal("80.00"),
            transaction_date="2026-09-30",
            description="Dinner",
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("transaction-split-api", args=[transaction.pk]),
            data=json.dumps({
                "group_id": str(self.group.pk),
                "paid_by_id": self.user.pk,
                "split_mode": "custom",
                "splits": [
                    {"user_id": self.user.pk, "amount": "30.00"},
                    {"user_id": self.friend.pk, "amount": "50.00"},
                ],
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(GroupExpenseSplit.objects.filter(expense__transaction=transaction).count(), 2)
        transaction.refresh_from_db()
        self.assertTrue(transaction.is_group_expense)

    def test_custom_split_api_rejects_shares_that_do_not_match_total(self):
        transaction = TransactionService.create_transaction(
            user=self.user,
            account=self.account,
            category=self.category,
            amount=Decimal("80.00"),
            transaction_date="2026-09-30",
            description="Dinner",
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("transaction-split-api", args=[transaction.pk]),
            data=json.dumps({
                "group_id": str(self.group.pk),
                "paid_by_id": self.user.pk,
                "split_mode": "custom",
                "splits": [
                    {"user_id": self.user.pk, "amount": "30.00"},
                    {"user_id": self.friend.pk, "amount": "40.00"},
                ],
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(GroupExpenseSplit.objects.filter(expense__transaction=transaction).exists())

    def test_transaction_form_does_not_prompt_for_a_split(self):
        form = TransactionForm(user=self.user)
        self.assertNotIn("split_mode", form.fields)
        self.assertNotIn("group", form.fields)


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
        self.account.refresh_from_db()
        self.assertEqual(self.account.current_balance, Decimal("500.00"))

    def test_upload_preserves_negative_amount_direction(self):
        category = Category.objects.create(
            name="Food",
            category_type=Category.CategoryType.EXPENSE,
            normal_side=EntryType.DEBIT,
            created_by=self.user,
        )
        csv_content = (
            "account,category,category_type,category_normal_side,merchant,amount,transaction_date,description\n"
            "Wallet,Food,expense,debit,,-12.50,7/25/2026,Returned purchase\n"
            "Wallet,Salary,income,credit,,-250.00,7/26/2026,Salary correction\n"
        ).encode("utf-8")
        upload_file = SimpleUploadedFile("transactions.csv", csv_content, content_type="text/csv")

        BulkTransactionUploadService().upload(self.user, upload_file)

        transaction = Transaction.objects.get(user=self.user, description="Returned purchase")
        self.assertEqual(transaction.amount, Decimal("12.50"))
        self.assertEqual(transaction.entry_type, EntryType.CREDIT)
        self.assertEqual(transaction.transaction_date, date(2026, 7, 25))
        imported_salary = Transaction.objects.get(user=self.user, description="Salary correction")
        self.assertEqual(imported_salary.category.category_type, Category.CategoryType.INCOME)
        self.assertEqual(imported_salary.entry_type, EntryType.DEBIT)

    def test_export_sign_matches_category_normal_side(self):
        self.client.force_login(self.user)
        category = Category.objects.create(
            name="Salary",
            category_type=Category.CategoryType.INCOME,
            normal_side=EntryType.CREDIT,
            created_by=self.user,
        )
        transaction = TransactionService.create_transaction(
            user=self.user,
            account=self.account,
            category=category,
            amount=Decimal("1250.00"),
            transaction_date="2026-06-10",
            description="Payday",
        )

        response = self.client.get(reverse("transaction-export"))
        rows = list(csv.DictReader(response.content.decode("utf-8").splitlines()))

        self.assertEqual(rows[0]["amount"], "1250.00")
        self.assertEqual(rows[0]["category_type"], Category.CategoryType.INCOME)
        self.assertEqual(rows[0]["category_normal_side"], EntryType.CREDIT)
        self.assertEqual(rows[0]["transaction_date"], "6/10/2026")
        self.assertNotIn("tags", rows[0])

    def test_csv_date_parser_accepts_unpadded_month_day_year_and_iso(self):
        self.assertEqual(
            BulkTransactionUploadService._parse_transaction_date("7/25/2026"),
            date(2026, 7, 25),
        )
        self.assertEqual(
            BulkTransactionUploadService._parse_transaction_date("2026-07-25"),
            date(2026, 7, 25),
        )


class GroupPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="group-user", password="strong-pass")

    def test_group_list_page_renders_for_authenticated_user(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("group-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Groups")

    def test_group_member_can_invite_user_from_group_detail(self):
        self.client.force_login(self.user)
        group = GroupService.create_group(name="Weekend trip", created_by=self.user)
        invitee = User.objects.create_user(
            email="invitee@example.com",
            username="invitee",
            password="strong-pass",
        )

        response = self.client.post(
            reverse("group-detail", kwargs={"pk": group.pk}),
            {"email": invitee.email},
        )

        self.assertRedirects(response, reverse("group-detail", kwargs={"pk": group.pk}))
        invitation = GroupInvitation.objects.get(group=group, invited_user=invitee)
        self.assertEqual(invitation.status, GroupInvitation.Status.PENDING)
        self.assertContains(self.client.get(reverse("group-detail", kwargs={"pk": group.pk})), "Invite a member")

    def test_non_member_cannot_access_group_detail(self):
        self.client.force_login(self.user)
        creator = User.objects.create_user(username="group-creator", password="strong-pass")
        group = GroupService.create_group(name="Private group", created_by=creator)

        response = self.client.get(reverse("group-detail", kwargs={"pk": group.pk}))

        self.assertEqual(response.status_code, 404)


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
