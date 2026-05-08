# Sora 视频生成使用指南

## 概述

Sora 视频生成功能通过云雾 API 对接 OpenAI 的 Sora 2.0 模型，生成高质量真实感视频。

与即梦 Seedance（动画风格）不同，Sora 更擅长生成真实感的视频内容。

## 架构设计

```
文案输入
    ↓
sora_prompt_builder.py (提示词构建)
    ↓
队列 JSON 文件
    ↓
sora_queue.py (执行器)
    ↓
云雾 API (sora-2-all 模型)
    ↓
视频输出
```

## 环境配置

### 1. 设置云雾 API 密钥

```bash
export YUNWU_API_KEY="your-api-key-here"
```

### 2. （可选）自定义 API 地址

```bash
export YUNWU_BASE_URL="https://api.yunwu.ai"
```

## 使用方式

### 方式一：通过 UI 界面

1. 启动 UI：
```bash
python viral_agent_ui.py
```

2. 在浏览器中打开 `http://127.0.0.1:7860`

3. 进入 **"🎥 Sora 视频生成"** 标签页

4. 操作步骤：
   - 载入或粘贴文案
   - 点击 **"🎥 拆分为 Sora 2.0 视频提示词"**
   - 查看生成的提示词和队列 JSON
   - 保存队列到文件
   - 在命令行执行队列

### 方式二：通过 Python 代码

```python
from viral_agent.sora_prompt_builder import build_sora_outputs

# 输入文案
script = """
你知道猫咪为什么喜欢睡在你身边吗？
其实这不是偶然，当猫咪选择在你旁边睡觉时...
"""

# 生成提示词和队列
markdown, queue_json = build_sora_outputs(script)

# 保存队列
with open("sora_queue.json", "w", encoding="utf-8") as f:
    f.write(queue_json)

print(markdown)
```

### 方式三：命令行执行队列

```bash
# 基本用法
python sora_queue.py /path/to/sora_queue.json

# 指定输出目录
python sora_queue.py /path/to/sora_queue.json --output-dir /path/to/outputs
```

## 队列 JSON 格式

```json
{
  "version": 1,
  "segments": [
    {
      "id": "sora-segment-01",
      "name": "Sora视频片段01",
      "mode": "text2video",
      "prompt": "高质量真实感视频风格...",
      "duration": "10",
      "ratio": "16:9",
      "model_version": "sora-2-all",
      "images": [],
      "videos": [],
      "audios": [],
      "transition_prompts": []
    }
  ]
}
```

## 与 Seedance 的区别

| 特性 | Seedance (即梦) | Sora (云雾) |
|------|----------------|-------------|
| **风格** | 日系动画、水彩插画 | 真实感视频 |
| **时长** | 4-15秒 | 5-20秒 |
| **画风** | 二维手绘、厚涂插画 | 电影级真实画面 |
| **适用场景** | 治愈动画、科普动画 | 真实场景、纪实风格 |
| **API** | 即梦 API | 云雾 API |
| **执行器** | dreamina_queue.py | sora_queue.py |

## 提示词风格

### Seedance 提示词示例
```
温馨治愈日系二维手绘动画画风，吉卜力式温暖动画质感...
猫咪毛发蓬松柔软、根根分明，脸部表情拟人化...
```

### Sora 提示词示例
```
高质量真实感视频风格，电影级画面质感，自然光影...
猫咪毛发自然真实，表情生动自然，动作流畅...
```

## 常见问题

### 1. API 密钥错误

```
❌ 需要设置 YUNWU_API_KEY 环境变量
```

**解决方案：**
```bash
export YUNWU_API_KEY="your-api-key"
```

### 2. 任务超时

默认超时时间为 3 小时。如果任务超时，可以：
- 检查 API 服务状态
- 缩短视频时长
- 简化提示词

### 3. 视频下载失败

检查网络连接和输出目录权限。

## 扩展开发

### 添加新的视频模型

1. 在 `sora_queue.py` 中添加新的客户端类
2. 在 `YunwuSoraClient.submit_video_generation()` 中添加模型判断
3. 在 UI 中添加模型选项

### 自定义提示词模板

编辑 `viral_agent/sora_prompt_builder.py` 中的 `SORA_STYLE_TEMPLATE`：

```python
SORA_STYLE_TEMPLATE = (
    "你的自定义风格描述..."
)
```

## 性能优化

### 并行处理

目前队列是串行处理。如需并行，可以修改 `sora_queue.py`：

```python
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=3) as executor:
    futures = [executor.submit(process_segment, seg, client, output_dir)
               for seg in segments]
```

### 批量提交

如果 API 支持批量提交，可以一次性提交多个任务。

## 更新日志

### v1.0.0 (2026-05-08)
- ✅ 初始版本
- ✅ 支持 sora-2-all 模型
- ✅ UI 集成
- ✅ 队列执行器
- ✅ 提示词构建器

## 贡献

欢迎提交 Issue 和 Pull Request！

## 许可证

与主项目保持一致
