from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib import messages
from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(BaseUserAdmin):
    """Custom user admin."""
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "phone_number")}),
        ("Permissions", {
            "fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions"),
        }),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
        ("Account approval", {"fields": ("is_approved", "is_email_verified")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "password1", "password2"),
        }),
    )
    list_display = (
        "email",
        "first_name",
        "last_name",
        "phone_number",
        "is_approved",
        "is_email_verified",
        "is_staff",
    )
    list_editable = ("is_approved",)
    list_filter = (
        "is_approved",
        "is_email_verified",
        "is_staff",
        "is_superuser",
        "is_active",
        "date_joined",
    )
    search_fields = ("email", "first_name", "last_name", "phone_number")
    ordering = ("-date_joined",)
    actions = ("approve_selected",)

    @admin.action(description="Approve selected accounts")
    def approve_selected(self, request, queryset):
        updated = queryset.update(is_approved=True)
        self.message_user(
            request,
            f"{updated} account(s) approved. Email verification is still required.",
            level=messages.SUCCESS,
        )
