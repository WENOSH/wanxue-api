"""WanXue 用户认证与学习记录模块"""
import sqlite3, hashlib, secrets, json, logging, time, random
from pathlib import Path

DB_PATH = Path(__file__).parent / "wanxue_users.db"
log = logging.getLogger("wanxue.auth")


def _get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """初始化数据库表"""
    conn = _get_db()
    conn.executescript("""
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
    """)
    conn.commit()
    conn.close()
    log.info("数据库初始化完成")


def _hash_password(password: str) -> str:
    """SHA-256 哈希密码"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def _generate_token() -> str:
    """生成 32 字节随机 Token"""
    return secrets.token_hex(32)


_TOKEN_EXPIRE_SECONDS = 30 * 24 * 3600  # 30 天


def register(phone: str, password: str, sms_code: str) -> dict:
    """手机号注册

    验证短信验证码（mock: code 为 "888888" 自动通过）
    返回: {"success": True, "user_id": 1, "nickname": ""} 或 {"success": False, "error": "..."}
    """
    phone = phone.strip()
    password = password.strip()
    sms_code = sms_code.strip()

    if not phone or len(phone) < 5:
        return {"success": False, "error": "请输入有效手机号"}
    if len(password) < 4:
        return {"success": False, "error": "密码至少 4 个字符"}
    if not sms_code or len(sms_code) != 6:
        return {"success": False, "error": "请输入 6 位验证码"}

    # 验证短信验证码
    if not _verify_sms_code(phone, sms_code):
        return {"success": False, "error": "验证码错误或已过期"}

    conn = _get_db()
    try:
        # 检查手机号是否已注册
        existing = conn.execute("SELECT id FROM users WHERE phone = ?", (phone,)).fetchone()
        if existing:
            return {"success": False, "error": "该手机号已注册"}

        password_hash = _hash_password(password)
        now = time.time()
        cursor = conn.execute(
            "INSERT INTO users (phone, password_hash, created_at) VALUES (?, ?, ?)",
            (phone, password_hash, now)
        )
        user_id = cursor.lastrowid
        conn.commit()
        log.info(f"新用户注册: user_id={user_id}, phone={phone}")
        return {"success": True, "user_id": user_id, "nickname": ""}
    except sqlite3.IntegrityError:
        return {"success": False, "error": "该手机号已注册"}
    finally:
        conn.close()


def login(phone: str, password: str) -> dict:
    """手机号密码登录

    返回: {"success": True, "token": "xxx", "user_id": 1, "nickname": "xxx"} 或 {"success": False, "error": "..."}
    """
    phone = phone.strip()
    password = password.strip()

    if not phone or not password:
        return {"success": False, "error": "请输入手机号和密码"}

    conn = _get_db()
    try:
        user = conn.execute(
            "SELECT id, phone, password_hash, nickname FROM users WHERE phone = ?",
            (phone,)
        ).fetchone()
        if not user:
            return {"success": False, "error": "手机号未注册"}

        if user["password_hash"] != _hash_password(password):
            return {"success": False, "error": "密码错误"}

        # 生成 Token
        token = _generate_token()
        expires_at = time.time() + _TOKEN_EXPIRE_SECONDS
        conn.execute(
            "INSERT OR REPLACE INTO tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user["id"], expires_at)
        )
        # 更新最后登录时间
        conn.execute("UPDATE users SET last_login = ? WHERE id = ?",
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
    finally:
        conn.close()


def verify_token(token: str) -> dict | None:
    """验证 Token，返回用户信息或 None"""
    if not token or not token.strip():
        return None
    token = token.strip()
    conn = _get_db()
    try:
        row = conn.execute("""
            SELECT t.token, t.user_id, t.expires_at, u.nickname, u.phone
            FROM tokens t JOIN users u ON t.user_id = u.id
            WHERE t.token = ?
        """, (token,)).fetchone()
        if not row:
            return None
        if time.time() > row["expires_at"]:
            conn.execute("DELETE FROM tokens WHERE token = ?", (token,))
            conn.commit()
            return None
        return {
            "token": row["token"],
            "user_id": row["user_id"],
            "nickname": row["nickname"],
            "phone": row["phone"],
        }
    finally:
        conn.close()


def _verify_sms_code(phone: str, code: str) -> bool:
    """验证短信验证码"""
    # 调试码 "888888" 永久可用
    if code == "888888":
        return True
    conn = _get_db()
    try:
        now = time.time()
        row = conn.execute(
            "SELECT code, expires_at FROM sms_codes WHERE phone = ? ORDER BY expires_at DESC LIMIT 1",
            (phone,)
        ).fetchone()
        if row and row["code"] == code and now <= row["expires_at"]:
            # 使用后删除
            conn.execute("DELETE FROM sms_codes WHERE phone = ?", (phone,))
            conn.commit()
            return True
        return False
    finally:
        conn.close()


def send_sms_code(phone: str) -> dict:
    """发送短信验证码（mock 实现，打印到控制台）

    Mock: 生成 6 位随机码，打印到日志，同时在控制台输出
    调试验证码固定为 "888888" 方便测试
    返回: {"success": True, "expires_in": 300}
    """
    phone = phone.strip()
    if not phone or len(phone) < 5:
        return {"success": False, "error": "请输入有效手机号"}

    # 生成 6 位随机码
    code = ''.join(random.choices('0123456789', k=6))

    expires_at = time.time() + 300  # 5 分钟有效期

    conn = _get_db()
    try:
        # 删除旧的验证码
        conn.execute("DELETE FROM sms_codes WHERE phone = ?", (phone,))
        conn.execute(
            "INSERT INTO sms_codes (phone, code, expires_at) VALUES (?, ?, ?)",
            (phone, code, expires_at)
        )
        conn.commit()
    finally:
        conn.close()

    # 打印验证码到控制台和日志
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

    conn = _get_db()
    try:
        user = conn.execute("SELECT id FROM users WHERE phone = ?", (phone,)).fetchone()
        if not user:
            return {"success": False, "error": "该手机号未注册"}

        password_hash = _hash_password(new_password)
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                     (password_hash, user["id"]))
        # 使所有 Token 过期
        conn.execute("DELETE FROM tokens WHERE user_id = ?", (user["id"],))
        conn.commit()
        log.info(f"密码重置: user_id={user['id']}")
        return {"success": True, "message": "密码重置成功，请重新登录"}
    finally:
        conn.close()


def update_profile(user_id: int, nickname: str = "") -> dict:
    """更新用户资料"""
    conn = _get_db()
    try:
        if nickname:
            nickname = nickname.strip()
            if len(nickname) > 30:
                return {"success": False, "error": "昵称不超过 30 个字符"}
            conn.execute("UPDATE users SET nickname = ? WHERE id = ?",
                         (nickname, user_id))
        conn.commit()
        user = conn.execute(
            "SELECT id, phone, nickname FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        if not user:
            return {"success": False, "error": "用户不存在"}
        return {
            "success": True,
            "user_id": user["id"],
            "phone": user["phone"],
            "nickname": user["nickname"],
        }
    finally:
        conn.close()


def save_learning_record(user_id: int, course_id: str, course_title: str = "",
                         progress: int = 0, total_cards: int = 0,
                         completed: bool = False, quiz_score: int = 0,
                         badges: list = None) -> dict:
    """保存/更新学习记录"""
    conn = _get_db()
    try:
        now = time.time()
        existing = conn.execute(
            "SELECT id FROM learning_records WHERE user_id = ? AND course_id = ?",
            (user_id, course_id)
        ).fetchone()

        badges_json = json.dumps(badges or [], ensure_ascii=False)
        completed_int = 1 if completed else 0

        if existing:
            conn.execute("""
                UPDATE learning_records SET
                    course_title = ?, progress = ?, total_cards = ?,
                    completed = ?, quiz_score = ?, badges = ?, updated_at = ?
                WHERE id = ?
            """, (course_title, progress, total_cards, completed_int,
                  quiz_score, badges_json, now, existing["id"]))
        else:
            conn.execute("""
                INSERT INTO learning_records
                    (user_id, course_id, course_title, progress, total_cards,
                     completed, quiz_score, badges, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, course_id, course_title, progress, total_cards,
                  completed_int, quiz_score, badges_json, now))

        conn.commit()
        return {"success": True}
    finally:
        conn.close()


def get_learning_records(user_id: int) -> list:
    """获取用户学习记录"""
    conn = _get_db()
    try:
        rows = conn.execute("""
            SELECT course_id, course_title, progress, total_cards,
                   completed, quiz_score, badges, updated_at
            FROM learning_records
            WHERE user_id = ?
            ORDER BY updated_at DESC
        """, (user_id,)).fetchall()
        results = []
        for r in rows:
            results.append({
                "course_id": r["course_id"],
                "course_title": r["course_title"],
                "progress": r["progress"],
                "total_cards": r["total_cards"],
                "completed": bool(r["completed"]),
                "quiz_score": r["quiz_score"],
                "badges": json.loads(r["badges"]),
                "updated_at": r["updated_at"],
            })
        return results
    finally:
        conn.close()


def get_learning_summary(user_id: int) -> dict:
    """获取学习摘要（总课程数、完成数、总徽章、总得分）"""
    conn = _get_db()
    try:
        row = conn.execute("""
            SELECT
                COUNT(*) as total_courses,
                SUM(completed) as completed_courses,
                COALESCE(SUM(quiz_score), 0) as total_score
            FROM learning_records
            WHERE user_id = ?
        """, (user_id,)).fetchone()

        # 收集所有徽章
        badge_rows = conn.execute(
            "SELECT badges FROM learning_records WHERE user_id = ?",
            (user_id,)
        ).fetchall()

        all_badges = set()
        for r in badge_rows:
            try:
                for b in json.loads(r["badges"]):
                    all_badges.add(b)
            except (json.JSONDecodeError, TypeError):
                pass

        return {
            "total_courses": row["total_courses"] or 0,
            "completed_courses": row["completed_courses"] or 0,
            "total_badges": len(all_badges),
            "badges": list(all_badges),
            "total_score": row["total_score"] or 0,
        }
    finally:
        conn.close()
