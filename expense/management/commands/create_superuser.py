import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create a Django superuser if one does not already exist"

    def add_arguments(self, parser):
        parser.add_argument("--username", type=str, help="Superuser username")
        parser.add_argument("--email", type=str, help="Superuser email")
        parser.add_argument("--password", type=str, help="Superuser password")
        parser.add_argument(
            "--noinput",
            action="store_true",
            help="Accepted for compatibility with automated environments",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Fail when required credentials are missing",
        )

    def handle(self, *args, **options):
        username = options.get("username") or os.getenv("DJANGO_SUPERUSER_USERNAME")
        email = options.get("email") or os.getenv("DJANGO_SUPERUSER_EMAIL")
        password = options.get("password") or os.getenv("DJANGO_SUPERUSER_PASSWORD")

        if not username or not email or not password:
            message = (
                "Skipping superuser creation: missing username/email/password. "
                "Provide --username/--email/--password or DJANGO_SUPERUSER_* env vars."
            )
            if options.get("strict"):
                raise CommandError(message)

            self.stdout.write(self.style.WARNING(message))
            return

        User = get_user_model()
        user_exists = User.objects.filter(username=username).exists()

        if user_exists:
            self.stdout.write(self.style.WARNING(f"- Superuser already exists: {username}"))
            return

        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"Created superuser: {username}"))
