# 云雾 API 使用说明

## 简介

云雾 API 是一个 OpenAI 兼容的 API 服务，支持 Whisper 语音识别模型。相比本地 Whisper，具有以下优势：

- ✅ 速度快：无需本地 GPU，云端处理更快
- ✅ 稳定性好：专业服务，稳定可靠
- ✅ 国内友好：访问速度快，无需翻墙
- ✅ 中文优化：针对中文语音识别优化

## API 信息

- **Base URL**: `https://api.yunwu.ai/v1`
- **API Key**: `your-yunwu-api-key`
- **模型**: `whisper-1`

## 快速开始

### 1. 设置环境变量

```bash
export YUNWU_API_KEY="your-yunwu-api-key"
```

### 2. 测试 API

运行测试脚本验证 API 是否正常工作：

```bash
python test_yunwu_transcribe.py
```

这个脚本会：
1. 查找本地视频文件
2. 提取音频
3. 使用云雾 API 转录
4. 显示转录结果

### 3. 使用命令行工具

#### 提取单个目录的逐字稿

```bash
python douyin/douyin_cli.py transcribe \
  --video-dir ./videos \
  --method yunwu \
  --yunwu-api-key "your-yunwu-api-key"
```

#### 完整流程（下载 + 转录）

```bash
python douyin/douyin_cli.py pipeline \
  --users "https://www.douyin.com/user/MS4wLjABAAAA..." \
  --output ./videos \
  --max-per-user 10 \
  --min-likes 100000 \
  --method yunwu \
  --yunwu-api-key "your-yunwu-api-key"
```

### 4. 启动 Web 界面

使用快速启动脚本（已配置云雾 API）：

```bash
bash start_viral_agent.sh
```

或手动启动：

```bash
export YUNWU_API_KEY="your-yunwu-api-key"
python viral_agent_ui.py
```

## Python API 使用

### 基础用法

```python
from pathlib import Path
from douyin_downloader.transcriber import transcribe_with_yunwu, extract_audio

# 1. 提取音频
video_path = Path("./videos/test.mp4")
audio_path = extract_audio(video_path)

# 2. 使用云雾 API 转录
api_key = "your-yunwu-api-key"
result = transcribe_with_yunwu(audio_path, api_key)

# 3. 获取结果
print(result["text"])  # 完整文本
print(result["segments"])  # 时间片段
```

### 完整流程

```python
from pathlib import Path
from douyin_downloader.transcriber import extract_transcript

# 一键提取逐字稿
result = extract_transcript(
    video_path=Path("./videos/test.mp4"),
    method="yunwu",
    save_json=True,
    api_key="your-yunwu-api-key"
)

print(result["text"])
```

### 批量处理

```python
from pathlib import Path
from douyin_downloader.transcriber import batch_extract_transcripts

# 批量提取目录中所有视频的逐字稿
results = batch_extract_transcripts(
    video_dir=Path("./videos"),
    method="yunwu",
    api_key="your-yunwu-api-key"
)

for video_name, result in results.items():
    print(f"{video_name}: {result['text'][:100]}...")
```

## 技术细节

### API 接口

云雾 API 使用 OpenAI 兼容的接口格式：

```python
from openai import OpenAI

client = OpenAI(
    api_key="your-yunwu-api-key",
    base_url="https://api.yunwu.ai/v1"
)

with open("audio.mp3", "rb") as f:
    transcription = client.audio.transcriptions.create(
        file=f,
        model="whisper-1",
        language="zh",
        response_format="verbose_json"
    )

print(transcription.text)
```

### 返回格式

```json
{
  "text": "完整的转录文本",
  "segments": [
    {
      "start": 0.0,
      "end": 2.5,
      "text": "第一段文本"
    },
    {
      "start": 2.5,
      "end": 5.0,
      "text": "第二段文本"
    }
  ]
}
```

## 对比其他方案

| 方案 | 速度 | 成本 | 准确度 | 中文支持 | 需要 GPU |
|------|------|------|--------|----------|----------|
| 本地 Whisper | 慢 | 免费 | 高 | 好 | 是 |
| Groq API | 快 | 免费额度 | 高 | 好 | 否 |
| 云雾 API | 快 | 付费 | 高 | 优秀 | 否 |

## 常见问题

### 1. API Key 无效？

检查：
- API Key 是否正确复制
- 是否有网络连接
- 是否超出配额限制

### 2. 转录速度慢？

- 检查网络连接
- 音频文件不要太大（建议 < 25MB）
- 考虑批量处理时使用异步

### 3. 中文识别不准确？

- 确保音频质量良好
- 使用 `language="zh"` 参数
- 音频采样率建议 16kHz

### 4. 如何处理长视频？

云雾 API 支持较长的音频文件，但建议：
- 单个文件 < 25MB
- 时长 < 30 分钟
- 超长视频可以分段处理

## 更新日志

### v1.0.0 (2025-01-XX)

- ✅ 集成云雾 API
- ✅ 支持命令行工具
- ✅ 支持 Python API
- ✅ 添加测试脚本
- ✅ 更新使用文档

## 支持

如有问题，请查看：
- [爆款文案智能体使用指南](./爆款文案智能体使用指南.md)
- [云雾 API 官方文档](https://yunwu.ai/docs)
