from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion
import uuid


def allocate_existing_settlements(apps, schema_editor):
    Settlement = apps.get_model("expense", "Settlement")
    GroupExpenseSplit = apps.get_model("expense", "GroupExpenseSplit")
    SettlementAllocation = apps.get_model("expense", "SettlementAllocation")
    Category = apps.get_model("expense", "Category")
    database = schema_editor.connection.alias
    allocated_by_split = {}

    for name, category_type, normal_side in (
        ("Group Settlement Paid", "expense", "debit"),
        ("Group Settlement Received", "income", "credit"),
    ):
        Category.objects.using(database).get_or_create(
            name=name,
            category_type=category_type,
            is_system=True,
            created_by_id=None,
            defaults={"normal_side": normal_side},
        )

    settlements = Settlement.objects.using(database).order_by(
        "created_at",
        "pk",
    )
    for settlement in settlements.iterator():
        remaining = Decimal(settlement.amount)
        splits = GroupExpenseSplit.objects.using(database).filter(
            expense__group_id=settlement.group_id,
            expense__paid_by_id=settlement.receiver_id,
            user_id=settlement.payer_id,
        ).order_by("created_at", "pk")

        for split in splits.iterator():
            if remaining <= 0:
                break

            already_allocated = allocated_by_split.get(split.pk)
            if already_allocated is None:
                already_allocated = sum(
                    SettlementAllocation.objects.using(database)
                    .filter(split_id=split.pk)
                    .values_list("amount", flat=True),
                    Decimal("0.00"),
                )

            outstanding = Decimal(split.share_amount) - already_allocated
            if outstanding <= 0:
                continue

            allocation_amount = min(remaining, outstanding)
            SettlementAllocation.objects.using(database).create(
                settlement_id=settlement.pk,
                split_id=split.pk,
                amount=allocation_amount,
            )
            already_allocated += allocation_amount
            allocated_by_split[split.pk] = already_allocated
            remaining -= allocation_amount

            if already_allocated >= Decimal(split.share_amount):
                GroupExpenseSplit.objects.using(database).filter(
                    pk=split.pk
                ).update(status="settled")


class Migration(migrations.Migration):

    dependencies = [
        ("expense", "0003_favoritedescription_description"),
    ]

    operations = [
        migrations.CreateModel(
            name="SettlementAllocation",
            fields=[
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, db_index=True),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "amount",
                    models.DecimalField(decimal_places=2, max_digits=15),
                ),
                (
                    "settlement",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="allocations",
                        to="expense.settlement",
                    ),
                ),
                (
                    "split",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="settlement_allocations",
                        to="expense.groupexpensesplit",
                    ),
                ),
            ],
            options={
                "db_table": "settlement_allocation",
            },
        ),
        migrations.AddConstraint(
            model_name="settlementallocation",
            constraint=models.UniqueConstraint(
                fields=("settlement", "split"),
                name="uq_settlement_split_allocation",
            ),
        ),
        migrations.AddField(
            model_name="settlement",
            name="payer_transaction",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="payer_settlement",
                to="expense.transaction",
            ),
        ),
        migrations.AddField(
            model_name="settlement",
            name="receiver_transaction",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="receiver_settlement",
                to="expense.transaction",
            ),
        ),
        migrations.AddField(
            model_name="settlement",
            name="is_completed",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="settlement",
            name="splits",
            field=models.ManyToManyField(
                related_name="settlements",
                through="expense.SettlementAllocation",
                to="expense.groupexpensesplit",
            ),
        ),
        migrations.RunPython(
            allocate_existing_settlements,
            migrations.RunPython.noop,
        ),
    ]
