# expense/forms.py

from django import forms
from django.forms import (
    modelformset_factory
)
from django.core.exceptions import ValidationError

from .models import (
    Account,
    Category,
    Merchant,
    Tag,
    Transaction,
    TransactionItem,
    Budget,
    ExpenseGroup,
    Settlement,
)


# ============================================================
# Account
# ============================================================

class AccountForm(forms.ModelForm):

    class Meta:
        model = Account

        fields = [
            "name",
            "account_type",
            "opening_balance",
        ]

        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "account_type": forms.Select(
                attrs={"class": "form-select"}
            ),
            "opening_balance": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                }
            ),
        }


# ============================================================
# Category
# ============================================================

class CategoryForm(forms.ModelForm):

    class Meta:
        model = Category

        fields = [
            "name",
            "category_type",
            "parent",
            "icon",
        ]

        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "category_type": forms.Select(
                attrs={"class": "form-select"}
            ),
            "parent": forms.Select(
                attrs={"class": "form-select"}
            ),
            "icon": forms.TextInput(
                attrs={"class": "form-control"}
            ),
        }


# ============================================================
# Merchant
# ============================================================

class MerchantForm(forms.ModelForm):

    class Meta:
        model = Merchant

        fields = [
            "name",
        ]

        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control"}
            )
        }


# ============================================================
# Tag
# ============================================================

class TagForm(forms.ModelForm):

    class Meta:
        model = Tag

        fields = [
            "name",
        ]

        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control"}
            )
        }


# ============================================================
# Transaction
# ============================================================

class TransactionForm(forms.ModelForm):

    class Meta:
        model = Transaction

        fields = [
            "account",
            "transfer_account",
            "category",
            "merchant",
            "amount",
            "transaction_type",
            "transaction_date",
            "description",
            "reference_number",
            "tags",
        ]

        widgets = {
            "account": forms.Select(
                attrs={"class": "form-select"}
            ),
            "transfer_account": forms.Select(
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
                    "step": "0.01",
                }
            ),
            "transaction_type": forms.Select(
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
            "reference_number": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "tags": forms.SelectMultiple(
                attrs={"class": "form-select"}
            ),
        }

    def __init__(
        self,
        *args,
        user=None,
        **kwargs
    ):
        super().__init__(*args, **kwargs)

        if user:

            self.fields[
                "account"
            ].queryset = Account.objects.filter(
                user=user,
                is_active=True,
            )

            self.fields[
                "transfer_account"
            ].queryset = Account.objects.filter(
                user=user,
                is_active=True,
            )

            self.fields[
                "tags"
            ].queryset = Tag.objects.filter(
                user=user
            )

            self.fields[
                "category"
            ].queryset = Category.objects.filter(
                is_system=True
            ) | Category.objects.filter(
                created_by=user
            )

            self.fields[
                "merchant"
            ].queryset = Merchant.objects.filter(
                is_system=True
            ) | Merchant.objects.filter(
                created_by=user
            )

    def clean(self):

        cleaned_data = super().clean()

        txn_type = cleaned_data.get(
            "transaction_type"
        )

        transfer_account = cleaned_data.get(
            "transfer_account"
        )

        account = cleaned_data.get(
            "account"
        )

        if (
            txn_type
            == Transaction.TransactionType.TRANSFER
        ):

            if not transfer_account:

                raise ValidationError(
                    "Transfer account is required."
                )

            if account == transfer_account:

                raise ValidationError(
                    "Cannot transfer to same account."
                )

        return cleaned_data


# ============================================================
# Transaction Item
# ============================================================

class TransactionItemForm(
    forms.ModelForm
):

    class Meta:

        model = TransactionItem

        fields = [
            "name",
            "quantity",
            "unit_price",
        ]

        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "quantity": forms.NumberInput(
                attrs={"class": "form-control qty"}
            ),
            "unit_price": forms.NumberInput(
                attrs={"class": "form-control price"}
            ),
        }
        
TransactionItemFormSet = (
    modelformset_factory(
        TransactionItem,
        form=TransactionItemForm,
        extra=1,
        can_delete=True,
    )
)


# ============================================================
# Budget
# ============================================================

class BudgetForm(forms.ModelForm):

    class Meta:
        model = Budget

        fields = [
            "category",
            "month",
            "year",
            "amount",
        ]

        widgets = {
            "category": forms.Select(
                attrs={"class": "form-select"}
            ),
            "month": forms.NumberInput(
                attrs={"class": "form-control"}
            ),
            "year": forms.NumberInput(
                attrs={"class": "form-control"}
            ),
            "amount": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                }
            ),
        }

    def __init__(
        self,
        *args,
        user=None,
        **kwargs
    ):
        super().__init__(*args, **kwargs)

        if user:

            self.fields[
                "category"
            ].queryset = Category.objects.filter(
                category_type=Category.CategoryType.EXPENSE
            ).filter(
                is_system=True
            ) | Category.objects.filter(
                created_by=user,
                category_type=Category.CategoryType.EXPENSE,
            )


# ============================================================
# Expense Group
# ============================================================

class ExpenseGroupForm(forms.ModelForm):

    class Meta:
        model = ExpenseGroup

        fields = [
            "name",
            "description",
        ]

        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                }
            ),
        }


# ============================================================
# Group Expense Form
# ============================================================

class GroupExpenseForm(forms.Form):

    transaction = forms.ModelChoiceField(
        queryset=Transaction.objects.none(),
        widget=forms.Select(
            attrs={"class": "form-select"}
        )
    )

    def __init__(
        self,
        *args,
        user=None,
        **kwargs
    ):
        super().__init__(*args, **kwargs)

        if user:

            self.fields[
                "transaction"
            ].queryset = (
                Transaction.objects
                .filter(
                    user=user,
                    is_deleted=False,
                )
                .order_by(
                    "-transaction_date"
                )
            )


# ============================================================
# Settlement
# ============================================================

class SettlementForm(forms.ModelForm):

    class Meta:
        model = Settlement

        fields = [
            "payer",
            "receiver",
            "amount",
            "settlement_date",
            "notes",
        ]

        widgets = {
            "payer": forms.Select(
                attrs={"class": "form-select"}
            ),
            "receiver": forms.Select(
                attrs={"class": "form-select"}
            ),
            "amount": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                }
            ),
            "settlement_date": forms.DateInput(
                attrs={
                    "class": "form-control",
                    "type": "date",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                }
            ),
        }

    def clean(self):

        cleaned_data = super().clean()

        payer = cleaned_data.get("payer")
        receiver = cleaned_data.get("receiver")

        if payer == receiver:

            raise ValidationError(
                "Payer and receiver cannot be same."
            )

        return cleaned_data