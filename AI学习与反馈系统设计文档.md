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

**验收标准**：
- 发布7天后自动获取效果数据
- 自动判断是否爆款
- 生成评估报告

### 阶段3：模式学习（第5-6周）

**目标**：从数据中学习，发现规律

**任务**：
1. 实现 `PatternLearner` 核心算法
2. 定期更新 `pattern_performance` 表
3. 实现趋势检测算法
4. 生成学习洞察

**验收标准**：
- 能统计各模式的成功率
- 能识别上升/下降趋势
- 能发现新兴模式

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

## 七、UI/交互设计

### 7.1 生成时显示策略建议

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

### 7.2 效果追踪面板

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

### 7.3 学习洞察报告

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

## 八、风险与应对

### 8.1 数据质量问题

**风险**：抓取的数据不准确或不完整

**应对**：
- 多次验证（间隔24小时再次抓取）
- 异常值检测（突然暴涨可能是刷量）
- 人工审核机制（标记可疑数据）

### 8.2 过拟合风险

**风险**：过度优化导致内容同质化

**应对**：
- 保持一定的随机性（20%探索，80%利用）
- 定期引入新模式（即使权重低也要尝试）
- 多样性奖励（避免所有内容都用同一种hook）

### 8.3 趋势滞后

**风险**：等7天才评估，趋势可能已经过时

**应对**：
- 缩短评估周期（3天初步评估，7天最终评估）
- 实时监控热点话题（外部数据源）
- 快速实验机制（新趋势立即小批量测试）

---

## 九、成功指标

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

## 十、技术栈

- **数据库**：SQLite（轻量级，易部署）
- **定时任务**：APScheduler（Python定时任务库）
- **数据分析**：Pandas + NumPy
- **LLM调用**：现有的Claude API
- **可视化**：Streamlit（已有UI框架）

---

## 十一、下一步行动

### 立即开始（本周）
1. [ ] 创建数据库表结构
2. [ ] 实现 `GenerationTracker` 基础类
3. [ ] 在现有生成流程中集成追踪

### 第一个里程碑（2周内）
1. [ ] 完成手动效果更新功能
2. [ ] 生成第一份效果追踪报告
3. [ ] 验证数据流完整性

### 第一次迭代（1个月内）
1. [ ] 实现自动效果追踪
2. [ ] 完成基础模式学习
3. [ ] 生成第一份AI学习报告

---

## 附录：代码文件结构

```
viral_agent/
├── tracking.py          # 生成追踪模块
├── evaluator.py         # 效果评估模块
├── learner.py           # 模式学习模块
├── optimizer.py         # 策略优化模块
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
