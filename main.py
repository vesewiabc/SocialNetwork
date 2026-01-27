from flask import Flask, render_template, request, redirect, session, flash, url_for, jsonify
import sqlite3
import os
from datetime import datetime
import hashlib
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "123"

# Настройки для загрузки файлов
UPLOAD_FOLDER = 'static/uploads/avatars'
GROUP_UPLOAD_FOLDER = 'static/uploads/groups'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['GROUP_UPLOAD_FOLDER'] = GROUP_UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2MB

# Создаем папки для загрузок, если их нет
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(GROUP_UPLOAD_FOLDER, exist_ok=True)

def get_current_date():
    """Возвращает текущую дату в формате ДД.ММ.ГГГГ"""
    return datetime.now().strftime('%d.%m.%Y')

def get_current_datetime():
    """Возвращает текущую дату и время в формате ДД.ММ.ГГГГ ЧЧ:ММ"""
    return datetime.now().strftime('%d.%m.%Y %H:%M')

def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


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
        cursor.execute("SELECT avatar FROM user_profiles LIMIT 1")
    except sqlite3.OperationalError:
        print("Добавляем столбец avatar в таблицу user_profiles...")
        cursor.execute('ALTER TABLE user_profiles ADD COLUMN avatar TEXT')
        cursor.execute('UPDATE user_profiles SET avatar = "default_avatar.png" WHERE avatar IS NULL')

    # Обновляем существующие даты на новый формат
    try:
        # Преобразуем даты в таблице users
        cursor.execute("SELECT id, created_at FROM users WHERE created_at IS NOT NULL")
        users = cursor.fetchall()
        for user in users:
            old_date = user['created_at']
            try:
                # Пробуем разные форматы
                formats = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y.%m.%d', '%Y.%m.%d %H:%M:%S']
                new_date = old_date
                for fmt in formats:
                    try:
                        dt = datetime.strptime(old_date, fmt)
                        new_date = dt.strftime('%d.%m.%Y')
                        break
                    except:
                        continue
                cursor.execute("UPDATE users SET created_at = ? WHERE id = ?", (new_date, user['id']))
            except:
                pass
    except:
        pass

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
        created_at TEXT
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
        created_at TEXT,
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
        created_at TEXT,
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
        created_at TEXT,
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
        created_at TEXT,
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
        created_at TEXT,
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

    connection.commit()
    connection.close()

    # Выполняем миграции для существующих таблиц
    migrate_database()


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


@app.route('/')
def index():
    if 'user_id' in session:
        if session.get('username') == 'admin':
            return redirect('/admin')
        else:
            return redirect('/home')
    return redirect('/login')


@app.route('/home')
def home():
    if 'user_id' not in session:
        return redirect('/login')

    # Добавляем информацию о заявках в друзья на главную
    user_id = session['user_id']
    conn = get_db_connection()
    friend_requests_count = conn.execute('''
        SELECT COUNT(*) as count FROM friendships 
        WHERE receiver_id = ? AND status = 'pending'
    ''', (user_id,)).fetchone()['count']
    conn.close()

    return render_template('home.html',
                           username=session.get('username'),
                           friend_requests_count=friend_requests_count)


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

    conn.close()

    return render_template('profile.html',
                           user=user,
                           profile=profile_data,
                           posts_count=posts_count,
                           friends_count=friends_count,
                           friend_requests_count=friend_requests_count)


@app.route('/profile/<int:user_id>')
def view_profile(user_id):
    if 'user_id' not in session:
        return redirect('/login')

    conn = get_db_connection()

    # Получаем информацию о пользователе
    user = row_to_dict(conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone())

    if not user:
        flash('Пользователь не найден', 'error')
        return redirect('/home')

    # Получаем профиль пользователя
    profile_data = row_to_dict(conn.execute('SELECT * FROM user_profiles WHERE user_id = ?', (user_id,)).fetchone())

    # Получаем количество постов
    posts_count = conn.execute('SELECT COUNT(*) as count FROM posts WHERE user_id = ?', (user_id,)).fetchone()['count']

    # Проверяем статус дружбы (если просматриваете не свой профиль)
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

        # Обработка загрузки аватарки
        avatar_filename = None
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename and allowed_file(file.filename):
                # Генерируем уникальное имя файла
                filename = secure_filename(file.filename)
                file_ext = filename.rsplit('.', 1)[1].lower()
                unique_filename = f"{user_id}_{hashlib.md5(str(datetime.now()).encode()).hexdigest()[:10]}.{file_ext}"

                # Сохраняем файл
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                file.save(file_path)
                avatar_filename = unique_filename

        conn = get_db_connection()

        # Проверяем, существует ли уже профиль
        existing_profile = conn.execute('SELECT id FROM user_profiles WHERE user_id = ?', (user_id,)).fetchone()

        if existing_profile:
            # Обновляем существующий профиль
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
            # Создаем новый профиль
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
                AND u.id != ?
                LIMIT 20
            ''', (f'%{search_query}%', f'%{search_query}%', user_id)).fetchall()

            # Преобразуем Row объекты в словари
            search_results = rows_to_dicts(rows)

            # Проверяем статус дружбы для каждого найденного пользователя
            for user in search_results:
                friend_status = conn.execute('''
                    SELECT status FROM friendships 
                    WHERE (sender_id = ? AND receiver_id = ?) 
                    OR (sender_id = ? AND receiver_id = ?)
                ''', (user_id, user['id'], user['id'], user_id)).fetchone()

                user['friend_status'] = friend_status['status'] if friend_status else None

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
    current_datetime = get_current_datetime()

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


@app.route('/my_posts')
def my_posts():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()

    # Получаем посты пользователя
    posts_rows = conn.execute('''
        SELECT * FROM posts 
        WHERE user_id = ? 
        ORDER BY created_at DESC
    ''', (user_id,)).fetchall()

    # Преобразуем в словари
    posts = rows_to_dicts(posts_rows)

    conn.close()

    return render_template('my_posts.html', posts=posts)


# ЛЕНТА НОВОСТЕЙ
@app.route('/feed')
def feed():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()

    # Получаем посты друзей
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

    # Получаем посты из пабликов, на которые подписан пользователь
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

    # Объединяем и сортируем все посты
    all_posts = []
    for post in posts_rows:
        post_dict = dict(post)
        post_dict['type'] = 'personal'
        all_posts.append(post_dict)

    for post in group_posts_rows:
        post_dict = dict(post)
        post_dict['type'] = 'group'
        all_posts.append(post_dict)

    # Сортируем по дате
    all_posts.sort(key=lambda x: x['created_at'], reverse=True)

    # Получаем паблики пользователя для боковой панели
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


# Создание поста
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


# Лайк поста
@app.route('/like_post/<int:post_id>', methods=['POST'])
def like_post(post_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authorized'})

    user_id = session['user_id']
    post_type = request.args.get('type', 'personal')  # 'personal' или 'group'

    conn = get_db_connection()

    try:
        if post_type == 'personal':
            # Проверяем, есть ли уже лайк
            existing_like = conn.execute('''
                SELECT id FROM post_likes WHERE post_id = ? AND user_id = ?
            ''', (post_id, user_id)).fetchone()

            if existing_like:
                # Удаляем лайк
                conn.execute('DELETE FROM post_likes WHERE id = ?', (existing_like['id'],))
                action = 'unliked'
            else:
                # Добавляем лайк
                conn.execute('INSERT INTO post_likes (post_id, user_id) VALUES (?, ?)', (post_id, user_id))
                action = 'liked'

            # Получаем новое количество лайков
            likes_count = \
            conn.execute('SELECT COUNT(*) as count FROM post_likes WHERE post_id = ?', (post_id,)).fetchone()['count']
        else:
            # Лайк поста в группе
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


# Удаление поста
@app.route('/delete_post/<int:post_id>', methods=['POST'])
def delete_post(post_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authorized'})

    user_id = session['user_id']
    post_type = request.args.get('type', 'personal')

    conn = get_db_connection()

    try:
        if post_type == 'personal':
            # Проверяем, является ли пользователь автором поста
            post = conn.execute('SELECT user_id FROM posts WHERE id = ?', (post_id,)).fetchone()
            if not post or post['user_id'] != user_id:
                return jsonify({'success': False, 'error': 'Not authorized to delete this post'})

            # Удаляем пост
            conn.execute('DELETE FROM posts WHERE id = ?', (post_id,))
            conn.execute('DELETE FROM post_likes WHERE post_id = ?', (post_id,))
            conn.execute('DELETE FROM comments WHERE post_id = ?', (post_id,))
        else:
            # Для групповых постов проверяем права
            post = conn.execute('SELECT author_id, group_id FROM group_posts WHERE id = ?', (post_id,)).fetchone()
            if not post:
                return jsonify({'success': False, 'error': 'Post not found'})

            # Проверяем, является ли пользователь автором или админом группы
            is_author = post['author_id'] == user_id
            is_admin = conn.execute('''
                SELECT role FROM group_members 
                WHERE group_id = ? AND user_id = ? AND role IN ('admin', 'moderator')
            ''', (post['group_id'], user_id)).fetchone()

            if not is_author and not is_admin:
                return jsonify({'success': False, 'error': 'Not authorized to delete this post'})

            conn.execute('DELETE FROM group_posts WHERE id = ?', (post_id,))
            conn.execute('DELETE FROM group_post_likes WHERE post_id = ?', (post_id,))

        conn.commit()
        return jsonify({'success': True})

    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})

    finally:
        conn.close()


# ПАБЛИКИ (ГРУППЫ)
@app.route('/groups')
def groups_list():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    search_query = request.args.get('search', '')
    tab = request.args.get('tab', 'all')

    conn = get_db_connection()

    query = '''
        SELECT g.*, 
               COUNT(DISTINCT gm.user_id) as members_count,
               COUNT(DISTINCT gp.id) as posts_count,
               EXISTS(SELECT 1 FROM group_members WHERE group_id = g.id AND user_id = ?) as is_member,
               (SELECT role FROM group_members WHERE group_id = g.id AND user_id = ? LIMIT 1) as role
        FROM groups g
        LEFT JOIN group_members gm ON g.id = gm.group_id
        LEFT JOIN group_posts gp ON g.id = gp.group_id
    '''
    params = [user_id, user_id]

    if tab == 'my':
        query += ' WHERE g.id IN (SELECT group_id FROM group_members WHERE user_id = ?)'
        params.append(user_id)
    elif tab == 'popular':
        query += ' WHERE g.is_public = 1'
    else:  # all
        query += ' WHERE g.is_public = 1'

    if search_query:
        if 'WHERE' in query:
            query += ' AND'
        else:
            query += ' WHERE'
        query += ' (g.name LIKE ? OR g.description LIKE ?)'
        params.extend([f'%{search_query}%', f'%{search_query}%'])

    query += ' GROUP BY g.id ORDER BY members_count DESC'

    groups = rows_to_dicts(conn.execute(query, params).fetchall())
    conn.close()

    return render_template('groups.html', groups=groups, search_query=search_query, current_tab=tab)


# Создание паблика
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

    # Обработка аватарки
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


# Вступление в паблик
@app.route('/join_group/<int:group_id>', methods=['POST'])
def join_group(group_id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']

    conn = get_db_connection()

    try:
        # Проверяем, не состоит ли уже пользователь в группе
        existing_member = conn.execute('''
            SELECT id FROM group_members WHERE group_id = ? AND user_id = ?
        ''', (group_id, user_id)).fetchone()

        if existing_member:
            flash('Вы уже состоите в этом паблике', 'info')
        else:
            # Проверяем, является ли группа публичной
            group = conn.execute('SELECT is_public FROM groups WHERE id = ?', (group_id,)).fetchone()
            if group and group['is_public']:
                conn.execute('''
                    INSERT INTO group_members (group_id, user_id, role)
                    VALUES (?, ?, 'member')
                ''', (group_id, user_id))
                flash('Вы вступили в паблик!', 'success')
            else:
                flash('Этот паблик закрытый', 'error')

        conn.commit()

    except Exception as e:
        conn.rollback()
        flash(f'Ошибка: {str(e)}', 'error')

    finally:
        conn.close()

    return redirect(request.referrer or '/groups')


# Выход из паблика
@app.route('/leave_group/<int:group_id>', methods=['POST'])
def leave_group(group_id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']

    conn = get_db_connection()

    try:
        # Проверяем, не является ли пользователь создателем
        group = conn.execute('SELECT creator_id FROM groups WHERE id = ?', (group_id,)).fetchone()
        if group and group['creator_id'] == user_id:
            flash('Создатель не может покинуть паблик. Сначала передайте права админа другому участнику.', 'error')
        else:
            conn.execute('DELETE FROM group_members WHERE group_id = ? AND user_id = ?', (group_id, user_id))
            flash('Вы покинули паблик', 'info')

        conn.commit()

    except Exception as e:
        conn.rollback()
        flash(f'Ошибка: {str(e)}', 'error')

    finally:
        conn.close()

    return redirect(request.referrer or '/groups')


# Страница паблика
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

    # Получаем посты группы
    posts = []
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

    conn.close()

    return render_template('group_detail.html',
                           group=group,
                           posts=posts,
                           members=members,
                           creator=creator,
                           is_member=is_member,
                           role=role)


# Создание поста в паблике
@app.route('/group/<int:group_id>/create_post', methods=['POST'])
def create_group_post(group_id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    content = request.form.get('content', '').strip()

    if not content:
        flash('Пост не может быть пустым', 'error')
        return redirect(f'/group/{group_id}')

    conn = get_db_connection()
    current_datetime = get_current_datetime()

    try:
        # Проверяем, является ли пользователь участником группы
        membership = conn.execute('''
            SELECT id FROM group_members WHERE group_id = ? AND user_id = ?
        ''', (group_id, user_id)).fetchone()

        if not membership:
            flash('Вы не являетесь участником этого паблика', 'error')
            return redirect(f'/group/{group_id}')

        # Создаем пост
        conn.execute('''
            INSERT INTO group_posts (group_id, author_id, content, created_at)
            VALUES (?, ?, ?, ?)
        ''', (group_id, user_id, content, current_datetime))

        conn.commit()
        flash('Пост опубликован в паблике!', 'success')

    except Exception as e:
        conn.rollback()
        flash(f'Ошибка: {str(e)}', 'error')
    finally:
        conn.close()

    return redirect(f'/group/{group_id}')


# Удаление поста из паблика
@app.route('/group_post/delete/<int:post_id>', methods=['POST'])
def delete_group_post(post_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authorized'})

    user_id = session['user_id']

    conn = get_db_connection()

    try:
        # Получаем информацию о посте
        post = conn.execute('''
            SELECT gp.*, g.creator_id
            FROM group_posts gp
            JOIN groups g ON gp.group_id = g.id
            WHERE gp.id = ?
        ''', (post_id,)).fetchone()

        if not post:
            return jsonify({'success': False, 'error': 'Post not found'})

        # Проверяем права: автор, админ или создатель группы
        is_author = post['author_id'] == user_id
        is_creator = post['creator_id'] == user_id
        is_admin = conn.execute('''
            SELECT role FROM group_members 
            WHERE group_id = ? AND user_id = ? AND role IN ('admin', 'moderator')
        ''', (post['group_id'], user_id)).fetchone()

        if not is_author and not is_creator and not is_admin:
            return jsonify({'success': False, 'error': 'Not authorized to delete this post'})

        # Удаляем пост
        conn.execute('DELETE FROM group_posts WHERE id = ?', (post_id,))
        conn.execute('DELETE FROM group_post_likes WHERE post_id = ?', (post_id,))

        conn.commit()
        return jsonify({'success': True})

    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})

    finally:
        conn.close()


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
            # Используем нашу функцию для даты
            current_date = get_current_date()
            cursor.execute('INSERT INTO users (username, password, created_at) VALUES (?, ?, ?)',
                         (username, password, current_date))
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
            cursor.execute("SELECT id FROM users WHERE username = ? AND password = ?", (username, password))
            user = cursor.fetchone()
            connection.close()

            if user:
                session['user_id'] = user['id']
                session['username'] = username

                if username == 'admin':
                    return redirect('/admin')
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


if __name__ == '__main__':
    create_tables()
    app.run(debug=True, host='0.0.0.0', port=5555)