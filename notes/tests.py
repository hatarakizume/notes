import base64
import io

from django.core.cache import cache
from django.urls import reverse
from PIL import Image
from rest_framework.test import APITestCase

from users.models import User

from .models import Note

PASSWORD = "Zx-cv!Bn7-mQ_42plx"


def png_data_url(size=(16, 16), mode="RGB", color=(0, 0, 0)):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def list_url():
    return reverse("note-list")


def detail_url(pk):
    return f"/api/notes/{pk}/"


class NotesBase(APITestCase):
    def setUp(self):
        cache.clear()
        self.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        self.bob = User.objects.create_user("bob", "bob@example.com", PASSWORD)
        self.alice_note = Note.objects.create(user=self.alice, title="A note", description="alice secret")
        self.alice_trash = Note.objects.create(
            user=self.alice, title="A trash", description="alice trashed", is_deleted=True
        )
        self.bob_note = Note.objects.create(user=self.bob, title="B note", description="bob secret")
        self.bob_trash = Note.objects.create(
            user=self.bob, title="B trash", description="bob trashed", is_deleted=True
        )
        self.as_user("alice")

    def as_user(self, username):
        cache.clear()
        resp = self.client.post(
            reverse("login"), {"username": username, "password": PASSWORD}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.json()['access']}")

    def snapshot(self, note):
        note.refresh_from_db()
        return (note.user_id, note.title, note.description, note.drawing, note.is_deleted, note.deleted_at)


class AnonymousAccessTests(NotesBase):
    def test_anonymous_gets_401_everywhere(self):
        self.client.credentials()
        before = Note.objects.count()
        pk = self.alice_note.pk
        for method, url, data in [
            ("get", list_url(), None),
            ("get", list_url() + "?trash=1", None),
            ("post", list_url(), {"title": "x"}),
            ("get", detail_url(pk), None),
            ("put", detail_url(pk), {"title": "x"}),
            ("patch", detail_url(pk), {"title": "x"}),
            ("delete", detail_url(pk), None),
            ("post", detail_url(pk) + "restore/", None),
            ("delete", f"/api/notes/{self.alice_trash.pk}/purge/", None),
        ]:
            with self.subTest(method=method, url=url):
                resp = getattr(self.client, method)(url, data, format="json")
                self.assertEqual(resp.status_code, 401)
                self.assertNotIn(b"alice secret", resp.content)
        self.assertEqual(Note.objects.count(), before)


class OwnershipTests(NotesBase):
    """Пользователь alice не видит и не меняет заметки bob ни через один endpoint."""

    def test_list_contains_only_own_notes(self):
        resp = self.client.get(list_url())
        self.assertEqual(resp.status_code, 200)
        ids = {n["id"] for n in resp.json()}
        self.assertEqual(ids, {self.alice_note.pk})
        self.assertNotIn(b"bob", resp.content)

    def test_trash_contains_only_own_notes(self):
        resp = self.client.get(list_url() + "?trash=1")
        self.assertEqual(resp.status_code, 200)
        ids = {n["id"] for n in resp.json()}
        self.assertEqual(ids, {self.alice_trash.pk})

    def test_list_params_cannot_widen_scope(self):
        for qs in ["?user=%d" % self.bob.pk, "?user_id=%d" % self.bob.pk, "?trash=1&user=2",
                   "?trash=1' OR '1'='1", "?trash[]=1", "?id=%d" % self.bob_note.pk]:
            with self.subTest(qs=qs):
                resp = self.client.get(list_url() + qs)
                self.assertEqual(resp.status_code, 200)
                self.assertNotIn(b"bob", resp.content)

    def test_cannot_read_foreign_note(self):
        for note in (self.bob_note, self.bob_trash):
            resp = self.client.get(detail_url(note.pk))
            self.assertEqual(resp.status_code, 404)
            self.assertNotIn(b"bob", resp.content)

    def test_foreign_and_missing_note_look_the_same(self):
        foreign = self.client.get(detail_url(self.bob_note.pk))
        missing = self.client.get(detail_url(999999))
        self.assertEqual(foreign.status_code, missing.status_code)
        self.assertEqual(foreign.json(), missing.json())

    def test_cannot_modify_foreign_note(self):
        before = self.snapshot(self.bob_note)
        before_trash = self.snapshot(self.bob_trash)
        for method, url, data in [
            ("put", detail_url(self.bob_note.pk), {"title": "pwned", "description": "x"}),
            ("patch", detail_url(self.bob_note.pk), {"title": "pwned"}),
            ("delete", detail_url(self.bob_note.pk), None),
            ("post", detail_url(self.bob_trash.pk) + "restore/", None),
            ("delete", detail_url(self.bob_trash.pk) + "purge/", None),
        ]:
            with self.subTest(method=method, url=url):
                resp = getattr(self.client, method)(url, data, format="json")
                self.assertEqual(resp.status_code, 404)
        self.assertEqual(self.snapshot(self.bob_note), before)
        self.assertEqual(self.snapshot(self.bob_trash), before_trash)

    def test_cannot_create_note_for_another_user(self):
        for field in ["user", "user_id", "owner"]:
            with self.subTest(field=field):
                before = Note.objects.count()
                resp = self.client.post(list_url(), {"title": "x", field: self.bob.pk}, format="json")
                self.assertEqual(resp.status_code, 400)
                self.assertIn(field, resp.json())
                self.assertEqual(Note.objects.count(), before)
        self.assertEqual(Note.objects.filter(user=self.bob).count(), 2)

    def test_cannot_change_owner_or_service_fields(self):
        before = self.snapshot(self.alice_note)
        for data in [
            {"user": self.bob.pk},
            {"user_id": self.bob.pk},
            {"owner": self.bob.pk},
            {"id": self.bob_note.pk},
            {"is_deleted": True},
            {"deleted_at": "2000-01-01T00:00:00Z"},
            {"created_at": "2000-01-01T00:00:00Z"},
        ]:
            with self.subTest(data=data):
                resp = self.client.patch(detail_url(self.alice_note.pk), data, format="json")
                self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.snapshot(self.alice_note), before)

    def test_bob_still_sees_his_notes(self):
        self.as_user("bob")
        resp = self.client.get(list_url())
        self.assertEqual({n["id"] for n in resp.json()}, {self.bob_note.pk})

    def test_non_numeric_id_is_404_not_500(self):
        for path in ["/api/notes/abc/", "/api/notes/abc/purge/", "/api/notes/1abc/restore/",
                     "/api/notes/1%20OR%201=1/"]:
            with self.subTest(path=path):
                resp = self.client.delete(path) if "purge" in path else self.client.get(path)
                self.assertEqual(resp.status_code, 404)


class OwnerFlowTests(NotesBase):
    def test_create_read_update_trash_restore_purge(self):
        drawing = png_data_url()
        resp = self.client.post(
            list_url(), {"title": "New", "description": "text", "drawing": drawing}, format="json"
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        pk = resp.json()["id"]
        note = Note.objects.get(pk=pk)
        self.assertEqual(note.user, self.alice)
        self.assertEqual(note.drawing, drawing)

        self.assertEqual(self.client.get(detail_url(pk)).status_code, 200)
        resp = self.client.patch(detail_url(pk), {"title": "Edited"}, format="json")
        self.assertEqual(resp.status_code, 200)
        resp = self.client.put(detail_url(pk), {"title": "Put", "description": "d"}, format="json")
        self.assertEqual(resp.status_code, 200)

        # purge недоступен, пока заметка не в корзине
        self.assertEqual(self.client.delete(detail_url(pk) + "purge/").status_code, 404)
        self.assertTrue(Note.objects.filter(pk=pk).exists())

        self.assertEqual(self.client.delete(detail_url(pk)).status_code, 204)
        note.refresh_from_db()
        self.assertTrue(note.is_deleted)
        self.assertIsNotNone(note.deleted_at)

        resp = self.client.post(detail_url(pk) + "restore/")
        self.assertEqual(resp.status_code, 200)
        note.refresh_from_db()
        self.assertFalse(note.is_deleted)

        self.client.delete(detail_url(pk))
        self.assertEqual(self.client.delete(detail_url(pk) + "purge/").status_code, 204)
        self.assertFalse(Note.objects.filter(pk=pk).exists())

    def test_get_does_not_modify(self):
        before = self.snapshot(self.alice_trash)
        self.assertEqual(self.client.get(detail_url(self.alice_trash.pk) + "restore/").status_code, 405)
        self.assertEqual(self.client.get(detail_url(self.alice_trash.pk) + "purge/").status_code, 405)
        self.assertEqual(self.snapshot(self.alice_trash), before)


class NoteValidationTests(NotesBase):
    def assert_create_rejected(self, data, field=None):
        before = Note.objects.count()
        resp = self.client.post(list_url(), data, format="json")
        self.assertEqual(resp.status_code, 400, resp.content)
        if field:
            self.assertIn(field, resp.json())
        self.assertEqual(Note.objects.count(), before)

    def test_missing_and_null(self):
        self.assert_create_rejected({}, "title")
        self.assert_create_rejected({"title": None}, "title")
        self.assert_create_rejected({"title": ""}, "title")
        self.assert_create_rejected({"title": "   "}, "title")
        self.assert_create_rejected({"title": "x", "description": None}, "description")
        self.assert_create_rejected({"title": "x", "drawing": None}, "drawing")

    def test_wrong_types(self):
        for field in ["title", "description", "drawing"]:
            for value in [1, 1.5, True, ["x"], {"x": 1}]:
                with self.subTest(field=field, value=value):
                    data = {"title": "ok", field: value}
                    self.assert_create_rejected(data, field)

    def test_non_object_body(self):
        resp = self.client.post(list_url(), [{"title": "x"}], format="json")
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post(list_url(), "{bad json", content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_too_long(self):
        self.assert_create_rejected({"title": "a" * 201}, "title")
        self.assert_create_rejected({"title": "x", "description": "a" * 100_001}, "description")

    def test_unknown_field(self):
        self.assert_create_rejected({"title": "x", "color": "red"}, "color")

    def test_update_validation_does_not_partially_save(self):
        before = self.snapshot(self.alice_note)
        resp = self.client.patch(
            detail_url(self.alice_note.pk), {"title": "changed", "drawing": "data:image/png;base64,!!"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.snapshot(self.alice_note), before)

    def test_bad_drawings_rejected(self):
        valid = png_data_url()
        jpeg = io.BytesIO()
        Image.new("RGB", (8, 8)).save(jpeg, format="JPEG")
        bomb = io.BytesIO()
        Image.new("1", (20000, 20000), 0).save(bomb, format="PNG")
        truncated_png = base64.b64decode(valid.split(",", 1)[1])[:-20]
        cases = {
            "wrong prefix": "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
            "javascript": "javascript:alert(1)",
            "attribute breakout": 'data:image/png;base64,"><img src=x onerror=alert(1)>',
            "broken base64": "data:image/png;base64,@@@@",
            "whitespace in base64": valid[:40] + " " + valid[40:],
            "not png bytes": "data:image/png;base64," + base64.b64encode(b"<script>alert(1)</script>").decode(),
            "jpeg disguised": "data:image/png;base64," + base64.b64encode(jpeg.getvalue()).decode(),
            "truncated png": "data:image/png;base64," + base64.b64encode(truncated_png).decode(),
            "too large dims": png_data_url(size=(5000, 1), mode="L", color=0),
            "decompression bomb": "data:image/png;base64," + base64.b64encode(bomb.getvalue()).decode(),
            "too long": "data:image/png;base64," + "A" * (2 * 1024 * 1024),
        }
        for name, drawing in cases.items():
            with self.subTest(name=name):
                self.assert_create_rejected({"title": "x", "drawing": drawing}, "drawing")


class InjectionTests(NotesBase):
    def test_sql_like_strings_are_stored_literally(self):
        payload = "x'); DROP TABLE notes_note; --"
        resp = self.client.post(list_url(), {"title": payload, "description": "' OR '1'='1"}, format="json")
        self.assertEqual(resp.status_code, 201)
        note = Note.objects.get(pk=resp.json()["id"])
        self.assertEqual(note.title, payload)
        self.assertEqual(Note.objects.filter(user=self.bob).count(), 2)
        self.assertEqual(Note.objects.count(), 5)

    def test_markup_is_returned_as_json_data_not_html(self):
        xss = '<script>alert(1)</script><img src=x onerror=alert(1)>'
        resp = self.client.post(list_url(), {"title": xss, "description": xss}, format="json")
        self.assertEqual(resp.status_code, 201)
        pk = resp.json()["id"]
        # Текст не портится: хранится и возвращается как есть...
        self.assertEqual(Note.objects.get(pk=pk).title, xss)
        resp = self.client.get(detail_url(pk))
        # ...но только как JSON-данные, а не как HTML-страница.
        self.assertEqual(resp["Content-Type"], "application/json")
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")
        self.assertEqual(resp.json()["title"], xss)


class NoteExtraFieldsTests(NotesBase):
    """Поля для нового интерфейса: категория, цвет, «Важное»."""

    def test_set_category_color_important(self):
        resp = self.client.patch(
            detail_url(self.alice_note.pk),
            {"category": "Учеба", "color": "#FFF9C4", "is_important": True},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.alice_note.refresh_from_db()
        self.assertEqual(self.alice_note.category, "Учеба")
        self.assertEqual(self.alice_note.color, "#FFF9C4")
        self.assertTrue(self.alice_note.is_important)

    def test_defaults(self):
        resp = self.client.post(list_url(), {"title": "x"}, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["color"], "#FEFAF4")
        self.assertFalse(resp.json()["is_important"])
        self.assertEqual(resp.json()["category"], "")

    def test_invalid_values_rejected(self):
        before = self.snapshot(self.alice_note)
        for data in [
            {"color": "red"},
            {"color": "#000000"},
            {"color": "#FFF9C4; background:url(x)"},
            {"color": None},
            {"color": 1},
            {"is_important": "true"},
            {"is_important": 1},
            {"is_important": "yes"},
            {"is_important": None},
            {"category": "a" * 31},
            {"category": ["x"]},
            {"category": None},
        ]:
            with self.subTest(data=data):
                resp = self.client.patch(detail_url(self.alice_note.pk), data, format="json")
                self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.snapshot(self.alice_note), before)
        self.alice_note.refresh_from_db()
        self.assertEqual(self.alice_note.color, "#FEFAF4")
        self.assertFalse(self.alice_note.is_important)

    def test_cannot_mark_foreign_note_important(self):
        resp = self.client.patch(detail_url(self.bob_note.pk), {"is_important": True}, format="json")
        self.assertEqual(resp.status_code, 404)
        self.bob_note.refresh_from_db()
        self.assertFalse(self.bob_note.is_important)

    def test_only_json_accepted(self):
        resp = self.client.post(list_url(), {"title": "x", "is_important": "true"}, format="multipart")
        self.assertEqual(resp.status_code, 415)
