import dearpygui.dearpygui as dpg
import psycopg2
from psycopg2 import OperationalError, Error
import logging
from datetime import datetime
import os

# ==================== КОНФИГУРАЦИЯ ====================
DB_CONFIG = {
    'host': 'localhost',
    'port': '5432',
    'dbname': 'gisp',
    'user': 'gisp',
    'password': 'gisp123'
}

SQL_QUERIES = {
    'get_maps': 'SELECT t."Id" as id, t."Name" as name FROM public."Maps" as t ORDER BY t."Name";',
    'get_layers': 'SELECT t."Id" as id, t."MapId" as map_id, t."Name" as name, t."Url" as url, t."Type" as type FROM public."Layers" as t WHERE t."Type" = \'xyz\' ORDER BY t."Name";',
    'insert_layer': """
        INSERT INTO public."Layers" ("MapId", "Name", "Url", "Type") 
        VALUES (%s, %s, %s, %s) 
        RETURNING "Id"
    """,
    'check_layer_exists': """
        SELECT 1 
        FROM public."Layers" as t
        WHERE t."MapId" = %s AND t."Name" = %s AND t."Type" = %s
        LIMIT 1
    """
}

LOG_CONFIG = {
    'level': logging.INFO,
    'format': '%(asctime)s - %(levelname)s - %(message)s',
    'handlers': [
        logging.FileHandler('db_operations.log'),
        logging.StreamHandler()
    ]
}

# ==================== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ====================
db_connection = None
all_maps = []
all_layers = []
left_panel_selected_map = None
right_panel_selected_map = None
selected_layers = {"left": None, "right": None}
current_layers = {"left": [], "right": []}


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def log_query(query, params=None):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[{timestamp}] Выполнен запрос: {query}"
    if params:
        log_message += f"\nПараметры: {params}"
    logger.info(log_message)
    print(log_message)


def toggle_fullscreen():
    dpg.maximize_viewport()


def show_window(sender, app_data, user_data):
    windows = ["connection_window", "main_window"]
    for window in windows:
        if window == user_data:
            dpg.show_item(window)
        else:
            dpg.hide_item(window)


def update_count_label(panel_side, count):
    dpg.configure_item(f"{panel_side}_count_label", default_value=f"Количество: {count}")


# ==================== ОСНОВНЫЕ ФУНКЦИИ ====================
def connect_to_db():
    global db_connection, all_maps, all_layers

    conn_params = {
        'host': dpg.get_value("host_input") or DB_CONFIG['host'],
        'port': dpg.get_value("port_input") or DB_CONFIG['port'],
        'dbname': dpg.get_value("dbname_input") or DB_CONFIG['dbname'],
        'user': dpg.get_value("username_input") or DB_CONFIG['user'],
        'password': dpg.get_value("password_input") or DB_CONFIG['password']
    }

    try:
        logger.info(f"Попытка подключения к БД с параметрами: {conn_params}")

        conn = psycopg2.connect(**conn_params)
        db_connection = conn

        with conn.cursor() as cur:
            log_query(SQL_QUERIES['get_maps'])
            cur.execute(SQL_QUERIES['get_maps'])
            all_maps = cur.fetchall()

            log_query(SQL_QUERIES['get_layers'])
            cur.execute(SQL_QUERIES['get_layers'])
            all_layers = cur.fetchall()

        map_names = [m[1] for m in all_maps]
        dpg.configure_item("left_maps_combo", items=map_names)
        dpg.configure_item("right_maps_combo", items=map_names)
        dpg.configure_item("db_status_text", default_value="Подключено успешно", color=(0, 255, 0))

        show_window(None, None, "main_window")

        logger.info(f"Загружено карт: {len(all_maps)}, слоев: {len(all_layers)}")
        return True

    except OperationalError as e:
        error_msg = f"Ошибка подключения: {e}"
        logger.error(error_msg)
        dpg.configure_item("db_status_text", default_value=error_msg, color=(255, 0, 0))
        return False


def update_layers_list(panel_side, map_id=None):
    if map_id is None:
        map_id = left_panel_selected_map if panel_side == "left" else right_panel_selected_map

    if not map_id:
        return

    layers = [layer for layer in all_layers if layer[1] == map_id]
    current_layers[panel_side] = layers
    items = [f"{layer[2]} ({layer[3]}) [ID: {layer[0]}]" for layer in layers]
    dpg.configure_item(f"{panel_side}_layers_listbox", items=items)
    selected_layers[panel_side] = None
    update_count_label(panel_side, len(layers))
    logger.info(f"Обновлен список слоев для {panel_side} панели (map_id={map_id}), количество: {len(layers)}")


def on_map_select(sender, app_data, user_data):
    panel_side = user_data
    selected_map_name = app_data

    selected_map = next((m for m in all_maps if m[1] == selected_map_name), None)
    if not selected_map:
        return

    if panel_side == "left":
        global left_panel_selected_map
        left_panel_selected_map = selected_map[0]
        update_layers_list("left")
    else:
        global right_panel_selected_map
        right_panel_selected_map = selected_map[0]
        update_layers_list("right")


def on_layer_select(sender, app_data, user_data):
    panel_side = user_data
    try:
        # Получаем индекс выбранного элемента
        selected_index = dpg.get_value(sender)  # Это вернет индекс выбранного элемента
        selected_layers[panel_side] = selected_index
        logger.info(f"Выбран слой с индексом: {selected_index}")
    except Exception as e:
        logger.error(f"Ошибка при выборе слоя: {e}")
        selected_layers[panel_side] = None

def check_layer_exists(map_id, name, layer_type):
    try:
        with db_connection.cursor() as cur:
            log_query(SQL_QUERIES['check_layer_exists'], (map_id, name, layer_type))
            cur.execute(SQL_QUERIES['check_layer_exists'], (map_id, name, layer_type))
            return cur.fetchone() is not None
    except Error as e:
        logger.error(f"Ошибка при проверке слоя: {e}")
        return False

def move_layer_to_right():
    if not db_connection:
        error_msg = "Нет подключения к БД"
        logger.error(error_msg)
        dpg.configure_item("action_status_text", default_value=error_msg, color=(255, 0, 0))
        return

    if not left_panel_selected_map or not right_panel_selected_map:
        error_msg = "Выберите карты в обеих панелях"
        logger.warning(error_msg)
        dpg.configure_item("action_status_text", default_value=error_msg, color=(255, 0, 0))
        return

    if selected_layers["left"] is None:
        error_msg = "Выберите слой для копирования"
        logger.warning(error_msg)
        dpg.configure_item("action_status_text", default_value=error_msg, color=(255, 0, 0))
        return

    try:
        selected_index = selected_layers["left"]
        source_layers = current_layers["left"]

        if selected_index is None or not isinstance(selected_index, int) or selected_index >= len(source_layers):
            error_msg = "Неверный индекс выбранного слоя"
            logger.error(error_msg)
            dpg.configure_item("action_status_text", default_value=error_msg, color=(255, 0, 0))
            return

        selected_layer = source_layers[selected_index]
        logger.info(f"Выбран слой для копирования: {selected_layer}")

        if check_layer_exists(right_panel_selected_map, selected_layer[2], selected_layer[4]):
            error_msg = f"Слой '{selected_layer[2]}' уже существует в целевой карте"
            logger.warning(error_msg)
            dpg.configure_item("action_status_text", default_value=error_msg, color=(255, 165, 0))
            return

        with db_connection.cursor() as cur:
            params = (right_panel_selected_map, selected_layer[2], selected_layer[3], selected_layer[4])
            log_query(SQL_QUERIES['insert_layer'], params)
            cur.execute(SQL_QUERIES['insert_layer'], params)
            new_id = cur.fetchone()[0]

            all_layers.append((new_id, right_panel_selected_map, selected_layer[2], selected_layer[3], selected_layer[4]))
            db_connection.commit()

            success_msg = f"Слой '{selected_layer[2]}' успешно скопирован (новый ID: {new_id})"
            logger.info(success_msg)

            update_layers_list("right")
            dpg.configure_item("action_status_text",
                             default_value=success_msg,
                             color=(0, 255, 0))

    except Error as e:
        db_connection.rollback()
        error_msg = f"Ошибка при копировании: {e}"
        logger.error(error_msg)
        dpg.configure_item("action_status_text",
                         default_value=error_msg,
                         color=(255, 0, 0))
    except Exception as e:
        error_msg = f"Неожиданная ошибка: {str(e)}"
        logger.error(error_msg)
        dpg.configure_item("action_status_text",
                         default_value=error_msg,
                         color=(255, 0, 0))


# ==================== ГЛАВНЫЙ ИНТЕРФЕЙС ====================
def create_gui():
    dpg.create_context()
    dpg.create_viewport(title='Управление слоями карт', width=1920, height=1080)
    dpg.maximize_viewport()

    # Инициализация шрифтов с поддержкой кириллицы
    try:
        font_path = os.path.join("assets", "CruinnMedium.ttf")
        if os.path.exists(font_path):
            with dpg.font_registry():
                default_font = dpg.add_font(font_path, 17)
                dpg.add_font_range_hint(dpg.mvFontRangeHint_Default)
                dpg.add_font_range_hint(dpg.mvFontRangeHint_Cyrillic)
                dpg.bind_font(default_font)
        else:
            # Если шрифт не найден, используем стандартный с поддержкой кириллицы
            with dpg.font_registry():
                default_font = dpg.add_font("NotoSans-Regular.ttf", 17)  # Замените на доступный шрифт
                dpg.add_font_range_hint(dpg.mvFontRangeHint_Default)
                dpg.add_font_range_hint(dpg.mvFontRangeHint_Cyrillic)
                dpg.bind_font(default_font)
            logger.warning(f"Файл шрифта не найден: {font_path}. Используется стандартный шрифт.")
    except Exception as e:
        logger.error(f"Ошибка при загрузке шрифта: {e}")

    with dpg.viewport_menu_bar():
        with dpg.menu(label="Окна"):
            dpg.add_menu_item(label="Подключение к БД", callback=show_window, user_data="connection_window")
            dpg.add_menu_item(label="Работа со слоями", callback=show_window, user_data="main_window")
        dpg.add_menu_item(label="Полный экран", callback=toggle_fullscreen)

    # Окно подключения к БД
    with dpg.window(label="Подключение к БД", tag="connection_window", width=600, height=400):
        with dpg.group(horizontal=True):
            with dpg.group(width=300):
                dpg.add_input_text(label="Хост", tag="host_input", default_value=DB_CONFIG['host'], width=250)
                dpg.add_input_text(label="Порт", tag="port_input", default_value=DB_CONFIG['port'], width=250)
                dpg.add_input_text(label="База данных", tag="dbname_input", default_value=DB_CONFIG['dbname'],
                                   width=250)
            with dpg.group(width=300):
                dpg.add_input_text(label="Пользователь", tag="username_input", default_value=DB_CONFIG['user'],
                                   width=250)
                dpg.add_input_text(label="Пароль", tag="password_input", default_value=DB_CONFIG['password'],
                                   password=True, width=250)
                dpg.add_button(label="Подключиться", callback=connect_to_db, width=250)
        dpg.add_text(tag="db_status_text", default_value="")

    # Основное окно работы со слоями
    with dpg.window(label="Работа со слоями", tag="main_window", show=False, width=1920, height=1080):
        dpg.add_text("ЛЕВАЯ ПАНЕЛЬ: исходные данные | ПРАВАЯ ПАНЕЛЬ: целевая карта", indent=250)
        with dpg.group(horizontal=True):
            # Левая панель (исходные данные)
            with dpg.child_window(width=450, height=550):
                dpg.add_text("Исходная карта:")
                dpg.add_combo(tag="left_maps_combo", items=[], width=430, callback=on_map_select, user_data="left")
                dpg.add_spacer(height=10)
                dpg.add_text("Слои выбранной карты:")
                dpg.add_listbox(tag="left_layers_listbox", items=[], num_items=15, width=430,
                                callback=on_layer_select, user_data="left")
                dpg.add_text(tag="left_count_label", default_value="Количество: 0")

            # Центральная панель с кнопкой
            with dpg.group(horizontal=False):
                dpg.add_spacer(height=100)
                dpg.add_button(
                    label="→ Копировать в карту →",
                    width=250,
                    height=50,
                    callback=move_layer_to_right
                )
                dpg.add_spacer(height=20)
                dpg.add_text(tag="action_status_text", default_value="", indent=50)

            # Правая панель (целевая карта)
            with dpg.child_window(width=450, height=550):
                dpg.add_text("Целевая карта:")
                dpg.add_combo(tag="right_maps_combo", items=[], width=430, callback=on_map_select, user_data="right")
                dpg.add_spacer(height=10)
                dpg.add_text("Слои выбранной карты:")
                dpg.add_listbox(tag="right_layers_listbox", items=[], num_items=15, width=430,
                                callback=on_layer_select, user_data="right")
                dpg.add_text(tag="right_count_label", default_value="Количество: 0")

    dpg.setup_dearpygui()
    dpg.show_viewport()
    show_window(None, None, "connection_window")
    dpg.start_dearpygui()
    dpg.destroy_context()


if __name__ == "__main__":
    logging.basicConfig(**LOG_CONFIG)
    logger = logging.getLogger(__name__)
    print("Запуск приложения")
    print("=" * 50)
    print("Начало работы приложения")
    print("Логи будут сохраняться в db_operations.log и выводиться в терминал")
    print("=" * 50)

    create_gui()

    logger.info("Завершение работы приложения")
    print("=" * 50)
    print("Работа приложения завершена")
    print("=" * 50)