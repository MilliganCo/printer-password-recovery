# Диагностический скрипт для анализа элементов страницы принтера
from playwright.sync_api import sync_playwright
import json
from datetime import datetime

TARGET_URL = "http://printer.local/"

def diagnose_page():
    print("🔍 Диагностика страницы принтера")
    print("="*50)
    
    with sync_playwright() as p:
        # Запускаем браузер в видимом режиме для диагностики
        browser = p.chromium.launch(headless=False)
        
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        
        page = context.new_page()
        page.set_default_timeout(30000)
        
        print(f"📍 Переход на страницу: {TARGET_URL}")
        try:
            page.goto(TARGET_URL, wait_until='networkidle', timeout=30000)
        except:
            try:
                page.goto(TARGET_URL, wait_until='load', timeout=30000)
            except:
                page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=30000)
        
        print("✅ Страница загружена")
        print("⏳ Ожидание загрузки JavaScript (10 секунд)...")
        page.wait_for_timeout(10000)
        
        # Проверяем наличие фреймов
        print("\n" + "="*50)
        print("🔍 ПОИСК ФРЕЙМОВ")
        print("="*50)
        
        frames = page.frames
        print(f"Найдено фреймов: {len(frames)}")
        for i, frame in enumerate(frames):
            print(f"  Фрейм #{i}: name={frame.name}, url={frame.url}")
        
        # Ищем фрейм с формой
        target_frame = None
        for frame in frames:
            if frame.name == 'wlmframe' or 'Start_Wlm' in frame.url or frame.name:
                target_frame = frame
                print(f"\n✅ Найден целевой фрейм: name={frame.name}, url={frame.url}")
                break
        
        if not target_frame and len(frames) > 1:
            # Берем первый не-основной фрейм
            target_frame = frames[1] if len(frames) > 1 else frames[0]
            print(f"\n✅ Используем фрейм: name={target_frame.name}, url={target_frame.url}")
        
        # Ждем загрузки фрейма
        if target_frame:
            print("⏳ Ожидание загрузки содержимого фрейма (5 секунд)...")
            target_frame.wait_for_load_state('networkidle', timeout=30000)
            target_frame.wait_for_timeout(5000)
        
        # Сохраняем скриншот
        screenshot_path = f"diagnose_screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        page.screenshot(path=screenshot_path, full_page=True)
        print(f"📸 Скриншот сохранен: {screenshot_path}")
        
        # Используем целевой фрейм для анализа, если он найден
        work_frame = target_frame if target_frame else page
        
        print("\n" + "="*50)
        print("📋 АНАЛИЗ INPUT ЭЛЕМЕНТОВ")
        print(f"Работаем с: {'фреймом ' + target_frame.name if target_frame else 'основной страницей'}")
        print("="*50)
        
        # Получаем все input элементы из нужного фрейма
        all_inputs = work_frame.query_selector_all('input')
        print(f"\nВсего найдено input элементов: {len(all_inputs)}")
        
        input_data = []
        for i, inp in enumerate(all_inputs):
            try:
                inp_id = inp.get_attribute('id') or ''
                inp_name = inp.get_attribute('name') or ''
                inp_type = inp.get_attribute('type') or ''
                inp_class = inp.get_attribute('class') or ''
                inp_value = inp.get_attribute('value') or ''
                inp_placeholder = inp.get_attribute('placeholder') or ''
                inp_maxlength = inp.get_attribute('maxlength') or ''
                inp_disabled = inp.get_attribute('disabled')
                inp_style = inp.get_attribute('style') or ''
                inp_data_bind = inp.get_attribute('data-bind') or ''
                
                # Проверяем видимость через JavaScript
                is_visible = work_frame.evaluate('''(element) => {
                    if (!element) return false;
                    const style = window.getComputedStyle(element);
                    return element.offsetParent !== null && 
                           style.display !== 'none' && 
                           style.visibility !== 'hidden';
                }''', inp)
                
                # Получаем позицию элемента
                box = inp.bounding_box()
                position = f"x:{box['x']:.0f}, y:{box['y']:.0f}, w:{box['width']:.0f}, h:{box['height']:.0f}" if box else "не видим"
                
                input_info = {
                    'index': i + 1,
                    'id': inp_id,
                    'name': inp_name,
                    'type': inp_type,
                    'class': inp_class,
                    'value': inp_value,
                    'placeholder': inp_placeholder,
                    'maxlength': inp_maxlength,
                    'disabled': inp_disabled is not None,
                    'visible': is_visible,
                    'position': position,
                    'data-bind': inp_data_bind,
                    'style': inp_style
                }
                
                input_data.append(input_info)
                
                print(f"\n--- Input #{i+1} ---")
                print(f"  ID: {inp_id}")
                print(f"  Name: {inp_name}")
                print(f"  Type: {inp_type}")
                print(f"  Class: {inp_class[:50]}")
                print(f"  Value: {inp_value[:30]}")
                print(f"  Placeholder: {inp_placeholder}")
                print(f"  MaxLength: {inp_maxlength}")
                print(f"  Disabled: {inp_disabled is not None}")
                print(f"  Видимый: {'✅' if is_visible else '❌'}")
                print(f"  Позиция: {position}")
                if inp_data_bind:
                    print(f"  Data-bind: {inp_data_bind}")
                
            except Exception as e:
                print(f"  ⚠️  Ошибка при анализе input #{i+1}: {e}")
        
        print("\n" + "="*50)
        print("🔍 ПОИСК ЦЕЛЕВЫХ ЭЛЕМЕНТОВ")
        print("="*50)
        
        # Ищем конкретные элементы в нужном фрейме
        target_selectors = [
            "#arg01_UserName",
            "#arg02_Password",
            'input[name="arg01_UserName"]',
            'input[name="arg02_Password"]',
            'input[type="text"][name="arg01_UserName"]',
            'input[type="password"][name="arg02_Password"]'
        ]
        
        for selector in target_selectors:
            try:
                element = work_frame.query_selector(selector)
                if element:
                    print(f"\n✅ Найден элемент: {selector}")
                    try:
                        is_visible = work_frame.evaluate('''(element) => {
                            if (!element) return false;
                            const style = window.getComputedStyle(element);
                            return element.offsetParent !== null && 
                                   style.display !== 'none' && 
                                   style.visibility !== 'hidden';
                        }''', element)
                        print(f"   Видимый: {'✅' if is_visible else '❌'}")
                        box = element.bounding_box()
                        if box:
                            print(f"   Позиция: x:{box['x']:.0f}, y:{box['y']:.0f}")
                        value = element.get_attribute('value') or ''
                        print(f"   Значение: {value[:30]}")
                    except Exception as e:
                        print(f"   ⚠️  Ошибка проверки: {e}")
                else:
                    print(f"❌ Не найден: {selector}")
            except Exception as e:
                print(f"⚠️  Ошибка поиска {selector}: {e}")
        
        print("\n" + "="*50)
        print("📄 АНАЛИЗ HTML СТРУКТУРЫ")
        print("="*50)
        
        # Сохраняем HTML страницы
        html_path = f"diagnose_html_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        html_content = page.content()
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"💾 HTML основной страницы сохранен: {html_path}")
        
        # Сохраняем HTML фрейма
        if target_frame:
            frame_html_path = f"diagnose_frame_html_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            frame_html_content = target_frame.content()
            with open(frame_html_path, 'w', encoding='utf-8') as f:
                f.write(frame_html_content)
            print(f"💾 HTML фрейма сохранен: {frame_html_path}")
            html_content = frame_html_content  # Используем HTML фрейма для дальнейшего анализа
        
        # Ищем упоминания arg01_UserName и arg02_Password в HTML
        if 'arg01_UserName' in html_content:
            print("✅ 'arg01_UserName' найден в HTML")
            # Находим контекст вокруг этого элемента
            idx = html_content.find('arg01_UserName')
            start = max(0, idx - 200)
            end = min(len(html_content), idx + 500)
            context = html_content[start:end]
            print("\nКонтекст в HTML:")
            print("-" * 50)
            print(context)
            print("-" * 50)
        else:
            print("❌ 'arg01_UserName' НЕ найден в HTML")
        
        if 'arg02_Password' in html_content:
            print("\n✅ 'arg02_Password' найден в HTML")
            idx = html_content.find('arg02_Password')
            start = max(0, idx - 200)
            end = min(len(html_content), idx + 500)
            context = html_content[start:end]
            print("\nКонтекст в HTML:")
            print("-" * 50)
            print(context)
            print("-" * 50)
        else:
            print("\n❌ 'arg02_Password' НЕ найден в HTML")
        
        print("\n" + "="*50)
        print("🔍 ПОИСК ЭЛЕМЕНТОВ С DATA-BIND")
        print("="*50)
        
        # Ищем все элементы с data-bind в нужном фрейме
        elements_with_bind = work_frame.query_selector_all('[data-bind]')
        print(f"\nНайдено элементов с data-bind: {len(elements_with_bind)}")
        
        for i, el in enumerate(elements_with_bind[:20]):  # Показываем первые 20
            try:
                tag = el.evaluate('el => el.tagName')
                el_id = el.get_attribute('id') or ''
                el_name = el.get_attribute('name') or ''
                data_bind = el.get_attribute('data-bind') or ''
                
                if 'UserName' in data_bind or 'Password' in data_bind or 'arg01' in el_id or 'arg02' in el_id:
                    print(f"\n--- Элемент #{i+1} (ВАЖНЫЙ) ---")
                    print(f"  Тег: {tag}")
                    print(f"  ID: {el_id}")
                    print(f"  Name: {el_name}")
                    print(f"  Data-bind: {data_bind}")
            except:
                pass
        
        print("\n" + "="*50)
        print("💾 СОХРАНЕНИЕ ДАННЫХ")
        print("="*50)
        
        # Сохраняем данные в JSON
        json_path = f"diagnose_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        output_data = {
            'url': TARGET_URL,
            'timestamp': datetime.now().isoformat(),
            'frame_used': target_frame.name if target_frame else 'main',
            'frame_url': target_frame.url if target_frame else TARGET_URL,
            'inputs': input_data,
            'target_elements_found': {
                'arg01_UserName_by_id': work_frame.query_selector("#arg01_UserName") is not None,
                'arg02_Password_by_id': work_frame.query_selector("#arg02_Password") is not None,
                'arg01_UserName_by_name': work_frame.query_selector('input[name="arg01_UserName"]') is not None,
                'arg02_Password_by_name': work_frame.query_selector('input[name="arg02_Password"]') is not None,
            }
        }
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        print(f"💾 Данные сохранены в JSON: {json_path}")
        
        print("\n" + "="*50)
        print("✅ Диагностика завершена!")
        print("="*50)
        print("\nНажмите Enter для закрытия браузера...")
        input()
        
        browser.close()

if __name__ == "__main__":
    try:
        diagnose_page()
    except KeyboardInterrupt:
        print("\n\n🛑 Прервано пользователем")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

