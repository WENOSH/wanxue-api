# WanXue API 项目记忆

## 工作目录
本目录：`D:\ai agent\wanxue\wanxue-api\` — 主项目（含 git）

## 最新改动（2026-06-16）
- **renderer.py**: 翻页模式（一卡一页、左右滑动、自动切章）替代了长滚动
- **config.py**: 所有难度每章卡片数改为 8
- **prompts.py**: 新增 practice 卡片、_concept_log、_storage_analysis、GOAL_DIFFICULTY_STRATEGY、Wisdom 声明
- **main.py**: bind-course 双重 role 参数 bug 修复
- **SKILL.md**: v0.8（理解阶梯 Knowledge→Skills→Wisdom）

## 待办
- 学习模式（mode字段: 速览/精学/复习/对比）— TODO 注释在 main.py:83
- Render 自动部署后验证 /api/auth/courses 等端点

## 相关目录
- `D:\ai agent\wanxue\wanxue-skill\` — SKILL.md 参考副本
- `D:\ai agent\wanxue\tts-skill\` — TTS 朗读 skill
- `D:\ai agent\wanxue\references\` — 早期版本存档
- `~/.workbuddy/skills/wanxue\` — WorkBuddy 运行时来源（不可动）
