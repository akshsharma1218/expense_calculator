import csv
import json
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from .forms import BudgetForm, FavoriteDescriptionForm, QuickTransactionForm, TransactionForm
from .models import Account, Budget, Category, EntryType, ExpenseGroup, FavoriteDescription, GroupBalance, GroupExpense, GroupExpenseSplit, GroupInvitation, GroupMember, Merchant, Settlement, SettlementAllocation, Transaction, Transfer, UserNotification
from .services import BudgetService, DashboardService, GroupInvitationService, GroupService, ServiceError, SettlementService, TransactionService, TransferService, BulkTransactionUploadService


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

    def test_non_staff_dashboard_shows_transaction_creation_without_import_tools(self):
        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "Add Transaction")
        self.assertNotContains(response, "Import / Export")
        self.assertNotContains(response, "TransactionUploadModal")
        self.assertNotContains(response, "DownloadTransactionsModal")

    def test_dashboard_timeline_groups_debit_expenses_by_category(self):
        today = date.today()
        second_category = Category.objects.create(
            name="Transport",
            category_type=Category.CategoryType.EXPENSE,
            normal_side=EntryType.DEBIT,
            created_by=self.user,
        )
        TransactionService.create_transaction(
            user=self.user,
            account=self.account,
            category=self.category,
            amount=Decimal("12.00"),
            transaction_date=today,
            description="Lunch",
        )
        TransactionService.create_transaction(
            user=self.user,
            account=self.account,
            category=second_category,
            amount=Decimal("8.00"),
            transaction_date=today,
            description="Bus",
        )
        transfer_category = Category.objects.create(
            name="Transfer Out",
            category_type=Category.CategoryType.TRANSFER,
            normal_side=EntryType.DEBIT,
            is_system=True,
        )
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=transfer_category,
            amount=Decimal("90.00"),
            entry_type=EntryType.DEBIT,
            transaction_date=today,
            description="Transfer",
        )

        timeline = DashboardService.timeline_breakdown(user=self.user, months=6)

        self.assertEqual(
            {category["name"] for category in timeline["categories"]},
            {"Food", "Transport"},
        )
        current_month = timeline["points"][-1]
        category_ids = {category["name"]: category["id"] for category in timeline["categories"]}
        self.assertEqual(current_month["values"][category_ids["Food"]], 12.0)
        self.assertEqual(current_month["values"][category_ids["Transport"]], 8.0)

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
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
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
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
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


class DashboardSetupPathTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="setup-path@example.com",
            username="setup-path",
            password="strong-pass",
        )
        self.client.force_login(self.user)

    def current_step(self, response):
        return next(
            step["key"]
            for step in response.context["setup_steps"]
            if step["current"]
        )

    def test_dashboard_setup_path_advances_through_required_records(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(self.current_step(response), "account")
        self.assertContains(response, 'href="/accounts/create/"')
        self.assertNotContains(response, 'href="/transactions/create/"')
        self.assertNotContains(response, 'id="quick-entry"')

        account = Account.objects.create(
            user=self.user,
            name="Setup wallet",
            account_type=Account.AccountType.WALLET,
        )
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(self.current_step(response), "category")

        category = Category.objects.create(
            name="Setup expenses",
            category_type=Category.CategoryType.EXPENSE,
            normal_side=EntryType.DEBIT,
            created_by=self.user,
        )
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(self.current_step(response), "budget")

        today = timezone.localdate()
        Budget.objects.create(
            user=self.user,
            category=None,
            description="Monthly setup",
            month=today.month,
            year=today.year,
            amount=Decimal("300.00"),
        )
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(self.current_step(response), "transaction")

        TransactionService.create_transaction(
            user=self.user,
            account=account,
            category=category,
            amount=Decimal("10.00"),
            transaction_date=today,
            description="First purchase",
        )
        response = self.client.get(reverse("dashboard"))
        self.assertTrue(response.context["setup_complete"])
        self.assertNotContains(response, "setupPathTitle")


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

    def test_overall_budget_counts_non_transfer_debits(self):
        today = timezone.localdate()
        budget = Budget.objects.create(
            user=self.user,
            category=None,
            description="Monthly household",
            month=today.month,
            year=today.year,
            amount=Decimal("100.00"),
        )
        TransactionService.create_transaction(
            user=self.user,
            account=self.account,
            category=self.category,
            amount=Decimal("25.00"),
            transaction_date=today,
            description="Groceries",
        )
        transfer_category = Category.objects.get(name="Transfer Out")
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=transfer_category,
            amount=Decimal("10.00"),
            entry_type=EntryType.DEBIT,
            transaction_date=today,
            description="Move money",
        )

        status = BudgetService.get_budget_status(budget)

        self.assertEqual(status["spent"], Decimal("25.00"))
        self.assertEqual(status["remaining"], Decimal("75.00"))

    def test_budget_form_only_exposes_amount_and_description(self):
        form = BudgetForm(user=self.user)

        self.assertEqual(set(form.fields), {"amount", "description"})

    def test_budget_create_uses_current_period_and_rejects_duplicate(self):
        self.client.force_login(self.user)
        today = timezone.localdate()

        response = self.client.post(
            reverse("budget-create"),
            {"amount": "150.00", "description": "Household spending"},
        )

        self.assertRedirects(response, reverse("budget-list"))
        budget = Budget.objects.get(user=self.user, category__isnull=True)
        self.assertEqual((budget.month, budget.year), (today.month, today.year))
        self.assertEqual(budget.description, "Household spending")

        response = self.client.post(
            reverse("budget-create"),
            {"amount": "175.00", "description": "Second overall budget"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Budget.objects.filter(user=self.user, category__isnull=True).count(), 1)
        self.assertContains(response, "An overall budget already exists for this month.")

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

    def test_transfer_transactions_can_only_be_edited_from_transfer_page(self):
        self.client.force_login(self.user)

        for linked_transaction in (
            self.transfer.debit_transaction,
            self.transfer.credit_transaction,
        ):
            with self.subTest(transaction=linked_transaction.pk):
                for method in (self.client.get, self.client.post):
                    response = method(
                        reverse("transaction-update", kwargs={"pk": linked_transaction.pk})
                    )

                    self.assertRedirects(
                        response,
                        reverse("transfer-update", kwargs={"pk": self.transfer.pk}),
                    )

    def test_transfer_transactions_cannot_be_changed_individually_by_service(self):
        debit_transaction = self.transfer.debit_transaction

        with self.assertRaisesMessage(ServiceError, "only be updated from the transfer page"):
            TransactionService.update_transaction(
                transaction_obj=debit_transaction,
                description="One-sided edit",
            )
        with self.assertRaisesMessage(ServiceError, "only be deleted from the transfer page"):
            TransactionService.delete_transaction(debit_transaction)

        debit_transaction.refresh_from_db()
        self.assertEqual(debit_transaction.description, "Original transfer")
        self.assertFalse(debit_transaction.is_deleted)

    def test_transfer_service_rejects_non_positive_or_non_finite_amount(self):
        for amount in (Decimal("0.00"), Decimal("NaN")):
            with self.subTest(amount=amount):
                with self.assertRaisesMessage(ServiceError, "valid positive number"):
                    TransferService.update_transfer(
                        transfer=self.transfer,
                        from_account=self.source,
                        to_account=self.destination,
                        amount=amount,
                        transaction_date="2026-06-15",
                    )

        self.source.refresh_from_db()
        self.destination.refresh_from_db()
        self.assertEqual(self.source.current_balance, Decimal("90.00"))
        self.assertEqual(self.destination.current_balance, Decimal("30.00"))

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

    def test_update_rejects_zero_and_non_finite_amounts(self):
        for amount, message in (
            (Decimal("0.00"), "greater than zero"),
            (Decimal("NaN"), "finite number"),
        ):
            with self.subTest(amount=amount):
                with self.assertRaisesMessage(ServiceError, message):
                    TransactionService.update_transaction(
                        transaction_obj=self.transaction,
                        amount=amount,
                    )

        self.account.refresh_from_db()
        self.assertEqual(self.account.current_balance, Decimal("400.00"))

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

    def test_transaction_list_applies_chart_drill_through_filters(self):
        self.client.force_login(self.user)
        other_category = Category.objects.create(
            name="Transport",
            category_type=Category.CategoryType.EXPENSE,
            normal_side=EntryType.DEBIT,
            created_by=self.user,
        )
        TransactionService.create_transaction(
            user=self.user,
            account=self.account,
            category=other_category,
            amount=Decimal("20.00"),
            transaction_date="2026-06-10",
            description="Bus fare",
        )

        response = self.client.get(
            reverse("transaction-list"),
            {
                "month": "2026-06",
                "kind": "expense",
                "category_id": str(self.category.pk),
            },
        )

        self.assertEqual(response.status_code, 200)
        rows = json.loads(response.context["transactions_json"])
        self.assertEqual([row["id"] for row in rows], [str(self.transaction.pk)])

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

    def create_due_split(self):
        account = Account.objects.create(
            user=self.user,
            name="Shared expenses",
            account_type=Account.AccountType.CASH,
            opening_balance=Decimal("120.00"),
            current_balance=Decimal("120.00"),
        )
        category = Category.objects.create(
            name="Shared trip",
            category_type=Category.CategoryType.EXPENSE,
            normal_side=EntryType.DEBIT,
            created_by=self.user,
        )
        transaction = Transaction.objects.create(
            user=self.user,
            account=account,
            category=category,
            amount=Decimal("120.00"),
            entry_type=EntryType.DEBIT,
            transaction_date="2026-06-15",
            description="Shared lunch",
        )
        GroupService.create_equal_split_expense(
            group=self.group,
            paid_by=self.user,
            transaction_obj=transaction,
            members=[self.user, self.debtor],
        )
        return GroupExpenseSplit.objects.get(
            expense__transaction=transaction,
            user=self.debtor,
        )

    def test_group_split_transaction_rejects_balance_affecting_edits(self):
        split = self.create_due_split()
        transaction = split.expense.transaction

        with self.assertRaisesMessage(ServiceError, "Update the group split"):
            TransactionService.update_transaction(
                transaction_obj=transaction,
                amount=Decimal("130.00"),
            )

        TransactionService.update_transaction(
            transaction_obj=transaction,
            description="Updated lunch note",
        )
        transaction.refresh_from_db()
        self.assertEqual(transaction.amount, Decimal("120.00"))
        self.assertEqual(transaction.description, "Updated lunch note")

    def test_payer_settles_full_share_and_receiver_records_credit_later(self):
        split = self.create_due_split()
        self.assertTrue(
            UserNotification.objects.filter(
                user=self.debtor,
                event="group_expense.split",
            ).exists()
        )
        payer_account = Account.objects.create(
            user=self.debtor,
            name="Payer cash",
            account_type=Account.AccountType.CASH,
            opening_balance=Decimal("100.00"),
            current_balance=Decimal("100.00"),
        )
        receiver_account = Account.objects.create(
            user=self.user,
            name="Receiver bank",
            account_type=Account.AccountType.BANK,
            opening_balance=Decimal("10.00"),
            current_balance=Decimal("10.00"),
        )
        settlement = SettlementService.settle(
            group=self.group,
            payer=self.debtor,
            receiver=self.user,
            account=payer_account,
            split_ids=[split.pk],
            notes="settled",
        )

        self.assertEqual(settlement.amount, Decimal("100.00"))
        self.assertTrue(settlement.is_completed)
        self.assertEqual(settlement.payer_transaction.entry_type, EntryType.DEBIT)
        self.assertTrue(
            UserNotification.objects.filter(
                user=self.user,
                event="group_settlement.paid",
                data__settlement_id=str(settlement.pk),
            ).exists()
        )
        payer_account.refresh_from_db()
        self.assertEqual(payer_account.current_balance, Decimal("40.00"))
        split.refresh_from_db()
        self.assertEqual(split.status, GroupExpenseSplit.Status.SETTLED)
        self.assertEqual(
            SettlementAllocation.objects.get(settlement=settlement, split=split).amount,
            split.share_amount,
        )
        self.assertFalse(GroupBalance.objects.filter(group=self.group, from_user=self.debtor, to_user=self.user).exists())
        self.assertFalse(GroupBalance.objects.filter(group=self.group).exists())

        with self.assertRaisesMessage(ServiceError, "Choose one of your own accounts"):
            SettlementService.record_received(
                settlement=settlement,
                receiver=self.user,
                account=payer_account,
            )

        receiver_transaction = SettlementService.record_received(
            settlement=settlement,
            receiver=self.user,
            account=receiver_account,
        )
        receiver_account.refresh_from_db()
        settlement.refresh_from_db()
        self.assertEqual(receiver_transaction.entry_type, EntryType.CREDIT)
        self.assertEqual(receiver_account.current_balance, Decimal("70.00"))
        self.assertEqual(settlement.receiver_transaction, receiver_transaction)
        self.assertTrue(
            UserNotification.objects.filter(
                user=self.debtor,
                event="group_settlement.received",
                data__settlement_id=str(settlement.pk),
            ).exists()
        )
        with self.assertRaisesMessage(ServiceError, "already been recorded"):
            SettlementService.record_received(
                settlement=settlement,
                receiver=self.user,
                account=receiver_account,
            )

    def test_cannot_settle_a_split_that_belongs_to_another_payer(self):
        split = self.create_due_split()
        payer_account = Account.objects.create(
            user=self.user,
            name="Payer cash",
            account_type=Account.AccountType.CASH,
        )

        with self.assertRaisesMessage(ServiceError, "no longer payable"):
            SettlementService.settle(
                group=self.group,
                payer=self.user,
                receiver=self.debtor,
                account=payer_account,
                split_ids=[split.pk],
            )

    def test_settlement_page_supports_payer_and_receiver_confirmation(self):
        split = self.create_due_split()
        second_transaction = Transaction.objects.create(
            user=self.user,
            account=split.expense.transaction.account,
            category=split.expense.transaction.category,
            amount=Decimal("80.00"),
            entry_type=EntryType.DEBIT,
            transaction_date="2026-06-16",
            description="Shared dinner",
        )
        GroupService.create_equal_split_expense(
            group=self.group,
            paid_by=self.user,
            transaction_obj=second_transaction,
            members=[self.user, self.debtor],
        )
        second_split = GroupExpenseSplit.objects.get(
            expense__transaction=second_transaction,
            user=self.debtor,
        )
        payer_account = Account.objects.create(
            user=self.debtor,
            name="Payer wallet",
            account_type=Account.AccountType.WALLET,
            opening_balance=Decimal("100.00"),
            current_balance=Decimal("100.00"),
        )
        receiver_account = Account.objects.create(
            user=self.user,
            name="Receiver bank",
            account_type=Account.AccountType.BANK,
            opening_balance=Decimal("0.00"),
            current_balance=Decimal("0.00"),
        )

        self.client.force_login(self.debtor)
        page = self.client.get(reverse("group-settlement", kwargs={"pk": self.group.pk}))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Expenses to settle")
        self.assertContains(page, "Paid from")
        self.assertContains(page, "Payer wallet · Wallet")
        self.assertContains(page, "data-select-all")
        self.assertContains(page, "data-select-none")
        self.assertContains(page, 'name="split_ids"')
        self.assertContains(page, "Shared dinner")
        payment_response = self.client.post(
            reverse(
                "group-settlement-pay",
                kwargs={"pk": self.group.pk, "receiver_id": self.user.pk},
            ),
            {
                "account": str(payer_account.pk),
                "split_ids": [str(split.pk), str(second_split.pk)],
                "notes": "Cash app",
            },
        )
        self.assertRedirects(
            payment_response,
            reverse("group-settlement", kwargs={"pk": self.group.pk}),
        )
        settlement = Settlement.objects.get(group=self.group, payer=self.debtor)
        self.assertIsNotNone(settlement.payer_transaction_id)
        self.assertIsNone(settlement.receiver_transaction_id)

        self.client.force_login(self.user)
        receiver_page = self.client.get(
            reverse("group-settlement", kwargs={"pk": self.group.pk})
        )
        self.assertContains(receiver_page, "Record received payment")
        receive_response = self.client.post(
            reverse(
                "group-settlement-record-received",
                kwargs={"pk": self.group.pk, "settlement_id": settlement.pk},
            ),
            {"account": str(receiver_account.pk)},
        )
        self.assertRedirects(
            receive_response,
            reverse("group-settlement", kwargs={"pk": self.group.pk}),
        )
        settlement.refresh_from_db()
        self.assertIsNotNone(settlement.receiver_transaction_id)

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

    def test_stale_group_expense_flag_does_not_block_splitting(self):
        transaction = TransactionService.create_transaction(
            user=self.user,
            account=self.account,
            category=self.category,
            amount=Decimal("80.00"),
            transaction_date="2026-09-30",
            description="Lunch after group deletion",
        )
        transaction.is_group_expense = True
        transaction.save(update_fields=["is_group_expense"])

        expense = GroupService.split_existing_transaction(
            transaction_obj=transaction,
            group=self.group,
            split_mode="equal",
            paid_by=self.user,
        )

        self.assertTrue(GroupExpense.objects.filter(pk=expense.pk).exists())

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

    def test_custom_split_page_assigns_remaining_share_to_current_user(self):
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
            reverse("transaction-split", args=[transaction.pk]),
            {
                "group": str(self.group.pk),
                "split_mode": "custom",
                "selected_members": [str(self.friend.pk)],
                f"share_{self.friend.pk}": "50.00",
            },
        )

        self.assertRedirects(response, reverse("transaction-list"))
        shares = {
            share.user_id: share.share_amount
            for share in GroupExpenseSplit.objects.filter(expense__transaction=transaction)
        }
        self.assertEqual(shares[self.user.pk], Decimal("30.00"))
        self.assertEqual(shares[self.friend.pk], Decimal("50.00"))

    def test_existing_split_can_be_updated_and_rebalances_outstanding_debt(self):
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
            splits=[{"user": self.friend, "amount": "50.00"}],
        )
        self.client.force_login(self.user)

        page = self.client.get(reverse("transaction-split", args=[transaction.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Update split")
        self.assertContains(page, 'value="50.00"')

        response = self.client.post(
            reverse("transaction-split", args=[transaction.pk]),
            {
                "group": str(self.group.pk),
                "split_mode": "custom",
                "selected_members": [str(self.friend.pk)],
                f"share_{self.friend.pk}": "30.00",
            },
        )

        self.assertRedirects(response, reverse("transaction-list"))
        shares = {
            share.user_id: share.share_amount
            for share in GroupExpenseSplit.objects.filter(expense__transaction=transaction)
        }
        self.assertEqual(shares, {
            self.user.pk: Decimal("50.00"),
            self.friend.pk: Decimal("30.00"),
        })
        self.assertEqual(
            GroupBalance.objects.get(
                group=self.group,
                from_user=self.friend,
                to_user=self.user,
            ).balance_amount,
            Decimal("30.00"),
        )

    def test_split_categories_are_hidden_from_transaction_form(self):
        paid_category = Category.objects.create(
            name="Group Settlement Paid",
            category_type=Category.CategoryType.EXPENSE,
            normal_side=EntryType.DEBIT,
            is_system=True,
        )
        received_category = Category.objects.create(
            name="Group Settlement Received",
            category_type=Category.CategoryType.INCOME,
            normal_side=EntryType.CREDIT,
            is_system=True,
        )

        form = TransactionForm(user=self.user)

        self.assertNotIn(paid_category, form.fields["category"].queryset)
        self.assertNotIn(received_category, form.fields["category"].queryset)

    def test_deleting_unsettled_split_removes_shares_and_reverses_group_balance(self):
        transaction = TransactionService.create_transaction(
            user=self.user,
            account=self.account,
            category=self.category,
            amount=Decimal("80.00"),
            transaction_date="2026-09-30",
            description="Dinner",
        )
        expense = GroupService.split_existing_transaction(
            transaction_obj=transaction,
            group=self.group,
            split_mode="custom",
            paid_by=self.user,
            splits=[{"user": self.friend, "amount": "50.00"}],
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("transaction-delete", args=[transaction.pk])
        )

        self.assertRedirects(response, reverse("transaction-list"))
        transaction.refresh_from_db()
        self.assertTrue(transaction.is_deleted)
        self.assertFalse(GroupExpenseSplit.objects.filter(expense=expense).exists())
        self.assertFalse(GroupExpense.objects.filter(pk=expense.pk).exists())
        self.assertFalse(GroupBalance.objects.filter(group=self.group).exists())

    def test_deleting_transaction_with_settled_share_is_blocked(self):
        split = self.create_existing_split_for_deletion()
        payer_account = Account.objects.create(
            user=self.friend,
            name="Settlement wallet",
            account_type=Account.AccountType.WALLET,
            opening_balance=Decimal("100.00"),
            current_balance=Decimal("100.00"),
        )
        SettlementService.settle(
            group=self.group,
            payer=self.friend,
            receiver=self.user,
            account=payer_account,
            split_ids=[split.pk],
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("transaction-delete", args=[split.expense.transaction_id])
        )

        self.assertRedirects(response, reverse("transaction-list"))
        split.expense.transaction.refresh_from_db()
        self.assertFalse(split.expense.transaction.is_deleted)
        self.assertContains(
            self.client.get(reverse("transaction-list")),
            "settled shares and cannot be deleted",
        )

    def create_existing_split_for_deletion(self):
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
            splits=[{"user": self.friend, "amount": "50.00"}],
        )
        return GroupExpenseSplit.objects.get(
            expense__transaction=transaction,
            user=self.friend,
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
                "split_mode": "custom",
                "splits": [
                    {"user_id": self.friend.pk, "amount": "50.00"},
                ],
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(GroupExpenseSplit.objects.filter(expense__transaction=transaction).count(), 2)
        shares = {
            share.user_id: share.share_amount
            for share in GroupExpenseSplit.objects.filter(expense__transaction=transaction)
        }
        self.assertEqual(shares[self.user.pk], Decimal("30.00"))
        self.assertEqual(shares[self.friend.pk], Decimal("50.00"))
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
                    {"user_id": self.friend.pk, "amount": "100.00"},
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

    def test_import_and_export_routes_are_forbidden_to_non_staff(self):
        self.client.force_login(self.user)

        for route in (
            "account-template",
            "transaction-template",
            "transaction-export",
        ):
            with self.subTest(route=route):
                self.assertEqual(self.client.get(reverse(route)).status_code, 403)

        self.assertEqual(self.client.post(reverse("account-upload")).status_code, 403)
        self.assertEqual(self.client.post(reverse("transactions-upload")).status_code, 403)
        self.assertEqual(self.client.post(reverse("receipt-upload")).status_code, 403)

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

    def test_upload_pairs_transfer_rows_by_date_description_and_amount(self):
        destination = Account.objects.create(
            user=self.user,
            name="Savings",
            account_type=Account.AccountType.BANK,
            opening_balance=Decimal("0.00"),
            current_balance=Decimal("0.00"),
        )
        csv_content = (
            "account,category,category_type,category_normal_side,merchant,amount,transaction_date,description\n"
            "Wallet,Transfer Out,transfer,debit,,42.50,7/25/2026,Move to savings\n"
            "Wallet,Transfer Out,transfer,debit,,42.50,7/25/2026,Move to savings\n"
            "Savings,Transfer In,transfer,credit,,42.50,7/25/2026,move to savings\n"
            "Savings,Transfer In,transfer,credit,,42.50,7/25/2026,move to savings\n"
        ).encode("utf-8")

        result = BulkTransactionUploadService().upload(
            self.user,
            SimpleUploadedFile("transfers.csv", csv_content, content_type="text/csv"),
        )

        transfers = list(Transfer.objects.filter(user=self.user).select_related(
            "debit_transaction__account",
            "credit_transaction__account",
        ))
        self.assertEqual(result["created"], 4)
        self.assertEqual(result["transfers_created"], 2)
        self.assertEqual(len(transfers), 2)
        for transfer in transfers:
            self.assertEqual(transfer.debit_transaction.account, self.account)
            self.assertEqual(transfer.credit_transaction.account, destination)
            self.assertEqual(transfer.amount, Decimal("42.50"))
            self.assertEqual(transfer.notes.casefold(), "move to savings")
        self.account.refresh_from_db()
        destination.refresh_from_db()
        self.assertEqual(self.account.current_balance, Decimal("415.00"))
        self.assertEqual(destination.current_balance, Decimal("85.00"))

    def test_unmatched_transfer_row_rolls_back_import(self):
        csv_content = (
            "account,category,category_type,category_normal_side,merchant,amount,transaction_date,description\n"
            "Wallet,Transfer Out,transfer,debit,,42.50,7/25/2026,Move to savings\n"
        ).encode("utf-8")

        with self.assertRaisesMessage(ServiceError, "must have a matching debit and credit"):
            BulkTransactionUploadService().upload(
                self.user,
                SimpleUploadedFile("transfers.csv", csv_content, content_type="text/csv"),
            )

        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 0)
        self.assertFalse(Transfer.objects.filter(user=self.user).exists())
        self.account.refresh_from_db()
        self.assertEqual(self.account.current_balance, Decimal("500.00"))

    def test_export_sign_matches_category_normal_side(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
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


class ReportPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="report-user@example.com",
            username="report-user",
            password="report-test-password",
        )
        self.client.force_login(self.user)

    def test_monthly_and_category_reports_render_without_transactions(self):
        monthly = self.client.get(reverse("monthly-report"))
        category = self.client.get(reverse("category-report"))

        self.assertEqual(monthly.status_code, 200)
        self.assertContains(monthly, "Monthly Report")
        self.assertEqual(category.status_code, 200)
        self.assertContains(category, "Category Report")

    def test_reports_render_investment_only_transactions(self):
        account = Account.objects.create(
            user=self.user,
            name="Investment account",
            account_type=Account.AccountType.INVESTMENT,
        )
        transfer_category = Category.objects.create(
            name="Investment transfer",
            category_type=Category.CategoryType.TRANSFER,
            normal_side=EntryType.DEBIT,
            created_by=self.user,
        )
        transaction_date = timezone.localdate()
        Transaction.objects.create(
            user=self.user,
            account=account,
            category=transfer_category,
            amount=Decimal("25.00"),
            entry_type=EntryType.CREDIT,
            transaction_date=transaction_date,
            description="Investment contribution",
        )

        monthly = self.client.get(
            reverse("monthly-report"),
            {"month": transaction_date.strftime("%Y-%m")},
        )
        category = self.client.get(reverse("category-report"))

        self.assertEqual(monthly.status_code, 200)
        self.assertTrue(monthly.context["has_report_data"])
        self.assertEqual(category.status_code, 200)
        self.assertTrue(category.context["has_report_data"])


class GroupPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="group-user", password="strong-pass")

    def test_group_list_page_renders_for_authenticated_user(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("group-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Groups")

    def test_group_creator_can_update_group_details(self):
        self.client.force_login(self.user)
        group = GroupService.create_group(name="Weekend trip", created_by=self.user)

        response = self.client.post(
            reverse("group-update", kwargs={"pk": group.pk}),
            {"name": "Updated trip", "description": "Autumn plans"},
        )

        self.assertRedirects(response, reverse("group-detail", kwargs={"pk": group.pk}))
        group.refresh_from_db()
        self.assertEqual(group.name, "Updated trip")
        self.assertEqual(group.description, "Autumn plans")

    def test_non_creator_cannot_update_group(self):
        group = GroupService.create_group(name="Creator-owned", created_by=self.user)
        member = User.objects.create_user(username="group-member", password="strong-pass")
        GroupMember.objects.create(group=group, user=member)
        self.client.force_login(member)

        response = self.client.get(reverse("group-update", kwargs={"pk": group.pk}))

        self.assertEqual(response.status_code, 404)
        group.refresh_from_db()
        self.assertEqual(group.name, "Creator-owned")

    def test_group_creator_can_delete_group_data_without_deleting_personal_transaction(self):
        self.client.force_login(self.user)
        group = GroupService.create_group(name="Delete this trip", created_by=self.user)
        member = User.objects.create_user(
            email="group-delete-member@example.com",
            username="group-delete-member",
            password="group-delete-password",
        )
        GroupMember.objects.create(group=group, user=member)
        invitee = User.objects.create_user(
            email="group-delete-invitee@example.com",
            username="group-delete-invitee",
            password="group-delete-password",
        )
        GroupInvitationService.invite_member(
            group=group,
            invited_user=invitee,
            invited_by=self.user,
        )
        account = Account.objects.create(
            user=self.user,
            name="Personal wallet",
            account_type=Account.AccountType.WALLET,
            opening_balance=Decimal("100.00"),
            current_balance=Decimal("100.00"),
        )
        transaction = TransactionService.create_transaction(
            user=self.user,
            account=account,
            category=Category.objects.create(
                name="Group deletion expense",
                category_type=Category.CategoryType.EXPENSE,
                normal_side=EntryType.DEBIT,
                created_by=self.user,
            ),
            amount=Decimal("20.00"),
            transaction_date=timezone.localdate(),
            description="Lunch",
        )
        expense = GroupService.create_equal_split_expense(
            group=group,
            paid_by=self.user,
            transaction_obj=transaction,
            members=[self.user, member],
        )
        member_account = Account.objects.create(
            user=member,
            name="Member wallet",
            account_type=Account.AccountType.WALLET,
            opening_balance=Decimal("100.00"),
            current_balance=Decimal("100.00"),
        )
        member_split = GroupExpenseSplit.objects.get(
            expense=expense,
            user=member,
        )
        settlement = SettlementService.settle(
            group=group,
            payer=member,
            receiver=self.user,
            account=member_account,
            split_ids=[member_split.pk],
        )
        receiver_transaction = SettlementService.record_received(
            settlement=settlement,
            receiver=self.user,
            account=account,
        )
        payer_transaction_id = settlement.payer_transaction_id
        receiver_transaction_id = receiver_transaction.pk
        settled_account_balances = {
            account.pk: Account.objects.get(pk=account.pk).current_balance,
            member_account.pk: Account.objects.get(pk=member_account.pk).current_balance,
        }
        response = self.client.post(
            reverse("group-delete", kwargs={"pk": group.pk})
        )

        self.assertRedirects(response, reverse("group-list"))
        self.assertFalse(ExpenseGroup.objects.filter(pk=group.pk).exists())
        self.assertFalse(GroupExpense.objects.filter(pk=expense.pk).exists())
        self.assertFalse(GroupInvitation.objects.filter(group_id=group.pk).exists())
        self.assertFalse(GroupBalance.objects.filter(group_id=group.pk).exists())
        self.assertFalse(Settlement.objects.filter(pk=settlement.pk).exists())
        self.assertFalse(UserNotification.objects.filter(data__group_id=str(group.pk)).exists())
        transaction.refresh_from_db()
        account.refresh_from_db()
        member_account.refresh_from_db()
        self.assertFalse(transaction.is_deleted)
        self.assertFalse(transaction.is_group_expense)
        self.assertEqual(account.current_balance, settled_account_balances[account.pk])
        self.assertEqual(member_account.current_balance, settled_account_balances[member_account.pk])
        self.assertTrue(Transaction.objects.filter(pk=transaction.pk).exists())
        self.assertTrue(Transaction.objects.filter(pk=payer_transaction_id).exists())
        self.assertTrue(Transaction.objects.filter(pk=receiver_transaction_id).exists())
        self.assertFalse(
            Settlement.objects.filter(payer_transaction_id=payer_transaction_id).exists()
        )
        self.assertFalse(
            Settlement.objects.filter(receiver_transaction_id=receiver_transaction_id).exists()
        )

    def test_non_creator_cannot_delete_group(self):
        group = GroupService.create_group(name="Creator-owned group", created_by=self.user)
        member = User.objects.create_user(
            email="group-delete-noncreator@example.com",
            username="group-delete-noncreator",
            password="group-delete-password",
        )
        GroupMember.objects.create(group=group, user=member)
        self.client.force_login(member)

        response = self.client.post(
            reverse("group-delete", kwargs={"pk": group.pk})
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(ExpenseGroup.objects.filter(pk=group.pk).exists())

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

    def test_group_creator_can_remove_member_without_outstanding_balance(self):
        self.client.force_login(self.user)
        group = GroupService.create_group(name="Weekend trip", created_by=self.user)
        member = User.objects.create_user(
            email="removable-member@example.com",
            username="removable-member",
            password="test-password",
        )
        GroupMember.objects.create(group=group, user=member)

        response = self.client.post(
            reverse("group-member-remove", kwargs={"pk": group.pk, "user_id": member.pk})
        )

        self.assertRedirects(response, reverse("group-detail", kwargs={"pk": group.pk}))
        self.assertFalse(GroupMember.objects.filter(group=group, user=member).exists())
        self.assertTrue(
            UserNotification.objects.filter(
                user=member,
                event="group_member.removed",
                data__group_id=str(group.pk),
            ).exists()
        )

    def test_notification_inbox_excludes_and_deletes_expired_notifications(self):
        expired = UserNotification.objects.create(
            user=self.user,
            event="group.test",
            message="Expired",
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        other_user = User.objects.create_user(
            email="notification-owner@example.com",
            username="notification-owner",
            password="notification-test-password",
        )
        other_notification = UserNotification.objects.create(
            user=other_user,
            event="group.test",
            message="Private",
        )
        unread_notification = UserNotification.objects.create(
            user=self.user,
            event="group.test",
            message="Unread",
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("notification-list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["unread_count"], 1)
        self.assertEqual(
            [item["id"] for item in response.json()["notifications"]],
            [str(unread_notification.pk)],
        )
        self.assertFalse(UserNotification.objects.filter(pk=expired.pk).exists())
        self.assertTrue(UserNotification.objects.filter(pk=other_notification.pk).exists())

        opened_response = self.client.post(reverse("notification-mark-all-read"))

        self.assertEqual(opened_response.status_code, 200)
        self.assertEqual(opened_response.json()["unread_count"], 0)
        unread_notification.refresh_from_db()
        self.assertTrue(unread_notification.is_read)
        other_notification.refresh_from_db()
        self.assertFalse(other_notification.is_read)

    def test_user_cannot_mark_another_users_notification_as_read(self):
        owner = User.objects.create_user(
            email="private-notification@example.com",
            username="private-notification",
            password="notification-test-password",
        )
        notification = UserNotification.objects.create(
            user=owner,
            event="group.test",
            message="Private",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                "notification-mark-read",
                kwargs={"notification_id": notification.pk},
            )
        )

        self.assertEqual(response.status_code, 404)
        notification.refresh_from_db()
        self.assertFalse(notification.is_read)

    def test_group_member_with_outstanding_balance_cannot_be_removed(self):
        self.client.force_login(self.user)
        group = GroupService.create_group(name="Weekend trip", created_by=self.user)
        member = User.objects.create_user(
            email="owing-member@example.com",
            username="owing-member",
            password="test-password",
        )
        GroupMember.objects.create(group=group, user=member)
        GroupBalance.objects.create(
            group=group,
            from_user=member,
            to_user=self.user,
            balance_amount=Decimal("20.00"),
        )

        response = self.client.post(
            reverse("group-member-remove", kwargs={"pk": group.pk, "user_id": member.pk})
        )

        self.assertRedirects(response, reverse("group-detail", kwargs={"pk": group.pk}))
        self.assertTrue(GroupMember.objects.filter(group=group, user=member).exists())
        self.assertContains(
            self.client.get(reverse("group-detail", kwargs={"pk": group.pk})),
            "Settle all outstanding group balances",
        )

    def test_invitation_is_visible_to_invitee_and_can_be_accepted(self):
        invitee = User.objects.create_user(
            email="group-invitee@example.com",
            username="group-invitee",
            password="test-password",
        )
        group = GroupService.create_group(name="Shared trip", created_by=self.user)
        invitation = GroupInvitationService.invite_member(
            group=group,
            invited_user=invitee,
            invited_by=self.user,
        )
        saved_notification = UserNotification.objects.get(
            user=invitee,
            event="group_invitation.created",
        )
        self.assertEqual(saved_notification.data["invitation_id"], str(invitation.pk))
        self.assertGreater(
            saved_notification.expires_at,
            timezone.now() + timedelta(days=6),
        )
        self.client.force_login(invitee)

        inbox_response = self.client.get(reverse("group-invitations"))
        self.assertEqual(inbox_response.status_code, 200)
        self.assertContains(inbox_response, "Shared trip")
        self.assertContains(inbox_response, "Invitations")
        notification_response = self.client.get(
            reverse("group-invitations"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(notification_response.status_code, 200)
        self.assertEqual(
            notification_response.json()["invitations"][0]["id"],
            str(invitation.pk),
        )
        saved_response = self.client.get(reverse("notification-list"))
        self.assertEqual(saved_response.status_code, 200)
        self.assertEqual(saved_response.json()["unread_count"], 1)
        self.assertEqual(
            saved_response.json()["notifications"][0]["id"],
            str(saved_notification.pk),
        )
        mark_read_response = self.client.post(
            reverse(
                "notification-mark-read",
                kwargs={"notification_id": saved_notification.pk},
            )
        )
        self.assertEqual(mark_read_response.status_code, 200)
        self.assertEqual(mark_read_response.json()["unread_count"], 0)
        saved_notification.refresh_from_db()
        self.assertTrue(saved_notification.is_read)

        response = self.client.post(
            reverse("group-invitation-accept", kwargs={"pk": invitation.pk})
        )

        self.assertRedirects(response, reverse("group-invitations"))
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, GroupInvitation.Status.ACCEPTED)
        self.assertTrue(GroupMember.objects.filter(group=group, user=invitee).exists())
        self.assertTrue(
            UserNotification.objects.filter(
                user=self.user,
                event="group_invitation.responded",
                data__invitation_id=str(invitation.pk),
            ).exists()
        )
        self.assertNotContains(
            self.client.get(reverse("group-invitations")),
            "Shared trip",
        )

    def test_invitation_can_be_declined(self):
        invitee = User.objects.create_user(
            email="declining-invitee@example.com",
            username="declining-invitee",
            password="test-password",
        )
        group = GroupService.create_group(name="Declined trip", created_by=self.user)
        invitation = GroupInvitationService.invite_member(
            group=group,
            invited_user=invitee,
            invited_by=self.user,
        )
        self.client.force_login(invitee)

        response = self.client.post(
            reverse("group-invitation-decline", kwargs={"pk": invitation.pk})
        )

        self.assertRedirects(response, reverse("group-invitations"))
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, GroupInvitation.Status.DECLINED)
        self.assertFalse(GroupMember.objects.filter(group=group, user=invitee).exists())

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
