from django.db import models
from users.models import User

class Note(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="notes"
    )
    title = models.CharField("Заголовок", max_length=200)
    description = models.TextField("Описание", blank=True)
    drawing = models.TextField("Рисунок", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title