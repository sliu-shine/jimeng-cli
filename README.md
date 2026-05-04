# 即梦 CLI 工具集

这是一个集成了多个功能的即梦（Dreamina）视频生成工具集，包含：

1. **Dreamina 队列管理器** - 批量视频生成队列系统
2. **爆款文案智能体** - 抖音爆款视频分析与文案生成
3. **抖音视频采集工具** - 自动化下载和分析抖音视频

## 📁 项目结构

```
jimeng-cli/
├── douyin/                    # 抖音视频采集工具
│   ├── douyin_downloader/     # 下载器核心模块
│   ├── douyin_cli.py          # 命令行工具
│   ├── douyin_selenium.py     # Selenium 自动化脚本
│   ├── import_videos.py       # 视频导入知识库
│   └── README.md              # 抖音工具说明
├── viral_agent/               # 爆款文案智能体核心
│   ├── knowledge_base.py      # 向量知识库
│   ├── analyzer.py            # 爆款模式分析
│   └── generator.py           # 文案生成器
├── tests/                     # 测试文件
├── scripts/                   # 工具脚本
├── web_app.py                 # Dreamina 队列 Web 界面
├── viral_agent_ui.py          # 爆款智能体 Web 界面
├── dreamina_queue.py          # Dreamina 队列命令行工具
└── README.md                  # 本文件
```

## 🚀 快速开始

### 环境准备

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements_viral.txt
pip install -r douyin/requirements_douyin.txt

# 配置环境变量
export ANTHROPIC_API_KEY="your-claude-api-key"
```

详细安装指南请查看 [SETUP.md](./SETUP.md)

### 使用场景

#### 场景 1：批量生成即梦视频

启动 Web 界面：
```bash
python3 web_app.py
```

访问 http://127.0.0.1:8765

**功能特性：**
- ✅ 多项目管理，独立队列
- ✅ 可视化表单快速添加任务
- ✅ 串行队列执行，避免并发冲突
- ✅ 自动轮询任务状态
- ✅ 失败重试和断点续传
- ✅ 实时日志查看

或使用命令行：
```bash
python3 dreamina_queue.py \
  --queue-file ./example.queue.txt \
  --output-root ./queue-output
```

#### 场景 2：爆款文案智能体

**完整流程：**

1. **采集抖音爆款视频**
```bash
cd douyin
python3 douyin_selenium.py
```

2. **导入知识库**
```bash
python3 douyin/import_videos.py ./douyin_videos --method groq
```

3. **生成爆款文案**
```bash
python3 viral_agent_ui.py
# 访问 http://127.0.0.1:7860
```

或命令行生成：
```bash
python3 -m viral_agent generate "如何提升工作效率" --num 3
```

详细使用指南：
- [快速开始](./快速开始.md)
- [爆款文案智能体使用指南](./爆款文案智能体使用指南.md)
- [操作文档](./操作文档.md)

## 📚 核心功能

### 1. Dreamina 队列管理器

**适用场景：**
- 批量视频生成需要排队
- 避免并发冲突
- 自动化视频生产流程

**核心特性：**
- 串行队列执行
- 自动状态轮询
- 失败重试机制
- 多项目管理
- Web 可视化界面

**队列文件格式：**
```txt
# 每行一条 dreamina 命令
multimodal2video --image ./shot-01.png --prompt "电影感推镜" --duration=5 --ratio=9:16
text2video --prompt "女孩在便利店门口回头" --duration=5 --ratio=9:16
```

### 2. 爆款文案智能体

**工作流程：**
1. 采集抖音爆款视频（高点赞数）
2. 自动转录视频为文字（Whisper/Groq）
3. 使用 Claude 分析爆款模式
4. 存入向量知识库
5. 基于学习的模式生成新文案

**核心能力：**
- 🎯 爆款模式识别（开场钩子、情绪节奏、行动召唤）
- 📊 向量知识库检索
- 🤖 Claude 驱动的文案生成
- 📈 多样本学习和模式提取

### 3. 抖音视频采集工具

**采集方式：**
- Selenium 自动化浏览器
- 配合 Tampermonkey 脚本
- 反爬虫检测优化
- 保持登录状态

**功能：**
- 批量下载用户视频
- 自动提取视频元数据
- 支持爆款视频筛选

## 🛠️ 常用命令

### Dreamina 队列

```bash
# Web 界面
python3 web_app.py

# 命令行执行队列
python3 dreamina_queue.py --queue-file queue.txt --output-root ./output

# 断点续传
python3 dreamina_queue.py --queue-file queue.txt --resume

# 失败即停止
python3 dreamina_queue.py --queue-file queue.txt --stop-on-failure
```

### 爆款智能体

```bash
# 启动 Web 界面
python3 viral_agent_ui.py

# 生成文案
python3 -m viral_agent generate "主题" --num 3

# 查看知识库统计
python3 -m viral_agent stats

# 导入视频
python3 douyin/import_videos.py ./videos --method groq
```

### 抖音采集

```bash
# Selenium 自动化下载
python3 douyin/douyin_selenium.py

# 命令行工具
python3 douyin/douyin_cli.py --user-url "https://www.douyin.com/user/xxx"
```

## 📋 依赖要求

**核心依赖：**
- Python 3.10+
- ffmpeg（视频处理）
- Chrome/Chromium（Selenium）

**Python 包：**
- anthropic（Claude API）
- selenium（浏览器自动化）
- openai-whisper（语音转录）
- chromadb（向量数据库）
- gradio（Web 界面）

详见 `requirements_viral.txt` 和 `douyin/requirements_douyin.txt`

## 🔧 配置说明

### 环境变量

```bash
# Claude API（必需）
export ANTHROPIC_API_KEY="sk-ant-xxx"

# Groq API（可选，用于快速转录）
export GROQ_API_KEY="gsk_xxx"
```

### Dreamina CLI

确保已安装并登录 Dreamina CLI：
```bash
dreamina --version
dreamina login
```

## 📖 文档索引

- [快速开始](./快速开始.md) - 5 分钟上手指南
- [SETUP.md](./SETUP.md) - 详细安装配置
- [爆款文案智能体使用指南](./爆款文案智能体使用指南.md) - 完整功能说明
- [操作文档](./操作文档.md) - 操作步骤详解
- [douyin/README.md](./douyin/README.md) - 抖音工具说明

## 🐛 故障排查

### Dreamina 队列问题

**问题：任务一直 pending**
- 检查 dreamina CLI 是否正常：`dreamina --version`
- 查看日志：`.webui/runner.log`
- 确认是否需要 Web 端授权

**问题：下载失败**
- 检查输出目录权限
- 确认 submit_id 有效性

### 爆款智能体问题

**问题：转录失败**
- 检查 ffmpeg：`ffmpeg -version`
- 尝试使用 Groq API 代替 Whisper
- 确认视频文件完整性

**问题：生成质量不好**
- 增加知识库样本（建议 > 20 个）
- 确保样本是真实爆款（高点赞数）
- 检查 Claude API 配置

### 抖音采集问题

**问题：Selenium 检测失败**
- 更新 ChromeDriver
- 检查反检测配置
- 确认 Tampermonkey 脚本已安装

**问题：无法下载视频**
- 检查网络连接
- 确认抖音账号登录状态
- 查看浏览器控制台错误

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

## 🔗 相关链接

- [Dreamina 官网](https://dreamina.com)
- [Claude API 文档](https://docs.anthropic.com)
- [Whisper 项目](https://github.com/openai/whisper)
