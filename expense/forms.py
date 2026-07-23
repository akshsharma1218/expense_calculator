from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.forms import modelformset_factory
from django.utils import timezone


User = get_user_model()

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
    refund = forms.BooleanField(
        required=False,
        label="Refund",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input"}
        ),
    )

    class Meta:
        model = Transaction

        fields = (
            "account",
            "category",
            "amount",
            "merchant",
            "description",
            "tags",
            "transaction_date",
            "refund",
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
            "tags": forms.SelectMultiple(
                attrs={
                    "class": "form-select",
                    "size": 3,
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

        self.fields["merchant"].required = False
        self.fields["transaction_date"].initial = timezone.localdate

        if not user:
            return


        if self.instance._state.adding == False:
            if self.instance.entry_type != self.instance.category.normal_side:
                self.fields["refund"].initial = True 

        self.fields["account"].queryset = (
            Account.objects.filter(
                user=user,
                is_active=True,
            )
            .order_by("name")
        )
        self.fields["account"].empty_label = None 

        category_qs = (
            Category.objects.filter(is_system=True)
            | Category.objects.filter(created_by=user)
        )

        self.fields["category"].empty_label = None 

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
        self.fields["merchant"].empty_label = None 

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
                }
            ),
            "unit_price": forms.NumberInput(
                attrs={
                    "class": "form-control price",
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

TransactionItemFormSet = modelformset_factory(
    TransactionItem,
    form=TransactionItemForm,
    extra=0,
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
            if choice[0] not in ("",Category.CategoryType.TRANSFER)
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