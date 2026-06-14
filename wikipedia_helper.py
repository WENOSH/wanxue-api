"""Wikipedia 知识检索模块 — 为课程生成提供事实依据"""

import logging
log = logging.getLogger("wanxue.wikipedia")

# 尝试导入 wikipedia-api
try:
    from wikipediaapi import Wikipedia
    _WIKI_ZH = Wikipedia('WanXue/1.0 (education bot)', 'zh')
    _WIKI_EN = Wikipedia('WanXue/1.0 (education bot)', 'en')
    _HAS_WIKI = True
except ImportError:
    _WIKI_ZH = None
    _WIKI_EN = None
    _HAS_WIKI = False
    log.warning("wikipedia-api 未安装，降级为无知识检索")

# 缓存（避免重复请求）
_cache = {}


def search_topic(query: str, lang: str = "zh") -> dict | None:
    """搜索维基百科主题，返回摘要

    返回: {"title": str, "summary": str, "url": str, "sections": [str]}
    或 None（未找到）
    """
    if not _HAS_WIKI:
        return None

    cache_key = f"{lang}:{query}"
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        wiki = _WIKI_ZH if lang == "zh" else _WIKI_EN
        page = wiki.page(query)
        if not page.exists():
            _cache[cache_key] = None
            return None

        # 收集章节标题（仅顶层，跳过空内容章节）
        sections = []
        for s in page.sections:
            title = s.title.strip()
            if title:
                sections.append(title)

        result = {
            "title": page.title,
            "summary": page.summary.strip(),
            "url": page.fullurl,
            "sections": sections,
        }
        _cache[cache_key] = result
        return result
    except Exception:
        log.warning(f"Wikipedia 请求失败（网络不可达或无此页面）: {query} (lang={lang})")
        _cache[cache_key] = None
        return None


def search_topic_en(query: str) -> dict | None:
    """英文维基百科备选"""
    return search_topic(query, lang="en")


def enrich_course_context(topic: str) -> str:
    """获取主题相关的维基百科内容，返回适合注入到 LLM prompt 的文本

    优先中文，如果中文结果质量差（摘要 < 50 字）则尝试英文

    返回格式：
    == 维基百科参考 ==
    主题: xxx
    摘要: xxx
    关键章节:
    - xxx
    ================
    或返回空字符串（未找到）
    """
    if not _HAS_WIKI:
        return ""

    # 优先中文
    result = search_topic(topic, lang="zh")
    lang_used = "zh"

    # 如果中文结果差，尝试英文
    if result is None or len(result["summary"]) < 50:
        en_result = search_topic_en(topic)
        if en_result and len(en_result["summary"]) >= 50:
            result = en_result
            lang_used = "en"

    if result is None:
        return ""

    summary = result["summary"]
    sections = result["sections"]

    lines = []
    lines.append("== 维基百科参考 ==")
    lines.append(f"主题: {result['title']}")
    lines.append(f"摘要: {summary}")
    if sections:
        lines.append("关键章节:")
        for s in sections[:10]:  # 最多 10 个章节标题
            lines.append(f"- {s}")
    lines.append("================")

    return "\n".join(lines)
