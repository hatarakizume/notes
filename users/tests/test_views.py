import io
import os
import shutil
import tempfile
from unittest import mock

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User, UserProfile

STRONG_PASSWORD = "Zx-cv!Bn7-mQ_42plx"
NEW_STRONG_PASSWORD = "Rt*yu!Io9-kL_77vbn"

TEMP_MEDIA = tempfile.mkdtemp(prefix="test-media-")


def image_bytes(fmt="PNG", size=(32, 32), mode="RGB", color=(200, 10, 10), **save_kwargs):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format=fmt, **save_kwargs)
    return buf.getvalue()


def upload(name, content, content_type="image/png"):
    return SimpleUploadedFile(name, content, content_type=content_type)


def media_files():
    result = []
    for root, _dirs, files in os.walk(TEMP_MEDIA):
        for f in files:
            result.append(os.path.relpath(os.path.join(root, f), TEMP_MEDIA))
    return sorted(result)


def get_secure_url(name, **kwargs):
    """Гарантирует генерацию URL с закрывающим слэшем."""
    url = reverse(name, kwargs=kwargs)
    if not url.endswith("/"):
        url += "/"
    return url


class BaseAPITest(APITestCase):
    def setUp(self):
        cache.clear()

    def create_user(self, username="alice", email="alice@example.com", password=STRONG_PASSWORD):
        return User.objects.create_user(username=username, email=email, password=password)

    def login(self, username="alice", password=STRONG_PASSWORD):
        resp = self.client.post(
            get_secure_url("login"), {"username": username, "password": password}, format="json", secure=True
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.json()

    def auth(self, access):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

# --------------------------------------------------------------------------
# Регистрация
# --------------------------------------------------------------------------


class RegistrationTests(BaseAPITest):
    @property
    def url(self):
        return get_secure_url("register")

    def payload(self, **overrides):
        data = {
            "username": "bob",
            "email": "bob@example.com",
            "password": STRONG_PASSWORD,
            "password_confirm": STRONG_PASSWORD,
        }
        data.update(overrides)
        return data

    def assert_rejected(self, data, field=None, fmt="json"):
        cache.clear()
        before = User.objects.count()
        # ИСПРАВЛЕНО: добавлено принудительное использование secure=True
        resp = self.client.post(self.url, data, format=fmt, secure=True)
        self.assertEqual(resp.status_code, 400, resp.content)
        if field:
            self.assertIn(field, resp.json())
        self.assertEqual(User.objects.count(), before)
        self.assertEqual(UserProfile.objects.count(), before)
        return resp

    def test_success_hashes_password_and_creates_profile(self):
        resp = self.client.post(self.url, self.payload(), format="json", secure=True)
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertIn("access", resp.json())
        self.assertNotIn("password", resp.json())
        user = User.objects.get(username="bob")
        self.assertNotEqual(user.password, STRONG_PASSWORD)
        self.assertNotIn(STRONG_PASSWORD, user.password)
        self.assertTrue(user.password.startswith("pbkdf2_sha256$"))
        self.assertTrue(user.check_password(STRONG_PASSWORD))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_password_whitespace_is_not_silently_trimmed(self):
        pw = "  " + STRONG_PASSWORD + "  "
        resp = self.client.post(
            self.url, self.payload(password=pw, password_confirm=pw), format="json", secure=True
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        user = User.objects.get(username="bob")
        self.assertTrue(user.check_password(pw))
        self.assertFalse(user.check_password(STRONG_PASSWORD))

    def test_weak_passwords_rejected(self):
        for pw in ["12345678", "password", "Ab1!", "bob@example.com", "bobexample"]:
            with self.subTest(pw=pw):
                self.assert_rejected(self.payload(password=pw, password_confirm=pw), "password")

    def test_password_similar_to_username_rejected(self):
        pw = "verylongusername1"
        self.assert_rejected(
            self.payload(username="verylongusername", password=pw, password_confirm=pw),
            "password",
        )

    def test_password_mismatch(self):
        self.assert_rejected(self.payload(password_confirm=NEW_STRONG_PASSWORD), "password")

    def test_missing_fields(self):
        for field in ["username", "email", "password", "password_confirm"]:
            with self.subTest(field=field):
                data = self.payload()
                del data[field]
                self.assert_rejected(data, field)

    def test_null_values(self):
        for field in ["username", "email", "password", "password_confirm"]:
            with self.subTest(field=field):
                self.assert_rejected(self.payload(**{field: None}), field)

    def test_wrong_types(self):
        for value in [123, 1.5, True, ["bob"], {"x": "bob"}]:
            for field in ["username", "email", "password"]:
                with self.subTest(field=field, value=value):
                    self.assert_rejected(self.payload(**{field: value}), field)

    def test_too_long_values(self):
        self.assert_rejected(self.payload(username="a" * 151), "username")
        self.assert_rejected(self.payload(email="a" * 250 + "@example.com"), "email")
        long_pw = STRONG_PASSWORD + "x" * 300
        self.assert_rejected(self.payload(password=long_pw, password_confirm=long_pw), "password")

    def test_invalid_email(self):
        self.assert_rejected(self.payload(email="not-an-email"), "email")

    def test_unknown_and_privileged_fields_rejected(self):
        for field, value in [
            ("is_staff", True),
            ("is_superuser", True),
            ("is_active", True),
            ("groups", []),
            ("user_permissions", []),
            ("user_id", 1),
            ("id", 999),
            ("owner", 1),
            ("unexpected", "x"),
        ]:
            with self.subTest(field=field):
                self.assert_rejected(self.payload(**{field: value}), field)
        self.assertFalse(User.objects.filter(is_staff=True).exists())
        self.assertFalse(User.objects.filter(is_superuser=True).exists())

    def test_privileged_fields_rejected_in_multipart(self):
        self.assert_rejected(self.payload(is_superuser="true"), "is_superuser", fmt="multipart")

    def test_non_object_body_rejected(self):
        resp = self.client.post(self.url, [self.payload()], format="json", secure=True)
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post(self.url, "not json{", content_type="application/json", secure=True)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(User.objects.count(), 0)

    def test_duplicate_username_and_email_give_identical_response(self):
        """Ответ не должен выдавать, какое именно значение уже занято."""
        self.create_user(username="taken", email="Taken@Example.com")
        dup_email = self.assert_rejected(self.payload(email="taken@example.com"))
        dup_username = self.assert_rejected(self.payload(username="taken"))
        both = self.assert_rejected(self.payload(username="taken", email="taken@example.com"))
        self.assertEqual(dup_email.json(), dup_username.json())
        self.assertEqual(dup_email.json(), both.json())
        self.assertEqual(list(dup_email.json()), ["non_field_errors"])
        body = dup_email.content.decode().lower()
        for leak in ["exist", "существует", "занят", "taken"]:
            self.assertNotIn(leak, body)

    def test_markup_and_sql_in_username_rejected(self):
        for name in ["<script>alert(1)</script>", "x' OR '1'='1", "a\"; DROP TABLE user;--"]:
            with self.subTest(name=name):
                self.assert_rejected(self.payload(username=name), "username")

# --------------------------------------------------------------------------
# Вход, выход, обновление токена
# --------------------------------------------------------------------------


class AuthenticationTests(BaseAPITest):
    def test_login_success_and_invalid_credentials(self):
        """Проверка генерации JWT при верных данных и блокировки при неверных."""
        self.create_user(username="loginuser", password=STRONG_PASSWORD)

        resp = self.client.post(
            get_secure_url("login"),
            {"username": "loginuser", "password": STRONG_PASSWORD},
            format="json",
            secure=True
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn("access", resp.json())
        self.assertIn("refresh", resp.json())

        cache.clear()
        resp = self.client.post(
            get_secure_url("login"),
            {"username": "loginuser", "password": "WrongPassword!"},
            format="json",
            secure=True
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_login_unknown_fields_rejected_by_mixin(self):
        """StrictInputMixin должен отклонять запросы на вход с левыми полями."""
        resp = self.client.post(
            get_secure_url("login"),
            {"username": "user", "password": STRONG_PASSWORD, "extra_hack_field": "danger"},
            format="json",
            secure=True
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("extra_hack_field", resp.json())

    def test_logout_and_token_blacklist(self):
        """Проверка занесения refresh-токена в блэклист при логауте."""
        user = self.create_user(username="logoutuser")
        tokens = self.login(username="logoutuser")

        resp = self.client.post(get_secure_url("logout"), {"refresh": tokens["refresh"]}, format="json", secure=True)
        self.assertEqual(resp.status_code, 204, resp.content)

        cache.clear()
        resp = self.client.post(
            get_secure_url("token_refresh"), {"refresh": tokens["refresh"]}, format="json", secure=True
        )
        self.assertEqual(resp.status_code, 401, resp.content)


# --------------------------------------------------------------------------
# Профиль пользователя (MeView)
# --------------------------------------------------------------------------


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ProfileTests(BaseAPITest):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if os.path.exists(TEMP_MEDIA):
            shutil.rmtree(TEMP_MEDIA)

    @mock.patch("users.serializers.process_avatar")
    def test_profile_retrieve_and_update_avatar_handling(self, mock_process_avatar):
        """Тест GET и PUT запросов к профилю с изоляцией дисковых операций."""
        mock_process_avatar.side_effect = lambda file: file
        user = self.create_user(username="avataruser")
        tokens = self.login(username="avataruser")
        self.auth(tokens["access"])

        resp = self.client.get(get_secure_url("me"), secure=True)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["username"], "avataruser")
        self.assertIn("avatar", resp.json())

        img = image_bytes()
        avatar_file = upload("test_avatar.png", img)
        resp = self.client.put(get_secure_url("me"), {"avatar": avatar_file}, format="multipart", secure=True)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIsNotNone(resp.json()["avatar"])


# --------------------------------------------------------------------------
# Смена пароля
# --------------------------------------------------------------------------


class ChangePasswordTests(BaseAPITest):
    def test_change_password_revokes_all_active_refresh_tokens(self):
        """Проверка принудительного отзыва всех прошлых токенов пользователя."""
        user = self.create_user(username="changepwd")
        tokens = self.login(username="changepwd")
        self.auth(tokens["access"])

        RefreshToken.for_user(user)
        old_tokens_count = OutstandingToken.objects.filter(user=user).count()
        self.assertTrue(old_tokens_count >= 2)

        data = {"old_password": STRONG_PASSWORD, "new_password": NEW_STRONG_PASSWORD}
        resp = self.client.post(get_secure_url("change_password"), data, format="json", secure=True)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn("access", resp.json())

        blacklisted_count = BlacklistedToken.objects.filter(token__user=user).count()
        self.assertEqual(blacklisted_count, old_tokens_count)
