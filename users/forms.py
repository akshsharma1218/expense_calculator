from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import UserCreationForm, PasswordResetForm, SetPasswordForm
from django.core.exceptions import ValidationError
from .models import CustomUser


class CustomUserCreationForm(UserCreationForm):
    """Enhanced user registration form with phone number."""

    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "placeholder": "your@email.com",
            "autocomplete": "email",
        }),
    )
    first_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "First Name",
        }),
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Last Name",
        }),
    )
    phone_number = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "+1234567890",
            "type": "tel",
        }),
        help_text="Format: +1234567890",
    )
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "••••••••",
            "autocomplete": "new-password",
        }),
    )
    password2 = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "••••••••",
            "autocomplete": "new-password",
        }),
    )

    class Meta:
        model = CustomUser
        fields = ("email", "first_name", "last_name", "phone_number", "password1", "password2")

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if CustomUser.objects.filter(email=email).exists():
            raise ValidationError("This email is already registered.")
        return email

    def clean_phone_number(self):
        phone = self.cleaned_data.get("phone_number")
        if phone and not phone.replace("+", "").replace("-", "").isdigit():
            raise ValidationError("Phone number must contain only digits, +, or -.")
        return phone

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class CustomAuthenticationForm(forms.Form):
    """Enhanced login form."""

    email = forms.CharField(
        label="Email, phone number, or username",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Email, phone number, or username",
            "autocomplete": "username",
            "autofocus": True,
        }),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "Enter your password",
            "autocomplete": "current-password",
        }),
    )
    remember_me = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            "class": "form-check-input",
        }),
        label="Remember me",
    )

    def clean(self):
        identifier = self.cleaned_data.get("email")
        password = self.cleaned_data.get("password")

        if identifier and password:
            user = CustomUser.objects.find_by_identifier(identifier)
            self.user_cache = (
                authenticate(username=user.email, password=password)
                if user else None
            )
            if self.user_cache is None:
                raise ValidationError("Invalid email, phone number, username, or password.")
        return self.cleaned_data

    def get_user(self):
        return getattr(self, "user_cache", None)


class CustomPasswordResetForm(PasswordResetForm):
    """Enhanced password reset form."""

    email = forms.EmailField(
        label="Email",
        max_length=254,
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "placeholder": "your@email.com",
            "autocomplete": "email",
            "autofocus": True,
        }),
    )

class CustomSetPasswordForm(SetPasswordForm):
    """Enhanced set password form."""

    new_password1 = forms.CharField(
        label="New Password",
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "••••••••",
            "autocomplete": "new-password",
        }),
        strip=False,
    )
    new_password2 = forms.CharField(
        label="Confirm New Password",
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "••••••••",
            "autocomplete": "new-password",
        }),
        strip=False,
    )


class UserProfileForm(forms.ModelForm):
    """Form for updating user profile."""

    class Meta:
        model = CustomUser
        fields = ("first_name", "last_name", "phone_number", "email")
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone_number": forms.TextInput(attrs={
                "class": "form-control",
                "type": "tel",
            }),
            "email": forms.EmailInput(attrs={
                "class": "form-control",
                "readonly": True,
            }),
        }
