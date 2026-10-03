from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class CustomUserManager(BaseUserManager):
    """Custom user manager with email as username."""

    def find_by_identifier(self, identifier):
        identifier = (identifier or "").strip()
        if not identifier:
            return None

        matches = list(
            self.filter(
                Q(email__iexact=identifier)
                | Q(username__iexact=identifier)
                | Q(phone_number__iexact=identifier)
            ).distinct()[:2]
        )
        return matches[0] if len(matches) == 1 else None

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_("Email is required"))
        extra_fields.setdefault("is_approved", True)
        extra_fields.setdefault("is_email_verified", True)
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_approved", True)
        extra_fields.setdefault("is_email_verified", True)

        if not extra_fields.get("is_staff"):
            raise ValueError(_("Superuser must have is_staff=True"))
        if not extra_fields.get("is_superuser"):
            raise ValueError(_("Superuser must have is_superuser=True"))

        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractUser):
    """Custom user model with phone number field."""

    email = models.EmailField(_("email address"), unique=True)
    phone_number = models.CharField(
        _("phone number"),
        max_length=15,
        blank=True,
        null=True,
        help_text=_("Phone number format: +1234567890"),
    )
    is_email_verified = models.BooleanField(
        _("email verified"),
        default=False,
        help_text=_("Designates whether this user's email has been verified."),
    )
    is_approved = models.BooleanField(
        _("approved"),
        default=False,
        help_text=_("Designates whether an administrator approved this account."),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    objects = CustomUserManager()

    class Meta:
        # Reuses the pre-existing 'auth_user' table so every foreign key that
        # already points at it (Account, Transaction, GroupMember, ...) keeps
        # working without any data migration.
        db_table = "auth_user"
        verbose_name = _("user")
        verbose_name_plural = _("users")
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["phone_number"],
                condition=Q(phone_number__isnull=False) & ~Q(phone_number=""),
                name="unique_customuser_phone_number",
            ),
        ]

    def __str__(self):
        return self.email

    def get_full_name_or_email(self):
        """Return full name or email if name is not available."""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.email
