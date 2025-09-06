"""
CUPCAKE Salted Caramel (CCSC) Django Admin Configuration.

Comprehensive billing and financial management admin interface.
"""

from django.contrib import admin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import BillableItemType, BillingRecord, ServicePrice, ServiceTier


@admin.register(ServiceTier)
class ServiceTierAdmin(admin.ModelAdmin):
    list_display = [
        "tier_name",
        "priority_level",
        "base_rate_multiplier",
        "discount_percentage",
        "active_prices_count",
        "is_active",
    ]
    list_filter = ["is_active", "priority_level", "created_at"]
    search_fields = ["tier_name", "description"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("Basic Information", {"fields": ("tier_name", "description", "priority_level", "is_active")}),
        (
            "Features & Limits",
            {"fields": ("features", "max_concurrent_bookings", "advance_booking_days"), "classes": ("collapse",)},
        ),
        (
            "Pricing Modifiers",
            {
                "fields": ("base_rate_multiplier", "discount_percentage"),
            },
        ),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def active_prices_count(self, obj):
        """Count active prices for this tier."""
        count = obj.prices.filter(is_active=True).count()
        if count > 0:
            url = (
                reverse("admin:ccsc_serviceprice_changelist") + f"?service_tier__id__exact={obj.id}&is_active__exact=1"
            )
            return format_html('<a href="{}">{} prices</a>', url, count)
        return "0 prices"

    active_prices_count.short_description = "Active Prices"


@admin.register(BillableItemType)
class BillableItemTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "content_type", "default_billing_unit", "requires_approval", "prices_count", "is_active"]
    list_filter = ["default_billing_unit", "requires_approval", "is_active", "created_at"]
    search_fields = ["name", "description"]
    readonly_fields = ["created_at", "updated_at"]

    def prices_count(self, obj):
        """Count prices for this billable item type."""
        count = obj.prices.count()
        if count > 0:
            url = reverse("admin:ccsc_serviceprice_changelist") + f"?billable_item_type__id__exact={obj.id}"
            return format_html('<a href="{}">{} prices</a>', url, count)
        return "0 prices"

    prices_count.short_description = "Configured Prices"


@admin.register(ServicePrice)
class ServicePriceAdmin(admin.ModelAdmin):
    list_display = [
        "item_tier_display",
        "base_price",
        "currency",
        "billing_unit",
        "effective_from",
        "effective_until",
        "is_current_display",
        "usage_count",
    ]
    list_filter = ["currency", "billing_unit", "is_active", "effective_from", "billable_item_type", "service_tier"]
    search_fields = ["billable_item_type__name", "service_tier__tier_name"]
    readonly_fields = ["created_at", "updated_at"]
    date_hierarchy = "effective_from"

    fieldsets = (
        (
            "Service & Pricing",
            {"fields": ("billable_item_type", "service_tier", "base_price", "currency", "billing_unit")},
        ),
        ("Additional Charges", {"fields": ("minimum_charge_units", "setup_fee"), "classes": ("collapse",)}),
        ("Bulk Pricing", {"fields": ("bulk_threshold", "bulk_discount_percentage"), "classes": ("collapse",)}),
        ("Validity Period", {"fields": ("effective_from", "effective_until", "is_active")}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def item_tier_display(self, obj):
        """Display item type and tier combination."""
        return f"{obj.billable_item_type.name} - {obj.service_tier.tier_name}"

    item_tier_display.short_description = "Service & Tier"

    def is_current_display(self, obj):
        """Show if price is currently effective."""
        if obj.is_current():
            return format_html('<span style="color: green;">✓ Current</span>')
        elif obj.effective_until and obj.effective_until < timezone.now():
            return format_html('<span style="color: red;">✗ Expired</span>')
        else:
            return format_html('<span style="color: orange;">○ Future</span>')

    is_current_display.short_description = "Status"

    def usage_count(self, obj):
        """Count how many billing records use this price."""
        count = obj.billing_records.count()
        if count > 0:
            url = reverse("admin:ccsc_billingrecord_changelist") + f"?service_price__id__exact={obj.id}"
            return format_html('<a href="{}">{} records</a>', url, count)
        return "0 records"

    usage_count.short_description = "Usage Records"


@admin.register(BillingRecord)
class BillingRecordAdmin(admin.ModelAdmin):
    list_display = [
        "billing_record_id",
        "user",
        "billable_object_display",
        "total_amount",
        "currency",
        "status",
        "created_at",
    ]
    list_filter = ["status", "currency", "service_tier", "content_type", "billing_period_start", "created_at"]
    search_fields = ["user__username", "user__email", "description", "cost_center", "funder", "notes"]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "cost_breakdown_display",
        "billable_object_link",
        "billing_calculations",
    ]
    date_hierarchy = "billing_period_start"

    fieldsets = (
        ("Billing Details", {"fields": ("id", "user", "service_tier", "service_price", "status")}),
        (
            "Billable Object",
            {
                "fields": ("billable_object_link", "description"),
            },
        ),
        (
            "Financial Breakdown",
            {
                "fields": ("billing_calculations", "cost_breakdown_display"),
            },
        ),
        ("Administrative", {"fields": ("cost_center", "funder", "notes"), "classes": ("collapse",)}),
        ("Billing Period", {"fields": ("billing_period_start", "billing_period_end"), "classes": ("collapse",)}),
        ("Approval Workflow", {"fields": ("approved_by", "approved_at"), "classes": ("collapse",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    raw_id_fields = ["user", "approved_by"]

    def billing_record_id(self, obj):
        """Display shortened UUID."""
        return str(obj.id)[:8] + "..."

    billing_record_id.short_description = "Record ID"

    def billable_object_display(self, obj):
        """Display billable object with type."""
        if obj.billable_object:
            content_type_name = obj.content_type.name.title()
            return f"{content_type_name}: {str(obj.billable_object)[:50]}"
        return "No object"

    billable_object_display.short_description = "Billable Item"

    def billable_object_link(self, obj):
        """Link to the billable object's admin page."""
        if obj.billable_object:
            content_type = obj.content_type
            app_label = content_type.app_label
            model_name = content_type.model
            object_id = obj.object_id

            try:
                url = reverse(f"admin:{app_label}_{model_name}_change", args=[object_id])
                return format_html(
                    '<a href="{}" target="_blank">{}: {}</a>', url, content_type.name.title(), str(obj.billable_object)
                )
            except Exception:
                return f"{content_type.name.title()}: {str(obj.billable_object)}"
        return "No linked object"

    billable_object_link.short_description = "Linked Object"

    def cost_breakdown_display(self, obj):
        """Display detailed cost breakdown."""
        breakdown = obj.get_cost_breakdown()
        html = '<table style="width: 100%; font-size: 12px;">'
        html += f'<tr><td><strong>Quantity:</strong></td><td>{breakdown["quantity"]}</td></tr>'
        html += (
            f'<tr><td><strong>Unit Price:</strong></td><td>{breakdown["unit_price"]} {breakdown["currency"]}</td></tr>'
        )
        html += f'<tr><td><strong>Subtotal:</strong></td><td>{breakdown["subtotal"]} {breakdown["currency"]}</td></tr>'

        if breakdown["setup_fee"] > 0:
            html += f'<tr><td><strong>Setup Fee:</strong></td><td>{breakdown["setup_fee"]} {breakdown["currency"]}</td></tr>'

        if breakdown["discount_amount"] > 0:
            html += f'<tr><td><strong>Discount:</strong></td><td>-{breakdown["discount_amount"]} {breakdown["currency"]}</td></tr>'

        if breakdown["tax_amount"] > 0:
            html += f'<tr><td><strong>Tax:</strong></td><td>{breakdown["tax_amount"]} {breakdown["currency"]}</td></tr>'

        html += f'<tr style="border-top: 1px solid #ccc; font-weight: bold;"><td><strong>Total:</strong></td><td>{breakdown["total_amount"]} {breakdown["currency"]}</td></tr>'
        html += "</table>"

        return mark_safe(html)

    cost_breakdown_display.short_description = "Cost Breakdown"

    def billing_calculations(self, obj):
        """Show billing calculation summary."""
        tier_multiplier = obj.service_tier.base_rate_multiplier if obj.service_tier else 1
        tier_discount = obj.service_tier.discount_percentage if obj.service_tier else 0

        html = '<div style="font-size: 12px;">'
        html += f'<p><strong>Service Tier:</strong> {obj.service_tier.tier_name if obj.service_tier else "None"}</p>'
        html += f"<p><strong>Rate Multiplier:</strong> {tier_multiplier}x</p>"
        html += f"<p><strong>Tier Discount:</strong> {tier_discount}%</p>"
        html += f'<p><strong>Billing Unit:</strong> {obj.service_price.get_billing_unit_display() if obj.service_price else "N/A"}</p>'
        html += "</div>"

        return mark_safe(html)

    billing_calculations.short_description = "Pricing Details"

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("user", "service_tier", "service_price", "content_type", "approved_by")
            .prefetch_related("service_price__billable_item_type")
        )

    actions = ["approve_selected", "mark_as_billed"]

    def approve_selected(self, request, queryset):
        """Bulk approve billing records."""
        approved_count = 0
        for record in queryset.filter(status="pending"):
            if record.approve(request.user):
                approved_count += 1

        self.message_user(request, f"Approved {approved_count} billing records.")

    approve_selected.short_description = "Approve selected billing records"

    def mark_as_billed(self, request, queryset):
        """Mark selected records as billed."""
        updated = queryset.filter(status="approved").update(status="billed")
        self.message_user(request, f"Marked {updated} records as billed.")

    mark_as_billed.short_description = "Mark selected records as billed"
