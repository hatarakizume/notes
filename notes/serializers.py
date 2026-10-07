from rest_framework import serializers
from users.serializers import StrictInputMixin

from .drawing import MAX_DRAWING_LEN, DrawingError, validate_drawing
from .models import Note

MAX_DESCRIPTION_LEN = 100_000


class NoteSerializer(StrictInputMixin, serializers.ModelSerializer):
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=MAX_DESCRIPTION_LEN,
        trim_whitespace=False,
    )
    drawing = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=MAX_DRAWING_LEN,
        trim_whitespace=False,
    )

    class Meta:
        model = Note
        fields = (
            "id",
            "title",
            "description",
            "drawing",
            "category",
            "color",
            "is_important",
            "created_at",
            "updated_at",
            "is_deleted",
            "deleted_at",
        )
        read_only_fields = (
            "id",
            "created_at",
            "updated_at",
            "is_deleted",
            "deleted_at",
        )

    def to_internal_value(self, data):
        # Для флага принимаем только настоящий JSON-boolean: без неявного
        # превращения "yes", 1 или "true" в True.
        if isinstance(data, dict) and "is_important" in data:
            if not isinstance(data["is_important"], bool):
                raise serializers.ValidationError(
                    {"is_important": ["Ожидается true или false."]}
                )
        return super().to_internal_value(data)

    def validate_drawing(self, value):
        try:
            return validate_drawing(value)
        except DrawingError as exc:
            raise serializers.ValidationError(str(exc))
