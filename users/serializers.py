from collections.abc import Mapping

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.utils import get_md5_hash_password

from .avatars import process_avatar
from .models import User, UserProfile

PASSWORD_MAX_LENGTH = 256
REGISTRATION_FAILED_MESSAGE = (
    "Не удалось завершить регистрацию. Проверьте введённые данные "
    "или восстановите доступ."
)


class StrictInputMixin:
    unknown_field_message = "Неизвестное поле или поле недоступно для изменения."
    not_a_string_message = "Ожидается строка."

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            writable = {
                name for name, field in self.fields.items() if not field.read_only
            }
            errors = {
                key: [self.unknown_field_message]
                for key in data.keys()
                if key not in writable
            }
            for name, field in self.fields.items():
                if field.read_only or not isinstance(field, serializers.CharField):
                    continue
                if name in data:
                    value = data[name]
                    if value is not None and not isinstance(value, str):
                        errors[name] = [self.not_a_string_message]
            if errors:
                raise serializers.ValidationError(errors)
        return super().to_internal_value(data)


def password_field():
    return serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        max_length=PASSWORD_MAX_LENGTH,
        style={"input_type": "password"},
    )


def check_password_strength(password, user, field=None):
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        messages = list(exc.messages)
        raise serializers.ValidationError({field: messages} if field else messages)


class UserRegistrationSerializer(StrictInputMixin, serializers.ModelSerializer):
    password = password_field()
    password_confirm = password_field()

    class Meta:
        model = User
        fields = ("username", "email", "password", "password_confirm")
        extra_kwargs = {
            "username": {"validators": [UnicodeUsernameValidator()]},
            "email": {"required": True, "allow_blank": False, "validators": []},
        }

    def validate_email(self, value):
        return User.objects.normalize_email(value)

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password": "Пароли не совпадают."})
        candidate = User(username=attrs["username"], email=attrs["email"])
        check_password_strength(attrs["password"], candidate, field="password")
        if User.objects.filter(
            Q(username=attrs["username"]) | Q(email__iexact=attrs["email"])
        ).exists():
            raise serializers.ValidationError(
                {"non_field_errors": [REGISTRATION_FAILED_MESSAGE]}
            )
        return attrs

    def create(self, validated_data):
        validated_data.pop("password_confirm")
        try:
            with transaction.atomic():
                return User.objects.create_user(
                    username=validated_data["username"],
                    email=validated_data["email"],
                    password=validated_data["password"],
                )
        except IntegrityError:
            raise serializers.ValidationError(
                {"non_field_errors": [REGISTRATION_FAILED_MESSAGE]}
            )


class UserLoginSerializer(StrictInputMixin, serializers.Serializer):
    # Логин или email (форма входа на сайте спрашивает email).
    username = serializers.CharField(max_length=254)
    password = password_field()

    def validate(self, attrs):
        username = attrs.get("username")
        password = attrs.get("password")

        if not username or not password:
            raise serializers.ValidationError("Необходимо указать логин и пароль.")

        login = username
        if "@" in login and not User.objects.filter(username=login).exists():
            match = User.objects.filter(email__iexact=login).only("username").first()
            if match is not None:
                login = match.username

        # authenticate вызывается ровно один раз в любом случае, ответ при
        # ошибке одинаковый: не раскрываем, существует ли логин или email.
        user = authenticate(
            request=self.context.get("request"),
            username=login,
            password=password,
        )

        if not user or not user.is_active:
            raise serializers.ValidationError("Неверный логин или пароль.")

        attrs["user"] = user
        return attrs


class LogoutSerializer(StrictInputMixin, serializers.Serializer):
    refresh = serializers.CharField(max_length=4096)

    def validate_refresh(self, value):
        try:
            self.token = RefreshToken(value)
        except Exception:
            raise serializers.ValidationError("Невалидный refresh-токен.")
        return value

    def save(self, **kwargs):
        self.token.blacklist()


class StrictTokenRefreshSerializer(StrictInputMixin, TokenRefreshSerializer):
    refresh = serializers.CharField(max_length=4096)

    def validate(self, attrs):
        token = self.token_class(attrs["refresh"])
        user_id = token.payload.get(jwt_settings.USER_ID_CLAIM)
        user = User.objects.filter(**{jwt_settings.USER_ID_FIELD: user_id}).first()
        if user is None or not user.is_active:
            raise AuthenticationFailed(
                self.error_messages["no_active_account"], "no_active_account"
            )
        if jwt_settings.CHECK_REVOKE_TOKEN and token.payload.get(
            jwt_settings.REVOKE_TOKEN_CLAIM
        ) != get_md5_hash_password(user.password):
            raise AuthenticationFailed(
                "Пароль пользователя был изменён.", "password_changed"
            )
        return super().validate(attrs)


class UserProfileSerializer(StrictInputMixin, serializers.ModelSerializer):
    username = serializers.ReadOnlyField(source="user.username")
    email = serializers.ReadOnlyField(source="user.email")
    avatar = serializers.ImageField(required=False, allow_null=True, use_url=True)

    class Meta:
        model = UserProfile
        fields = ("username", "email", "avatar", "phone", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")

    def validate_avatar(self, file):
        if file is None:
            return None
        try:
            return process_avatar(file)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))


class ChangePasswordSerializer(StrictInputMixin, serializers.Serializer):
    old_password = password_field()
    new_password = password_field()

    def validate_old_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Старый пароль указан неверно")
        return value

    def validate_new_password(self, value):
        check_password_strength(value, self.context["request"].user)
        return value

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user
