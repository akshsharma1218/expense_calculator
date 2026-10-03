from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("expense", "0006_usernotification_is_read"),
    ]

    operations = [
        migrations.AddField(
            model_name="budget",
            name="description",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AlterField(
            model_name="budget",
            name="category",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="expense.category",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="budget",
            name="uq_budget_period",
        ),
        migrations.AddConstraint(
            model_name="budget",
            constraint=models.UniqueConstraint(
                condition=models.Q(("category__isnull", True)),
                fields=("user", "month", "year"),
                name="uq_budget_overall_period",
            ),
        ),
        migrations.AddConstraint(
            model_name="budget",
            constraint=models.UniqueConstraint(
                condition=models.Q(("category__isnull", False)),
                fields=("user", "category", "month", "year"),
                name="uq_budget_category_period",
            ),
        ),
    ]