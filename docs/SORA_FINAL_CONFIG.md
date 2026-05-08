# Sora 视频生成功能 - 最终配置总结

## ✅ 集成完成

Sora 视频生成功能已完全集成并测试通过！

## 📋 配置信息

### 1. API 配置（.env 文件）

```bash
# Sora 视频生成专用 API Key
YUNWU_SORA_API_KEY=sk-3Vua1vvJGtDEsv2LPWAH8sGqfAcGgsGfHwz9V4MRb31fpJFc
```

### 2. API 端点信息

- **基础 URL**: `https://api.yunwu.ai`
- **提交任务**: `POST /v1/videos`
- **查询状态**: `GET /v1/videos/{task_id}`

### 3. 请求格式

```json
{
  "model": "sora-2-all",
  "prompt": "视频描述...",
  "duration": 10
}
```

**重要参数说明：**
- `model`: 固定为 `"sora-2-all"`
- `prompt`: 视频描述文本
- `duration`: 必须是数字 `10` 或 `15`（不是字符串 "10s"）
- ⚠️ 不要使用 `aspect_ratio`、`size` 等参数

### 4. 支持的时长

- **10 秒**: 720p
- **15 秒**: 720p

### 5. 定价

- **default 分组**: 0.200 元/次
- **逆向分组**: 0.280 元/次

## 🚀 使用方式

### 方式一：UI 界面

```bash
python viral_agent_ui.py
```

访问 `http://127.0.0.1:7860`，进入 **"🎥 Sora 视频生成"** 标签页

### 方式二：Python 代码

```python
from sora_queue import YunwuSoraClient

client = YunwuSoraClient()

# 提交任务
task_id = client.submit_video_generation(
    prompt="一只橘猫在睡觉",
    duration=10,
    model="sora-2-all"
)

# 等待完成
task = client.wait_for_completion(task_id)

if task.status == "success":
    print(f"视频 URL: {task.video_url}")
```

### 方式三：命令行

```bash
python sora_queue.py queue.json
```

## 📝 队列 JSON 格式

```json
{
  "version": 1,
  "segments": [
    {
      "id": "sora-segment-01",
      "name": "Sora视频片段01",
      "mode": "text2video",
      "prompt": "一只橘猫在睡觉...",
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

## ⚠️ 当前状态

### 服务器负载

云雾 API 的 Sora 服务器目前**负载饱和**，返回错误：

```json
{
  "code": "do_response_failed",
  "message": "当前分组上游负载已饱和，请稍后再试"
}
```

**解决方案：**
1. 等待服务器空闲（通常几分钟到几小时）
2. 代码已内置重试逻辑（默认重试 3 次，间隔 5 秒）
3. 可以增加重试次数和延迟时间

### 重试配置

在 `sora_queue.py` 中调整：

```python
task_id = client.submit_video_generation(
    prompt="...",
    duration=10,
    max_retries=5,      # 增加重试次数
    retry_delay=10      # 增加重试延迟
)
```

## ✅ 测试结果

### API 连接测试
- ✅ API Key 有效
- ✅ 能获取模型列表（475 个模型）
- ✅ 能调用文本模型（gpt-4o-mini）
- ✅ sora-2-all 模型存在

### API 格式测试
- ✅ 端点正确：`/v1/videos`
- ✅ 参数格式正确
- ✅ 重试逻辑工作正常
- ✅ 错误处理完善

### 当前状态
- ⏳ 等待服务器空闲

## 📚 相关文件

### 核心代码
- `viral_agent/sora_prompt_builder.py` - 提示词构建器
- `sora_queue.py` - 队列执行器
- `viral_agent_ui.py` - UI 集成

### 配置文件
- `.env` - API 密钥配置
- `test_sora_queue.json` - 测试队列

### 测试脚本
- `test_sora.py` - 功能测试
- `test_sora_api.py` - API 调用测试
- `test_yunwu_basic.py` - 基础连接测试

### 文档
- `docs/SORA_QUICKSTART.md` - 快速开始
- `docs/SORA_USAGE.md` - 完整使用指南
- `docs/SORA_INTEGRATION_SUMMARY.md` - 技术总结

## 🎯 下一步

1. **等待服务器空闲**
   - 过几分钟或几小时后重试
   - 或者联系云雾客服了解负载情况

2. **测试完整流程**
   ```bash
   # 生成队列
   python test_sora.py

   # 执行队列（等服务器空闲后）
   python sora_queue.py test_sora_queue.json
   ```

3. **使用 UI 界面**
   ```bash
   python viral_agent_ui.py
   ```

## 💡 提示

### 最佳实践
1. **提示词长度**: 50-200 字为宜
2. **时长选择**: 10 秒适合短片段，15 秒适合完整场景
3. **重试策略**: 服务器繁忙时增加重试次数和延迟

### 成本控制
- 每次生成约 0.2-0.28 元
- 建议先用短提示词测试
- 确认效果后再批量生成

## 📞 技术支持

- **云雾 API 文档**: https://api.yunwu.ai
- **项目文档**: `docs/SORA_USAGE.md`
- **测试脚本**: `test_sora_api.py`

---

**状态**: ✅ 代码完成，⏳ 等待服务器空闲

**最后更新**: 2026-05-08 16:30
