from django.contrib.auth.backends import ModelBackend


class VerifiedApprovedBackend(ModelBackend):
    def user_can_authenticate(self, user):
        return (
            super().user_can_authenticate(user)
            and user.is_email_verified
            and user.is_approved
        )
