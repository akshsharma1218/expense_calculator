from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.views import PasswordResetDoneView
from django.core.exceptions import ValidationError
from django.core import mail
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse, resolve

from .forms import CustomPasswordResetForm, UserProfileForm


class RememberMeAuthTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="rememberme@example.com",
            username="rememberme",
            password="strong-password-123",
        )

    def test_login_remember_me_sets_30_day_session_expiry(self):
        response = self.client.post(
            reverse("users:login"),
            {
                "email": self.user.email,
                "password": "strong-password-123",
                "remember_me": "on",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("dashboard", response.request["PATH_INFO"])
        self.assertEqual(self.client.session.get_expiry_age(), 30 * 24 * 60 * 60)

    def test_login_without_remember_me_uses_browser_session_expiry(self):
        response = self.client.post(
            reverse("users:login"),
            {
                "email": self.user.email,
                "password": "strong-password-123",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("dashboard", response.request["PATH_INFO"])
        self.assertEqual(self.client.session.get_expiry_age(), 0)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SignupApprovalAndRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_signup_requires_email_verification_and_admin_approval(self):
        response = self.client.post(
            reverse("users:signup"),
            {
                "email": "pending@example.com",
                "first_name": "Pending",
                "last_name": "User",
                "phone_number": "",
                "password1": "Strong-password-123!",
                "password2": "Strong-password-123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["delivery_status"], "sent")
        user = get_user_model().objects.get(email="pending@example.com")
        self.assertFalse(user.is_email_verified)
        self.assertFalse(user.is_approved)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].alternatives[0][1], "text/html")
        self.assertIn("Verify email", mail.outbox[0].alternatives[0][0])
        self.assertIn("administrator must approve", mail.outbox[0].body)

        verification_url = next(
            line for line in mail.outbox[0].body.splitlines()
            if line.startswith("http://testserver/")
        )
        response = self.client.get(verification_url.replace("http://testserver", ""))
        self.assertContains(response, "waiting for an administrator")
        user.refresh_from_db()
        self.assertTrue(user.is_email_verified)

        response = self.client.post(
            reverse("users:login"),
            {"email": user.email, "password": "Strong-password-123!"},
        )
        self.assertContains(response, "waiting for administrator approval")
        self.assertNotIn("_auth_user_id", self.client.session)

        user.is_approved = True
        user.save(update_fields=["is_approved"])
        response = self.client.post(
            reverse("users:login"),
            {"email": user.email, "password": "Strong-password-123!"},
        )
        self.assertRedirects(response, reverse("dashboard"))

    def test_login_attempts_are_rate_limited(self):
        user = get_user_model().objects.create_user(
            email="throttle@example.com",
            username="throttle",
            password="Strong-password-123!",
        )

        for _ in range(5):
            response = self.client.post(
                reverse("users:login"),
                {"email": user.email, "password": "incorrect-password"},
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("users:login"),
            {"email": user.email, "password": "incorrect-password"},
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "900")

    def test_signup_attempts_are_rate_limited_by_ip(self):
        for attempt in range(5):
            response = self.client.post(
                reverse("users:signup"),
                {"email": f"invalid-{attempt}@example.com"},
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("users:signup"),
            {"email": "sixth@example.com"},
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "3600")


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