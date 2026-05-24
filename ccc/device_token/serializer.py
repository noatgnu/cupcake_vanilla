from rest_framework import serializers

from ccc.device_token.model import DeviceToken


class DeviceTokenSerializer(serializers.ModelSerializer):
    is_expired = serializers.SerializerMethodField()
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = DeviceToken
        fields = [
            "id",
            "token",
            "label",
            "description",
            "permission",
            "enabled",
            "user",
            "username",
            "created_at",
            "last_used_at",
            "expires_at",
            "is_expired",
        ]
        read_only_fields = ["id", "token", "user", "created_at", "last_used_at"]

    def get_is_expired(self, obj):
        return obj.is_expired()
