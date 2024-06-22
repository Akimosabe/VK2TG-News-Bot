import json
import os
import sys
import threading
import time
import telebot
import vk_api
from telebot import types

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
    print("Телеграм инициализирован.")


# Функция для инициализации VK API
def start_vk():
    vk_session = vk_api.VkApi(token=vk_token)
    module.vk = vk_session.get_api()
    print("ВК инициализирован.")

    # Запуск функции проверки новостной ленты
    check_news(int(time.time()))


# Функция для проверки новостной ленты VK
def check_news(start_time):
    retries = 0
    while True:
        time.sleep(time_check)  # Задержка между проверками
        try:
            newsfeed = module.vk.newsfeed.get(
                count=100, start_time=start_time, max_photos=10
            )
            posts = (json.loads(json.dumps(newsfeed))).get("items")
            if posts:
                start_time = posts[0]["date"] + 1
                for post in posts[::-1]:
                    check_content(post)
            retries = 0  # Сбросить счетчик повторных попыток при успешном запросе
        except Exception as e:
            retries += 1
            print(f"Ошибка при проверке новостной ленты: {e}")
            if retries >= retries_max:
                print("Превышено максимальное количество повторных попыток. Завершение программы.")
                break
            print(f"Повторная попытка через {retries_time} секунд (попытка {retries}/{retries_max})")
            time.sleep(retries_time)


# Функция для проверки прикреплений в посте VK
def check_content(post):
    if post.get("photos"):
        return

    if post.get("copy_history"):
        post = post["copy_history"][0]

    if not (post.get("attachments")):
        pass
    else:
        send_content(get_content(post))


# Функция для получения URL изображения определенного размера
def scale(size_path):
    photo_size = None

    for photoType in size_path[0:]:
        if photoType.get("type") == "x":
            photo_size = photoType.get("url")
        if photoType.get("type") == "y":
            photo_size = photoType.get("url")
        if photoType.get("type") == "z":
            photo_size = photoType.get("url")
        if photoType.get("type") == "w":
            photo_size = photoType.get("url")

    return photo_size


# Функция для получения материалов из поста VK
def get_content(post):
    attach_list = []
    photo_group = []

    for att in post["attachments"][0:]:
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
            doc_type = attachment.get("type")
            if doc_type != 3 and doc_type != 4 and doc_type != 5:
                att_type = "other"
            attachments = attachment.get("url")

        elif att_type == "album":
            preview = scale(attachment["thumb"].get("sizes"))
            title = attachment.get("title")
            owner_id = str(attachment.get("owner_id"))
            album_id = str(attachment.get("id"))
            attachments = str(f"https://vk.com/album{owner_id}_{album_id}")

        elif att_type == "link" and attachment.get("description") == "Статья":
            preview = scale(attachment["photo"].get("sizes"))
            title = attachment.get("title")
            attachments = str(attachment.get("url"))

        if attachments is not None:
            attach_list.append(
                {
                    "type": att_type,
                    "link": attachments,
                    "title": title,
                    "preview": preview,
                }
            )

    if photo_group:
        attach_list.append({"type": "photo", "link": photo_group})

    return attach_list


# Функция для отправки в Telegram
def send_content(attachments):
    for attach_element in attachments[0:]:
        att_type = attach_element.get("type")
        link = attach_element.get("link")
        title = attach_element.get("title")
        preview = attach_element.get("preview")

        try:
            if att_type == "photo":
                media_photo = []
                for photo_url in link[0:]:
                    media_photo.append(types.InputMediaPhoto(photo_url))
                module.bot.send_media_group(telegram_chat, media_photo)
                print("Изображение отправлено.")

            elif att_type == "video":
                module.bot.send_media_group(
                    telegram_chat,
                    [types.InputMediaPhoto(preview, caption=f"{title}\n{link}")],
                )
                print("Видео отправлено.")

            elif att_type == "album":
                module.bot.send_media_group(
                    telegram_chat,
                    [types.InputMediaPhoto(preview, caption=f"{title}\n{link}")],
                )
                print("Альбом отправлен.")

            elif att_type == "link":
                module.bot.send_media_group(
                    telegram_chat,
                    [types.InputMediaPhoto(preview, caption=f"{title}\n{link}")],
                )
                print("Ссылка отправлена.")

            elif att_type == "doc" or att_type == "gif":
                module.bot.send_document(telegram_chat, link)
                print("Документ отправлен.")

            elif att_type == "other":
                module.bot.send_message(telegram_chat, f"{title}\n{link}")
                print("Отправлено.")

        except Exception as e:
            pass


# Запуск инициализации VK и Telegram в отдельных потоках
launch_vk = threading.Thread(target=start_vk)
launch_tg = threading.Thread(target=start_tg)

launch_vk.start()
launch_tg.start()
launch_vk.join()
launch_tg.join()
