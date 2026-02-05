import sqlite3
import json
from datetime import datetime
from typing import Optional, List, Dict, Tuple

class Database:
    def __init__(self, db_path: str = "reputation.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        
        # Пользователи
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Репутация
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reputation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER,
                to_user_id INTEGER,
                vote_type TEXT CHECK(vote_type IN ('positive', 'negative')),
                comment TEXT,
                photo_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (from_user_id) REFERENCES users(user_id),
                FOREIGN KEY (to_user_id) REFERENCES users(user_id)
            )
        ''')
        
        # Индексы для быстрого поиска
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_reputation_to_user ON reputation(to_user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_reputation_from_user ON reputation(from_user_id)')
        
        self.conn.commit()
    
    # === Методы для пользователей ===
    def get_or_create_user(self, user_id: int, username: str = "", first_name: str = "", last_name: str = ""):
        cursor = self.conn.cursor()
        
        # Проверяем существование
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        
        if not user:
            # Создаем нового
            cursor.execute('''
                INSERT INTO users (user_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name))
            self.conn.commit()
            
            # Получаем созданного
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            user = cursor.fetchone()
        
        return dict(user) if user else None
    
    def get_user(self, user_id: int):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        return dict(user) if user else None
    
    def search_user(self, query: str):
        """Поиск по username или ID"""
        cursor = self.conn.cursor()
        
        # Пробуем как ID
        if query.isdigit():
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (int(query),))
            user = cursor.fetchone()
            if user:
                return dict(user)
        
        # Пробуем как username (с @ или без)
        username = query.lstrip('@')
        cursor.execute('SELECT * FROM users WHERE username LIKE ?', (f"%{username}%",))
        user = cursor.fetchone()
        
        return dict(user) if user else None
    
    # === Методы для репутации ===
    def add_reputation(self, from_user_id: int, to_user_id: int, vote_type: str, comment: str = "", photo_id: str = ""):
        """Добавление оценки репутации"""
        cursor = self.conn.cursor()
        
        # Проверка самоголосования
        if from_user_id == to_user_id:
            return False, "Нельзя голосовать за себя"
        
        # Проверка: один голос в день на одного пользователя
        cursor.execute('''
            SELECT COUNT(*) FROM reputation 
            WHERE from_user_id = ? AND to_user_id = ? 
            AND DATE(created_at) = DATE('now')
        ''', (from_user_id, to_user_id))
        
        if cursor.fetchone()[0] > 0:
            return False, "Вы уже голосовали за этого пользователя сегодня"
        
        # Добавляем запись
        cursor.execute('''
            INSERT INTO reputation (from_user_id, to_user_id, vote_type, comment, photo_id)
            VALUES (?, ?, ?, ?, ?)
        ''', (from_user_id, to_user_id, vote_type, comment, photo_id))
        
        self.conn.commit()
        return True, "Репутация сохранена"
    
    def get_user_stats(self, user_id: int):
        """Статистика пользователя"""
        cursor = self.conn.cursor()
        
        # Подсчет оценок
        cursor.execute('''
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN vote_type = 'positive' THEN 1 ELSE 0 END) as positive,
                SUM(CASE WHEN vote_type = 'negative' THEN 1 ELSE 0 END) as negative
            FROM reputation 
            WHERE to_user_id = ?
        ''', (user_id,))
        
        stats = dict(cursor.fetchone())
        
        # Расчет процентов
        total = stats['total'] or 0
        positive = stats['positive'] or 0
        negative = stats['negative'] or 0
        
        if total > 0:
            pos_percent = round((positive / total) * 100)
            neg_percent = round((negative / total) * 100)
        else:
            pos_percent = 0
            neg_percent = 0
        
        return {
            'total': total,
            'positive': positive,
            'negative': negative,
            'positive_percent': pos_percent,
            'negative_percent': neg_percent
        }
    
    def get_user_reputation(self, user_id: int, filter_type: str = 'all'):
        """Получение отзывов о пользователе"""
        cursor = self.conn.cursor()
        
        query = '''
            SELECT r.*, u.username, u.first_name, u.last_name
            FROM reputation r
            LEFT JOIN users u ON r.from_user_id = u.user_id
            WHERE r.to_user_id = ?
        '''
        
        params = [user_id]
        
        if filter_type == 'positive':
            query += " AND r.vote_type = 'positive'"
        elif filter_type == 'negative':
            query += " AND r.vote_type = 'negative'"
        
        query += " ORDER BY r.created_at DESC"
        
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    
    def get_reputation_by_id(self, rep_id: int):
        """Получение конкретного отзыва"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT r.*, u.username, u.first_name, u.last_name
            FROM reputation r
            LEFT JOIN users u ON r.from_user_id = u.user_id
            WHERE r.id = ?
        ''', (rep_id,))
        rep = cursor.fetchone()
        return dict(rep) if rep else None
    
    def close(self):
        self.conn.close()
