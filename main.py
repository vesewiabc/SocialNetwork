from flask import Flask, render_template, request, redirect, session, flash, url_for
import sqlite3
import os
from datetime import datetime
import hashlib
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "123"

# Настройки для загрузки файлов
UPLOAD_FOLDER = 'static/uploads/avatars'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2MB

# Создаем папку для загрузок, если ее нет
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

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
    
    # Проверяем и добавляем недостающие столбцы в таблицу user_profiles
    try:
        cursor.execute("SELECT avatar FROM user_profiles LIMIT 1")
    except sqlite3.OperationalError:
        print("Добавляем столбец avatar в таблицу user_profiles...")
        # Сначала добавляем столбец без DEFAULT значения
        cursor.execute('ALTER TABLE user_profiles ADD COLUMN avatar TEXT')
        # Затем обновляем существующие записи
        cursor.execute('UPDATE user_profiles SET avatar = "default_avatar.png" WHERE avatar IS NULL')
    
    # Проверяем столбец created_at в user_profiles
    try:
        cursor.execute("SELECT created_at FROM user_profiles LIMIT 1")
    except sqlite3.OperationalError:
        print("Добавляем столбец created_at в таблицу user_profiles...")
        cursor.execute('ALTER TABLE user_profiles ADD COLUMN created_at TIMESTAMP')
        cursor.execute('UPDATE user_profiles SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL')
    
    # Проверяем столбец created_at в users
    try:
        cursor.execute("SELECT created_at FROM users LIMIT 1")
    except sqlite3.OperationalError:
        print("Добавляем столбец created_at в таблицу users...")
        cursor.execute('ALTER TABLE users ADD COLUMN created_at TIMESTAMP')
        cursor.execute('UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL')
    
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
        password TEXT NOT NULL
    )
    ''')
    
    # Таблица профилей пользователей (без created_at и avatar в CREATE TABLE)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE,
        full_name TEXT,
        bio TEXT,
        location TEXT,
        website TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    ''')
    
    # Таблица постов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        content TEXT NOT NULL,
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
    
    connection.commit()
    connection.close()
    
    # Выполняем миграции для существующих таблиц
    migrate_database()


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
            # Используем COALESCE для обработки NULL значений
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
