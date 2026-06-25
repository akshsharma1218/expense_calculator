from datetime import date
from decimal import Decimal
import json
from calendar import month_abbr

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import (
    render,
    redirect,
    get_object_or_404,
)
from django.core.paginator import Paginator

from .models import (
    Account,
    Category,
    EntryType,
    Merchant,
    Transaction,
    TransactionItem,
    Budget,
    ExpenseGroup,
)

from .forms import (
    AccountForm,
    CategoryForm,
    MerchantForm,
    TransactionForm,
    BudgetForm,
    ExpenseGroupForm,
    SettlementForm,
    TransactionItemFormSet,
)

from django.contrib.auth.forms import UserCreationForm

from .services import (
    BudgetService,
    DashboardService,
    GroupService,
    SettlementService,
    ServiceError,
    TransactionService,
    TransferService,
)


def _collect_transaction_items(formset):
    items = []
    total_amount = Decimal("0.00")

    for item_form in formset:
        if not item_form.cleaned_data:
            continue

        if item_form.cleaned_data.get("DELETE"):
            continue

        quantity = item_form.cleaned_data["quantity"]
        unit_price = item_form.cleaned_data["unit_price"]
        item_total = quantity * unit_price
        total_amount += item_total

        items.append({
            "name": item_form.cleaned_data["name"],
            "quantity": quantity,
            "unit_price": unit_price,
            "total_price": item_total,
        })

    return items, total_amount


def _transaction_fields_from_form(form):
    return {
        "category": form.cleaned_data["category"],
        "merchant": form.cleaned_data.get("merchant"),
        "transaction_date": form.cleaned_data["transaction_date"],
        "description": form.cleaned_data["description"],
        "reference_number": form.cleaned_data["reference_number"],
    }


def _transaction_create_fields_from_form(form):
    fields = _transaction_fields_from_form(form)
    fields["account"] = form.cleaned_data["account"]
    return fields

def signup(request):

    if request.method == "POST":

        form = UserCreationForm(
            request.POST
        )

        if form.is_valid():

            form.save()

            messages.success(
                request,
                "Account created successfully."
            )

            return redirect(
                "login"
            )

    else:

        form = UserCreationForm()

    return render(
        request,
        "registration/signup.html",
        {
            "form": form
        },
    )


# ============================================================
# DASHBOARD
# ============================================================

@login_required
def dashboard(request):

    today = date.today()

    monthly_trend = DashboardService.monthly_trend(user=request.user)
    category_breakdown = DashboardService.category_breakdown(
        user=request.user,
        month=today.month,
        year=today.year,
    )
    account_distribution = DashboardService.account_distribution(user=request.user)

    context = {
        "accounts": Account.objects.filter(
            user=request.user,
            is_active=True,
        ).only("id", "name", "current_balance", "account_type"),
        "total_balance": DashboardService.total_balance(
            request.user
        ),
        "monthly_expense": DashboardService.monthly_expense(
            user=request.user,
            month=today.month,
            year=today.year,
        ),
        "monthly_income": DashboardService.monthly_income(
            user=request.user,
            month=today.month,
            year=today.year,
        ),
        "recent_transactions": DashboardService.recent_transactions(
            user=request.user
        ),
        "chart_monthly_trend": json.dumps(monthly_trend),
        "chart_category_breakdown": json.dumps(category_breakdown),
        "chart_account_distribution": json.dumps(account_distribution),
        "current_month_label": f"{month_abbr[today.month]} {today.year}",
    }

    context["monthly_savings"] = (
        context["monthly_income"]
        - context["monthly_expense"]
    )
    return render(
        request,
        "expense/dashboard.html",
        context,
    )


# ============================================================
# ACCOUNTS
# ============================================================

@login_required
def account_list(request):

    accounts = list(
        Account.objects.filter(
            user=request.user,
            is_active=True,
        ).only("id", "name", "account_type", "opening_balance", "current_balance", "created_at")
    )

    total_balance = sum(
        (account.current_balance for account in accounts),
        Decimal("0.00"),
    )

    accounts_data = [
        {
            "id": str(account.id),
            "name": account.name,
            "type": account.account_type,
            "opening_balance": float(account.opening_balance),
            "current_balance": float(account.current_balance),
            "created": account.created_at.strftime("%d %b %Y"),
        }
        for account in accounts
    ]

    return render(
        request,
        "expense/account/list.html",
        {
            "accounts": accounts,
            "accounts_json": json.dumps(accounts_data),
            "total_balance": total_balance,
        },
    )


@login_required
def account_create(request):

    if request.method == "POST":

        form = AccountForm(request.POST)

        if form.is_valid():

            account = form.save(
                commit=False
            )

            account.user = request.user
            account.current_balance = (
                account.opening_balance
            )

            account.save()

            messages.success(
                request,
                "Account created successfully."
            )

            return redirect(
                "account-list"
            )

    else:

        form = AccountForm()

    return render(
        request,
        "expense/account/form.html",
        {
            "form": form
        },
    )


# ============================================================
# TRANSACTIONS
# ============================================================

@login_required
def transaction_list(request):

    transactions = (
        Transaction.objects
        .select_related(
            "account",
            "category",
            "merchant",
            "transaction_group",
        )
        .filter(
            user=request.user,
            is_deleted=False,
        )
        .only(
            "id",
            "amount",
            "transaction_date",
            "entry_type",
            "description",
            "account_id",
            "category_id",
            "merchant_id",
            "transaction_group_id",
            "transaction_group__operation_type",
            "account__name",
            "category__name",
            "merchant__name",
        )
        .order_by(
            "-transaction_date",
            "-created_at",
        )
    )

    transactions_data = [
        {
            "id": str(txn.id),
            "date": txn.transaction_date.isoformat(),
            "type": txn.entry_type,
            "operation": txn.transaction_group.operation_type,
            "category": txn.category.name if txn.category else "—",
            "merchant": txn.merchant.name if txn.merchant else "—",
            "account": txn.account.name,
            "amount": float(txn.amount),
            "description": txn.description or "",
            "delete_url": f"/transactions/{txn.id}/delete/",
            "edit_url": f"/transactions/{txn.id}/edit/",
        }
        for txn in transactions
    ]

    return render(
        request,
        "expense/transaction/list.html",
        {
            "transactions_json": json.dumps(transactions_data),
            "transaction_count": len(transactions_data),
        },
    )


@login_required
def transaction_create(request):

    if request.method == "POST":

        form = TransactionForm(
            request.POST,
            user=request.user,
        )

        formset = TransactionItemFormSet(
            request.POST,
            queryset=TransactionItem.objects.none(),
            prefix="items",
        )

        if form.is_valid() and formset.is_valid():

            items, total_amount = _collect_transaction_items(formset)

            if not items:
                messages.error(request, "Add at least one item.")
            else:
                try:
                    to_account = form.cleaned_data.get("to_account")
                    shared = {
                        "user": request.user,
                        "amount": total_amount,
                        "tags": form.cleaned_data["tags"],
                        **_transaction_create_fields_from_form(form),
                    }
                    if to_account:
                        TransferService.create_transfer(
                            to_account=to_account,
                            from_account=form.cleaned_data["account"],
                            items=items,
                            **shared,
                        )
                    else:
                        TransactionService.create_transaction(
                            items=items,
                            **shared,
                        )
                except ServiceError as exc:
                    messages.error(request, str(exc))
                else:
                    messages.success(request, "Transaction created.")
                    return redirect("transaction-list")

    else:

        form = TransactionForm(user=request.user)

        formset = TransactionItemFormSet(
            queryset=TransactionItem.objects.none(),
            prefix="items",
        )

    return render(
        request,
        "expense/transaction/form.html",
        {
            "form": form,
            "formset": formset,
            "is_edit": False,
        },
    )


@login_required
def transaction_update(request, pk):

    transaction = get_object_or_404(
        Transaction,
        pk=pk,
        user=request.user,
        is_deleted=False,
    )

    if request.method == "POST":

        form = TransactionForm(
            request.POST,
            instance=transaction,
            user=request.user,
        )

        formset = TransactionItemFormSet(
            request.POST,
            queryset=transaction.items.all(),
            prefix="items",
        )

        if form.is_valid() and formset.is_valid():

            items, _total_amount = _collect_transaction_items(formset)

            if not items:
                messages.error(request, "Add at least one item.")
            else:
                try:
                    TransactionService.update_transaction(
                        transaction_obj=transaction,
                        items=items,
                        tags=form.cleaned_data["tags"],
                        **_transaction_fields_from_form(form),
                    )
                except ServiceError as exc:
                    messages.error(request, str(exc))
                else:
                    messages.success(request, "Transaction updated.")
                    return redirect("transaction-list")

    else:

        form = TransactionForm(
            instance=transaction,
            user=request.user,
        )

        formset = TransactionItemFormSet(
            queryset=transaction.items.all(),
            prefix="items",
        )

    return render(
        request,
        "expense/transaction/form.html",
        {
            "form": form,
            "formset": formset,
            "transaction": transaction,
            "is_edit": True,
        },
    )

@login_required
def transaction_delete(
    request,
    pk
):

    transaction = get_object_or_404(
        Transaction,
        pk=pk,
        user=request.user,
    )

    TransactionService.delete_transaction(
        transaction
    )

    messages.success(
        request,
        "Transaction deleted."
    )

    return redirect(
        "transaction-list"
    )


# ============================================================
# BUDGETS
# ============================================================

@login_required
def budget_list(request):

    budgets = (
        Budget.objects.filter(user=request.user)
        .select_related("category")
        .only("id", "month", "year", "amount", "category_id", "category__name")
        .order_by("-year", "-month", "category__name")
    )

    budget_summaries = []
    for budget in budgets:
        budget_summaries.append(
            {
                "budget": budget,
                **BudgetService.get_budget_status(budget),
            }
        )

    return render(
        request,
        "expense/budget/list.html",
        {
            "budgets": budget_summaries,
        },
    )


@login_required
def budget_detail(request, pk):

    budget = get_object_or_404(
        Budget,
        pk=pk,
        user=request.user,
    )

    status = BudgetService.get_budget_status(budget)
    transactions = (
        Transaction.objects.filter(
            user=request.user,
            category=budget.category,
            entry_type=EntryType.DEBIT,
            transaction_date__month=budget.month,
            transaction_date__year=budget.year,
            is_deleted=False,
        )
        .select_related("account", "merchant")
        .only(
            "id",
            "amount",
            "description",
            "transaction_date",
            "account_id",
            "merchant_id",
        )
        .order_by("-transaction_date", "-created_at")
    )

    return render(
        request,
        "expense/budget/detail.html",
        {
            "budget": budget,
            "status": status,
            "transactions": transactions,
        },
    )


@login_required
def budget_create(request):

    if request.method == "POST":

        form = BudgetForm(
            request.POST,
            user=request.user,
        )

        if form.is_valid():

            budget = form.save(commit=False)
            budget.user = request.user
            budget.save()

            messages.success(request, "Budget created.")
            return redirect("budget-list")

    else:
        form = BudgetForm(user=request.user)

    return render(
        request,
        "expense/budget/form.html",
        {
            "form": form,
            "title": "Create Budget",
        },
    )


@login_required
def budget_update(request, pk):

    budget = get_object_or_404(Budget, pk=pk, user=request.user)

    if request.method == "POST":
        form = BudgetForm(request.POST, instance=budget, user=request.user)

        if form.is_valid():
            form.save()
            messages.success(request, "Budget updated.")
            return redirect("budget-list")
    else:
        form = BudgetForm(instance=budget, user=request.user)

    return render(
        request,
        "expense/budget/form.html",
        {
            "form": form,
            "title": "Update Budget",
        },
    )


@login_required
def budget_delete(request, pk):

    budget = get_object_or_404(Budget, pk=pk, user=request.user)
    budget.delete()
    messages.success(request, "Budget deleted.")
    return redirect("budget-list")


# ============================================================
# GROUPS
# ============================================================

@login_required
def group_list(request):

    groups = (
        ExpenseGroup.objects
        .filter(
            members__user=request.user
        )
        .distinct()
    )

    return render(
        request,
        "expense/group/list.html",
        {
            "groups": groups
        },
    )


@login_required
def group_create(request):

    if request.method == "POST":

        form = ExpenseGroupForm(
            request.POST
        )

        if form.is_valid():

            GroupService.create_group(
                name=form.cleaned_data["name"],
                description=form.cleaned_data[
                    "description"
                ],
                created_by=request.user,
            )

            messages.success(
                request,
                "Group created."
            )

            return redirect(
                "group-list"
            )

    else:

        form = ExpenseGroupForm()

    return render(
        request,
        "expense/group/form.html",
        {
            "form": form
        },
    )


@login_required
def group_detail(
    request,
    pk
):

    group = get_object_or_404(
        ExpenseGroup,
        pk=pk,
    )

    context = {

        "group": group,

        "members":
            group.members.select_related(
                "user"
            ),

        "expenses":
            group.expenses.select_related(
                "transaction",
                "paid_by",
            ),

        "balances":
            group.balances.select_related(
                "from_user",
                "to_user",
            ),
    }

    return render(
        request,
        "expense/group/detail.html",
        context,
    )


@login_required
def settlement_create(
    request,
    pk
):

    group = get_object_or_404(
        ExpenseGroup,
        pk=pk,
    )

    if request.method == "POST":

        form = SettlementForm(
            request.POST
        )

        if form.is_valid():

            SettlementService.settle(
                group=group,
                payer=form.cleaned_data[
                    "payer"
                ],
                receiver=form.cleaned_data[
                    "receiver"
                ],
                amount=form.cleaned_data[
                    "amount"
                ],
                notes=form.cleaned_data[
                    "notes"
                ],
            )

            messages.success(
                request,
                "Settlement completed."
            )

            return redirect(
                "group-detail",
                pk=group.pk,
            )

    else:

        form = SettlementForm()

    return render(
        request,
        "expense/group/settlement.html",
        {
            "form": form,
            "group": group,
        },
    )


# ============================================================
# REPORTS
# ============================================================

@login_required
def monthly_report(request):

    data = list(
        Transaction.objects
        .filter(
            user=request.user,
            entry_type=EntryType.DEBIT,
            is_deleted=False,
        )
        .values(
            "category__name"
        )
        .annotate(
            total=Sum("amount")
        )
        .order_by("-total")
    )

    chart_data = [
        {
            "name": item["category__name"] or "Uncategorized",
            "total": float(item["total"] or 0),
        }
        for item in data
    ]

    return render(
        request,
        "expense/reports/monthly.html",
        {
            "data": data,
            "total_expense": sum(item["total"] for item in data),
            "chart_data": json.dumps(chart_data),
        },
    )


@login_required
def category_report(request):

    categories = list(
        Transaction.objects
        .filter(
            user=request.user,
            entry_type=EntryType.DEBIT,
            is_deleted=False,
        )
        .values(
            "category__name"
        )
        .annotate(
            total=Sum("amount")
        )
        .order_by("-total")
    )

    chart_data = [
        {
            "name": item["category__name"] or "Uncategorized",
            "total": float(item["total"] or 0),
        }
        for item in categories
    ]

    return render(
        request,
        "expense/reports/category.html",
        {
            "categories": categories,
            "total_expense": sum(item["total"] for item in categories),
            "chart_data": json.dumps(chart_data),
        },
    )

@login_required
def category_list(request):

    categories = (
        Category.objects
        .filter(created_by=request.user)
        .order_by("name")
    )

    return render(
        request,
        "expense/category/list.html",
        {
            "categories": categories
        }
    )

@login_required
def category_create(request):

    if request.method == "POST":

        form = CategoryForm(request.POST)

        if form.is_valid():

            category = form.save(commit=False)

            category.created_by = request.user

            category.save()

            messages.success(
                request,
                "Category created successfully."
            )

            return redirect("category-list")

    else:

        form = CategoryForm()

    return render(
        request,
        "expense/category/form.html",
        {
            "form": form,
            "title": "Create Category"
        }
    )

@login_required
def category_update(request, pk):

    category = get_object_or_404(
        Category,
        pk=pk,
        created_by=request.user,
    )

    if request.method == "POST":

        form = CategoryForm(
            request.POST,
            instance=category,
        )

        if form.is_valid():

            form.save()

            messages.success(
                request,
                "Category updated."
            )

            return redirect("category-list")

    else:

        form = CategoryForm(instance=category)

    return render(
        request,
        "expense/category/form.html",
        {
            "form": form,
            "title": "Update Category"
        }
    )

@login_required
def category_delete(request, pk):

    category = get_object_or_404(
        Category,
        pk=pk,
        created_by=request.user,
    )

    category.delete()

    messages.success(
        request,
        "Category deleted."
    )

    return redirect("category-list")

@login_required
def merchant_list(request):

    merchants = (
        Merchant.objects
        .filter(created_by=request.user)
        .order_by("name")
    )

    return render(
        request,
        "expense/merchant/list.html",
        {
            "merchants": merchants
        }
    )

@login_required
def merchant_create(request):

    if request.method == "POST":

        form = MerchantForm(request.POST)

        if form.is_valid():

            merchant = form.save(commit=False)

            merchant.created_by = request.user

            merchant.save()

            messages.success(
                request,
                "Merchant created."
            )

            return redirect("merchant-list")

    else:

        form = MerchantForm()

    return render(
        request,
        "expense/merchant/form.html",
        {
            "form": form,
            "title": "Create Merchant"
        }
    )

@login_required
def merchant_update(request, pk):

    merchant = get_object_or_404(
        Merchant,
        pk=pk,
        created_by=request.user,
    )

    if request.method == "POST":

        form = MerchantForm(
            request.POST,
            instance=merchant,
        )

        if form.is_valid():

            form.save()

            messages.success(
                request,
                "Merchant updated."
            )

            return redirect("merchant-list")

    else:

        form = MerchantForm(
            instance=merchant
        )

    return render(
        request,
        "expense/merchant/form.html",
        {
            "form": form,
            "title": "Update Merchant"
        }
    )

@login_required
def merchant_delete(request, pk):

    merchant = get_object_or_404(
        Merchant,
        pk=pk,
        created_by=request.user,
    )

    merchant.delete()

    messages.success(
        request,
        "Merchant deleted."
    )

    return redirect("merchant-list")