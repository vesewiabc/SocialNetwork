from flask import Flask, render_template, request, redirect, session, flash, url_for, jsonify
import sqlite3
import os
from datetime import datetime
import hashlib
from werkzeug.utils import secure_filename
import feedparser
from bs4 import BeautifulSoup
import requests
import re


    
app = Flask(__name__)
app.secret_key = "123"

# Настройки для загрузки файлов
UPLOAD_FOLDER = 'static/uploads/avatars'
GROUP_UPLOAD_FOLDER = 'static/uploads/groups'
POST_MEDIA_FOLDER = 'static/uploads/posts'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'avi', 'mov', 'wmv'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'wmv'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['GROUP_UPLOAD_FOLDER'] = GROUP_UPLOAD_FOLDER
app.config['POST_MEDIA_FOLDER'] = POST_MEDIA_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB

# Создаем папки для загрузок, если их нет
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(GROUP_UPLOAD_FOLDER, exist_ok=True)
os.makedirs(POST_MEDIA_FOLDER, exist_ok=True)


def get_current_date():
    """Возвращает текущую дату в формате ДД.ММ.ГГГГ"""
    return datetime.now().strftime('%d.%m.%Y')


def get_current_datetime():
    """Возвращает текущую дату и время в формате ДД.ММ.ГГГГ ЧЧ:ММ"""
    return datetime.now().strftime('%d.%m.%Y %H:%M')


def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def allowed_image_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def allowed_video_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_VIDEO_EXTENSIONS


# Добавляем соединение с БД для работы со строками как словарями
def get_db_connection():
    conn = sqlite3.connect('users.db')
    conn.row_factory = sqlite3.Row
    return conn


# Функция для преобразования Row в словарь
def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


# Функция для преобразования списка Row в список словарей
def rows_to_dicts(rows):
    return [dict(row) for row in rows]


# Функция для добавления недостающих столбцов в таблицы
def migrate_database():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Проверяем и добавляем недостающие столбцы
    try:
        cursor.execute("SELECT role FROM users LIMIT 1")
    except sqlite3.OperationalError:
        print("Добавляем столбец role в таблицу users...")
        cursor.execute('ALTER TABLE users ADD COLUMN role TEXT DEFAULT "user"')

    try:
        cursor.execute("SELECT is_banned FROM users LIMIT 1")
    except sqlite3.OperationalError:
        print("Добавляем столбец is_banned в таблицу users...")
        cursor.execute('ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0')

    try:
        cursor.execute("SELECT avatar FROM user_profiles LIMIT 1")
    except sqlite3.OperationalError:
        print("Добавляем столбец avatar в таблицу user_profiles...")
        cursor.execute('ALTER TABLE user_profiles ADD COLUMN avatar TEXT')
        cursor.execute('UPDATE user_profiles SET avatar = "default_avatar.png" WHERE avatar IS NULL')

    # Проверяем и добавляем request_permissions если нет
    try:
        cursor.execute("SELECT request_permissions FROM groups LIMIT 1")
    except sqlite3.OperationalError:
        print("Добавляем столбец request_permissions в таблицу groups...")
        cursor.execute('ALTER TABLE groups ADD COLUMN request_permissions TEXT DEFAULT "moderators"')


# Проверяем и добавляем таблицу post_media если нет
    try:
        cursor.execute("SELECT post_id FROM post_media LIMIT 1")
    except sqlite3.OperationalError:
        print("Таблица post_media не существует, создаем...")
        cursor.execute('''
                CREATE TABLE post_media (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id INTEGER,
                    group_post_id INTEGER,
                    filename TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    thumbnail TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
                    FOREIGN KEY (group_post_id) REFERENCES group_posts(id) ON DELETE CASCADE
                )
            ''')
    else:
        # Проверяем структуру
        cursor.execute("PRAGMA table_info(post_media)")
        columns = cursor.fetchall()
        for col in columns:
            if col[1] == 'post_id' and col[3] == 1:  # post_id имеет NOT NULL
                print("Исправляем структуру таблицы post_media...")
                # Создаем временную таблицу
                cursor.execute('''
                        CREATE TABLE post_media_new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            post_id INTEGER,
                            group_post_id INTEGER,
                            filename TEXT NOT NULL,
                            file_type TEXT NOT NULL,
                            thumbnail TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
                            FOREIGN KEY (group_post_id) REFERENCES group_posts(id) ON DELETE CASCADE
                        )
                    ''')

                # Копируем данные
                cursor.execute('''
                        INSERT INTO post_media_new 
                        SELECT id, post_id, group_post_id, filename, file_type, thumbnail, created_at 
                        FROM post_media
                    ''')

                # Удаляем старую и переименовываем новую
                cursor.execute('DROP TABLE post_media')
                cursor.execute('ALTER TABLE post_media_new RENAME TO post_media')
                break

    # Создаем таблицу черного списка, если ее нет
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS blacklist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        blocker_id INTEGER NOT NULL,
        blocked_id INTEGER NOT NULL,
        reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (blocker_id) REFERENCES users(id),
        FOREIGN KEY (blocked_id) REFERENCES users(id),
        UNIQUE(blocker_id, blocked_id)
    )
    ''')

    conn.commit()
    conn.close()


# Таблицы для хранения пользователей и их данных
def create_tables():
    connection = get_db_connection()
    cursor = connection.cursor()

    # Таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'user',
        is_banned INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Таблица профилей пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE,
        full_name TEXT,
        bio TEXT,
        location TEXT,
        website TEXT,
        avatar TEXT DEFAULT 'default_avatar.png',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    ''')


# Таблица личных постов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        visibility TEXT DEFAULT 'public',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    ''')

    # Таблица друзей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS friendships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (sender_id) REFERENCES users(id),
        FOREIGN KEY (receiver_id) REFERENCES users(id),
        UNIQUE(sender_id, receiver_id)
    )
    ''')

    # Таблица лайков постов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS post_likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (post_id) REFERENCES posts(id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        UNIQUE(post_id, user_id)
    )
    ''')

    # Таблица комментариев
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (post_id) REFERENCES posts(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    ''')

    # Таблица групп/пабликов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        avatar TEXT DEFAULT 'default_group.png',
        creator_id INTEGER NOT NULL,
        is_public BOOLEAN DEFAULT 1,
        post_permissions TEXT DEFAULT 'all', -- 'admins', 'moderators', 'all'
        request_permissions TEXT DEFAULT 'moderators', -- 'admins', 'moderators'
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (creator_id) REFERENCES users(id)
    )
    ''')

    # Таблица подписчиков групп
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS group_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        role TEXT DEFAULT 'member', -- 'admin', 'moderator', 'member'
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (group_id) REFERENCES groups(id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        UNIQUE(group_id, user_id)
    )
    ''')

    # Таблица постов в группах
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS group_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        author_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (group_id) REFERENCES groups(id),
        FOREIGN KEY (author_id) REFERENCES users(id)
    )
    ''')

    # Таблица лайков постов в группах
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS group_post_likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (post_id) REFERENCES group_posts(id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        UNIQUE(post_id, user_id)
    )
    ''')

    # Таблица заявок на вступление в приватные группы
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS group_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        status TEXT DEFAULT 'pending', -- 'pending', 'approved', 'rejected'
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (group_id) REFERENCES groups(id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        UNIQUE(group_id, user_id)
    )
    ''')

    # Таблица медиафайлов для постов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS post_media (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER,
        group_post_id INTEGER,
        filename TEXT NOT NULL,
        file_type TEXT NOT NULL, -- 'image' или 'video'
        thumbnail TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
        FOREIGN KEY (group_post_id) REFERENCES group_posts(id) ON DELETE CASCADE
    )
    ''')

    # Таблица импортированных новостей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS imported_news (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        link TEXT NOT NULL UNIQUE,
        source TEXT DEFAULT 'RBC',
        published TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Таблица жалоб
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reporter_id INTEGER NOT NULL,
        reported_id INTEGER NOT NULL,
        reason TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        admin_notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (reporter_id) REFERENCES users(id),
        FOREIGN KEY (reported_id) REFERENCES users(id)
    )
    ''')

    connection.commit()
    connection.close()

    # Выполняем миграции для существующих таблиц
    migrate_database()

    # Создаем тех-админа, если его нет
    create_tech_admin()


def create_tech_admin():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Проверяем, существует ли уже тех-админ
    cursor.execute("SELECT id FROM users WHERE username = 'techadmin'")
    tech_admin = cursor.fetchone()

    if not tech_admin:
        # Создаем тех-админа
        cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                       ('techadmin', 'techadmin123', 'techadmin'))
        print("Создан аккаунт тех-админа: Логин: techadmin, Пароль: techadmin123")

    # Проверяем, существует ли админ
    cursor.execute("SELECT id FROM users WHERE username = 'admin'")
    admin = cursor.fetchone()

    if not admin:
        # Обновляем существующего админа или создаем нового
        cursor.execute("SELECT id FROM users WHERE username = 'admin'")
        existing_admin = cursor.fetchone()

        if existing_admin:
            # Обновляем роль существующего админа
            cursor.execute("UPDATE users SET role = 'admin' WHERE username = 'admin'")
        else:
            # Создаем нового админа
            cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                           ('admin', 'admin123', 'admin'))
            print("Создан аккаунт администратора: Логин: admin, Пароль: admin123")

    conn.commit()
    conn.close()


# Добавляем функцию для форматирования даты в шаблонах
@app.context_processor
def utility_processor():
    def format_datetime(value, format='%d.%m.%Y %H:%M'):
        if not value:
            return ''

        # Если дата уже в формате ДД.ММ.ГГГГ, просто добавляем время если нужно
        if isinstance(value, str):
            if len(value) == 10 and '.' in value:  # ДД.ММ.ГГГГ
                if format == '%d.%m.%Y':
                    return value
                else:
                    return f"{value} 00:00"  # Добавляем время по умолчанию

        return value

    return {'datetime_format': format_datetime}

# Функция для получения медиафайлов поста
def get_post_media(post_id, is_group_post=True):
    """Получает медиафайлы для поста"""
    conn = get_db_connection()

    if is_group_post:
        media = conn.execute('''
            SELECT id, filename, file_type, thumbnail 
            FROM post_media 
            WHERE group_post_id = ?
            ORDER BY id
        ''', (post_id,)).fetchall()
    else:
        media = conn.execute('''
            SELECT id, filename, file_type, thumbnail 
            FROM post_media 
            WHERE post_id = ?
            ORDER BY id
        ''', (post_id,)).fetchall()

    conn.close()
    return rows_to_dicts(media)


@app.template_filter('format_date')
def format_date_filter(value):
    if not value:
        return ''

    if isinstance(value, str):
        try:
            # Пробуем разные форматы входящих дат
            formats_to_try = [
                '%Y-%m-%d',  # 2026-01-27
                '%Y-%m-%d %H:%M:%S',  # 2026-01-27 10:30:15
                '%Y-%m-%d %H:%M:%S.%f',  # 2026-01-27 10:30:15.123456
                '%Y.%m.%d',  # 2026.01.27 - ВАШ ФОРМАТ
                '%Y.%m.%d %H:%M:%S',  # 2026.01.27 10:30:15
                '%d-%m-%Y %H:%M:%S',  # 27-01-2026 10:30:15
                '%d-%m-%Y %H:%M:%S.%f',  # 27-01-2026 10:30:15.123456
            ]

            for fmt in formats_to_try:
                try:
                    dt = datetime.strptime(value, fmt)
                    return dt.strftime('%d.%m.%Y')
                except:
                    continue
        except Exception as e:
            print(f"Ошибка форматирования даты {value}: {e}")

    # Если значение - объект datetime
    if hasattr(value, 'strftime'):
        return value.strftime('%d.%m.%Y')

    # Если ничего не сработало, возвращаем как есть
    return value


# Проверка прав на создание поста
def check_post_permission(group_id, user_id, conn):
    """Проверяет, может ли пользователь создавать посты в группе"""
    # Получаем настройки группы
    group = conn.execute('SELECT post_permissions FROM groups WHERE id = ?', (group_id,)).fetchone()

    if not group:
        return False

    # Получаем роль пользователя
    membership = conn.execute('SELECT role FROM group_members WHERE group_id = ? AND user_id = ?',
                              (group_id, user_id)).fetchone()

    if not membership:
        return False

    user_role = membership['role']
    post_permissions = group['post_permissions']

    # Проверяем права в зависимости от настроек
    if post_permissions == 'admins':
        return user_role == 'admin'
    elif post_permissions == 'moderators':
        return user_role in ['admin', 'moderator']
    else:  # 'all'
        return True


# ==================== НОВОСТНЫЕ ФУНКЦИИ ====================

def get_news_feed(user_id=None, limit=20):
    """Получение ленты новостей (посты пользователей + импортированные новости)"""
    conn = get_db_connection()

    user_posts = []
    imported_news = []

    try:
        # Получаем посты пользователей (свои и друзей)
        if user_id:
            try:
                # Получаем посты всех пользователей для упрощения
                user_posts_rows = conn.execute('''
                    SELECT p.*, u.username 
                    FROM posts p
                    JOIN users u ON p.user_id = u.id
                    ORDER BY p.created_at DESC
                    LIMIT 10
                ''').fetchall()

                if user_posts_rows:
                    user_posts = rows_to_dicts(user_posts_rows)
            except Exception as e:
                print(f"Ошибка при получении постов: {e}")
                import traceback
                traceback.print_exc()

        # Получаем импортированные новости
        try:
            news_rows = conn.execute('''
                SELECT *, 'news' as type FROM imported_news
                ORDER BY published DESC
                LIMIT 10
            ''').fetchall()

            if news_rows:
                imported_news = rows_to_dicts(news_rows)
        except Exception as e:
            print(f"Ошибка при получении новостей: {e}")

    except Exception as e:
        print(f"Общая ошибка при получении ленты: {e}")
    finally:
        conn.close()

    # Объединяем
    all_feed = []

    # Добавляем посты
    for post in user_posts:
        post['type'] = 'post'
        all_feed.append(post)


# Добавляем новости
    for news in imported_news:
        news['type'] = 'news'
        all_feed.append(news)

    # Простая сортировка - сначала новые посты, потом новости
    try:
        # Приводим даты к строковому формату для сравнения
        def get_sort_key(item):
            if item['type'] == 'post':
                return item.get('created_at', '') if isinstance(item.get('created_at'), str) else ''
            else:
                return item.get('published', '')

        all_feed.sort(key=lambda x: get_sort_key(x), reverse=True)
    except Exception as e:
        print(f"Ошибка сортировки: {e}")
        # Если сортировка не работает, просто оставляем как есть

    return all_feed[:limit]


def fetch_ria_news():
    """Получение новостей с сайта RIA.ru"""
    try:
        print("Получаем новости с RIA.ru...")

        # URL главной страницы RIA.ru
        url = "https://ria.ru/"

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        }

        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        # Проверяем кодировку
        response.encoding = 'utf-8'
        html_content = response.text

        print(f"Получено {len(html_content)} символов с RIA.ru")

        all_news = []

        # Ищем новости в HTML
        # Паттерн для поиска новостных блоков на RIA.ru
        news_patterns = [
            r'<a[^>]*?class="[^"]*list-item__title[^"]*"[^>]*?href="([^"]+)"[^>]*?>([^<]+)</a>',
            r'<a[^>]*?href="/[0-9]+/[^"]*"[^>]*?class="[^"]*cell__title[^"]*"[^>]*?>([^<]+)</a>',
            r'<a[^>]*?href="([^"]+)"[^>]*?class="[^"]*item__title[^"]*"[^>]*?>([^<]+)</a>',
            r'<a[^>]*?href="([^"]+)"[^>]*?title="([^"]+)"[^>]*?>',
            r'<div[^>]*?class="[^"]*news-item[^"]*"[^>]*?>.*?<a[^>]*?href="([^"]+)"[^>]*?>([^<]+)</a>',
        ]

        for pattern in news_patterns:
            matches = re.findall(pattern, html_content, re.DOTALL)
            if matches:
                print(f"Найдено {len(matches)} новостей по паттерну")

                for match in matches[:10]:  # Берем первые 10
                    try:
                        if isinstance(match, tuple):
                            if len(match) == 2:
                                link_part = match[0]
                                title = match[1]
                            else:
                                continue
                        else:
                            continue

                        # Очищаем заголовок
                        title = re.sub(r'\s+', ' ', title).strip()
                        title = re.sub(r'<[^>]+>', '', title)

                        # Формируем полную ссылку
                        if link_part.startswith('http'):
                            link = link_part
                        elif link_part.startswith('/'):
                            link = f"https://ria.ru{link_part}"
                        else:
                            continue

                        # Получаем краткое описание (попробуем найти рядом)
                        description = "Читать далее на RIA.ru"

                        # Ищем описание рядом со ссылкой
                        desc_pattern = r'<div[^>]*?class="[^"]*itemcontent[^"]*"[^>]*?>.*?<div[^>]*?class="[^"]*itemtext[^"]*"[^>]*?>([^<]+)</div>'
                        desc_match = re.search(desc_pattern, html_content[
                                                              html_content.find(link_part) - 500:html_content.find(


link_part) + 500])
                        if desc_match:
                            description = desc_match.group(1).strip()
                            description = re.sub(r'<[^>]+>', '', description)
                            if len(description) > 150:
                                description = description[:150] + '...'

                        # Создаем объект новости
                        news_item = {
                            'title': title[:200],
                            'description': description,
                            'link': link,
                            'published': datetime.now().strftime('%d.%m.%Y %H:%M'),
                            'source': 'RIA.ru'
                        }

                        # Проверяем, нет ли дубликатов
                        if not any(n['title'] == news_item['title'] for n in all_news):
                            all_news.append(news_item)
                            print(f"Добавлена новость: {title[:50]}...")

                    except Exception as e:
                        print(f"Ошибка при обработке новости: {e}")
                        continue

        # Если не нашли новости по паттернам, попробуем другой подход
        if not all_news:
            print("Пробуем альтернативный метод парсинга...")

            # Ищем все ссылки с заголовками
            link_pattern = r'<a[^>]*?href="(/[0-9]+/[^"/]*)"[^>]*?>([^<]+)</a>'
            matches = re.findall(link_pattern, html_content)

            for match in matches[:15]:  # Берем первые 15
                try:
                    link_part, title = match
                    title = re.sub(r'\s+', ' ', title).strip()

                    if len(title) > 10:  # Фильтруем короткие заголовки
                        link = f"https://ria.ru{link_part}"

                        news_item = {
                            'title': title[:200],
                            'description': "Новость с RIA.ru",
                            'link': link,
                            'published': datetime.now().strftime('%d.%m.%Y %H:%M'),
                            'source': 'RIA.ru'
                        }

                        all_news.append(news_item)

                except:
                    continue

        print(f"Всего собрано {len(all_news)} новостей с RIA.ru")
        return all_news[:8]  # Возвращаем до 8 новостей

    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе к RIA.ru: {e}")
        return []
    except Exception as e:
        print(f"Неожиданная ошибка при парсинге RIA.ru: {e}")
        import traceback
        traceback.print_exc()
        return []


def fetch_lenta_news():
    """Альтернативный источник - Lenta.ru"""
    try:
        print("Пробуем получить новости с Lenta.ru...")
        url = "https://lenta.ru/rss/news"

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # Простой парсинг RSS
        content = response.text

        all_news = []

        # Ищем элементы item в RSS
        item_pattern = r'<item>.*?<title>(.*?)</title>.*?<link>(.*?)</link>.*?<description>(.*?)</description>.*?</item>'
        matches = re.findall(item_pattern, content, re.DOTALL)

        for match in matches[:5]:
            try:
                title, link, description = match

                # Очищаем HTML теги
                title = re.sub(r'<[^>]+>', '', title).strip()
                description = re.sub(r'<[^>]+>', '', description).strip()

                if len(description) > 150:
                    description = description[:150] + '...'

                news_item = {
                    'title': title[:200],
                    'description': description,
                    'link': link,
                    'published': datetime.now().strftime('%d.%m.%Y %H:%M'),
                    'source': 'Lenta.ru'
                }

                all_news.append(news_item)

            except:
                continue

        return all_news

    except:
        return []


def fetch_news_simple():
    """Простой импорт новостей - создает тестовые новости если не удалось получить реальные"""
    try:
        print("Пробуем получить новости с реальных сайтов...")

        # Сначала пробуем RIA.ru
        news_items = fetch_ria_news()

        # Если не получилось, пробуем Lenta.ru
        if not news_items:
            print("RIA.ru не сработал, пробуем Lenta.ru...")
            news_items = fetch_lenta_news()

        # Если все еще нет новостей, создаем тестовые
        if not news_items:
            print("Создаем тестовые новости...")
            news_items = create_test_news()

        return news_items

    except Exception as e:
        print(f"Ошибка в fetch_news_simple: {e}")
        return create_test_news()


def create_test_news():
    """Создание тестовых новостей"""
    topics = [
        ("Технологии", "Новые технологии меняют нашу жизнь"),
        ("Наука", "Ученые совершили важное открытие"),
        ("Образование", "Онлайн-обучение становится популярнее"),
        ("ИТ", "Развитие программирования и ИИ"),
        ("Соцсети", "Новые возможности в социальных сетях"),
        ("Киберспорт", "Турниры по киберспорту набирают популярность"),
        ("Игры", "Выход новых игровых проектов"),
        ("Бизнес", "Стартапы привлекают инвестиции")
    ]

    import random
    news_items = []

    for i, (topic, desc) in enumerate(topics):
        news_items.append({
            'title': f'{topic}: Новости дня',
            'description': f'{desc}. Подробнее читайте в полной версии статьи.',
            'link': f'https://example.com/news_{i + 1}',
            'published': datetime.now().strftime('%d.%m.%Y %H:%M'),
            'source': 'Новостной портал'
        })

    return news_items


def import_news_to_db():
    """Импорт новостей в базу данных"""
    try:
        print("Начинаем импорт новостей...")

        # Получаем новости
        news_items = fetch_news_simple()

        if not news_items:
            print("Не удалось получить ни одной новости")
            return False

        print(f"Получено {len(news_items)} новостей для импорта")

        conn = get_db_connection()

        imported_count = 0
        for i, news in enumerate(news_items, 1):
            try:
                # Проверяем, не существует ли уже такая новость
                existing = conn.execute(
                    'SELECT id FROM imported_news WHERE link = ? OR title = ?',
                    (news['link'], news['title'])
                ).fetchone()


                if not existing:
                    # Преобразуем строку даты в datetime объект
                    published_str = news.get('published', '')
                    try:
                        published_dt = datetime.strptime(published_str, '%d.%m.%Y %H:%M')
                    except:
                        published_dt = datetime.now()

                    conn.execute('''
                        INSERT INTO imported_news (title, description, link, source, published)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (
                        news['title'][:250],
                        news['description'][:500],
                        news['link'][:300],
                        news.get('source', 'RIA.ru')[:50],
                        published_dt
                    ))
                    imported_count += 1
                    print(f"[{i}] Импортировано: {news['title'][:50]}...")

            except Exception as e:
                print(f"Ошибка при импорте новости '{news.get('title', '')}': {e}")
                continue

        conn.commit()
        conn.close()

        print(f"Успешно импортировано {imported_count} новостей")
        return imported_count > 0

    except Exception as e:
        print(f"Критическая ошибка при импорте новостей в БД: {e}")
        import traceback
        traceback.print_exc()
        return False


# ==================== ОСНОВНЫЕ МАРШРУТЫ ====================

@app.route('/')
def index():
    if 'user_id' in session:
        username = session.get('username')
        if username == 'admin':
            return redirect('/admin')
        elif username == 'techadmin':
            return redirect('/techadmin')
        else:
            return redirect('/home')
    return redirect('/login')


@app.route('/home', methods=['GET', 'POST'])
def home():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']

    if request.method == 'POST':
        # Создание нового поста
        content = request.form.get('content', '').strip()

        if content:
            conn = get_db_connection()
            try:
                conn.execute('''
                    INSERT INTO posts (user_id, content)
                    VALUES (?, ?)
                ''', (user_id, content))
                conn.commit()
                flash('Пост опубликован!', 'success')
                print(f"Пользователь {user_id} опубликовал пост: {content[:50]}...")
            except Exception as e:
                flash(f'Ошибка при публикации поста: {str(e)[:50]}', 'error')
                print(f"Ошибка при публикации поста: {e}")
            finally:
                conn.close()
        else:
            flash('Пост не может быть пустым', 'error')

        return redirect('/home')

    # GET запрос - показываем ленту
    feed_items = []

    try:
        # Пробуем импортировать новости (только раз в 5 запросов)
        import_counter = session.get('import_counter', 0)
        import_counter += 1
        session['import_counter'] = import_counter

        if import_counter % 5 == 0:
            print(f"Попытка импорта новостей (запрос #{import_counter})...")
            import_news_to_db()
            # Сбрасываем счетчик, чтобы не импортировать слишком часто
            if import_counter > 100:
                session['import_counter'] = 0

        # Получаем ленту новостей
        feed_items = get_news_feed(user_id, limit=20)
        print(f"Получено {len(feed_items)} элементов в ленте")

    except Exception as e:
        print(f"Ошибка при подготовке ленты: {e}")
        flash('Не удалось загрузить все новости', 'info')

    # Получаем количество заявок в друзья
    friend_requests_count = 0
    conn = get_db_connection()
    try:
        result = conn.execute('''
            SELECT COUNT(*) as count FROM friendships 
            WHERE receiver_id = ? AND status = 'pending'
        ''', (user_id,)).fetchone()
        friend_requests_count = result['count'] if result else 0
    except Exception as e:
        print(f"Ошибка при получении заявок: {e}")
    finally:
        conn.close()

    return render_template('home.html',
                           username=session.get('username'),
                           friend_requests_count=friend_requests_count,
                           feed_items=feed_items)


@app.route('/import_news', methods=['POST'])
def import_news_route():
    """Ручной импорт новостей"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Требуется авторизация'}), 401

    try:
        result = import_news_to_db()
        if result:
            return jsonify({'success': True, 'message': 'Новости успешно импортированы'})
        else:
            return jsonify({'success': False, 'message': 'Не удалось импортировать новости'})
    except Exception as e:
        print(f"Ошибка при ручном импорте новостей: {e}")
        return jsonify({'success': False, 'message': str(e)[:100]})


@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()

    # Получаем основную информацию о пользователе
    user = row_to_dict(conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone())

    # Получаем профиль пользователя
    profile_data = row_to_dict(conn.execute('SELECT * FROM user_profiles WHERE user_id = ?', (user_id,)).fetchone())


# Получаем количество постов
    posts_count = conn.execute('SELECT COUNT(*) as count FROM posts WHERE user_id = ?', (user_id,)).fetchone()['count']

    # Получаем количество друзей
    friends_count = conn.execute('''
        SELECT COUNT(*) as count FROM friendships 
        WHERE (sender_id = ? OR receiver_id = ?) AND status = 'accepted'
    ''', (user_id, user_id)).fetchone()['count']

    # Получаем количество заявок в друзья
    friend_requests_count = conn.execute('''
        SELECT COUNT(*) as count FROM friendships 
        WHERE receiver_id = ? AND status = 'pending'
    ''', (user_id,)).fetchone()['count']

    # Получаем количество пользователей в черном списке
    blacklist_count = conn.execute('''
        SELECT COUNT(*) as count FROM blacklist 
        WHERE blocker_id = ?
    ''', (user_id,)).fetchone()['count']

    conn.close()

    return render_template('profile.html',
                           user=user,
                           profile=profile_data,
                           posts_count=posts_count,
                           friends_count=friends_count,
                           friend_requests_count=friend_requests_count,
                           blacklist_count=blacklist_count)


@app.route('/profile/<int:user_id>')
def view_profile(user_id):
    if 'user_id' not in session:
        return redirect('/login')

    conn = get_db_connection()
    user = row_to_dict(conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone())

    if not user:
        flash('Пользователь не найден', 'error')
        return redirect('/home')

    profile_data = row_to_dict(conn.execute('SELECT * FROM user_profiles WHERE user_id = ?', (user_id,)).fetchone())
    posts_count = conn.execute('SELECT COUNT(*) as count FROM posts WHERE user_id = ?', (user_id,)).fetchone()['count']
    friend_status = None
    if user_id != session['user_id']:
        friendship = conn.execute('''
            SELECT status FROM friendships 
            WHERE (sender_id = ? AND receiver_id = ?) 
            OR (sender_id = ? AND receiver_id = ?)
        ''', (session['user_id'], user_id, user_id, session['user_id'])).fetchone()
        friend_status = friendship['status'] if friendship else None

    conn.close()

    return render_template('view_profile.html',
                           user=user,
                           profile=profile_data,
                           posts_count=posts_count,
                           friend_status=friend_status,
                           is_own_profile=(user_id == session['user_id']))

@app.route('/profile/edit', methods=['GET', 'POST'])
def edit_profile():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']

    if request.method == 'POST':
        full_name = request.form.get('full_name', '')
        bio = request.form.get('bio', '')
        location = request.form.get('location', '')

        avatar_filename = None
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file_ext = filename.rsplit('.', 1)[1].lower()
                unique_filename = f"{user_id}_{hashlib.md5(str(datetime.now()).encode()).hexdigest()[:10]}.{file_ext}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                file.save(file_path)
                avatar_filename = unique_filename

        conn = get_db_connection()
        existing_profile = conn.execute('SELECT id FROM user_profiles WHERE user_id = ?', (user_id,)).fetchone()

        if existing_profile:
            if avatar_filename:
                conn.execute('''
                    UPDATE user_profiles 
                    SET full_name = ?, bio = ?, location = ?, avatar = ?
                    WHERE user_id = ?
                ''', (full_name, bio, location, avatar_filename, user_id))
            else:
                conn.execute('''
                    UPDATE user_profiles 
                    SET full_name = ?, bio = ?, location = ?
                    WHERE user_id = ?
                ''', (full_name, bio, location, user_id))
        else:
            avatar_to_use = avatar_filename if avatar_filename else 'default_avatar.png'
            conn.execute('''
                INSERT INTO user_profiles (user_id, full_name, bio, location, avatar)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, full_name, bio, location, avatar_to_use))

        conn.commit()
        conn.close()
        flash('Профиль успешно обновлен!', 'success')
        return redirect('/profile')

    # GET запрос - показываем форму редактирования
    conn = get_db_connection()
    profile_data = row_to_dict(conn.execute('SELECT * FROM user_profiles WHERE user_id = ?', (user_id,)).fetchone())
    conn.close()

    return render_template('edit_profile.html', profile=profile_data)


@app.route('/find_friends', methods=['GET', 'POST'])
def find_friends():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    search_results = []

    if request.method == 'POST':
        search_query = request.form.get('search_query', '').strip()
        if search_query:
            conn = get_db_connection()

            # Ищем пользователей по имени пользователя или ФИО
            rows = conn.execute('''
                SELECT u.id, u.username, up.full_name, 
                       COALESCE(up.avatar, 'default_avatar.png') as avatar 
                FROM users u
                LEFT JOIN user_profiles up ON u.id = up.user_id
                WHERE (u.username LIKE ? OR up.full_name LIKE ?) 
                AND u.id != ? AND u.is_banned = 0
                LIMIT 20
            ''', (f'%{search_query}%', f'%{search_query}%', user_id)).fetchall()

            # Преобразуем Row объекты в словари
            search_results = rows_to_dicts(rows)

            # Проверяем статус дружбы и черного списка для каждого найденного пользователя
            for user in search_results:
                # Проверяем статус дружбы
                friend_status = conn.execute('''
                    SELECT status FROM friendships 
                    WHERE (sender_id = ? AND receiver_id = ?) 
                    OR (sender_id = ? AND receiver_id = ?)
                ''', (user_id, user['id'], user['id'], user_id)).fetchone()

                user['friend_status'] = friend_status['status'] if friend_status else None

# Проверяем, находится ли пользователь в черном списке
                blacklisted = conn.execute('''
                    SELECT id FROM blacklist 
                    WHERE blocker_id = ? AND blocked_id = ?
                ''', (user_id, user['id'])).fetchone()

                user['is_blacklisted'] = blacklisted is not None

            conn.close()

    return render_template('find_friends.html', search_results=search_results)


@app.route('/add_friend/<int:friend_id>', methods=['POST'])
def add_friend(friend_id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']

    if user_id == friend_id:
        flash('Нельзя добавить себя в друзья!', 'error')
        return redirect('/find_friends')

    conn = get_db_connection()

    # Проверяем, не заблокирован ли пользователь
    is_blacklisted = conn.execute('''
        SELECT id FROM blacklist 
        WHERE blocker_id = ? AND blocked_id = ?
    ''', (user_id, friend_id)).fetchone()

    if is_blacklisted:
        flash('Вы не можете добавить в друзья пользователя из черного списка!', 'error')
        conn.close()
        return redirect('/find_friends')

    # Проверяем, не существует ли уже заявка
    existing_request = conn.execute('''
        SELECT * FROM friendships 
        WHERE (sender_id = ? AND receiver_id = ?) 
        OR (sender_id = ? AND receiver_id = ?)
    ''', (user_id, friend_id, friend_id, user_id)).fetchone()

    if existing_request:
        status = existing_request['status']
        if status == 'pending':
            if existing_request['receiver_id'] == user_id:
                # Пользователь принимает заявку
                conn.execute('''
                    UPDATE friendships SET status = 'accepted' 
                    WHERE id = ?
                ''', (existing_request['id'],))
                flash('Заявка в друзья принята!', 'success')
            else:
                flash('Заявка уже отправлена и ожидает подтверждения', 'info')
        elif status == 'accepted':
            flash('Этот пользователь уже у вас в друзьях', 'info')
        elif status == 'rejected':
            flash('Заявка была отклонена ранее', 'info')
    else:
        # Отправляем новую заявку
        conn.execute('''
            INSERT INTO friendships (sender_id, receiver_id, status)
            VALUES (?, ?, 'pending')
        ''', (user_id, friend_id))
        flash('Заявка в друзья отправлена!', 'success')

    conn.commit()
    conn.close()

    return redirect('/find_friends')


@app.route('/add_friend_to_blacklist/<int:friend_id>')
def add_friend_to_blacklist(friend_id):
    """Добавить друга в черный список из раздела друзей"""
    if 'user_id' not in session:
        return redirect('/login')

    blocker_id = session['user_id']

    if blocker_id == friend_id:
        flash('Нельзя добавить себя в черный список!', 'error')
        return redirect('/friends')

    conn = get_db_connection()

    # Получаем информацию о друге
    friend_info = conn.execute('''
        SELECT u.username, up.full_name 
        FROM users u
        LEFT JOIN user_profiles up ON u.id = up.user_id
        WHERE u.id = ?
    ''', (friend_id,)).fetchone()

    if not friend_info:
        conn.close()
        flash('Пользователь не найден', 'error')
        return redirect('/friends')

    # Проверяем, не добавлен ли уже пользователь в черный список
    existing = conn.execute('''
        SELECT id FROM blacklist 
        WHERE blocker_id = ? AND blocked_id = ?
    ''', (blocker_id, friend_id)).fetchone()

    if existing:
        flash('Пользователь уже в вашем черном списке', 'info')
    else:
        # Добавляем в черный список
        conn.execute('''
            INSERT INTO blacklist (blocker_id, blocked_id, reason)
            VALUES (?, ?, ?)
        ''', (blocker_id, friend_id, 'Добавлен из раздела друзей'))

        # Удаляем из друзей
        conn.execute('''
            DELETE FROM friendships 
            WHERE ((sender_id = ? AND receiver_id = ?) 
            OR (sender_id = ? AND receiver_id = ?)) 
            AND status = 'accepted'
        ''', (blocker_id, friend_id, friend_id, blocker_id))

        # Отменяем все заявки в друзья между этими пользователями
        conn.execute('''
            DELETE FROM friendships 
            WHERE (sender_id = ? AND receiver_id = ?) 
            OR (sender_id = ? AND receiver_id = ?)
        ''', (blocker_id, friend_id, friend_id, blocker_id))

        flash(f'{friend_info["username"]} добавлен в черный список и удален из друзей', 'success')

    conn.commit()
    conn.close()

    return redirect('/friends')


@app.route('/friends')
def friends():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()

    # Получаем список друзей
    friends_rows = conn.execute('''
        SELECT u.id, u.username, up.full_name, 
               COALESCE(up.avatar, 'default_avatar.png') as avatar 
        FROM users u
        LEFT JOIN user_profiles up ON u.id = up.user_id
        WHERE u.id IN (
            SELECT CASE 
                WHEN sender_id = ? THEN receiver_id 
                ELSE sender_id 
            END as friend_id
            FROM friendships 
            WHERE (sender_id = ? OR receiver_id = ?) AND status = 'accepted'
        )
        ORDER BY up.full_name, u.username
    ''', (user_id, user_id, user_id)).fetchall()

    # Преобразуем в словари
    friends = rows_to_dicts(friends_rows)

    # Получаем входящие заявки в друзья
    incoming_requests_rows = conn.execute('''
        SELECT u.id, u.username, up.full_name, 
               COALESCE(up.avatar, 'default_avatar.png') as avatar, 
               f.created_at, f.id as request_id
        FROM users u
        LEFT JOIN user_profiles up ON u.id = up.user_id
        JOIN friendships f ON u.id = f.sender_id
        WHERE f.receiver_id = ? AND f.status = 'pending'
        ORDER BY f.created_at DESC
    ''', (user_id,)).fetchall()

    incoming_requests = rows_to_dicts(incoming_requests_rows)

    # Получаем исходящие заявки
    outgoing_requests_rows = conn.execute('''
        SELECT u.id, u.username, up.full_name, 
               COALESCE(up.avatar, 'default_avatar.png') as avatar, 
               f.created_at, f.id as request_id
        FROM users u
        LEFT JOIN user_profiles up ON u.id = up.user_id
        JOIN friendships f ON u.id = f.receiver_id
        WHERE f.sender_id = ? AND f.status = 'pending'
        ORDER BY f.created_at DESC
    ''', (user_id,)).fetchall()

    outgoing_requests = rows_to_dicts(outgoing_requests_rows)

    conn.close()

    return render_template('friends.html',
                           friends=friends,
                           incoming_requests=incoming_requests,
                           outgoing_requests=outgoing_requests)


@app.route('/friend_action/<int:request_id>/<action>')
def friend_action(request_id, action):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()

    # Получаем информацию о заявке
    friend_request = conn.execute('''
        SELECT * FROM friendships 
        WHERE id = ?
    ''', (request_id,)).fetchone()

    if friend_request:
        friend_request_dict = dict(friend_request)
        # Проверяем, имеет ли пользователь право выполнять это действие
        if action == 'accept' and friend_request_dict['receiver_id'] == user_id:
            conn.execute('''
                UPDATE friendships SET status = 'accepted' 
                WHERE id = ?
            ''', (request_id,))
            flash('Заявка в друзья принята!', 'success')
        elif action == 'reject' and friend_request_dict['receiver_id'] == user_id:
            conn.execute('''
                UPDATE friendships SET status = 'rejected' 
                WHERE id = ?
            ''', (request_id,))
            flash('Заявка в друзья отклонена', 'info')
        elif action == 'cancel' and friend_request_dict['sender_id'] == user_id:
            # Пользователь отменяет свою исходящую заявку
            conn.execute('''
                DELETE FROM friendships WHERE id = ?
            ''', (request_id,))
            flash('Заявка отменена', 'info')
        else:
            flash('У вас нет прав для выполнения этого действия', 'error')

    conn.commit()
    conn.close()

    return redirect('/friends')


@app.route('/remove_friend/<int:friend_id>')
def remove_friend(friend_id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()

    # Удаляем запись о дружбе
    conn.execute('''
        DELETE FROM friendships 
        WHERE ((sender_id = ? AND receiver_id = ?) 
        OR (sender_id = ? AND receiver_id = ?)) 
        AND status = 'accepted'
    ''', (user_id, friend_id, friend_id, user_id))

    conn.commit()
    conn.close()

    flash('Пользователь удален из друзей', 'info')
    return redirect('/friends')


# Черный список
@app.route('/blacklist')
def blacklist():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()

    # Получаем список пользователей в черном списке
    blacklist_rows = conn.execute('''
        SELECT u.id, u.username, up.full_name, 
               COALESCE(up.avatar, 'default_avatar.png') as avatar,
               b.reason, b.created_at
        FROM blacklist b
        JOIN users u ON b.blocked_id = u.id
        LEFT JOIN user_profiles up ON u.id = up.user_id
        WHERE b.blocker_id = ?
        ORDER BY b.created_at DESC
    ''', (user_id,)).fetchall()

    blacklisted_users = rows_to_dicts(blacklist_rows)

    conn.close()

    return render_template('blacklist.html', blacklisted_users=blacklisted_users)


@app.route('/add_to_blacklist/<int:user_id>', methods=['GET', 'POST'])
def add_to_blacklist(user_id):
    if 'user_id' not in session:
        return redirect('/login')

    blocker_id = session['user_id']

    if blocker_id == user_id:
        flash('Нельзя добавить себя в черный список!', 'error')
        return redirect(request.referrer or '/find_friends')

    if request.method == 'POST':
        reason = request.form.get('reason', '')

        conn = get_db_connection()

        # Проверяем, не добавлен ли уже пользователь в черный список
        existing = conn.execute('''
            SELECT id FROM blacklist 
            WHERE blocker_id = ? AND blocked_id = ?
        ''', (blocker_id, user_id)).fetchone()

        if existing:
            flash('Пользователь уже в вашем черном списке', 'info')
        else:
            # Добавляем в черный список
            conn.execute('''
                INSERT INTO blacklist (blocker_id, blocked_id, reason)
                VALUES (?, ?, ?)
            ''', (blocker_id, user_id, reason))

            # Удаляем из друзей, если были друзьями
            conn.execute('''
                DELETE FROM friendships 
                WHERE ((sender_id = ? AND receiver_id = ?) 
                OR (sender_id = ? AND receiver_id = ?)) 
                AND status = 'accepted'
            ''', (blocker_id, user_id, user_id, blocker_id))

            # Отменяем все заявки в друзья между этими пользователями
            conn.execute('''
                DELETE FROM friendships 
                WHERE (sender_id = ? AND receiver_id = ?) 
                OR (sender_id = ? AND receiver_id = ?)
            ''', (blocker_id, user_id, user_id, blocker_id))

            flash('Пользователь добавлен в черный список', 'success')

        conn.commit()
        conn.close()

        return redirect('/blacklist')

    # GET запрос - показываем форму
    conn = get_db_connection()
    user_info = conn.execute('''
        SELECT u.username, up.full_name 
        FROM users u
        LEFT JOIN user_profiles up ON u.id = up.user_id
        WHERE u.id = ?
    ''', (user_id,)).fetchone()

    conn.close()

    if user_info:
        return render_template('add_to_blacklist.html',
                               user_id=user_id,
                               username=user_info['username'],
                               full_name=user_info['full_name'])
    else:
        flash('Пользователь не найден', 'error')
        return redirect('/find_friends')


@app.route('/remove_from_blacklist/<int:blocked_id>')
def remove_from_blacklist(blocked_id):
    if 'user_id' not in session:
        return redirect('/login')

    blocker_id = session['user_id']

    conn = get_db_connection()

    # Удаляем из черного списка
    conn.execute('''
        DELETE FROM blacklist 
        WHERE blocker_id = ? AND blocked_id = ?
    ''', (blocker_id, blocked_id))

    conn.commit()
    conn.close()

    flash('Пользователь удален из черного списка', 'info')
    return redirect('/blacklist')


# Жалобы на пользователей
@app.route('/report_friend/<int:friend_id>', methods=['GET', 'POST'])
def report_friend(friend_id):
    """Отправить жалобу на друга из раздела друзей"""
    if 'user_id' not in session:
        return redirect('/login')

    reporter_id = session['user_id']

    if reporter_id == friend_id:
        flash('Нельзя отправить жалобу на себя!', 'error')
        return redirect('/friends')

    if request.method == 'POST':
        reason = request.form.get('reason', '').strip()
        violation_type = request.form.get('violation_type', '')

        if not reason or len(reason) < 10:
            flash('Пожалуйста, опишите причину жалобы подробнее (минимум 10 символов)', 'error')
            return redirect(f'/report_friend/{friend_id}')

        conn = get_db_connection()

# Отправляем жалобу
        full_reason = f"Тип нарушения: {violation_type}\n\n{reason}"
        conn.execute('''
            INSERT INTO reports (reporter_id, reported_id, reason, status)
            VALUES (?, ?, ?, 'pending')
        ''', (reporter_id, friend_id, full_reason))

        conn.commit()
        conn.close()

        flash('Жалоба отправлена администратору. Спасибо за ваше сообщение!', 'success')
        return redirect('/friends')

    # GET запрос - показываем форму
    conn = get_db_connection()
    friend_info = conn.execute('''
        SELECT u.username, up.full_name 
        FROM users u
        LEFT JOIN user_profiles up ON u.id = up.user_id
        WHERE u.id = ?
    ''', (friend_id,)).fetchone()

    conn.close()

    if friend_info:
        return render_template('report_user.html',
                               user_id=friend_id,
                               username=friend_info['username'],
                               full_name=friend_info['full_name'])
    else:
        flash('Пользователь не найден', 'error')
        return redirect('/friends')


@app.route('/report_user/<int:user_id>', methods=['GET', 'POST'])
def report_user(user_id):
    if 'user_id' not in session:
        return redirect('/login')

    reporter_id = session['user_id']

    if reporter_id == user_id:
        flash('Нельзя отправить жалобу на себя!', 'error')
        return redirect(request.referrer or '/friends')

    if request.method == 'POST':
        reason = request.form.get('reason', '').strip()
        violation_type = request.form.get('violation_type', 'other')

        if not reason or len(reason) < 10:
            flash('Пожалуйста, опишите причину жалобы подробнее (минимум 10 символов)', 'error')
            return redirect(f'/report_user/{user_id}')

        conn = get_db_connection()

        try:
            # Отправляем жалобу
            full_reason = f"Тип нарушения: {violation_type}\n\n{reason}"
            conn.execute('''
                INSERT INTO reports (reporter_id, reported_id, reason, status)
                VALUES (?, ?, ?, 'pending')
            ''', (reporter_id, user_id, full_reason))

            conn.commit()
            flash('Жалоба отправлена администратору. Спасибо за ваше сообщение!', 'success')
        except Exception as e:
            print(f"Ошибка при сохранении жалобы: {e}")
            flash('Ошибка при отправке жалобы', 'error')
        finally:
            conn.close()

        return redirect('/friends')

    # GET запрос - показываем форму
    conn = get_db_connection()
    user_info = conn.execute('''
        SELECT u.username, up.full_name 
        FROM users u
        LEFT JOIN user_profiles up ON u.id = up.user_id
        WHERE u.id = ?
    ''', (user_id,)).fetchone()
    conn.close()

    if user_info:
        return render_template('report_user.html',
                               user_id=user_id,
                               username=user_info['username'],
                               full_name=user_info['full_name'])
    else:
        flash('Пользователь не найден', 'error')
        return redirect('/friends')


# ==================== ГРУППЫ ====================

@app.route('/groups')
def groups_list():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    search_query = request.args.get('search', '')
    tab = request.args.get('tab', 'all')

    conn = get_db_connection()

    # Базовый запрос для ВСЕХ групп
    query = '''
        SELECT g.*, 
               COUNT(DISTINCT gm.user_id) as members_count,
               COUNT(DISTINCT gp.id) as posts_count,
               EXISTS(SELECT 1 FROM group_members WHERE group_id = g.id AND user_id = ?) as is_member,
               (SELECT role FROM group_members WHERE group_id = g.id AND user_id = ? LIMIT 1) as role,
               EXISTS(SELECT 1 FROM group_requests WHERE group_id = g.id AND user_id = ? AND status = 'pending') as has_pending_request
        FROM groups g
        LEFT JOIN group_members gm ON g.id = gm.group_id
        LEFT JOIN group_posts gp ON g.id = gp.group_id
    '''
    params = [user_id, user_id, user_id]

    if tab == 'my':
        query += ' WHERE g.id IN (SELECT group_id FROM group_members WHERE user_id = ?)'
        params.append(user_id)
    # Для вкладки "Все группы" показываем ВСЕ группы (и публичные, и приватные)

    if search_query:
        if 'WHERE' in query:
            query += ' AND'
        else:
            query += ' WHERE'
        query += ' (g.name LIKE ? OR g.description LIKE ?)'
        params.extend([f'%{search_query}%', f'%{search_query}%'])

    query += ' GROUP BY g.id ORDER BY members_count DESC'

    groups = rows_to_dicts(conn.execute(query, params).fetchall())

    # Получаем creator_id для каждой группы
    for group in groups:
        creator = conn.execute('SELECT creator_id FROM groups WHERE id = ?', (group['id'],)).fetchone()
        group['creator_id'] = creator['creator_id'] if creator else None

    conn.close()

    return render_template('groups.html',
                           groups=groups,
                           search_query=search_query,
                           current_tab=tab,
                           session_user_id=user_id)


@app.route('/create_group', methods=['POST'])
def create_group():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    is_public = request.form.get('is_public') == 'on'

    if not name:
        flash('Название паблика обязательно', 'error')
        return redirect('/groups')

    avatar_filename = None
    if 'avatar' in request.files:
        file = request.files['avatar']
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_ext = filename.rsplit('.', 1)[1].lower()
            unique_filename = f"group_{hashlib.md5(str(datetime.now()).encode()).hexdigest()[:10]}.{file_ext}"
            file_path = os.path.join(app.config['GROUP_UPLOAD_FOLDER'], unique_filename)
            file.save(file_path)
            avatar_filename = unique_filename

    conn = get_db_connection()
    current_datetime = get_current_datetime()

    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO groups (name, description, avatar, creator_id, is_public, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (name, description, avatar_filename if avatar_filename else 'default_group.png',
              user_id, 1 if is_public else 0, current_datetime))

        group_id = cursor.lastrowid

        cursor.execute('''
            INSERT INTO group_members (group_id, user_id, role)
            VALUES (?, ?, 'admin')
        ''', (group_id, user_id))

        conn.commit()
        flash('Паблик успешно создан!', 'success')
        return redirect(f'/group/{group_id}')

    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при создании паблика: {str(e)}', 'error')
        return redirect('/groups')
    finally:
        conn.close()


@app.route('/join_group/<int:group_id>', methods=['POST'])
def join_group(group_id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()

    try:
        existing_member = conn.execute('''
            SELECT id FROM group_members WHERE group_id = ? AND user_id = ?
        ''', (group_id, user_id)).fetchone()

        if existing_member:
            flash('Вы уже в этой группе', 'info')
            return redirect(request.referrer or f'/group/{group_id}')

        group = conn.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone()
        if not group:
            flash('Группа не найдена', 'error')
            return redirect('/groups')

        if group['is_public']:
            conn.execute('''
                INSERT INTO group_members (group_id, user_id, role)
                VALUES (?, ?, 'member')
            ''', (group_id, user_id))
            flash(f'Вы присоединились к группе "{group["name"]}"!', 'success')
        else:
            existing_request = conn.execute('''
                SELECT id FROM group_requests 
                WHERE group_id = ? AND user_id = ? AND status = 'pending'
            ''', (group_id, user_id)).fetchone()

            if existing_request:
                flash('Вы уже отправили заявку на вступление', 'info')
            else:
                conn.execute('''
                    INSERT INTO group_requests (group_id, user_id, status, created_at)
                    VALUES (?, ?, 'pending', ?)
                ''', (group_id, user_id, get_current_datetime()))
                flash('Заявка на вступление отправлена! Администратор рассмотрит её в ближайшее время.', 'success')

        conn.commit()

    except Exception as e:
        conn.rollback()
        flash(f'Ошибка: {str(e)}', 'error')
    finally:
        conn.close()

    return redirect(request.referrer or f'/group/{group_id}')


@app.route('/leave_group/<int:group_id>', methods=['POST'])
def leave_group(group_id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()

    try:
        group = conn.execute('SELECT creator_id, name FROM groups WHERE id = ?', (group_id,)).fetchone()

        if group and group['creator_id'] == user_id:
            conn.execute('DELETE FROM group_posts WHERE group_id = ?', (group_id,))
            conn.execute(
                'DELETE FROM group_post_likes WHERE post_id IN (SELECT id FROM group_posts WHERE group_id = ?)',
                (group_id,))
            conn.execute('DELETE FROM group_members WHERE group_id = ?', (group_id,))
            conn.execute('DELETE FROM group_requests WHERE group_id = ?', (group_id,))
            conn.execute('DELETE FROM groups WHERE id = ?', (group_id,))

            group_avatar = conn.execute('SELECT avatar FROM groups WHERE id = ?', (group_id,)).fetchone()
            if group_avatar and group_avatar['avatar'] and group_avatar['avatar'] != 'default_group.png':
                try:
                    os.remove(os.path.join(app.config['GROUP_UPLOAD_FOLDER'], group_avatar['avatar']))
                except:
                    pass

            flash(f'Группа "{group["name"]}" была удалена, так как вы покинули её как создатель.', 'info')

        else:
            conn.execute('DELETE FROM group_members WHERE group_id = ? AND user_id = ?', (group_id, user_id))
            flash(f'Вы отписались от группы "{group["name"]}"', 'info')

        conn.commit()

    except Exception as e:
        conn.rollback()
        flash(f'Ошибка: {str(e)}', 'error')

    finally:
        conn.close()

    return redirect('/groups')


@app.route('/group/<int:group_id>')
def group_detail(group_id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()

# Получаем информацию о группе
    group = row_to_dict(conn.execute('''
        SELECT g.*, 
               COUNT(DISTINCT gm.user_id) as members_count,
               COUNT(DISTINCT gp.id) as posts_count,
               u.username as creator_username
        FROM groups g
        LEFT JOIN group_members gm ON g.id = gm.group_id
        LEFT JOIN group_posts gp ON g.id = gp.group_id
        LEFT JOIN users u ON g.creator_id = u.id
        WHERE g.id = ?
        GROUP BY g.id
    ''', (group_id,)).fetchone())

    if not group:
        flash('Паблик не найден', 'error')
        return redirect('/groups')

    # Проверяем, является ли пользователь участником
    membership = conn.execute('''
        SELECT role FROM group_members WHERE group_id = ? AND user_id = ?
    ''', (group_id, user_id)).fetchone()

    is_member = membership is not None
    role = membership['role'] if membership else None

    # Проверяем, может ли пользователь создавать посты
    can_post = False
    if is_member:
        can_post = check_post_permission(group_id, user_id, conn)

    # Проверяем, показывать ли вкладку "Заявки"
    show_requests_tab = False
    pending_requests = []
    pending_requests_count = 0

    if is_member and role in ['admin', 'moderator'] and not group['is_public']:
        # Проверяем права на просмотр заявок
        if group.get('request_permissions') == 'admins':
            show_requests_tab = role == 'admin'
        else:  # moderators или по умолчанию
            show_requests_tab = role in ['admin', 'moderator']

        if show_requests_tab:
            # Получаем заявки на вступление
            pending_requests = rows_to_dicts(conn.execute('''
                SELECT gr.id as request_id, gr.user_id, gr.created_at,
                       u.username, up.full_name, COALESCE(up.avatar, 'default_avatar.png') as avatar
                FROM group_requests gr
                JOIN users u ON gr.user_id = u.id
                LEFT JOIN user_profiles up ON u.id = up.user_id
                WHERE gr.group_id = ? AND gr.status = 'pending'
                ORDER BY gr.created_at
            ''', (group_id,)).fetchall())

            pending_requests_count = len(pending_requests)

    # Получаем посты группы
    posts_data = []
    if is_member or group['is_public']:
        posts = rows_to_dicts(conn.execute('''
            SELECT gp.*,
                   u.username as author_username,
                   up.full_name as author_name,
                   COALESCE(up.avatar, 'default_avatar.png') as author_avatar,
                   (SELECT COUNT(*) FROM group_post_likes WHERE post_id = gp.id) as likes_count
            FROM group_posts gp
            JOIN users u ON gp.author_id = u.id
            LEFT JOIN user_profiles up ON u.id = up.user_id
            WHERE gp.group_id = ?
            ORDER BY gp.created_at DESC
            LIMIT 50
        ''', (group_id,)).fetchall())

        # Добавляем роль автора поста для каждого поста
        for post in posts:
            # Получаем роль автора поста в этой группе
            author_role = conn.execute('''
                SELECT role FROM group_members 
                WHERE group_id = ? AND user_id = ?
            ''', (group_id, post['author_id'])).fetchone()

            # Если автор не состоит в группе (хотя это маловероятно), считаем его участником
            post['author_role'] = author_role['role'] if author_role else 'member'

            # Получаем медиафайлы для поста
            post['media_files'] = get_post_media(post['id'], is_group_post=True)

            posts_data.append(post)

    # Получаем участников группы
    members = rows_to_dicts(conn.execute('''
        SELECT u.id, u.username, up.full_name, 
               COALESCE(up.avatar, 'default_avatar.png') as avatar,


        gm.role, gm.joined_at
        FROM group_members gm
        JOIN users u ON gm.user_id = u.id
        LEFT JOIN user_profiles up ON u.id = up.user_id
        WHERE gm.group_id = ?
        ORDER BY 
            CASE gm.role 
                WHEN 'admin' THEN 1
                WHEN 'moderator' THEN 2
                ELSE 3
            END,
            u.username
    ''', (group_id,)).fetchall())

    # Получаем создателя
    creator = row_to_dict(conn.execute('''
        SELECT u.id, u.username, up.full_name, 
               COALESCE(up.avatar, 'default_avatar.png') as avatar
        FROM users u
        LEFT JOIN user_profiles up ON u.id = up.user_id
        WHERE u.id = ?
    ''', (group['creator_id'],)).fetchone())

    # Проверяем, есть ли у пользователя ожидающая заявка (для приватных групп)
    has_pending_request = False
    if not is_member and not group['is_public']:
        pending_request = conn.execute('''
            SELECT id FROM group_requests 
            WHERE group_id = ? AND user_id = ? AND status = 'pending'
        ''', (group_id, user_id)).fetchone()
        has_pending_request = pending_request is not None

    conn.close()

    return render_template('group_detail.html',
                           group=group,
                           posts=posts_data,
                           members=members,
                           creator=creator,
                           is_member=is_member,
                           role=role,
                           can_post=can_post,
                           has_pending_request=has_pending_request,
                           session_user_id=user_id,
                           show_requests_tab=show_requests_tab,
                           pending_requests=pending_requests,
                           pending_requests_count=pending_requests_count)

@app.route('/group/<int:group_id>/create_post', methods=['POST'])
def create_group_post(group_id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    content = request.form.get('content', '').strip()
    conn = get_db_connection()

    print(f"=== НАЧАЛО СОЗДАНИЯ ПОСТА ===")
    print(f"user_id: {user_id}")
    print(f"content: '{content}'")

    try:
        # Проверяем права на публикацию
        if not check_post_permission(group_id, user_id, conn):
            flash('У вас нет прав для создания постов в этой группе', 'error')
            return redirect(f'/group/{group_id}')

        # Проверяем, есть ли файлы
        has_valid_files = False
        files = []
        if 'media_files' in request.files:
            files = request.files.getlist('media_files')
            print(f"Получено файлов: {len(files)}")
            for file in files:
                if file and file.filename and file.filename.strip() != '':
                    has_valid_files = True

        # Проверяем, есть ли хоть что-то для публикации
        if not content and not has_valid_files:
            flash('Пост не может быть пустым. Добавьте текст или файлы.', 'error')
            return redirect(f'/group/{group_id}')

        current_datetime = get_current_datetime()

        # Создаем пост
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO group_posts (group_id, author_id, content, created_at)
            VALUES (?, ?, ?, ?)
        ''', (group_id, user_id, content, current_datetime))

        post_id = cursor.lastrowid
        print(f"Создан пост ID: {post_id}")

        # Обработка загруженных файлов
        uploaded_files = 0
        if files:
            for file in files:
                if file and file.filename and file.filename.strip() != '':
                    filename = secure_filename(file.filename)

                    if '.' not in filename:
                        continue

                    file_ext = filename.rsplit('.', 1)[1].lower()

                    # Определяем тип файла
                    if file_ext in ALLOWED_IMAGE_EXTENSIONS:
                        file_type = 'image'
                    elif file_ext in ALLOWED_VIDEO_EXTENSIONS:
                        file_type = 'video'
                    else:
                        continue

                    # Генерируем уникальное имя файла
                    import time
                    unique_filename = f"{post_id}_{int(time.time())}_{hashlib.md5(filename.encode()).hexdigest()[:8]}.{file_ext}"
                    file_path = os.path.join(app.config['POST_MEDIA_FOLDER'], unique_filename)

                    try:
                        # Сохраняем файл
                        file.save(file_path)

                        # ВАЖНО: Используем group_post_id для групповых постов
                        cursor.execute('''
                            INSERT INTO post_media (group_post_id, filename, file_type)
                            VALUES (?, ?, ?)
                        ''', (post_id, unique_filename, file_type))

                        uploaded_files += 1

                    except Exception as file_error:
                        print(f"Ошибка при сохранении файла: {str(file_error)}")
                        continue

        conn.commit()

        if uploaded_files > 0:
            flash(f'Пост опубликован в группе! Загружено {uploaded_files} файл(ов)', 'success')
        else:
            flash('Пост опубликован в группе!', 'success')

    except Exception as e:
        conn.rollback()
        print(f"Ошибка: {str(e)}")
        flash(f'Ошибка при создании поста: {str(e)}', 'error')
    finally:
        conn.close()

    return redirect(f'/group/{group_id}')


@app.route('/group/<int:group_id>/manage')
def manage_group(group_id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']

    conn = get_db_connection()


    membership = conn.execute(''' SELECT role FROM group_members WHERE group_id = ? AND user_id = ? ''', (group_id, user_id)).fetchone()

    if not membership or membership['role'] != 'admin':
        flash('У вас нет прав для управления этой группой', 'error')
        return redirect(f'/group/{group_id}')

    group = row_to_dict(conn.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone())

    members = rows_to_dicts(conn.execute('''
        SELECT u.id, u.username, up.full_name, 
               COALESCE(up.avatar, 'default_avatar.png') as avatar,
               gm.role, gm.joined_at
        FROM group_members gm
        JOIN users u ON gm.user_id = u.id
        LEFT JOIN user_profiles up ON u.id = up.user_id
        WHERE gm.group_id = ?
        ORDER BY 
            CASE gm.role 
                WHEN 'admin' THEN 1
                WHEN 'moderator' THEN 2
                ELSE 3
            END,
            u.username
    ''', (group_id,)).fetchall())

    conn.close()

    return render_template('manage_group.html', group=group, members=members)


@app.route('/group/<int:group_id>/settings')
def group_settings(group_id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()

    # Проверяем права (только админы)
    membership = conn.execute('''
        SELECT role FROM group_members WHERE group_id = ? AND user_id = ?
    ''', (group_id, user_id)).fetchone()

    if not membership or membership['role'] != 'admin':
        flash('Только администраторы могут изменять настройки группы', 'error')
        return redirect(f'/group/{group_id}')

    # Получаем информацию о группе
    group = row_to_dict(conn.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone())

    # Получаем список всех участников группы
    members = rows_to_dicts(conn.execute('''
        SELECT u.id, u.username, up.full_name, 
               COALESCE(up.avatar, 'default_avatar.png') as avatar,
               gm.role, gm.joined_at
        FROM group_members gm
        JOIN users u ON gm.user_id = u.id
        LEFT JOIN user_profiles up ON u.id = up.user_id
        WHERE gm.group_id = ?
        ORDER BY 
            CASE gm.role 
                WHEN 'admin' THEN 1
                WHEN 'moderator' THEN 2
                ELSE 3
            END,
            u.username
    ''', (group_id,)).fetchall())

    conn.close()
    return render_template('group_settings.html',
                           group=group,
                           members=members)


@app.route('/group/<int:group_id>/settings', methods=['POST'])
def update_group_settings(group_id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()

    # Проверяем права
    membership = conn.execute('''
        SELECT role FROM group_members WHERE group_id = ? AND user_id = ?
    ''', (group_id, user_id)).fetchone()

    if not membership or membership['role'] != 'admin':
        flash('Только администраторы могут изменять настройки группы', 'error')
        return redirect(f'/group/{group_id}')

    # Получаем данные из формы
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    is_public = request.form.get('is_public') == '1'
    post_permissions = request.form.get('post_permissions', 'all')
    request_permissions = request.form.get('request_permissions', 'moderators')

    if not name:
        flash('Название группы обязательно', 'error')
        return redirect(f'/group/{group_id}/settings')

    try:
        # Обновляем основные данные
        conn.execute('''
            UPDATE groups 
            SET name = ?, description = ?, is_public = ?, 
                post_permissions = ?, request_permissions = ?
            WHERE id = ?
        ''', (name, description, 1 if is_public else 0,
              post_permissions, request_permissions, group_id))

# Обработка аватарки
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename and allowed_file(file.filename):
                # Удаляем старый аватар если нужно
                old_avatar = conn.execute('SELECT avatar FROM groups WHERE id = ?', (group_id,)).fetchone()['avatar']

                filename = secure_filename(file.filename)
                file_ext = filename.rsplit('.', 1)[1].lower()
                unique_filename = f"group_{group_id}_{hashlib.md5(str(datetime.now()).encode()).hexdigest()[:8]}.{file_ext}"
                file_path = os.path.join(app.config['GROUP_UPLOAD_FOLDER'], unique_filename)
                file.save(file_path)

                # Обновляем в БД
                conn.execute('UPDATE groups SET avatar = ? WHERE id = ?', (unique_filename, group_id))

                # Удаляем старый файл (кроме дефолтного)
                if old_avatar and old_avatar != 'default_group.png':
                    try:
                        os.remove(os.path.join(app.config['GROUP_UPLOAD_FOLDER'], old_avatar))
                    except:
                        pass

        # Удаление аватарки
        if request.form.get('remove_avatar'):
            old_avatar = conn.execute('SELECT avatar FROM groups WHERE id = ?', (group_id,)).fetchone()['avatar']
            if old_avatar and old_avatar != 'default_group.png':
                try:
                    os.remove(os.path.join(app.config['GROUP_UPLOAD_FOLDER'], old_avatar))
                except:
                    pass
            conn.execute('UPDATE groups SET avatar = "default_group.png" WHERE id = ?', (group_id,))

        conn.commit()
        flash('Настройки группы обновлены!', 'success')

    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при обновлении настроек: {str(e)}', 'error')
        return redirect(f'/group/{group_id}/settings')
    finally:
        conn.close()

    return redirect(f'/group/{group_id}')


@app.route('/group/<int:group_id>/request/<int:request_id>/<action>')
def handle_group_request(group_id, request_id, action):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authorized'})

    user_id = session['user_id']
    conn = get_db_connection()

    # Получаем настройки группы
    group = conn.execute('SELECT request_permissions FROM groups WHERE id = ?', (group_id,)).fetchone()

    if not group:
        return jsonify({'success': False, 'error': 'Группа не найдена'})

    # Проверяем права в зависимости от настроек
    membership = conn.execute('''
        SELECT role FROM group_members WHERE group_id = ? AND user_id = ?
    ''', (group_id, user_id)).fetchone()

    if not membership:
        return jsonify({'success': False, 'error': 'Вы не состоите в этой группе'})

    if group['request_permissions'] == 'admins':
        # Только админы могут обрабатывать заявки
        if membership['role'] != 'admin':
            return jsonify({'success': False, 'error': 'Только администраторы могут обрабатывать заявки'})
    else:
        # Админы и модераторы могут обрабатывать заявки
        if membership['role'] not in ['admin', 'moderator']:
            return jsonify({'success': False, 'error': 'Только администраторы и модераторы могут обрабатывать заявки'})

    try:
        if action == 'approve':
            # Получаем заявку
            request_data = conn.execute('SELECT * FROM group_requests WHERE id = ?', (request_id,)).fetchone()
            if request_data:
                # Добавляем пользователя в группу
                conn.execute('''
                    INSERT INTO group_members (group_id, user_id, role)
                    VALUES (?, ?, 'member')
                ''', (group_id, request_data['user_id']))

                # Удаляем заявку
                conn.execute('DELETE FROM group_requests WHERE id = ?', (request_id,))

                conn.commit()
                return jsonify({'success': True})


        elif action == 'reject':
            conn.execute('DELETE FROM group_requests WHERE id = ?', (request_id,))
            conn.commit()
            return jsonify({'success': True})

    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()


@app.route('/group/<int:group_id>/change_role/<int:user_id>', methods=['POST'])
def change_member_role(group_id, user_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authorized'})

    current_user_id = session['user_id']
    data = request.get_json()
    new_role = data.get('role')

    if not new_role or new_role not in ['admin', 'moderator', 'member']:
        return jsonify({'success': False, 'error': 'Invalid role'})

    conn = get_db_connection()

    try:
        current_user_role = conn.execute('''
            SELECT role FROM group_members WHERE group_id = ? AND user_id = ?
        ''', (group_id, current_user_id)).fetchone()

        if not current_user_role or current_user_role['role'] != 'admin':
            return jsonify({'success': False, 'error': 'Только администраторы могут изменять роли'})

        group = conn.execute('SELECT creator_id FROM groups WHERE id = ?', (group_id,)).fetchone()
        if group['creator_id'] == user_id:
            return jsonify({'success': False, 'error': 'Нельзя изменить роль создателя группы'})

        conn.execute('''
            UPDATE group_members 
            SET role = ?
            WHERE group_id = ? AND user_id = ?
        ''', (new_role, group_id, user_id))

        conn.commit()
        return jsonify({'success': True})

    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()


@app.route('/group/<int:group_id>/transfer_admin/<int:new_admin_id>', methods=['POST'])
def transfer_admin_rights(group_id, new_admin_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authorized'})

    current_user_id = session['user_id']

    conn = get_db_connection()

    try:
        current_user_role = conn.execute('''
            SELECT role FROM group_members WHERE group_id = ? AND user_id = ?
        ''', (group_id, current_user_id)).fetchone()

        if not current_user_role or current_user_role['role'] != 'admin':
            return jsonify({'success': False, 'error': 'Только администраторы могут передавать права'})

        new_admin = conn.execute('''
            SELECT id FROM group_members WHERE group_id = ? AND user_id = ?
        ''', (group_id, new_admin_id)).fetchone()

        if not new_admin:
            return jsonify({'success': False, 'error': 'Пользователь не найден в группе'})

        group = conn.execute('SELECT creator_id FROM groups WHERE id = ?', (group_id,)).fetchone()
        if group['creator_id'] == new_admin_id:
            return jsonify({'success': False, 'error': 'Этот пользователь уже является создателем группы'})

        conn.execute('''
            UPDATE group_members 
            SET role = 'member'
            WHERE group_id = ? AND user_id = ?
        ''', (group_id, current_user_id))

        conn.execute('''
            UPDATE group_members 
            SET role = 'admin'
            WHERE group_id = ? AND user_id = ?
        ''', (group_id, new_admin_id))

        conn.commit()
        return jsonify({'success': True})

    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()


@app.route('/group/<int:group_id>/remove_member/<int:user_id>', methods=['POST'])
def remove_group_member(group_id, user_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authorized'})

    current_user_id = session['user_id']

    conn = get_db_connection()

    try:
        current_user_role = conn.execute('''
            SELECT role FROM group_members WHERE group_id = ? AND user_id = ?
        ''', (group_id, current_user_id)).fetchone()

        if not current_user_role or current_user_role['role'] not in ['admin', 'moderator']:
            return jsonify({'success': False, 'error': 'Только администраторы и модераторы могут удалять участников'})

        group = conn.execute('SELECT creator_id FROM groups WHERE id = ?', (group_id,)).fetchone()
        if group['creator_id'] == user_id:
            return jsonify({'success': False, 'error': 'Нельзя удалить создателя группы'})

        target_user_role = conn.execute('''
            SELECT role FROM group_members WHERE group_id = ? AND user_id = ?
        ''', (group_id, user_id)).fetchone()

        if not target_user_role:
            return jsonify({'success': False, 'error': 'Пользователь не найден в группе'})

        if current_user_role['role'] == 'moderator' and target_user_role['role'] in ['admin', 'moderator']:
            return jsonify({'success': False, 'error': 'Модераторы могут удалять только обычных участников'})

        conn.execute('DELETE FROM group_members WHERE group_id = ? AND user_id = ?', (group_id, user_id))

        conn.commit()
        return jsonify({'success': True})

    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/group_post/edit/<int:post_id>', methods=['POST'])
def edit_group_post(post_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authorized'})

    user_id = session['user_id']
    data = request.get_json()
    new_content = data.get('content', '').strip()

    if not new_content:
        return jsonify({'success': False, 'error': 'Пост не может быть пустым'})

    conn = get_db_connection()

    try:
        post = conn.execute('''
            SELECT gp.*, g.creator_id, gp.author_id as post_author_id
            FROM group_posts gp
            JOIN groups g ON gp.group_id = g.id
            WHERE gp.id = ?
        ''', (post_id,)).fetchone()

        if not post:
            return jsonify({'success': False, 'error': 'Пост не найден'})

        user_role = conn.execute('''
            SELECT role FROM group_members 
            WHERE group_id = ? AND user_id = ?
        ''', (post['group_id'], user_id)).fetchone()

        author_role = conn.execute('''
            SELECT role FROM group_members 
            WHERE group_id = ? AND user_id = ?
        ''', (post['group_id'], post['post_author_id'])).fetchone()

        can_edit = False

        if post['post_author_id'] == user_id:
            can_edit = True
        elif user_role and user_role['role'] == 'admin':
            can_edit = True
        elif user_role and user_role['role'] == 'moderator':
            if author_role and author_role['role'] == 'member':
                can_edit = True

        if not can_edit:
            return jsonify({'success': False, 'error': 'У вас нет прав для редактирования этого поста'})

        conn.execute('UPDATE group_posts SET content = ? WHERE id = ?', (new_content, post_id))

        conn.commit()
        return jsonify({'success': True})

    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()


@app.route('/group_post/delete/<int:post_id>', methods=['POST'])
def delete_group_post(post_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authorized'})

    user_id = session['user_id']

    conn = get_db_connection()

    try:
        post = conn.execute('''
            SELECT gp.*, g.creator_id, gp.author_id as post_author_id
            FROM group_posts gp
            JOIN groups g ON gp.group_id = g.id
            WHERE gp.id = ?
        ''', (post_id,)).fetchone()

        if not post:
            return jsonify({'success': False, 'error': 'Post not found'})

        user_role = conn.execute('''
            SELECT role FROM group_members 
            WHERE group_id = ? AND user_id = ?
        ''', (post['group_id'], user_id)).fetchone()

        author_role = conn.execute('''
            SELECT role FROM group_members 
            WHERE group_id = ? AND user_id = ?
        ''', (post['group_id'], post['post_author_id'])).fetchone()

        can_delete = False

        if post['post_author_id'] == user_id:
            can_delete = True
        elif user_role and user_role['role'] == 'admin':
            can_delete = True
        elif user_role and user_role['role'] == 'moderator':
            if author_role and author_role['role'] == 'member':
                can_delete = True

        if not can_delete:
            return jsonify({'success': False, 'error': 'Not authorized to delete this post'})

        conn.execute('DELETE FROM group_posts WHERE id = ?', (post_id,))
        conn.execute('DELETE FROM group_post_likes WHERE post_id = ?', (post_id,))
        conn.execute('DELETE FROM post_media WHERE group_post_id = ?', (post_id,))

        conn.commit()
        return jsonify({'success': True})

    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})

    finally:
        conn.close()

@app.route('/feed')
def feed():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()

    posts_rows = conn.execute('''
        SELECT p.*,
               u.id as author_id, 
               u.username as author_username,
               up.full_name as author_name,
               COALESCE(up.avatar, 'default_avatar.png') as author_avatar,
               (SELECT COUNT(*) FROM post_likes WHERE post_id = p.id) as likes_count,
               (SELECT COUNT(*) FROM comments WHERE post_id = p.id) as comments_count
        FROM posts p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN user_profiles up ON u.id = up.user_id
        WHERE (p.visibility = 'public' 
               OR (p.visibility = 'friends' AND p.user_id IN (
                   SELECT CASE 
                       WHEN sender_id = ? THEN receiver_id 
                       ELSE sender_id 
                   END as friend_id
                   FROM friendships 
                   WHERE (sender_id = ? OR receiver_id = ?) AND status = 'accepted'
               ))
               OR p.user_id = ?)
        AND (p.user_id IN (
            SELECT CASE 
                WHEN sender_id = ? THEN receiver_id 
                ELSE sender_id 
            END as friend_id
            FROM friendships 
            WHERE (sender_id = ? OR receiver_id = ?) AND status = 'accepted'
        ) OR p.user_id = ?)
        ORDER BY p.created_at DESC
        LIMIT 50
    ''', (user_id, user_id, user_id, user_id, user_id, user_id, user_id, user_id)).fetchall()

    group_posts_rows = conn.execute('''
        SELECT gp.*,
               g.id as group_id,
               g.name as group_name,
               COALESCE(g.avatar, 'default_group.png') as group_avatar,
               u.id as author_id,
               u.username as author_username,
               up.full_name as author_name,
               COALESCE(up.avatar, 'default_avatar.png') as author_avatar,
               (SELECT COUNT(*) FROM group_post_likes WHERE post_id = gp.id) as likes_count
        FROM group_posts gp
        JOIN groups g ON gp.group_id = g.id
        JOIN users u ON gp.author_id = u.id
        LEFT JOIN user_profiles up ON u.id = up.user_id
        WHERE g.id IN (
            SELECT group_id FROM group_members WHERE user_id = ?
        )
        ORDER BY gp.created_at DESC
        LIMIT 50
    ''', (user_id,)).fetchall()

    all_posts = []
    for post in posts_rows:
        post_dict = dict(post)
        post_dict['type'] = 'personal'
        all_posts.append(post_dict)

    for post in group_posts_rows:
        post_dict = dict(post)
        post_dict['type'] = 'group'
        all_posts.append(post_dict)

    all_posts.sort(key=lambda x: x['created_at'], reverse=True)

    my_groups = rows_to_dicts(conn.execute('''
        SELECT g.*, COUNT(DISTINCT gm.user_id) as members_count
        FROM groups g
        JOIN group_members gm ON g.id = gm.group_id
        WHERE gm.user_id = ?
        GROUP BY g.id
        ORDER BY g.name
        LIMIT 10
    ''', (user_id,)).fetchall())

    conn.close()

    return render_template('feed.html', posts=all_posts, my_groups=my_groups)


@app.route('/create_post', methods=['POST'])
def create_post():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    content = request.form.get('content', '').strip()
    visibility = request.form.get('visibility', 'public')

    if not content:
        flash('Пост не может быть пустым', 'error')
        return redirect('/feed')

    conn = get_db_connection()
    current_datetime = get_current_datetime()
    conn.execute('''
        INSERT INTO posts (user_id, content, visibility, created_at)
        VALUES (?, ?, ?, ?)
    ''', (user_id, content, visibility, current_datetime))
    conn.commit()
    conn.close()

    flash('Пост опубликован!', 'success')
    return redirect('/feed')


@app.route('/like_post/<int:post_id>', methods=['POST'])
def like_post(post_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authorized'})

    user_id = session['user_id']
    post_type = request.args.get('type', 'personal')

    conn = get_db_connection()

    try:
        if post_type == 'personal':
            existing_like = conn.execute('''
                SELECT id FROM post_likes WHERE post_id = ? AND user_id = ?
            ''', (post_id, user_id)).fetchone()

            if existing_like:
                conn.execute('DELETE FROM post_likes WHERE id = ?', (existing_like['id'],))
                action = 'unliked'
            else:
                conn.execute('INSERT INTO post_likes (post_id, user_id) VALUES (?, ?)', (post_id, user_id))
                action = 'liked'

            likes_count = \
                conn.execute('SELECT COUNT(*) as count FROM post_likes WHERE post_id = ?', (post_id,)).fetchone()[
                    'count']
        else:
            existing_like = conn.execute('''
                SELECT id FROM group_post_likes WHERE post_id = ? AND user_id = ?
            ''', (post_id, user_id)).fetchone()

            if existing_like:
                conn.execute('DELETE FROM group_post_likes WHERE id = ?', (existing_like['id'],))
                action = 'unliked'
            else:
                conn.execute('INSERT INTO group_post_likes (post_id, user_id) VALUES (?, ?)', (post_id, user_id))
                action = 'liked'

            likes_count = \
                conn.execute('SELECT COUNT(*) as count FROM group_post_likes WHERE post_id = ?', (post_id,)).fetchone()[
                    'count']

        conn.commit()
        return jsonify({'success': True, 'action': action, 'likes_count': likes_count})

    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()


@app.route('/delete_post/<int:post_id>', methods=['POST'])
def delete_post(post_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authorized'})

    user_id = session['user_id']
    post_type = request.args.get('type', 'personal')

    conn = get_db_connection()

    try:
        if post_type == 'personal':
            post = conn.execute('SELECT user_id FROM posts WHERE id = ?', (post_id,)).fetchone()
            if not post or post['user_id'] != user_id:
                return jsonify({'success': False, 'error': 'Not authorized to delete this post'})

            conn.execute('DELETE FROM posts WHERE id = ?', (post_id,))
            conn.execute('DELETE FROM post_likes WHERE post_id = ?', (post_id,))
            conn.execute('DELETE FROM comments WHERE post_id = ?', (post_id,))
            conn.execute('DELETE FROM post_media WHERE post_id = ?', (post_id,))
        else:
            post = conn.execute('SELECT author_id, group_id FROM group_posts WHERE id = ?', (post_id,)).fetchone()
            if not post:
                return jsonify({'success': False, 'error': 'Post not found'})

            is_author = post['author_id'] == user_id
            is_admin = conn.execute('''
                SELECT role FROM group_members 
                WHERE group_id = ? AND user_id = ? AND role IN ('admin', 'moderator')
            ''', (post['group_id'], user_id)).fetchone()

            if not is_author and not is_admin:
                return jsonify({'success': False, 'error': 'Not authorized to delete this post'})

            conn.execute('DELETE FROM group_posts WHERE id = ?', (post_id,))
            conn.execute('DELETE FROM group_post_likes WHERE post_id = ?', (post_id,))
            conn.execute('DELETE FROM post_media WHERE group_post_id = ?', (post_id,))

        conn.commit()
        return jsonify({'success': True})

    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()


@app.route('/my_posts')
def my_posts():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()

    posts_rows = conn.execute('''
        SELECT * FROM posts 
        WHERE user_id = ? 
        ORDER BY created_at DESC
    ''', (user_id,)).fetchall()

    posts = rows_to_dicts(posts_rows)

    conn.close()

    return render_template('my_posts.html', posts=posts)

# ==================== ТЕХ-АДМИН ====================

@app.route('/techadmin')
def techadmin():
    if 'user_id' not in session:
        return redirect('/login')

    # Проверяем, является ли пользователь тех-админом
    conn = get_db_connection()
    user = conn.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()

    if not user or user['role'] != 'techadmin':
        flash('Доступ запрещен', 'error')
        return redirect('/home')

    return render_template('techadmin.html')


@app.route('/techadmin/reports')
def techadmin_reports():
    if 'user_id' not in session:
        return redirect('/login')

    # Проверяем, является ли пользователь тех-админом
    conn = get_db_connection()
    user = conn.execute('SELECT username, role FROM users WHERE id = ?', (session['user_id'],)).fetchone()

    print(f"=== ТЕХ-АДМИН ЗАПРОС ===")
    print(f"Пользователь: {user['username'] if user else 'не найден'}")
    print(f"Роль: {user['role'] if user else 'нет'}")

    if not user or user['role'] != 'techadmin':
        conn.close()
        flash('Доступ запрещен', 'error')
        return redirect('/home')

    # Получаем статус фильтра
    status_filter = request.args.get('status', 'all')

    print(f"Фильтр статуса: {status_filter}")

    # Формируем запрос в зависимости от фильтра
    query = '''
        SELECT r.*, 
               reporter.username as reporter_username,
               reported.username as reported_username,
               reporter_profile.full_name as reporter_full_name,
               reported_profile.full_name as reported_full_name
        FROM reports r
        JOIN users reporter ON r.reporter_id = reporter.id
        JOIN users reported ON r.reported_id = reported.id
        LEFT JOIN user_profiles reporter_profile ON reporter.id = reporter_profile.user_id
        LEFT JOIN user_profiles reported_profile ON reported.id = reported_profile.user_id
    '''

    if status_filter != 'all':
        query += f" WHERE r.status = '{status_filter}'"

    query += " ORDER BY r.created_at DESC"

    print(f"Выполняем SQL запрос...")

    reports_rows = conn.execute(query).fetchall()
    reports = rows_to_dicts(reports_rows)

    print(f"Найдено жалоб: {len(reports)}")
    for i, report in enumerate(reports):
        print(f"  {i + 1}. ID: {report['id']}, Статус: {report['status']}, От: {report['reporter_username']}, На: {report['reported_username']}")

    conn.close()

    return render_template('techadmin_reports.html', reports=reports)


@app.route('/techadmin/report_action/<int:report_id>/<action>', methods=['POST'])
def techadmin_report_action(report_id, action):
    if 'user_id' not in session:
        return redirect('/login')

    # Проверяем, является ли пользователь тех-админом
    conn = get_db_connection()
    user = conn.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()

    if not user or user['role'] != 'techadmin':
        conn.close()
        flash('Доступ запрещен', 'error')
        return redirect('/home')

    admin_notes = request.form.get('admin_notes', '')

    if action == 'approve':
        # Помечаем жалобу как обработанную
        conn.execute('''
            UPDATE reports 
            SET status = 'approved', admin_notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (admin_notes, report_id))

        # Получаем информацию о жалобе
        report = conn.execute('SELECT reported_id FROM reports WHERE id = ?', (report_id,)).fetchone()
        if report:
            # Баним пользователя (можно добавить более сложную логику)
            conn.execute('''
                UPDATE users SET is_banned = 1 WHERE id = ?
            ''', (report['reported_id'],))

        flash('Жалоба одобрена, пользователь забанен', 'success')


    elif action == 'reject':
        # Помечаем жалобу как отклоненную
        conn.execute('''
            UPDATE reports 
            SET status = 'rejected', admin_notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (admin_notes, report_id))
        flash('Жалоба отклонена', 'info')

    elif action == 'delete':
        # Удаляем жалобу
        conn.execute('DELETE FROM reports WHERE id = ?', (report_id,))
        flash('Жалоба удалена', 'info')

    conn.commit()
    conn.close()

    return redirect('/techadmin/reports')


@app.route('/techadmin/stats')
def techadmin_stats():
    """Получение статистики для тех-админа"""
    if 'user_id' not in session:
        return jsonify({'error': 'Требуется авторизация'}), 401

    conn = get_db_connection()

    # Проверяем, является ли пользователь тех-админом
    user = conn.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()

    if not user or user['role'] != 'techadmin':
        conn.close()
        return jsonify({'error': 'Доступ запрещен'}), 403

    # Получаем статистику жалоб
    pending_reports = conn.execute('''SELECT COUNT(*) as count FROM reports WHERE status = 'pending''').fetchone()[
        'count']
    total_reports = conn.execute('''SELECT COUNT(*) as count FROM reports''').fetchone()['count']

    # Получаем статистику пользователей
    banned_users = conn.execute('''SELECT COUNT(*) as count FROM users WHERE is_banned = 1''').fetchone()['count']
    total_users = conn.execute('''SELECT COUNT(*) as count FROM users''').fetchone()['count']

    conn.close()

    return jsonify({
        'pending_reports': pending_reports,
        'total_reports': total_reports,
        'banned_users': banned_users,
        'total_users': total_users
    })


# ==================== АУТЕНТИФИКАЦИЯ ====================

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form.get('confirm_password', '')

        if password != confirm_password:
            return render_template('register.html', error="Пароли не совпадают")

        if len(password) < 6:
            return render_template('register.html', error="Пароль должен содержать минимум 6 символов")

        try:
            connection = get_db_connection()
            cursor = connection.cursor()
            cursor.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, password))
            connection.commit()
            connection.close()
            flash('Регистрация успешна! Теперь вы можете войти.', 'success')
            return redirect('/login')
        except sqlite3.IntegrityError:
            return render_template('register.html', error="Пользователь с таким именем уже существует")
        except Exception as e:
            print(f"Ошибка регистрации: {e}")
            return render_template('register.html', error="Ошибка при регистрации")

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        try:
            connection = get_db_connection()
            cursor = connection.cursor()
            cursor.execute("SELECT id, username, role, is_banned FROM users WHERE username = ? AND password = ?",
                           (username, password))
            user_row = cursor.fetchone()
            connection.close()

            if user_row:
                # Преобразуем Row в словарь
                user = dict(user_row)

                # Проверяем, не забанен ли пользователь (для обычных пользователей)
                if user.get('role') == 'user' and user.get('is_banned', 0) == 1:
                    return render_template('login.html', error="Ваш аккаунт заблокирован")

                session['user_id'] = user['id']
                session['username'] = user['username']

                if username == 'admin':
                    return redirect('/admin')
                elif username == 'techadmin':
                    return redirect('/techadmin')
                else:
                    return redirect('/home')
            else:
                return render_template('login.html', error="Неверное имя пользователя или пароль")
        except Exception as e:
            print(f"Ошибка входа: {e}")
            return render_template('login.html', error="Ошибка базы данных")

    return render_template('login.html')


@app.route('/admin')
def admin():
    if 'user_id' not in session or session.get('username') != 'admin':
        return redirect('/login')
    return "Админ-панель (будет реализована позже)"


@app.route('/user')
def user_page():
    return redirect('/home')


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


@app.route('/get_user_stats')
def get_user_stats():
    if 'user_id' not in session:
        return jsonify({'error': 'Требуется авторизация'}), 401

    user_id = session['user_id']
    conn = get_db_connection()

    # Получаем количество постов пользователя
    posts_count = conn.execute('''
        SELECT COUNT(*) as count FROM posts WHERE user_id = ?
    ''', (user_id,)).fetchone()['count']

    # Получаем количество друзей
    friends_count = conn.execute('''
        SELECT COUNT(*) as count FROM friendships 
        WHERE (sender_id = ? OR receiver_id = ?) AND status = 'accepted'
    ''', (user_id, user_id)).fetchone()['count']

    conn.close()

    return jsonify({
        'posts_count': posts_count,
        'friends_count': friends_count
    })


@app.route('/check_table_structure')
def check_table_structure():
    conn = get_db_connection()
    cursor = conn.cursor()


    # Получаем информацию о таблице post_media
    cursor.execute("PRAGMA table_info(post_media)")
    columns = cursor.fetchall()

    result = "Структура таблицы post_media:<br>"
    for col in columns:
        result += f"ID: {col[0]}, Имя: {col[1]}, Тип: {col[2]}, NotNull: {col[3]}, Default: {col[4]}, PK: {col[5]}<br>"

    conn.close()
    return result


if __name__ == 'main':
    create_tables()
    app.run(debug=True, host='0.0.0.0', port=5555)