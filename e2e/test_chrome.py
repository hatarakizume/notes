import time
import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from django.contrib.auth import get_user_model

User = get_user_model()

@pytest.fixture(scope="class")
def chrome_driver():
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-extensions")
    
    # Ключевые настройки для обхода ошибок net:: и SSL-сертификатов
    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument("--allow-insecure-localhost")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    driver = webdriver.Chrome(options=chrome_options)
    
    driver.implicitly_wait(15) 
    
    yield driver
    driver.quit()


@pytest.mark.django_db(transaction=True)
class TestGoogleChromeFrontend:

    @pytest.fixture(autouse=True)
    def setup_user(self):
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
        driver = chrome_driver
        
        target_url = live_server.url.replace("https://", "http://")
        driver.get(f"{target_url}/register/")

        time.sleep(3) 

        driver.find_element(By.ID, "name").send_keys("new_chrome_bob")
        driver.find_element(By.ID, "email").send_keys("bob_chrome@example.com")
        driver.find_element(By.ID, "password").send_keys(self.password)
        driver.find_element(By.ID, "password2").send_keys(self.password)
        
        time.sleep(2) 

        driver.find_element(By.CSS_SELECTOR, "button.btn-primary").click()

        time.sleep(5) 
        
        assert "/workspace/" in driver.current_url
        assert User.objects.filter(username="new_chrome_bob").exists()

    def test_login_and_workspace_actions(self, live_server, chrome_driver):
        driver = chrome_driver
        
        target_url = live_server.url.replace("https://", "http://")
        driver.get(f"{target_url}/login/")
        
        time.sleep(3) 

        driver.find_element(By.ID, "login").send_keys(self.username)
        driver.find_element(By.ID, "password").send_keys(self.password)
        time.sleep(2) 
        
        driver.find_element(By.CSS_SELECTOR, "button.btn-primary").click()

        time.sleep(5) 

        user_email_el = driver.find_element(By.ID, "userEmail")
        assert self.email in user_email_el.text

        driver.find_element(By.ID, "createBtn").click()

        time.sleep(2) 

        driver.find_element(By.ID, "noteTitle").send_keys("Заметка из Google Chrome")
        driver.find_element(By.ID, "noteText").send_keys("Линия 1\nЛиния 2")
        driver.find_element(By.ID, "noteCategory").send_keys("Автоматизация")
        time.sleep(2) 

        driver.find_element(By.ID, "noteSave").click()

        time.sleep(5) 

        grid_element = driver.find_element(By.ID, "grid")
        assert "Заметка из Google Chrome" in grid_element.text
        assert "Автоматизация" in grid_element.text
        
        time.sleep(3)
