from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Note
from .serializers import NoteSerializer


class NoteViewSet(viewsets.ModelViewSet):
    serializer_class = NoteSerializer
    permission_classes = [IsAuthenticated]
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        qs = Note.objects.filter(user=self.request.user)
        if self.action == "list":
            in_trash = self.request.query_params.get("trash") == "1"
            qs = qs.filter(is_deleted=in_trash)
        return qs

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def destroy(self, request, *args, **kwargs):
        note = self.get_object()
        note.is_deleted = True
        note.deleted_at = timezone.now()
        note.save(update_fields=["is_deleted", "deleted_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        note = self.get_object()
        note.is_deleted = False
        note.deleted_at = None
        note.save(update_fields=["is_deleted", "deleted_at"])
        return Response(self.get_serializer(note).data)

    @action(detail=True, methods=["delete"])
    def purge(self, request, pk=None):
        note = self.get_object()
        if not note.is_deleted:
            raise NotFound()
        note.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
