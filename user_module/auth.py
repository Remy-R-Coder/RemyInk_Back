from django.contrib.auth.tokens import PasswordResetTokenGenerator

class AutoLoginTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user, timestamp):
        return f"{user.pk}{timestamp}{user.is_active}"

autologin_token_generator = AutoLoginTokenGenerator()
