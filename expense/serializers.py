from decimal import Decimal

from rest_framework import serializers

from .models import (
    Account,
    Category,
    Merchant,
    Tag,
)


class TransactionItemSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2)

    def validate(self, attrs):
        attrs["total_price"] = (
            Decimal(attrs["quantity"])
            * Decimal(attrs["unit_price"])
        )
        return attrs


class TransactionCreateSerializer(serializers.Serializer):

    account = serializers.PrimaryKeyRelatedField(
        queryset=Account.objects.none()
    )

    category = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.none()
    )

    merchant = serializers.PrimaryKeyRelatedField(
        queryset=Merchant.objects.none(),
        required=False,
        allow_null=True,
    )

    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    description = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    transaction_date = serializers.DateField()

    tags = serializers.PrimaryKeyRelatedField(
        queryset=Tag.objects.none(),
        many=True,
        required=False,
    )

    items = TransactionItemSerializer(
        many=True,
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        user = self.context["request"].user

        self.fields["account"].queryset = (
            Account.objects.filter(
                user=user,
                is_active=True,
            )
        )

        self.fields["category"].queryset = (
            Category.objects.filter(is_system=True)
            | Category.objects.filter(created_by=user)
        ).exclude(
            category_type=Category.CategoryType.TRANSFER
        )

        self.fields["merchant"].queryset = (
            Merchant.objects.filter(is_system=True)
            | Merchant.objects.filter(created_by=user)
        )

        self.fields["tags"].queryset = (
            Tag.objects.filter(user=user)
        )