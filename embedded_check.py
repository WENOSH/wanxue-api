"""
embedded_check — 嵌入式验证存根模块

chat.py 依赖此模块的 L1/L2/L3 验证生成函数。
实际的 3 层验证已实现在 renderer.py 的 JS 模板中（前端侧），
此模块提供空存根以避免 ImportError，在实际调用时返回空数据。
"""
import logging
log = logging.getLogger("wanxue.embedded_check")

async def plan_checks(session):
    """规划验证计划 — 存根实现，返回空计划列表"""
    return []

async def generate_l1_check(plan, api_key=""):
    """生成 L1 关键概念反问 — 存根实现"""
    return {"level": "L1", "question": "", "keyword": "", "feedback": ""}

async def generate_l2_check(plan, course, api_key=""):
    """生成 L2 章节小测 — 存根实现"""
    return {"level": "L2", "questions": [], "passed": False}

async def generate_l3_check(course, api_key=""):
    """生成 L3 场景迁移 — 存根实现"""
    return {"level": "L3", "scenario": "", "question": "", "options": [], "answer": 0, "explanation": ""}
