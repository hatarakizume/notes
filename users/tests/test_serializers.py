import io
from unittest import mock
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from users.serializers import (
    UserRegistrationSerializer,
    UserLoginSerializer,
    LogoutSerializer,
    ChangePasswordSerializer,
)

User = get_user_model()

STRONG_PASSWORD = "Zx-cv!Bn7-mQ_42plx"
NEW_STRONG_PASSWORD = "Rt*yu!Io9-kL_77vbn"


class TestUserRegistrationSerializer(APITestCase):

    def test_successful_registration(self):
        data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password": STRONG_PASSWORD,
            "password_confirm": STRONG_PASSWORD,
        }
        serializer = UserRegistrationSerializer(data=data)
        self.assertTrue(serializer.is_valid(), f"Ошибки: {serializer.errors}")
        user = serializer.save()
        self.assertEqual(user.username, "newuser")
        self.assertEqual(user.email, "newuser@example.com")
        self.assertTrue(user.check_password(STRONG_PASSWORD))

    def test_passwords_mismatch(self):
        data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password": STRONG_PASSWORD,
            "password_confirm": "DifferentPass123!",
        }
        serializer = UserRegistrationSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("password", serializer.errors)
        self.assertEqual(serializer.errors["password"], ["Пароли не совпадают."])

    def test_email_already_taken(self):
        User.objects.create_user(username="existing", email="taken@example.com", password=STRONG_PASSWORD)
        data = {
            "username": "newuser",
            "email": "TAKEN@example.com",
            "password": STRONG_PASSWORD,
            "password_confirm": STRONG_PASSWORD,
        }
        serializer = UserRegistrationSerializer(data=data)
        
        try:
            if serializer.is_valid():
                serializer.save()
                errors = {}
            else:
                errors = serializer.errors
        except ValidationError as exc:
            errors = exc.detail

        target_field = "non_field_errors" if "non_field_errors" in errors else "email"
        self.assertIn(target_field, errors)
        self.assertIn("Не удалось завершить регистрацию", str(errors[target_field]))


class TestStrictInputMixin(APITestCase):

    def test_unknown_field_raises_error(self):
        data = {
            "username": "testuser",
            "password": STRONG_PASSWORD,
            "unknown_field": "some_value",
        }
        serializer = UserLoginSerializer(data=data)
        with self.assertRaises(ValidationError) as context:
            serializer.is_valid(raise_exception=True)
        self.assertIn("unknown_field", context.exception.detail)


class TestLogoutSerializer(APITestCase):
    def test_logout_with_invalid_refresh_token(self):
        data = {"refresh": "completely_broken_token_string"}
        serializer = LogoutSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("refresh", serializer.errors)


class TestChangePasswordSerializer(APITestCase):
    def test_change_password_success(self):
        user = User.objects.create_user(username="pwduser", password=STRONG_PASSWORD)
        
        request_mock = mock.MagicMock()
        request_mock.user = user

        data = {
            "old_password": STRONG_PASSWORD,
            "new_password": NEW_STRONG_PASSWORD,
        }
        serializer = ChangePasswordSerializer(data=data, context={"request": request_mock})
        self.assertTrue(serializer.is_valid(), f"Ошибки: {serializer.errors}")
        updated_user = serializer.save()
        self.assertTrue(updated_user.check_password(NEW_STRONG_PASSWORD))
