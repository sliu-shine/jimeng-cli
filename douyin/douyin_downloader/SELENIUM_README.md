# 抖音视频批量下载 - Tampermonkey + Selenium 方案

## 📦 安装依赖

```bash
pip install selenium requests
```

安装 Chrome 浏览器和 ChromeDriver：
```bash
# macOS
brew install chromedriver

# 或者手动下载
# https://chromedriver.chromium.org/downloads
```

## 🚀 使用步骤

### 第一步：安装 Tampermonkey 脚本

1. 在 Chrome 浏览器安装 **Tampermonkey** 插件
   - 访问：https://www.tampermonkey.net/
   - 或在 Chrome 应用商店搜索 "Tampermonkey"

2. 安装脚本
   - 点击 Tampermonkey 图标 → "管理面板"
   - 点击 "+" 创建新脚本
   - 复制 `douyin_downloader/tampermonkey_script.js` 的全部内容
   - 粘贴并保存（Ctrl+S 或 Cmd+S）

### 第二步：运行 Python 自动化脚本

```bash
python douyin_selenium.py
```

### 第三步：在浏览器中操作

1. 脚本会自动打开抖音用户主页
2. 页面右侧会出现 **"📥 批量下载助手"** 面板
3. 设置筛选条件：
   - 最低点赞数（默认 2000）
   - 最多下载数量（默认 20）
4. 点击 **"🔍 扫描爆款视频"**
5. 确认视频列表无误
6. 点击 **"⬇️ 下载选中视频"**
7. 回到终端按 Enter 继续

### 第四步：自动下载

脚本会自动：
- 读取选中的视频列表
- 逐个打开视频页面
- 提取真实视频地址
- 下载到 `douyin_videos/` 目录

## 📁 输出文件

```
douyin_videos/
├── 7234567890123456789_5000.mp4  # 视频ID_点赞数.mp4
├── 7234567890123456790_8000.mp4
└── ...
```

## 🎯 工作流程

```
用户输入主页链接
    ↓
Selenium 打开浏览器
    ↓
自动滚动加载视频
    ↓
Tampermonkey 扫描爆款
    ↓
用户确认选择
    ↓
Python 读取列表
    ↓
逐个下载视频
    ↓
保存到本地
```

## ⚙️ 配置选项

### Tampermonkey 脚本

在脚本中可以修改：
- `@match` 规则（支持哪些页面）
- 默认筛选条件
- UI 样式

### Python 脚本

```python
# 修改输出目录
downloader = DouyinSeleniumDownloader(output_dir="my_videos")

# 修改滚动次数
downloader.run(user_url, scroll_times=20)

# 启用无头模式（不显示浏览器窗口）
# 在 init_driver() 中取消注释：
# chrome_options.add_argument('--headless')
```

## 🔧 故障排查

### 1. ChromeDriver 版本不匹配
```bash
# 检查 Chrome 版本
google-chrome --version

# 下载对应版本的 ChromeDriver
# https://chromedriver.chromium.org/downloads
```

### 2. 无法提取视频地址
- 抖音可能更新了页面结构
- 需要分析新的 DOM 结构或网络请求
- 可以使用浏览器开发者工具（F12）查看视频元素

### 3. 下载速度慢
- 调整 `time.sleep()` 时间
- 使用多线程下载（需修改代码）

### 4. 被检测为机器人
- 增加随机延迟
- 使用代理 IP
- 降低请求频率

## 🎨 进阶功能

### 自动转录和导入

下载完成后，自动转录并导入到爆款智能体：

```python
from douyin_downloader.transcriber import transcribe_video
from viral_agent.analyzer import analyze_script
from viral_agent import knowledge_base as kb

# 处理下载的视频
for video_file in Path("douyin_videos").glob("*.mp4"):
    video_id = video_file.stem.split('_')[0]
    likes = int(video_file.stem.split('_')[1])

    # 转录
    script = transcribe_video(str(video_file))

    # 分析
    analysis = analyze_script(script, likes=likes, niche='理财')

    # 导入知识库
    kb.add_script(video_id, script, analysis, {'likes': likes})

    print(f"✅ 已导入: {video_id}")
```

### 批量处理多个账号

```python
accounts = [
    "https://www.douyin.com/user/MS4wLjABAAAA...",
    "https://www.douyin.com/user/MS4wLjABAAAA...",
]

for account_url in accounts:
    downloader.run(account_url, scroll_times=10)
```

## 📝 注意事项

1. **遵守抖音服务条款**：仅用于个人学习研究
2. **控制请求频率**：避免被封禁
3. **尊重版权**：下载的内容仅供分析，不得商用
4. **数据安全**：不要上传敏感信息

## 🆚 对比其他方案

| 方案 | 优点 | 缺点 |
|------|------|------|
| **Tampermonkey + Selenium** | 稳定、可控、免费 | 需要手动确认 |
| 第三方 API | 自动化程度高 | 不稳定、可能收费 |
| 浏览器插件 | 简单易用 | 功能有限 |
| 桌面工具 | 功能全面 | 通常收费 |

## 🔗 相关文档

- [Selenium 文档](https://selenium-python.readthedocs.io/)
- [Tampermonkey 文档](https://www.tampermonkey.net/documentation.php)
- [ChromeDriver 下载](https://chromedriver.chromium.org/downloads)
