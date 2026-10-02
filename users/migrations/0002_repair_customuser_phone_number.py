from django.db import migrations


def ensure_phone_number_column(apps, schema_editor):
    user_model = apps.get_model("users", "CustomUser")
    table_name = user_model._meta.db_table

    with schema_editor.connection.cursor() as cursor:
        columns = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(
                cursor, table_name
            )
        }

    if "phone_number" not in columns:
        schema_editor.add_field(
            user_model,
            user_model._meta.get_field("phone_number"),
        )


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            ensure_phone_number_column,
            migrations.RunPython.noop,
        ),
    ]