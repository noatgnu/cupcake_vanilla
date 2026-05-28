from django.db import models
from django.utils.crypto import get_random_string

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ccc.device_token.model import DeviceToken
from ccc.device_token.permissions import IsDeviceTokenAuthenticated
from ccc.device_token.serializer import DeviceTokenSerializer


class DeviceTokenViewSet(viewsets.ModelViewSet):
    serializer_class = DeviceTokenSerializer
    permission_classes = [IsAuthenticated, IsDeviceTokenAuthenticated]

    def get_queryset(self):
        return DeviceToken.objects.filter(user=self.request.user).select_related("user")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"])
    def rotate(self, request, pk=None):
        token = self.get_object()
        token.token = get_random_string(128)
        token.save(update_fields=["token"])
        return Response({"token": token.token})

    @action(detail=True, methods=["post"])
    def toggle(self, request, pk=None):
        token = self.get_object()
        token.enabled = not token.enabled
        token.save(update_fields=["enabled"])
        return Response({"enabled": token.enabled})


class DeviceSummaryViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, IsDeviceTokenAuthenticated]

    @action(detail=False, methods=["get"])
    def summary(self, request):
        user = request.user

        active_timers = 0
        try:
            from ccrv.models import TimeKeeper

            active_timers = TimeKeeper.objects.filter(started=True, user=user).count()
        except ImportError:
            pass

        instrument_count = 0
        active_jobs = 0
        low_reagents = 0
        try:
            from ccm.models import Instrument, InstrumentJob, StoredReagent

            instrument_count = Instrument.objects.filter(enabled=True, is_vaulted=False).count()
            active_jobs = InstrumentJob.objects.filter(status__in=["pending", "in_progress"], user=user).count()
            low_reagents = StoredReagent.objects.filter(
                quantity__lte=models.F("low_stock_threshold"), user=user
            ).count()
        except ImportError:
            pass

        return Response(
            {
                "instruments": instrument_count,
                "active_jobs": active_jobs,
                "low_reagents": low_reagents,
                "active_timers": active_timers,
            }
        )
