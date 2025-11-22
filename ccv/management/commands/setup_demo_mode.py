from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from ccv.models import LabGroup

User = get_user_model()


class Command(BaseCommand):
    help = "Setup demo mode with demo user and lab group"

    def handle(self, *args, **options):
        if not settings.DEMO_MODE:
            self.stdout.write(
                self.style.WARNING("Demo mode is not enabled. Set DEMO_MODE=True in environment variables.")
            )
            return

        demo_username = settings.DEMO_USER_USERNAME
        demo_password = settings.DEMO_USER_PASSWORD
        demo_email = settings.DEMO_USER_EMAIL

        user, created = User.objects.get_or_create(
            username=demo_username,
            defaults={
                "email": demo_email,
                "first_name": "Demo",
                "last_name": "User",
                "is_active": True,
                "is_staff": False,
                "is_superuser": False,
            },
        )

        if created:
            user.set_password(demo_password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Created demo user: {demo_username}"))
        else:
            user.set_password(demo_password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Demo user already exists: {demo_username}, password updated"))

        lab_group, created = LabGroup.objects.get_or_create(
            name="Demo Lab Group",
            defaults={
                "description": "Demo lab group for testing",
                "is_active": True,
            },
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f"Created demo lab group: {lab_group.name}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Demo lab group already exists: {lab_group.name}"))

        if user not in lab_group.members.all():
            lab_group.members.add(user)
            self.stdout.write(self.style.SUCCESS(f"Added {demo_username} to {lab_group.name}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDemo mode setup complete!\n"
                f"Username: {demo_username}\n"
                f"Password: {demo_password}\n"
                f"Email: {demo_email}\n"
                f"Cleanup interval: {settings.DEMO_CLEANUP_INTERVAL_MINUTES} minutes"
            )
        )
