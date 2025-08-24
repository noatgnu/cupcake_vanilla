"""
Management command to create JWT tokens for users.
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from rest_framework_simplejwt.tokens import RefreshToken


class Command(BaseCommand):
    help = "Create JWT tokens for a user"

    def add_arguments(self, parser):
        parser.add_argument("username", type=str, help="Username to create token for")

    def handle(self, *args, **options):
        username = options["username"]

        try:
            user = User.objects.get(username=username)
            refresh = RefreshToken.for_user(user)
            access_token = refresh.access_token

            # Add custom claims
            access_token["username"] = user.username
            access_token["email"] = user.email
            access_token["is_staff"] = user.is_staff
            access_token["is_superuser"] = user.is_superuser

            self.stdout.write(self.style.SUCCESS(f"JWT tokens created for user: {username}"))
            self.stdout.write(f"Access Token: {access_token}")
            self.stdout.write(f"Refresh Token: {refresh}")

        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User "{username}" does not exist'))
