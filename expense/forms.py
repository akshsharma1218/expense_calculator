import json
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone


User = get_user_model()

from .models import (
    Account,
    Category,
    Merchant,
    Transaction,
    ExpenseGroup,
    Budget,
    EntryType,
    FavoriteDescription,
    GroupExpenseSplit,
)

SETTLEMENT_CATEGORY_NAMES = (
    "Group Settlement Paid",
    "Group Settlement Received",
)

    
# ============================================================
# Transaction
# ============================================================

class QuickTransactionForm(forms.Form):
    favorite = forms.ModelChoiceField(
        queryset=FavoriteDescription.objects.none(),
        label="Saved favorite",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    amount = forms.DecimalField(
        max_digits=15,
        decimal_places=2,
        help_text="Use a negative amount for the opposite direction.",
        widget=forms.NumberInput(
            attrs={
                "class": "form-control quick-entry-amount",
                "min": "-9999999999999.99",
                "step": "0.01",
                "placeholder": "0.00",
                "autofocus": True,
            }
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            favorites = FavoriteDescription.objects.filter(
                user=user,
                account__user=user,
                account__is_active=True,
                category__isnull=False,
            ).filter(
                Q(category__is_system=True) | Q(category__created_by=user),
            ).filter(
                Q(merchant__isnull=True)
                | Q(merchant__is_system=True)
                | Q(merchant__created_by=user),
            ).exclude(
                category__category_type__in=(Category.CategoryType.TRANSFER, "refund"),
            ).exclude(
                category__name__in=SETTLEMENT_CATEGORY_NAMES,
            ).select_related("account", "category", "merchant").order_by("name")
        else:
            favorites = FavoriteDescription.objects.none()

        self.fields["favorite"].queryset = favorites
        self.fields["favorite"].empty_label = "Choose a favorite"
        self.fields["favorite"].initial = favorites.first()

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount == 0:
            raise ValidationError("Amount cannot be zero.")
        return amount


class FavoriteDescriptionForm(forms.ModelForm):
    class Meta:
        model = FavoriteDescription
        fields = ("name", "account", "category", "merchant", "description")
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 80}
            ),
            "account": forms.Select(attrs={"class": "form-select"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "merchant": forms.Select(attrs={"class": "form-select"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 1}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["account"].required = False
        self.fields["category"].required = False
        self.fields["merchant"].required = False
        self.fields["account"].queryset = (
            Account.objects.filter(user=user, is_active=True).order_by("name")
            if user else Account.objects.none()
        )
        self.fields["description"].required = False
        self.fields["category"].queryset = (
            (Category.objects.filter(is_system=True) | Category.objects.filter(created_by=user))
            .exclude(category_type__in=(Category.CategoryType.TRANSFER, "refund"))
            .exclude(name__in=SETTLEMENT_CATEGORY_NAMES)
            .order_by("name")
            if user else Category.objects.none()
        )
        self.fields["merchant"].queryset = (
            (Merchant.objects.filter(is_system=True) | Merchant.objects.filter(created_by=user))
            .order_by("name")
            if user else Merchant.objects.none()
        )
        self.fields["account"].empty_label = "No default account"
        self.fields["category"].empty_label = "No default category"
        self.fields["merchant"].empty_label = "No default merchant"
        self.fields["description"].empty_label = "No default description"

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        matches = FavoriteDescription.objects.filter(user=self.user, name__iexact=name)
        if self.instance.pk:
            matches = matches.exclude(pk=self.instance.pk)
        if matches.exists():
            raise ValidationError("You already have a favorite with this name.")
        return name

class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction

        fields = (
            "account",
            "category",
            "amount",
            "merchant",
            "description",
            "transaction_date",
        )

        widgets = {
            "account": forms.Select(
                attrs={"class": "form-select"}
            ),
            "category": forms.Select(
                attrs={"class": "form-select"}
            ),
            "merchant": forms.Select(
                attrs={"class": "form-select"}
            ),
            "amount": forms.NumberInput(
                attrs={
                    "class": "form-control",
                }
            ),
            "transaction_date": forms.DateInput(
                attrs={
                    "class": "form-control",
                    "type": "date",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                }
            ),
        }

    def __init__(
        self,
        *args,
        user=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.user = user
        self.has_accounts = False
        self.amount_is_negative = False

        self.fields["merchant"].required = False
        self.fields["transaction_date"].initial = timezone.localdate
        self.fields["amount"].help_text = "Use a negative amount for the opposite direction."

        if not user:
            return


        if not self.instance._state.adding and self.instance.entry_type != self.instance.category.normal_side:
            self.initial["amount"] = -self.instance.amount

        self.fields["account"].queryset = (
            Account.objects.filter(
                user=user,
                is_active=True,
            )
            .order_by("name")
        )
        self.has_accounts = self.fields["account"].queryset.exists()
        self.fields["account"].empty_label = None 

        category_qs = (
            Category.objects.filter(is_system=True)
            | Category.objects.filter(created_by=user)
        )

        self.fields["category"].empty_label = None 

        self.fields["category"].queryset = (
            category_qs
            .exclude(category_type__in=(Category.CategoryType.TRANSFER, "refund"))
            .exclude(name__in=SETTLEMENT_CATEGORY_NAMES)
            .order_by("name")
        )

        self.fields["merchant"].queryset = (
            (
                Merchant.objects.filter(is_system=True)
                | Merchant.objects.filter(created_by=user)
            )
            .order_by("name")
        )
        self.fields["merchant"].empty_label = None 

    def clean(self):
        cleaned = super().clean()
        amount = cleaned.get("amount")
        self.amount_is_negative = amount is not None and amount < 0
        if amount == 0:
            self.add_error("amount", "Amount cannot be zero.")
        if self.amount_is_negative:
            cleaned["amount"] = abs(amount)

        if not self.has_accounts:
            self.add_error(None, "Create an account before adding a transaction.")
        account = cleaned.get("account")
        category = cleaned.get("category")

        if account and account.user_id != self.user.id:
            raise ValidationError(
                "Invalid account."
            )

        if category:
            if (
                not category.is_system
                and category.created_by_id != self.user.id
            ):
                raise ValidationError(
                    "Invalid category."
                )

        merchant = cleaned.get("merchant")

        if merchant:
            if (
                not merchant.is_system
                and merchant.created_by_id != self.user.id
            ):
                raise ValidationError(
                    "Invalid merchant."
                )

        return cleaned


class SplitTransactionForm(forms.Form):
    split_mode = forms.ChoiceField(
        choices=(("equal", "Split equally"), ("custom", "Custom amounts")),
        initial="equal",
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Split method",
    )
    group = forms.ModelChoiceField(
        queryset=ExpenseGroup.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
        empty_label="Choose a group",
    )
    def __init__(self, *args, user=None, transaction=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.transaction = transaction
        self.members = []
        self.fields["group"].queryset = (
            ExpenseGroup.objects.filter(members__user=user).distinct().order_by("name")
            if user else ExpenseGroup.objects.none()
        )
        group_id = self.data.get("group") or self.initial.get("group")
        group = self.fields["group"].queryset.filter(pk=group_id).first()
        self.members = list(group.members.select_related("user").order_by("user__username")) if group else []
        if group:
            owed_members = [
                member for member in self.members
                if member.user_id != getattr(user, "pk", None)
            ]
            self.fields["selected_members"] = forms.MultipleChoiceField(
                choices=[
                    (str(member.user_id), member.user.get_full_name() or member.user.username)
                    for member in owed_members
                ],
                required=False,
            )
            for member in owed_members:
                self.fields[f"share_{member.user_id}"] = forms.DecimalField(
                    required=False,
                    min_value=Decimal("0.01"),
                    max_digits=15,
                    decimal_places=2,
                    widget=forms.NumberInput(
                        attrs={"class": "form-control split-custom-amount", "step": "0.01"}
                    ),
                )
                initial_amount = self.initial.get(f"share_{member.user_id}")
                if initial_amount is not None:
                    self.fields[f"share_{member.user_id}"].initial = initial_amount
            selected_members = self.initial.get("selected_members")
            if selected_members is not None:
                self.fields["selected_members"].initial = selected_members

    def clean(self):
        cleaned = super().clean()
        group = cleaned.get("group")
        if group and self.user and not group.members.filter(user=self.user).exists():
            self.add_error("group", "You must be a member of the selected group.")

        custom_shares = []
        if cleaned.get("split_mode") == "custom" and group and self.transaction:
            selected_ids = cleaned.get("selected_members") or []
            total = Decimal("0.00")
            if not selected_ids:
                self.add_error(None, "Select at least one group member for the custom split.")
            if len(selected_ids) != len(set(selected_ids)):
                self.add_error(None, "A group member can only be selected once.")
            for member_id in selected_ids:
                amount = cleaned.get(f"share_{member_id}")
                if amount is None:
                    self.add_error(None, "Enter a valid positive share for each selected member.")
                    continue
                if amount <= 0:
                    self.add_error(None, "Each selected member needs a share greater than zero.")
                    continue
                total += amount
                custom_shares.append({
                    "user_id": member_id,
                    "amount": str(amount),
                    "selected": True,
                })
            if selected_ids and total > self.transaction.amount:
                self.add_error(
                    None,
                    "Amounts owed by group members cannot exceed the transaction total.",
                )
        cleaned["custom_shares"] = custom_shares
        return cleaned


# ============================================================
# Transfer
# ============================================================

class TransferForm(forms.Form):

    from_account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )

    to_account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )

    amount = forms.DecimalField(
        min_value=0.01,
        max_digits=15,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
            }
        ),
    )

    transaction_date = forms.DateField(
        initial=timezone.localdate,
        widget=forms.DateInput(
            attrs={
                "class": "form-control",
                "type": "date",
            }
        ),
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
            }
        ),
    )

    def __init__(
        self,
        *args,
        user=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.user = user

        if not user:
            return

        qs = (
            Account.objects.filter(
                user=user,
                is_active=True,
            )
            .order_by("name")
        )

        self.fields["from_account"].queryset = qs
        self.fields["to_account"].queryset = qs
        self.fields["from_account"].empty_label = None
        self.fields["to_account"].empty_label = None

    def clean(self):
        cleaned = super().clean()

        from_account = cleaned.get("from_account")
        to_account = cleaned.get("to_account")
        amount = cleaned.get("amount")

        if from_account == to_account:
            raise ValidationError(
                "Source and destination accounts must be different."
            )

        if amount and amount <= 0:
            raise ValidationError(
                "Amount must be greater than zero."
            )

        if from_account and from_account.user_id != self.user.id:
            raise ValidationError(
                "Invalid source account."
            )

        if to_account and to_account.user_id != self.user.id:
            raise ValidationError(
                "Invalid destination account."
            )

        return cleaned

# ============================================================
# Account
# ============================================================

class AccountForm(forms.ModelForm):

    class Meta:
        model = Account
        fields = (
            "name",
            "account_type",
            "opening_balance",
        )

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "maxlength": 100,
                }
            ),
            "account_type": forms.Select(
                attrs={"class": "form-select"}
            ),
            "opening_balance": forms.NumberInput(
                attrs={
                    "class": "form-control",
                }
            ),
        }

    def clean_opening_balance(self):
        balance = self.cleaned_data["opening_balance"]

        if balance < 0:
            raise ValidationError(
                "Opening balance cannot be negative."
            )

        return balance
    
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        if not user:
            raise ValueError("User is required for AccountForm.")

# ============================================================
# Category
# ============================================================

class CategoryForm(forms.ModelForm):

    class Meta:
        model = Category

        fields = (
            "name",
            "category_type",
            "parent",
            "icon",
        )

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "maxlength": 100,
                }
            ),
            "category_type": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "parent": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "icon": forms.TextInput(
                attrs={
                    "class": "form-control",
                }
            ),
        }

    def get_descendants(self, category_id, children_map):
        descendants = set()
        stack = [category_id]

        while stack:
            parent_id = stack.pop()

            for child in children_map.get(parent_id, []):
                if child.pk not in descendants:
                    descendants.add(child.pk)
                    stack.append(child.pk)

        return descendants
    
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        
        if user:
            queryset = Category.objects.filter(
                created_by=user,
            )

            if self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
                categories = list(queryset.exclude(pk=self.instance.pk))
                children_map = {}
                for category in categories:
                    children_map.setdefault(category.parent_id, []).append(category)

                categories = list(queryset.exclude(pk=self.instance.pk))

                children_map = {}
                for category in categories:
                    children_map.setdefault(category.parent_id, []).append(category)

                descendant_ids = self.get_descendants(
                    self.instance.pk,
                    children_map,
                )

                queryset = queryset.exclude(
                    pk__in=descendant_ids | {self.instance.pk}
                )

            self.fields["parent"].queryset = queryset.order_by("name")

        self.fields["category_type"].choices = [
            choice
            for choice in self.fields["category_type"].choices
            if choice[0] not in ("", Category.CategoryType.TRANSFER, "refund")
        ]
        self.fields["parent"].required = False
        self.fields["parent"].empty_label = ""

    def clean_name(self):
        return self.cleaned_data["name"].strip()

    def clean(self):
        cleaned = super().clean()

        parent = cleaned.get("parent")

        if parent == self.instance:
            raise ValidationError(
                "A category cannot be its own parent."
            )

        if parent and parent.category_type != cleaned.get("category_type"):
            raise ValidationError(
                "Parent category must have the same category type."
            )

        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)

        if obj.category_type == Category.CategoryType.EXPENSE:
            obj.normal_side = EntryType.DEBIT
        else:
            obj.normal_side = EntryType.CREDIT

        if commit:
            obj.save()

        return obj


# ============================================================
# Merchant
# ============================================================

class MerchantForm(forms.ModelForm):

    class Meta:
        model = Merchant

        fields = (
            "name",
        )

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "maxlength": 255,
                }
            )
        }

    def clean_name(self):
        return self.cleaned_data["name"].strip()

class BudgetForm(forms.ModelForm):

    description = forms.CharField(
        max_length=200,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "maxlength": 200,
                "placeholder": "e.g. Monthly household spending",
            }
        ),
    )

    amount = forms.DecimalField(
        min_value=Decimal("0.01"),
        max_digits=15,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "min": "0.01",
                "step": "0.01",
                "inputmode": "decimal",
            }
        ),
    )

    class Meta:
        model = Budget
        fields = ("amount", "description", "category")
        widgets = {
            "category": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.user = user
        if self.instance.pk and not self.initial.get("description"):
            self.initial["description"] = (
                self.instance.description
                or getattr(self.instance.category, "name", "")
            )
        self.fields["category"].queryset = Category.objects.filter(
            category_type=Category.CategoryType.EXPENSE,
            created_by = self.user).order_by("name")

    def clean_description(self):
        description = self.cleaned_data["description"].strip()
        if not description:
            raise ValidationError("Enter a description for this budget.")
        return description

    def clean_amount(self):
        amount = self.cleaned_data["amount"]

        if amount <= 0:
            raise ValidationError(
                "Budget amount must be greater than zero."
            )

        return amount

class ExpenseGroupForm(forms.ModelForm):

    class Meta:
        model = ExpenseGroup

        fields = (
            "name",
            "description",
        )

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "maxlength": 200,
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                }
            ),
        }

    def clean_name(self):
        return self.cleaned_data["name"].strip()


class GroupInvitationForm(forms.Form):
    email = forms.CharField(
        label="Email, phone number, or username",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Email, phone number, or username",
                "autocomplete": "username",
            }
        ),
    )

    def clean_email(self):
        return self.cleaned_data["email"].strip()

class SplitShareForm(forms.Form):
    member = forms.ModelChoiceField(queryset=User.objects.none(), widget=forms.Select(attrs={"class": "form-select"}))
    amount = forms.DecimalField(min_value=0.00, max_digits=15, decimal_places=2, widget=forms.NumberInput(attrs={"class": "form-control"}))

    def __init__(self, *args, group=None, **kwargs):
        super().__init__(*args, **kwargs)
        if group:
            self.fields["member"].queryset = User.objects.filter(id__in=group.members.values_list("user_id", flat=True)).order_by("username")
            self.fields["member"].empty_label = None


class GroupExpenseForm(forms.Form):

    transaction = forms.ModelChoiceField(
        queryset=Transaction.objects.none(),
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        if not user:
            return

        self.fields["transaction"].queryset = (
            Transaction.objects.filter(
                user=user,
                is_deleted=False,
            )
            .exclude(
                group_expense__isnull=False,
            )
            .order_by(
                "-transaction_date",
                "-created_at",
            )
        )
        self.fields["transaction"].empty_label = None


class SettlementAccountChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, account):
        return (
            f"{account.name} · {account.get_account_type_display()} · "
            f"Balance ₹{account.current_balance:.2f}"
        )


class SettlementForm(forms.Form):

    account = SettlementAccountChoiceField(
        queryset=Account.objects.none(),
        widget=forms.Select(attrs={"class": "form-select settlement-account-select"}),
        label="Paid from",
    )
    split_ids = forms.MultipleChoiceField(
        choices=(),
        widget=forms.CheckboxSelectMultiple,
        label="Expenses to settle",
    )
    notes = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )

    def __init__(
        self,
        *args,
        group=None,
        payer=None,
        receiver=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.group = group
        self.payer = payer
        self.receiver = receiver
        self.split_amounts = {}
        self.split_options = []

        if not group or not payer or not receiver:
            return

        self.fields["account"].queryset = Account.objects.filter(
            user=payer,
            is_active=True,
        ).order_by("name")
        self.fields["account"].empty_label = "Choose an account"

        splits = (
            GroupExpenseSplit.objects
            .filter(
                expense__group=group,
                expense__paid_by=receiver,
                user=payer,
                status=GroupExpenseSplit.Status.PENDING,
            )
            .exclude(user=receiver)
            .select_related("expense__transaction")
            .prefetch_related("settlement_allocations")
            .order_by("created_at")
        )
        choices = []
        for split in splits:
            allocated = sum(
                (allocation.amount for allocation in split.settlement_allocations.all()),
                Decimal("0.00"),
            )
            remaining = split.share_amount - allocated
            if remaining <= 0:
                continue
            self.split_amounts[str(split.pk)] = remaining
            description = split.expense.transaction.description or "Group expense"
            self.split_options.append(
                {
                    "id": str(split.pk),
                    "description": description,
                    "amount": remaining,
                }
            )
            choices.append(
                (str(split.pk), f"{description} — ₹{remaining:.2f}")
            )
        self.fields["split_ids"].choices = choices
        self.fields["split_ids"].initial = [value for value, _ in choices]
        selected_ids = self["split_ids"].value() or []
        selected_ids = {str(value) for value in selected_ids}
        for option in self.split_options:
            option["selected"] = option["id"] in selected_ids

    def clean(self):
        cleaned = super().clean()
        selected_ids = cleaned.get("split_ids", [])
        cleaned["selected_splits"] = selected_ids
        cleaned["amount"] = sum(
            (self.split_amounts[split_id] for split_id in selected_ids),
            Decimal("0.00"),
        )
        return cleaned


class SettlementReceiptForm(forms.Form):
    account = SettlementAccountChoiceField(
        queryset=Account.objects.none(),
        widget=forms.Select(attrs={"class": "form-select settlement-account-select"}),
        label="Deposit into",
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields["account"].queryset = Account.objects.filter(
                user=user,
                is_active=True,
            ).order_by("name")
            self.fields["account"].empty_label = "Choose an account"


class ReceiptUploadForm(forms.Form):
    receipt = forms.FileField(
        widget=forms.FileInput(
            attrs={
                "class": "form-control",
                "accept": "image/*,.pdf",
            }
        )
    )


class TransactionsUploadForm(forms.Form):
    csv_file = forms.FileField(
        label="CSV File",
        widget=forms.FileInput(
            attrs={
                "class": "form-control",
                "accept": ".csv,text/csv",
            }
        )
    )

    def clean_csv_file(self):
        file = self.cleaned_data["csv_file"]

        if not file.name.lower().endswith(".csv"):
            raise forms.ValidationError("Please upload a CSV file.")

        return file


class AccountCSVUploadForm(forms.Form):
    csv_file = forms.FileField(
        label="CSV file",
        widget=forms.FileInput(attrs={"class": "form-control", "accept": ".csv,text/csv"}),
    )

    def clean_csv_file(self):
        file = self.cleaned_data["csv_file"]
        if not file.name.lower().endswith(".csv"):
            raise ValidationError("Please upload a CSV file.")
        if file.size > 5 * 1024 * 1024:
            raise ValidationError("Account CSV files must be 5 MB or smaller.")
        return file
