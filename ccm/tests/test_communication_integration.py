"""
Tests for CCM-CCMC integration functionality.

Tests the optional communication layer integration between CCM and CCMC apps.
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from ccm.communication import (
    create_instrument_thread,
    get_instrument_notifications,
    get_instrument_threads,
    is_ccmc_available,
    send_maintenance_alert,
    send_notification,
    send_reagent_alert,
)
from ccm.models import Instrument, MaintenanceLog, Reagent, StoredReagent, SupportInformation

User = get_user_model()


class CommunicationAvailabilityTest(TestCase):
    """Test CCMC availability detection."""

    @override_settings(INSTALLED_APPS=["ccm"])
    def test_ccmc_not_available(self):
        """Test detection when CCMC is not in INSTALLED_APPS."""
        self.assertFalse(is_ccmc_available())

    @override_settings(INSTALLED_APPS=["ccm", "ccmc"])
    @patch("ccm.communication.apps.is_installed")
    def test_ccmc_available(self, mock_is_installed):
        """Test detection when CCMC is installed."""
        mock_is_installed.return_value = True
        self.assertTrue(is_ccmc_available())


class NotificationIntegrationTest(TestCase):
    """Test notification integration with CCMC."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@test.com")
        self.instrument = Instrument.objects.create(instrument_name="Test Instrument", user=self.user)

    @patch("ccm.communication.is_ccmc_available")
    def test_send_notification_ccmc_unavailable(self, mock_available):
        """Test notification sending when CCMC is unavailable."""
        mock_available.return_value = False

        result = send_notification(title="Test Notification", message="Test message", recipient=self.user)

        self.assertFalse(result)

    @patch("ccm.communication.is_ccmc_available")
    @patch("ccmc.models.Notification.objects.create")
    def test_send_notification_ccmc_available(self, mock_create, mock_available):
        """Test notification sending when CCMC is available."""
        mock_available.return_value = True
        mock_notification = MagicMock()
        mock_notification.id = "test-uuid"
        mock_create.return_value = mock_notification

        result = send_notification(
            title="Test Notification",
            message="Test message",
            recipient=self.user,
            related_object=self.instrument,
            data={"test": "data"},
        )

        self.assertTrue(result)
        mock_create.assert_called_once()


class MaintenanceAlertIntegrationTest(TestCase):
    """Test maintenance alert integration."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@test.com")
        self.instrument = Instrument.objects.create(instrument_name="Test Instrument", user=self.user)

    @patch("ccm.communication.is_ccmc_available")
    def test_maintenance_alert_ccmc_unavailable(self, mock_available):
        """Test maintenance alert when CCMC unavailable."""
        mock_available.return_value = False

        result = send_maintenance_alert(instrument=self.instrument, message_type="maintenance_due")

        self.assertFalse(result)

    @patch("ccm.communication.send_notification")
    @patch("ccm.communication.is_ccmc_available")
    def test_maintenance_due_alert(self, mock_available, mock_send):
        """Test maintenance due alert."""
        mock_available.return_value = True
        mock_send.return_value = True

        result = send_maintenance_alert(
            instrument=self.instrument, message_type="maintenance_due", maintenance_info={"frequency_days": 30}
        )

        self.assertTrue(result)
        mock_send.assert_called_once()

        # Check the call arguments
        call_args = mock_send.call_args[1]
        self.assertIn("Maintenance Due", call_args["title"])
        self.assertEqual(call_args["notification_type"], "maintenance")
        self.assertEqual(call_args["priority"], "high")

    @patch("ccm.communication.send_notification")
    @patch("ccm.communication.is_ccmc_available")
    def test_warranty_expiring_alert(self, mock_available, mock_send):
        """Test warranty expiring alert."""
        mock_available.return_value = True
        mock_send.return_value = True

        result = send_maintenance_alert(
            instrument=self.instrument, message_type="warranty_expiring", maintenance_info={"days_remaining": 15}
        )

        self.assertTrue(result)
        mock_send.assert_called_once()

        call_args = mock_send.call_args[1]
        self.assertIn("Warranty Expiring", call_args["title"])


class ReagentAlertIntegrationTest(TestCase):
    """Test reagent alert integration."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@test.com")
        self.reagent = Reagent.objects.create(name="Test Reagent")
        self.stored_reagent = StoredReagent.objects.create(reagent=self.reagent, quantity=5.0, user=self.user)

    @patch("ccm.communication.is_ccmc_available")
    def test_reagent_alert_ccmc_unavailable(self, mock_available):
        """Test reagent alert when CCMC unavailable."""
        mock_available.return_value = False

        result = send_reagent_alert(stored_reagent=self.stored_reagent, alert_type="low_stock")

        self.assertFalse(result)

    @patch("ccm.communication.send_notification")
    @patch("ccm.communication.is_ccmc_available")
    def test_low_stock_alert(self, mock_available, mock_send):
        """Test low stock alert."""
        mock_available.return_value = True
        mock_send.return_value = True

        result = send_reagent_alert(stored_reagent=self.stored_reagent, alert_type="low_stock")

        self.assertTrue(result)
        mock_send.assert_called_once()

        call_args = mock_send.call_args[1]
        self.assertIn("Low Stock Alert", call_args["title"])
        self.assertEqual(call_args["notification_type"], "inventory")
        self.assertEqual(call_args["priority"], "high")


class InstrumentCommunicationTest(TestCase):
    """Test instrument communication methods."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@test.com")
        self.instrument = Instrument.objects.create(instrument_name="Test Instrument", user=self.user)

    @patch("ccm.communication.is_ccmc_available")
    def test_create_instrument_thread_ccmc_unavailable(self, mock_available):
        """Test thread creation when CCMC unavailable."""
        mock_available.return_value = False

        result = create_instrument_thread(instrument=self.instrument, title="Test Thread")

        self.assertIsNone(result)

    @patch("ccmc.models.MessageThread.objects.create")
    @patch("ccm.communication.is_ccmc_available")
    def test_create_instrument_thread_ccmc_available(self, mock_available, mock_create):
        """Test thread creation when CCMC available."""
        mock_available.return_value = True
        mock_thread = MagicMock()
        mock_create.return_value = mock_thread

        result = create_instrument_thread(
            instrument=self.instrument, title="Test Thread", description="Test description", participants=[self.user]
        )

        self.assertEqual(result, mock_thread)
        mock_create.assert_called_once()

    @patch("ccm.communication.is_ccmc_available")
    def test_get_instrument_notifications_ccmc_unavailable(self, mock_available):
        """Test getting notifications when CCMC unavailable."""
        mock_available.return_value = False

        result = get_instrument_notifications(self.instrument)

        self.assertEqual(result, [])

    @patch("ccm.communication.is_ccmc_available")
    def test_get_instrument_threads_ccmc_unavailable(self, mock_available):
        """Test getting threads when CCMC unavailable."""
        mock_available.return_value = False

        result = get_instrument_threads(self.instrument)

        self.assertEqual(result, [])


class InstrumentModelIntegrationTest(TestCase):
    """Test CCM model methods with CCMC integration."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@test.com")
        self.instrument = Instrument.objects.create(instrument_name="Test Instrument", user=self.user)

        # Create support information with warranty and maintenance
        self.support_info = SupportInformation.objects.create(
            vendor_name="Test Vendor",
            warranty_end_date=date.today() + timedelta(days=15),
            maintenance_frequency_days=90,
        )
        self.instrument.support_information.add(self.support_info)

    @patch("ccm.communication.send_maintenance_alert")
    def test_check_warranty_expiration_with_ccmc(self, mock_send_alert):
        """Test warranty expiration check with CCMC integration."""
        mock_send_alert.return_value = True

        result = self.instrument.check_warranty_expiration(days_threshold=30)

        self.assertTrue(result)
        mock_send_alert.assert_called_once()

        # Verify the call arguments
        call_kwargs = mock_send_alert.call_args[1]
        self.assertEqual(call_kwargs["instrument"], self.instrument)
        self.assertEqual(call_kwargs["message_type"], "warranty_expiring")
        self.assertIn("warranty_end_date", call_kwargs["maintenance_info"])

    @patch("ccm.communication.send_maintenance_alert")
    def test_check_upcoming_maintenance_with_ccmc(self, mock_send_alert):
        """Test maintenance check with CCMC integration."""
        mock_send_alert.return_value = True

        result = self.instrument.check_upcoming_maintenance(days_threshold=120)

        self.assertTrue(result)
        mock_send_alert.assert_called_once()

        call_kwargs = mock_send_alert.call_args[1]
        self.assertEqual(call_kwargs["message_type"], "maintenance_due")


class StoredReagentIntegrationTest(TestCase):
    """Test StoredReagent model methods with CCMC integration."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@test.com")
        self.reagent = Reagent.objects.create(name="Test Reagent")
        self.stored_reagent = StoredReagent.objects.create(
            reagent=self.reagent,
            quantity=2.0,
            user=self.user,
            low_stock_threshold=5.0,
            notify_on_low_stock=True,
            expiration_date=date.today() + timedelta(days=3),
        )

    @patch("ccm.communication.send_reagent_alert")
    def test_check_low_stock_with_ccmc(self, mock_send_alert):
        """Test low stock check with CCMC integration."""
        mock_send_alert.return_value = True

        result = self.stored_reagent.check_low_stock()

        self.assertTrue(result)
        mock_send_alert.assert_called_once()

        call_kwargs = mock_send_alert.call_args[1]
        self.assertEqual(call_kwargs["stored_reagent"], self.stored_reagent)
        self.assertEqual(call_kwargs["alert_type"], "low_stock")

    @patch("ccm.communication.send_reagent_alert")
    def test_check_expiration_with_ccmc(self, mock_send_alert):
        """Test expiration check with CCMC integration."""
        mock_send_alert.return_value = True

        result = self.stored_reagent.check_expiration(days_threshold=7)

        self.assertTrue(result)
        mock_send_alert.assert_called_once()

        call_kwargs = mock_send_alert.call_args[1]
        self.assertEqual(call_kwargs["alert_type"], "expiring_soon")

    @patch("ccm.communication.send_reagent_alert")
    def test_check_expired_reagent_with_ccmc(self, mock_send_alert):
        """Test expired reagent check with CCMC integration."""
        # Set expiration to past date
        self.stored_reagent.expiration_date = date.today() - timedelta(days=1)
        self.stored_reagent.save()

        mock_send_alert.return_value = True

        result = self.stored_reagent.check_expiration()

        self.assertTrue(result)
        mock_send_alert.assert_called_once()

        call_kwargs = mock_send_alert.call_args[1]
        self.assertEqual(call_kwargs["alert_type"], "expired")


class SignalIntegrationTest(TestCase):
    """Test signal handlers with CCMC integration."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@test.com")
        self.instrument = Instrument.objects.create(instrument_name="Test Instrument", user=self.user)

    @patch("ccm.signals.send_maintenance_alert")
    @patch("ccm.signals.is_ccmc_available")
    def test_maintenance_log_signal(self, mock_available, mock_send_alert):
        """Test maintenance log completion signal."""
        mock_available.return_value = True
        mock_send_alert.return_value = True

        # Create completed maintenance log
        MaintenanceLog.objects.create(
            instrument=self.instrument,
            status="completed",
            maintenance_type="routine",
            maintenance_date=timezone.now(),
            maintenance_description="Test maintenance",
            created_by=self.user,
        )

        # Signal should trigger
        mock_send_alert.assert_called_once()
        call_kwargs = mock_send_alert.call_args[1]
        self.assertEqual(call_kwargs["message_type"], "maintenance_completed")


class ManagementCommandIntegrationTest(TestCase):
    """Test management command with CCMC integration."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@test.com")

        # Create instrument with warranty and maintenance
        self.instrument = Instrument.objects.create(instrument_name="Test Instrument", user=self.user, enabled=True)

        support_info = SupportInformation.objects.create(
            warranty_end_date=date.today() + timedelta(days=15), maintenance_frequency_days=30
        )
        self.instrument.support_information.add(support_info)

        # Create reagent with low stock
        reagent = Reagent.objects.create(name="Test Reagent")
        self.stored_reagent = StoredReagent.objects.create(
            reagent=reagent,
            quantity=1.0,
            low_stock_threshold=5.0,
            notify_on_low_stock=True,
            expiration_date=date.today() + timedelta(days=3),
        )

    @patch("ccm.management.commands.check_ccm_alerts.is_ccmc_available")
    def test_command_with_ccmc_unavailable(self, mock_available):
        """Test command execution when CCMC is unavailable."""
        from io import StringIO

        from django.core.management import call_command

        mock_available.return_value = False

        out = StringIO()
        call_command("check_ccm_alerts", stdout=out)

        output = out.getvalue()
        self.assertIn("CCMC not available", output)
        self.assertIn("no notifications", output)

    @patch("ccm.communication.is_ccmc_available")
    @patch("ccm.communication.send_maintenance_alert")
    @patch("ccm.communication.send_reagent_alert")
    def test_command_with_ccmc_available(self, mock_reagent_alert, mock_maintenance_alert, mock_available):
        """Test command execution when CCMC is available."""
        from io import StringIO

        from django.core.management import call_command

        mock_available.return_value = True
        mock_maintenance_alert.return_value = True
        mock_reagent_alert.return_value = True

        out = StringIO()
        call_command("check_ccm_alerts", stdout=out)

        output = out.getvalue()
        self.assertIn("CCMC communications available", output)
        self.assertIn("notifications will be sent", output)
