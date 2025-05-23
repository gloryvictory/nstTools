import dearpygui.dearpygui as dpg
import psycopg2
from psycopg2 import OperationalError, Error
import logging
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('db_operations.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Глобальные переменные
db_connection = None
all_maps = []
all_layers = []
left_panel_selected_map = None
right_panel_selected_map = None
selected_layers = {"left": None, "right": None}


def log_query(query, params=None):
    """Логирование SQL запроса"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[{timestamp}] Выполнен запрос: {query}"
    if params:
        log_message += f"\nПараметры: {params}"

    logger.info(log_message)
    print(log_message)


def toggle_fullscreen():
    """Переключение полноэкранного режима"""
    if dpg.is_viewport_maximized():
        dpg.maximize_viewport()
    else:
        dpg.maximize_viewport()


def show_window(sender, app_data, user_data):
    """Показать выбранное окно и скрыть другие"""
    windows = ["connection_window", "main_window"]
    for window in windows:
        if window == user_data:
            dpg.show_item(window)
        else:
            dpg.hide_item(window)


def connect_to_db():
    """Подключение к PostgreSQL"""
    global db_connection, all_maps, all_layers
    try:
        conn_params = {
            'host': dpg.get_value("host_input"),
            'port': dpg.get_value("port_input"),
            'dbname': dpg.get_value("dbname_input"),
            'user': dpg.get_value("username_input"),
            'password': dpg.get_value("password_input")
        }

        logger.info(f"Попытка подключения к БД с параметрами: {conn_params}")

        conn = psycopg2.connect(**conn_params)
        db_connection = conn

        # Загрузка карт
        maps_query = 'select t."Id" as id , t."Name"as name from public."Maps" as t ORDER by t."Name";'
        log_query(maps_query)
        with conn.cursor() as cur:
            cur.execute(maps_query)
            all_maps = cur.fetchall()

        # Загрузка слоев
        layers_query = 'select t."Id"  as id, t."MapId" as map_id, t."Name" as name_ru, t."Url" as url, t."Type" as type from public."Layers" as t where t."Type" = \'xyz\' order by t."Name"'
        log_query(layers_query)
        with conn.cursor() as cur:
            cur.execute(layers_query)
            all_layers = cur.fetchall()

        map_names = [m[1] for m in all_maps]
        dpg.configure_item("left_maps_combo", items=map_names)
        dpg.configure_item("right_maps_combo", items=map_names)
        dpg.configure_item("db_status_text", default_value="Подключено успешно", color=(0, 255, 0))

        # Переключаемся на основное окно после успешного подключения
        show_window(None, None, "main_window")

        logger.info("Подключение к БД установлено успешно")
        return True

    except OperationalError as e:
        error_msg = f"Ошибка подключения: {e}"
        logger.error(error_msg)
        dpg.configure_item("db_status_text", default_value=error_msg, color=(255, 0, 0))
        return False


def update_layers_list(panel_side, map_id=None):
    """Обновление списка слоев для выбранной карты"""
    if map_id is None:
        map_id = left_panel_selected_map if panel_side == "left" else right_panel_selected_map

    if not map_id:
        return

    layers = [layer for layer in all_layers if layer[1] == map_id]
    items = [f"{layer[2]} ({layer[3]}) [ID: {layer[0]}]" for layer in layers]
    dpg.configure_item(f"{panel_side}_layers_listbox", items=items)
    selected_layers[panel_side] = None
    logger.info(f"Обновлен список слоев для {panel_side} панели (map_id={map_id})")


def on_map_select(sender, app_data, user_data):
    """Обработчик выбора карты в комбо-боксе"""
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
    """Обработчик выбора слоя"""
    panel_side = user_data
    selected_layers[panel_side] = app_data


def move_layers(direction):
    """Добавление слоёв в целевую карту"""
    if not db_connection:
        error_msg = "Нет подключения к БД"
        logger.error(error_msg)
        dpg.configure_item("action_status_text", default_value=error_msg, color=(255, 0, 0))
        return

    source_panel = "left" if direction == "right" else "right"
    target_panel = "right" if direction == "right" else "left"

    source_map = left_panel_selected_map if source_panel == "left" else right_panel_selected_map
    target_map = left_panel_selected_map if target_panel == "left" else right_panel_selected_map

    if not source_map or not target_map:
        error_msg = "Выберите карты в обеих панелях"
        logger.warning(error_msg)
        dpg.configure_item("action_status_text", default_value=error_msg, color=(255, 0, 0))
        return

    if selected_layers[source_panel] is None:
        error_msg = "Выберите слой для копирования"
        logger.warning(error_msg)
        dpg.configure_item("action_status_text", default_value=error_msg, color=(255, 0, 0))
        return

    try:
        with db_connection.cursor() as cur:
            source_layers = [layer for layer in all_layers if layer[1] == source_map]
            selected_layer = source_layers[selected_layers[source_panel]]

            insert_query = """
                INSERT INTO layers (map_id, name_ru, type) 
                VALUES (%s, %s, %s) 
                RETURNING id
            """
            params = (target_map, selected_layer[2], selected_layer[3])
            log_query(insert_query, params)

            cur.execute(insert_query, params)
            new_id = cur.fetchone()[0]
            all_layers.append((new_id, target_map, selected_layer[2], selected_layer[3]))

            db_connection.commit()

            success_msg = f"Слой ID {selected_layer[0]} скопирован в карту ID {target_map}, новый ID: {new_id}"
            logger.info(success_msg)

            update_layers_list(target_panel)
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


def create_gui():
    dpg.create_context()

    # Создаем viewport в полноэкранном режиме
    dpg.create_viewport(title='Управление слоями карт', width=1920, height=1080)
    dpg.maximize_viewport()
    with dpg.font_registry():
        # with dpg.font(r"c:\windows\fonts\cour.ttf", 15, default_font=True) as default_font:
        with dpg.font(r"assets\CruinnMedium.ttf", 17, default_font=True) as default_font:
            dpg.add_font_range_hint(dpg.mvFontRangeHint_Default)
            dpg.add_font_range_hint(dpg.mvFontRangeHint_Cyrillic)


    # Главное меню
    with dpg.viewport_menu_bar():
        with dpg.menu(label="Окна"):
            dpg.add_menu_item(label="Подключение к БД", callback=show_window, user_data="connection_window")
            dpg.add_menu_item(label="Работа со слоями", callback=show_window, user_data="main_window")
        dpg.add_menu_item(label="Полный экран", callback=toggle_fullscreen)

    # Окно подключения к БД
    with dpg.window(label="Подключение к БД", tag="connection_window", width=600, height=400):
        with dpg.group(horizontal=True):
            with dpg.group(width=300):
                dpg.add_input_text(label="Хост", tag="host_input", default_value="localhost", width=250)
                dpg.add_input_text(label="Порт", tag="port_input", default_value="5432", width=250)
                dpg.add_input_text(label="База данных", tag="dbname_input", default_value="gisp", width=250)
            with dpg.group(width=300):
                dpg.add_input_text(label="Пользователь", tag="username_input", default_value="gisp", width=250)
                dpg.add_input_text(label="Пароль", tag="password_input", default_value="", password=True, width=250)
                dpg.add_button(label="Подключиться", callback=connect_to_db, width=250)
        dpg.add_text(tag="db_status_text", default_value="")

    # Основное окно работы со слоями
    with dpg.window(label="Работа со слоями", tag="main_window", show=False, width=1920, height=1080):
        dpg.add_text("ЛЕВАЯ ПАНЕЛЬ: исходные данные | ПРАВАЯ ПАНЕЛЬ: куда копируем", indent=250)
        with dpg.group(horizontal=True):
            # Левая панель
            with dpg.child_window(width=450, height=550):
                dpg.add_text("Исходная карта:")
                dpg.add_combo(
                    tag="left_maps_combo",
                    items=[],
                    width=430,
                    callback=on_map_select,
                    user_data="left"
                )
                dpg.add_spacer(height=10)
                dpg.add_text("Слои выбранной карты:")
                dpg.add_listbox(
                    tag="left_layers_listbox",
                    items=[],
                    num_items=15,
                    width=430,
                    # height=400,
                    callback=on_layer_select,
                    user_data="left"
                )

            # Кнопки перемещения
            with dpg.group(horizontal=False):
                dpg.add_spacer(height=100)
                dpg.add_button(
                    label="→ Копировать в правую →",
                    width=200,
                    height=50,
                    callback=lambda: move_layers("right")
                )
                dpg.add_spacer(height=20)
                dpg.add_button(
                    label="← Копировать в левую ←",
                    width=200,
                    height=50,
                    callback=lambda: move_layers("left")
                )
                dpg.add_spacer(height=20)
                dpg.add_text(tag="action_status_text", default_value="", indent=25)

            # Правая панель
            with dpg.child_window(width=450, height=550):
                dpg.add_text("Целевая карта:")
                dpg.add_combo(
                    tag="right_maps_combo",
                    items=[],
                    width=430,
                    callback=on_map_select,
                    user_data="right"
                )
                dpg.add_spacer(height=10)
                dpg.add_text("Слои выбранной карты:")
                dpg.add_listbox(
                    tag="right_layers_listbox",
                    items=[],
                    num_items=15,
                    width=430,
                    # height=400,
                    callback=on_layer_select,
                    user_data="right"
                )

    # Настройка и запуск

    dpg.bind_font(default_font)
    dpg.show_font_manager()

    dpg.setup_dearpygui()
    dpg.show_viewport()

    # Показываем окно подключения по умолчанию
    show_window(None, None, "connection_window")

    dpg.start_dearpygui()
    dpg.destroy_context()


if __name__ == "__main__":
    logger.info("Запуск приложения")
    print("=" * 50)
    print("Начало работы приложения")
    print("Логи будут сохраняться в db_operations.log и выводиться в терминал")
    print("=" * 50)

    create_gui()

    logger.info("Завершение работы приложения")
    print("=" * 50)
    print("Работа приложения завершена")
    print("=" * 50)
