from django.urls import path
from . import views

app_name = "users"

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("login/", views.login_view, name="login"),
    path("verification-sent/", views.verification_sent, name="verification_sent"),
    path("verify-email/<str:token>/", views.verify_email, name="verify_email"),
    path("resend-verification/", views.resend_verification, name="resend_verification"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile, name="profile"),
    path("password-reset/", views.CustomPasswordResetView.as_view(), name="password_reset"),
    path(
        "password-reset/done/",
        views.PasswordResetDoneView.as_view(template_name="users/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "password-reset/<uidb64>/<token>/",
        views.CustomPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        views.CustomPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
]
