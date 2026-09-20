import mysql.connector
import bcrypt
import json
from uuid import uuid4

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "neopolis_rag_db"
}

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def ensure_history_schema():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS chat_sessions ("
            "id VARCHAR(36) PRIMARY KEY, user_id INT NOT NULL, "
            "title VARCHAR(120) NOT NULL, model_settings JSON NULL, "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, "
            "INDEX chat_sessions_user_updated (user_id, updated_at)"
            ")"
        )
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS chat_messages ("
            "id BIGINT AUTO_INCREMENT PRIMARY KEY, session_id VARCHAR(36) NOT NULL, "
            "legacy_history_id INT NULL, role VARCHAR(20) NOT NULL, content LONGTEXT NOT NULL, "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, source_file VARCHAR(255) NULL, "
            "source_page INT NULL, INDEX chat_messages_session (session_id, created_at, id), "
            "UNIQUE KEY chat_messages_legacy (session_id, legacy_history_id, role)"
            ")"
        )
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS conversation_files ("
            "id INT AUTO_INCREMENT PRIMARY KEY, "
            "user_id INT NOT NULL, conversation_id VARCHAR(36) NOT NULL, "
            "file_name VARCHAR(255) NOT NULL, file_timestamp VARCHAR(40) NULL, "
            "UNIQUE KEY unique_conversation_file (user_id, conversation_id, file_name), "
            "INDEX conversation_files_lookup (user_id, conversation_id)"
            ")"
        )
        cursor.execute("SHOW COLUMNS FROM conversation_files LIKE 'file_timestamp'")
        if cursor.fetchone() is None:
            cursor.execute(
                "ALTER TABLE conversation_files ADD COLUMN file_timestamp VARCHAR(40) NULL"
            )
        cursor.execute("DROP TABLE IF EXISTS historique")
        cursor.execute("SHOW COLUMNS FROM utilisateurs LIKE 'avatar'")
        if cursor.fetchone() is None:
            cursor.execute("ALTER TABLE utilisateurs ADD COLUMN avatar LONGTEXT NULL")
        cursor.execute(
            "DELETE FROM conversation_files WHERE conversation_id NOT IN "
            "(SELECT id FROM chat_sessions)"
        )
        cursor.execute(
            "DELETE FROM chat_sessions WHERE id NOT IN "
            "(SELECT DISTINCT session_id FROM chat_messages)"
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def create_user(nom, prenom, email, password):
    """Insert a new user. Returns user_id or raises an exception."""
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO utilisateurs (nom, prenom, email, mot_de_passe_hash) VALUES (%s, %s, %s, %s)",
            (nom, prenom, email, hashed)
        )
        conn.commit()
        user_id = cursor.lastrowid
        return user_id
    finally:
        cursor.close()
        conn.close()

def authenticate_user(email, password):
    """
    Verify credentials.
    Returns (user_id, nom, prenom, email) if successful, else None.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM utilisateurs WHERE email = %s", (email,))
        user = cursor.fetchone()
        stored_hash = user["mot_de_passe_hash"] if user else None
        if isinstance(stored_hash, str):
            stored_hash = stored_hash.encode("utf-8")
        if user and stored_hash and bcrypt.checkpw(password.encode("utf-8"), stored_hash):
            return user["id"], user["nom"], user["prenom"], user["email"]
        return None
    finally:
        cursor.close()
        conn.close()


def create_chat_session(user_id, title="New conversation", model_settings=None, session_id=None):
    session_id = session_id or str(uuid4())
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO chat_sessions (id, user_id, title, model_settings) VALUES (%s, %s, %s, %s)",
            (session_id, user_id, title.strip() or "New conversation", json.dumps(model_settings or {}))
        )
        conn.commit()
        return get_chat_session(user_id, session_id)
    finally:
        cursor.close()
        conn.close()

def get_chat_sessions(user_id, limit=100):
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT s.id, s.title, s.model_settings, s.created_at, s.updated_at, "
            "COUNT(m.id) AS message_count "
            "FROM chat_sessions s LEFT JOIN chat_messages m ON m.session_id = s.id "
            "WHERE s.user_id = %s GROUP BY s.id "
            "HAVING COUNT(m.id) > 0 ORDER BY s.updated_at DESC LIMIT %s",
            (user_id, limit)
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

def get_chat_session(user_id, session_id):
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, title, model_settings, created_at, updated_at "
            "FROM chat_sessions WHERE id = %s AND user_id = %s",
            (session_id, user_id)
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

def update_chat_session(user_id, session_id, title=None, model_settings=None):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        fields = []
        values = []
        if title is not None:
            fields.append("title = %s")
            values.append(title.strip() or "New conversation")
        if model_settings is not None:
            fields.append("model_settings = %s")
            values.append(json.dumps(model_settings))
        if not fields:
            return get_chat_session(user_id, session_id)
        values.extend([session_id, user_id])
        cursor.execute(
            f"UPDATE chat_sessions SET {', '.join(fields)} WHERE id = %s AND user_id = %s",
            values
        )
        if cursor.rowcount == 0:
            return None
        conn.commit()
        return get_chat_session(user_id, session_id)
    finally:
        cursor.close()
        conn.close()

def delete_chat_session(user_id, session_id):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_messages WHERE session_id = %s", (session_id,))
        cursor.execute(
            "DELETE FROM conversation_files WHERE user_id = %s AND conversation_id = %s",
            (user_id, session_id)
        )
        cursor.execute(
            "DELETE FROM chat_sessions WHERE id = %s AND user_id = %s",
            (session_id, user_id)
        )
        deleted = cursor.rowcount > 0
        conn.commit()
        return deleted
    finally:
        cursor.close()
        conn.close()

def get_chat_session_detail(user_id, session_id):
    session = get_chat_session(user_id, session_id)
    if not session:
        return None
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, role, content, created_at, source_file, source_page "
            "FROM chat_messages WHERE session_id = %s ORDER BY created_at ASC, id ASC",
            (session_id,)
        )
        messages = cursor.fetchall()
        return {**session, "messages": messages, "files": get_conversation_files(user_id, session_id)}
    finally:
        cursor.close()
        conn.close()

def save_chat_messages(user_id, session_id, exchanges, files):
    if not get_chat_session(user_id, session_id):
        return False
    conn = get_connection()
    try:
        cursor = conn.cursor()
        for exchange in exchanges:
            sources = exchange.get("sources") or []
            source = sources[0] if sources else {}
            for role, content in (("user", exchange["question"]), ("assistant", exchange["answer"])):
                cursor.execute(
                    "SELECT id FROM chat_messages WHERE session_id = %s AND role = %s AND content = %s LIMIT 1",
                    (session_id, role, content)
                )
                if cursor.fetchone():
                    continue
                cursor.execute(
                    "INSERT INTO chat_messages (session_id, role, content, source_file, source_page) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (session_id, role, content, source.get("fichier") if role == "assistant" else None,
                     source.get("page") if role == "assistant" else None)
                )
        for file in files:
            file_name = file if isinstance(file, str) else file["name"]
            file_timestamp = None if isinstance(file, str) else file.get("timestamp")
            cursor.execute(
                "INSERT IGNORE INTO conversation_files "
                "(user_id, conversation_id, file_name, file_timestamp) VALUES (%s, %s, %s, %s)",
                (user_id, session_id, file_name, file_timestamp)
            )
        cursor.execute(
            "UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = %s AND user_id = %s",
            (session_id, user_id)
        )
        conn.commit()
        return True
    finally:
        cursor.close()
        conn.close()

def get_conversation_files(user_id, conversation_id):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT file_name, file_timestamp FROM conversation_files "
            "WHERE user_id = %s AND conversation_id = %s ORDER BY id ASC",
            (user_id, conversation_id)
        )
        return [{"name": row[0], "timestamp": row[1]} for row in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()

def get_user_info(user_id):
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT nom, prenom, email, date_creation, avatar FROM utilisateurs WHERE id = %s",
            (user_id,)
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

def update_user_avatar(user_id, avatar):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM utilisateurs WHERE id = %s", (user_id,))
        if cursor.fetchone() is None:
            return False
        cursor.execute(
            "UPDATE utilisateurs SET avatar = %s WHERE id = %s",
            (avatar, user_id)
        )
        conn.commit()
        return True
    finally:
        cursor.close()
        conn.close()
