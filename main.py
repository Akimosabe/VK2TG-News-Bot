import json
import os
import sys
import threading
import time
import logging
import telebot
import vk_api
from telebot import types

# Настройка логгирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    datefmt="%d.%m.%Y %H:%M",
)

# Чтение конфигурационного файла JSON
with open("config.json", "r") as f:
    config = json.load(f)

# Получение токенов и настроек из конфигурационного файла
vk_token = config["VK"]["tokenvk"]
telegram_token = config["Telegram"]["tokentg"]
telegram_chat = config["Telegram"]["chat"]
time_check = int(config["Settings"]["time_check"])
retries_max = int(config["Settings"]["retries_max"])
retries_time = int(config["Settings"]["retries_time"])

# Инициализация текущего модуля
module = sys.modules[__name__]


# Функция для инициализации Telegram бота
def start_tg():
    module.bot = telebot.TeleBot(telegram_token)
    logging.info("Телеграм инициализирован.")


# Функция для инициализации VK API
def start_vk():
    vk_session = vk_api.VkApi(token=vk_token)
    module.vk = vk_session.get_api()
    logging.info("ВК инициализирован.")

    # Запуск функции проверки новостной ленты
    check_news(int(time.time()))


# Функция для проверки новостной ленты VK
def check_news(start_time: int):
    retries = 0
    while True:
        time.sleep(time_check)  # Задержка между проверками
        try:
            newsfeed = module.vk.newsfeed.get(count=100, start_time=start_time, max_photos=10)
            posts = newsfeed.get("items")
            if posts:
                start_time = posts[0]["date"] + 1
                for post in posts[::-1]:
                    check_content(post)
            retries = 0  # Сбросить счетчик повторных попыток при успешном запросе
        except Exception as e:
            retries += 1
            logging.error(f"Ошибка при проверке новостной ленты: {e}")
            if retries >= retries_max:
                logging.error("Превышено максимальное количество повторных попыток. Завершение программы.")
                break
            logging.info(f"Повторная попытка через {retries_time} секунд (попытка {retries}/{retries_max})")
            time.sleep(retries_time)


# Функция для проверки прикреплений в посте VK
def check_content(post: dict):
    if post.get("photos"):
        return

    if post.get("copy_history"):
        post = post["copy_history"][0]

    if post.get("attachments"):
        send_content(get_content(post))


# Функция для получения URL изображения определенного размера
def scale(size_path: list) -> str:
    for photoType in size_path:
        if photoType.get("type") in {"x", "y", "z", "w"}:
            return photoType.get("url")
    return None


# Функция для получения материалов из поста VK
def get_content(post):
    attach_list = []
    photo_group = []

    # Определяем автора поста
    if post.get("source_id") > 0:
        # Пост от пользователя
        author_info = module.vk.users.get(user_ids=post.get("source_id"))[0]
        author = f"{author_info.get('first_name')} {author_info.get('last_name')}"
    else:
        # Пост от сообщества или паблика
        group_info = module.vk.groups.getById(group_ids=abs(post.get("source_id")))[0]
        author = group_info.get("name")

    # Получаем текст поста, если он есть
    text = post.get("text", "")

    # Добавляем автора и текст в начало сообщения
    comment = f"Источник: **{author}**\n\n{text}\n"

    for att in post["attachments"]:
        att_type = att.get("type")
        attachment = att[att_type]

        attachments = None
        title = None
        preview = None

        if att_type == "photo":
            photo_size = scale(attachment.get("sizes"))
            photo_group.append(photo_size)
            continue

        elif att_type == "video":
            photos = {}

            owner_id = str(attachment.get("owner_id"))
            video_id = str(attachment.get("id"))
            access_key = str(attachment.get("access_key"))

            for key, value in attachment.items():
                if key.startswith("photo_"):
                    photos[key] = value

            preview = attachment[max(photos)]
            title = attachment.get("title")
            full_url = str(owner_id + "_" + video_id + "_" + access_key)

            attachments = module.vk.video.get(videos=full_url)["items"][0].get("player")

        elif att_type == "doc":
            title = attachment.get("title")
            if attachment.get("type") in {3, 4, 5}:
                attachments = attachment.get("url")
            else:
                att_type = "other"
                attachments = attachment.get("url")

        elif att_type == "album":
            preview = scale(attachment["thumb"].get("sizes"))
            title = attachment.get("title")
            attachments = f"https://vk.com/album{attachment.get('owner_id')}_{attachment.get('id')}"

        elif att_type == "link" and attachment.get("description") == "Статья":
            preview = scale(attachment["photo"].get("sizes"))
            title = attachment.get("title")
            attachments = attachment.get("url")

        if attachments:
            attach_list.append({
                "type": att_type,
                "link": attachments,
                "title": title,
                "preview": preview,
                "comment": comment  
            })

    if photo_group:
        attach_list.append({"type": "photo", "link": photo_group, "comment": comment})

    return attach_list

# Функция для отправки в Telegram
def send_content(attachments):
    for attach_element in attachments:
        att_type = attach_element.get("type")
        link = attach_element.get("link")
        title = attach_element.get("title")
        preview = attach_element.get("preview")
        comment = attach_element.get("comment")  # Получаем комментарий

        try:
            if att_type == "photo":
                media_photo = [types.InputMediaPhoto(photo_url, caption=comment) for photo_url in link]
                module.bot.send_media_group(telegram_chat, media_photo)
                logging.info("Изображение отправлено.")

            elif att_type == "video":
                module.bot.send_media_group(telegram_chat,[types.InputMediaPhoto(preview, caption=f"{comment}\n{link}")])
                logging.info("Видео отправлено.")

            elif att_type == "album":
                module.bot.send_media_group(telegram_chat, [types.InputMediaPhoto(preview, caption=f"{comment}\n{title}\n{link}")])
                logging.info("Альбом отправлен.")

            elif att_type == "link":
                module.bot.send_message(telegram_chat, f"{comment}\n{title}\n{link}")
                logging.info("Ссылка отправлена.")

            elif att_type in {"doc", "gif"}:
                module.bot.send_document(telegram_chat, link, caption=comment)
                logging.info("Документ отправлен.")

            elif att_type == "other":
                module.bot.send_message(telegram_chat, f"{comment}\n{title}\n{link}")
                logging.info("Отправлено.")

        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения в Telegram: {e}")


# Запуск инициализации VK и Telegram в отдельных потоках
launch_vk = threading.Thread(target=start_vk)
launch_tg = threading.Thread(target=start_tg)

launch_vk.start()
launch_tg.start()
launch_vk.join()
launch_tg.join()