"""
CUPCAKE Salted Caramel (CCSC) Signal Handlers.

Automatic billing record creation and management signals.
"""

import logging
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

logger = logging.getLogger(__name__)


def get_ccm_models():
    """Safely import CCM models."""
    try:
        from ccm.models import InstrumentJob, InstrumentUsage

        return InstrumentUsage, InstrumentJob
    except ImportError:
        return None, None


def get_user_service_tier(user):
    """Get user's service tier or default."""
    from .models import ServiceTier

    # Try to get user's tier from profile or organization
    # This can be extended with more complex logic
    try:
        if hasattr(user, "profile") and hasattr(user.profile, "service_tier"):
            return user.profile.service_tier
    except Exception:
        pass

    # Default to basic tier
    basic_tier, created = ServiceTier.objects.get_or_create(
        tier_name="Basic",
        defaults={
            "description": "Standard service level",
            "priority_level": 1,
            "base_rate_multiplier": Decimal("1.0"),
            "discount_percentage": Decimal("0"),
        },
    )
    return basic_tier


def get_service_price(billable_item_type, service_tier):
    """Get current service price for item type and tier."""
    from .models import ServicePrice

    current_prices = ServicePrice.objects.filter(
        billable_item_type=billable_item_type, service_tier=service_tier, is_active=True
    ).order_by("-effective_from")

    for price in current_prices:
        if price.is_current():
            return price

    return None


def create_billing_record_for_usage(usage_instance):
    """Create billing record for InstrumentUsage."""
    from .models import BillableItemType, BillingRecord

    try:
        # Get or create billable item type for instrument usage
        content_type = ContentType.objects.get_for_model(usage_instance.__class__)
        billable_type, created = BillableItemType.objects.get_or_create(
            name="Instrument Usage",
            content_type=content_type,
            defaults={"description": "Hourly instrument usage billing", "default_billing_unit": "hourly"},
        )

        # Get user's service tier
        service_tier = get_user_service_tier(usage_instance.user)

        # Get pricing
        service_price = get_service_price(billable_type, service_tier)
        if not service_price:
            logger.warning(f"No pricing found for {billable_type.name} - {service_tier.tier_name}")
            return None

        # Calculate hours and costs
        hours = Decimal(str(usage_instance.usage_hours))
        if hours <= 0:
            return None

        cost_breakdown = service_price.calculate_total_cost(hours)
        tier_adjusted_total = service_tier.calculate_price(cost_breakdown["total"])

        # Create billing record
        billing_record = BillingRecord.objects.create(
            billable_object=usage_instance,
            user=usage_instance.user,
            service_tier=service_tier,
            service_price=service_price,
            quantity=Decimal(str(hours)),
            unit_price=service_price.base_price,
            setup_fee=service_price.setup_fee,
            subtotal=cost_breakdown["subtotal"],
            discount_amount=cost_breakdown["bulk_discount"],
            total_amount=tier_adjusted_total,
            currency=service_price.currency,
            billing_period_start=usage_instance.time_started or timezone.now(),
            billing_period_end=usage_instance.time_ended or timezone.now(),
            description=f"Instrument usage: {usage_instance.instrument.instrument_name}",
            status="pending",
        )

        logger.info(f"Created billing record {billing_record.id} for usage {usage_instance.id}")
        return billing_record

    except Exception as e:
        logger.error(f"Failed to create billing record for usage {usage_instance.id}: {e}")
        return None


def create_billing_record_for_job(job_instance):
    """Create billing record for InstrumentJob."""
    from .models import BillableItemType, BillingRecord

    try:
        # Get or create billable item type for instrument jobs
        content_type = ContentType.objects.get_for_model(job_instance.__class__)
        billable_type, created = BillableItemType.objects.get_or_create(
            name="Instrument Job",
            content_type=content_type,
            defaults={"description": "Task-based instrument job billing", "default_billing_unit": "flat"},
        )

        # Get user's service tier
        service_tier = get_user_service_tier(job_instance.user)

        # Get pricing
        service_price = get_service_price(billable_type, service_tier)
        if not service_price:
            logger.warning(f"No pricing found for {billable_type.name} - {service_tier.tier_name}")
            return None

        # Calculate quantity based on job type
        if hasattr(job_instance, "sample_number") and job_instance.sample_number:
            quantity = Decimal(str(job_instance.sample_number))
        else:
            # Use total hours if available
            total_hours = job_instance.instrument_hours + job_instance.personnel_hours
            if total_hours > 0:
                quantity = Decimal(str(total_hours))
            else:
                quantity = Decimal("1")

        cost_breakdown = service_price.calculate_total_cost(quantity)
        tier_adjusted_total = service_tier.calculate_price(cost_breakdown["total"])

        # Create billing record
        billing_record = BillingRecord.objects.create(
            billable_object=job_instance,
            user=job_instance.user,
            service_tier=service_tier,
            service_price=service_price,
            quantity=quantity,
            unit_price=service_price.base_price,
            setup_fee=service_price.setup_fee,
            subtotal=cost_breakdown["subtotal"],
            discount_amount=cost_breakdown["bulk_discount"],
            total_amount=tier_adjusted_total,
            currency=service_price.currency,
            billing_period_start=job_instance.created_at,
            billing_period_end=job_instance.completed_at or timezone.now(),
            description=f"Job: {job_instance.job_name or job_instance.get_job_type_display()}",
            cost_center=job_instance.cost_center or "",
            funder=job_instance.funder or "",
            status="pending" if not job_instance.completed_at else "approved",
        )

        logger.info(f"Created billing record {billing_record.id} for job {job_instance.id}")
        return billing_record

    except Exception as e:
        logger.error(f"Failed to create billing record for job {job_instance.id}: {e}")
        return None


@receiver(post_save)
def handle_ccm_billing(sender, instance, created, **kwargs):
    """Handle billing for CCM models when they are saved."""
    InstrumentUsage, InstrumentJob = get_ccm_models()

    if not InstrumentUsage or not InstrumentJob:
        return

    # Handle InstrumentUsage billing
    if sender == InstrumentUsage:
        # Only bill completed usage sessions
        if instance.time_ended and instance.approved:
            # Check if billing record already exists
            from .models import BillingRecord

            existing = BillingRecord.objects.filter(
                content_type=ContentType.objects.get_for_model(InstrumentUsage), object_id=instance.id
            ).exists()

            if not existing:
                create_billing_record_for_usage(instance)

    # Handle InstrumentJob billing
    elif sender == InstrumentJob:
        # Bill when job status changes to completed or specific statuses
        if instance.status in ["completed", "delivered"]:
            # Check if billing record already exists
            from .models import BillingRecord

            existing = BillingRecord.objects.filter(
                content_type=ContentType.objects.get_for_model(InstrumentJob), object_id=instance.id
            ).exists()

            if not existing:
                create_billing_record_for_job(instance)


@receiver(pre_save)
def handle_billing_record_status_changes(sender, instance, **kwargs):
    """Handle billing record status changes."""
    from .models import BillingRecord

    if sender != BillingRecord:
        return

    # Handle approval workflow
    if instance.pk:
        try:
            old_instance = BillingRecord.objects.get(pk=instance.pk)
            if old_instance.status != instance.status:
                if instance.status == "approved" and not instance.approved_at:
                    instance.approved_at = timezone.now()
                    # Could trigger notification here
        except BillingRecord.DoesNotExist:
            pass
