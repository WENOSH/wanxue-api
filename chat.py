"""WanXue 对话式学习引擎 (2026-06-13 新增)

设计原则：
1. 对话优先：用户用自然语言，AI 引导
2. 流式输出：边生成边推 (SSE)
3. 上下文保持：服务端内存存 session
4. 复用引擎：单卡生成/调难度走同一个 LLM
"""

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

import httpx

try:
    from . import prompts
    from .config import LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, LLM_MAX_TOKENS, LLM_TEMPERATURE, OUTPUT_DIR
except ImportError:
    import prompts
    from config import LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, LLM_MAX_TOKENS, LLM_TEMPERATURE, OUTPUT_DIR

log = logging.getLogger("wanxue.chat")

# ── 内存会话存储（单进程 / 重启即清） ─────────────────────
# 生产环境可换成 Redis：接口兼容即可。
SESSIONS: dict[str, "ChatSession"] = {}


@dataclass
class ChatSession:
    """对话会话：上下文 + 当前课程快照"""
    session_id: str
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    history: list[dict] = field(default_factory=list)  # [{role, content, intent, ...}]
    current_course: Optional[dict] = None  # 最近生成的课程数据
    user_profile: dict = field(default_factory=dict)  # {age, goal, difficulty_level, ...}
    # 嵌入式验证相关 (2026-06-13 新增)
    check_plans: list = field(default_factory=list)  # List[CheckPlan]
    skip_levels: set = field(default_factory=set)  # 用户"先不考"过的层
    chapter_done_sent: set = field(default_factory=set)  # 已发过"chapter_done"事件的章
    # 累计进度
    checks_answered: int = 0  # 已回答的验证数
    checks_correct: int = 0   # 答对的数量
    current_check: Optional[dict] = None  # 当前等待回答的 check
    # 学习进度追踪 (2026-06-13 新增)
    chapters_viewed: set = field(default_factory=set)   # 已浏览的章号集合
    cards_viewed: set = field(default_factory=set)       # 已浏览的卡片 ID 集合
    total_chapters: int = 0
    total_cards: int = 0
    chapter_current: int = 0  # 当前学到第几章（0-based）

    def add_msg(self, role: str, content: str, **kwargs):
        self.history.append({"role": role, "content": content, "ts": time.time(), **kwargs})
        self.last_active = time.time()
        # 限制历史最多 20 条（防止 token 爆炸）
        if len(self.history) > 20:
            self.history = self.history[-20:]

    def to_context(self) -> str:
        """把历史对话压缩成 LLM 上下文摘要"""
        if not self.history:
            return ""
        lines = []
        for h in self.history[-10:]:
            role = "用户" if h["role"] == "user" else "AI"
            lines.append(f"{role}: {h['content'][:200]}")
        return "\n".join(lines)


def create_session() -> ChatSession:
    sid = uuid.uuid4().hex[:12]
    s = ChatSession(session_id=sid)
    SESSIONS[sid] = s
    return s


def get_session(sid: str) -> Optional[ChatSession]:
    return SESSIONS.get(sid)


def cleanup_sessions(max_age_sec: int = 3600):
    """清理超过 1 小时未活跃的会话"""
    now = time.time()
    stale = [k for k, v in SESSIONS.items() if now - v.last_active > max_age_sec]
    for k in stale:
        SESSIONS.pop(k, None)
    if stale:
        log.info(f"清理了 {len(stale)} 个过期会话")


def make_progress(session: ChatSession) -> dict:
    """生成当前学习进度摘要（供 SSE 事件携带）"""
    total_checks = len(session.check_plans)
    checks_done = session.checks_answered
    # 章进度
    ch_total = session.total_chapters or 0
    ch_done = len(session.chapters_viewed)
    # 卡进度
    cd_total = session.total_cards or 0
    cd_done = len(session.cards_viewed)
    return {
        "chapters": {"done": ch_done, "total": ch_total},
        "cards":    {"done": cd_done, "total": cd_total},
        "checks":   {"done": checks_done, "total": total_checks},
    }


# ── 意图识别 ─────────────────────────────────────
INTENT_KEYWORDS = {
    "generate": ["我想学", "教我", "讲讲", "介绍", "什么是", "什么是？", "想了解", "开始学"],
    "deepen": ["再深", "深一点", "更深入", "详细讲", "深入讲", "展开讲", "详细说", "为什么", "本质"],
    # ⚠️ "太简单了"先于"简单"匹配：用户说"太简单"意思是想要更难的内容
    # 而"再简单点/通俗点"才是要更简单
    "simplify": ["再简单", "简单点", "通俗", "小白", "零基础", "小学", "初中", "没懂", "没明白", "听不懂", "换个讲法", "太难了", "太难"],
    "quiz": ["考考我", "测试", "出题", "做题", "练习", "测验", "quiz"],
    "translate": ["翻译", "英文", "English", "日文", "Japanese", "中文", "Chinese"],
    "explore_more": ["例子", "举例", "应用", "哪里用", "怎么用"],
    "summary": ["总结", "回顾", "复习", "回顾一下"],
    "save": ["收藏", "保存", "下载"],
    "next": ["下一章", "继续", "下一个"],
    "prev": ["上一章", "上一", "回到"],
    "skip_check": ["先不考", "不要考", "跳过", "别测了", "不测了", "不用测", "skip"],
    "answer": ["对", "是的", "正确", "✓", "yes", "✔", "yep", "yeah", "不对", "不是", "错了", "错", "no", "nope", "选a", "选b", "选c", "选d", "a", "b", "c", "d"],
    # 难度反馈 - 学完后用户对难度的评价
    "difficulty_feedback": ["正好", "刚好", "适中", "偏难", "偏易", "简单适中", "难度反馈", "试试新难度"],
}


def detect_intent(text: str) -> str:
    """轻量意图识别 - 基于关键词"""
    text = text.lower().strip()
    
    # ★ 优先匹配：如果包含"简单了" 或 "太简单" → 是"太容易"的意思，要更难
    if "太简单" in text or "简单了" in text:
        return "deepen"
    
    for intent, kws in INTENT_KEYWORDS.items():
        if any(kw in text for kw in kws):
            return intent
    # 默认：如果包含"刚才" / "那个" / 引用历史 → 当作追问
    if any(k in text for k in ["刚才", "那个", "之前", "上面", "这个概念"]):
        return "deepen"
    # 包含学科名/概念 → 推断为新主题
    if re.search(r'[\u4e00-\u9fa5a-zA-Z]{2,15}', text):
        return "generate"
    return "other"


def extract_topic(text: str) -> str:
    """从用户消息提取主题"""
    # 去掉引导词
    for kw in ["我想学", "教我", "讲讲", "介绍", "什么是", "想了解", "开始学", "请讲", "帮我讲"]:
        text = text.replace(kw, "")
    text = text.strip(" ?？，,。.!")
    # 截断到合理长度
    if len(text) > 30:
        text = text[:30]
    return text or "未知主题"


# ── LLM 流式调用 ─────────────────────────────────
async def _stream_llm(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
) -> AsyncIterator[str]:
    """流式调用 LLM（DeepSeek/通用 OpenAI 兼容）"""
    import json as _json
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": LLM_MAX_TOKENS,
        "temperature": LLM_TEMPERATURE,
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = f"{LLM_BASE_URL}/chat/completions"
    async with httpx.AsyncClient(timeout=180.0) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise RuntimeError(f"LLM 流式调用失败 {resp.status_code}: {body[:200]!r}")
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                chunk = line[6:]
                if chunk == "[DONE]":
                    break
                try:
                    d = _json.loads(chunk)
                    delta = d["choices"][0].get("delta", {}).get("content", "")
                    if delta:
                        yield delta
                except (_json.JSONDecodeError, KeyError, IndexError):
                    continue


# ── 引导消息生成 ─────────────────────────────────
async def generate_guide(user_msg: str, session: ChatSession, api_key: str) -> dict:
    """生成 AI 的引导回复 + 识别意图"""
    intent = detect_intent(user_msg)
    topic = extract_topic(user_msg) if intent in ("generate", "deepen", "explore_more", "simplify", "translate") else (
        session.current_course.get("course_title", "") if session.current_course else ""
    )

    # 简单规则的引导话术（不走 LLM，保证速度）
    guide_map = {
        "generate": f"好的，正在为你生成《{topic}》课程... ✨",
        "deepen": f"好的，让我更深入地讲讲关于「{topic}」的内容...",
        "simplify": "好的，我用更通俗的方式重新讲 ✏️",
        "difficulty_feedback": "好的，正在根据你的反馈调整课程难度...",
        "quiz": f"好的，正在为你生成关于《{topic}》的 3 道测验题...",
        "translate": "好的，正在生成翻译版本 🌍",
        "explore_more": f"好的，我加几个关于「{topic}」的实际例子...",
        "summary": "好的，让我帮你回顾一下这章重点...",
        "save": "课程已自动保存到你的学习记录 ✅",
        "next": "正在为你准备下一章...",
        "prev": "回到上一章...",
        "skip_check": "好的，本次学习不再做验证。继续～",
        "answer": "已收到～",
        "other": "请告诉我你想学什么，或者对当前课程哪里有疑问？",
    }
    return {
        "intent": intent,
        "topic": topic,
        "guide_message": guide_map.get(intent, guide_map["other"]),
    }


# ── 主流程：处理用户消息 ─────────────────────────
async def handle_user_message(
    user_msg: str,
    session: ChatSession,
    api_key: Optional[str] = None,
) -> AsyncIterator[dict]:
    """处理用户消息并流式产出事件

    事件类型：
    - {"event": "guide", "data": {...}}    AI 引导回复
    - {"event": "thinking", "data": "..."}  正在思考
    - {"event": "card_delta", "data": "..."}  单卡流式内容
    - {"event": "card_done", "data": {...}}  单卡完成
    - {"event": "course_done", "data": {...}} 整课完成
    - {"event": "error", "data": "..."}    错误
    """
    api_key = api_key or LLM_API_KEY
    session.add_msg("user", user_msg)

    # 1) 引导回复
    guide = await generate_guide(user_msg, session, api_key)
    yield {"event": "guide", "data": guide}
    session.add_msg("assistant_guide", guide["guide_message"], intent=guide["intent"], topic=guide["topic"])

    intent = guide["intent"]
    topic = guide["topic"]

    # 2) 根据意图分支
    if intent == "generate":
        # 直接走 engine 生成课程，绑定到会话
        from wanxue_api.config import get_difficulty_config
        diff_key = session.user_profile.get("difficulty", session.user_profile.get("difficulty_level", "3-标准"))
        diff_cfg = get_difficulty_config(diff_key)
        total_est = diff_cfg["chapters"] * diff_cfg["cards"]
        yield {"event": "thinking", "data": f"正在生成《{topic}》课程 {diff_cfg['chapters']} 章约 {total_est} 卡片（{diff_cfg['label']}）..."}
        try:
            from wanxue_api.engine import WanXueEngine
            from wanxue_api.embedded_check import (
                plan_checks, generate_l1_check, generate_l2_check, generate_l3_check,
            )
            engine = WanXueEngine()
            age = session.user_profile.get("age", "成人")
            goal = session.user_profile.get("goal", "入门科普")
            # 调用 engine（不是流式的，但用户期待立刻看到）
            course = await engine.generate_course(topic=topic, age=age, goal=goal, difficulty=diff_key)
            session.current_course = course
            # 重新计算 total_cards + 记录到 session
            course["_total_cards"] = sum(
                len(ch.get("cards", [])) for ch in course.get("chapters", [])
            )
            session.total_chapters = len(course.get("chapters", []))
            session.total_cards = course["_total_cards"]
            session.chapters_viewed = set()
            session.cards_viewed = set()
            session.chapter_current = 0
            session.user_profile["last_topic"] = topic
            session.add_msg("system", f"已生成《{topic}》{len(course.get('chapters', []))} 章 / {course['_total_cards']} 卡")
            # ★ 保存课程到磁盘（供分享链接和直接查看使用）
            try:
                from wanxue_api.renderer import render_html
                from pathlib import Path
                course_id = course.get("_course_id", WanXueEngine._slugify(topic))
                course_dir = OUTPUT_DIR / course_id
                course_dir.mkdir(parents=True, exist_ok=True)
                html_content = render_html(course)
                clean_html = html_content.encode('utf-8', errors='surrogatepass').decode('utf-8', errors='replace')
                (course_dir / "index.html").write_text(clean_html, encoding="utf-8")
                (course_dir / "course.json").write_text(
                    json.dumps(course, ensure_ascii=False, indent=2).encode('utf-8', errors='surrogatepass').decode('utf-8', errors='replace'),
                    encoding="utf-8"
                )
                log.info(f"课程已保存到磁盘: {course_id}")
            except Exception as save_err:
                log.warning(f"保存课程到磁盘失败（不影响对话）: {save_err}")
            # ★ 关键改动：规划 3 层嵌入式验证
            plans = await plan_checks(course)
            session.check_plans = plans
            # 把 plan 摘要（不暴露全量）通过事件告诉前端
            plans_summary = [
                {
                    "level": p.level,
                    "trigger_at": p.trigger_at,
                    "chapter_idx": p.chapter_idx,
                    "description": p.description,
                }
                for p in plans
            ]
            yield {
                "event": "checks_planned",
                "data": {"plans": plans_summary, "count": len(plans)}
            }
            # 课程数据
            yield {
                "event": "course_done",
                "data": {
                    "topic": topic,
                    "course": course,
                    "message": f"《{topic}》课程已生成完毕！共 {session.total_chapters} 章 {session.total_cards} 卡片。学习过程中我会自然地穿插一些小验证帮你巩固～",
                    "progress": make_progress(session),
                }
            }
            # ★ 立即触发第一层 L1（第一章关键概念反问）
            if plans and plans[0].level == "L1":
                l1 = await generate_l1_check(plans[0], api_key)
                session.current_check = l1
                yield {"event": "embedded_check", "data": l1}
        except Exception as e:
            yield {"event": "error", "data": f"课程生成失败: {e}"}
        return

    elif intent == "simplify":
        if not session.current_course:
            yield {"event": "guide", "data": {"guide_message": "请先告诉我你想学什么～"}}
            return
        # 降一档难度重新生成完整课程
        from wanxue_api.config import DIFFICULTY_LEVELS, get_difficulty_config
        current_diff = session.user_profile.get("difficulty_level", "3-标准")
        diff_keys = list(DIFFICULTY_LEVELS.keys())
        current_idx = diff_keys.index(current_diff) if current_diff in diff_keys else 2
        new_idx = max(0, current_idx - 1)
        new_diff = diff_keys[new_idx]
        session.user_profile["difficulty_level"] = new_diff
        new_cfg = get_difficulty_config(new_diff)
        yield {"event": "thinking", "data": f"正在用更通俗的方式重新生成课程（{new_cfg['label']}）..."}
        try:
            from wanxue_api.engine import WanXueEngine
            engine = WanXueEngine()
            age = session.user_profile.get("age", "成人")
            goal = session.user_profile.get("goal", "入门科普")
            course = await engine.generate_course(
                topic=topic, age=age, goal=goal, difficulty=new_diff
            )
            session.current_course = course
            course["_total_cards"] = sum(
                len(ch.get("cards", [])) for ch in course.get("chapters", [])
            )
            session.total_chapters = len(course.get("chapters", []))
            session.total_cards = course["_total_cards"]
            session.user_profile["last_topic"] = topic
            session.add_msg("system", f"已重新生成通俗版《{topic}》（{new_cfg['label']}）{len(course.get('chapters', []))} 章 / {course['_total_cards']} 卡")
            yield {
                "event": "course_done",
                "data": {
                    "topic": topic,
                    "course": course,
                    "message": f"已重新生成通俗版《{topic}》（{new_cfg['label']}），共 {session.total_chapters} 章 {session.total_cards} 卡片",
                    "difficulty_level": new_diff,
                }
            }
        except Exception as e:
            yield {"event": "error", "data": f"重新生成失败: {e}"}
        return

    elif intent == "deepen":
        if not session.current_course:
            yield {"event": "guide", "data": {"guide_message": "请先告诉我你想学什么～"}}
            return
        # 升一档难度重新生成完整课程
        from wanxue_api.config import DIFFICULTY_LEVELS, get_difficulty_config
        current_diff = session.user_profile.get("difficulty_level", "3-标准")
        diff_keys = list(DIFFICULTY_LEVELS.keys())
        current_idx = diff_keys.index(current_diff) if current_diff in diff_keys else 2
        new_idx = min(len(diff_keys) - 1, current_idx + 1)
        new_diff = diff_keys[new_idx]
        session.user_profile["difficulty_level"] = new_diff
        new_cfg = get_difficulty_config(new_diff)
        yield {"event": "thinking", "data": f"正在更深入地重新生成课程（{new_cfg['label']}）..."}
        try:
            from wanxue_api.engine import WanXueEngine
            engine = WanXueEngine()
            age = session.user_profile.get("age", "成人")
            goal = session.user_profile.get("goal", "入门科普")
            course = await engine.generate_course(
                topic=topic, age=age, goal=goal, difficulty=new_diff
            )
            session.current_course = course
            course["_total_cards"] = sum(
                len(ch.get("cards", [])) for ch in course.get("chapters", [])
            )
            session.total_chapters = len(course.get("chapters", []))
            session.total_cards = course["_total_cards"]
            session.user_profile["last_topic"] = topic
            session.add_msg("system", f"已重新生成深入版《{topic}》（{new_cfg['label']}）{len(course.get('chapters', []))} 章 / {course['_total_cards']} 卡")
            yield {
                "event": "course_done",
                "data": {
                    "topic": topic,
                    "course": course,
                    "message": f"已重新生成深入版《{topic}》（{new_cfg['label']}），共 {session.total_chapters} 章 {session.total_cards} 卡片",
                    "difficulty_level": new_diff,
                }
            }
        except Exception as e:
            yield {"event": "error", "data": f"重新生成失败: {e}"}
        return

    elif intent == "difficulty_feedback":
        # 用户学完课程后对难度做出反馈
        if not session.current_course:
            yield {"event": "guide", "data": {"guide_message": "先学一门课再说感受吧～"}}
            return
        user_msg_lower = user_msg.lower().strip()
        # 解析难度反馈
        if any(w in user_msg_lower for w in ["太简单", "太浅", "偏易"]):
            # 用户觉得太简单 → 需要更难
            feedback_diff = "4-进阶"
            direction = "更深更难"
            diff_change = +1
        elif any(w in user_msg_lower for w in ["太难", "太深", "偏难"]):
            # 用户觉得太难 → 需要更简单
            feedback_diff = "2-基础"
            direction = "更简单易懂"
            diff_change = -1
        else:
            # "正好" / "刚好" / "适中" → 保持，记录
            session.user_profile["difficulty_level"] = "3-标准"
            session.user_profile["difficulty_fit"] = "正好"
            yield {
                "event": "difficulty_feedback",
                "data": {
                    "rating": "just_right",
                    "message": "太好了！这个难度正适合你。之后的课程都会保持这个难度水平 💪",
                    "difficulty_level": "3-标准",
                }
            }
            return

        # 保存用户的难度偏好
        from wanxue_api.config import DIFFICULTY_LEVELS, get_difficulty_config
        diff_keys = list(DIFFICULTY_LEVELS.keys())
        current_diff = session.user_profile.get("difficulty_level", "3-标准")
        current_idx = diff_keys.index(current_diff) if current_diff in diff_keys else 2
        new_idx = max(0, min(len(diff_keys) - 1, current_idx + diff_change))
        new_diff = diff_keys[new_idx]
        session.user_profile["difficulty_level"] = new_diff
        session.user_profile["difficulty_fit"] = direction
        new_cfg = get_difficulty_config(new_diff)
        yield {
            "event": "difficulty_feedback",
            "data": {
                "rating": "too_easy" if diff_change > 0 else "too_hard",
                "message": f"明白了！你觉得这个课程{direction}。我重新生成一个更合适难度的版本吧（{new_cfg['label']}）？或者输入「试试新难度」开始～",
                "suggested_difficulty": new_diff,
                "difficulty_label": new_cfg["label"],
            }
        }
        return

    elif intent == "explore_more":
        # 生成单张补卡
        if not session.current_course:
            yield {"event": "guide", "data": {"guide_message": "请先告诉我你想学什么主题～"}}
            return
        yield {"event": "thinking", "data": f"正在补充关于「{topic}」的卡片..."}
        async for ev in stream_single_card(topic, session, api_key, card_type="concept"):
            yield ev
        return

    elif intent == "quiz":
        if not session.current_course:
            yield {"event": "guide", "data": {"guide_message": "请先学一门课，然后我就能出测验题啦～"}}
            return
        yield {"event": "thinking", "data": f"正在生成关于「{topic}」的 3 道测验题..."}
        async for ev in stream_quiz_questions(topic, session, api_key):
            yield ev
        return

    elif intent == "translate":
        if not session.current_course:
            yield {"event": "guide", "data": {"guide_message": "请先学一门课，然后我可以翻译～"}}
            return
        yield {"event": "thinking", "data": "正在翻译成英文版..."}
        async for ev in stream_translate(session, api_key, lang="en"):
            yield ev
        return

    elif intent == "skip_check":
        # 用户说"先不考" → 本次会话不再触发该层
        if session.current_check:
            level = session.current_check.get("level", "L1")
            session.skip_levels.add(level)
            session.current_check = None
            yield {
                "event": "guide",
                "data": {
                    "guide_message": f"好的，本次学习不再做 {level} 验证。继续学～",
                    "intent": "skip_check",
                }
            }
        else:
            yield {
                "event": "guide",
                "data": {"guide_message": "好的，继续～", "intent": "skip_check"}
            }
        return

    elif intent == "answer":
        # 用户在回答当前的 check
        if not session.current_check:
            yield {
                "event": "guide",
                "data": {"guide_message": "没有待回答的问题哦～", "intent": "answer"}
            }
            return
        # 简单匹配：yes/no
        text = user_msg.strip().lower()
        check = session.current_check
        is_correct = None
        if check["level"] == "L1":
            # 是非题
            yes_words = ["对", "是的", "正确", "yes", "yep", "yeah", "✓", "✔"]
            no_words = ["不对", "不是", "错", "no", "nope", "✗", "✘"]
            if any(w in text for w in yes_words):
                is_correct = check.get("answer", "yes") == "yes"
            elif any(w in text for w in no_words):
                is_correct = check.get("answer", "yes") == "no"
            else:
                is_correct = None
            session.checks_answered += 1
            if is_correct:
                session.checks_correct += 1
            yield {
                "event": "check_result",
                "data": {
                    "level": "L1",
                    "is_correct": is_correct,
                    "expected": check.get("answer"),
                    "clarify": check.get("clarify", "") if not is_correct else "",
                    "concept_title": check.get("concept_title", ""),
                    "progress": make_progress(session),
                }
            }
            session.current_check = None
        elif check["level"] == "L2":
            # 4 选 1
            for opt in ["a", "b", "c", "d"]:
                if f"选{opt}" == text or text == opt:
                    # 在 questions 里找对应的"对"的题来对比
                    # 简化：标记已回答
                    session.checks_answered += 1
                    session.current_check = None
                    yield {
                        "event": "check_result",
                        "data": {
                            "level": "L2",
                            "selected": opt.upper(),
                            "message": f"已记录你的选择 {opt.upper()}",
                            "progress": make_progress(session),
                        }
                    }
                    return
            yield {
                "event": "guide",
                "data": {"guide_message": "请用 A/B/C/D 回答哦", "intent": "answer"}
            }
        elif check["level"] == "L3":
            for opt in ["a", "b", "c", "d"]:
                if f"选{opt}" == text or text == opt:
                    correct_opt = None
                    for o in check.get("options", []):
                        if o.get("correct"):
                            correct_opt = o["id"]
                            break
                    is_correct = (opt.upper() == correct_opt)
                    session.checks_answered += 1
                    if is_correct:
                        session.checks_correct += 1
                    yield {
                        "event": "check_result",
                        "data": {
                            "level": "L3",
                            "selected": opt.upper(),
                            "correct": correct_opt,
                            "is_correct": is_correct,
                            "options": check.get("options", []),
                            "progress": make_progress(session),
                        }
                    }
                    session.current_check = None
                    return
            yield {
                "event": "guide",
                "data": {"guide_message": "请用 A/B/C/D 回答哦", "intent": "answer"}
            }
        return

    elif intent == "next":
        # 用户翻到下一章 → 可能触发 L1/L2/L3 验证
        from wanxue_api.embedded_check import (
            generate_l1_check, generate_l2_check, generate_l3_check,
        )
        # 找下一个待触发的 plan
        triggered = False
        for p in session.check_plans:
            if p.level == "L1" and "L1" not in session.skip_levels:
                if p.chapter_idx is not None and p.chapter_idx not in session.chapter_done_sent and p.chapter_idx > 0:
                    session.chapter_done_sent.add(p.chapter_idx)
                    l1 = await generate_l1_check(p, api_key)
                    session.current_check = l1
                    yield {"event": "embedded_check", "data": l1}
                    triggered = True
                    break
            elif p.level == "L2" and "L2" not in session.skip_levels:
                if p.chapter_idx is not None and p.chapter_idx not in session.chapter_done_sent:
                    session.chapter_done_sent.add(p.chapter_idx)
                    l2 = await generate_l2_check(p, session.current_course, api_key)
                    session.current_check = l2
                    yield {"event": "embedded_check", "data": l2}
                    triggered = True
                    break
            elif p.level == "L3" and "L3" not in session.skip_levels:
                if "course_done" not in session.chapter_done_sent:
                    session.chapter_done_sent.add("course_done")
                    l3 = await generate_l3_check(session.current_course, api_key)
                    session.current_check = l3
                    yield {"event": "embedded_check", "data": l3}
                    triggered = True
                    break
        if not triggered:
            yield {"event": "guide", "data": {"guide_message": "继续～", "intent": "next"}}
        return

    elif intent == "prev":
        yield {"event": "guide", "data": {"guide_message": "回到上一章...", "intent": "prev"}}
        return

    elif intent == "summary":
        if not session.current_course:
            yield {"event": "guide", "data": {"guide_message": "请先学一门课～"}}
            return
        # 不走 LLM，直接用本地课程数据生成摘要
        summary = build_summary(session.current_course)
        yield {"event": "summary", "data": summary}
        return

    else:
        yield {"event": "guide", "data": {"guide_message": guide["guide_message"]}}


# ── 单卡生成（流式） ─────────────────────────────
async def stream_single_card(
    topic: str,
    session: ChatSession,
    api_key: str,
    card_type: str = "concept",
) -> AsyncIterator[dict]:
    """生成单张卡片，流式输出"""
    course_ctx = json.dumps({
        "title": session.current_course.get("course_title", topic),
        "chapters_count": len(session.current_course.get("chapters", [])),
    }, ensure_ascii=False) if session.current_course else f"主题: {topic}"

    user_prompt = f"""当前课程上下文：{course_ctx}
用户追问/请求：{topic}
请生成一张 {card_type} 类型卡片来回应用户。

要求：
- 直接生成 JSON（type={card_type}）
- 如果用户说"刚才 X 没懂"，则围绕 X 讲清楚
- 如果用户说"举例"，用具体例子
- body 用 HTML 短文本
- 准确性铁律：禁止编造，使用审慎措辞
"""

    accumulated = ""
    try:
        async for delta in _stream_llm(prompts.SINGLE_CARD_SYSTEM, user_prompt, api_key):
            accumulated += delta
            yield {"event": "card_delta", "data": delta}

        # 解析完成的 JSON
        from wanxue_api.engine import WanXueEngine
        try:
            card = WanXueEngine()._parse_json(accumulated)
            # 加入到当前课程最后一章
            if session.current_course and session.current_course.get("chapters"):
                session.current_course["chapters"][-1]["cards"].append(card)
                # 更新元数据
                from wanxue_api.engine import WanXueEngine as _E
                session.current_course["_total_cards"] = sum(
                    len(c.get("cards", [])) for c in session.current_course["chapters"]
                )
            yield {
                "event": "card_done",
                "data": {"card": card, "location": "last_chapter"}
            }
        except Exception as e:
            yield {"event": "error", "data": f"卡片 JSON 解析失败: {e}, 原文: {accumulated[:200]}"}
    except Exception as e:
        yield {"event": "error", "data": f"LLM 调用失败: {e}"}


# ── 难度调整（流式） ─────────────────────────────
async def stream_difficulty_adjusted(
    topic: str,
    session: ChatSession,
    api_key: str,
    direction: str,  # "simplify" | "deepen"
) -> AsyncIterator[dict]:
    """调整课程难度"""
    course_summary = json.dumps({
        "title": session.current_course.get("course_title", ""),
        "chapters": [
            {"title": ch.get("title", ""), "n_cards": len(ch.get("cards", []))}
            for ch in session.current_course.get("chapters", [])
        ]
    }, ensure_ascii=False) if session.current_course else f"主题: {topic}"

    direction_zh = "更通俗" if direction == "simplify" else "更深入"
    user_prompt = f"""原课程结构：
{course_summary}

请把整个课程调整为{direction_zh}的版本。保持 5 章 35 卡结构。

调整策略（{"简化" if direction == "simplify" else "加深"}）：
{"- 减少术语、加入生活类比、用小学能懂的话重写" if direction == "simplify" else "- 增加专业术语、加入数学公式、深入原理本质"}

输出完整 5 章 JSON。"""

    accumulated = ""
    try:
        async for delta in _stream_llm(prompts.ADJUST_DIFFICULTY_SYSTEM, user_prompt, api_key):
            accumulated += delta
            yield {"event": "diff_delta", "data": delta}

        from wanxue_api.engine import WanXueEngine
        try:
            adjusted = WanXueEngine()._parse_json(accumulated)
            if "chapters" in adjusted:
                session.current_course = adjusted
                session.current_course["_total_cards"] = sum(
                    len(c.get("cards", [])) for c in adjusted["chapters"]
                )
                session.current_course["_course_id"] = "chat-" + session.session_id[:8]
                yield {
                    "event": "course_done",
                    "data": {
                        "course": adjusted,
                        "message": f"已重新生成{direction_zh}版（{len(adjusted['chapters'])} 章 / {session.current_course['_total_cards']} 卡）"
                    }
                }
        except Exception as e:
            yield {"event": "error", "data": f"JSON 解析失败: {e}, 原文: {accumulated[:200]}"}
    except Exception as e:
        yield {"event": "error", "data": f"LLM 调用失败: {e}"}


# ── 测验题生成 ─────────────────────────────
async def stream_quiz_questions(
    topic: str,
    session: ChatSession,
    api_key: str,
) -> AsyncIterator[dict]:
    """生成 3 道测验题"""
    course_data = session.current_course
    if not course_data:
        return

    # 提取课程关键概念作为出题素材
    concepts = []
    for ch in course_data.get("chapters", []):
        for c in ch.get("cards", []):
            if c.get("type") == "concept":
                concepts.append(c.get("title", ""))

    user_prompt = f"""基于以下课程内容，生成 3 道测验题：

主题：{course_data.get('course_title', topic)}
关键概念：{json.dumps(concepts[:10], ensure_ascii=False)}

要求：
- 3 道 quiz 类型卡片（type="quiz"）
- 每道题 2-4 个选项
- 必须用 game-box + answer-btn + data-good 格式
- 1 道概念理解题、1 道应用题、1 道判断题

输出 JSON 数组：{{"questions": [{{type:"quiz", title, body}}, ...]}}"""

    accumulated = ""
    try:
        async for delta in _stream_llm(prompts.SINGLE_CARD_SYSTEM, user_prompt, api_key):
            accumulated += delta
            yield {"event": "quiz_delta", "data": delta}

        from wanxue_api.engine import WanXueEngine
        try:
            data = WanXueEngine()._parse_json(accumulated)
            questions = data.get("questions", [data] if data.get("type") == "quiz" else [])
            yield {
                "event": "quiz_done",
                "data": {
                    "questions": questions,
                    "count": len(questions)
                }
            }
        except Exception as e:
            yield {"event": "error", "data": f"测验 JSON 解析失败: {e}, 原文: {accumulated[:200]}"}
    except Exception as e:
        yield {"event": "error", "data": f"LLM 调用失败: {e}"}


# ── 翻译（流式） ─────────────────────────────
async def stream_translate(
    session: ChatSession,
    api_key: str,
    lang: str = "en",
) -> AsyncIterator[dict]:
    """翻译整个课程"""
    course = session.current_course
    if not course:
        return

    lang_name = {"en": "英文", "ja": "日文", "zh": "中文"}.get(lang, lang)
    user_prompt = f"""请把以下课程翻译成{lang_name}，保持 5 章 35 卡结构，准确性铁律同样适用。

{json.dumps(course, ensure_ascii=False, indent=2)[:3000]}

输出纯 JSON：{{course_title, course_subtitle, chapters: [...]}}"""

    accumulated = ""
    try:
        async for delta in _stream_llm(prompts.ADJUST_DIFFICULTY_SYSTEM, user_prompt, api_key):
            accumulated += delta
            yield {"event": "trans_delta", "data": delta}

        from wanxue_api.engine import WanXueEngine
        try:
            translated = WanXueEngine()._parse_json(accumulated)
            yield {
                "event": "translation_done",
                "data": {
                    "lang": lang,
                    "course": translated,
                }
            }
        except Exception as e:
            yield {"event": "error", "data": f"翻译 JSON 解析失败: {e}, 原文: {accumulated[:200]}"}
    except Exception as e:
        yield {"event": "error", "data": f"LLM 调用失败: {e}"}


# ── 课程摘要（本地生成，不走 LLM） ─────────────
def build_summary(course: dict) -> dict:
    """用本地数据生成课程摘要"""
    chapters = course.get("chapters", [])
    summary = {
        "title": course.get("course_title", ""),
        "chapters": []
    }
    for ch in chapters:
        concepts = [c.get("title", "") for c in ch.get("cards", []) if c.get("type") == "concept"]
        funfacts = [c.get("body", "")[:100] for c in ch.get("cards", []) if c.get("type") == "funfact"]
        summary["chapters"].append({
            "title": ch.get("title", ""),
            "emoji": ch.get("emoji", ""),
            "key_concepts": concepts[:3],
            "fun_facts": funfacts[:2],
        })
    return summary
