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
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
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
    paid_by = forms.ModelChoiceField(
        queryset=User.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Paid by",
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
        member_ids = [member.user_id for member in self.members]
        self.fields["paid_by"].queryset = (
            User.objects.filter(pk__in=member_ids).order_by("email")
            if group else User.objects.none()
        )
        if group:
            self.fields["selected_members"] = forms.MultipleChoiceField(
                choices=[
                    (str(member.user_id), member.user.get_full_name() or member.user.username)
                    for member in self.members
                ],
                required=False,
            )
            for member in self.members:
                self.fields[f"share_{member.user_id}"] = forms.DecimalField(
                    required=False,
                    min_value=Decimal("0.01"),
                    max_digits=15,
                    decimal_places=2,
                    widget=forms.NumberInput(
                        attrs={"class": "form-control split-custom-amount", "step": "0.01"}
                    ),
                )
        if user and group and group.members.filter(user=user).exists():
            self.fields["paid_by"].initial = user

    def clean(self):
        cleaned = super().clean()
        group = cleaned.get("group")
        payer = cleaned.get("paid_by")
        if group and payer and not group.members.filter(user=payer).exists():
            self.add_error("paid_by", "The payer must be a member of the selected group.")

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
            if selected_ids and total != self.transaction.amount:
                self.add_error(None, "Share amounts must add up to the transaction total.")
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

    class Meta:
        model = Budget

        fields = (
            "category",
            "month",
            "year",
            "amount",
        )

        widgets = {
            "category": forms.Select(
                attrs={"class": "form-select"}
            ),
            "month": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "max": 12,
                }
            ),
            "year": forms.NumberInput(
                attrs={
                    "class": "form-control",
                }
            ),
            "amount": forms.NumberInput(
                attrs={
                    "class": "form-control",
                }
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.user = user

        if user:
            self.fields["category"].queryset = (
                (
                    Category.objects.filter(
                        is_system=True,
                        normal_side=EntryType.DEBIT,
                    )
                    | Category.objects.filter(
                        created_by=user,
                        normal_side=EntryType.DEBIT,
                    )
                )
                .order_by("name")
            )
        self.fields["category"].empty_label = None 

    def clean_month(self):
        month = self.cleaned_data["month"]

        if month < 1 or month > 12:
            raise ValidationError(
                "Month must be between 1 and 12."
            )

        return month

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


class SettlementForm(forms.Form):

    receiver = forms.ModelChoiceField(
        queryset=User.objects.none(),
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
        group=None,
        payer=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.group = group
        self.payer = payer

        if not group or not payer:
            return

        self.fields["receiver"].queryset = (
            User.objects.filter(
                id__in=group.members.values_list(
                    "user_id",
                    flat=True,
                )
            )
            .exclude(
                id=payer.id,
            )
            .order_by("username")
        )
        self.fields["receiver"].empty_label = None

    def clean(self):
        cleaned = super().clean()

        receiver = cleaned.get("receiver")
        amount = cleaned.get("amount")

        if amount and amount <= 0:
            raise ValidationError(
                "Amount must be greater than zero."
            )

        if (
            self.group
            and receiver
            and not self.group.members.filter(
                user=receiver,
            ).exists()
        ):
            raise ValidationError(
                "Invalid receiver."
            )

        return cleaned
        
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
