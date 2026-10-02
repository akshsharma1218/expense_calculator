from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.views import PasswordResetDoneView
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from django.urls import reverse, resolve

from .forms import CustomPasswordResetForm, UserProfileForm


class CustomUserAuthRelationTests(TestCase):

    def test_groups_and_permissions_use_custom_user_through_columns(self):
        user = get_user_model().objects.create_user(
            email="auth-relations@example.com",
            username="auth-relations",
            password="test-password",
        )
        group = Group.objects.create(name="auth-relations")
        permission = Permission.objects.order_by("pk").first()

        user.groups.add(group)
        user.user_permissions.add(permission)

        self.assertIn(group, user.groups.all())
        self.assertIn(permission, user.user_permissions.all())

    def test_phone_number_is_unique_but_optional_values_can_repeat(self):
        user_model = get_user_model()
        user_model.objects.create_user(
            email="phone-owner@example.com",
            username="phone-owner",
            phone_number="+15551234567",
            password="test-password",
        )
        duplicate_phone_user = user_model(
            email="phone-duplicate@example.com",
            username="phone-duplicate",
            phone_number="+15551234567",
        )

        with self.assertRaises(ValidationError):
            duplicate_phone_user.full_clean()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                user_model.objects.create_user(
                    email="phone-duplicate@example.com",
                    username="phone-duplicate",
                    phone_number="+15551234567",
                    password="test-password",
                )

        user_model.objects.create_user(
            email="no-phone-one@example.com",
            username="no-phone-one",
            phone_number="",
            password="test-password",
        )
        user_model.objects.create_user(
            email="no-phone-two@example.com",
            username="no-phone-two",
            phone_number="",
            password="test-password",
        )


class PasswordResetFlowTests(SimpleTestCase):

    def test_reset_urls_are_namespaced_and_resolvable(self):
        urls = {
            "users:password_reset": "/auth/password-reset/",
            "users:password_reset_done": "/auth/password-reset/done/",
            "users:password_reset_confirm": "/auth/password-reset/MQ/token/",
            "users:password_reset_complete": "/auth/password-reset/complete/",
        }

        for name, expected_path in urls.items():
            with self.subTest(name=name):
                self.assertEqual(reverse(name, kwargs={"uidb64": "MQ", "token": "token"}) if name.endswith("confirm") else reverse(name), expected_path)

    def test_reset_done_route_uses_the_sent_instructions_view(self):
        match = resolve(reverse("users:password_reset_done"))

        self.assertIs(match.func.view_class, PasswordResetDoneView)
        response = self.client.get(reverse("users:password_reset_done"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/password_reset_done.html")

    def test_reset_form_does_not_disclose_unknown_email_addresses(self):
        form = CustomPasswordResetForm(data={"email": "not-registered@example.com"})

        self.assertTrue(form.is_valid())


class UserProfileTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="profile-user@example.com",
            username="profile-user",
            password="profile-test-password",
        )
        self.client.force_login(self.user)

    def test_profile_can_be_opened_and_saved(self):
        profile_url = reverse("users:profile")
        self.assertEqual(self.client.get(profile_url).status_code, 200)

        response = self.client.post(
            profile_url,
            {
                "first_name": "Profile",
                "last_name": "User",
                "phone_number": "+15551234567",
                "email": self.user.email,
            },
        )

        self.assertRedirects(response, profile_url)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Profile")
        self.assertEqual(self.user.phone_number, "+15551234567")

    def test_profile_rejects_phone_number_owned_by_another_user(self):
        get_user_model().objects.create_user(
            email="profile-other@example.com",
            username="profile-other",
            phone_number="+15557654321",
            password="profile-test-password",
        )

        form = UserProfileForm(
            data={
                "first_name": "",
                "last_name": "",
                "phone_number": "+15557654321",
                "email": self.user.email,
            },
            instance=self.user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("already in use", str(form.errors["phone_number"]))