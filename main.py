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

# 确保输出目录存在
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)


# ── Models ────────────────────────────────────────
class GenerateRequest(BaseModel):
    topic: str
    age: str = "成人"
    goal: str = "入门科普"


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class BindCourseRequest(BaseModel):
    session_id: str
    course: dict  # 客户端把 generate-course 返回的 course 绑到会话上


class StabilityTestRequest(BaseModel):
    topics: list[str] | None = None
    rounds: int = 1
    concurrency: int = 8
    quality_check: bool = True


# ── Routes ────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/generate-course")
async def generate_course(req: GenerateRequest):
    log.info(f"生成课程请求: topic={req.topic}, age={req.age}, goal={req.goal}")

    # 1. 调用引擎生成课程数据
    course = await engine.generate_course(
        topic=req.topic, age=req.age, goal=req.goal
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
    (course_dir / "index.html").write_text(html_content, encoding="utf-8")
    (course_dir / "course.json").write_text(
        json.dumps(course, ensure_ascii=False, indent=2), encoding="utf-8"
    )

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
