from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    PasswordResetView,
    PasswordResetDoneView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
)
from django.db import IntegrityError
from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods
from .forms import (
    CustomUserCreationForm,
    CustomAuthenticationForm,
    CustomPasswordResetForm,
    CustomSetPasswordForm,
    UserProfileForm,
)
from .models import CustomUser


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
        if form.is_valid():
            try:
                user = form.save()
                login(request, user)
                return _post_authentication_redirect(request, user)
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
        if form.is_valid():
            user = form.get_user()
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


class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    """Custom password reset confirm view."""
    template_name = "users/password_reset_confirm.html"
    form_class = CustomSetPasswordForm
    success_url = reverse_lazy("users:password_reset_complete")


class CustomPasswordResetCompleteView(PasswordResetCompleteView):
    """Custom password reset complete view."""
    template_name = "users/password_reset_complete.html"
