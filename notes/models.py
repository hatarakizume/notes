from django.db import models
from users.models import User


class Note(models.Model):
    class Color(models.TextChoices):
        PAPER = "#FEFAF4", "Бумага"
        YELLOW = "#FFF9C4", "Жёлтый"
        BLUE = "#E3F2FD", "Голубой"
        PINK = "#FCE4EC", "Розовый"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notes")
    title = models.CharField("Заголовок", max_length=200)
    description = models.TextField("Описание", blank=True)
    drawing = models.TextField("Рисунок", blank=True)
    category = models.CharField("Категория", max_length=30, blank=True, default="")
    color = models.CharField(
        "Цвет", max_length=7, choices=Color.choices, default=Color.PAPER
    )
    is_important = models.BooleanField("Важное", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title
