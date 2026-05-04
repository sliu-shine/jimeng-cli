# 抖音爆款视频下载和分析工具

自动下载抖音爆款视频，提取逐字稿，并导入到爆款文案智能体。

## 功能特性

- ✅ 批量下载抖音账号的爆款视频（按点赞数筛选）
- ✅ 自动提取视频逐字稿（支持 Whisper 和 Groq）
- ✅ 导出为爆款智能体可用格式
- ✅ 一键导入到知识库

## 安装依赖

```bash
# 安装 Python 依赖
pip install -r requirements_douyin.txt

# 安装 ffmpeg（用于音频提取）
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg

# Windows
# 从 https://ffmpeg.org/download.html 下载
```

## 使用方法

### 方式 1: 完整流水线（推荐）

一键完成下载、转录、导入全流程：

```bash
python douyin_cli.py pipeline \
  --users "https://www.douyin.com/user/MS4wLjABAAAA..." \
          "https://www.douyin.com/user/MS4wLjABAAAA..." \
  --max-per-user 20 \
  --min-likes 100000 \
  --method whisper \
  --model large-v3
```

然后导入到爆款智能体：

```bash
python import_douyin_samples.py ./douyin_analysis/viral_samples.json
```

### 方式 2: 分步执行

#### 步骤 1: 下载视频

```bash
python douyin_cli.py download \
  --users "https://www.douyin.com/user/MS4wLjABAAAA..." \
  --max-per-user 20 \
  --min-likes 100000 \
  --output ./douyin_analysis
```

#### 步骤 2: 提取逐字稿

```bash
python douyin_cli.py transcribe \
  --video-dir ./douyin_analysis/videos \
  --method whisper \
  --model large-v3
```

#### 步骤 3: 导入知识库

```bash
python import_douyin_samples.py ./douyin_analysis/viral_samples.json
```

## 参数说明

### 通用参数

- `--users`: 抖音用户主页链接（可多个）
- `--max-per-user`: 每个账号最多下载数量（默认 20）
- `--min-likes`: 最低点赞数筛选（默认 100000）
- `--output`: 输出目录（默认 ./douyin_analysis）

### 转录参数

- `--method`: 识别方法
  - `whisper`: 本地 Whisper 模型（推荐，免费）
  - `groq`: Groq API（更快，需要 API key）
- `--model`: Whisper 模型名称
  - `tiny`: 最快，准确率较低
  - `base`: 快速，准确率一般
  - `small`: 平衡
  - `medium`: 较慢，准确率高
  - `large-v3`: 最慢，准确率最高（推荐）

## 获取抖音用户链接

1. 打开抖音网页版：https://www.douyin.com
2. 搜索目标账号
3. 进入主页，复制链接（格式：`https://www.douyin.com/user/MS4wLjABAAAA...`）

## 使用 Groq API（可选）

Groq 提供免费的 Whisper API，速度更快：

```bash
# 设置 API key
export GROQ_API_KEY="your_groq_api_key"

# 使用 groq 方法
python douyin_cli.py pipeline \
  --users "..." \
  --method groq
```

获取 Groq API key: https://console.groq.com

## 输出目录结构

```
douyin_analysis/
├── videos/                    # 下载的视频
│   ├── MS4wLjABAAAA.../      # 按用户分组
│   │   ├── 7123456789_150000likes.mp4
│   │   ├── 7123456789_150000likes.json        # 视频元数据
│   │   ├── 7123456789_150000likes.mp3         # 提取的音频
│   │   └── 7123456789_150000likes.transcript.json  # 逐字稿
└── viral_samples.json         # 导出的爆款样本
```

## 注意事项

1. **API 限制**: 使用的是开源 API 服务，可能有频率限制
2. **下载速度**: 建议设置合理的并发数，避免触发风控
3. **存储空间**: 视频文件较大，注意磁盘空间
4. **模型选择**:
   - 首次使用 Whisper 会自动下载模型（large-v3 约 3GB）
   - 推荐使用 `base` 或 `small` 模型快速测试
   - 正式使用推荐 `large-v3` 获得最佳准确率

## 故障排查

### 下载失败

- 检查用户链接是否正确
- 检查网络连接
- 尝试降低并发数

### 转录失败

- 确认 ffmpeg 已安装：`ffmpeg -version`
- 检查视频文件是否完整
- 尝试使用较小的 Whisper 模型

### 导入失败

- 确认爆款智能体已正确安装
- 检查 Claude CLI 是否可用：`claude --version`

## 示例工作流

```bash
# 1. 下载 3 个账号的爆款视频（点赞 10 万+）
python douyin_cli.py pipeline \
  --users \
    "https://www.douyin.com/user/账号1" \
    "https://www.douyin.com/user/账号2" \
    "https://www.douyin.com/user/账号3" \
  --max-per-user 15 \
  --min-likes 100000 \
  --method whisper \
  --model base

# 2. 导入到爆款智能体
python import_douyin_samples.py ./douyin_analysis/viral_samples.json

# 3. 使用智能体生成文案
python viral_agent_ui.py
# 在界面中输入主题，生成爆款文案
```

## 高级用法

### 只下载不转录

```bash
python douyin_cli.py download --users "..." --max-per-user 50
```

### 只转录已有视频

```bash
python douyin_cli.py transcribe --video-dir ./my_videos --method groq
```

### 自定义筛选条件

修改 `douyin_downloader/downloader.py` 中的筛选逻辑，可以添加：
- 评论数筛选
- 完播率筛选
- 时长筛选
- 发布时间筛选

## 相关文档

- [爆款智能体使用文档](viral_agent/README.md)
- [Whisper 模型文档](https://github.com/openai/whisper)
- [Groq API 文档](https://console.groq.com/docs)
