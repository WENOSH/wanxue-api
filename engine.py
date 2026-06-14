""" WanXue Course Generation Engine — 调用 LLM 生成结构化课程 """

import json
import re
import time
import logging
from typing import Optional
import httpx

try:
    from . import prompts
    from .config import (
        LLM_API_KEY, LLM_MODEL, LLM_BASE_URL,
        LLM_MAX_TOKENS, LLM_TEMPERATURE, MAX_CHAPTERS, MAX_CARDS_PER_CHAPTER
    )
except ImportError:
    import prompts
    from config import (
        LLM_API_KEY, LLM_MODEL, LLM_BASE_URL,
        LLM_MAX_TOKENS, LLM_TEMPERATURE, MAX_CHAPTERS, MAX_CARDS_PER_CHAPTER
    )

log = logging.getLogger("wanxue.engine")


class WanXueEngine:
    """万学课程生成引擎"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or LLM_API_KEY
        self.client = httpx.AsyncClient(timeout=120.0)

    async def generate_course(
        self,
        topic: str,
        age: str = "成人",
        goal: str = "入门科普"
    ) -> dict:
        """生成完整课程

        Args:
            topic: 学习主题，如"量子力学"
            age: 学习者年龄，小学/中学/大学/成人
            goal: 学习目标，入门科普/考试准备/项目应用/深入研究

        Returns:
            dict: 结构化课程数据
        """
        log.info(f"🚀 开始生成课程: topic={topic}, age={age}, goal={goal}")

        if not self.api_key:
            log.warning("⚠️ 未配置 API KEY，使用降级模板")
            return self._fallback_course(topic, age, goal)

        try:
            course_data = await self._call_llm(topic, age, goal)
        except Exception as e:
            log.warning(f"⚠️ 首次 LLM 调用失败，尝试补全: {e}")
            course_data = None

        if course_data:
            try:
                validated = self._validate_and_fix(course_data, topic, age)
            except Exception as e:
                log.warning(f"⚠️ 验证失败: {e}, LLM返回数据: {json.dumps(course_data, ensure_ascii=False)[:500]}")
                validated = None
        else:
            validated = None

        if validated:
            log.info(f"✅ 课程生成完成: {validated['course_title']}, {len(validated['chapters'])}章")

            # ── 质量补全：章节太少或卡片太少时让 LLM 补全 ─────
            total_chapters = len(validated["chapters"])
            total_cards = validated["_total_cards"]
            MIN_CHAPTERS = 3
            MIN_CARDS = 12
            if total_chapters < MIN_CHAPTERS or total_cards < MIN_CARDS:
                log.warning(
                    f"⚠️ 课程过短 ({total_chapters}章/{total_cards}卡)，尝试 LLM 补全"
                )
                try:
                    filled = await self._refill_short_course(topic, age, goal, validated)
                    if filled and (
                        len(filled["chapters"]) > total_chapters
                        or filled["_total_cards"] > total_cards
                    ):
                        log.info(
                            f"✅ 补全成功: {len(filled['chapters'])}章/{filled['_total_cards']}卡"
                        )
                        return filled
                except Exception as e:
                    log.warning(f"补全失败，使用原数据: {e}")
            return validated

        # 首次完全失败，尝试补全生成
        log.warning(f"⚠️ 首次解析失败，尝试 LLM 补全生成")
        try:
            filled = await self._refill_short_course(topic, age, goal, {"chapters": []})
            if filled and len(filled.get("chapters", [])) >= 3:
                log.info(
                    f"✅ 补全生成成功: {len(filled['chapters'])}章/{filled['_total_cards']}卡"
                )
                return filled
        except Exception as e:
            log.warning(f"补全生成失败: {e}")

        log.error(f"❌ LLM 生成失败，使用降级模板")
        return self._fallback_course(topic, age, goal)

    async def _call_llm(self, topic: str, age: str, goal: str) -> dict:
        """调用 LLM API 生成课程 JSON"""
        user_prompt = prompts.USER_PROMPT_TEMPLATE.format(
            topic=topic, age=age, goal=goal
        )

        payload = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": prompts.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": LLM_MAX_TOKENS,
            "temperature": LLM_TEMPERATURE,
            "response_format": {"type": "json_object"}
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        url = f"{LLM_BASE_URL}/chat/completions"
        resp = await self.client.post(url, json=payload, headers=headers)

        if resp.status_code != 200:
            raise RuntimeError(f"LLM API 错误 {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return self._parse_json(content)

    def _parse_json(self, raw: str) -> dict:
        """解析 LLM 返回的 JSON - 兼容 deepseek 思考链"""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)

        # 直接 json.loads 优先
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 用 raw_decode 自动定位最外层 JSON（支持嵌套）
        decoder = json.JSONDecoder()
        for i, ch in enumerate(cleaned):
            if ch == '{':
                try:
                    obj, end = decoder.raw_decode(cleaned, i)
                    return obj
                except json.JSONDecodeError:
                    continue

        raise ValueError(f"无法解析 LLM 返回的 JSON: {cleaned[:200]}...")

    def _validate_and_fix(self, data: dict, topic: str, age: str) -> dict:
        """验证并修复课程数据"""
        # 必需字段
        data.setdefault("course_title", f"{topic}入门课")
        data.setdefault("course_emoji", "📚")
        data.setdefault("course_subtitle", f"用万学方法轻松掌握{topic}")

        chapters = data.get("chapters", [])
        if not chapters:
            raise ValueError("课程没有章节")

        # 截断到最大章节数
        chapters = chapters[:MAX_CHAPTERS]

        for i, ch in enumerate(chapters):
            ch.setdefault("id", i + 1)
            ch.setdefault("title", f"第{i+1}章")
            ch.setdefault("emoji", "📖")

            cards = ch.get("cards", [])
            if not cards:
                # 为没有卡片的章节生成占位卡片
                cards = [{
                    "type": "concept",
                    "title": f"📖 {ch['title']}",
                    "body": f"<p>内容生成中...</p>"
                }]

            # 截断卡片数
            cards = cards[:MAX_CARDS_PER_CHAPTER]

            # 确保每张卡片有必需字段
            for j, card in enumerate(cards):
                card.setdefault("type", "concept")
                card.setdefault("title", f"卡片 {j+1}")
                card.setdefault("body", "<p>内容待补充</p>")

            ch["cards"] = cards

        # 计算每章卡片总数（给同步器用）
        chapter_totals = [0]  # 索引0占位
        for ch in chapters:
            chapter_totals.append(len(ch["cards"]))

        data["chapters"] = chapters
        data["_chapter_totals"] = chapter_totals
        data["_total_cards"] = sum(chapter_totals[1:])
        data["_course_id"] = self._slugify(topic)

        return data

    def _fallback_course(self, topic: str, age: str, goal: str) -> dict:
        """降级方案：生成模板课程（无需 LLM）"""
        slug = self._slugify(topic)
        return {
            "course_title": f"探索{topic}",
            "course_emoji": "📚",
            "course_subtitle": f"适合{age}学习者的{topic}入门课",
            "chapters": [
                {
                    "id": 1,
                    "title": f"什么是{topic}？",
                    "emoji": "🔍",
                    "cards": [
                        {"type": "scene", "title": "🔍 生活中的发现",
                         "body": f"<p>你有没有想过，{topic}其实就在我们身边？让我们一起探索吧！</p>"},
                        {"type": "concept", "title": f"📖 {topic}是什么",
                         "body": f"<p>{topic}是一个有趣的知识领域。它帮助我们理解世界的运作方式。</p><p><strong>一句话总结：</strong>{topic}是我们理解世界的一把钥匙。</p>"},
                        {"type": "funfact", "title": "🎁 你知道吗",
                         "body": "<p>很多科学家都是从好奇一个问题开始的。保持好奇心是最好的学习方法！</p>"},
                        {"type": "meta", "title": "🧠 学习技巧",
                         "body": "<p>学习任何新知识的最好方法是：先理解大图景，再深入细节。画一张思维导图会很有帮助！</p>"},
                        {"type": "explore", "title": "🔗 应用场景",
                         "body": f"<p>🌍 <strong>日常生活：</strong>{topic}的知识可以用在很多地方。</p><p>📝 <strong>考试应用：</strong>掌握基础概念就能应对大部分题目。</p>"},
                        {"type": "quiz", "title": "✅ 来试试",
                         "body": f'<div class="game-box"><p>{topic}属于哪类知识？</p><button class="answer-btn" onclick="checkAnswer(this,true,\'fb1\')" data-good="正确！保持好奇心！">有趣的新知识</button><button class="answer-btn" onclick="checkAnswer(this,false,\'fb1\')" data-good="再想想～它其实很有趣">无聊的旧知识</button><div id="fb1" class="feedback"></div></div>'},
                        {"type": "reward", "title": "🏆 完成！",
                         "body": "<p>🎉 你已经迈出了学习的第一步！</p><p>记住：学习不是赛跑，而是一场探险。慢慢来，享受过程。</p><p>🥉 获得徽章：<strong>新章解锁</strong></p>"}
                    ]
                }
            ],
            "_chapter_totals": [0, 7],
            "_total_cards": 7,
            "_course_id": slug,
            "_fallback": True
        }

    @staticmethod
    def _slugify(text: str) -> str:
        """生成课程 ID（ASCII 安全）"""
        import time
        # 只保留 ASCII 字母数字，其它用 - 代替
        ascii_part = re.sub(r'[^a-z0-9]', '-', text.lower())
        ascii_part = re.sub(r'-+', '-', ascii_part).strip('-')
        # 如果全是非 ASCII（如纯中文），用 generic 名
        if not ascii_part:
            ascii_part = "course"
        # 加时间戳确保唯一
        timestamp = str(int(time.time()))[-6:]
        slug = f"{ascii_part}-{timestamp}"
        return slug[:50]

    async def _refill_short_course(
        self, topic: str, age: str, goal: str, current: dict
    ) -> Optional[dict]:
        """课程过短时让 LLM 补全到 5 章，每章 7 卡"""
        existing = json.dumps({
            "title": current.get("course_title", ""),
            "chapters": [
                {"title": ch.get("title", ""), "cards": [c.get("title", "") for c in ch.get("cards", [])]}
                for ch in current.get("chapters", [])
            ]
        }, ensure_ascii=False)

        user_prompt = (
            f"主题：{topic}，年龄：{age}，目标：{goal}\n\n"
            f"现有内容（保留并扩展）：{existing}\n\n"
            f"请输出一份完整 JSON：\n"
            f"- 保留已有章节并扩充每章到 7 张卡片\n"
            f"- 总章节补足到 5 章\n"
            f"- 每张卡片含 type(7种:scene/concept/funfact/meta/explore/quiz/reward)、title、body(简短 HTML)\n"
            f"- 必须用 response_format json_object\n"
        )

        payload = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": prompts.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": LLM_MAX_TOKENS,
            "temperature": LLM_TEMPERATURE,
            "response_format": {"type": "json_object"}
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        url = f"{LLM_BASE_URL}/chat/completions"
        resp = await self.client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            return None
        content = resp.json()["choices"][0]["message"]["content"]
        data = self._parse_json(content)
        # 复用验证流程
        return self._validate_and_fix(data, topic, age)
