# WanXue API — 长期记忆

## ✅ 已完成 (2026-06-16)
- `prompts.py`: 新增 practice 卡片类型、_concept_log、_storage_analysis、Wisdom 诚实声明、GOAL_DIFFICULTY_STRATEGY
- `engine.py`: inject goal_strategy into user prompt, add _concept_log/_storage_analysis defaults
- `renderer.py`: add checkPractice() JS function, practice-input CSS, wisdom-statement CSS
- `main.py`: TODO 注释已在 GenerateRequest

## 待办：新增学习模式（mode）字段（2026-06-16 记录）

### 背景
受 PM Skills 文章的 Skill 2.0（Plugin = Skill + Command + Hook）概念启发，在 wanxue SKILL.md v0.7 中新增了 4 种学习模式，但 **wanxue-api 尚未实现**。

### 需要做的事
在 `GenerateRequest` 中添加 `mode` 字段：
```python
mode: str = "精学"  # 速览 / 精学 / 复习 / 对比
```

各模式行为：
| 模式 | 执行逻辑 | 改哪里 |
|------|---------|-------|
| 速览 | engine.py 只跑 Step 1-3，prompts.py 只生成知识地图+核心概念 | engine.py + prompts.py |
| 精学 | 默认行为，无需改动 | - |
| 复习 | 读已有 mastery-log，只出闪卡+Quiz，不走生成流水线 | engine.py 新分支 |
| 对比 | topic 支持 "A vs B"，双主题并行生成后合成为对比卡片 | main.py（接口）+ engine.py |

### 触发位置
- `main.py:79` `class GenerateRequest` — TODO 注释已写在代码里
- `engine.py` — 需要按 mode 分叉生成逻辑
- `prompts.py` — 需要不同模式的提示词模板

### 何时做
建议下次迭代 `engine.py` 或 `prompts.py` 时顺手加上，不要单独为 mode 开一轮迭代。
