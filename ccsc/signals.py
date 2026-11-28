"""
CUPCAKE Salted Caramel (CCSC) Signal Handlers.

Billing records are created automatically for the three billable kinds: staff time and instrument time from
completed instrument jobs, instrument time from finished approved bookings, and reagent cost from each quantity
reserved from a stored reagent.
"""

import logging
from decimal import Decimal

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from .models import BillableItemType, BillingRecord, ServicePrice, ServiceTier

logger = logging.getLogger(__name__)

KIND_DEFAULTS = {
    BillableItemType.STAFF_TIME: ("Staff time", "Hours staff spend on instrument jobs", "hourly"),
    BillableItemType.INSTRUMENT_TIME: ("Instrument time", "Hours of instrument use, booked or for jobs", "hourly"),
    BillableItemType.REAGENT_COST: ("Reagent cost", "Quantities reserved from stored reagents", "unit"),
}


def ccm_model(name):
    """A model of the instrument app, or None when it is not installed."""
    try:
        return apps.get_model("ccm", name)
    except LookupError:
        return None


def get_user_service_tier(user):
    """The user's service tier, or the Basic tier."""
    try:
        if hasattr(user, "profile") and hasattr(user.profile, "service_tier"):
            return user.profile.service_tier
    except Exception:
        pass
    basic_tier, _ = ServiceTier.objects.get_or_create(
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
    """The current price of an item type for a service tier, or None."""
    current_prices = ServicePrice.objects.filter(
        billable_item_type=billable_item_type, service_tier=service_tier, is_active=True
    ).order_by("-effective_from")
    for price in current_prices:
        if price.is_current():
            return price
    return None


def item_type_for(kind):
    """The billable item type of a kind, created with its defaults when there is none."""
    item_type = BillableItemType.objects.filter(kind=kind).order_by("id").first()
    if item_type:
        return item_type
    name, description, unit = KIND_DEFAULTS[kind]
    item_type, _ = BillableItemType.objects.get_or_create(
        name=name, defaults={"kind": kind, "description": description, "default_billing_unit": unit}
    )
    if item_type.kind != kind:
        item_type.kind = kind
        item_type.save(update_fields=["kind"])
    return item_type


def already_billed(billable_object, kind):
    """Whether the object already has a billing record of the kind."""
    return BillingRecord.objects.filter(
        content_type=ContentType.objects.get_for_model(billable_object.__class__),
        object_id=billable_object.pk,
        service_price__billable_item_type__kind=kind,
    ).exists()


def bill(kind, billable_object, user, quantity, period_start, period_end, description, **extra):
    """Create the billing record of a kind for an object, priced for the user's service tier; None without a price."""
    quantity = Decimal(str(quantity))
    if quantity <= 0 or already_billed(billable_object, kind):
        return None
    item_type = item_type_for(kind)
    service_tier = get_user_service_tier(user)
    service_price = get_service_price(item_type, service_tier)
    if not service_price:
        logger.warning(f"No pricing found for {item_type.name} - {service_tier.tier_name}")
        return None
    cost = service_price.calculate_total_cost(quantity)
    record = BillingRecord.objects.create(
        billable_object=billable_object,
        user=user,
        service_tier=service_tier,
        service_price=service_price,
        quantity=quantity,
        unit_price=service_price.base_price,
        setup_fee=service_price.setup_fee,
        subtotal=cost["subtotal"],
        discount_amount=cost["bulk_discount"],
        total_amount=service_tier.calculate_price(cost["total"]),
        currency=service_price.currency,
        billing_period_start=period_start,
        billing_period_end=period_end,
        description=description,
        **extra,
    )
    logger.info(f"Created billing record {record.id} for {kind} of {billable_object}")
    return record


def bill_usage(usage):
    """Bill a finished approved booking as instrument time."""
    return bill(
        BillableItemType.INSTRUMENT_TIME,
        usage,
        usage.user,
        usage.usage_hours or 0,
        usage.time_started or timezone.now(),
        usage.time_ended or timezone.now(),
        f"Instrument time: {usage.instrument.instrument_name}",
        status="pending",
    )


def bill_job(job):
    """Bill a completed instrument job as its staff time and its instrument time."""
    common = {
        "cost_center": job.cost_center or "",
        "funder": job.funder or "",
        "status": "approved" if job.completed_at else "pending",
    }
    name = job.job_name or job.get_job_type_display()
    end = job.completed_at or timezone.now()
    return [
        bill(
            BillableItemType.STAFF_TIME,
            job,
            job.user,
            job.personnel_hours or 0,
            job.created_at,
            end,
            f"Staff time: {name}",
            **common,
        ),
        bill(
            BillableItemType.INSTRUMENT_TIME,
            job,
            job.user,
            job.instrument_hours or 0,
            job.created_at,
            end,
            f"Instrument time: {name}",
            **common,
        ),
    ]


def bill_reservation(action):
    """Bill a quantity reserved from a stored reagent as reagent cost."""
    stored = action.reagent
    unit = stored.reagent.unit or ""
    return bill(
        BillableItemType.REAGENT_COST,
        action,
        action.user,
        action.quantity or 0,
        action.created_at,
        action.created_at,
        f"Reagent cost: {stored.reagent.name}, {action.quantity:g} {unit}".strip(),
        status="pending",
    )


@receiver(post_save)
def handle_ccm_billing(sender, instance, created, **kwargs):
    """Bill bookings, instrument jobs and reagent reservations when they are saved."""
    if sender is ccm_model("InstrumentUsage"):
        if instance.time_ended and instance.approved:
            bill_usage(instance)
    elif sender is ccm_model("InstrumentJob"):
        if instance.status in ["completed", "delivered"]:
            bill_job(instance)
    elif sender is ccm_model("ReagentAction"):
        if created and instance.action_type == "reserve" and instance.user_id:
            bill_reservation(instance)


@receiver(post_delete)
def cancel_reservation_billing(sender, instance, **kwargs):
    """Remove the pending reagent cost of a reservation that is deleted."""
    if sender is not ccm_model("ReagentAction"):
        return
    BillingRecord.objects.filter(
        content_type=ContentType.objects.get_for_model(sender), object_id=instance.pk, status="pending"
    ).delete()


@receiver(pre_save)
def handle_billing_record_status_changes(sender, instance, **kwargs):
    """Record when a billing record is approved."""
    if sender != BillingRecord or not instance.pk:
        return
    old_instance = BillingRecord.objects.filter(pk=instance.pk).first()
    if old_instance and old_instance.status != instance.status:
        if instance.status == "approved" and not instance.approved_at:
            instance.approved_at = timezone.now()
