# expense/models.py

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone

User = settings.AUTH_USER_MODEL


# ============================================================
# Base Model
# ============================================================

class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ============================================================
# Account
# ============================================================

class Account(BaseModel):

    class AccountType(models.TextChoices):
        BANK = "bank", "Bank"
        CASH = "cash", "Cash"
        CREDIT_CARD = "credit_card", "Credit Card"
        WALLET = "wallet", "Wallet"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="accounts"
    )

    name = models.CharField(max_length=100)

    account_type = models.CharField(
        max_length=20,
        choices=AccountType.choices
    )

    opening_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00")
    )

    current_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00")
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "account"

        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["user", "account_type"]),
        ]

    def __str__(self):
        return self.name

    def credit(self, amount):
        self.current_balance += Decimal(amount)
        self.save(update_fields=["current_balance"])

    def debit(self, amount):
        self.current_balance -= Decimal(amount)
        self.save(update_fields=["current_balance"])

    @property
    def calculated_balance(self):
        income = (
            self.transactions.filter(
                transaction_type=Transaction.TransactionType.INCOME,
                is_deleted=False
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )

        expense = (
            self.transactions.filter(
                transaction_type=Transaction.TransactionType.EXPENSE,
                is_deleted=False
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )

        return self.opening_balance + income - expense


# ============================================================
# Category
# ============================================================

class Category(BaseModel):

    class CategoryType(models.TextChoices):
        INCOME = "income", "Income"
        EXPENSE = "expense", "Expense"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    name = models.CharField(max_length=100)

    category_type = models.CharField(
        max_length=10,
        choices=CategoryType.choices
    )

    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children"
    )

    is_system = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="custom_categories"
    )

    icon = models.CharField(
        max_length=50,
        blank=True
    )

    class Meta:
        db_table = "category"

        constraints = [
            models.UniqueConstraint(
                fields=["name", "created_by"],
                name="uq_category_name_creator"
            )
        ]

        indexes = [
            models.Index(fields=["parent"]),
            models.Index(fields=["category_type"]),
        ]

    def __str__(self):
        return self.name


# ============================================================
# Merchant
# ============================================================

class Merchant(BaseModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    name = models.CharField(max_length=255)

    is_system = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="custom_merchants"
    )

    class Meta:
        db_table = "merchant"

        constraints = [
            models.UniqueConstraint(
                fields=["name", "created_by"],
                name="uq_merchant_name_creator"
            )
        ]

        indexes = [
            models.Index(fields=["name"])
        ]

    def __str__(self):
        return self.name


# ============================================================
# Tag
# ============================================================

class Tag(BaseModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="tags"
    )

    is_system = models.BooleanField(default=False)

    name = models.CharField(max_length=50)

    class Meta:
        db_table = "tag"

        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                name="uq_tag_user_name"
            )
        ]

    def __str__(self):
        return self.name


# ============================================================
# Transaction
# ============================================================

class Transaction(BaseModel):

    class TransactionType(models.TextChoices):
        INCOME = "income", "Income"
        EXPENSE = "expense", "Expense"
        TRANSFER = "transfer", "Transfer"
        REFUND = "refund", "Refund"

    class TransactionStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        POSTED = "posted", "Posted"
        CANCELLED = "cancelled", "Cancelled"
    
    status = models.CharField(
        max_length=20,
        choices=TransactionStatus.choices,
        default=TransactionStatus.POSTED
    )
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="transactions"
    )

    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="transactions"
    )

    transfer_account = models.ForeignKey(
        "Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="incoming_transfers"
    )

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="transactions"
    )

    merchant = models.ForeignKey(
        Merchant,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="transactions"
    )

    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2
    )

    transaction_type = models.CharField(
        max_length=20,
        choices=TransactionType.choices
    )

    transaction_date = models.DateField(
        default=timezone.now
    )

    description = models.TextField(blank=True)

    reference_number = models.CharField(
        max_length=100,
        blank=True
    )

    is_group_expense = models.BooleanField(default=False)

    is_deleted = models.BooleanField(default=False)

    tags = models.ManyToManyField(
        "Tag",
        through="TransactionTag",
        blank=True
    )

    class Meta:
        db_table = "transaction"

        indexes = [
            models.Index(
                fields=["user", "-transaction_date"]
            ),
            models.Index(
                fields=["user","is_deleted"]
            ),
            models.Index(
                fields=["account", "-transaction_date"]
            ),
            models.Index(
                fields=["category", "transaction_date"]
            ),
            models.Index(
                fields=["merchant", "transaction_date"]
            ),
            models.Index(
                fields=["transaction_type"]
            ),
        ]

    def __str__(self):
        return f"{self.transaction_type} - {self.amount}"


# ============================================================
# Transaction Item
# ============================================================

class TransactionItem(BaseModel):

    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.CASCADE,
        related_name="items"
    )

    name = models.CharField(
        max_length=200
    )

    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=1
    )

    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    total_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        editable=False
    )

    def save(self, *args, **kwargs):

        self.total_price = (
            self.quantity *
            self.unit_price
        )

        super().save(
            *args,
            **kwargs
        )

# ============================================================
# Transaction Tag
# ============================================================

class TransactionTag(models.Model):

    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.CASCADE
    )

    tag = models.ForeignKey(
        Tag,
        on_delete=models.CASCADE
    )

    class Meta:
        db_table = "transaction_tag"

        constraints = [
            models.UniqueConstraint(
                fields=["transaction", "tag"],
                name="uq_transaction_tag"
            )
        ]


# ============================================================
# Attachment
# ============================================================

class Attachment(BaseModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.CASCADE,
        related_name="attachments"
    )

    file = models.FileField(
        upload_to="receipts/"
    )


# ============================================================
# Ledger Entry
# ============================================================

class LedgerEntry(BaseModel):

    class EntryType(models.TextChoices):
        CREDIT = "credit", "Credit"
        DEBIT = "debit", "Debit"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.CASCADE,
        related_name="ledger_entries"
    )

    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="ledger_entries"
    )

    entry_type = models.CharField(
        max_length=10,
        choices=EntryType.choices
    )

    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2
    )

    running_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0
    )

    class Meta:
        db_table = "ledger_entry"

        indexes = [
            models.Index(fields=["account"]),
            models.Index(fields=["transaction"]),
            models.Index(fields=["account", "-created_at"]),
        ]


# ============================================================
# Budget
# ============================================================

class Budget(BaseModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE
    )

    month = models.PositiveSmallIntegerField()
    year = models.PositiveSmallIntegerField()

    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2
    )

    class Meta:
        db_table = "budget"

        constraints = [
            models.UniqueConstraint(
                fields=["user", "category", "month", "year"],
                name="uq_budget_period"
            )
        ]


# ============================================================
# Expense Group
# ============================================================

class ExpenseGroup(BaseModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    name = models.CharField(max_length=200)

    description = models.TextField(blank=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="created_groups"
    )

    class Meta:
        db_table = "expense_group"

    @property
    def total_expense(self):
        return (
            self.expenses.aggregate(
                total=Sum("transaction__amount")
            )["total"]
            or Decimal("0.00")
        )

    def __str__(self):
        return self.name


# ============================================================
# Group Member
# ============================================================

class GroupMember(BaseModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    group = models.ForeignKey(
        ExpenseGroup,
        on_delete=models.CASCADE,
        related_name="members"
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    class Meta:
        db_table = "group_member"

        constraints = [
            models.UniqueConstraint(
                fields=["group", "user"],
                name="uq_group_member"
            )
        ]


# ============================================================
# Group Expense
# ============================================================

class GroupExpense(BaseModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    group = models.ForeignKey(
        ExpenseGroup,
        on_delete=models.CASCADE,
        related_name="expenses"
    )

    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.CASCADE,
        related_name="group_expense"
    )

    paid_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    class Meta:
        db_table = "group_expense"

        indexes = [
            models.Index(fields=["group"]),
            models.Index(fields=["paid_by"]),
        ]


# ============================================================
# Group Expense Split
# ============================================================

class GroupExpenseSplit(BaseModel):

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SETTLED = "settled", "Settled"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    expense = models.ForeignKey(
        GroupExpense,
        on_delete=models.CASCADE,
        related_name="splits"
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    share_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )

    class Meta:
        db_table = "group_expense_split"

        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["expense"]),
        ]


# ============================================================
# Settlement
# ============================================================

class Settlement(BaseModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    group = models.ForeignKey(
        ExpenseGroup,
        on_delete=models.CASCADE
    )

    payer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="payments_made"
    )

    receiver = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="payments_received"
    )

    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2
    )

    settlement_date = models.DateField(
        default=timezone.now
    )

    notes = models.TextField(blank=True)

    class Meta:
        db_table = "settlement"

        indexes = [
            models.Index(fields=["group"]),
            models.Index(fields=["payer"]),
            models.Index(fields=["receiver"]),
        ]


# ============================================================
# Group Balance
# ============================================================

class GroupBalance(BaseModel):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    group = models.ForeignKey(
        ExpenseGroup,
        on_delete=models.CASCADE,
        related_name="balances"
    )

    from_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="owes"
    )

    to_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="owed_by"
    )

    balance_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00")
    )

    class Meta:
        db_table = "group_balance"

        constraints = [
            models.UniqueConstraint(
                fields=["group", "from_user", "to_user"],
                name="uq_group_balance_pair"
            )
        ]

        indexes = [
            models.Index(fields=["group"]),
            models.Index(fields=["from_user"]),
            models.Index(fields=["to_user"]),
        ]