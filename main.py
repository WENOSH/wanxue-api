"""WanXue API — FastAPI 服务入口"""

import sys
import importlib.util
from pathlib import Path

# ── 包引导：确保 wanxue_api 包可被正确导入 ────────
# 目录名含连字符无法直接作为 Python 包名，
# 因此用 importlib 手动注册包到 sys.modules，
# 让 engine.py / prompts.py 中的相对导入能正常工作。
_PKG_NAME = "wanxue_api"
_THIS_DIR = Path(__file__).resolve().parent

if _PKG_NAME not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        _PKG_NAME,
        str(_THIS_DIR / "__init__.py"),
        submodule_search_locations=[str(_THIS_DIR)],
    )
    _pkg = importlib.util.module_from_spec(_spec)
    sys.modules[_PKG_NAME] = _pkg
    _spec.loader.exec_module(_pkg)

# ── 标准库 / 第三方 ──────────────────────────────
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
from fastapi import Header
import json, logging, time

# ── 本地模块（通过注册的包导入，相对导入可正常工作）──
from wanxue_api.engine import WanXueEngine
from wanxue_api.config import HOST, PORT, OUTPUT_DIR, STATIC_DIR
from wanxue_api import chat as chat_module
from wanxue_api import prompts

# renderer 由 renderer-dev 提供，尚未就绪时降级
try:
    from wanxue_api.renderer import render_html as _render_html
except ImportError:
    _render_html = None

log = logging.getLogger("wanxue.api")

# ── App ───────────────────────────────────────────
app = FastAPI(title="WanXue API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = WanXueEngine()

# ── 用户认证 ──────────────────────────────────────
from wanxue_api.user_auth import (
    init_db, register, login, verify_token, send_sms_code,
    reset_password, update_profile, save_learning_record,
    get_learning_records, get_learning_summary
)


@app.on_event("startup")
async def startup_auth():
    init_db()

# 确保输出目录存在
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)


# ── Models ────────────────────────────────────────
class GenerateRequest(BaseModel):
    topic: str
    age: str = "成人"
    goal: str = "入门科普"
    difficulty: str = "3-标准"  # 1-入门 / 2-基础 / 3-标准 / 4-进阶 / 5-挑战


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    difficulty: Optional[str] = None  # 用户选择的难度等级


class BindCourseRequest(BaseModel):
    session_id: str
    course: dict  # 客户端把 generate-course 返回的 course 绑到会话上


class StabilityTestRequest(BaseModel):
    topics: list[str] | None = None
    rounds: int = 1
    concurrency: int = 8
    quality_check: bool = True


# ── Auth Models ────────────────────────────────────
class AuthSendCodeRequest(BaseModel):
    phone: str


class AuthRegisterRequest(BaseModel):
    phone: str
    password: str
    sms_code: str


class AuthLoginRequest(BaseModel):
    phone: str
    password: str


class AuthResetPasswordRequest(BaseModel):
    phone: str
    new_password: str
    sms_code: str


class AuthProfileRequest(BaseModel):
    nickname: str = ""


class SaveLearningRecordRequest(BaseModel):
    course_id: str
    course_title: str = ""
    progress: int = 0
    total_cards: int = 0
    completed: bool = False
    quiz_score: int = 0
    badges: list = []


# ── Routes ────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/generate-course")
async def generate_course(req: GenerateRequest):
    log.info(f"生成课程请求: topic={req.topic}, age={req.age}, goal={req.goal}")

    # 1. 调用引擎生成课程数据
    course = await engine.generate_course(
        topic=req.topic, age=req.age, goal=req.goal, difficulty=req.difficulty
    )

    course_id = course.get("_course_id", WanXueEngine._slugify(req.topic))
    course_dir = OUTPUT_DIR / course_id
    course_dir.mkdir(parents=True, exist_ok=True)

    # 2. 渲染 HTML
    if _render_html is not None:
        html_content = _render_html(course)
    else:
        html_content = _fallback_html(course)

    # 3. 保存文件
    clean_html = html_content.encode('utf-8', errors='surrogatepass').decode('utf-8', errors='replace')
    (course_dir / "index.html").write_text(clean_html, encoding="utf-8")
    course_json = json.dumps(course, ensure_ascii=False, indent=2)
    course_json_clean = course_json.encode('utf-8', errors='surrogatepass').decode('utf-8', errors='replace')
    (course_dir / "course.json").write_text(course_json_clean, encoding="utf-8")

    log.info(f"课程已保存: {course_id}")

    return {
        "success": True,
        "course": course,
        "html_url": f"/api/courses/{course_id}/index.html",
        "course_id": course_id,
    }


@app.get("/api/courses")
async def list_courses():
    courses = []
    if not OUTPUT_DIR.exists():
        return {"courses": courses}

    for d in sorted(OUTPUT_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        meta_file = d / "course.json"
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            stat = meta_file.stat()
            courses.append({
                "course_id": d.name,
                "title": meta.get("course_title", d.name),
                "created_at": time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)
                ),
                "url": f"/api/courses/{d.name}/index.html",
            })
        except Exception:
            continue

    return {"courses": courses}


@app.get("/api/courses/{course_id}/index.html", response_class=HTMLResponse)
async def get_course_html(course_id: str):
    html_path = OUTPUT_DIR / course_id / "index.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="课程未找到")
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


# ── 分享与预览端点 ──────────────────────────────

@app.get("/api/courses/{course_id}/preview")
async def get_course_preview(course_id: str):
    """获取课程预览（前2张卡片 + 元数据），用于分享"""
    meta_path = OUTPUT_DIR / course_id / "course.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="课程未找到")
    course = json.loads(meta_path.read_text(encoding="utf-8"))
    chapters = course.get("chapters", [])
    preview = {
        "course_id": course_id,
        "course_title": course.get("course_title", ""),
        "course_emoji": course.get("course_emoji", ""),
        "course_subtitle": course.get("course_subtitle", ""),
        "total_chapters": len(chapters),
        "total_cards": course.get("_total_cards", 0),
        "preview_cards": [],
        "full_version_available": True,
    }
    # 取前 2 张卡片
    if chapters:
        for ch in chapters[:1]:  # 只取第1章
            for card in ch.get("cards", [])[:2]:  # 取前2张卡片
                preview["preview_cards"].append({
                    "type": card.get("type", ""),
                    "title": card.get("title", ""),
                    "body": card.get("body", ""),
                })
    return preview


@app.get("/api/share/{course_id}")
async def get_share_link(course_id: str):
    """生成课程分享链接"""
    meta_path = OUTPUT_DIR / course_id / "course.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="课程未找到")
    course = json.loads(meta_path.read_text(encoding="utf-8"))
    return {
        "share_url": f"/share/{course_id}",
        "title": course.get("course_title", ""),
        "emoji": course.get("course_emoji", ""),
    }


@app.get("/share/{course_id}", response_class=HTMLResponse)
async def share_course_page(course_id: str):
    """分享落地页 — 预览前几张卡片 + 下载引导"""
    meta_path = OUTPUT_DIR / course_id / "course.json"
    if not meta_path.exists():
        return HTMLResponse(content="""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>课程未找到 - WanXue 万学</title>
<style>body{font-family:system-ui;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#fff8e7;color:#2d3047;text-align:center;padding:20px}h1{font-size:24px;margin-bottom:8px}p{color:#6c6f7d}.btn{display:inline-block;margin-top:16px;padding:12px 24px;background:#ff6b6b;color:#fff;border-radius:10px;text-decoration:none;font-weight:700}</style>
</head><body><div><h1>😕 课程未找到</h1><p>这个分享链接可能已过期或课程已被删除</p><a class="btn" href="/static/app.html">前往 WanXue</a></div></body></html>""")

    course = json.loads(meta_path.read_text(encoding="utf-8"))
    chapters = course.get("chapters", [])
    title = course.get("course_title", "")
    emoji = course.get("course_emoji", "📖")
    subtitle = course.get("course_subtitle", "")
    total_cards = course.get("_total_cards", 0)
    total_chapters = len(chapters)

    # 取前 2 张卡片
    preview_cards = []
    if chapters:
        for ch in chapters[:1]:
            for card in ch.get("cards", [])[:2]:
                preview_cards.append({
                    "type": card.get("type", ""),
                    "title": card.get("title", ""),
                    "body": card.get("body", ""),
                })

    # 渲染卡片HTML
    cards_html = ""
    for i, card in enumerate(preview_cards):
        visible = "active" if i == 0 else ""
        cards_html += f"""<div class="share-card {visible}" data-index="{i}">
          <div class="card-badge">{card.get('type', 'card')}</div>
          <h3 class="card-title">{card.get('title', '')}</h3>
          <div class="card-body">{card.get('body', '')}</div>
        </div>"""

    # 如果不足2张卡片，加一个空的占位
    if len(preview_cards) < 1:
        cards_html = """<div class="share-card active"><div class="card-body" style="text-align:center;padding:40px 0">暂无预览内容</div></div>"""

    # 翻页导航（如果有2张卡片）
    pagination_html = ""
    if len(preview_cards) > 1:
        pagination_html = f"""<div class="card-nav">
          <button class="nav-btn" id="prevBtn" onclick="changeCard(-1)" disabled>‹</button>
          <span class="nav-dots" id="navDots">
            {"".join(f'<span class="dot {"active" if i==0 else ""}"></span>' for i in range(len(preview_cards)))}
          </span>
          <button class="nav-btn" id="nextBtn" onclick="changeCard(1)">›</button>
        </div>"""

    remaining = total_cards - len(preview_cards)
    remaining_text = f"全 {total_cards} 张卡片" if remaining <= 0 else f"全 {total_cards} 张卡片（还有 {remaining} 张）"

    return HTMLResponse(content=f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="description" content="WanXue 万学 - {title}">
<meta name="theme-color" content="#fff8e7">
<title>{emoji} {title} - WanXue 万学</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", Arial, sans-serif;
    background: #fff8e7; color: #2d3047; line-height: 1.6; min-height: 100vh;
    display: flex; flex-direction: column;
  }}
  .container {{ max-width: 480px; margin: 0 auto; width: 100%; flex: 1; display: flex; flex-direction: column; }}

  /* ===== Header ===== */
  .share-header {{
    text-align: center; padding: 32px 20px 24px; position: relative;
    background: linear-gradient(180deg, #fff8e7 0%, rgba(255,230,109,0.15) 100%);
  }}
  .share-header .course-emoji {{ font-size: 48px; display: block; margin-bottom: 12px; }}
  .share-header h1 {{ font-size: 22px; font-weight: 800; color: #2d3047; margin-bottom: 6px; }}
  .share-header .subtitle {{ font-size: 14px; color: #6c6f7d; margin-bottom: 8px; }}
  .share-header .meta {{ font-size: 12px; color: #9a9dad; }}
  .share-header .meta span {{ margin: 0 6px; }}

  /* ===== Card Preview ===== */
  .card-area {{ flex: 1; padding: 0 16px; display: flex; flex-direction: column; }}
  .card-stack {{ position: relative; flex: 1; min-height: 280px; margin-bottom: 12px; }}
  .share-card {{
    position: absolute; top: 0; left: 0; right: 0;
    background: #ffffff; border-radius: 16px; padding: 20px;
    box-shadow: 0 4px 16px rgba(45,48,71,0.08);
    border: 1px solid #f0e8d5;
    opacity: 0; transform: translateX(30px) scale(0.96);
    transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
    pointer-events: none;
  }}
  .share-card.active {{
    opacity: 1; transform: translateX(0) scale(1);
    pointer-events: auto; position: relative;
  }}
  .share-card .card-badge {{
    display: inline-block; padding: 3px 10px; border-radius: 6px;
    font-size: 11px; font-weight: 700; margin-bottom: 10px;
    background: #4ecdc4; color: #fff;
  }}
  .share-card .card-title {{ font-size: 17px; font-weight: 700; margin-bottom: 10px; color: #2d3047; }}
  .share-card .card-body {{ font-size: 14px; color: #6c6f7d; line-height: 1.7; }}
  .share-card .card-body p {{ margin-bottom: 8px; }}
  .share-card .card-body ul {{ padding-left: 18px; margin-bottom: 8px; }}
  .share-card .card-body li {{ margin-bottom: 4px; }}

  /* ===== Pagination ===== */
  .card-nav {{
    display: flex; align-items: center; justify-content: center; gap: 16px;
    padding: 8px 0 16px;
  }}
  .nav-btn {{
    width: 40px; height: 40px; border-radius: 50%; border: 1.5px solid #f0e8d5;
    background: #ffffff; color: #2d3047; font-size: 20px; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    transition: all 0.2s; font-family: inherit;
  }}
  .nav-btn:active {{ background: #fff8e7; transform: scale(0.92); }}
  .nav-btn:disabled {{ opacity: 0.3; cursor: not-allowed; }}
  .nav-dots {{ display: flex; gap: 8px; }}
  .nav-dots .dot {{
    width: 8px; height: 8px; border-radius: 50%; background: #f0e8d5; transition: all 0.25s;
  }}
  .nav-dots .dot.active {{ background: #ff6b6b; width: 20px; border-radius: 4px; }}

  /* ===== Paywall ===== */
  .paywall {{
    margin: 0 16px 20px; padding: 24px 20px;
    background: linear-gradient(135deg, #2d3047 0%, #3d4057 100%);
    border-radius: 16px; text-align: center; color: #fff;
    position: relative; overflow: hidden;
  }}
  .paywall::before {{
    content: ''; position: absolute; top: -50%; left: -50%; width: 200%; height: 200%;
    background: radial-gradient(circle at 30% 30%, rgba(255,107,107,0.15) 0%, transparent 50%);
  }}
  .paywall .lock-icon {{ font-size: 36px; display: block; margin-bottom: 8px; position: relative; }}
  .paywall h2 {{ font-size: 18px; font-weight: 800; margin-bottom: 6px; position: relative; }}
  .paywall p {{ font-size: 13px; color: rgba(255,255,255,0.7); margin-bottom: 16px; position: relative; }}
  .paywall .btn-download {{
    display: inline-flex; align-items: center; gap: 8px;
    padding: 14px 28px; border: none; border-radius: 12px;
    background: linear-gradient(135deg, #ff6b6b, #ff8a65);
    color: #fff; font-size: 16px; font-weight: 700; cursor: pointer;
    text-decoration: none; transition: transform 0.15s; position: relative;
    font-family: inherit;
  }}
  .paywall .btn-download:active {{ transform: scale(0.96); }}

  /* ===== Footer ===== */
  .share-footer {{
    text-align: center; padding: 16px 20px 24px; font-size: 12px; color: #9a9dad;
  }}
  .share-footer .brand {{ font-weight: 700; color: #4ecdc4; }}
</style>
</head>
<body>
<div class="container">
  <div class="share-header">
    <span class="course-emoji">{emoji}</span>
    <h1>{title}</h1>
    <div class="subtitle">{subtitle}</div>
    <div class="meta">
      <span>📚 {total_chapters} 章</span>
      <span>🃏 {total_cards} 张卡片</span>
    </div>
  </div>

  <div class="card-area">
    <div class="card-stack">
      {cards_html}
    </div>
    {pagination_html}
  </div>

  <div class="paywall">
    <span class="lock-icon">🔒</span>
    <h2>已解锁 2 / {total_cards} 张卡片</h2>
    <p>下载 WanXue APP 继续学习{remaining_text}</p>
    <a class="btn-download" href="/static/app.html">
      📲 下载 WanXue 万学
    </a>
  </div>

  <div class="share-footer">
    由 <span class="brand">WanXue 万学</span> 生成 · 对话式结构化学习
  </div>
</div>

<script>
(function() {{
  'use strict';
  var cards = document.querySelectorAll('.share-card');
  var current = 0;
  window.changeCard = function(dir) {{
    var next = current + dir;
    if (next < 0 || next >= cards.length) return;
    cards[current].classList.remove('active');
    cards[next].classList.add('active');
    current = next;
    var prevBtn = document.getElementById('prevBtn');
    var nextBtn = document.getElementById('nextBtn');
    if (prevBtn) prevBtn.disabled = current === 0;
    if (nextBtn) nextBtn.disabled = current === cards.length - 1;
    // 更新 dots
    var dots = document.querySelectorAll('.nav-dots .dot');
    dots.forEach(function(d, i) {{
      d.classList.toggle('active', i === current);
    }});
  }};
}})();
</script>
</body>
</html>""")



# ── 对话式学习端点 (2026-06-13 新增) ──────────────────
from fastapi.responses import StreamingResponse


@app.post("/api/chat/session")
async def chat_create_session():
    """创建新会话"""
    chat_module.cleanup_sessions()
    s = chat_module.create_session()
    return {
        "session_id": s.session_id,
        "welcome": prompts.WELCOME_GUIDE if hasattr(prompts, "WELCOME_GUIDE") else "你好！请告诉我你想学什么～",
    }


@app.get("/api/chat/session/{session_id}")
async def chat_get_session(session_id: str):
    """获取会话状态"""
    s = chat_module.get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    return {
        "session_id": s.session_id,
        "history": s.history,
        "has_course": s.current_course is not None,
        "course_title": s.current_course.get("course_title", "") if s.current_course else "",
        "total_cards": s.current_course.get("_total_cards", 0) if s.current_course else 0,
        "user_profile": s.user_profile,
    }


@app.post("/api/chat/bind-course")
async def chat_bind_course(req: BindCourseRequest):
    """把已生成的课程绑定到会话上下文中（让对话能引用它）"""
    s = chat_module.get_session(req.session_id)
    if not s:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    s.current_course = req.course
    s.add_msg("system", f"已加载课程《{req.course.get('course_title', '?')}》共 {req.course.get('_total_cards', 0)} 卡片", role="system")
    return {"ok": True, "course_title": s.current_course.get("course_title", "")}


@app.post("/api/chat")
async def chat_message(req: ChatRequest):
    """对话主端点 - SSE 流式响应

    客户端用 EventSource 接收，事件类型：
    - guide: AI 引导回复
    - thinking: 正在思考
    - card_delta/card_done: 单卡流式
    - course_done: 整课完成
    - error: 错误
    """
    from wanxue_api import chat as _c
    sid = req.session_id
    if sid:
        s = _c.get_session(sid)
        if not s:
            s = _c.create_session()
    else:
        s = _c.create_session()

    async def event_gen():
        try:
            yield f"event: meta\ndata: {json.dumps({'session_id': s.session_id})}\n\n"
            # 如果客户端传了 difficulty，设置到 session.user_profile
            if req.difficulty and req.difficulty in ["1-入门","2-基础","3-标准","4-进阶","5-挑战"]:
                s.user_profile["difficulty_level"] = req.difficulty
            async for ev in _c.handle_user_message(req.message, s):
                yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'], ensure_ascii=False)}\n\n"
            yield "event: done\ndata: {}\n\n"
        except Exception as e:
            log.exception("Chat SSE failed")
            yield f"event: error\ndata: {json.dumps(str(e), ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/_admin/stability-test")
async def stability_test(req: StabilityTestRequest = StabilityTestRequest()):
    """
    稳定性测试 - N 主题 × M 并发 × K 轮
    quality_check=True 时同步输出每个课程的质量分

    返回测试结果摘要（完整报告写到 output/stability_test_report.json）
    """
    topics = req.topics
    rounds = req.rounds
    concurrency = req.concurrency
    quality_check = req.quality_check
    import asyncio as _asyncio
    import statistics
    from dataclasses import dataclass as _dc
    import re as _re
    from statistics import mean as _mean

    @_dc
    class _R:
        topic: str; round: int; status: int = 0
        elapsed: float = 0.0; cards: int = 0; error: str = ""
        quality: int = 0; grade: str = ""

    BATCH1 = [
        "光合作用", "血液循环", "DNA复制", "牛顿第二定律", "氧化还原反应",
        "中国古代史", "欧洲文艺复兴", "工业革命", "冷战时期", "一带一路",
        "俯卧撑训练", "瑜伽基础", "营养学入门", "心理学导论", "冥想入门",
        "C++编程", "JavaScript基础", "数据结构", "算法分析", "Linux命令",
        "摄影构图", "油画入门", "钢琴基础", "围棋规则", "象棋残局",
        "市场营销", "财务报表分析", "管理学原理", "供应链管理", "商业模式",
    ]
    REPEAT = ["光合作用", "C++编程", "俯卧撑训练", "摄影构图", "供应链管理"]

    if topics:
        # 用自定义主题，但保持三批架构：自定义 / 重复
        BATCH1 = topics[:30] if len(topics) >= 30 else topics
        REPEAT = topics[:5] if len(topics) >= 5 else topics

    def _quality_score(course):
        """5维度快速打分（结构/教学法/互动/表达/事实）"""
        REQUIRED = {"scene", "concept", "funfact", "meta", "explore", "quiz", "reward"}
        ABSOLUTE = [r"科学研究表明", r"科学家发现", r"专家表示", r"根据最新研究",
                    r"绝对", r"一定", r"肯定"]
        chapters = course.get("chapters", [])
        n_ch = len(chapters)
        n_cards = sum(len(c.get("cards", [])) for c in chapters)
        types = {c.get("type") for ch in chapters for c in ch.get("cards", [])}
        # 1. 结构
        s1 = 0
        if n_ch == 5: s1 += 10
        elif n_ch >= 4: s1 += 5
        if 30 <= n_cards <= 40: s1 += 10
        elif n_cards >= 20: s1 += 4
        if REQUIRED.issubset(types): s1 += 10
        elif len(types & REQUIRED) >= 5: s1 += 5
        # 2. 教学法
        full = sum(1 for ch in chapters
                   if REQUIRED.issubset({c.get("type") for c in ch.get("cards", [])}))
        s2 = int(full / max(len(chapters), 1) * 20)
        # 3. 互动
        quiz = [c for ch in chapters for c in ch.get("cards", []) if c.get("type") == "quiz"]
        if quiz:
            g = sum(1 for c in quiz if "game-box" in c.get("body", ""))
            f = sum(1 for c in quiz if "data-good" in c.get("body", ""))
            s3 = int(g / len(quiz) * 7) + int(f / len(quiz) * 8)
        else:
            s3 = 0
        # 4. 表达
        bodies = [c.get("body", "") for ch in chapters for c in ch.get("cards", [])]
        text = " ".join(bodies)
        sents = [s for s in _re.split(r"[。!?]", text) if len(s.strip()) > 5]
        avg_len = _mean(len(s) for s in sents) if sents else 0
        emojis = sum(1 for c in text if ord(c) > 0x1F000)
        s4 = 0
        if 15 <= avg_len <= 40: s4 += 8
        elif 10 <= avg_len < 15 or 40 < avg_len <= 60: s4 += 5
        if emojis >= 50: s4 += 6
        elif emojis >= 30: s4 += 4
        s4 += 6  # 标题项默认给满
        # 5. 事实
        abs_hits = sum(len(_re.findall(p, text)) for p in ABSOLUTE)
        cau_hits = sum(len(_re.findall(p, text)) for p in
                       [r"目前认为", r"主流观点", r"可能", r"大约", r"约"])
        s5 = 15
        if abs_hits >= 5: s5 -= 5
        elif abs_hits >= 2: s5 -= 2
        if cau_hits < 2: s5 -= 3
        s5 = max(s5, 0)
        return s1 + s2 + s3 + s4 + s5

    def _grade(s):
        if s >= 90: return "A"
        if s >= 80: return "B"
        if s >= 70: return "C"
        if s >= 60: return "D"
        return "F"

    async def _call(topic, rnd):
        r = _R(topic=topic, round=rnd)
        t0 = time.time()
        try:
            course = await engine.generate_course(topic=topic, age="大学", goal="入门到应用")
            r.elapsed = time.time() - t0
            r.status = 200
            r.cards = course.get("_total_cards", 0)
            if quality_check:
                r.quality = _quality_score(course)
                r.grade = _grade(r.quality)
        except Exception as e:
            r.elapsed = time.time() - t0
            r.status = 500
            r.error = f"{type(e).__name__}: {str(e)[:120]}"
        return r

    async def _run_batch(topics, rnd, conc):
        sem = _asyncio.Semaphore(conc)
        async def _b(t):
            async with sem:
                return await _call(t, rnd)
        return await _asyncio.gather(*[_b(t) for t in topics])

    def _summary(rs):
        ok = [r for r in rs if r.status == 200 and r.cards >= 30]
        fail = [r for r in rs if r not in ok]
        ts = [r.elapsed for r in ok]
        qs = [r.quality for r in ok] if quality_check else []
        s = {
            "total": len(rs), "success": len(ok), "failed": len(fail),
            "success_rate": round(len(ok)/len(rs)*100, 1) if rs else 0,
            "avg_time": round(statistics.mean(ts), 1) if ts else 0,
            "p95_time": round(sorted(ts)[int(len(ts)*0.95)], 1) if len(ts) > 1 else (ts[0] if ts else 0),
            "max_time": round(max(ts), 1) if ts else 0,
            "min_time": round(min(ts), 1) if ts else 0,
            "failures": [{"topic": r.topic, "round": r.round, "error": r.error} for r in fail],
        }
        if qs:
            s["avg_quality"] = round(statistics.mean(qs), 1)
            s["p50_quality"] = round(sorted(qs)[len(qs)//2], 1)
            s["min_quality"] = min(qs)
            s["max_quality"] = max(qs)
            s["quality_distribution"] = {
                "A(>=90)": sum(1 for q in qs if q >= 90),
                "B(80-89)": sum(1 for q in qs if 80 <= q < 90),
                "C(70-79)": sum(1 for q in qs if 70 <= q < 80),
                "D/F(<70)": sum(1 for q in qs if q < 70),
            }
            s["low_quality_topics"] = [
                {"topic": r.topic, "round": r.round, "quality": r.quality, "grade": r.grade}
                for r in ok if r.quality < 70
            ]
        return s

    summaries = []
    all_results = []

    # 第1批：30 主题 / 8 并发
    log.info(f"[stability] 批1: {len(BATCH1)} 主题 / {concurrency} 并发")
    t0 = time.time()
    rs = await _run_batch(BATCH1, 1, concurrency)
    s = _summary(rs); s["batch"] = f"1: {len(BATCH1)}主题x{concurrency}并发"; s["wall_time"] = round(time.time()-t0, 1)
    summaries.append(s); all_results.extend(rs)
    log.info(f"[stability] 批1完成: {s['success']}/{s['total']} 平均{s['avg_time']}s 质量{s.get('avg_quality', 'N/A')}")

    # 第2批：5 主题 × 多轮重复
    for rnd in range(2, rounds + 2):
        log.info(f"[stability] 批2.轮{rnd}: {len(REPEAT)} 主题 / 5 并发")
        rs = await _run_batch(REPEAT, rnd, 5)
        s = _summary(rs); s["batch"] = f"2.r{rnd}: {len(REPEAT)}主题x5并发"
        summaries.append(s); all_results.extend(rs)
        log.info(f"[stability] 第{rnd}轮: {s['success']}/{s['total']} 平均{s['avg_time']}s")

    # 第3批：主批量再跑一次
    log.info(f"[stability] 批3: {len(BATCH1)} 主题 / {concurrency} 并发（重复）")
    t0 = time.time()
    rs = await _run_batch(BATCH1, rounds + 2, concurrency)
    s = _summary(rs); s["batch"] = f"3: {len(BATCH1)}主题x{concurrency}并发(重复)"; s["wall_time"] = round(time.time()-t0, 1)
    summaries.append(s); all_results.extend(rs)
    log.info(f"[stability] 批3完成: {s['success']}/{s['total']} 平均{s['avg_time']}s")

    # 汇总
    ok = sum(1 for r in all_results if r.status == 200 and r.cards >= 30)
    fail = len(all_results) - ok
    ok_times = [r.elapsed for r in all_results if r.status == 200 and r.cards >= 30]
    overall = {
        "total": len(all_results),
        "success": ok, "failed": fail,
        "success_rate": round(ok/len(all_results)*100, 1),
        "avg_time": round(statistics.mean(ok_times), 1) if ok_times else 0,
        "p95_time": round(sorted(ok_times)[int(len(ok_times)*0.95)], 1) if len(ok_times) > 1 else 0,
    }
    if quality_check:
        ok_q = [r.quality for r in all_results if r.status == 200 and r.cards >= 30]
        if ok_q:
            overall["avg_quality"] = round(statistics.mean(ok_q), 1)
            overall["p50_quality"] = round(sorted(ok_q)[len(ok_q)//2], 1)
            overall["min_quality"] = min(ok_q)
            overall["max_quality"] = max(ok_q)
            overall["quality_distribution"] = {
                "A(>=90)": sum(1 for q in ok_q if q >= 90),
                "B(80-89)": sum(1 for q in ok_q if 80 <= q < 90),
                "C(70-79)": sum(1 for q in ok_q if 70 <= q < 80),
                "D/F(<70)": sum(1 for q in ok_q if q < 70),
            }

    report = {
        "test_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "config": {"rounds": rounds, "concurrency": concurrency, "quality_check": quality_check},
        "overall": overall,
        "summaries": summaries,
    }
    (OUTPUT_DIR / "stability_test_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return report


# ── 用户认证路由 ──────────────────────────────────

@app.post("/api/auth/send-code")
async def auth_send_code(req: AuthSendCodeRequest):
    """发送短信验证码"""
    return send_sms_code(req.phone)


@app.post("/api/auth/register")
async def auth_register(req: AuthRegisterRequest):
    """手机号注册"""
    return register(req.phone, req.password, req.sms_code)


@app.post("/api/auth/login")
async def auth_login(req: AuthLoginRequest):
    """登录"""
    return login(req.phone, req.password)


@app.post("/api/auth/reset-password")
async def auth_reset_password(req: AuthResetPasswordRequest):
    """忘记密码重置"""
    return reset_password(req.phone, req.new_password, req.sms_code)


@app.post("/api/auth/profile")
async def auth_update_profile(req: AuthProfileRequest, authorization: str = Header(None)):
    """更新用户资料（需 token）"""
    user = verify_token(authorization.replace("Bearer ", "")) if authorization else None
    if not user:
        return {"success": False, "error": "未登录或登录已过期"}
    return update_profile(user["user_id"], nickname=req.nickname)


@app.get("/api/auth/profile")
async def auth_get_profile(authorization: str = Header(None)):
    """获取用户资料（需 token）"""
    user = verify_token(authorization.replace("Bearer ", "")) if authorization else None
    if not user:
        return {"success": False, "error": "未登录或登录已过期"}
    return {"success": True, **user}


@app.post("/api/auth/learning/save")
async def auth_save_learning(req: SaveLearningRecordRequest, authorization: str = Header(None)):
    """保存学习记录（需 token）"""
    user = verify_token(authorization.replace("Bearer ", "")) if authorization else None
    if not user:
        return {"success": False, "error": "未登录或登录已过期"}
    return save_learning_record(
        user["user_id"], req.course_id, req.course_title,
        req.progress, req.total_cards, req.completed,
        req.quiz_score, req.badges
    )


@app.get("/api/auth/learning/records")
async def auth_get_learning_records(authorization: str = Header(None)):
    """获取学习记录（需 token）"""
    user = verify_token(authorization.replace("Bearer ", "")) if authorization else None
    if not user:
        return {"success": False, "error": "未登录或登录已过期"}
    records = get_learning_records(user["user_id"])
    return {"success": True, "records": records}


@app.get("/api/auth/learning/summary")
async def auth_get_learning_summary(authorization: str = Header(None)):
    """获取学习摘要（需 token）"""
    user = verify_token(authorization.replace("Bearer ", "")) if authorization else None
    if not user:
        return {"success": False, "error": "未登录或登录已过期"}
    summary = get_learning_summary(user["user_id"])
    return {"success": True, **summary}


@app.get("/api/auth/learning/advice")
async def get_learning_advice(authorization: str = Header(None)):
    """AI 个性化学习建议 — 根据用户学习记录生成"""
    user = verify_token(authorization.replace("Bearer ", "")) if authorization else None
    if not user:
        return {"success": False, "error": "未登录或登录已过期"}

    summary = get_learning_summary(user["user_id"])
    records = get_learning_records(user["user_id"])

    # 构建 Prompt
    completed = summary["completed_courses"]
    total = summary["total_courses"]
    course_titles = [r["course_title"] for r in records[:5] if r["course_title"]]
    courses_str = "、".join(course_titles) if course_titles else "暂无"

    prompt_text = (
        f"用户已学习 {total} 门课程，完成 {completed} 门。\n"
        f"最近课程：{courses_str}\n"
        f"总徽章：{summary['total_badges']}，总分：{summary['total_score']}\n\n"
        f"请根据以上学习数据，生成一段简短、鼓励性的个性化学习建议（50-100 字），"
        f"包括对当前进度的肯定和下一步学习方向的建议。用中文回复。"
    )

    # 调用 LLM 生成建议
    try:
        from wanxue_api.config import LLM_API_KEY, LLM_MODEL, LLM_BASE_URL
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = {
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": "你是一个友善的学习顾问。请根据用户的学习数据给出个性化建议。回复简短、有温度。每个建议单独成行，不超过 3 行。"},
                    {"role": "user", "content": prompt_text}
                ],
                "max_tokens": 512,
                "temperature": 0.7,
            }
            headers = {
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type": "application/json"
            }
            url = f"{LLM_BASE_URL}/chat/completions"
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                advice = data["choices"][0]["message"]["content"].strip()
            else:
                raise RuntimeError(f"API 错误 {resp.status_code}")
    except Exception as e:
        log.warning(f"生成学习建议失败: {e}")
        advice = "继续加油！每天学习一点点，知识就会慢慢积累起来。试着回顾一下学过的内容，巩固记忆效果更好哦。"

    return {"success": True, "advice": advice}


# ===== 我的课程 API =====

@app.post("/api/auth/courses/save")
async def save_course(request: Request, authorization: str = Header(None)):
    """保存课程到我的课程"""
    user = verify_token(authorization.replace("Bearer ", "")) if authorization else None
    if not user:
        return {"success": False, "error": "未登录或登录已过期"}
    body = await request.json()
    course = body.get("course", {})
    diff = body.get("difficulty", "")
    result = save_user_course(
        user_id=user["user_id"],
        course_id=course.get("_course_id", course.get("course_id", "")),
        course_title=course.get("course_title", "课程"),
        course_emoji=course.get("course_emoji", "📖"),
        total_chapters=len(course.get("chapters", [])),
        total_cards=course.get("_total_cards", 0),
        difficulty=diff,
    )
    return result


@app.get("/api/auth/courses")
async def list_courses(authorization: str = Header(None)):
    """获取我的课程列表"""
    user = verify_token(authorization.replace("Bearer ", "")) if authorization else None
    if not user:
        return {"success": False, "error": "未登录或登录已过期", "courses": []}
    courses = list_user_courses(user["user_id"])
    return {"success": True, "courses": courses}


@app.delete("/api/auth/courses/{course_id}")
async def delete_course(course_id: str, authorization: str = Header(None)):
    """删除我的课程"""
    user = verify_token(authorization.replace("Bearer ", "")) if authorization else None
    if not user:
        return {"success": False, "error": "未登录或登录已过期"}
    return delete_user_course(user["user_id"], course_id)


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=_api_docs_html())


# ── Static files (放在路由之后，避免覆盖) ───────
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR), html=True), name="output")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Helpers ───────────────────────────────────────

def _fallback_html(course: dict) -> str:
    """renderer 未就绪时的简易预览页"""
    title = course.get("course_title", "WanXue Course")
    chapters = course.get("chapters", [])
    chapters_html = ""
    for ch in chapters:
        chapters_html += f"<h2>{ch.get('emoji', '')} {ch.get('title', '')}</h2>"
        for card in ch.get("cards", []):
            chapters_html += (
                f"<div style='margin:12px 0;padding:12px;border:1px solid #ddd;border-radius:8px'>"
                f"<h3>{card.get('title', '')}</h3>"
                f"<div>{card.get('body', '')}</div>"
                f"</div>"
            )
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:system-ui;max-width:720px;margin:2em auto;padding:0 1em}}</style>
</head><body>
<h1>{course.get('course_emoji', '')} {title}</h1>
<p>{course.get('course_subtitle', '')}</p>
{chapters_html}
</body></html>"""


def _api_docs_html() -> str:
    return """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>WanXue API</title>
<style>
  body{font-family:system-ui;max-width:800px;margin:2em auto;padding:0 1em;color:#333}
  h1{color:#6c5ce7}h2{margin-top:2em;border-bottom:2px solid #eee;padding-bottom:.3em}
  .method{display:inline-block;padding:2px 8px;border-radius:4px;color:#fff;font-weight:bold;margin-right:8px}
  .get{background:#00b894}.post{background:#6c5ce7}
  code{background:#f0f0f0;padding:2px 6px;border-radius:3px;font-size:0.9em}
  pre{background:#2d3436;color:#dfe6e9;padding:1em;border-radius:8px;overflow-x:auto}
</style></head><body>
<h1>WanXue API v1.0</h1>
<p>万学 — 结构化课程生成引擎</p>

<h2>路由列表</h2>

<p><span class="method get">GET</span> <code>/api/health</code></p>
<p>健康检查。返回 <code>{"status": "ok"}</code></p>

<p><span class="method post">POST</span> <code>/api/generate-course</code></p>
<p>生成课程。请求体：</p>
<pre>{"topic": "量子力学", "age": "中学", "goal": "入门科普"}</pre>
<p>返回课程数据及 HTML 访问地址。</p>

<p><span class="method get">GET</span> <code>/api/courses</code></p>
<p>列出所有已生成的课程。</p>

<p><span class="method get">GET</span> <code>/api/courses/{course_id}/index.html</code></p>
<p>获取生成的课程 HTML 页面。</p>

<p><span class="method get">GET</span> <code>/api/courses/{course_id}/preview</code></p>
<p>获取课程预览（前 2 张卡片 + 元数据），用于分享。</p>

<p><span class="method get">GET</span> <code>/api/share/{course_id}</code></p>
<p>生成课程分享链接。</p>

  <p><span class="method get">GET</span> <code>/share/{course_id}</code></p>
  <p>分享落地页 — 预览前几张卡片 + 下载引导。</p>

  <h2>用户认证</h2>
  <p>所有认证路由（带 🔒 标记的）需要在请求头携带 <code>Authorization: Bearer &lt;token&gt;</code></p>

  <p><span class="method post">POST</span> <code>/api/auth/send-code</code></p>
  <p>发送短信验证码。请求体：<code>{"phone": "13800138000"}</code>。调试码 <code>888888</code> 永久可用。</p>

  <p><span class="method post">POST</span> <code>/api/auth/register</code></p>
  <p>手机号注册。请求体：<code>{"phone": "13800138000", "password": "xxx", "sms_code": "888888"}</code></p>

  <p><span class="method post">POST</span> <code>/api/auth/login</code></p>
  <p>手机号密码登录。请求体：<code>{"phone": "13800138000", "password": "xxx"}</code>
  <br>返回 token，后续请求需在 Header 中携带。</p>

  <p><span class="method post">POST</span> <code>/api/auth/reset-password</code></p>
  <p>忘记密码重置。请求体：<code>{"phone": "13800138000", "new_password": "xxx", "sms_code": "888888"}</code></p>

  <p><span class="method get">GET</span> <code>/api/auth/profile</code> 🔒</p>
  <p>获取用户资料。</p>

  <p><span class="method post">POST</span> <code>/api/auth/profile</code> 🔒</p>
  <p>更新用户资料。请求体：<code>{"nickname": "小明"}</code></p>

  <h2>学习记录</h2>

  <p><span class="method post">POST</span> <code>/api/auth/learning/save</code> 🔒</p>
  <p>保存/更新学习记录。请求体包含 <code>course_id</code>, <code>progress</code>, <code>total_cards</code> 等。</p>

  <p><span class="method get">GET</span> <code>/api/auth/learning/records</code> 🔒</p>
  <p>获取用户学习记录列表。</p>

  <p><span class="method get">GET</span> <code>/api/auth/learning/summary</code> 🔒</p>
  <p>获取学习摘要（总课程数、完成数、徽章、总得分）。</p>

  <p><span class="method get">GET</span> <code>/api/auth/learning/advice</code> 🔒</p>
  <p>AI 个性化学习建议 — 根据用户学习记录生成。</p>

<h2>静态文件</h2>
<ul>
  <li><code>/output/</code> — 生成的课程文件</li>
  <li><code>/static/</code> — 静态资源</li>
</ul>
</body></html>"""


# ── Entry ─────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
