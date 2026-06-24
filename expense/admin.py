from django.contrib import admin

from .models import (
    Account,
    Category,
    Merchant,
    Tag,
    Transaction,
    TransactionItem,
    LedgerEntry,
    Budget,
    ExpenseGroup,
    GroupMember,
    GroupExpense,
    GroupExpenseSplit,
    GroupBalance,
    Settlement,
)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "user",
        "account_type",
        "current_balance",
        "is_active",
    )

    list_filter = (
        "account_type",
        "is_active",
    )

    search_fields = (
        "name",
        "user__username",
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category_type",
        "parent",
        "is_system",
    )

    list_filter = (
        "category_type",
        "is_system",
    )

    search_fields = (
        "name",
    )


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "is_system",
        "created_by",
    )

    list_filter = (
        "is_system",
    )

    search_fields = (
        "name",
    )


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "user",
    )

    search_fields = (
        "name",
    )


class TransactionItemInline(admin.TabularInline):
    model = TransactionItem
    extra = 0


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "transaction_date",
        "user",
        "transaction_type",
        "amount",
        "account",
        "category",
        "is_deleted",
    )

    list_filter = (
        "transaction_type",
        "is_deleted",
    )

    search_fields = (
        "description",
        "reference_number",
    )

    autocomplete_fields = (
        "account",
        "category",
        "merchant",
    )

    inlines = [
        TransactionItemInline
    ]


@admin.register(TransactionItem)
class TransactionItemAdmin(admin.ModelAdmin):
    list_display = (
        "transaction",
        "name",
        "quantity",
        "unit_price",
        "total_price",
    )

    search_fields = (
        "name",
    )


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "account",
        "entry_type",
        "amount",
        "running_balance",
    )

    list_filter = (
        "entry_type",
    )


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "category",
        "month",
        "year",
        "amount",
    )

    list_filter = (
        "month",
        "year",
    )


@admin.register(ExpenseGroup)
class ExpenseGroupAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "created_by",
        "created_at",
    )

    search_fields = (
        "name",
    )


@admin.register(GroupMember)
class GroupMemberAdmin(admin.ModelAdmin):
    list_display = (
        "group",
        "user",
    )

    search_fields = (
        "group__name",
        "user__username",
    )


@admin.register(GroupExpense)
class GroupExpenseAdmin(admin.ModelAdmin):
    list_display = (
        "group",
        "paid_by",
        "transaction",
    )


@admin.register(GroupExpenseSplit)
class GroupExpenseSplitAdmin(admin.ModelAdmin):
    list_display = (
        "expense",
        "user",
        "share_amount",
    )


@admin.register(GroupBalance)
class GroupBalanceAdmin(admin.ModelAdmin):
    list_display = (
        "group",
        "from_user",
        "to_user",
        "balance_amount",
    )

    search_fields = (
        "group__name",
        "from_user__username",
        "to_user__username",
    )


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = (
        "group",
        "payer",
        "receiver",
        "amount",
        "settlement_date",
    )

    list_filter = (
        "settlement_date",
    )