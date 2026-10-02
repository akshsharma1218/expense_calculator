from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO
import json
import csv
import logging
from calendar import month_abbr
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import DecimalField, ProtectedError, Sum, Case, When, F, Q
from django.db import transaction as db_transaction
from django.shortcuts import (
    render,
    redirect,
    get_object_or_404,
)
from django.utils import timezone
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST

from .models import (
    Account,
    Category,
    EntryType,
    Merchant,
    Transaction,
    Transfer,
    Budget,
    ExpenseGroup,
    GroupExpense,
    GroupExpenseSplit,
    GroupInvitation,
    FavoriteDescription,
    Settlement,
    UserNotification,
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
    GroupInvitationForm,
    SettlementForm,
    SettlementReceiptForm,
    QuickTransactionForm,
    FavoriteDescriptionForm,
    SplitTransactionForm,
    AccountCSVUploadForm,
)

from django.contrib.auth.forms import UserCreationForm

from .services import (
    BulkTransactionUploadService,
    BudgetService,
    DashboardService,
    GroupInvitationService,
    GroupService,
    ReceiptService,
    ServiceError,
    TextTransactionService,
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


def _transaction_fields_from_form(form):
    return {
        "category": form.cleaned_data["category"],
        "merchant": form.cleaned_data.get("merchant"),
        "transaction_date": form.cleaned_data["transaction_date"],
        "description": form.cleaned_data["description"],
        "account": form.cleaned_data["account"],
        "amount": -form.cleaned_data["amount"] if form.amount_is_negative else form.cleaned_data["amount"],
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
def text_transaction_input(request):
    if request.method != "POST":
        _log_warning("Text input rejected: invalid method", **_request_context(request))
        return redirect("transaction-list")

    text = request.POST.get("text", "").strip()
    if not text:
        _flash_error(request, "Please enter transaction details.")
        return redirect("transaction-list")

    try:
        payload = TextTransactionService.extract(text=text)
        request.session["transaction_initial"] = {
            "form": {
                "amount": payload["amount"],
                "transaction_date": payload["transaction_date"],
                "description": payload["description"],
            },
            "items": payload["items"],
        }
        _log_info(
            "Text transaction parsed successfully",
            **_request_context(request),
            amount=payload["amount"],
            item_count=len(payload.get("items", [])),
        )
        _flash_success(request, "Transaction parsed. Review and save.")
        return redirect("transaction-create")
    except ServiceError as exc:
        _log_error("Text transaction service error", exc_info=True, **_request_context(request))
        _flash_error(request, f"Error parsing transaction: {str(exc)}", exc_info=True)
        return redirect("transaction-list")
    except Exception as exc:
        _log_exception("Text transaction unexpected error", **_request_context(request))
        _flash_error(request, f"Unexpected error: {str(exc)}", exc_info=True)
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

    quick_add_form = QuickTransactionForm(user=request.user)
    quick_add_ready = quick_add_form.fields["favorite"].queryset.exists()

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "quick_add":
            form = QuickTransactionForm(request.POST, user=request.user)
            if not quick_add_ready:
                _flash_error(request, "Create a favorite with an active account and category before using quick add.")
            elif form.is_valid():
                try:
                    favorite = form.cleaned_data["favorite"]
                    TransactionService.create_transaction(
                        user=request.user,
                        account=favorite.account,
                        category=favorite.category,
                        merchant=favorite.merchant,
                        amount=form.cleaned_data["amount"],
                        description=favorite.description or favorite.name,
                        transaction_date=timezone.localdate(),
                    )
                except ServiceError as exc:
                    _flash_error(request, str(exc), exc_info=True)
                else:
                    _flash_success(request, "Transaction added.")
                    return redirect("dashboard")
            else:
                for errors in form.errors.values():
                    for error in errors:
                        _flash_error(request, error)
            return redirect("dashboard")

    today = date.today()

    monthly_trend = DashboardService.monthly_trend(user=request.user)
    category_breakdown = DashboardService.category_breakdown(
        user=request.user,
        month=today.month,
        year=today.year,
    )
    account_distribution = DashboardService.account_distribution(user=request.user)

    context = {
        "quick_add_form": quick_add_form,
        "quick_add_ready": quick_add_ready,
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
        "owed_amount": DashboardService.owed_amount(user=request.user),
        "lent_amount": DashboardService.lent_amount(user=request.user),
        "recent_transactions": DashboardService.recent_transactions(
            user=request.user
        ),
        "chart_monthly_trend": json.dumps(monthly_trend),
        "chart_category_breakdown": json.dumps(category_breakdown),
        "chart_account_distribution": json.dumps(account_distribution),
        "chart_item_breakdown": json.dumps(DashboardService.item_breakdown(user=request.user, month=today.month, year=today.year)),
        "chart_timeline_breakdown": json.dumps(DashboardService.timeline_breakdown(user=request.user, months=6)),
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


@login_required
def favorite_list(request):
    favorites = FavoriteDescription.objects.filter(user=request.user).order_by("name")
    create_form = FavoriteDescriptionForm(user=request.user)
    edit_form = None
    editing_favorite_id = None

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create":
            create_form = FavoriteDescriptionForm(request.POST, user=request.user)
            if create_form.is_valid():
                favorite = create_form.save(commit=False)
                favorite.user = request.user
                favorite.save()
                create_form.save_m2m()
                _flash_success(request, "Favorite created.")
                return redirect("favorite-list")
        elif action == "update":
            favorite = get_object_or_404(
                favorites,
                pk=request.POST.get("favorite_id"),
            )
            edit_form = FavoriteDescriptionForm(
                request.POST,
                instance=favorite,
                user=request.user,
                prefix=str(favorite.pk),
            )
            editing_favorite_id = str(favorite.pk)
            if edit_form.is_valid():
                edit_form.save()
                _flash_success(request, "Favorite updated.")
                return redirect("favorite-list")
        elif action == "delete":
            favorite = get_object_or_404(
                favorites,
                pk=request.POST.get("favorite_id"),
            )
            favorite.delete()
            _flash_success(request, "Favorite deleted.")
            return redirect("favorite-list")

    favorite_rows = [
        {
            "favorite": favorite,
            "form": edit_form if editing_favorite_id == str(favorite.pk) else FavoriteDescriptionForm(instance=favorite, user=request.user, prefix=str(favorite.pk)),
            "is_editing": editing_favorite_id == str(favorite.pk),
        }
        for favorite in favorites
    ]
    return render(
        request,
        "expense/favorites.html",
        {
            "favorite_rows": favorite_rows,
            "favorite_form": create_form,
        },
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
        )
        .exclude(account_type=Account.AccountType.INVESTMENT)
        .only("id", "name", "account_type", "opening_balance", "current_balance", "created_at")
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
            "account_upload_form": AccountCSVUploadForm(),
        },
    )


@login_required
def account_template_download(request):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="accounts-template.csv"'
    writer = csv.writer(response)
    writer.writerow(["name", "account_type", "opening_balance"])
    writer.writerow(["Everyday Wallet", "wallet", "0.00"])
    return response


@login_required
def account_upload(request):
    if request.method != "POST":
        return redirect("account-list")

    form = AccountCSVUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        for error in _form_error_list(form):
            _flash_error(request, error)
        return redirect("account-list")

    try:
        content = form.cleaned_data["csv_file"].read().decode("utf-8-sig")
        reader = csv.DictReader(StringIO(content))
    except (UnicodeDecodeError, csv.Error):
        _flash_error(request, "The account CSV must be a valid UTF-8 CSV file.")
        return redirect("account-list")

    if not reader.fieldnames:
        _flash_error(request, "The account CSV is missing its header row.")
        return redirect("account-list")

    reader.fieldnames = [(header or "").strip().lower() for header in reader.fieldnames]
    required = {"name", "account_type", "opening_balance"}
    missing = required - set(reader.fieldnames)
    if missing:
        _flash_error(request, f"Missing CSV columns: {', '.join(sorted(missing))}.")
        return redirect("account-list")

    valid_types = {value for value, _label in Account.AccountType.choices}
    existing_names = {
        name.casefold()
        for name in Account.objects.filter(user=request.user).values_list("name", flat=True)
    }
    seen_names = set()
    new_accounts = []
    errors = []
    for line_number, row in enumerate(reader, start=2):
        values = {(key or "").strip().lower(): (value or "").strip() for key, value in row.items()}
        if not any(values.values()):
            continue
        error_count = len(errors)
        name = values.get("name", "")
        account_type = values.get("account_type", "").casefold().replace(" ", "_")
        raw_balance = values.get("opening_balance", "")
        if not name:
            errors.append(f"Row {line_number}: account name is required.")
        elif len(name) > 100:
            errors.append(f"Row {line_number}: account name must be 100 characters or fewer.")
        elif name.casefold() in existing_names or name.casefold() in seen_names:
            errors.append(f"Row {line_number}: account '{name}' already exists.")
        if account_type not in valid_types:
            errors.append(f"Row {line_number}: invalid account type '{account_type}'.")
        try:
            opening_balance = Decimal(raw_balance)
            if not opening_balance.is_finite() or opening_balance < 0:
                raise InvalidOperation
        except (InvalidOperation, TypeError, ValueError):
            errors.append(f"Row {line_number}: opening balance must be a non-negative amount.")
            opening_balance = None
        if len(errors) == error_count:
            seen_names.add(name.casefold())
            new_accounts.append(Account(
                user=request.user,
                name=name,
                account_type=account_type,
                opening_balance=opening_balance,
                current_balance=opening_balance,
            ))

    if errors:
        _flash_error(request, "No accounts were imported. " + " ".join(errors[:8]))
        return redirect("account-list")
    if not new_accounts:
        _flash_error(request, "The CSV contains no account rows to import.")
        return redirect("account-list")

    with db_transaction.atomic():
        Account.objects.bulk_create(new_accounts)
    _flash_success(request, f"Imported {len(new_accounts)} account(s).")
    return redirect("account-list")


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
            "is_group_expense",
        )
        .order_by(
            "-transaction_date",
            "-created_at",
        )
    )

    transaction_ids = [transaction.pk for transaction in transactions]
    split_transaction_ids = set(
        GroupExpense.objects.filter(
            transaction_id__in=transaction_ids,
        ).values_list("transaction_id", flat=True)
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
            "split_url": f"/transactions/{txn.id}/split/",
            "is_group_expense": txn.pk in split_transaction_ids,
            "is_expense": txn.entry_type == EntryType.DEBIT and txn.category.category_type != Category.CategoryType.TRANSFER,
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

        if form.is_valid():
            try:
                shared = {
                    "user": request.user,
                    **_transaction_fields_from_form(form),
                }
                TransactionService.create_transaction(
                    **shared,
                )
            except ServiceError as exc:
                _flash_error(request, str(exc), exc_info=True)
            else:
                _flash_success(request, "Transaction created.")
                return redirect("transaction-list")

    else:
        initial = _get_transaction_initial(request)
        if not initial and request.GET.get("favorite"):
            favorite = get_object_or_404(
                FavoriteDescription.objects,
                pk=request.GET["favorite"],
                user=request.user,
            )
            initial = {
                "form": {
                    "description": favorite.name,
                    "account": favorite.account_id,
                    "category": favorite.category_id,
                    "merchant": favorite.merchant_id,
                },
                "items": [],
            }
        elif not initial and request.GET.get("description"):
            initial = {"form": {"description": request.GET["description"]}, "items": []}

        if initial:

            form = TransactionForm(
                user=request.user,
                initial=initial["form"],
            )

        else:

            form = TransactionForm(
                user=request.user,
            )

    return render(
        request,
        "expense/transaction/form.html",
        {
            "form": form,
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

        if form.is_valid():
            try:
                TransactionService.update_transaction(
                    transaction_obj=transaction,
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

    return render(
        request,
        "expense/transaction/form.html",
        {
            "form": form,
            "transaction": transaction,
            "is_edit": True,
        },
    )


def _create_transaction_split(transaction, user, form):
    group_members = {
        str(member.user_id): member.user
        for member in form.cleaned_data["group"].members.select_related("user")
    }
    custom_splits = [
        {"user": group_members[str(share["user_id"])], "amount": share["amount"]}
        for share in form.cleaned_data["custom_shares"]
        if share.get("selected", True)
    ] if form.cleaned_data["split_mode"] == "custom" else None
    return GroupService.split_existing_transaction(
        transaction_obj=transaction,
        group=form.cleaned_data["group"],
        paid_by=user,
        split_mode=form.cleaned_data["split_mode"],
        splits=custom_splits,
    )


@login_required
def transaction_split(request, pk):
    transaction = get_object_or_404(
        Transaction.objects.select_related("account", "category"),
        pk=pk,
        user=request.user,
        is_deleted=False,
    )
    group_expense = (
        GroupExpense.objects.filter(transaction=transaction)
        .prefetch_related("splits")
        .first()
    )
    initial = None
    existing_split_data = []
    if group_expense:
        existing_splits = list(group_expense.splits.select_related("user"))
        external_splits = [
            split for split in existing_splits
            if split.user_id != group_expense.paid_by_id
        ]
        initial = {
            "group": group_expense.group_id,
            "split_mode": "custom" if external_splits else "equal",
        }
        if external_splits:
            initial["selected_members"] = [
                str(split.user_id) for split in external_splits
            ]
            for split in external_splits:
                initial[f"share_{split.user_id}"] = split.share_amount
        existing_split_data = [
            {"user_id": str(split.user_id), "amount": str(split.share_amount)}
            for split in external_splits
        ]
    form_data = request.POST or None
    if group_expense and request.method == "POST":
        form_data = request.POST.copy()
        form_data["group"] = str(group_expense.group_id)
    form = SplitTransactionForm(
        form_data,
        user=request.user,
        transaction=transaction,
        initial=initial,
    )
    if group_expense:
        form.fields["group"].disabled = True
        if request.method == "POST" and request.POST.get("split_mode") == "custom":
            selected_ids = request.POST.getlist("selected_members")
            existing_split_data = [
                {
                    "user_id": member_id,
                    "amount": request.POST.get(f"share_{member_id}", ""),
                }
                for member_id in selected_ids
            ]
    if request.method == "POST" and form.is_valid():
        try:
            if group_expense:
                group_members = {
                    str(member.user_id): member.user
                    for member in form.cleaned_data["group"].members.select_related("user")
                }
                custom_splits = [
                    {
                        "user": group_members[share["user_id"]],
                        "amount": share["amount"],
                    }
                    for share in form.cleaned_data["custom_shares"]
                ] if form.cleaned_data["split_mode"] == "custom" else None
                GroupService.update_split_expense(
                    transaction_obj=transaction,
                    group=form.cleaned_data["group"],
                    paid_by=request.user,
                    split_mode=form.cleaned_data["split_mode"],
                    splits=custom_splits,
                )
            else:
                _create_transaction_split(transaction, request.user, form)
        except ServiceError as exc:
            form.add_error(None, str(exc))
        else:
            _flash_success(
                request,
                "Transaction split updated." if group_expense else "Transaction split added.",
            )
            return redirect("transaction-list")

    group_member_data = [
        {
            "id": str(group.pk),
            "members": [
                {
                    "id": str(member.user_id),
                    "name": member.user.get_full_name().strip() or member.user.email,
                }
                for member in group.members.select_related("user")
            ],
        }
        for group in form.fields["group"].queryset.prefetch_related("members__user")
    ]
    return render(
        request,
        "expense/transaction/split.html",
        {
            "transaction": transaction,
            "form": form,
            "group_member_data": group_member_data,
            "existing_split_data": existing_split_data,
            "is_editing_split": group_expense is not None,
            "original_group_id": group_expense.group_id if group_expense else "",
        },
    )


@login_required
@require_POST
def transaction_split_api(request, pk):
    transaction = get_object_or_404(
        Transaction.objects.select_related("account", "category"),
        pk=pk,
        user=request.user,
        is_deleted=False,
    )
    try:
        payload = json.loads(request.body or b"{}")
    except (TypeError, ValueError):
        return JsonResponse({"errors": {"body": ["Request body must contain valid JSON."]}}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"errors": {"body": ["Request body must be a JSON object."]}}, status=400)

    form_data = {
        "group": payload.get("group_id", ""),
        "split_mode": payload.get("split_mode", ""),
    }
    paid_by_id = payload.get("paid_by_id")
    if paid_by_id not in (None, "", request.user.pk, str(request.user.pk)):
        return JsonResponse(
            {"errors": {"paid_by_id": [{"message": "The transaction owner is the payer."}]}},
            status=400,
        )
    if form_data["split_mode"] == "custom":
        shares = payload.get("splits", [])
        if not isinstance(shares, list):
            return JsonResponse({"errors": {"splits": [{"message": "Custom splits must be a list."}]}}, status=400)
        selected_ids = []
        seen_ids = set()
        legacy_payer_amount = None
        for share in shares:
            if not isinstance(share, dict):
                return JsonResponse({"errors": {"splits": [{"message": "Each split must identify a member and amount."}]}}, status=400)
            selected = share.get("selected", True)
            if not isinstance(selected, bool):
                return JsonResponse({"errors": {"splits": [{"message": "Selected must be true or false."}]}}, status=400)
            if not selected:
                continue
            raw_user_id = share.get("user_id")
            if isinstance(raw_user_id, bool) or not isinstance(raw_user_id, (str, int)):
                return JsonResponse({"errors": {"splits": [{"message": "Each split needs a valid member."}]}}, status=400)
            user_id = str(raw_user_id)
            if user_id in seen_ids:
                return JsonResponse({"errors": {"splits": [{"message": "A member can only be selected once."}]}}, status=400)
            seen_ids.add(user_id)
            if user_id == str(request.user.pk):
                legacy_payer_amount = share.get("amount", "")
                continue
            selected_ids.append(user_id)
            form_data[f"share_{user_id}"] = share.get("amount", "")
        form_data["selected_members"] = selected_ids
    else:
        legacy_payer_amount = None
    form = SplitTransactionForm(form_data, user=request.user, transaction=transaction)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors.get_json_data()}, status=400)
    if legacy_payer_amount is not None:
        try:
            submitted_payer_amount = Decimal(str(legacy_payer_amount))
        except (InvalidOperation, TypeError, ValueError):
            return JsonResponse(
                {"errors": {"splits": [{"message": "The payer's amount must be a valid number."}]}},
                status=400,
            )
        owed_total = sum(
            (Decimal(share["amount"]) for share in form.cleaned_data["custom_shares"]),
            Decimal("0.00"),
        )
        if submitted_payer_amount != Decimal(str(transaction.amount)) - owed_total:
            return JsonResponse(
                {"errors": {"splits": [{"message": "The payer's share is calculated from the remaining amount."}]}},
                status=400,
            )

    try:
        expense = _create_transaction_split(transaction, request.user, form)
    except ServiceError as exc:
        return JsonResponse({"errors": {"split": [{"message": str(exc)}]}}, status=400)

    return JsonResponse(
        {
            "expense_id": str(expense.pk),
            "transaction_id": str(transaction.pk),
            "group_id": str(expense.group_id),
            "paid_by_id": expense.paid_by_id,
            "shares": [
                {"user_id": share.user_id, "amount": str(share.share_amount)}
                for share in expense.splits.all()
            ],
        },
        status=201,
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
                "from_account": transfer.debit_transaction.account,
                "to_account": transfer.credit_transaction.account,
                "amount": transfer.amount,
                "transaction_date": transfer.debit_transaction.transaction_date,
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
        is_deleted=False,
    )

    try:
        TransactionService.delete_transaction(transaction)
    except ServiceError as exc:
        _flash_error(request, str(exc))
    else:
        _flash_success(request, "Transaction deleted.")

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

            group = GroupService.create_group(
                name=form.cleaned_data["name"],
                description=form.cleaned_data[
                    "description"
                ],
                created_by=request.user,
            )

            member_emails = [
                email.strip()
                for email in request.POST.getlist("members")
                if email.strip()
            ]

            invited_count = 0
            for email in member_emails:
                invited_user = get_user_model().objects.filter(email__iexact=email).first()
                if invited_user is None:
                    _flash_error(request, f"No user found with email {email}.")
                    continue
                try:
                    GroupInvitationService.invite_member(
                        group=group,
                        invited_user=invited_user,
                        invited_by=request.user,
                    )
                    invited_count += 1
                except ServiceError as exc:
                    _flash_error(request, str(exc))

            if invited_count:
                _flash_success(
                    request,
                    f"Group created. {invited_count} invite(s) sent."
                )
            else:
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
def invitation_list(request):

    invitations = (
        GroupInvitation.objects
        .filter(invited_user=request.user, status=GroupInvitation.Status.PENDING)
        .select_related("group", "invited_by")
        .order_by("-created_at")
    )

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({
            "invitations": [
                {
                    "id": str(invitation.id),
                    "group_name": invitation.group.name,
                    "invited_by": str(invitation.invited_by),
                    "created_at": invitation.created_at.isoformat(),
                }
                for invitation in invitations
            ]
        })

    return render(
        request,
        "expense/group/invitations.html",
        {
            "invitations": invitations
        },
    )


@login_required
def notification_list(request):
    now = timezone.now()
    UserNotification.objects.filter(
        user=request.user,
        expires_at__lte=now,
    ).delete()
    notifications = UserNotification.objects.filter(
        user=request.user,
        expires_at__gt=now,
    ).order_by("-created_at")[:50]
    return JsonResponse({
        "unread_count": UserNotification.objects.filter(
            user=request.user,
            expires_at__gt=now,
            is_read=False,
        ).count(),
        "notifications": [
            {
                **notification.data,
                "id": str(notification.pk),
                "event": notification.event,
                "message": notification.message,
                "created_at": notification.created_at.isoformat(),
                "expires_at": notification.expires_at.isoformat(),
                "is_read": notification.is_read,
            }
            for notification in notifications
        ]
    })


@login_required
@require_POST
def notification_mark_read(request, notification_id):
    notification = get_object_or_404(
        UserNotification,
        pk=notification_id,
        user=request.user,
        expires_at__gt=timezone.now(),
    )
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read", "updated_at"])
    unread_count = UserNotification.objects.filter(
        user=request.user,
        expires_at__gt=timezone.now(),
        is_read=False,
    ).count()
    return JsonResponse({"status": "ok", "unread_count": unread_count})


@login_required
@require_POST
def notification_mark_all_read(request):
    now = timezone.now()
    UserNotification.objects.filter(
        user=request.user,
        expires_at__gt=now,
        is_read=False,
    ).update(is_read=True, updated_at=now)
    return JsonResponse({"status": "ok", "unread_count": 0})


@login_required
@require_POST
def invitation_accept(request, pk):

    invitation = get_object_or_404(GroupInvitation, pk=pk, invited_user=request.user)

    try:
        GroupInvitationService.accept_invitation(invitation=invitation, user=request.user)
        _flash_success(request, f"You joined \"{invitation.group.name}\".")
    except ServiceError as exc:
        _flash_error(request, str(exc))

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"status": "ok"})

    return redirect("group-invitations")


@login_required
@require_POST
def invitation_decline(request, pk):

    invitation = get_object_or_404(GroupInvitation, pk=pk, invited_user=request.user)

    try:
        GroupInvitationService.decline_invitation(invitation=invitation, user=request.user)
        _flash_success(request, f"Invitation to \"{invitation.group.name}\" declined.")
    except ServiceError as exc:
        _flash_error(request, str(exc))

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"status": "ok"})

    return redirect("group-invitations")


@login_required
def group_detail(
    request,
    pk
):

    group = get_object_or_404(
        ExpenseGroup.objects.filter(members__user=request.user),
        pk=pk,
    )

    invite_form = GroupInvitationForm(request.POST or None)
    if request.method == "POST" and invite_form.is_valid():
        invited_user = get_user_model().objects.find_by_identifier(
            invite_form.cleaned_data["email"]
        )
        if invited_user is None:
            invite_form.add_error(
                "email",
                "No unique account matches that email, phone number, or username.",
            )
        else:
            try:
                GroupInvitationService.invite_member(
                    group=group,
                    invited_user=invited_user,
                    invited_by=request.user,
                )
            except ServiceError as exc:
                invite_form.add_error("email", str(exc))
            else:
                _flash_success(request, f"Invitation sent to {invited_user.email}.")
                return redirect("group-detail", pk=group.pk)

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

        "invite_form": invite_form,
    }

    return render(
        request,
        "expense/group/detail.html",
        context,
    )


@login_required
@require_POST
def group_delete(request, pk):
    group = get_object_or_404(
        ExpenseGroup,
        pk=pk,
        created_by=request.user,
    )
    try:
        GroupService.delete_group(group=group, deleted_by=request.user)
    except ServiceError as exc:
        _flash_error(request, str(exc))
        return redirect("group-detail", pk=group.pk)

    _flash_success(
        request,
        "Group and its group data were deleted. Personal transactions and account balances were preserved.",
    )
    return redirect("group-list")


def _settlement_page_context(
    *,
    group,
    user,
    bound_receiver_id=None,
    bound_form=None,
):
    splits = (
        GroupExpenseSplit.objects
        .filter(
            expense__group=group,
            user=user,
            status=GroupExpenseSplit.Status.PENDING,
        )
        .exclude(expense__paid_by=user)
        .select_related("expense__paid_by", "expense__transaction")
        .prefetch_related("settlement_allocations")
        .order_by("expense__paid_by__username", "created_at")
    )
    obligations_by_receiver = {}
    for split in splits:
        allocated = sum(
            (allocation.amount for allocation in split.settlement_allocations.all()),
            Decimal("0.00"),
        )
        outstanding = split.share_amount - allocated
        if outstanding <= 0:
            continue
        receiver = split.expense.paid_by
        obligation = obligations_by_receiver.setdefault(
            receiver.pk,
            {"receiver": receiver, "splits": [], "total": Decimal("0.00")},
        )
        obligation["splits"].append(
            {"split": split, "amount": outstanding}
        )
        obligation["total"] += outstanding

    obligations = []
    for receiver_id, obligation in obligations_by_receiver.items():
        form = (
            bound_form
            if str(receiver_id) == str(bound_receiver_id) and bound_form is not None
            else SettlementForm(
                group=group,
                payer=user,
                receiver=obligation["receiver"],
            )
        )
        obligation["form"] = form
        obligations.append(obligation)

    incoming_settlements = list(
        Settlement.objects
        .filter(
            group=group,
            receiver=user,
            receiver_transaction__isnull=True,
            is_completed=True,
        )
        .select_related("payer", "payer_transaction")
        .order_by("-created_at")
    )
    return {
        "group": group,
        "obligations": obligations,
        "incoming_payments": [
            {
                "settlement": settlement,
                "form": SettlementReceiptForm(user=user),
            }
            for settlement in incoming_settlements
        ],
    }


@login_required
def settlement_create(request, pk):
    group = get_object_or_404(
        ExpenseGroup.objects.filter(members__user=request.user),
        pk=pk,
    )
    return render(
        request,
        "expense/group/settlement.html",
        _settlement_page_context(group=group, user=request.user),
    )


@login_required
@require_POST
def settlement_pay(request, pk, receiver_id):
    group = get_object_or_404(
        ExpenseGroup.objects.filter(members__user=request.user),
        pk=pk,
    )
    receiver = get_object_or_404(
        group.members.select_related("user"),
        user_id=receiver_id,
    ).user
    form = SettlementForm(
        request.POST,
        group=group,
        payer=request.user,
        receiver=receiver,
    )
    if form.is_valid():
        try:
            SettlementService.settle(
                group=group,
                payer=request.user,
                receiver=receiver,
                account=form.cleaned_data["account"],
                split_ids=form.cleaned_data["selected_splits"],
                notes=form.cleaned_data["notes"],
            )
        except ServiceError as exc:
            form.add_error(None, str(exc))
        else:
            _flash_success(request, f"Payment to {receiver} recorded.")
            return redirect("group-settlement", pk=group.pk)

    return render(
        request,
        "expense/group/settlement.html",
        _settlement_page_context(
            group=group,
            user=request.user,
            bound_receiver_id=receiver.pk,
            bound_form=form,
        ),
        status=400,
    )


@login_required
@require_POST
def settlement_record_received(request, pk, settlement_id):
    group = get_object_or_404(
        ExpenseGroup.objects.filter(members__user=request.user),
        pk=pk,
    )
    settlement = get_object_or_404(
        Settlement,
        pk=settlement_id,
        group=group,
        receiver=request.user,
        is_completed=True,
        receiver_transaction__isnull=True,
    )
    form = SettlementReceiptForm(request.POST, user=request.user)
    if form.is_valid():
        try:
            SettlementService.record_received(
                settlement=settlement,
                receiver=request.user,
                account=form.cleaned_data["account"],
            )
        except ServiceError as exc:
            form.add_error(None, str(exc))
        else:
            _flash_success(request, "Received payment recorded in your account.")
            return redirect("group-settlement", pk=group.pk)

    context = _settlement_page_context(group=group, user=request.user)
    for payment in context["incoming_payments"]:
        if payment["settlement"].pk == settlement.pk:
            payment["form"] = form
            break
    return render(
        request,
        "expense/group/settlement.html",
        context,
        status=400,
    )


@login_required
@require_POST
def group_member_remove(request, pk, user_id):
    group = get_object_or_404(
        ExpenseGroup,
        pk=pk,
        created_by=request.user,
    )
    member = get_object_or_404(group.members.select_related("user"), user_id=user_id)
    try:
        GroupService.remove_member(
            group=group,
            user=member.user,
            removed_by=request.user,
        )
    except ServiceError as exc:
        _flash_error(request, str(exc))
    else:
        _flash_success(request, f"{member.user} was removed from the group.")
    return redirect("group-detail", pk=group.pk)

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

    current_month_value = timezone.localdate().strftime("%Y-%m")
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

    investment_list = list(
        Transaction.objects
            .filter(
                user=request.user,
                is_deleted=False,
                category__category_type=Category.CategoryType.TRANSFER,
                transaction_date__month=selected_month_date.month,
                transaction_date__year=selected_month_date.year,
                account__account_type=Account.AccountType.INVESTMENT,
            )
            .values(
                "account__name",
            )
            .annotate(
                total=Sum(
                        Case(
                            When(entry_type=EntryType.CREDIT, then=F("amount")),
                            default=-F("amount"),
                            output_field=DecimalField(),
                        )
                    )
                )
            .order_by("-total")
        )
    investment_data = [
        {
            "name": item["account__name"] or "Uncategorized",
            "total": float(item["total"] or 0),
        }
        for item in investment_list
    ]
    return render(
        request,
        "expense/reports/monthly.html",
        {
            "data": data,
            "has_report_data": bool(data or investment_data),
            "total_expense": sum(item["total"] for item in data if item["category__category_type"] == Category.CategoryType.EXPENSE),
            "total_income": abs(sum(item["total"] for item in data if item["category__category_type"] == Category.CategoryType.INCOME)),
            "investment_data": json.dumps(investment_data),
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

    investment_list = list(
        Transaction.objects
            .filter(
                user=request.user,
                is_deleted=False,
                category__category_type=Category.CategoryType.TRANSFER,
                account__account_type=Account.AccountType.INVESTMENT,
            )
            .values(
                "account__name",
            )
            .annotate(
                total=Sum(
                        Case(
                            When(entry_type=EntryType.CREDIT, then=F("amount")),
                            default=-F("amount"),
                            output_field=DecimalField(),
                        )
                    )
                )
            .order_by("-total")
        )
    investment_data = [
        {
            "name": item["account__name"] or "Uncategorized",
            "total": float(item["total"] or 0),
        }
        for item in investment_list
    ]

    return render(
        request,
        "expense/reports/category.html",
        {
            "categories": categories,
            "has_report_data": bool(categories or investment_data),
            "total_expense": sum(item["total"] for item in categories if item["category__category_type"] == Category.CategoryType.EXPENSE),
            "total_income": abs(sum(item["total"] for item in categories if item["category__category_type"] == Category.CategoryType.INCOME)),
            "investment_data": json.dumps(investment_data),
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

    try:
        category.delete()
    except ProtectedError:
        _flash_error(
            request,
            "Cannot delete category because it is associated with existing transactions."
        )

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
def transaction_template_download(request):
    account = (
        Account.objects.filter(user=request.user, is_active=True)
        .exclude(account_type=Account.AccountType.INVESTMENT)
        .order_by("name")
        .first()
    )
    category = Category.objects.filter(
        category_type=Category.CategoryType.EXPENSE,
    ).filter(
        Q(is_system=True) | Q(created_by=request.user)
    ).order_by("name").first()

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="transactions-template.csv"'
    writer = csv.writer(response)
    writer.writerow([
        "account", "category", "category_type", "category_normal_side",
        "merchant", "amount", "transaction_date", "description",
    ])
    writer.writerow([
        account.name if account else "Create an account first",
        category.name if category else "Food",
        category.category_type if category else Category.CategoryType.EXPENSE,
        category.normal_side if category else EntryType.DEBIT,
        "Example merchant",
        "25.00",
        f"{date.today().month}/{date.today().day}/{date.today().year}",
        "Example expense",
    ])
    return response


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
    queryset = Transaction.objects.filter(user=request.user, is_deleted=False).select_related(
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
    
    # Keep this header aligned with the transaction importer.
    writer = csv.writer(response)
    writer.writerow([
        'account', 'category', 'category_type', 'category_normal_side',
        'merchant', 'amount', 'transaction_date', 'description'
    ])
    
    for txn in queryset:
        writer.writerow([
            txn.account.name,
            txn.category.name,
            txn.category.category_type,
            txn.category.normal_side,
            txn.merchant.name if txn.merchant else "",
            f"{txn.amount:.2f}" if txn.entry_type == txn.category.normal_side else f"{-txn.amount:.2f}",
            f"{txn.transaction_date.month}/{txn.transaction_date.day}/{txn.transaction_date.year}",
            txn.description,
        ])
    
    _log_info(
        "Transactions export completed",
        user_id=request.user.id,
        count=queryset.count(),
    )
    return response
