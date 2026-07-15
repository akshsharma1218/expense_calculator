from django.core.management.base import BaseCommand
from expense.models import Category, EntryType


class Command(BaseCommand):
    help = "Create default system categories for expense tracking"

    def handle(self, *args, **options):
        categories_data = [
            
            # Transfer categories
            {
                "name": "Transfer In",
                "category_type": Category.CategoryType.TRANSFER,
                "normal_side": EntryType.DEBIT,
                "is_system": True,
            },
            {
                "name": "Transfer Out",
                "category_type": Category.CategoryType.TRANSFER,
                "normal_side": EntryType.CREDIT,
                "is_system": True,
            },
        ]

        created_count = 0
        for data in categories_data:
            obj, created = Category.objects.get_or_create(
                name=data["name"],
                category_type=data["category_type"],
                defaults={
                    "normal_side": data["normal_side"],
                    "is_system": data["is_system"],
                },
            )
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f"Created: {data['name']}")
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f"- Already exists: {data['name']}")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nTotal created: {created_count} categories"
            )
        )
