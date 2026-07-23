from datetime import date
from decimal import Decimal
import json
import csv
import logging
from calendar import month_abbr
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import DecimalField, Sum, Case, When, F
from django.shortcuts import (
    render,
    redirect,
    get_object_or_404,
)
from django.http import HttpResponse

from .models import (
    Account,
    Category,
    EntryType,
    Merchant,
    Transaction,
    TransactionItem,
    Transfer,
    Budget,
    ExpenseGroup,
)

from .forms import (
    AccountForm,
    CategoryForm,
    MerchantForm,
    ReceiptUploadForm,
    TransactionForm,
    TransactionsUploadForm,
    TransferForm,
    BudgetForm,
    ExpenseGroupForm,
    TransactionItemFormSet,
    SettlementForm,
)

from django.contrib.auth.forms import UserCreationForm

from .services import (
    BulkTransactionUploadService,
    BudgetService,
    DashboardService,
    GroupService,
    ReceiptService,
    ServiceError,
    TransactionService,
    TransferService,
    SettlementService,
)
from .validators import validate_file_upload, log_security_event

logger = logging.getLogger(__name__)
_RESERVED_LOG_RECORD_KEYS = frozenset(logging.makeLogRecord({}).__dict__.keys())


def _safe_log_extra(extra):
    if not extra:
        return None

    sanitized = {}
    for key, value in extra.items():
        safe_key = str(key)
        if safe_key in _RESERVED_LOG_RECORD_KEYS:
            safe_key = f"ctx_{safe_key}"
        sanitized[safe_key] = value
    return sanitized


def _log_info(message, **extra):
    logger.info(message, extra=_safe_log_extra(extra))


def _log_warning(message, **extra):
    logger.warning(message, extra=_safe_log_extra(extra))


def _log_error(message, *, exc_info=False, **extra):
    logger.error(message, extra=_safe_log_extra(extra), exc_info=exc_info)


def _log_exception(message, **extra):
    logger.exception(message, extra=_safe_log_extra(extra))


def _request_context(request):
    return {
        "user_id": getattr(request.user, "id", None),
        "username": getattr(request.user, "username", None),
        "path": request.path,
        "method": request.method,
    }


def _logger_for_message_level(level):
    if level >= messages.ERROR:
        return logger.error
    if level == messages.WARNING:
        return logger.warning
    return logger.info


def _flash_message(request, level, message, *, extra=None, exc_info=False):
    messages.add_message(request, level, message)
    log_fn = _logger_for_message_level(level)
    log_fn(
        "Flash message emitted",
        extra=_safe_log_extra({
            **_request_context(request),
            "flash_level": level,
            "flash_message": str(message),
            **(extra or {}),
        }),
        exc_info=exc_info,
    )


def _flash_error(request, message, *, extra=None, exc_info=False):
    _flash_message(request, messages.ERROR, message, extra=extra, exc_info=exc_info)


def _flash_warning(request, message, *, extra=None):
    _flash_message(request, messages.WARNING, message, extra=extra)


def _flash_success(request, message, *, extra=None):
    _flash_message(request, messages.SUCCESS, message, extra=extra)


def _form_error_list(form):
    return [
        f"{field}: {', '.join(errs)}"
        for field, errs in form.errors.items()
    ]


def _collect_transaction_items(formset):
    items = []

    for item_form in formset:
        if not item_form.cleaned_data:
            continue

        if item_form.cleaned_data.get("DELETE"):
            continue

        quantity = item_form.cleaned_data["quantity"]
        unit_price = item_form.cleaned_data["unit_price"]
        item_total = quantity * unit_price

        items.append({
            "name": item_form.cleaned_data["name"],
            "quantity": quantity,
            "unit_price": unit_price,
            "total_price": item_total,
        })

    return items


def _transaction_fields_from_form(form):
    return {
        "category": form.cleaned_data["category"],
        "merchant": form.cleaned_data.get("merchant"),
        "transaction_date": form.cleaned_data["transaction_date"],
        "description": form.cleaned_data["description"],
        "account": form.cleaned_data["account"],
        "amount": form.cleaned_data["amount"],
        "refund": form.cleaned_data.get("refund"),
    }


def health_check(request):
    return HttpResponse("OK", content_type="text/plain")

def signup(request):

    if request.method == "POST":

        form = UserCreationForm(
            request.POST
        )

        if form.is_valid():

            form.save()

            _flash_success(
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


@login_required
def receipt_upload(request):
    if request.method != "POST":
        _log_warning("Receipt upload rejected: invalid method", **_request_context(request))
        _flash_error(request, "Method not allowed.")
        return redirect("transaction-list")

    form = ReceiptUploadForm(
        request.POST,
        request.FILES,
    )

    if not form.is_valid():
        errors = _form_error_list(form)
        _log_warning(
            "Receipt upload form validation failed",
            **_request_context(request),
            form_errors=errors,
        )
        for error in errors:
            _flash_error(
                request,
                error,
                extra={
                    "event": "receipt_upload_form_validation_error",
                    "form_error": error,
                },
            )
        return redirect("transaction-list")

    try:
        receipt_file = form.cleaned_data["receipt"]
        _log_info(
            "Receipt upload started",
            **_request_context(request),
            upload_filename=receipt_file.name,
            size=getattr(receipt_file, "size", None),
        )

        is_valid, error_msg = validate_file_upload(
            receipt_file,
            allowed_extensions={"png", "jpg", "jpeg", "pdf"},
        )

        if not is_valid:
            detail = f"File upload error: {error_msg}"
            _log_warning(
                "Receipt upload file validation failed",
                **_request_context(request),
                upload_filename=receipt_file.name,
                detail=detail,
            )
            log_security_event("suspicious_receipt_upload", request, error_msg)
            _flash_error(request, detail)
            return redirect("transaction-list")

        payload = ReceiptService.extract(
            receipt=receipt_file,
        )

        request.session["transaction_initial"] = {
            "form": {
                "amount": payload["amount"],
                "transaction_date": payload["transaction_date"],
                "description": payload["description"],
            },
            "items": payload["items"],
        }

        _log_info(
            "Receipt processed successfully",
            **_request_context(request),
            upload_filename=receipt_file.name,
            item_count=len(payload.get("items", [])),
        )
        _flash_success(request, "Receipt processed successfully.")
        return redirect("transaction-create")

    except ServiceError as exc:
        _log_error("Receipt upload service error", exc_info=True, **_request_context(request))
        detail = f"Error processing receipt: {str(exc)}"
        _flash_error(request, detail, exc_info=True)
        return redirect("transaction-list")
    except Exception as exc:
        _log_exception("Receipt upload unexpected error", **_request_context(request))
        detail = f"Unexpected error processing receipt: {str(exc)}"
        _flash_error(request, detail, exc_info=True)
        return redirect("transaction-list")


@login_required
def transactions_upload(request):
    if request.method != "POST":
        _log_warning("Transactions upload rejected: invalid method", **_request_context(request))
        _flash_error(request, "Method not allowed.")
        return redirect("transaction-list")

    form = TransactionsUploadForm(
        request.POST,
        request.FILES,
    )

    if not form.is_valid():
        errors = _form_error_list(form)
        _log_warning(
            "Transactions upload form validation failed",
            **_request_context(request),
            form_errors=errors,
        )
        for error in errors:
            _flash_error(
                request,
                error,
                extra={
                    "event": "transactions_upload_form_validation_error",
                    "form_error": error,
                },
            )
        return redirect("transaction-list")

    try:
        csv_file = form.cleaned_data["csv_file"]
        _log_info(
            "Transactions upload started",
            **_request_context(request),
            upload_filename=csv_file.name,
            size=getattr(csv_file, "size", None),
        )

        is_valid, error_msg = validate_file_upload(
            csv_file,
            allowed_extensions={"csv"},
        )

        if not is_valid:
            detail = f"File upload error: {error_msg}"
            _log_warning(
                "Transactions upload file validation failed",
                **_request_context(request),
                upload_filename=csv_file.name,
                detail=detail,
            )
            log_security_event("suspicious_csv_upload", request, detail)
            _flash_error(request, detail)
            return redirect("transaction-list")

        service = BulkTransactionUploadService()
        result = service.upload(
            user=request.user,
            file=csv_file,
        )

        if result["success"]:
            _log_info(
                "Transactions upload completed",
                **_request_context(request),
                created=result.get("created", 0),
                failed=result.get("failed", 0),
            )
            _flash_success(
                request,
                f"Successfully created {result['created']} transactions.",
            )
        else:
            _log_warning(
                "Transactions upload completed with failures",
                **_request_context(request),
                created=result.get("created", 0),
                failed=result.get("failed", 0),
                errors=result.get("errors", []),
            )
            _flash_warning(
                request,
                f"Created {result['created']} transactions. Failed: {result['failed']}.",
            )
            for error in result.get("errors", []):
                _flash_error(
                    request,
                    error,
                    extra={
                        "event": "transactions_upload_processing_error",
                        "error": error,
                    },
                )

        return redirect("transaction-list")

    except ServiceError as exc:
        _log_error("Transactions upload service error", exc_info=True, **_request_context(request))
        detail = f"Upload failed: {str(exc)}"
        _flash_error(request, detail, exc_info=True)
        return redirect("transaction-list")

    except Exception as exc:
        _log_exception("Transactions upload unexpected error", **_request_context(request))
        detail = f"Unexpected error during upload: {str(exc)}"
        _flash_error(request, detail, exc_info=True)
        return redirect("transaction-list")


# ============================================================
# DASHBOARD
# ============================================================

@login_required
def dashboard(request):
    _log_info("Rendering dashboard", user_id=request.user.id, path=request.path)

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
        "receipt_upload_form": ReceiptUploadForm(),
        "transactions_upload_form": TransactionsUploadForm(),
        "export_accounts": Account.objects.filter(
            user=request.user,
            is_active=True,
        ).only("id", "name").order_by("name"),
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
        (
            -account.current_balance
            if account.account_type == Account.AccountType.CREDIT_CARD
            else account.current_balance
            for account in accounts
        ),
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

        form = AccountForm(request.POST, user=request.user)

        if form.is_valid():

            account = form.save(
                commit=False
            )

            account.user = request.user
            account.current_balance = (
                account.opening_balance
            )

            account.save()

            _flash_success(
                request,
                "Account created successfully."
            )

            return redirect(
                "account-list"
            )

    else:

        form = AccountForm(user=request.user)

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
    _log_info("Rendering transaction list", user_id=request.user.id, path=request.path)

    transactions = (
        Transaction.objects
        .select_related(
            "account",
            "category",
            "merchant",
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
            "receipt_upload_form": ReceiptUploadForm(),
            "transactions_upload_form": TransactionsUploadForm(),
            "export_accounts": Account.objects.filter(
                user=request.user,
                is_active=True,
            ).only("id", "name").order_by("name"),
        },
    )

def _get_transaction_initial(request):

    return request.session.pop(
        "transaction_initial",
        None,
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

            items = _collect_transaction_items(formset)

            if not items:
                items = [{
                    "name": "Item",
                    "quantity": 1,
                    "unit_price": form.cleaned_data["amount"],
                    "total_price": form.cleaned_data["amount"],
                }]
            try:
                shared = {
                    "user": request.user,
                    "tags": form.cleaned_data["tags"],
                    **_transaction_fields_from_form(form),
                }
                TransactionService.create_transaction(
                    items=items,
                    **shared,
                )
            except ServiceError as exc:
                _flash_error(request, str(exc), exc_info=True)
            else:
                _flash_success(request, "Transaction created.")
                return redirect("transaction-list")

    else:
        initial = _get_transaction_initial(request)

        if initial:

            form = TransactionForm(
                user=request.user,
                initial=initial["form"],
            )
            TransactionItemFormSet.extra = max(0, len(initial["items"]) - 1)
            formset = TransactionItemFormSet(
                queryset=TransactionItem.objects.none(),
                prefix="items",
                initial=initial["items"],
            )

        else:

            form = TransactionForm(
                user=request.user,
            )

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

            items = _collect_transaction_items(formset)

            if not items:
                _flash_error(request, "Add at least one item.")
            else:
                try:
                    TransactionService.update_transaction(
                        transaction_obj=transaction,
                        items=items,
                        tags=form.cleaned_data["tags"],
                        **_transaction_fields_from_form(form),
                    )
                except ServiceError as exc:
                    _flash_error(request, str(exc), exc_info=True)
                else:
                    _flash_success(request, "Transaction updated.")
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
def transfer_create(request):

    if request.method == "POST":

        form = TransferForm(
            request.POST,
            user=request.user,
        )

        if form.is_valid():

            try:

                TransferService.create_transfer(
                    user=request.user,
                    **form.cleaned_data,
                )

            except ServiceError as exc:

                _flash_error(request, str(exc), exc_info=True)

            else:

                _flash_success(
                    request,
                    "Transfer created."
                )

                return redirect(
                    "transfer-list"
                )

    else:

        form = TransferForm(
            user=request.user
        )

    return render(
        request,
        "expense/transfer/form.html",
        {
            "form": form,
            "is_edit": False,
        },
    )

@login_required
def transfer_update(request, pk):

    transfer = get_object_or_404(
        Transfer,
        pk=pk,
        user=request.user,
        is_deleted=False,
    )

    if request.method == "POST":

        form = TransferForm(
            request.POST,
            user=request.user,
        )

        if form.is_valid():

            try:

                TransferService.update_transfer(
                    transfer=transfer,
                    **form.cleaned_data,
                )

            except ServiceError as exc:

                _flash_error(
                    request,
                    str(exc),
                    exc_info=True,
                )

            else:

                _flash_success(
                    request,
                    "Transfer updated.",
                )

                return redirect(
                    "transfer-list",
                )

    else:

        form = TransferForm(
            initial={
                "from_account": transfer.from_account,
                "to_account": transfer.to_account,
                "amount": transfer.amount,
                "transaction_date": transfer.transaction_date,
                "notes": transfer.notes,
            },
            user=request.user,
        )

    return render(
        request,
        "expense/transfer/form.html",
        {
            "form": form,
            "transfer": transfer,
            "is_edit": True,
        },
    )

@login_required
def transfer_delete(request, pk):

    transfer = get_object_or_404(
        Transfer,
        pk=pk,
        user=request.user,
        is_deleted=False,
    )

    try:

        TransferService.delete_transfer(
            transfer
        )

    except ServiceError as exc:

        _flash_error(
            request,
            str(exc),
            exc_info=True,
        )

    else:

        _flash_success(
            request,
            "Transfer deleted.",
        )

    return redirect(
        "transfer-list"
    )

@login_required
def transfer_list(request):

    transfers = (
        Transfer.objects
        .select_related(
            "debit_transaction__account",
            "credit_transaction__account",
        )
        .filter(
            user=request.user,
            is_deleted=False,
        )
        .order_by(
            "-created_at",
        )
    )

    return render(
        request,
        "expense/transfer/list.html",
        {
            "transfers": transfers,
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

    _flash_success(
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

            _flash_success(request, "Budget created.")
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
            _flash_success(request, "Budget updated.")
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
    _flash_success(request, "Budget deleted.")
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

            _flash_success(
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
def settlement_create(request, pk):

    group = get_object_or_404(
        ExpenseGroup,
        pk=pk,
    )

    if request.method == "POST":

        form = SettlementForm(
            request.POST,
            group=group,
        )

        if form.is_valid():

            try:

                SettlementService.settle(
                    group=group,
                    payer=request.user,
                    receiver=form.cleaned_data["receiver"],
                    amount=form.cleaned_data["amount"],
                    notes=form.cleaned_data["notes"],
                )

            except ServiceError as exc:

                _flash_error(
                    request,
                    str(exc),
                    exc_info=True,
                )

            else:

                _flash_success(
                    request,
                    "Settlement completed successfully.",
                )

                return redirect(
                    "group-detail",
                    pk=group.pk,
                )

    else:

        form = SettlementForm(
            group=group,
        )

    return render(
        request,
        "expense/group/settlement.html",
        {
            "form": form,
            "group": group,
            "payer": request.user,
        },
    )

# ============================================================
# REPORTS
# ============================================================

@login_required
def monthly_report(request):
    base_queryset = (
        Transaction.objects
        .filter(
            user=request.user,
            is_deleted=False,
        )
        .exclude(category__category_type=Category.CategoryType.TRANSFER)
    )

    month_options = [
        {
            "value": month_start.strftime("%Y-%m"),
            "label": month_start.strftime("%b %Y"),
        }
        for month_start in base_queryset.dates("transaction_date", "month", order="DESC")
    ]

    current_month_value = date.today().strftime("%Y-%m")
    requested_month_value = request.GET.get("month")
    try:
        selected_month_value = (
            requested_month_value
            if requested_month_value
            else current_month_value
        )
        selected_month_date = date.fromisoformat(f"{selected_month_value}-01")
    except ValueError:
        selected_month_value = current_month_value
        selected_month_date = date.fromisoformat(f"{selected_month_value}-01")

    if not any(option["value"] == selected_month_value for option in month_options):
        month_options.insert(
            0,
            {
                "value": selected_month_value,
                "label": selected_month_date.strftime("%b %Y"),
            },
        )

    data = list(
        base_queryset
        .filter(
            transaction_date__month=selected_month_date.month,
            transaction_date__year=selected_month_date.year,
        )
        .values(
            "category__name",
            "category__category_type",
        )
        .annotate(
            total=Sum(
                    Case(
                        When(entry_type=EntryType.CREDIT, then=-F("amount")),
                        default=F("amount"),
                        output_field=DecimalField(),
                    )
                )
            )
        .order_by("-total")
    )
    chart_data = [
        {
            "name": item["category__name"] or "Uncategorized",
            "type": item["category__category_type"],
            "total": float(item["total"] or 0),
        }
        for item in data
    ]
    return render(
        request,
        "expense/reports/monthly.html",
        {
            "data": data,
            "total_expense": sum(item["total"] for item in data if item["category__category_type"] == Category.CategoryType.EXPENSE),
            "total_income": abs(sum(item["total"] for item in data if item["category__category_type"] == Category.CategoryType.INCOME)),
            "chart_data": json.dumps(chart_data),
            "month_options": month_options,
            "selected_month": selected_month_value,
            "selected_month_label": selected_month_date.strftime("%b %Y"),
        },
    )


@login_required
def category_report(request):

    categories = list(
        Transaction.objects
        .filter(
            user=request.user,
            is_deleted=False,
        )
        .exclude(category__category_type=Category.CategoryType.TRANSFER)
        .values(
            "category__name",
            "category__category_type",
        )
        .annotate(
            total=Sum(
                    Case(
                        When(entry_type=EntryType.CREDIT, then=-F("amount")),
                        default=F("amount"),
                        output_field=DecimalField(),
                    )
                )
            )
        .order_by("-total")
    )

    chart_data = [
        {
            "name": item["category__name"] or "Uncategorized",
            "total": float(item["total"] or 0),
            "type": item["category__category_type"],
        }
         for item in categories
    ]    
    print(chart_data)
    return render(
        request,
        "expense/reports/category.html",
        {
            "categories": categories,
            "total_expense": sum(item["total"] for item in categories if item["category__category_type"] == Category.CategoryType.EXPENSE),
            "total_income": abs(sum(item["total"] for item in categories if item["category__category_type"] == Category.CategoryType.INCOME)),
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

        form = CategoryForm(request.POST, request.user)

        if form.is_valid():

            category = form.save(commit=False)

            category.created_by = request.user

            category.save()

            _flash_success(
                request,
                "Category created successfully."
            )

            return redirect("category-list")

    else:

        form = CategoryForm(user = request.user)

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
            user = request.user
        )

        if form.is_valid():

            form.save()

            _flash_success(
                request,
                "Category updated."
            )

            return redirect("category-list")

    else:

        form = CategoryForm(instance=category, user = request.user)

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

    _flash_success(
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

            _flash_success(
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

            _flash_success(
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

    _flash_success(
        request,
        "Merchant deleted."
    )

    return redirect("merchant-list")


# ============================================================
# DATA EXPORT / IMPORT
# ============================================================

@login_required
def transaction_export(request):
    """Export transactions as CSV."""
    _log_info(
        "Exporting transactions",
        user_id=request.user.id,
        start_date=request.GET.get('start_date'),
        end_date=request.GET.get('end_date'),
        account=request.GET.get('account'),
    )
    
    # Start with user's transactions
    queryset = Transaction.objects.filter(user=request.user).select_related(
        'account', 'category', 'merchant'
    ).order_by('-transaction_date')
    
    # Filter by date range if provided
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    if start_date:
        queryset = queryset.filter(transaction_date__gte=start_date)
    
    if end_date:
        queryset = queryset.filter(transaction_date__lte=end_date)
    
    # Filter by account if provided
    account_id = request.GET.get('account')
    if account_id:
        queryset = queryset.filter(account_id=account_id)
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="transactions-{date.today().isoformat()}.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Date', 'Account', 'Category', 'Merchant', 'Amount', 'Type', 'Description'
    ])
    
    for txn in queryset:
        writer.writerow([
            txn.transaction_date.strftime('%Y-%m-%d'),
            txn.account.name,
            txn.category.name,
            txn.merchant.name if txn.merchant else '',
            f'{txn.amount:.2f}',
            txn.entry_type,
            txn.description,
        ])
    
    _log_info(
        "Transactions export completed",
        user_id=request.user.id,
        count=queryset.count(),
    )
    return response


@login_required
def account_json(request):
    """Return accounts as JSON for JavaScript."""
    accounts = Account.objects.filter(user=request.user).values('id', 'name')
    
    return HttpResponse(
        json.dumps(list(accounts)),
        content_type='application/json'
    )