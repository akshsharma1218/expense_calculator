from django.db import migrations, models


def preserve_existing_access(apps, schema_editor):
    user_model = apps.get_model("users", "CustomUser")
    user_model.objects.all().update(
        is_approved=True,
        is_email_verified=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0004_unique_customuser_phone_number"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="is_approved",
            field=models.BooleanField(
                default=False,
                help_text="Designates whether an administrator approved this account.",
                verbose_name="approved",
            ),
        ),
        migrations.RunPython(preserve_existing_access, migrations.RunPython.noop),
    ]
