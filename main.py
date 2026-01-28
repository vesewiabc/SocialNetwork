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


def migrate_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Проверяем и добавляем недостающие столбцы в таблицу users
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
        cursor.execute("SELECT created_at FROM users LIMIT 1")
    except sqlite3.OperationalError:
        print("Добавляем столбец created_at в таблицу users...")
        cursor.execute('ALTER TABLE users ADD COLUMN created_at TIMESTAMP')
        cursor.execute('UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL')
    
    # Проверяем и добавляем недостающие столбцы в таблицу user_profiles
    try:
        cursor.execute("SELECT avatar FROM user_profiles LIMIT 1")
    except sqlite3.OperationalError:
        print("Добавляем столбец avatar в таблицу user_profiles...")
        cursor.execute('ALTER TABLE user_profiles ADD COLUMN avatar TEXT')
        cursor.execute('UPDATE user_profiles SET avatar = "default_avatar.png" WHERE avatar IS NULL')
    
    try:
        cursor.execute("SELECT created_at FROM user_profiles LIMIT 1")
    except sqlite3.OperationalError:
        print("Добавляем столбец created_at в таблицу user_profiles...")
        cursor.execute('ALTER TABLE user_profiles ADD COLUMN created_at TIMESTAMP')
        cursor.execute('UPDATE user_profiles SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL')
    
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
    
    # Создаем таблицу жалоб, если ее нет
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
    
    conn.commit()
    conn.close()

def create_tables():
    connection = get_db_connection()
    cursor = connection.cursor()
    
    # Таблица пользователей (без дополнительных столбцов, они добавятся через миграцию)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL
    )
    ''')
    
    # Таблица профилей пользователей (без дополнительных столбцов)
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

def get_news_feed(user_id=None, limit=30):
    """Получение ленты новостей (посты пользователей + импортированные новости)"""
    conn = get_db_connection()
    
    user_posts = []
    imported_news = []
    
    try:
        # Получаем посты пользователей
        if user_id:
            try:
                user_posts_rows = conn.execute('''
                    SELECT p.*, u.username, up.avatar, up.full_name,
                           (SELECT COUNT(*) FROM post_likes WHERE post_id = p.id) as likes_count,
                           (SELECT COUNT(*) FROM comments WHERE post_id = p.id) as comments_count
                    FROM posts p
                    JOIN users u ON p.user_id = u.id
                    LEFT JOIN user_profiles up ON u.id = up.user_id
                    WHERE u.id = ? OR u.id IN (
                        SELECT CASE 
                            WHEN sender_id = ? THEN receiver_id 
                            ELSE sender_id 
                        END as friend_id
                        FROM friendships 
                        WHERE (sender_id = ? OR receiver_id = ?) AND status = 'accepted'
                    )
                    ORDER BY p.created_at DESC
                    LIMIT 15
                ''', (user_id, user_id, user_id, user_id)).fetchall()
                
                if user_posts_rows:
                    user_posts = rows_to_dicts(user_posts_rows)
            except Exception as e:
                print(f"Ошибка при получении постов: {e}")
        
        # Получаем импортированные новости
        try:
            news_rows = conn.execute('''
                SELECT *, 'news' as type FROM imported_news
                ORDER BY published DESC
                LIMIT 15
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
    
    # Сортируем по дате создания (если есть)
    try:
        all_feed.sort(key=lambda x: x.get('created_at') or x.get('published') or '', reverse=True)
    except:
        pass
    
    return all_feed[:limit]

def fetch_rbc_news():
    """Получение новостей с RBC.ru"""
    try:
        # Основные RSS ленты RBC
        rss_urls = [
            'https://rssexport.rbc.ru/rbcnews/news/30/full.rss',
            'https://rssexport.rbc.ru/rbcnews/news/20/full.rss',
            'https://rssexport.rbc.ru/rbcnews/news/10/full.rss'
        ]
        
        all_news = []
        
        for rss_url in rss_urls:
            try:
                # Парсим RSS ленту
                feed = feedparser.parse(rss_url)
                
                # Проверяем, есть ли записи
                if hasattr(feed, 'entries') and feed.entries:
                    for entry in feed.entries[:3]:  # Берем первые 3 новости
                        try:
                            title = entry.get('title', 'Новость без названия')
                            description = entry.get('description', '')
                            link = entry.get('link', '')
                            
                            # Пропускаем если нет ссылки
                            if not link:
                                continue
                            
                            # Очищаем описание от HTML тегов
                            if description:
                                # Используем BeautifulSoup для очистки HTML
                                soup = BeautifulSoup(description, 'html.parser')
                                # Удаляем все теги, оставляем только текст
                                clean_description = soup.get_text().strip()
                                
                                # Обрезаем слишком длинные описания
                                if len(clean_description) > 150:
                                    clean_description = clean_description[:150] + '...'
                            else:
                                clean_description = 'Читать далее...'
                            
                            # Обрабатываем дату публикации
                            published = entry.get('published', '')
                            if published:
                                try:
                                    # Пробуем распарсить дату в разных форматах
                                    parsed_date = None
                                    date_formats = [
                                        '%a, %d %b %Y %H:%M:%S %z',
                                        '%a, %d %b %Y %H:%M:%S %Z',
                                        '%Y-%m-%dT%H:%M:%S%z',
                                        '%Y-%m-%d %H:%M:%S'
                                    ]
                                    
                                    for date_format in date_formats:
                                        try:
                                            parsed_date = datetime.strptime(published, date_format)
                                            break
                                        except:
                                            continue
                                    
                                    if parsed_date:
                                        published_str = parsed_date.strftime('%d.%m.%Y %H:%M')
                                    else:
                                        published_str = datetime.now().strftime('%d.%m.%Y %H:%M')
                                except:
                                    published_str = datetime.now().strftime('%d.%m.%Y %H:%M')
                            else:
                                published_str = datetime.now().strftime('%d.%m.%Y %H:%M')
                            
                            # Создаем объект новости
                            news_item = {
                                'title': title,
                                'description': clean_description,
                                'link': link,
                                'published': published_str,
                                'source': 'RBC'
                            }
                            
                            all_news.append(news_item)
                            
                        except Exception as e:
                            print(f"Ошибка при обработке новости: {e}")
                            continue
                else:
                    print(f"Нет записей в RSS ленте: {rss_url}")
                    
            except Exception as e:
                print(f"Ошибка при получении RSS с {rss_url}: {e}")
                continue
        
        # Удаляем дубликаты по ссылкам
        seen_links = set()
        unique_news = []
        for news in all_news:
            if news['link'] not in seen_links:
                seen_links.add(news['link'])
                unique_news.append(news)
        
        return unique_news[:8]  # Возвращаем до 8 новостей
        
    except Exception as e:
        print(f"Критическая ошибка при получении новостей RBC: {e}")
        return []

def import_news_to_db():
    """Импорт новостей в базу данных"""
    try:
        # Пробуем получить новости
        news_items = fetch_rbc_news()
        
        # Если не получили новости, пробуем альтернативный источник
        if not news_items:
            print("Не удалось получить новости RBC, пробуем альтернативный источник...")
            news_items = fetch_alternative_news()
        
        if not news_items:
            print("Не удалось получить новости ни из одного источника")
            return False
        
        conn = get_db_connection()
        
        imported_count = 0
        for news in news_items:
            try:
                # Проверяем, не существует ли уже такая новость
                existing = conn.execute(
                    'SELECT id FROM imported_news WHERE link = ?',
                    (news['link'],)
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
                        news['title'],
                        news['description'],
                        news['link'],
                        news.get('source', 'news'),
                        published_dt
                    ))
                    imported_count += 1
                    
            except Exception as e:
                print(f"Ошибка при импорте новости '{news.get('title', '')}': {e}")
                continue
        
        conn.commit()
        conn.close()
        
        print(f"Успешно импортировано {imported_count} новостей")
        return imported_count > 0
        
    except Exception as e:
        print(f"Критическая ошибка при импорте новостей в БД: {e}")
        return False

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
            except Exception as e:
                flash(f'Ошибка при публикации поста: {str(e)[:50]}', 'error')
            finally:
                conn.close()
        else:
            flash('Пост не может быть пустым', 'error')
        
        return redirect('/home')
    
    # GET запрос - показываем ленту
    feed_items = []
    
    try:
        # Пробуем импортировать новости (только раз в 20 запросов)
        import_counter = session.get('import_counter', 0)
        import_counter += 1
        session['import_counter'] = import_counter
        
        if import_counter % 20 == 0:
            print(f"Попытка импорта новостей (запрос #{import_counter})...")
            import_news_to_db()
        
        # Получаем ленту новостей
        feed_items = get_news_feed(user_id, limit=20)
        
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
@app.route('/report_user/<int:user_id>', methods=['GET', 'POST'])
def report_user(user_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    reporter_id = session['user_id']
    
    if reporter_id == user_id:
        flash('Нельзя отправить жалобу на себя!', 'error')
        return redirect(request.referrer or '/find_friends')
    
    if request.method == 'POST':
        reason = request.form.get('reason', '').strip()
        
        if not reason or len(reason) < 10:
            flash('Пожалуйста, опишите причину жалобы подробнее (минимум 10 символов)', 'error')
            return redirect(f'/report_user/{user_id}')
        
        conn = get_db_connection()
        
        # Отправляем жалобу
        conn.execute('''
            INSERT INTO reports (reporter_id, reported_id, reason, status)
            VALUES (?, ?, ?, 'pending')
        ''', (reporter_id, user_id, reason))
        
        conn.commit()
        conn.close()
        
        flash('Жалоба отправлена администратору. Спасибо за ваше сообщение!', 'success')
        return redirect('/find_friends')
    
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
        return redirect('/find_friends')

# Панель тех-админа
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
    user = conn.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    
    if not user or user['role'] != 'techadmin':
        conn.close()
        flash('Доступ запрещен', 'error')
        return redirect('/home')
    
    # Получаем все жалобы
    reports_rows = conn.execute('''
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
        ORDER BY r.created_at DESC
    ''').fetchall()
    
    reports = rows_to_dicts(reports_rows)
    
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
            cursor.execute("SELECT id, username, role, is_banned FROM users WHERE username = ? AND password = ?", (username, password))
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

if __name__ == '__main__':
    create_tables()
    app.run(debug=True, host='0.0.0.0', port=5555)
