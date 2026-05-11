# AI学习与反馈系统设计文档

## 一、系统目标

让AI从生成内容的实际效果中学习，持续优化爆款内容生成策略，而不仅仅依赖静态知识库。

### 核心能力
1. **效果追踪**：记录AI生成内容的实际表现数据
2. **模式学习**：从成功/失败案例中提取规律
3. **策略优化**：动态调整生成策略，提高爆款率
4. **趋势感知**：发现新兴热点，淘汰过时模式

---

## 二、系统架构

### 2.1 整体流程

```
┌─────────────┐
│ 1. 生成内容 │
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│ 2. 记录生成信息 │ ← 新增模块
│  - 生成时间     │
│  - 使用的模板   │
│  - 参考案例     │
│  - 生成参数     │
└──────┬──────────┘
       │
       ▼
┌─────────────┐
│ 3. 发布内容 │
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│ 4. 效果追踪     │ ← 新增模块
│  (7天后自动)    │
│  - 点赞数       │
│  - 播放量       │
│  - 评论数       │
│  - 分享数       │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ 5. 效果评估     │ ← 新增模块
│  - 是否爆款？   │
│  - 成功/失败    │
│  - 原因分析     │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ 6. 模式学习     │ ← 新增模块
│  - 更新权重     │
│  - 发现趋势     │
│  - 淘汰过时模式 │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ 7. 策略优化     │ ← 新增模块
│  - 调整推荐算法 │
│  - 更新生成参数 │
└─────────────────┘
```

### 2.2 数据库设计

#### 表1: `generated_content` (生成内容追踪表)
```sql
CREATE TABLE generated_content (
    id TEXT PRIMARY KEY,              -- 生成ID（UUID）
    video_id TEXT,                    -- 发布后的视频ID（可能为空）
    script TEXT NOT NULL,             -- 生成的文案
    niche TEXT,                       -- 领域

    -- 生成信息
    generated_at TIMESTAMP,           -- 生成时间
    reference_videos TEXT,            -- 参考的爆款视频ID（JSON数组）
    hook_type TEXT,                   -- 使用的hook类型
    generation_params TEXT,           -- 生成参数（JSON）

    -- 效果数据（初始为空，后续更新）
    published_at TIMESTAMP,           -- 发布时间
    likes INTEGER DEFAULT 0,          -- 点赞数
    views INTEGER DEFAULT 0,          -- 播放量
    comments INTEGER DEFAULT 0,       -- 评论数
    shares INTEGER DEFAULT 0,         -- 分享数

    -- 评估结果
    is_viral BOOLEAN,                 -- 是否爆款（NULL=未评估）
    performance_score REAL,           -- 表现评分（0-100）
    tracked_at TIMESTAMP,             -- 最后追踪时间

    -- 分析
    success_factors TEXT,             -- 成功因素（JSON）
    failure_reasons TEXT              -- 失败原因（JSON）
);
```

#### 表2: `pattern_performance` (模式表现统计表)
```sql
CREATE TABLE pattern_performance (
    pattern_type TEXT,                -- 模式类型（hook_type/structure/emotion等）
    pattern_value TEXT,               -- 具体值（如"悬念式开头"）
    niche TEXT,                       -- 领域

    -- 统计数据
    total_uses INTEGER DEFAULT 0,     -- 使用次数
    success_count INTEGER DEFAULT 0,  -- 成功次数
    success_rate REAL,                -- 成功率
    avg_likes REAL,                   -- 平均点赞数
    avg_views REAL,                   -- 平均播放量

    -- 趋势数据
    recent_30d_success_rate REAL,     -- 最近30天成功率
    trend TEXT,                       -- 趋势（rising/stable/declining）

    -- 权重
    weight REAL DEFAULT 1.0,          -- 推荐权重（动态调整）

    updated_at TIMESTAMP,             -- 最后更新时间

    PRIMARY KEY (pattern_type, pattern_value, niche)
);
```

#### 表3: `learning_insights` (学习洞察表)
```sql
CREATE TABLE learning_insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    insight_type TEXT,                -- 洞察类型（trend/warning/opportunity）
    title TEXT,                       -- 标题
    description TEXT,                 -- 描述
    confidence REAL,                  -- 置信度（0-1）
    evidence TEXT,                    -- 证据数据（JSON）
    created_at TIMESTAMP,
    is_active BOOLEAN DEFAULT 1       -- 是否仍然有效
);
```

#### 表4: `published_video_feedback` (发布后反馈事件表)
```sql
CREATE TABLE published_video_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generation_id TEXT NOT NULL,       -- 对应 generated_content.id
    video_id TEXT NOT NULL,            -- 平台视频ID
    platform TEXT DEFAULT 'douyin',    -- 平台

    -- 反馈时间点
    snapshot_at TIMESTAMP NOT NULL,    -- 本次采集时间
    hours_after_publish INTEGER,       -- 发布后第几小时

    -- 基础表现
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    favorites INTEGER DEFAULT 0,
    followers_gained INTEGER DEFAULT 0,

    -- 关键质量指标
    like_rate REAL,                    -- 点赞率 = likes / views
    comment_rate REAL,                 -- 评论率 = comments / views
    share_rate REAL,                   -- 分享率 = shares / views
    favorite_rate REAL,                -- 收藏率 = favorites / views
    completion_rate REAL,              -- 完播率
    avg_watch_seconds REAL,            -- 平均观看时长
    retention_3s REAL,                 -- 3秒留存
    retention_5s REAL,                 -- 5秒留存

    raw_payload TEXT,                  -- 原始平台数据（JSON）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 表5: `ai_feedback_labels` (AI归因标签表)
```sql
CREATE TABLE ai_feedback_labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generation_id TEXT NOT NULL,
    video_id TEXT NOT NULL,

    -- AI分析结果
    label_type TEXT,                   -- success/failure/risk/opportunity
    target_part TEXT,                  -- hook/script/visual/rhythm/topic/cta/publish_time
    label TEXT,                        -- 具体标签，如"开头数字强钩子"
    explanation TEXT,                  -- 归因说明
    confidence REAL,                   -- 置信度 0-1

    -- 是否进入学习
    is_accepted BOOLEAN DEFAULT 1,     -- 可人工否决错误归因
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 表6: `strategy_experiments` (策略实验表)
```sql
CREATE TABLE strategy_experiments (
    id TEXT PRIMARY KEY,               -- 实验ID
    niche TEXT,
    hypothesis TEXT,                   -- 假设：如"3秒内出现具体数字会提升完播"
    strategy_patch TEXT,               -- 策略变更（JSON）
    sample_size INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running',     -- running/won/lost/inconclusive
    result_summary TEXT,
    started_at TIMESTAMP,
    ended_at TIMESTAMP
);
```

---

## 三、核心模块设计

### 3.1 生成追踪模块 (`tracking.py`)

```python
class GenerationTracker:
    """追踪AI生成的内容"""

    def record_generation(
        self,
        script: str,
        niche: str,
        reference_videos: list[str],
        hook_type: str,
        generation_params: dict
    ) -> str:
        """
        记录一次内容生成
        返回：generation_id
        """
        pass

    def link_to_published_video(
        self,
        generation_id: str,
        video_id: str,
        published_at: datetime
    ):
        """
        关联生成内容与发布的视频
        """
        pass

    def update_performance(
        self,
        video_id: str,
        likes: int,
        views: int,
        comments: int,
        shares: int
    ):
        """
        更新视频表现数据
        """
        pass
```

### 3.2 效果评估模块 (`evaluator.py`)

```python
class PerformanceEvaluator:
    """评估内容表现"""

    def evaluate_video(self, video_id: str) -> dict:
        """
        评估视频是否爆款
        返回：{
            "is_viral": bool,
            "performance_score": float,
            "success_factors": list,
            "failure_reasons": list
        }
        """
        pass

    def get_viral_threshold(self, niche: str) -> dict:
        """
        获取该领域的爆款阈值
        返回：{"likes": 10000, "views": 100000, ...}
        """
        pass

    def analyze_success_factors(self, video_data: dict) -> list:
        """
        分析成功因素
        - hook类型是否有效
        - 文案结构是否合理
        - 情绪触发是否到位
        """
        pass

    def analyze_failure_reasons(self, video_data: dict) -> list:
        """
        分析失败原因
        - hook不够吸引
        - 节奏拖沓
        - 情绪不足
        """
        pass
```

### 3.3 模式学习模块 (`learner.py`)

```python
class PatternLearner:
    """从数据中学习模式"""

    def update_pattern_stats(self):
        """
        更新所有模式的统计数据
        - 计算成功率
        - 分析趋势
        - 调整权重
        """
        pass

    def detect_trends(self) -> list[dict]:
        """
        检测新兴趋势
        返回：[
            {
                "pattern": "某种hook类型",
                "trend": "rising",
                "recent_success_rate": 0.75,
                "previous_success_rate": 0.45
            }
        ]
        """
        pass

    def identify_declining_patterns(self) -> list[dict]:
        """
        识别衰退模式（以前有效，现在不行了）
        """
        pass

    def discover_new_patterns(self) -> list[dict]:
        """
        发现新模式
        - 从成功案例中提取共同特征
        - 使用LLM分析为什么这些案例成功
        """
        pass
```

### 3.4 策略优化模块 (`optimizer.py`)

```python
class StrategyOptimizer:
    """优化生成策略"""

    def get_recommended_strategy(self, niche: str) -> dict:
        """
        获取当前最优策略
        返回：{
            "hook_types": [
                {"type": "悬念式", "weight": 0.35, "success_rate": 0.72},
                {"type": "痛点式", "weight": 0.28, "success_rate": 0.68},
                ...
            ],
            "trending_keywords": ["AI", "副业", "赚钱"],
            "optimal_duration": "60-90秒",
            "emotion_intensity": "high",
            "best_posting_time": "19:00-21:00"
        }
        """
        pass

    def adjust_weights(self):
        """
        根据最近表现调整各模式的权重
        - 成功率高的 → 权重上升
        - 成功率低的 → 权重下降
        - 过时的 → 权重归零
        """
        pass

    def generate_insights(self) -> list[str]:
        """
        生成可操作的洞察
        返回：[
            "最近'痛点式开头'成功率下降15%，建议减少使用",
            "发现新趋势：'数据对比'类内容点赞率提升40%",
            "建议：在19:00-21:00发布，平均播放量提升2.3倍"
        ]
        """
        pass
```

---

## 四、实施计划

### 阶段1：基础追踪（第1-2周）

**目标**：能记录生成内容和手动更新效果数据

**任务**：
1. 创建数据库表结构
2. 实现 `GenerationTracker` 基础功能
3. 在现有生成流程中集成追踪
4. 提供手动更新效果数据的接口

**验收标准**：
- 每次生成内容都自动记录
- 可以手动输入视频表现数据
- 可以查看历史生成记录

### 阶段2：自动效果追踪（第3-4周）

**目标**：自动抓取已发布视频的表现数据

**任务**：
1. 实现定时任务（每天运行）
2. 调用抖音API或爬虫获取视频数据
3. 自动更新 `generated_content` 表
4. 实现 `PerformanceEvaluator` 评估逻辑
5. 按1小时、6小时、24小时、72小时、7天保存反馈快照

**验收标准**：
- 发布7天后自动获取效果数据
- 自动判断是否爆款
- 生成评估报告
- 可以看到每条视频的阶段性表现变化

### 阶段3：模式学习（第5-6周）

**目标**：从数据中学习，发现规律

**任务**：
1. 实现 `PatternLearner` 核心算法
2. 定期更新 `pattern_performance` 表
3. 实现趋势检测算法
4. 实现 `FeedbackAnalyzer` 归因分析
5. 实现 `CommentLearner` 评论区学习
6. 生成学习洞察

**验收标准**：
- 能统计各模式的成功率
- 能识别上升/下降趋势
- 能发现新兴模式
- 能把评论区高频问题转成下一条选题建议

### 阶段4：策略优化（第7-8周）

**目标**：根据学习结果优化生成策略

**任务**：
1. 实现 `StrategyOptimizer`
2. 动态调整推荐权重
3. 集成到现有生成流程
4. 提供策略建议面板

**验收标准**：
- 生成时优先使用高成功率模式
- 每周生成策略优化报告
- 爆款率相比初始版本提升20%+

---

## 五、关键技术点

### 5.1 爆款判定标准

**多维度评分模型**：
```python
def calculate_performance_score(data: dict, niche: str) -> float:
    """
    综合评分 =
        点赞权重 * (实际点赞 / 领域平均点赞) +
        播放权重 * (实际播放 / 领域平均播放) +
        互动权重 * (评论+分享) / (领域平均互动)

    爆款阈值：score >= 3.0（即各维度平均超过3倍）
    """
    pass
```

### 5.2 趋势检测算法

**时间窗口对比**：
```python
def detect_trend(pattern: str, niche: str) -> str:
    """
    对比最近30天 vs 之前30天的成功率
    - 提升 > 20% → "rising"
    - 下降 > 20% → "declining"
    - 其他 → "stable"
    """
    pass
```

### 5.3 权重调整策略

**指数移动平均（EMA）**：
```python
def update_weight(current_weight: float, recent_success_rate: float) -> float:
    """
    新权重 = 0.7 * 当前权重 + 0.3 * (成功率 * 2)

    这样可以：
    - 平滑调整，避免剧烈波动
    - 对最近表现更敏感
    - 成功率高的模式权重逐渐上升
    """
    pass
```

### 5.4 新模式发现

**使用LLM分析**：
```python
def discover_new_patterns(successful_cases: list) -> list:
    """
    1. 筛选最近30天成功率 > 70% 的案例
    2. 提取文案特征（关键词、结构、情绪）
    3. 用LLM分析共同点
    4. 生成新的模式定义
    """
    prompt = f"""
    分析以下爆款文案的共同特征：
    {successful_cases}

    请提取：
    1. 开头hook的共同模式
    2. 结构上的相似性
    3. 情绪触发的共同点
    4. 独特的表达方式
    """
    pass
```

---

## 六、数据流示例

### 示例1：完整学习闭环

```
Day 0: 生成内容
├─ 用户输入："帮我写一个关于AI副业的爆款文案"
├─ 系统查询当前最优策略
│  └─ 推荐：痛点式hook（权重0.35，成功率68%）
├─ 生成文案
└─ 记录到 generated_content
   ├─ generation_id: "gen_001"
   ├─ hook_type: "痛点式"
   ├─ reference_videos: ["video_123", "video_456"]

Day 1: 用户发布
└─ 关联视频ID
   └─ video_id: "douyin_789"

Day 7: 自动追踪
├─ 抓取数据
│  ├─ likes: 15,000
│  ├─ views: 200,000
│  └─ comments: 500
├─ 评估结果
│  ├─ is_viral: True
│  ├─ performance_score: 3.8
│  └─ success_factors: ["hook有效", "节奏紧凑", "痛点精准"]
└─ 更新 pattern_performance
   └─ "痛点式" 成功率: 68% → 69%

Day 30: 模式学习
├─ 分析最近30天数据
│  ├─ "痛点式" 成功率: 69%（稳定）
│  ├─ "数据对比式" 成功率: 45% → 72%（上升）
│  └─ "故事式" 成功率: 65% → 52%（下降）
├─ 调整权重
│  ├─ "数据对比式": 0.15 → 0.28
│  └─ "故事式": 0.25 → 0.18
└─ 生成洞察
   └─ "发现新趋势：数据对比类内容点赞率提升60%"

Day 31: 下次生成
└─ 优先推荐"数据对比式"hook
```

---

## 七、视频发布后的反馈学习闭环

这一部分是系统真正“越用越会爆”的核心。发布后的反馈不能只看最终点赞数，而要把视频从发布到衰减的全过程拆成可学习信号，再反向更新生成策略。

### 7.1 反馈闭环总览

```
视频发布
  ↓
绑定 generation_id 与 video_id
  ↓
分阶段采集反馈数据
  ├─ 1小时：冷启动表现
  ├─ 6小时：推荐池扩散能力
  ├─ 24小时：内容质量初判
  ├─ 72小时：增长潜力判断
  └─ 7天：最终效果归档
  ↓
AI做表现归因
  ├─ 为什么涨？
  ├─ 为什么停？
  ├─ 哪个内容元素有效？
  └─ 哪个生成策略需要调整？
  ↓
进入学习系统
  ├─ 更新模式权重
  ├─ 生成新洞察
  ├─ 发起小流量实验
  └─ 形成下一次生成约束
```

### 7.2 反馈信号分层

发布后的反馈分为四类，分别对应不同的学习价值。

| 信号层级 | 核心指标 | 说明 | 学习用途 |
|---|---|---|---|
| 曝光层 | 播放量、推荐量、播放增长速度 | 平台是否愿意继续推 | 判断选题与账号匹配度 |
| 吸引层 | 3秒留存、5秒留存、平均观看时长 | 开头是否抓人 | 优化hook、开场画面、第一句话 |
| 内容层 | 完播率、复播率、收藏率 | 内容是否有价值或爽点 | 优化结构、节奏、信息密度 |
| 互动层 | 点赞率、评论率、分享率、涨粉率 | 是否触发情绪和传播 | 优化情绪触发、争议点、CTA |

**关键原则**：
- 播放量高但互动低：选题可能对，但表达不够强。
- 留存低但互动率高：开头弱，后段内容可能有价值。
- 完播高但分享低：内容顺，但传播钩子不够。
- 评论高但点赞低：可能有争议，需要区分正向争议和负向反感。

### 7.3 分阶段反馈判断

#### 1小时：冷启动诊断

目标是判断视频是否过了第一轮小流量池。

```python
def diagnose_1h_feedback(data: dict) -> dict:
    """
    重点看：
    - 初始播放增长速度
    - 3秒/5秒留存
    - 点赞率是否明显低于账号均值
    """
    return {
        "stage": "cold_start",
        "diagnosis": "hook_passed",  # hook_passed/hook_failed/insufficient_data
        "learning_target": ["hook", "first_frame", "opening_sentence"]
    }
```

**学习规则**：
- 3秒留存低 → 降低该hook模式权重，标记“开头吸引不足”。
- 3秒留存高但点赞低 → hook能吸引，但正文承接不足。
- 初始播放低 → 可能是选题/发布时间/账号标签不匹配，不直接否定文案。

#### 6小时：扩散能力诊断

目标是判断视频是否从第一轮推荐进入第二轮推荐。

```python
def diagnose_6h_feedback(data: dict) -> dict:
    """
    重点看：
    - 播放增长是否继续
    - 完播率是否达标
    - 分享率/评论率是否触发扩散
    """
    pass
```

**学习规则**：
- 完播率高、分享率低 → 内容完整，但缺少传播理由。
- 评论率高、播放继续增长 → 争议点或情绪点有效，应提取为可复用模式。
- 播放停止增长 → 进入“推荐衰减”分析，找出卡点。

#### 24小时：内容质量初判

目标是形成初步的成功/失败归因。

```python
def diagnose_24h_feedback(data: dict) -> dict:
    """
    输出：
    - 初步评分
    - 主要成功因素
    - 主要失败因素
    - 是否需要做相似选题变体
    """
    pass
```

**学习规则**：
- 24小时表现超过账号均值2倍 → 进入“可复制候选”。
- 某类标签连续3条低于均值 → 暂时降权。
- 高收藏低点赞 → 说明实用价值强，可改成教程/清单/步骤类变体继续测试。

#### 72小时：增长潜力判断

目标是识别“慢热型内容”和“短爆型内容”。

```python
def diagnose_72h_feedback(data: dict) -> dict:
    """
    判断：
    - 是否仍在增长
    - 是否值得二创/复刻
    - 是否进入成功案例库
    """
    pass
```

**学习规则**：
- 72小时仍稳定增长 → 说明选题长尾价值高，增加同主题深挖。
- 前6小时爆、72小时停 → 说明情绪强但信息价值不足，可做更强交付版。
- 评论区出现高频问题 → 直接生成下一条视频的选题。

#### 7天：最终归档学习

目标是确认最终标签，并更新长期策略。

```python
def finalize_7d_learning(video_id: str) -> dict:
    """
    输出最终学习结果：
    - viral / potential / normal / failed
    - 可复用模式
    - 应避免模式
    - 下次生成策略补丁
    """
    pass
```

### 7.4 AI归因分析

AI每次分析视频反馈时，需要同时看“生成时记录”和“发布后结果”，避免只凭结果倒推。

```python
class FeedbackAnalyzer:
    """把发布后的数据转成AI可学习的归因标签"""

    def analyze(self, generation_id: str, snapshot: dict) -> dict:
        """
        输入：
        - 原始文案
        - 生成参数
        - 使用的参考案例
        - 发布后表现数据
        - 评论区样本

        输出：
        {
            "summary": "这条视频开头有效，但中段信息密度不足",
            "labels": [
                {
                    "label_type": "success",
                    "target_part": "hook",
                    "label": "开头使用具体收益数字",
                    "confidence": 0.82
                },
                {
                    "label_type": "failure",
                    "target_part": "rhythm",
                    "label": "第二段解释过长导致完播下降",
                    "confidence": 0.71
                }
            ],
            "strategy_patch": {
                "increase": ["数字对比式hook", "3秒内抛结果"],
                "decrease": ["长铺垫解释"],
                "next_tests": ["同选题改成清单结构", "评论区问题二创"]
            }
        }
        """
        pass
```

### 7.5 评论区反馈学习

评论区是最直接的用户需求反馈，应该单独进入学习系统。

| 评论类型 | 示例 | 学习动作 |
|---|---|---|
| 追问型 | “具体怎么做？” | 生成教程型续集 |
| 质疑型 | “这不现实吧？” | 生成反驳/澄清型内容 |
| 共鸣型 | “我也是这样” | 强化情绪表达模式 |
| 求资源型 | “工具在哪？” | 增加清单、步骤、工具推荐 |
| 争议型 | “普通人根本做不到” | 判断是否可转为争议传播点 |

```python
class CommentLearner:
    """从评论区提取下一轮选题和表达优化点"""

    def extract_comment_insights(self, comments: list[str]) -> dict:
        return {
            "top_questions": [],
            "user_pain_points": [],
            "objections": [],
            "next_video_ideas": [],
            "language_patterns": []
        }
```

### 7.6 策略更新机制

策略更新不能简单地“成功就加权、失败就降权”，需要按置信度、样本量、时间衰减处理。

```python
def update_strategy_weight(
    old_weight: float,
    performance_delta: float,
    sample_size: int,
    confidence: float,
    recency_factor: float
) -> float:
    """
    新权重 = 旧权重 + 表现增量 * 样本量系数 * 置信度 * 时间衰减

    避免：
    - 单条爆款导致策略过拟合
    - 老数据长期占据权重
    - 平台偶然流量误导AI
    """
    pass
```

**权重更新规则**：
- 单条视频只产生“候选洞察”，不直接大幅改策略。
- 连续3条同类成功，进入正式加权。
- 连续3条同类失败，进入降权观察。
- 样本不足时，生成“实验建议”，不生成“确定结论”。
- 最近30天数据权重大于历史数据。

### 7.7 探索与利用机制

为了持续输出爆款，系统需要保留实验能力，不能只复制过去成功的套路。

```python
def choose_generation_strategy(niche: str) -> dict:
    """
    80% 利用：选择当前成功率最高的策略
    20% 探索：测试新模式、新选题、新结构
    """
    if random.random() < 0.8:
        return optimizer.get_best_strategy(niche)
    return optimizer.get_experimental_strategy(niche)
```

**探索来源**：
1. 最近爆款评论区高频问题
2. 外部热点趋势
3. 新出现的高表现结构
4. 旧模式的新包装
5. AI提出但尚未验证的假设

### 7.8 下一次生成如何使用反馈

生成新视频前，AI必须读取最近学习结果，形成“生成约束”。

```python
def build_generation_constraints(niche: str) -> dict:
    return {
        "must_use": [
            "开头3秒内出现具体结果",
            "前15秒完成痛点+收益承诺"
        ],
        "prefer": [
            "数据对比式hook",
            "普通人视角",
            "评论区追问作为选题"
        ],
        "avoid": [
            "超过20秒才进入主题",
            "泛泛讲趋势不落到行动"
        ],
        "experiment": [
            "同选题测试清单结构",
            "加入反常识开头"
        ]
    }
```

生成Prompt中加入：

```text
你必须参考最近30天学习结果：
1. 优先使用成功率上升的hook和结构。
2. 避免最近连续失败的表达方式。
3. 如果使用实验策略，必须标记 experiment_id。
4. 输出时说明本次文案采用了哪些学习结论。
```

### 7.9 爆款能力飞轮

```
发布更多视频
  ↓
获得更多真实反馈
  ↓
AI提取成功/失败规律
  ↓
策略权重更新
  ↓
下一次生成更贴近平台和用户
  ↓
爆款率提升
  ↓
更多高质量案例进入学习库
```

最终目标不是让AI记住某一条爆款文案，而是让AI持续学习：
- 哪些选题正在变热
- 哪些hook正在失效
- 哪些表达最容易留住用户
- 哪些情绪最容易触发评论和分享
- 哪些评论可以变成下一条爆款选题

---

## 八、UI/交互设计

### 8.1 生成时显示策略建议

```
🎯 当前最优策略（AI副业领域）

推荐Hook类型：
  1. 数据对比式 ⭐⭐⭐⭐⭐ (成功率72%, 趋势↑)
  2. 痛点式     ⭐⭐⭐⭐   (成功率69%, 趋势→)
  3. 悬念式     ⭐⭐⭐     (成功率58%, 趋势→)

热门关键词：AI工具、副业、月入过万
最佳时长：60-90秒
建议发布时间：19:00-21:00

💡 最新洞察：
  - "数据对比"类内容最近表现优异，建议多用
  - "故事式开头"效果下降，暂时少用
```

### 8.2 效果追踪面板

```
📊 生成内容效果追踪

总计生成：127条
已发布：89条
爆款率：23.6% (21/89)

最近7天表现：
  ✅ 爆款：3条
  📈 潜力：5条（播放量持续增长）
  📉 低效：2条

待追踪：12条（发布未满7天）
```

### 8.3 学习洞察报告

```
🧠 AI学习报告（2024-05-01 至 2024-05-31）

📈 上升趋势：
  1. "数据对比式"开头 - 成功率提升27%
  2. "反常识"类内容 - 平均点赞数提升40%

📉 下降趋势：
  1. "故事式"开头 - 成功率下降13%
  2. 视频时长>120秒 - 完播率下降25%

🆕 新发现：
  1. 在开头3秒内展示"具体数字"的视频，点赞率提升35%
  2. 使用"普通人"视角的内容，分享率提升50%

💡 行动建议：
  1. 增加"数据对比式"内容比例
  2. 控制视频时长在60-90秒
  3. 开头3秒必须有"钩子"（数字/反常识/痛点）
```

---

## 九、风险与应对

### 9.1 数据质量问题

**风险**：抓取的数据不准确或不完整

**应对**：
- 多次验证（间隔24小时再次抓取）
- 异常值检测（突然暴涨可能是刷量）
- 人工审核机制（标记可疑数据）

### 9.2 过拟合风险

**风险**：过度优化导致内容同质化

**应对**：
- 保持一定的随机性（20%探索，80%利用）
- 定期引入新模式（即使权重低也要尝试）
- 多样性奖励（避免所有内容都用同一种hook）

### 9.3 趋势滞后

**风险**：等7天才评估，趋势可能已经过时

**应对**：
- 缩短评估周期（3天初步评估，7天最终评估）
- 实时监控热点话题（外部数据源）
- 快速实验机制（新趋势立即小批量测试）

---

## 十、成功指标

### 短期（1-2个月）
- ✅ 所有生成内容都有追踪记录
- ✅ 自动效果追踪准确率 > 95%
- ✅ 能识别至少3个上升/下降趋势

### 中期（3-6个月）
- ✅ 爆款率相比初始版本提升 20%
- ✅ 每月发现至少1个新兴模式
- ✅ 策略优化建议采纳率 > 60%

### 长期（6-12个月）
- ✅ 爆款率稳定在 30% 以上
- ✅ AI能自主发现并验证新模式
- ✅ 用户反馈："AI越来越懂我的领域"

---

## 十一、技术栈

- **数据库**：SQLite（轻量级，易部署）
- **定时任务**：APScheduler（Python定时任务库）
- **数据分析**：Pandas + NumPy
- **LLM调用**：现有的Claude API
- **可视化**：Streamlit（已有UI框架）

---

## 十二、MVP落地方案：手动反馈到AI学习

第一版先不做复杂自动化，目标是用最小成本跑通“视频发布后，AI能复盘并优化下一条”的闭环。

### 12.1 MVP目标

**一句话目标**：

让每条已发布视频都变成一条可复盘、可学习、可影响下一次生成的样本。

第一版只做四件事：
1. 记录AI生成了什么
2. 手动录入视频发布后的表现数据
3. AI输出结构化复盘
4. 下次生成前读取最近复盘，形成生成约束

暂时不做：
- 自动抓取平台数据
- 复杂机器学习模型
- 完整A/B实验系统
- 自动改写所有生成策略

### 12.2 每条视频需要填写的数据

发布后先手动填写即可。

```text
基础信息：
- generation_id：对应哪一次AI生成
- 视频标题/选题
- 原始文案
- 视频时长
- 发布时间
- 发布平台

表现数据：
- 播放量
- 点赞数
- 评论数
- 收藏数
- 分享数
- 完播率
- 2s跳出率
- 5s完播率
- 平均播放时长
- 平均播放占比

人工备注：
- 封面是否正常
- 配音是否正常
- 画面是否有明显问题
- 是否蹭了热点
- 是否投流/互推
- 评论区典型反馈
```

### 12.3 AI每条视频必须输出的复盘格式

每条视频录入数据后，AI必须按固定格式复盘，不能随意发挥。

```text
一、总体判断
- 结果等级：爆款 / 潜力 / 普通 / 失败
- 核心结论：一句话说明这条为什么是这个结果

二、数据诊断
- 播放诊断：平台是否给了基础流量
- 开头诊断：2s跳出率、5s完播率说明什么
- 正文诊断：平均播放时长、平均播放占比说明什么
- 互动诊断：点赞、评论、收藏、分享说明什么

三、归因标签
- 成功点：哪些可以保留
- 失败点：哪些必须修改
- 不确定因素：哪些可能不是文案导致的

四、下一条优化建议
- 同选题是否继续做
- 要换什么hook
- 要改什么结构
- 时长建议
- 结尾如何触发评论/收藏/分享

五、策略补丁
- must_use：下次必须使用
- prefer：下次优先使用
- avoid：下次避免使用
- experiment：下次可以测试
```

### 12.4 单条视频复盘示例

以这条数据为例：

```text
播放1011
点赞27
评论0
收藏4
完播率11.01%
2s跳出率29.9%
平均播放时长23秒
5s完播率48.72%
平均播放占比26.25%
```

AI应输出：

```json
{
  "result_level": "普通",
  "main_diagnosis": "开头有一定停留能力，但前5秒承诺不够强，中后段留存明显不足。",
  "data_reading": {
    "traffic": "平台给了基础小流量，但没有继续放大",
    "hook": "2s跳出率不算灾难，说明第一眼没有完全失败；5s完播率偏弱，说明前5秒没有建立强期待",
    "body": "平均播放占比26.25%，完播率11.01%，说明正文节奏和信息密度撑不住当前时长",
    "interaction": "点赞率尚可，但评论为0，说明没有触发强共鸣、争议或提问"
  },
  "keep": [
    "选题可以继续测试",
    "内容有轻微认可度"
  ],
  "improve": [
    "压缩视频时长",
    "前5秒直接抛结果/冲突/收益",
    "中段每10-15秒加入一个新刺激点",
    "结尾增加评论触发问题"
  ],
  "strategy_patch": {
    "must_use": [
      "前5秒明确看完收益",
      "正文改成更短的3点结构"
    ],
    "prefer": [
      "45-60秒版本",
      "反常识或数据对比式hook"
    ],
    "avoid": [
      "90秒以上长铺垫",
      "先讲背景再讲重点",
      "只有观点没有具体例子"
    ],
    "experiment": [
      "同选题改成清单结构",
      "结尾加入二选一争议问题"
    ]
  }
}
```

### 12.5 10条样本后的规律总结

单条复盘只能指导下一条，10条以上才开始看规律。

每积累10条视频，AI生成一次小结：

```text
最近10条视频规律：
1. 哪类选题播放最高
2. 哪类hook的5s完播率最高
3. 哪个时长区间完播最好
4. 哪种结构点赞率最高
5. 哪种结尾更容易评论
6. 哪些模式连续失败，需要暂停
7. 下一轮建议重点测试什么
```

10条样本总结后，才允许调整长期策略权重：

```text
连续有效 → 提升权重
连续失败 → 降低权重
只有单条有效 → 标记为候选，不直接定论
数据矛盾 → 继续实验，不写死规则
```

### 12.6 MVP使用流程

日常使用流程：

```text
1. AI生成文案
   ↓
2. 系统记录 generation_id、选题、hook、结构、文案
   ↓
3. 用户发布视频
   ↓
4. 用户手动录入表现数据
   ↓
5. AI生成结构化复盘
   ↓
6. 系统保存策略补丁
   ↓
7. 下一次生成前，AI读取最近策略补丁
   ↓
8. 新文案自动避开失败点，强化有效点
```

### 12.7 第一版验收标准

第一版完成后，应满足：

- 每条生成内容都有唯一 `generation_id`
- 可以手动录入视频表现数据
- AI能对单条视频输出固定格式复盘
- AI能生成 `must_use / prefer / avoid / experiment` 策略补丁
- 下一次生成文案时能读取最近5-10条复盘结论
- 累积10条后能输出阶段性规律总结

---

## 十三、下一步行动

### 立即开始（本周）
1. [ ] 定义MVP反馈录入字段
2. [ ] 实现 `GenerationTracker`，记录每次AI生成
3. [ ] 实现手动录入视频表现数据
4. [ ] 实现单条视频AI复盘模板
5. [ ] 让下一次生成读取最近复盘结论

### 第一个里程碑（2周内）
1. [ ] 跑通10条视频的手动反馈闭环
2. [ ] 生成第一份10条样本规律总结
3. [ ] 验证策略补丁能影响下一次文案生成

### 第一次迭代（1个月内）
1. [ ] 增加反馈数据面板
2. [ ] 完成基础模式学习
3. [ ] 再考虑自动效果追踪

---

## 附录：代码文件结构

```
viral_agent/
├── tracking.py          # 生成追踪模块
├── evaluator.py         # 效果评估模块
├── learner.py           # 模式学习模块
├── optimizer.py         # 策略优化模块
├── feedback_analyzer.py # 发布后反馈归因模块
├── comment_learner.py   # 评论区学习模块
├── experiments.py       # 策略实验与探索模块
├── database.py          # 数据库操作封装
├── scheduler.py         # 定时任务调度
└── insights.py          # 洞察生成模块

migrations/
└── 001_create_tables.sql  # 数据库初始化脚本

tests/
├── test_tracking.py
├── test_evaluator.py
├── test_learner.py
└── test_optimizer.py
```

---

**文档版本**：v1.0
**创建日期**：2024-05-06
**作者**：Kiro AI
**状态**：待评审
