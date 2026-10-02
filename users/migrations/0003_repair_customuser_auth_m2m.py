from django.db import migrations


def repair_auth_many_to_many_columns(apps, schema_editor):
    user_model = apps.get_model("users", "CustomUser")
    connection = schema_editor.connection
    tables = set(connection.introspection.table_names())

    with connection.cursor() as cursor:
        for field_name in ("groups", "user_permissions"):
            user_field = user_model._meta.get_field(field_name)
            through_model = user_field.remote_field.through
            table_name = through_model._meta.db_table
            expected_column = through_model._meta.get_field(
                user_field.m2m_field_name()
            ).column

            if table_name not in tables:
                schema_editor.create_model(through_model)
                tables.add(table_name)
                continue

            columns = {
                column.name
                for column in connection.introspection.get_table_description(
                    cursor, table_name
                )
            }

            if expected_column not in columns and "user_id" in columns:
                cursor.execute(
                    f"ALTER TABLE {schema_editor.quote_name(table_name)} "
                    f"RENAME COLUMN {schema_editor.quote_name('user_id')} "
                    f"TO {schema_editor.quote_name(expected_column)}"
                )
            elif expected_column in columns and "user_id" in columns:
                raise RuntimeError(
                    f"Cannot repair {table_name}: both {expected_column} and "
                    "user_id exist. Resolve the duplicate columns and rerun migrations."
                )
            elif expected_column not in columns:
                raise RuntimeError(
                    f"Cannot repair {table_name}: expected either "
                    f"{expected_column} or user_id, found {sorted(columns)}"
                )


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0002_repair_customuser_phone_number"),
    ]

    operations = [
        migrations.RunPython(
            repair_auth_many_to_many_columns,
            migrations.RunPython.noop,
        ),
    ]
