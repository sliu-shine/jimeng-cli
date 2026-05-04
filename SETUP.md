# 爆款文案智能体 - 安装指南

## 当前状态

✅ **已安装：**
- Selenium（浏览器自动化）
- webdriver-manager（ChromeDriver 管理）
- ffmpeg（视频处理）

❌ **需要安装：**
- anthropic（Claude API）
- chromadb（向量数据库）
- sentence-transformers（文本嵌入）
- openai-whisper（语音识别）
- groq（快速语音识别 API）
- aiohttp（异步 HTTP）
- aiofiles（异步文件操作）

## 安装步骤

### 1. 安装核心依赖（必需）

```bash
pip install -r requirements_viral.txt
```

这将安装：
- anthropic - Claude API 客户端
- chromadb - 向量知识库
- sentence-transformers - 文本嵌入模型
- openai-whisper - 本地语音识别
- groq - 云端语音识别（可选）

### 2. 安装抖音下载依赖（必需）

```bash
pip install -r requirements_douyin.txt
```

这将安装：
- aiohttp - 异步 HTTP 客户端
- aiofiles - 异步文件操作
- ffmpeg-python - FFmpeg Python 绑定

### 3. 配置 API Keys

#### Claude API（必需）

```bash
export ANTHROPIC_API_KEY="your-api-key"
```

获取地址：https://console.anthropic.com/

#### Groq API（可选，推荐）

```bash
export GROQ_API_KEY="your-api-key"
```

获取地址：https://console.groq.com/

优势：比本地 Whisper 快 10-20 倍，有免费额度

## 验证安装

```bash
python3 setup_check.py
```

应该看到所有依赖都显示 ✅

## 完整工作流

### 方式 1：使用 Selenium 自动化（推荐）

```bash
# 1. 采集视频（需要先安装 Tampermonkey 脚本）
python3 test_douyin_selenium.py

# 2. 导入到知识库（自动转录 + 分析）
python3 import_videos.py ./douyin_videos --method whisper

# 或使用 Groq（更快）
python3 import_videos.py ./douyin_videos --method groq --groq-api-key "your-key"

# 3. 启动 Web 界面
python3 viral_agent_ui.py
```

### 方式 2：使用完整流程脚本

```bash
python3 test_full_pipeline.py
```

这个脚本会引导你完成所有步骤。

## 常见问题

### Q: pip install 很慢？

使用国内镜像：
```bash
pip install -r requirements_viral.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### Q: Whisper 下载模型很慢？

首次使用会自动下载模型（~1GB），可以手动下载：
```bash
python3 -c "import whisper; whisper.load_model('base')"
```

### Q: 没有 GPU，Whisper 很慢？

使用 Groq API 代替：
```bash
python3 import_videos.py ./douyin_videos --method groq --groq-api-key "your-key"
```

### Q: ChromaDB 报错？

删除旧数据库重新开始：
```bash
rm -rf .viral_kb/
```

## 目录结构

```
jimeng-cli/
├── douyin_videos/           # Selenium 下载的视频
│   ├── *.mp4               # 视频文件
│   ├── *.json              # 元数据
│   └── *.txt               # 转录文本（自动生成）
├── .viral_kb/              # 知识库数据
│   └── chroma.sqlite3      # ChromaDB 数据库
├── setup_check.py          # 依赖检查脚本
├── import_videos.py        # 视频导入脚本（新）
├── test_douyin_selenium.py # Selenium 采集脚本
└── viral_agent_ui.py       # Web 界面
```

## 下一步

1. 运行 `pip install -r requirements_viral.txt`
2. 运行 `pip install -r requirements_douyin.txt`
3. 配置 `ANTHROPIC_API_KEY`
4. 运行 `python3 setup_check.py` 验证
5. 开始使用！
