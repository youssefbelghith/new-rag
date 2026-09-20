import mysql.connector
import bcrypt
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
        cursor.execute("SHOW COLUMNS FROM historique LIKE 'conversation_id'")
        if cursor.fetchone() is None:
            cursor.execute(
                "ALTER TABLE historique ADD COLUMN conversation_id VARCHAR(36) NULL"
            )
            cursor.execute(
                "UPDATE historique SET conversation_id = UUID() "
                "WHERE conversation_id IS NULL"
            )
        cursor.execute("SHOW COLUMNS FROM historique LIKE 'conversation_title'")
        if cursor.fetchone() is None:
            cursor.execute(
                "ALTER TABLE historique ADD COLUMN conversation_title VARCHAR(120) NULL"
            )

        cursor.execute(
            "SELECT user_id, conversation_id FROM historique "
            "WHERE conversation_id IS NOT NULL AND conversation_title IS NULL "
            "GROUP BY user_id, conversation_id ORDER BY MIN(date_message), MIN(id)"
        )
        for user_id, conversation_id in cursor.fetchall():
            cursor.execute(
                "SELECT COUNT(DISTINCT conversation_id) FROM historique "
                "WHERE user_id = %s AND conversation_title IS NOT NULL",
                (user_id,)
            )
            conversation_number = cursor.fetchone()[0] + 1
            cursor.execute(
                "UPDATE historique SET conversation_title = %s "
                "WHERE user_id = %s AND conversation_id = %s",
                (f"Conversation n{conversation_number}", user_id, conversation_id)
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


def save_qa_history(user_id, question, answer, fichier=None, page=None, conversation_id=None):
    conversation_id = conversation_id or str(uuid4())
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT conversation_title FROM historique "
            "WHERE user_id = %s AND conversation_id = %s LIMIT 1",
            (user_id, conversation_id)
        )
        existing = cursor.fetchone()
        conversation_title = existing[0] if existing else None
        if conversation_title is None:
            cursor.execute(
                "SELECT COUNT(DISTINCT conversation_id) FROM historique "
                "WHERE user_id = %s AND conversation_title IS NOT NULL",
                (user_id,)
            )
            conversation_number = cursor.fetchone()[0] + 1
            conversation_title = f"Conversation n{conversation_number}"
        cursor.execute(
            "INSERT INTO historique "
            "(user_id, conversation_id, conversation_title, question_utilisateur, "
            "reponse_llm, nom_fichier, numero_page) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (user_id, conversation_id, conversation_title, question, answer, fichier, page)
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def save_conversation(user_id, conversation_id, exchanges, files):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT conversation_title FROM historique "
            "WHERE user_id = %s AND conversation_id = %s LIMIT 1",
            (user_id, conversation_id)
        )
        existing = cursor.fetchone()
        if existing:
            conversation_title = existing[0]
        else:
            cursor.execute(
                "SELECT COUNT(DISTINCT conversation_id) FROM historique "
                "WHERE user_id = %s AND conversation_title IS NOT NULL",
                (user_id,)
            )
            conversation_title = f"Conversation n{cursor.fetchone()[0] + 1}"

        for exchange in exchanges:
            sources = exchange.get("sources") or []
            source = sources[0] if sources else {}
            cursor.execute(
                "SELECT id FROM historique WHERE user_id = %s AND conversation_id = %s "
                "AND question_utilisateur = %s AND reponse_llm = %s LIMIT 1",
                (user_id, conversation_id, exchange["question"], exchange["answer"])
            )
            if cursor.fetchone():
                continue
            cursor.execute(
                "INSERT INTO historique "
                "(user_id, conversation_id, conversation_title, question_utilisateur, "
                "reponse_llm, nom_fichier, numero_page) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    user_id,
                    conversation_id,
                    conversation_title,
                    exchange["question"],
                    exchange["answer"],
                    source.get("fichier"),
                    source.get("page"),
                )
            )

        for file in files:
            if isinstance(file, str):
                file_name = file
                file_timestamp = None
            else:
                file_name = file["name"]
                file_timestamp = file.get("timestamp")
            cursor.execute(
                "INSERT IGNORE INTO conversation_files "
                "(user_id, conversation_id, file_name, file_timestamp) VALUES (%s, %s, %s, %s)",
                (user_id, conversation_id, file_name, file_timestamp)
            )
        conn.commit()
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
            "SELECT nom, prenom, email, date_creation FROM utilisateurs WHERE id = %s",
            (user_id,)
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

def get_user_history(user_id, limit=50):
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, conversation_id, question_utilisateur, reponse_llm, nom_fichier, numero_page, date_message "
            "FROM historique WHERE user_id = %s ORDER BY date_message DESC LIMIT %s",
            (user_id, limit)
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

def get_user_conversations(user_id, limit=100):
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT h.conversation_id, MAX(h.conversation_title) AS title, "
            "MAX(date_message) AS date_message, COUNT(*) AS message_count "
            "FROM historique h WHERE h.user_id = %s AND h.conversation_id IS NOT NULL "
            "GROUP BY h.conversation_id, h.user_id "
            "ORDER BY MAX(h.date_message) DESC LIMIT %s",
            (user_id, limit)
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

def get_conversation(user_id, conversation_id):
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, conversation_id, question_utilisateur, reponse_llm, "
            "nom_fichier, numero_page, date_message FROM historique "
            "WHERE user_id = %s AND conversation_id = %s ORDER BY date_message ASC, id ASC",
            (user_id, conversation_id)
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()