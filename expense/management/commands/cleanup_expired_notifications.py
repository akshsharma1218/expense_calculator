from django.core.management.base import BaseCommand
from django.utils import timezone

from expense.models import UserNotification


class Command(BaseCommand):
    help = "Delete notifications whose one-week retention period has elapsed."

    def handle(self, *args, **options):
        deleted_count, _ = UserNotification.objects.filter(
            expires_at__lte=timezone.now(),
        ).delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted_count} expired notification record(s)."
            )
        )
