# 爆款文案智能体 - 使用文档

## 核心思路

```
喂入爆款视频文案 → Claude 拆解模式 → 存入向量知识库
           ↓
输入主题 → 智能体检索相似爆款 → 基于真实数据生成文案
```

智能体的核心优势：**不是凭空创作，而是基于已验证的爆款模式进行二创**。

---

## 快速开始

### 1. 启动可视化界面

```bash
ANTHROPIC_API_KEY="你的key" ANTHROPIC_BASE_URL="https://cc.codesome.ai" \
python viral_agent_ui.py
```

浏览器打开 `http://localhost:7860`

### 2. 命令行使用

```bash
# 学习单条文案（JSON 文件）
python -m viral_agent learn --text scripts.json --niche 情感

# 学习本地视频目录（需要 ffmpeg + Whisper/Groq）
python -m viral_agent learn --dir ./对标爆款/0415 --niche 情感

# 生成文案
python -m viral_agent generate --topic "普通人如何月入过万" --niche 干货 --versions 3

# 查看知识库状态
python -m viral_agent stats

# 查看最近生成记录，拿到 generation_id
python -m viral_agent feedback list

# 手动录入发布后数据，并立即复盘
python -m viral_agent feedback add \
  --generation-id gen_xxx \
  --views 1011 --likes 27 --comments 0 --favorites 4 \
  --completion-rate 11.01 --bounce-2s-rate 29.9 \
  --completion-5s-rate 48.72 --avg-watch-seconds 23 \
  --avg-watch-ratio 26.25 --analyze

# 查看最近复盘沉淀出的生成约束
python -m viral_agent feedback context --niche 宠物
```

---

## 文件结构

```
viral_agent/
├── knowledge_base.py   # 向量知识库（ChromaDB，本地持久化）
├── transcriber.py      # 视频音频转文字（Whisper / Groq ASR）
├── analyzer.py         # Claude 爆款模式分析
├── agent.py            # 文案生成主逻辑
├── feedback/           # 发布后反馈学习 MVP
├── pipeline.py         # 数据导入管道
└── __main__.py         # CLI 入口

viral_agent_ui.py       # Gradio 可视化界面
.viral_kb/              # 知识库数据（自动创建）
```

---

## 三个核心模块

### 模块一：知识库（knowledge_base.py）

本地向量数据库，支持语义检索。

**存储内容（每条爆款）：**

| 字段 | 说明 |
|------|------|
| `script` | 原始文案全文 |
| `hook` | 开头钩子原文 |
| `hook_type` | 钩子类型（共鸣/利益/好奇/痛点等） |
| `hook_formula` | 可复用的钩子公式模板 |
| `structure` | 文案结构描述 |
| `why_viral` | 爆火核心原因 |
| `viral_elements` | 爆款元素标签列表 |
| `rewrite_template` | 带占位符的改写模板 |
| `likes` | 点赞数（用于排序参考） |

**API：**
```python
from viral_agent.knowledge_base import add_script, search_scripts, get_all_patterns

# 存入
add_script(video_id, script, analysis, metadata)

# 检索
results = search_scripts("职场升职", n=5, niche="干货")

# 统计
stats = get_all_patterns(niche="情感")
```

---

### 模块二：分析器（analyzer.py）

调用 Claude 对文案进行深度结构化拆解。

**输入：** 原始文案文本
**输出：** 结构化分析 JSON

```python
from viral_agent.analyzer import analyze_script

analysis = analyze_script(
    script="你有没有发现，越是没本事的人...",
    likes=280000,
    niche="情感"
)
# 返回：
# {
#   "hook": "你有没有发现，越是没本事的人，越喜欢充大头",
#   "hook_type": "共鸣型",
#   "hook_formula": "你有没有发现，越是[负面特征]的人，越[反差行为]",
#   "structure": "反常识观点→案例佐证→哲理升华→互动引导",
#   "emotion_triggers": ["共鸣", "优越感", "认同"],
#   "viral_elements": ["反转", "共鸣", "身份认同"],
#   "why_viral": "精准戳中有社会经验的人的共鸣点...",
#   "rewrite_template": "你有没有发现，越是[X]的人，越[Y]...",
#   ...
# }
```

---

### 模块三：智能体（agent.py）

基于知识库生成新文案，三步流程：

```
1. search_scripts(topic)      → 检索相似爆款
2. get_all_patterns(niche)    → 获取整体规律
3. claude("基于以上数据生成") → 输出多版本文案
```

每个版本文案都会标注参考了哪个爆款的结构/公式。

```python
from viral_agent.agent import generate

result = generate(
    topic="普通人如何快速升职",
    niche="干货",
    requirements="目标受众：25-35岁职场人",
    versions=3,
)
```

---

## 批量导入格式

JSON 文件格式（用于 `--text` 参数或界面批量导入）：

```json
[
  {
    "video_id": "唯一ID（可选）",
    "script": "视频文案全文...",
    "likes": 280000,
    "niche": "情感"
  },
  {
    "video_id": "video_002",
    "script": "另一条文案...",
    "likes": 150000,
    "niche": "干货"
  }
]
```

---

## 从视频自动提取文案

需要：`ffmpeg` + `whisper` 或 `groq`

```bash
# 安装
brew install ffmpeg
pip install openai-whisper   # 本地（慢但精准）
pip install groq             # API（快，有免费额度）

# 设置 Groq key（可选，不设置则用本地 Whisper）
export GROQ_API_KEY="gsk_xxx"

# 从视频目录学习
python -m viral_agent learn --dir ./对标爆款/0415 --niche 情感
```

视频目录可以放一个 `metadata.json` 补充点赞数等信息：
```json
[
  {"video_id": "视频文件名（不含扩展名）", "likes": 100000}
]
```

---

## 推荐使用流程

### 第一阶段：构建知识库（越多越好）
1. 整理对标账号的爆款文案，建议每个赛道 **30-50 条**
2. 通过界面或 CLI 批量导入
3. 查看"统计分析"，确认钩子类型、爆款元素已被正确提取

### 第二阶段：验证知识库质量
1. 用"语义检索"搜索几个关键词，看返回结果是否相关
2. 检查爆款分析结果是否准确（钩子公式、结构是否正确）

### 第三阶段：生成 & 迭代
1. 输入主题，生成 3-5 个版本
2. 选出最好的版本，手动润色后发布
3. **把发布后爆了的视频文案也加入知识库**（自我迭代）

---

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ANTHROPIC_API_KEY` | API 密钥 | 必填 |
| `ANTHROPIC_BASE_URL` | API 地址 | `https://api.anthropic.com` |
| `GROQ_API_KEY` | Groq ASR 密钥（可选） | 无 |
| `CLAUDE_BIN` | claude CLI 路径 | `claude` |

---

## 常见问题

**Q: 知识库数据存在哪里？**
A: `.viral_kb/` 目录（项目根目录下），本地 SQLite + 向量索引，删除此目录即清空知识库。

**Q: 生成质量不好怎么办？**
A: 主要看知识库质量。确保：① 录入的是真实爆款（点赞 10w+）；② 赛道对口；③ 数量足够（30条以上效果明显提升）。

**Q: 如何处理有字幕的视频？**
A: 可以直接提取字幕文件（.srt/.ass），比 ASR 更准确。把字幕内容作为 `script` 字段录入即可。
