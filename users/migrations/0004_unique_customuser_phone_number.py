from django.db import migrations, models
from django.db.models import Q


def ensure_phone_numbers_are_unique(apps, schema_editor):
    user_model = apps.get_model("users", "CustomUser")
    table_name = schema_editor.quote_name(user_model._meta.db_table)
    phone_column = schema_editor.quote_name(
        user_model._meta.get_field("phone_number").column
    )

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"SELECT COUNT(*) FROM ("
            f"SELECT {phone_column} FROM {table_name} "
            f"WHERE {phone_column} IS NOT NULL AND {phone_column} <> '' "
            f"GROUP BY {phone_column} HAVING COUNT(*) > 1"
            f") AS duplicate_phone_numbers"
        )
        duplicate_count = cursor.fetchone()[0]

    if duplicate_count:
        raise RuntimeError(
            "Cannot enforce unique phone numbers: "
            f"{duplicate_count} duplicate phone number value(s) exist. "
            "Resolve the duplicates and rerun migrations."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0003_repair_customuser_auth_m2m"),
    ]

    operations = [
        migrations.RunPython(
            ensure_phone_numbers_are_unique,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="customuser",
            constraint=models.UniqueConstraint(
                fields=("phone_number",),
                condition=Q(phone_number__isnull=False) & ~Q(phone_number=""),
                name="unique_customuser_phone_number",
            ),
        ),
    ]
