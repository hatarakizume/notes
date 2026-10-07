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
from rest_framework.test import APITestCase

from .models import User, UserProfile

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


class BaseAPITest(APITestCase):
    def setUp(self):
        cache.clear()  # сбрасываем счётчики ограничения частоты

    def create_user(self, username="alice", email="alice@example.com", password=STRONG_PASSWORD):
        return User.objects.create_user(username=username, email=email, password=password)

    def login(self, username="alice", password=STRONG_PASSWORD):
        resp = self.client.post(
            reverse("login"), {"username": username, "password": password}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.json()

    def auth(self, access):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")


# --------------------------------------------------------------------------
# Регистрация
# --------------------------------------------------------------------------


class RegistrationTests(BaseAPITest):
    url = reverse("register")

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
        resp = self.client.post(self.url, data, format=fmt)
        self.assertEqual(resp.status_code, 400, resp.content)
        if field:
            self.assertIn(field, resp.json())
        self.assertEqual(User.objects.count(), before)
        self.assertEqual(UserProfile.objects.count(), before)
        return resp

    def test_success_hashes_password_and_creates_profile(self):
        resp = self.client.post(self.url, self.payload(), format="json")
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
            self.url, self.payload(password=pw, password_confirm=pw), format="json"
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
            ("groups", [1]),
            ("user_permissions", [1]),
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
        resp = self.client.post(self.url, [self.payload()], format="json")
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post(self.url, "not json{", content_type="application/json")
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


class LoginTests(BaseAPITest):
    url = reverse("login")

    def setUp(self):
        super().setUp()
        self.user = self.create_user()

    def test_success(self):
        data = self.login()
        self.assertIn("access", data)
        self.assertIn("refresh", data)

    def test_same_error_for_wrong_password_unknown_and_inactive_user(self):
        wrong = self.client.post(self.url, {"username": "alice", "password": "nope-nope-nope"}, format="json")
        unknown = self.client.post(self.url, {"username": "ghost", "password": "nope-nope-nope"}, format="json")
        User.objects.create_user("carol", "carol@example.com", STRONG_PASSWORD, is_active=False)
        inactive = self.client.post(self.url, {"username": "carol", "password": STRONG_PASSWORD}, format="json")
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(wrong.json(), unknown.json())
        self.assertEqual(wrong.json(), inactive.json())

    def test_sql_like_input_does_not_bypass_auth(self):
        for username, password in [
            ("alice' --", "x"),
            ("' OR '1'='1", "' OR '1'='1"),
            ("alice", "' OR '1'='1' --"),
        ]:
            with self.subTest(username=username):
                resp = self.client.post(self.url, {"username": username, "password": password}, format="json")
                self.assertEqual(resp.status_code, 400)
                self.assertNotIn("access", resp.json())
        self.assertEqual(User.objects.count(), 1)

    def test_wrong_types_and_unknown_fields(self):
        for data in [
            {"username": ["alice"], "password": STRONG_PASSWORD},
            {"username": "alice", "password": {"p": 1}},
            {"username": 1, "password": STRONG_PASSWORD},
            {"username": "alice", "password": None},
            {"username": "alice"},
            {"username": "alice", "password": STRONG_PASSWORD, "is_staff": True},
        ]:
            with self.subTest(data=data):
                cache.clear()
                resp = self.client.post(self.url, data, format="json")
                self.assertEqual(resp.status_code, 400)

    def test_rate_limited(self):
        codes = [
            self.client.post(self.url, {"username": "alice", "password": "wrong-pass-1"}, format="json").status_code
            for _ in range(6)
        ]
        self.assertEqual(codes[:5], [400] * 5)
        self.assertEqual(codes[5], 429)
        # Даже правильный пароль не принимается, пока действует ограничение.
        resp = self.client.post(self.url, {"username": "alice", "password": STRONG_PASSWORD}, format="json")
        self.assertEqual(resp.status_code, 429)

    def test_rate_limit_not_bypassed_with_x_forwarded_for(self):
        for i in range(5):
            self.client.post(
                self.url, {"username": "alice", "password": "wrong"}, format="json",
                HTTP_X_FORWARDED_FOR=f"10.0.0.{i}",
            )
        resp = self.client.post(
            self.url, {"username": "alice", "password": "wrong"}, format="json",
            HTTP_X_FORWARDED_FOR="10.9.9.9",
        )
        self.assertEqual(resp.status_code, 429)

    def test_register_rate_limited(self):
        url = reverse("register")
        codes = [self.client.post(url, {}, format="json").status_code for _ in range(11)]
        self.assertEqual(codes[-1], 429)


class TokenTests(BaseAPITest):
    def setUp(self):
        super().setUp()
        self.user = self.create_user()
        self.tokens = self.login()

    def test_logout_blacklists_refresh_token(self):
        resp = self.client.post(reverse("logout"), {"refresh": self.tokens["refresh"]}, format="json")
        self.assertEqual(resp.status_code, 204)
        resp = self.client.post(reverse("token_refresh"), {"refresh": self.tokens["refresh"]}, format="json")
        self.assertEqual(resp.status_code, 401)

    def test_logout_invalid_input(self):
        for data in [{"refresh": "garbage"}, {"refresh": ["x"]}, {"refresh": 1}, {}, {"refresh": None}]:
            with self.subTest(data=data):
                resp = self.client.post(reverse("logout"), data, format="json")
                self.assertEqual(resp.status_code, 400)

    def test_refresh_rotates_and_old_refresh_is_rejected(self):
        resp = self.client.post(reverse("token_refresh"), {"refresh": self.tokens["refresh"]}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("refresh", resp.json())
        again = self.client.post(reverse("token_refresh"), {"refresh": self.tokens["refresh"]}, format="json")
        self.assertEqual(again.status_code, 401)

    def test_refresh_for_deleted_user_is_401_not_500(self):
        self.user.delete()
        resp = self.client.post(reverse("token_refresh"), {"refresh": self.tokens["refresh"]}, format="json")
        self.assertEqual(resp.status_code, 401)

    def test_refresh_wrong_types(self):
        for data in [{"refresh": ["x"]}, {"refresh": 5}, {"refresh": self.tokens["refresh"], "extra": 1}]:
            with self.subTest(data=data):
                resp = self.client.post(reverse("token_refresh"), data, format="json")
                self.assertEqual(resp.status_code, 400)

    def test_basic_auth_is_not_accepted(self):
        import base64
        cred = base64.b64encode(f"alice:{STRONG_PASSWORD}".encode()).decode()
        resp = self.client.get(reverse("me"), HTTP_AUTHORIZATION=f"Basic {cred}")
        self.assertEqual(resp.status_code, 401)


# --------------------------------------------------------------------------
# Смена пароля
# --------------------------------------------------------------------------


class ChangePasswordTests(BaseAPITest):
    url = reverse("change_password")

    def setUp(self):
        super().setUp()
        self.user = self.create_user()
        self.tokens = self.login()
        self.auth(self.tokens["access"])

    def test_anonymous_rejected(self):
        self.client.credentials()
        resp = self.client.post(self.url, {"old_password": STRONG_PASSWORD, "new_password": NEW_STRONG_PASSWORD}, format="json")
        self.assertEqual(resp.status_code, 401)

    def test_wrong_current_password(self):
        resp = self.client.post(self.url, {"old_password": "wrong-pass", "new_password": NEW_STRONG_PASSWORD}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(STRONG_PASSWORD))
        self.assertFalse(self.user.check_password(NEW_STRONG_PASSWORD))

    def test_weak_new_password(self):
        for pw in ["12345678", "password", "short", "alice1234", "alice@example.com"]:
            with self.subTest(pw=pw):
                resp = self.client.post(self.url, {"old_password": STRONG_PASSWORD, "new_password": pw}, format="json")
                self.assertEqual(resp.status_code, 400)
                self.assertIn("new_password", resp.json())
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(STRONG_PASSWORD))

    def test_wrong_types_and_unknown_fields(self):
        for data in [
            {"old_password": STRONG_PASSWORD, "new_password": 12345678901234},
            {"old_password": [STRONG_PASSWORD], "new_password": NEW_STRONG_PASSWORD},
            {"old_password": STRONG_PASSWORD, "new_password": None},
            {"old_password": STRONG_PASSWORD},
            {"old_password": STRONG_PASSWORD, "new_password": NEW_STRONG_PASSWORD, "user_id": 2},
            {"old_password": STRONG_PASSWORD, "new_password": NEW_STRONG_PASSWORD, "is_superuser": True},
        ]:
            with self.subTest(data=data):
                cache.clear()
                resp = self.client.post(self.url, data, format="json")
                self.assertEqual(resp.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(STRONG_PASSWORD))
        self.assertFalse(self.user.is_superuser)

    def test_success_revokes_old_tokens(self):
        other_session = self.login()  # второе «устройство»
        cache.clear()
        resp = self.client.post(self.url, {"old_password": STRONG_PASSWORD, "new_password": NEW_STRONG_PASSWORD}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        new_tokens = resp.json()
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_STRONG_PASSWORD))
        self.assertTrue(self.user.password.startswith("pbkdf2_sha256$"))

        # Старые access-токены больше не принимаются.
        for access in (self.tokens["access"], other_session["access"]):
            self.auth(access)
            self.assertEqual(self.client.get(reverse("me")).status_code, 401)
        # Старые refresh-токены отозваны.
        self.client.credentials()
        for refresh in (self.tokens["refresh"], other_session["refresh"]):
            r = self.client.post(reverse("token_refresh"), {"refresh": refresh}, format="json")
            self.assertEqual(r.status_code, 401)
        # Новые токены работают.
        self.auth(new_tokens["access"])
        self.assertEqual(self.client.get(reverse("me")).status_code, 200)
        r = self.client.post(reverse("token_refresh"), {"refresh": new_tokens["refresh"]}, format="json")
        self.assertEqual(r.status_code, 200)


# --------------------------------------------------------------------------
# Профиль и аватарка
# --------------------------------------------------------------------------


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ProfileTests(BaseAPITest):
    url = reverse("me")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        super().setUp()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)
        os.makedirs(TEMP_MEDIA, exist_ok=True)
        self.user = self.create_user()
        self.auth(self.login()["access"])

    def patch_avatar(self, file):
        return self.client.patch(self.url, {"avatar": file}, format="multipart")

    def avatar_name(self, user=None):
        return UserProfile.objects.get(user=user or self.user).avatar.name or ""

    def assert_avatar_rejected(self, file):
        before_name = self.avatar_name()
        before_files = media_files()
        cache.clear()
        resp = self.patch_avatar(file)
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("avatar", resp.json())
        self.assertEqual(self.avatar_name(), before_name)
        self.assertEqual(media_files(), before_files)
        return resp

    # ----- доступ -----

    def test_anonymous_rejected(self):
        self.client.credentials()
        self.assertEqual(self.client.get(self.url).status_code, 401)
        resp = self.client.patch(self.url, {"avatar": upload("a.png", image_bytes())}, format="multipart")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(media_files(), [])

    def test_get_own_profile_without_secrets(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/json")
        body = resp.json()
        self.assertEqual(body["username"], "alice")
        self.assertNotIn("password", body)
        self.assertNotIn(self.user.password, resp.content.decode())

    def test_read_only_and_privileged_fields_rejected(self):
        for data in [
            {"username": "mallory"},
            {"email": "m@example.com"},
            {"is_staff": True},
            {"is_superuser": True},
            {"user": 2},
            {"user_id": 2},
            {"owner": 2},
            {"created_at": "2000-01-01T00:00:00Z"},
        ]:
            with self.subTest(data=data):
                cache.clear()
                resp = self.client.patch(self.url, data, format="json")
                self.assertEqual(resp.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "alice")
        self.assertEqual(self.user.email, "alice@example.com")
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)

    # ----- корректная загрузка -----

    def test_upload_png_success_with_server_generated_name(self):
        resp = self.patch_avatar(upload("../../../etc/my avatar.png", image_bytes("PNG")))
        self.assertEqual(resp.status_code, 200, resp.content)
        name = self.avatar_name()
        self.assertRegex(name, r"^avatars/[0-9a-f]{32}\.png$")
        self.assertEqual(media_files(), [name])
        with Image.open(os.path.join(TEMP_MEDIA, name)) as img:
            self.assertEqual(img.format, "PNG")

    def test_upload_jpeg_strips_exif(self):
        exif = Image.Exif()
        exif[0x010F] = "SecretCameraMaker"  # Make
        exif[0x8825] = {2: (55.0, 45.0, 0.0)}  # GPSInfo
        resp = self.patch_avatar(upload("me.jpg", image_bytes("JPEG", exif=exif), "image/jpeg"))
        self.assertEqual(resp.status_code, 200, resp.content)
        name = self.avatar_name()
        self.assertRegex(name, r"^avatars/[0-9a-f]{32}\.jpg$")
        with open(os.path.join(TEMP_MEDIA, name), "rb") as fh:
            raw = fh.read()
        self.assertNotIn(b"SecretCameraMaker", raw)
        with Image.open(io.BytesIO(raw)) as img:
            self.assertEqual(len(img.getexif()), 0)

    def test_extension_is_taken_from_real_format(self):
        # PNG под видом JPEG сохраняется как .png (формат по содержимому).
        resp = self.patch_avatar(upload("photo.jpg", image_bytes("PNG"), "image/jpeg"))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(self.avatar_name().endswith(".png"))
        # Неизображательное расширение отклоняется.
        self.assert_avatar_rejected(upload("photo.html", image_bytes("PNG"), "text/html"))

    def test_replacing_avatar_deletes_old_file(self):
        self.patch_avatar(upload("a.png", image_bytes()))
        first = self.avatar_name()
        cache.clear()
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.patch_avatar(upload("b.png", image_bytes(color=(1, 2, 3))))
        self.assertEqual(resp.status_code, 200)
        second = self.avatar_name()
        self.assertNotEqual(first, second)
        self.assertEqual(media_files(), [second])

    def test_null_removes_avatar_and_file(self):
        self.patch_avatar(upload("a.png", image_bytes()))
        cache.clear()
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.patch(self.url, {"avatar": None}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.avatar_name(), "")
        self.assertEqual(media_files(), [])

    def test_cannot_overwrite_other_users_avatar(self):
        bob = self.create_user("bob", "bob@example.com")
        self.client.credentials()
        cache.clear()
        self.auth(self.login("bob")["access"])
        self.patch_avatar(upload("bob.png", image_bytes()))
        bob_name = self.avatar_name(bob)
        with open(os.path.join(TEMP_MEDIA, bob_name), "rb") as fh:
            bob_bytes = fh.read()

        cache.clear()
        self.auth(self.login("alice")["access"])
        # Пытаемся подсунуть имя файла Боба: имя генерирует сервер.
        resp = self.patch_avatar(upload(os.path.basename(bob_name), image_bytes(color=(0, 0, 0))))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.avatar_name(bob), bob_name)
        self.assertNotEqual(self.avatar_name(), bob_name)
        with open(os.path.join(TEMP_MEDIA, bob_name), "rb") as fh:
            self.assertEqual(fh.read(), bob_bytes)

    # ----- отклоняемые файлы -----

    def test_svg_rejected(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>alert(1)</script></svg>'
        self.assert_avatar_rejected(upload("a.svg", svg, "image/svg+xml"))
        self.assert_avatar_rejected(upload("a.png", svg, "image/png"))

    def test_fake_image_rejected(self):
        self.assert_avatar_rejected(upload("a.png", b"<html><script>alert(1)</script></html>"))
        self.assert_avatar_rejected(upload("a.jpg", b"\xff\xd8\xff\xe0" + b"garbage" * 50, "image/jpeg"))

    def test_corrupted_image_rejected(self):
        data = image_bytes("PNG", size=(200, 200), color=(10, 20, 30))
        self.assert_avatar_rejected(upload("a.png", data[: len(data) // 2]))
        jpeg = image_bytes("JPEG", size=(200, 200))
        self.assert_avatar_rejected(upload("a.jpg", jpeg[: len(jpeg) // 2], "image/jpeg"))

    def test_other_formats_rejected(self):
        self.assert_avatar_rejected(upload("a.gif", image_bytes("GIF", mode="P", color=1), "image/gif"))
        self.assert_avatar_rejected(upload("a.bmp", image_bytes("BMP"), "image/bmp"))
        self.assert_avatar_rejected(upload("a.png", image_bytes("BMP"), "image/png"))

    def test_too_large_file_rejected(self):
        noise = Image.frombytes("RGB", (1000, 1000), os.urandom(1000 * 1000 * 3))
        buf = io.BytesIO()
        noise.save(buf, format="PNG")
        self.assertGreater(len(buf.getvalue()), 2 * 1024 * 1024)
        self.assert_avatar_rejected(upload("big.png", buf.getvalue()))

    def test_too_large_dimensions_rejected(self):
        self.assert_avatar_rejected(upload("wide.png", image_bytes("PNG", size=(5000, 10), mode="L", color=0)))
        self.assert_avatar_rejected(upload("tall.png", image_bytes("PNG", size=(10, 3000), mode="L", color=0)))

    def test_decompression_bomb_rejected(self):
        bomb = image_bytes("PNG", size=(20000, 20000), mode="1", color=0)
        self.assertLess(len(bomb), 2 * 1024 * 1024)
        self.assert_avatar_rejected(upload("bomb.png", bomb))

    def test_url_instead_of_file_rejected_without_network(self):
        with mock.patch("socket.create_connection") as conn, mock.patch("socket.getaddrinfo") as gai:
            for value in [
                "http://169.254.169.254/latest/meta-data/",
                "http://127.0.0.1/a.png",
                "http://[::1]/a.png",
                "https://example.com/a.png",
            ]:
                with self.subTest(value=value):
                    cache.clear()
                    resp = self.client.patch(self.url, {"avatar": value}, format="json")
                    self.assertEqual(resp.status_code, 400)
                    cache.clear()
                    resp = self.client.patch(self.url, {"avatar": value}, format="multipart")
                    self.assertEqual(resp.status_code, 400)
            conn.assert_not_called()
            gai.assert_not_called()
        self.assertEqual(self.avatar_name(), "")
        self.assertEqual(media_files(), [])

    def test_avatar_wrong_types(self):
        for value in [123, ["a.png"], {"url": "x"}, True]:
            with self.subTest(value=value):
                cache.clear()
                resp = self.client.patch(self.url, {"avatar": value}, format="json")
                self.assertEqual(resp.status_code, 400)
        self.assertEqual(media_files(), [])

    def test_profile_update_rate_limited(self):
        codes = []
        for _ in range(31):
            codes.append(self.client.patch(self.url, {}, format="json").status_code)
        self.assertEqual(codes[-1], 429)
        # Чтение профиля не ограничивается.
        self.assertEqual(self.client.get(self.url).status_code, 200)


# --------------------------------------------------------------------------
# Адреса, которые использует frontend (static/js/app.js)
# --------------------------------------------------------------------------


class FrontendContractTests(BaseAPITest):
    def test_frontend_paths_work(self):
        reg = self.client.post("/api/auth/register/", {
            "username": "front", "email": "front@example.com",
            "password": STRONG_PASSWORD, "password_confirm": STRONG_PASSWORD,
        }, format="json")
        self.assertEqual(reg.status_code, 201, reg.content)
        cache.clear()
        login = self.client.post("/api/auth/login/", {"username": "front", "password": STRONG_PASSWORD}, format="json")
        self.assertEqual(login.status_code, 200)
        tokens = login.json()
        self.auth(tokens["access"])
        me = self.client.get("/api/auth/me/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["phone"], "")
        self.assertIn("created_at", me.json())
        self.client.credentials()
        ref = self.client.post("/api/auth/refresh/", {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(ref.status_code, 200)
        out = self.client.post("/api/auth/logout/", {"refresh": ref.json()["refresh"]}, format="json")
        self.assertEqual(out.status_code, 204)

    def test_index_page_renders(self):  # главная страница
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "js/script.js")


class PhoneTests(BaseAPITest):
    def setUp(self):
        super().setUp()
        self.user = self.create_user()
        self.auth(self.login()["access"])

    def test_valid_phone_saved_via_multipart(self):
        resp = self.client.patch(reverse("me"), {"phone": "+7 (999) 123-45-67"}, format="multipart")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(UserProfile.objects.get(user=self.user).phone, "+7 (999) 123-45-67")

    def test_empty_phone_allowed(self):
        resp = self.client.patch(reverse("me"), {"phone": ""}, format="multipart")
        self.assertEqual(resp.status_code, 200)

    def test_invalid_phone_rejected(self):
        for value in ["<script>", "abc12345", "+7" + "1" * 25, "12", "javascript:1"]:
            with self.subTest(value=value):
                cache.clear()
                resp = self.client.patch(reverse("me"), {"phone": value}, format="json")
                self.assertEqual(resp.status_code, 400)
        for value in [79991234567, ["+7999"], None]:
            with self.subTest(value=value):
                cache.clear()
                resp = self.client.patch(reverse("me"), {"phone": value}, format="json")
                self.assertEqual(resp.status_code, 400)
        self.assertEqual(UserProfile.objects.get(user=self.user).phone, "")


class LoginByEmailTests(BaseAPITest):
    url = reverse("login")

    def setUp(self):
        super().setUp()
        self.user = self.create_user(username="alice", email="Alice@Example.com")

    def test_login_with_email_case_insensitive(self):
        for login in ["alice@example.com", "ALICE@example.com", "Alice@Example.com"]:
            with self.subTest(login=login):
                cache.clear()
                resp = self.client.post(self.url, {"username": login, "password": STRONG_PASSWORD}, format="json")
                self.assertEqual(resp.status_code, 200, resp.content)
                self.assertIn("access", resp.json())

    def test_email_with_wrong_password_and_unknown_email_look_the_same(self):
        wrong = self.client.post(self.url, {"username": "alice@example.com", "password": "nope-nope-1"}, format="json")
        unknown = self.client.post(self.url, {"username": "ghost@example.com", "password": "nope-nope-1"}, format="json")
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(wrong.json(), unknown.json())

    def test_username_containing_at_sign_still_works(self):
        User.objects.create_user(username="bob@home", email="bob@example.com", password=STRONG_PASSWORD)
        resp = self.client.post(self.url, {"username": "bob@home", "password": STRONG_PASSWORD}, format="json")
        self.assertEqual(resp.status_code, 200)


class PagesTests(BaseAPITest):
    def test_pages_render_with_static_files(self):
        for name, marker in [
            ("home", "img/331.png"),
            ("login_page", 'id="loginForm"'),
            ("register_page", 'id="registerForm"'),
            ("workspace", 'id="grid"'),
            ("account", 'id="profileForm"'),
        ]:
            with self.subTest(name=name):
                resp = self.client.get(reverse(name))
                self.assertEqual(resp.status_code, 200)
                self.assertContains(resp, marker)
                self.assertContains(resp, "/static/css/style.css")
                self.assertContains(resp, "/static/js/script.js")

    def test_pages_contain_no_user_data(self):
        self.create_user(username="secretuser", email="secret@example.com")
        for name in ["workspace", "account"]:
            resp = self.client.get(reverse(name))
            self.assertNotContains(resp, "secretuser")
            self.assertNotContains(resp, "secret@example.com")
