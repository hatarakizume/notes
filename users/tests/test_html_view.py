from django.test import TestCase
from django.urls import reverse

class NotesHtmlTemplatesTestCase(TestCase):

    def test_home_page_renders_correct_html(self):
        response = self.client.get(reverse('home'), secure=True, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'index.html')

    def test_login_page_renders_correct_html(self):
        response = self.client.get(reverse('login_page'), secure=True, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'login.html')

    def test_register_page_renders_correct_html(self):
        response = self.client.get(reverse('register_page'), secure=True, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'register.html')

    def test_workspace_page_renders_correct_html(self):
        response = self.client.get(reverse('workspace'), secure=True, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'workspace.html')

    def test_account_page_renders_correct_html(self):
        response = self.client.get(reverse('account'), secure=True, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'account.html')
