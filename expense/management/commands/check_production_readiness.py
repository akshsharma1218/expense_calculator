"""
Django management command to check production deployment readiness.
Usage: python manage.py check_production_readiness
"""
import os
import sys
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings


class Command(BaseCommand):
    help = 'Check if Django project is ready for production deployment'

    def add_arguments(self, parser):
        parser.add_argument(
            '--strict',
            action='store_true',
            dest='strict',
            help='Exit with error code if any issues found',
        )

    def handle(self, *args, **options):
        issues = []
        warnings = []

        self.stdout.write(self.style.SUCCESS('Checking Production Readiness...'))
        self.stdout.write('-' * 50)

        # 1. DEBUG mode
        if settings.DEBUG:
            issues.append('ERROR: DEBUG is set to True (should be False in production)')
        else:
            self.stdout.write(self.style.SUCCESS('SUCCESS: DEBUG is False'))

        # 2. SECRET_KEY
        if 'insecure' in settings.SECRET_KEY.lower() or settings.SECRET_KEY == 'django-insecure-dev-key-only-for-development':
            issues.append('ERROR: SECRET_KEY is using development default (must be changed for production)')
        else:
            self.stdout.write(self.style.SUCCESS('SUCCESS: SECRET_KEY is set'))

        # 3. ALLOWED_HOSTS
        if '*' in settings.ALLOWED_HOSTS:
            issues.append('ERROR: ALLOWED_HOSTS contains wildcard * (should be specific domains)')
        elif len(settings.ALLOWED_HOSTS) == 0:
            issues.append('ERROR: ALLOWED_HOSTS is empty')
        else:
            self.stdout.write(self.style.SUCCESS(f'SUCCESS: ALLOWED_HOSTS configured: {settings.ALLOWED_HOSTS}'))

        # 4. SSL/HTTPS
        if not settings.SECURE_SSL_REDIRECT:
            warnings.append('WARN: SECURE_SSL_REDIRECT is False (should be True in production)')
        else:
            self.stdout.write(self.style.SUCCESS('SUCCESS: SECURE_SSL_REDIRECT is True'))

        if not settings.SESSION_COOKIE_SECURE:
            warnings.append('WARN: SESSION_COOKIE_SECURE is False (should be True in production)')
        else:
            self.stdout.write(self.style.SUCCESS('SUCCESS: SESSION_COOKIE_SECURE is True'))

        if not settings.CSRF_COOKIE_SECURE:
            warnings.append('WARN: CSRF_COOKIE_SECURE is False (should be True in production)')
        else:
            self.stdout.write(self.style.SUCCESS('SUCCESS: CSRF_COOKIE_SECURE is True'))

        # 5. HSTS
        if settings.SECURE_HSTS_SECONDS == 0:
            warnings.append('WARN: SECURE_HSTS_SECONDS is 0 (recommended to set to 31536000 in production)')
        else:
            self.stdout.write(self.style.SUCCESS(f'SUCCESS: HSTS enabled: {settings.SECURE_HSTS_SECONDS} seconds'))

        # 6. Database
        db_config = settings.DATABASES.get('default', {})
        if db_config.get('ENGINE') == 'django.db.backends.sqlite3':
            issues.append('ERROR: Using SQLite database (should use PostgreSQL in production)')
        else:
            self.stdout.write(self.style.SUCCESS(f'SUCCESS: Using {db_config.get("ENGINE")} database'))

        # 7. Static files
        if not settings.STATIC_ROOT:
            issues.append('ERROR: STATIC_ROOT is not configured')
        else:
            self.stdout.write(self.style.SUCCESS(f'SUCCESS: STATIC_ROOT configured: {settings.STATIC_ROOT}'))

        # 8. Logging
        if not settings.LOGGING:
            warnings.append('WARN: Logging is not configured')
        else:
            self.stdout.write(self.style.SUCCESS('SUCCESS: Logging is configured'))

        # 9. Environment
        environment = os.getenv('ENVIRONMENT', 'development')
        if environment != 'production':
            warnings.append(f'WARN: ENVIRONMENT is {environment} (should be production)')
        else:
            self.stdout.write(self.style.SUCCESS('SUCCESS: ENVIRONMENT is production'))

        # Print warnings
        self.stdout.write('-' * 50)
        if warnings:
            self.stdout.write(self.style.WARNING('Warnings:'))
            for warning in warnings:
                self.stdout.write(self.style.WARNING(warning))

        # Print issues
        if issues:
            self.stdout.write('-' * 50)
            self.stdout.write(self.style.ERROR('Critical Issues:'))
            for issue in issues:
                self.stdout.write(self.style.ERROR(issue))

        # Summary
        self.stdout.write('-' * 50)
        if issues:
            self.stdout.write(self.style.ERROR(f'ERROR: {len(issues)} critical issue(s) found'))
            if options.get('strict'):
                sys.exit(1)
        else:
            self.stdout.write(self.style.SUCCESS('SUCCESS: All checks passed!'))
