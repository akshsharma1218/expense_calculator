from django.contrib.auth.views import PasswordResetDoneView
from django.test import SimpleTestCase
from django.urls import reverse, resolve

from .forms import CustomPasswordResetForm


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