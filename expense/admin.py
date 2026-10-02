from django.contrib import admin

from .models import (
    Account,
    Category,
    Merchant,
    Transaction,
    TransactionItem,
    Budget,
    ExpenseGroup,
    GroupInvitation,
    GroupMember,
    GroupExpense,
    GroupExpenseSplit,
    GroupBalance,
    Settlement,
    SettlementAllocation,
    Transfer,
    UserNotification,
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
        "normal_side",
        "parent",
        "is_system",
    )

    list_filter = (
        "category_type",
        "normal_side",
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


class TransactionItemInline(admin.TabularInline):
    model = TransactionItem
    extra = 0


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "transaction_date",
        "user",
        "entry_type",
        "amount",
        "account",
        "category",
        "is_deleted",
    )

    list_filter = (
        "entry_type",
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

@admin.register(Transfer)
class TransferAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "transfer_type",
        "debit_transaction",
        "credit_transaction",
        "notes",
        "is_deleted",
    )

    list_filter = (
        "transfer_type",
        "is_deleted",
    )

    search_fields = (
        "notes",
    )

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

@admin.register(GroupInvitation)
class GroupInvitationAdmin(admin.ModelAdmin):
    list_display = (
        "group",
        "invited_user",
        "invited_by",
        "status",
        "created_at",
        "responded_at",
    )

    list_filter = (
        "status",
        "created_at",
    )

    search_fields = (
        "group__name",
        "invited_user__email",
        "invited_user__username",
        "invited_by__email",
        "invited_by__username",
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
        "is_completed",
        "payer_transaction",
        "receiver_transaction",
    )

    list_filter = (
        "settlement_date",
        "is_completed",
    )


@admin.register(SettlementAllocation)
class SettlementAllocationAdmin(admin.ModelAdmin):
    list_display = (
        "settlement",
        "split",
        "amount",
        "created_at",
    )

    search_fields = (
        "settlement__group__name",
        "settlement__payer__username",
        "settlement__receiver__username",
    )


@admin.register(UserNotification)
class UserNotificationAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "event",
        "message",
        "created_at",
        "expires_at",
    )
    list_filter = ("event", "created_at", "expires_at")
    search_fields = ("user__username", "user__email", "message")