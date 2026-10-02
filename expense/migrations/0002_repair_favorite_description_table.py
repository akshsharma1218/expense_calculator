from django.db import migrations


def ensure_favorite_description_table(apps, schema_editor):
    model = apps.get_model("expense", "FavoriteDescription")
    table_name = model._meta.db_table
    existing_tables = schema_editor.connection.introspection.table_names()
    if table_name not in existing_tables:
        schema_editor.create_model(model)


class Migration(migrations.Migration):
    dependencies = [
        ("expense", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            ensure_favorite_description_table,
            migrations.RunPython.noop,
        ),
    ]