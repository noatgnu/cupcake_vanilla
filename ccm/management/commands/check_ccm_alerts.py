"""
Management command to check all CCM alerts and send notifications via CCMC if available.

Usage:
    python manage.py check_ccm_alerts [--warranty-days 30] [--maintenance-days 14] [--expiry-days 7]
"""

from django.core.management.base import BaseCommand

from ccm.communication import is_ccmc_available
from ccm.models import Instrument, StoredReagent


class Command(BaseCommand):
    help = "Check all instruments and reagents for alerts (maintenance, warranty, low stock, expiry)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--warranty-days", type=int, default=30, help="Days before warranty expiry to trigger alerts (default: 30)"
        )
        parser.add_argument(
            "--maintenance-days",
            type=int,
            default=14,
            help="Days before maintenance due to trigger alerts (default: 14)",
        )
        parser.add_argument(
            "--expiry-days", type=int, default=7, help="Days before reagent expiry to trigger alerts (default: 7)"
        )

    def handle(self, *args, **options):
        warranty_days = options["warranty_days"]
        maintenance_days = options["maintenance_days"]
        expiry_days = options["expiry_days"]

        self.stdout.write(self.style.SUCCESS("Starting CCM alert checks..."))

        if is_ccmc_available():
            self.stdout.write("CCMC communications available - notifications will be sent")
        else:
            self.stdout.write(self.style.WARNING("CCMC not available - no notifications will be sent"))

        # Check instrument alerts
        self.stdout.write("\n--- Checking Instrument Alerts ---")
        warranty_count = 0
        maintenance_count = 0
        instrument_count = 0

        instruments = Instrument.objects.filter(enabled=True).prefetch_related("support_information")

        for instrument in instruments:
            instrument_count += 1

            if instrument.check_warranty_expiration(warranty_days):
                warranty_count += 1
                self.stdout.write(f"Warranty alert: {instrument.instrument_name}")

            if instrument.check_upcoming_maintenance(maintenance_days):
                maintenance_count += 1
                self.stdout.write(f"Maintenance alert: {instrument.instrument_name}")

        self.stdout.write(f"Checked {instrument_count} instruments")
        self.stdout.write(f"Warranty alerts sent: {warranty_count}")
        self.stdout.write(f"Maintenance alerts sent: {maintenance_count}")

        # Check reagent alerts
        self.stdout.write("\n--- Checking Reagent Alerts ---")
        low_stock_count = 0
        expiry_count = 0
        reagent_count = 0

        stored_reagents = StoredReagent.objects.all().select_related("reagent")

        for reagent in stored_reagents:
            reagent_count += 1

            if reagent.check_low_stock():
                low_stock_count += 1
                self.stdout.write(f"Low stock alert: {reagent.reagent.name}")

            if reagent.check_expiration(expiry_days):
                expiry_count += 1
                self.stdout.write(f"Expiry alert: {reagent.reagent.name}")

        self.stdout.write(f"Checked {reagent_count} reagents")
        self.stdout.write(f"Low stock alerts sent: {low_stock_count}")
        self.stdout.write(f"Expiry alerts sent: {expiry_count}")

        # Summary
        total_alerts = warranty_count + maintenance_count + low_stock_count + expiry_count
        self.stdout.write(self.style.SUCCESS(f"\nAlert check complete! Total alerts sent: {total_alerts}"))
