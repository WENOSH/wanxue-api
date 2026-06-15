"""WanXue 用户认证与学习记录模块

支持 SQLite（本地开发）和 PostgreSQL（Render 部署）。
当环境变量 DATABASE_URL 存在时自动使用 PostgreSQL。
"""

import hashlib, secrets, json, logging, time, random, sqlite3
from pathlib import Path

log = logging.getLogger("wanxue.auth")

# ── 数据库选择 ────────────────
# 优先用环境变量 DATABASE_URL（Render 自动注入），否则用本地 SQLite
DATABASE_URL = ""
try:
    from wanxue_api.config import DATABASE_URL
except ImportError:
    import os
    DATABASE_URL = os.getenv("DATABASE_URL", "")

_USE_PG = bool(DATABASE_URL and DATABASE_URL.strip())

DB_PATH = Path(__file__).parent / "wanxue_users.db"


def _get_conn():
    """获取数据库连接，自动选择 PostgreSQL 或 SQLite"""
    if _USE_PG:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn
    else:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn


def _execute(conn, sql, params=None):
    """统一执行 SQL（兼容 PG/SQLite）"""
    if _USE_PG:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            if cur.description:
                try:
                    return cur.fetchall()
                except psycopg2.ProgrammingError:
                    return []
            return []
    else:
        if params:
            return conn.execute(sql, params)
        try:
            return conn.execute(sql)
        except sqlite3.ProgrammingError:
            # SQLite conn.execute() 一次只支持一条语句
            # 多语句 DDL 使用 executescript
            return conn.executescript(sql)


def _fetchone(cursor_or_conn, sql, params=None):
    """获取单行（兼容 PG/SQLite）"""
    if _USE_PG:
        with cursor_or_conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()
    else:
        return cursor_or_conn.execute(sql, params or ()).fetchone()


def _fetchall(cursor_or_conn, sql, params=None):
    """获取所有行（兼容 PG/SQLite）"""
    if _USE_PG:
        with cursor_or_conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()
    else:
        return cursor_or_conn.execute(sql, params or ()).fetchall()


def _row_to_dict(row, keys):
    """将 PG 或 SQLite 行转为字典"""
    if row is None:
        return None
    if _USE_PG:
        return dict(zip(keys, row))
    else:
        return dict(row)


def init_db():
    """初始化数据库表（PG/SQLite 兼容）"""
    conn = _get_conn()
    try:
        if _USE_PG:
            _execute(conn, """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    phone VARCHAR(64) UNIQUE NOT NULL,
                    password_hash VARCHAR(128) NOT NULL,
                    nickname VARCHAR(64) DEFAULT '',
                    created_at DOUBLE PRECISION NOT NULL,
                    last_login DOUBLE PRECISION
                );
                CREATE TABLE IF NOT EXISTS sms_codes (
                    id SERIAL PRIMARY KEY,
                    phone VARCHAR(64) NOT NULL,
                    code VARCHAR(16) NOT NULL,
                    expires_at DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS learning_records (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    course_id VARCHAR(128) NOT NULL,
                    course_title VARCHAR(256) DEFAULT '',
                    progress INTEGER DEFAULT 0,
                    total_cards INTEGER DEFAULT 0,
                    completed INTEGER DEFAULT 0,
                    quiz_score INTEGER DEFAULT 0,
                    badges TEXT DEFAULT '[]',
                    updated_at DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tokens (
                    token VARCHAR(128) PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    expires_at DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_courses (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    course_id VARCHAR(128) NOT NULL,
                    course_title VARCHAR(256) DEFAULT '',
                    course_emoji VARCHAR(16) DEFAULT '📖',
                    total_chapters INTEGER DEFAULT 0,
                    total_cards INTEGER DEFAULT 0,
                    difficulty VARCHAR(32) DEFAULT '',
                    created_at DOUBLE PRECISION NOT NULL,
                    UNIQUE(user_id, course_id)
                );
            """)
        else:
            _execute(conn, """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    nickname TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    last_login REAL
                );
                CREATE TABLE IF NOT EXISTS sms_codes (
                    phone TEXT NOT NULL,
                    code TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS learning_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    course_id TEXT NOT NULL,
                    course_title TEXT DEFAULT '',
                    progress INTEGER DEFAULT 0,
                    total_cards INTEGER DEFAULT 0,
                    completed INTEGER DEFAULT 0,
                    quiz_score INTEGER DEFAULT 0,
                    badges TEXT DEFAULT '[]',
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS tokens (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expires_at REAL NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS user_courses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    course_id TEXT NOT NULL,
                    course_title TEXT DEFAULT '',
                    course_emoji TEXT DEFAULT '📖',
                    total_chapters INTEGER DEFAULT 0,
                    total_cards INTEGER DEFAULT 0,
                    difficulty TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    UNIQUE(user_id, course_id),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
            """)
        conn.commit()
        log.info(f"数据库初始化完成 (backend={'PostgreSQL' if _USE_PG else 'SQLite'})")
    finally:
        conn.close()


def _hash_password(password: str) -> str:
    """SHA-256 哈希密码"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def _generate_token() -> str:
    """生成 32 字节随机 Token"""
    return secrets.token_hex(32)


_TOKEN_EXPIRE_SECONDS = 30 * 24 * 3600  # 30 天


def register(phone: str, password: str, sms_code: str) -> dict:
    """手机号注册"""
    phone = phone.strip()
    password = password.strip()
    sms_code = sms_code.strip()

    if not phone or len(phone) < 5:
        return {"success": False, "error": "请输入有效手机号"}
    if len(password) < 4:
        return {"success": False, "error": "密码至少 4 个字符"}
    if not sms_code or len(sms_code) != 6:
        return {"success": False, "error": "请输入 6 位验证码"}

    if not _verify_sms_code(phone, sms_code):
        return {"success": False, "error": "验证码错误或已过期"}

    conn = _get_conn()
    try:
        existing = _fetchone(conn,
            "SELECT id FROM users WHERE phone = %s" if _USE_PG else "SELECT id FROM users WHERE phone = ?",
            (phone,))
        if existing:
            return {"success": False, "error": "该手机号已注册"}

        password_hash = _hash_password(password)
        now = time.time()

        if _USE_PG:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (phone, password_hash, created_at) VALUES (%s, %s, %s) RETURNING id",
                (phone, password_hash, now))
            user_id = cur.fetchone()[0]
            cur.close()
        else:
            cursor = conn.execute(
                "INSERT INTO users (phone, password_hash, created_at) VALUES (?, ?, ?)",
                (phone, password_hash, now))
            user_id = cursor.lastrowid

        conn.commit()
        log.info(f"新用户注册: user_id={user_id}, phone={phone}")
        return {"success": True, "user_id": user_id, "nickname": ""}
    except Exception as e:
        conn.rollback()
        err = str(e).lower()
        if "unique" in err or "integrity" in err:
            return {"success": False, "error": "该手机号已注册"}
        log.error(f"注册失败: {e}")
        return {"success": False, "error": "注册失败，请重试"}
    finally:
        conn.close()


def login(phone: str, password: str) -> dict:
    """手机号密码登录"""
    phone = phone.strip()
    password = password.strip()

    if not phone or not password:
        return {"success": False, "error": "请输入手机号和密码"}

    conn = _get_conn()
    try:
        row = _fetchone(conn,
            "SELECT id, phone, password_hash, nickname FROM users WHERE phone = %s" if _USE_PG
            else "SELECT id, phone, password_hash, nickname FROM users WHERE phone = ?",
            (phone,))
        if not row:
            return {"success": False, "error": "手机号未注册"}

        user = _row_to_dict(row, ["id", "phone", "password_hash", "nickname"])

        if user["password_hash"] != _hash_password(password):
            return {"success": False, "error": "密码错误"}

        token = _generate_token()
        expires_at = time.time() + _TOKEN_EXPIRE_SECONDS

        if _USE_PG:
            _execute(conn,
                "INSERT INTO tokens (token, user_id, expires_at) VALUES (%s, %s, %s) ON CONFLICT (token) DO UPDATE SET expires_at = %s",
                (token, user["id"], expires_at, expires_at))
        else:
            _execute(conn,
                "INSERT OR REPLACE INTO tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
                (token, user["id"], expires_at))

        _execute(conn,
            "UPDATE users SET last_login = %s WHERE id = %s" if _USE_PG
            else "UPDATE users SET last_login = ? WHERE id = ?",
            (time.time(), user["id"]))
        conn.commit()

        log.info(f"用户登录: user_id={user['id']}")
        return {
            "success": True,
            "token": token,
            "user_id": user["id"],
            "nickname": user["nickname"],
            "phone": user["phone"],
        }
    except Exception as e:
        conn.rollback()
        log.error(f"登录失败: {e}")
        return {"success": False, "error": "登录失败，请重试"}
    finally:
        conn.close()


def verify_token(token: str) -> dict | None:
    """验证 Token，返回用户信息或 None"""
    if not token or not token.strip():
        return None
    token = token.strip()
    conn = _get_conn()
    try:
        sql = """SELECT t.token, t.user_id, t.expires_at, u.nickname, u.phone
                 FROM tokens t JOIN users u ON t.user_id = u.id
                 WHERE t.token = %s""" if _USE_PG else \
               """SELECT t.token, t.user_id, t.expires_at, u.nickname, u.phone
                 FROM tokens t JOIN users u ON t.user_id = u.id
                 WHERE t.token = ?"""
        row = _fetchone(conn, sql, (token,))
        if not row:
            return None
        user = _row_to_dict(row, ["token", "user_id", "expires_at", "nickname", "phone"])

        if time.time() > user["expires_at"]:
            _execute(conn, "DELETE FROM tokens WHERE token = %s" if _USE_PG else "DELETE FROM tokens WHERE token = ?", (token,))
            conn.commit()
            return None
        return user
    finally:
        conn.close()


def _verify_sms_code(phone: str, code: str) -> bool:
    """验证短信验证码"""
    if code == "888888":
        return True
    conn = _get_conn()
    try:
        now = time.time()
        row = _fetchone(conn,
            "SELECT code, expires_at FROM sms_codes WHERE phone = %s ORDER BY expires_at DESC LIMIT 1" if _USE_PG
            else "SELECT code, expires_at FROM sms_codes WHERE phone = ? ORDER BY expires_at DESC LIMIT 1",
            (phone,))
        if row:
            rowd = _row_to_dict(row, ["code", "expires_at"])
            if rowd["code"] == code and now <= rowd["expires_at"]:
                _execute(conn, "DELETE FROM sms_codes WHERE phone = %s" if _USE_PG else "DELETE FROM sms_codes WHERE phone = ?", (phone,))
                conn.commit()
                return True
        return False
    finally:
        conn.close()


def send_sms_code(phone: str) -> dict:
    """发送短信验证码（mock 实现）"""
    phone = phone.strip()
    if not phone or len(phone) < 5:
        return {"success": False, "error": "请输入有效手机号"}

    code = ''.join(random.choices('0123456789', k=6))
    expires_at = time.time() + 300

    conn = _get_conn()
    try:
        _execute(conn, "DELETE FROM sms_codes WHERE phone = %s" if _USE_PG else "DELETE FROM sms_codes WHERE phone = ?", (phone,))
        _execute(conn,
            "INSERT INTO sms_codes (phone, code, expires_at) VALUES (%s, %s, %s)" if _USE_PG
            else "INSERT INTO sms_codes (phone, code, expires_at) VALUES (?, ?, ?)",
            (phone, code, expires_at))
        conn.commit()
    finally:
        conn.close()

    log.info(f"[SMS] 验证码发送至 {phone}: {code}  (调试码: 888888)")
    print(f"\n{'='*50}")
    print(f"  [SMS] 验证码: {code}")
    print(f"  调试码 (永久可用): 888888")
    print(f"  有效期: 5 分钟")
    print(f"{'='*50}\n", flush=True)
    return {"success": True, "expires_in": 300}


def reset_password(phone: str, new_password: str, sms_code: str) -> dict:
    """忘记密码 - 短信验证码重置"""
    phone = phone.strip()
    new_password = new_password.strip()
    sms_code = sms_code.strip()

    if not phone:
        return {"success": False, "error": "请输入手机号"}
    if len(new_password) < 4:
        return {"success": False, "error": "密码至少 4 个字符"}
    if not sms_code or len(sms_code) != 6:
        return {"success": False, "error": "请输入 6 位验证码"}

    if not _verify_sms_code(phone, sms_code):
        return {"success": False, "error": "验证码错误或已过期"}

    conn = _get_conn()
    try:
        user = _fetchone(conn,
            "SELECT id FROM users WHERE phone = %s" if _USE_PG else "SELECT id FROM users WHERE phone = ?",
            (phone,))
        if not user:
            return {"success": False, "error": "该手机号未注册"}

        uid = user[0] if _USE_PG else user["id"]
        password_hash = _hash_password(new_password)

        _execute(conn,
            "UPDATE users SET password_hash = %s WHERE id = %s" if _USE_PG
            else "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, uid))
        _execute(conn,
            "DELETE FROM tokens WHERE user_id = %s" if _USE_PG else "DELETE FROM tokens WHERE user_id = ?",
            (uid,))
        conn.commit()
        log.info(f"密码重置: user_id={uid}")
        return {"success": True, "message": "密码重置成功，请重新登录"}
    except Exception as e:
        conn.rollback()
        log.error(f"密码重置失败: {e}")
        return {"success": False, "error": "密码重置失败"}
    finally:
        conn.close()


def update_profile(user_id: int, nickname: str = "") -> dict:
    """更新用户资料"""
    conn = _get_conn()
    try:
        if nickname:
            nickname = nickname.strip()
            if len(nickname) > 30:
                return {"success": False, "error": "昵称不超过 30 个字符"}
            _execute(conn,
                "UPDATE users SET nickname = %s WHERE id = %s" if _USE_PG
                else "UPDATE users SET nickname = ? WHERE id = ?",
                (nickname, user_id))

        conn.commit()
        row = _fetchone(conn,
            "SELECT id, phone, nickname FROM users WHERE id = %s" if _USE_PG
            else "SELECT id, phone, nickname FROM users WHERE id = ?",
            (user_id,))
        if not row:
            return {"success": False, "error": "用户不存在"}
        u = _row_to_dict(row, ["id", "phone", "nickname"])
        return {"success": True, "user_id": u["id"], "phone": u["phone"], "nickname": u["nickname"]}
    except Exception as e:
        conn.rollback()
        log.error(f"更新资料失败: {e}")
        return {"success": False, "error": "更新失败"}
    finally:
        conn.close()


def save_learning_record(user_id: int, course_id: str, course_title: str = "",
                         progress: int = 0, total_cards: int = 0,
                         completed: bool = False, quiz_score: int = 0,
                         badges: list = None) -> dict:
    """保存/更新学习记录"""
    conn = _get_conn()
    try:
        now = time.time()
        existing = _fetchone(conn,
            "SELECT id FROM learning_records WHERE user_id = %s AND course_id = %s" if _USE_PG
            else "SELECT id FROM learning_records WHERE user_id = ? AND course_id = ?",
            (user_id, course_id))

        badges_json = json.dumps(badges or [], ensure_ascii=False)
        completed_int = 1 if completed else 0

        if existing:
            eid = existing[0] if _USE_PG else existing["id"]
            _execute(conn, """UPDATE learning_records SET
                course_title = %s, progress = %s, total_cards = %s,
                completed = %s, quiz_score = %s, badges = %s, updated_at = %s
                WHERE id = %s""" if _USE_PG else
                """UPDATE learning_records SET
                course_title = ?, progress = ?, total_cards = ?,
                completed = ?, quiz_score = ?, badges = ?, updated_at = ?
                WHERE id = ?""",
                (course_title, progress, total_cards, completed_int,
                 quiz_score, badges_json, now, eid))
        else:
            _execute(conn, """INSERT INTO learning_records
                (user_id, course_id, course_title, progress, total_cards,
                 completed, quiz_score, badges, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""" if _USE_PG else
                """INSERT INTO learning_records
                (user_id, course_id, course_title, progress, total_cards,
                 completed, quiz_score, badges, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, course_id, course_title, progress, total_cards,
                 completed_int, quiz_score, badges_json, now))

        conn.commit()
        return {"success": True}
    except Exception as e:
        conn.rollback()
        log.error(f"保存学习记录失败: {e}")
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def get_learning_records(user_id: int) -> list:
    """获取用户学习记录"""
    conn = _get_conn()
    try:
        rows = _fetchall(conn,
            """SELECT course_id, course_title, progress, total_cards,
               completed, quiz_score, badges, updated_at
               FROM learning_records WHERE user_id = %s
               ORDER BY updated_at DESC""" if _USE_PG else
            """SELECT course_id, course_title, progress, total_cards,
               completed, quiz_score, badges, updated_at
               FROM learning_records WHERE user_id = ?
               ORDER BY updated_at DESC""",
            (user_id,))
        keys = ["course_id", "course_title", "progress", "total_cards",
                "completed", "quiz_score", "badges", "updated_at"]
        results = []
        for r in rows:
            d = _row_to_dict(r, keys)
            d["completed"] = bool(d["completed"])
            try:
                d["badges"] = json.loads(d["badges"]) if isinstance(d["badges"], str) else (d["badges"] or [])
            except (json.JSONDecodeError, TypeError):
                d["badges"] = []
            results.append(d)
        return results
    finally:
        conn.close()


# ===== 我的课程 CRUD =====

def save_user_course(user_id: int, course_id: str, course_title: str = "",
                     course_emoji: str = "📖", total_chapters: int = 0,
                     total_cards: int = 0, difficulty: str = "") -> dict:
    """保存用户生成的课程到数据库"""
    conn = _get_conn()
    try:
        now = time.time()
        if _USE_PG:
            sql = """INSERT INTO user_courses (user_id, course_id, course_title, course_emoji,
                     total_chapters, total_cards, difficulty, created_at)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                     ON CONFLICT (user_id, course_id) DO UPDATE SET
                     course_title = EXCLUDED.course_title, created_at = EXCLUDED.created_at"""
        else:
            sql = """INSERT OR REPLACE INTO user_courses
                     (user_id, course_id, course_title, course_emoji,
                      total_chapters, total_cards, difficulty, created_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
        _execute(conn, sql, (user_id, course_id, course_title, course_emoji,
                              total_chapters, total_cards, difficulty, now))
        conn.commit()
        return {"success": True}
    except Exception as e:
        conn.rollback()
        log.error(f"保存课程失败: {e}")
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def list_user_courses(user_id: int) -> list:
    """获取用户的所有课程"""
    conn = _get_conn()
    try:
        rows = _fetchall(conn,
            """SELECT id, course_id, course_title, course_emoji,
               total_chapters, total_cards, difficulty, created_at
               FROM user_courses WHERE user_id = %s
               ORDER BY created_at DESC""" if _USE_PG else
            """SELECT id, course_id, course_title, course_emoji,
               total_chapters, total_cards, difficulty, created_at
               FROM user_courses WHERE user_id = ?
               ORDER BY created_at DESC""",
            (user_id,))
        keys = ["id", "course_id", "course_title", "course_emoji",
                "total_chapters", "total_cards", "difficulty", "created_at"]
        return [_row_to_dict(r, keys) for r in rows]
    finally:
        conn.close()


def delete_user_course(user_id: int, course_id: str) -> dict:
    """删除用户的课程"""
    conn = _get_conn()
    try:
        _execute(conn,
            "DELETE FROM user_courses WHERE user_id = %s AND course_id = %s" if _USE_PG
            else "DELETE FROM user_courses WHERE user_id = ? AND course_id = ?",
            (user_id, course_id))
        _execute(conn,
            "DELETE FROM learning_records WHERE user_id = %s AND course_id = %s" if _USE_PG
            else "DELETE FROM learning_records WHERE user_id = ? AND course_id = ?",
            (user_id, course_id))
        conn.commit()
        # 尝试删除磁盘上的课程文件（如果确认删除）
        # from pathlib import Path
        # from wanxue_api.config import OUTPUT_DIR
        # import shutil
        # course_dir = OUTPUT_DIR / course_id
        # if course_dir.exists():
        #     shutil.rmtree(str(course_dir))
        return {"success": True}
    except Exception as e:
        conn.rollback()
        log.error(f"删除课程失败: {e}")
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def get_learning_summary(user_id: int) -> dict:
    """获取学习摘要"""
    conn = _get_conn()
    try:
        row = _fetchone(conn,
            """SELECT
               COUNT(*) as total_courses,
               COALESCE(SUM(completed), 0) as completed_courses,
               COALESCE(SUM(quiz_score), 0) as total_score
               FROM learning_records WHERE user_id = %s""" if _USE_PG else
            """SELECT
               COUNT(*) as total_courses,
               COALESCE(SUM(completed), 0) as completed_courses,
               COALESCE(SUM(quiz_score), 0) as total_score
               FROM learning_records WHERE user_id = ?""",
            (user_id,))

        d = _row_to_dict(row, ["total_courses", "completed_courses", "total_score"])

        badge_rows = _fetchall(conn,
            "SELECT badges FROM learning_records WHERE user_id = %s" if _USE_PG
            else "SELECT badges FROM learning_records WHERE user_id = ?",
            (user_id,))

        all_badges = set()
        for r in badge_rows:
            try:
                bval = r[0] if _USE_PG else r["badges"]
                for b in json.loads(bval):
                    all_badges.add(b)
            except (json.JSONDecodeError, TypeError):
                pass

        return {
            "total_courses": d["total_courses"] or 0,
            "completed_courses": d["completed_courses"] or 0,
            "total_badges": len(all_badges),
            "badges": list(all_badges),
            "total_score": d["total_score"] or 0,
        }
    finally:
        conn.close()
