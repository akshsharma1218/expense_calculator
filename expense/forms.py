from django import forms
from django.core.exceptions import ValidationError
from django.forms import modelformset_factory
from django.utils import timezone

from .models import (
    Account,
    Category,
    Merchant,
    Tag,
    Transaction,
    TransactionItem,
    ExpenseGroup,
    Budget,
    EntryType,
)

    
# ============================================================
# Transaction
# ============================================================

class TransactionForm(forms.ModelForm):

    class Meta:
        model = Transaction

        fields = (
            "account",
            "category",
            "merchant",
            "transaction_date",
            "description",
            "tags",
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
            "tags": forms.SelectMultiple(
                attrs={"class": "form-select"}
            ),
        }

    def __init__(
        self,
        *args,
        user=None,
        entry_type=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.user = user

        self.fields["merchant"].required = False
        self.fields["transaction_date"].initial = timezone.localdate

        if not user:
            return

        self.fields["account"].queryset = (
            Account.objects.filter(
                user=user,
                is_active=True,
            )
            .order_by("name")
        )

        category_qs = (
            Category.objects.filter(is_system=True)
            | Category.objects.filter(created_by=user)
        )

        if entry_type:
            category_qs = category_qs.filter(
                normal_side=entry_type
            )

        self.fields["category"].queryset = (
            category_qs
            .exclude(category_type=Category.CategoryType.TRANSFER)
            .order_by("name")
        )

        self.fields["merchant"].queryset = (
            (
                Merchant.objects.filter(is_system=True)
                | Merchant.objects.filter(created_by=user)
            )
            .order_by("name")
        )

        self.fields["tags"].queryset = (
            Tag.objects.filter(user=user)
            .order_by("name")
        )

    def clean(self):
        cleaned = super().clean()

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

        tags = cleaned.get("tags")

        for tag in tags:
            if tag.user_id != self.user.id:
                raise ValidationError(
                    "Invalid tag."
                )

        return cleaned


class TransactionItemForm(forms.ModelForm):

    class Meta:
        model = TransactionItem

        fields = (
            "name",
            "quantity",
            "unit_price",
        )

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "maxlength": 200,
                }
            ),
            "quantity": forms.NumberInput(
                attrs={
                    "class": "form-control qty",
                    "step": "0.01",
                    "min": "0.01",
                }
            ),
            "unit_price": forms.NumberInput(
                attrs={
                    "class": "form-control price",
                    "step": "0.01",
                    "min": "0.01",
                }
            ),
        }

    def clean_name(self):
        return self.cleaned_data["name"].strip()

    def clean_quantity(self):
        qty = self.cleaned_data["quantity"]

        if qty <= 0:
            raise ValidationError(
                "Quantity must be greater than zero."
            )

        return qty

    def clean_unit_price(self):
        price = self.cleaned_data["unit_price"]

        if price <= 0:
            raise ValidationError(
                "Unit price must be greater than zero."
            )

        return price

TransactionItemFormSet = modelformset_factory(
    TransactionItem,
    form=TransactionItemForm,
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
)

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
                "step": "0.01",
                "min": "0.01",
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
                    "step": "0.01",
                    "min": "0",
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

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        if user:
            self.fields["parent"].queryset = (
                Category.objects.filter(is_system=True)
                | Category.objects.filter(created_by=user)
            )

    def clean_name(self):
        return self.cleaned_data["name"].strip()

    def clean(self):
        cleaned = super().clean()

        parent = cleaned.get("parent")

        if parent == self.instance:
            raise ValidationError(
                "A category cannot be its own parent."
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
                    "min": 1,
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
                    "step": "0.01",
                    "min": "0.01",
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

# ============================================================
# Tag
# ============================================================

class TagForm(forms.ModelForm):

    class Meta:
        model = Tag

        fields = (
            "name",
        )

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "maxlength": 50,
                }
            )
        }

    def clean_name(self):
        return self.cleaned_data["name"].strip()