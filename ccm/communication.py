"""
Optional CCMC (Communications) integration for CCM (Macaron).

This module provides optional integration with the CUPCAKE Mint Chocolate communications
system. All functions gracefully handle the case where CCMC is not installed.
"""

import logging

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()


def is_ccmc_available():
    """Check if CCMC app is installed and available."""
    in_installed_apps = any("ccmc" in str(app).lower() for app in settings.INSTALLED_APPS)
    is_installed = apps.is_installed("ccmc")
    return in_installed_apps and is_installed


def send_notification(
    title, message, recipient, notification_type="system", priority="normal", related_object=None, data=None
):
    """
    Send a notification using CCMC if available.

    Args:
        title (str): Notification title
        message (str): Notification message
        recipient (User): User to receive notification
        notification_type (str): Type of notification (system, maintenance, inventory, etc.)
        priority (str): Priority level (low, normal, high, urgent)
        related_object (Model instance): Optional related object that triggered notification
        data (dict): Optional additional data

    Returns:
        bool: True if notification was sent, False if CCMC unavailable
    """
    if not is_ccmc_available():
        logger.info(f"CCMC not available - notification not sent: {title}")
        return False

    try:
        from django.contrib.contenttypes.models import ContentType

        from ccmc.models import Notification

        # Prepare notification data
        notification_data = {
            "title": title,
            "message": message,
            "recipient": recipient,
            "notification_type": notification_type,
            "priority": priority,
            "data": data or {},
        }

        # Add generic relation if related object provided
        if related_object:
            notification_data["content_type"] = ContentType.objects.get_for_model(related_object)
            notification_data["object_id"] = related_object.pk

        notification = Notification.objects.create(**notification_data)
        logger.info(f"CCMC notification sent: {notification.id}")
        return True

    except Exception as e:
        logger.error(f"Failed to send CCMC notification: {e}")
        return False


def create_instrument_thread(instrument, title, description="", participants=None):
    """
    Create a message thread for an instrument if CCMC is available.

    Args:
        instrument: Instrument instance
        title (str): Thread title
        description (str): Thread description
        participants (list): List of User instances to add as participants

    Returns:
        MessageThread instance or None if CCMC unavailable
    """
    if not is_ccmc_available():
        logger.info(f"CCMC not available - thread not created: {title}")
        return None

    try:
        from django.contrib.contenttypes.models import ContentType

        from ccmc.models import MessageThread

        # Create thread linked to instrument
        thread = MessageThread.objects.create(
            title=title,
            description=description,
            creator=instrument.user,
            content_type=ContentType.objects.get_for_model(instrument),
            object_id=instrument.pk,
        )

        # Add participants
        if participants:
            for user in participants:
                thread.participants.add(user)

        logger.info(f"CCMC thread created for instrument: {thread.id}")
        return thread

    except Exception as e:
        logger.error(f"Failed to create CCMC thread: {e}")
        return None


def send_maintenance_alert(instrument, message_type="maintenance_due", maintenance_info=None, notify_users=None):
    """
    Send maintenance alerts using CCMC if available.

    Args:
        instrument: Instrument instance
        message_type (str): Type of maintenance message
        maintenance_info (dict): Details about the maintenance
        notify_users (list): Specific users to notify, defaults to instrument owner

    Returns:
        bool: True if alerts sent successfully
    """
    if not is_ccmc_available():
        logger.warning("CCMC not available - cannot send maintenance alert")
        return False

    if not notify_users:
        notify_users = [instrument.user] if instrument.user else []

    if not notify_users:
        logger.warning(f"No users to notify for instrument {instrument.id}")
        return False

    maintenance_info = maintenance_info or {}

    # Determine message content based on type
    if message_type == "maintenance_due":
        title = f"Maintenance Due: {instrument.instrument_name}"
        message = f"Scheduled maintenance is due for {instrument.instrument_name}."
        priority = "high"
        notification_type = "maintenance"
    elif message_type == "warranty_expiring":
        title = f"Warranty Expiring: {instrument.instrument_name}"
        message = f"The warranty for {instrument.instrument_name} is expiring soon."
        priority = "high"
        notification_type = "maintenance"
    elif message_type == "maintenance_completed":
        title = f"Maintenance Completed: {instrument.instrument_name}"
        message = f"Maintenance has been completed for {instrument.instrument_name}."
        priority = "normal"
        notification_type = "maintenance"
    else:
        title = f"Instrument Alert: {instrument.instrument_name}"
        message = f"Alert for {instrument.instrument_name}: {message_type}"
        priority = "normal"
        notification_type = "system"

    # Send notifications to all specified users
    success_count = 0
    for user in notify_users:
        if send_notification(
            title=title,
            message=message,
            recipient=user,
            notification_type=notification_type,
            priority=priority,
            related_object=instrument,
            data=maintenance_info,
        ):
            success_count += 1
        else:
            logger.warning(f"Failed to send maintenance alert to user {user.id}")

    if success_count == 0:
        logger.error(f"Failed to send maintenance alerts to any of {len(notify_users)} users")
    else:
        logger.info(f"Successfully sent maintenance alerts to {success_count}/{len(notify_users)} users")

    return success_count > 0


def send_reagent_alert(stored_reagent, alert_type="low_stock", notify_users=None):
    """
    Send reagent alerts using CCMC if available.

    Args:
        stored_reagent: StoredReagent instance
        alert_type (str): Type of alert (low_stock, expired, etc.)
        notify_users (list): Specific users to notify

    Returns:
        bool: True if alerts sent successfully
    """
    if not is_ccmc_available():
        logger.warning("CCMC not available - cannot send reagent alert")
        return False

    if not notify_users:
        # Get users who have subscriptions for this reagent
        notify_users = []
        if hasattr(stored_reagent, "subscriptions"):
            notify_users = [sub.user for sub in stored_reagent.subscriptions.all()]

        # Fallback to reagent owner if no subscriptions
        if not notify_users and stored_reagent.user:
            notify_users = [stored_reagent.user]

    if not notify_users:
        logger.warning(f"No users to notify for stored reagent {stored_reagent.id}")
        return False

    reagent_data = {"alert_type": alert_type, "quantity": stored_reagent.quantity}

    if stored_reagent.storage_object_id:
        link = f"/storage/{stored_reagent.storage_object_id}?reagentId={stored_reagent.id}"
        reagent_data["link"] = link

    if alert_type == "low_stock":
        title = f"Low Stock Alert: {stored_reagent.reagent.name}"
        message = f"Stock is running low for {stored_reagent.reagent.name} (Current: {stored_reagent.quantity} {stored_reagent.reagent.unit})"
        priority = "high"
        notification_type = "inventory"
    elif alert_type == "expired":
        title = f"Expired Reagent: {stored_reagent.reagent.name}"
        message = f"{stored_reagent.reagent.name} has expired and should be disposed of safely."
        priority = "urgent"
        notification_type = "inventory"
    elif alert_type == "expiring_soon":
        title = f"Reagent Expiring Soon: {stored_reagent.reagent.name}"
        message = f"{stored_reagent.reagent.name} will expire soon. Please use or dispose of safely."
        priority = "high"
        notification_type = "inventory"
    else:
        title = f"Reagent Alert: {stored_reagent.reagent.name}"
        message = f"Alert for {stored_reagent.reagent.name}: {alert_type}"
        priority = "normal"
        notification_type = "inventory"

    # Send notifications to all specified users
    success_count = 0
    for user in notify_users:
        if send_notification(
            title=title,
            message=message,
            recipient=user,
            notification_type=notification_type,
            priority=priority,
            related_object=stored_reagent,
            data=reagent_data,
        ):
            success_count += 1
        else:
            logger.warning(f"Failed to send reagent alert to user {user.id}")

    if success_count == 0:
        logger.error(f"Failed to send reagent alerts to any of {len(notify_users)} users")
    else:
        logger.info(f"Successfully sent reagent alerts to {success_count}/{len(notify_users)} users")

    return success_count > 0


def get_instrument_notifications(instrument, user=None):
    """
    Get notifications related to an instrument.

    Args:
        instrument: Instrument instance
        user: User instance (optional, filters to user's notifications)

    Returns:
        QuerySet of notifications or empty list if CCMC unavailable
    """
    if not is_ccmc_available():
        return []

    try:
        from django.contrib.contenttypes.models import ContentType

        from ccmc.models import Notification

        content_type = ContentType.objects.get_for_model(instrument)
        notifications = Notification.objects.filter(content_type=content_type, object_id=instrument.pk)

        if user:
            notifications = notifications.filter(recipient=user)

        return notifications.order_by("-created_at")

    except Exception as e:
        logger.error(f"Failed to get CCMC notifications: {e}")
        return []


def get_instrument_threads(instrument, user=None):
    """
    Get message threads related to an instrument.

    Args:
        instrument: Instrument instance
        user: User instance (optional, filters to user's threads)

    Returns:
        QuerySet of threads or empty list if CCMC unavailable
    """
    if not is_ccmc_available():
        return []

    try:
        from django.contrib.contenttypes.models import ContentType

        from ccmc.models import MessageThread

        content_type = ContentType.objects.get_for_model(instrument)
        threads = MessageThread.objects.filter(content_type=content_type, object_id=instrument.pk)

        if user:
            threads = threads.filter(participants=user)

        return threads.order_by("-last_message_at")

    except Exception as e:
        logger.error(f"Failed to get CCMC threads: {e}")
        return []
