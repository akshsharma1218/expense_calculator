import logging

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    PasswordResetView,
    PasswordResetDoneView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
)
from django.db import IntegrityError
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.shortcuts import render, redirect
from django.urls import reverse, reverse_lazy
from django.template.loader import render_to_string
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods
from django.conf import settings
from .forms import (
    CustomUserCreationForm,
    CustomAuthenticationForm,
    CustomPasswordResetForm,
    CustomSetPasswordForm,
    UserProfileForm,
)
from .models import CustomUser
from .rate_limit import is_rate_limited, retry_after


logger = logging.getLogger(__name__)
EMAIL_VERIFICATION_SALT = "users.email-verification"
EMAIL_VERIFICATION_MAX_AGE = 60 * 60 * 24


def _verification_token(user):
    return signing.dumps(
        {"user_id": user.pk, "email": user.email},
        salt=EMAIL_VERIFICATION_SALT,
    )


def _send_verification_email(request, user):
    token = _verification_token(user)
    verification_url = request.build_absolute_uri(
        reverse("users:verify_email", kwargs={"token": token})
    )
    context = {
        "first_name": user.first_name,
        "verification_url": verification_url,
    }
    print(f"Preparing to send verification email to {user.email} with URL: {verification_url}")
    try:
        message = EmailMultiAlternatives(
            subject="One step to finish your FinFlow registration",
            body=render_to_string("users/emails/email_verification.txt", context),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        print(f"Sending verification email to {user.email} with URL: {verification_url}")
        message.attach_alternative(
            render_to_string("users/emails/email_verification.html", context),
            "text/html",
        )
        if not message.send(fail_silently=False):
            return "failed"
        if settings.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend":
            return "console"
        return "sent"
    except Exception:
        print(f"Failed to send verification email to {user.email} with URL: {verification_url}")
        logger.exception("Could not send email verification message", extra={"user_id": user.pk})
        return "failed"


def _rate_limited_response(request, template_name, context, scope):
    response = render(request, template_name, context, status=429)
    response["Retry-After"] = str(retry_after(scope))
    return response


def _post_authentication_redirect(request, user):
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    if user.favorite_descriptions.exists():
        return redirect("favorite-list")
    return redirect("dashboard")


@require_http_methods(["GET", "POST"])
def signup(request):
    """User registration view."""
    if request.user.is_authenticated:
        return _post_authentication_redirect(request, request.user)

    if request.method == "POST":
        form = CustomUserCreationForm(request.POST)
        email = request.POST.get("email", "")
        if is_rate_limited(request, "signup", email):
            form.add_error(None, "Too many sign-up attempts. Please try again later.")
            return _rate_limited_response(
                request,
                "users/signup.html",
                {"form": form},
                "signup",
            )
        if form.is_valid():
            try:
                user = form.save(commit=False)
                user.is_email_verified = False
                user.is_approved = False
                user.save()
                delivery_status = _send_verification_email(request, user)
                return render(
                    request,
                    "users/verification_sent.html",
                    {"delivery_status": delivery_status},
                    status=503 if delivery_status == "failed" else 200,
                )
            except IntegrityError:
                form.add_error("email", "This email is already registered.")
        return render(request, "users/signup.html", {"form": form})
    else:
        form = CustomUserCreationForm()
    return render(request, "users/signup.html", {"form": form})


@require_http_methods(["GET", "POST"])
def login_view(request):
    """User login view."""
    if request.user.is_authenticated:
        return _post_authentication_redirect(request, request.user)

    if request.method == "POST":
        form = CustomAuthenticationForm(request.POST)
        identifier = request.POST.get("email", "")
        if is_rate_limited(request, "login", identifier):
            form.add_error(None, "Too many sign-in attempts. Please try again later.")
            return _rate_limited_response(
                request,
                "users/login.html",
                {
                    "form": form,
                    "next_url": request.POST.get("next") or request.GET.get("next", ""),
                },
                "login",
            )
        if form.is_valid():
            user = form.get_user()
            remember_me = form.cleaned_data.get("remember_me", False)
            if remember_me:
                request.session.set_expiry(30 * 24 * 60 * 60)
            else:
                request.session.set_expiry(0)
            login(request, user)
            return _post_authentication_redirect(request, user)
        return render(request, "users/login.html", {
            "form": form,
            "next_url": request.POST.get("next") or request.GET.get("next", ""),
        })
    else:
        form = CustomAuthenticationForm()
    return render(request, "users/login.html", {
        "form": form,
        "next_url": request.GET.get("next", ""),
    })


def verification_sent(request):
    return render(request, "users/verification_sent.html", {"delivery_status": "unknown"})


def verify_email(request, token):
    try:
        payload = signing.loads(
            token,
            salt=EMAIL_VERIFICATION_SALT,
            max_age=EMAIL_VERIFICATION_MAX_AGE,
        )
    except signing.SignatureExpired:
        return render(request, "users/email_verified.html", {"status": "expired"})
    except (signing.BadSignature, TypeError, ValueError):
        return render(request, "users/email_verified.html", {"status": "invalid"})

    user = CustomUser.objects.filter(
        pk=payload.get("user_id"),
        email=payload.get("email"),
    ).first()
    if user is None:
        return render(request, "users/email_verified.html", {"status": "invalid"})

    if not user.is_email_verified:
        user.is_email_verified = True
        user.save(update_fields=["is_email_verified", "updated_at"])
    status = "ready" if user.is_approved else "pending_approval"
    return render(request, "users/email_verified.html", {"status": status})


@require_http_methods(["GET", "POST"])
def resend_verification(request):
    if request.method == "GET":
        return render(request, "users/resend_verification.html")

    email = request.POST.get("email", "")
    if is_rate_limited(request, "verification_resend", email):
        response = render(request, "users/resend_verification.html", {
            "rate_limited": True,
        }, status=429)
        response["Retry-After"] = str(retry_after("verification_resend"))
        return response

    user = CustomUser.objects.filter(email__iexact=email.strip()).first()
    if user and not user.is_email_verified:
        _send_verification_email(request, user)
    return render(request, "users/resend_verification.html", {"submitted": True})


@require_http_methods(["GET", "POST"])
@login_required
def logout_view(request):
    """User logout view."""
    logout(request)
    return redirect("login")


@login_required
def profile(request):
    """User profile view."""
    if request.method == "POST":
        form = UserProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            return redirect("users:profile")
    else:
        form = UserProfileForm(instance=request.user)
    return render(request, "users/profile.html", {"form": form})


class CustomPasswordResetView(PasswordResetView):
    """Custom password reset view."""
    form_class = CustomPasswordResetForm
    template_name = "users/password_reset.html"
    email_template_name = "users/password_reset_email.html"
    success_url = reverse_lazy("users:password_reset_done")
    from_email = "noreply@finflow.app"

    def post(self, request, *args, **kwargs):
        email = request.POST.get("email", "")
        if is_rate_limited(request, "password_reset", email):
            form = self.get_form()
            form.add_error(None, "Too many password reset requests. Please try again later.")
            response = self.form_invalid(form)
            response.status_code = 429
            response["Retry-After"] = str(retry_after("password_reset"))
            return response
        return super().post(request, *args, **kwargs)


class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    """Custom password reset confirm view."""
    template_name = "users/password_reset_confirm.html"
    form_class = CustomSetPasswordForm
    success_url = reverse_lazy("users:password_reset_complete")


class CustomPasswordResetCompleteView(PasswordResetCompleteView):
    """Custom password reset complete view."""
    template_name = "users/password_reset_complete.html"
