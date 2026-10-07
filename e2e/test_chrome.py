import time
import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from django.contrib.auth import get_user_model

User = get_user_model()

@pytest.fixture(scope="class")
def chrome_driver():
    """Настройка Google Chrome для тестирования с обходом сетевых ошибок"""
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-extensions")
    
    # Ключевые настройки для обхода ошибок net:: и SSL-сертификатов
    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument("--allow-insecure-localhost")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    # Запускаем браузер
    driver = webdriver.Chrome(options=chrome_options)
    
    # Неявное ожидание элементов в DOM-дереве
    driver.implicitly_wait(15) 
    
    yield driver
    driver.quit()


@pytest.mark.django_db(transaction=True)
class TestGoogleChromeFrontend:

    @pytest.fixture(autouse=True)
    def setup_user(self):
        """Создаем пользователя в тестовой БД перед тестами"""
        self.username = "chrome_user"
        self.email = "chrome@hf78.ru"
        self.password = "Zx-cv!Bn7-mQ_42plx"
        
        if not User.objects.filter(username=self.username).exists():
            User.objects.create_user(
                username=self.username,
                email=self.email,
                password=self.password
            )

    def test_registration_flow(self, live_server, chrome_driver):
        """Тест: Регистрация нового пользователя через интерфейс"""
        driver = chrome_driver
        
        # Гарантируем, что тестовый сервер открывается по HTTP, а не по HTTPS
        target_url = live_server.url.replace("https://", "http://")
        driver.get(f"{target_url}/register/")

        # Даем 3 секунды на загрузку страницы и скриптов
        time.sleep(3) 

        # Заполняем форму по id из вашего register.html
        driver.find_element(By.ID, "name").send_keys("new_chrome_bob")
        driver.find_element(By.ID, "email").send_keys("bob_chrome@example.com")
        driver.find_element(By.ID, "password").send_keys(self.password)
        driver.find_element(By.ID, "password2").send_keys(self.password)
        
        time.sleep(2) 

        # Отправляем форму
        driver.find_element(By.CSS_SELECTOR, "button.btn-primary").click()

        # КРИТИЧЕСКАЯ ПАУЗА: 5 секунд вашему JS на fetch-запрос и редирект
        time.sleep(5) 
        
        # Проверяем успешный переход
        assert "/workspace/" in driver.current_url
        assert User.objects.filter(username="new_chrome_bob").exists()

    def test_login_and_workspace_actions(self, live_server, chrome_driver):
        """Тест: Авторизация и создание новой заметки в модальном окне"""
        driver = chrome_driver
        
        target_url = live_server.url.replace("https://", "http://")
        driver.get(f"{target_url}/login/")
        
        time.sleep(3) 

        # Вводим данные в форму авторизации из login.html
        driver.find_element(By.ID, "login").send_keys(self.username)
        driver.find_element(By.ID, "password").send_keys(self.password)
        time.sleep(2) 
        
        driver.find_element(By.CSS_SELECTOR, "button.btn-primary").click()

        # КРИТИЧЕСКАЯ ПАУЗА: 5 секунд на авторизацию, запись JWT в localStorage и переход в Workspace
        time.sleep(5) 

        # Проверяем, что email подгрузился скриптом в шапку доски
        user_email_el = driver.find_element(By.ID, "userEmail")
        assert self.email in user_email_el.text

        # Кликаем на кнопку "+ Создать" в сайдбаре workspace.html
        driver.find_element(By.ID, "createBtn").click()

        # Пауза на анимацию появления Bootstrap-модалки
        time.sleep(2) 

        # Заполняем форму новой заметки по её id
        driver.find_element(By.ID, "noteTitle").send_keys("Заметка из Google Chrome")
        driver.find_element(By.ID, "noteText").send_keys("Линия 1\nЛиния 2")
        driver.find_element(By.ID, "noteCategory").send_keys("Автоматизация")
        time.sleep(2) 

        # Сохраняем заметку
        driver.find_element(By.ID, "noteSave").click()

        # КРИТИЧЕСКАЯ ПАУЗА: 5 секунд на отправку заметки на API, закрытие окна и обновление DOM
        time.sleep(5) 

        # Проверяем, появилась ли карточка в сетке заметок #grid
        grid_element = driver.find_element(By.ID, "grid")
        assert "Заметка из Google Chrome" in grid_element.text
        assert "Автоматизация" in grid_element.text
        
        time.sleep(3)
