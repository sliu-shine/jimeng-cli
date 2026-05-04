# 抖音采集 Web UI 使用指南

## 功能概述

抖音采集 Web UI 是一个可视化的批量视频下载工具，支持：

- ✅ 多账号批量下载
- ✅ 可视化账号管理
- ✅ 实时进度显示
- ✅ 自动队列处理
- ✅ 按标签分类保存
- ✅ 智能文件命名

## 系统架构

```
┌─────────────────┐
│   Web UI 界面   │  ← 用户在浏览器中操作
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│   web_app.py    │  ← Python 后端服务
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│ douyin_selenium │  ← Selenium 自动化
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│ Tampermonkey    │  ← 浏览器脚本（扫描视频）
└─────────────────┘
```

## 快速开始

### 1. 安装依赖

```bash
# 安装 Selenium 相关依赖
pip install -r requirements_selenium.txt

# 或手动安装
pip install selenium webdriver-manager requests
```

### 2. 安装 Tampermonkey 脚本

1. 在 Chrome 浏览器中安装 [Tampermonkey 扩展](https://chrome.google.com/webstore/detail/tampermonkey/)
2. 打开 `douyin/douyin_downloader/tampermonkey_script.js`
3. 复制脚本内容
4. 在 Tampermonkey 中创建新脚本，粘贴并保存

### 3. 启动 Web 服务

```bash
python3 web_app.py
```

服务默认运行在 `http://127.0.0.1:8765`

### 4. 访问抖音采集页面

在浏览器中打开：
```
http://127.0.0.1:8765/douyin
```

## 使用流程

### 方式一：自动模式（推荐）

1. **添加账号**
   - 在 Web UI 中点击"添加账号"
   - 输入抖音用户主页链接（例如：`https://www.douyin.com/user/MS4wLjABAAAA...`）
   - 可以一次添加多个账号

2. **配置参数**
   - 保存路径：视频保存位置（默认：`./douyin_videos`）
   - 最低点赞数：只下载点赞数超过此值的视频（默认：1000）
   - 按标签分类：是否按视频标签创建子文件夹

3. **开始下载**
   - 点击"开始下载"按钮
   - 系统会自动打开 Chrome 浏览器
   - Tampermonkey 脚本会自动扫描每个账号的视频
   - 扫描完成后自动跳转到下一个账号
   - 所有账号处理完成后自动关闭浏览器

4. **查看进度**
   - Web UI 实时显示当前处理的账号
   - 显示每个账号的状态（待处理/处理中/已完成）
   - 显示下载进度和日志信息

### 方式二：手动模式

如果需要手动控制每个步骤：

1. 在命令行运行：
   ```bash
   python3 douyin/douyin_selenium.py
   ```

2. 输入账号链接（支持多个，用逗号分隔）

3. 浏览器打开后，在页面右侧会出现 Tampermonkey 控制面板

4. 点击"🔍 扫描爆款视频"

5. 确认视频列表后，回到终端按 Enter 继续

6. 系统自动下载视频

## Tampermonkey 脚本功能

### 队列显示面板

当从 Web UI 启动下载任务时，Tampermonkey 脚本会在抖音页面右上角显示一个队列面板：

```
┌─────────────────────────┐
│  📥 下载队列            │
├─────────────────────────┤
│ 总账号数：5             │
│ 已完成：2               │
│ 待处理：3               │
├─────────────────────────┤
│ 当前账号                │
│ 账号 MS4wLjABAAAA...    │
│ ████████░░ 80%          │
│ 处理中...               │
├─────────────────────────┤
│ ✅ 账号 1: 已完成       │
│ ✅ 账号 2: 已完成       │
│ 🔄 账号 3: 处理中       │
│ ⏳ 账号 4: 待处理       │
│ ⏳ 账号 5: 待处理       │
├─────────────────────────┤
│ [🔍 开始扫描] [⏭️ 下一个]│
└─────────────────────────┘
```

### 自动化流程

1. **自动扫描**：脚本自动扫描当前页面的视频
2. **进度更新**：实时更新扫描进度（10% → 30% → 50% → 80% → 100%）
3. **自动跳转**：扫描完成后提示跳转到下一个账号
4. **状态同步**：所有状态通过 localStorage 与 Python 后端同步

## 文件命名规则

下载的视频文件名格式：
```
[点赞数]_[标题]_[视频ID].mp4
```

示例：
```
[2.5w赞]_超好看的舞蹈教学_7234567890123456789.mp4
```

同时会生成对应的元数据文件：
```
[2.5w赞]_超好看的舞蹈教学_7234567890123456789.json
```

元数据包含：
- 视频 ID
- 视频链接
- 点赞数
- 标题
- 描述
- 标签
- 作者
- 下载时间

## 按标签分类

启用"按标签分类"后，视频会按第一个标签创建子文件夹：

```
douyin_videos/
├── 舞蹈/
│   ├── [2.5w赞]_超好看的舞蹈教学_xxx.mp4
│   └── [1.8w赞]_古典舞分解动作_xxx.mp4
├── 美食/
│   ├── [3.2w赞]_家常菜做法_xxx.mp4
│   └── [2.1w赞]_烘焙教程_xxx.mp4
└── 旅游/
    └── [4.5w赞]_云南旅游攻略_xxx.mp4
```

## API 接口

Web UI 提供以下 API 接口：

### 获取账号列表
```
GET /api/douyin/accounts
```

### 保存账号列表
```
POST /api/douyin/accounts
Content-Type: application/json

{
  "accounts": [
    {"url": "https://www.douyin.com/user/xxx", "enabled": true},
    {"url": "https://www.douyin.com/user/yyy", "enabled": true}
  ]
}
```

### 启动下载任务
```
POST /api/douyin/start
Content-Type: application/json

{
  "accounts": ["https://www.douyin.com/user/xxx"],
  "save_path": "./douyin_videos",
  "min_likes": 1000,
  "organize_by_tag": true,
  "auto_next": true
}
```

### 停止下载任务
```
POST /api/douyin/stop
```

### 获取任务状态
```
GET /api/douyin/status

返回：
{
  "is_running": true,
  "accounts": [
    {
      "url": "https://www.douyin.com/user/xxx",
      "status": "processing",
      "progress": 60,
      "video_count": 15,
      "downloaded": 8,
      "total": 15
    }
  ],
  "logs": [
    {"level": "info", "message": "开始下载...", "time": "2024-01-01T12:00:00"}
  ]
}
```

## 故障排查

### 1. 浏览器无法启动

**问题**：`selenium.common.exceptions.WebDriverException`

**解决方案**：
```bash
# 更新 ChromeDriver
pip install --upgrade webdriver-manager

# 或手动下载 ChromeDriver
# https://chromedriver.chromium.org/downloads
```

### 2. Tampermonkey 脚本未生效

**检查**：
- 确认脚本已启用
- 确认在抖音用户主页（`https://www.douyin.com/user/*`）
- 刷新页面重试

### 3. 视频下载失败

**可能原因**：
- 视频地址提取失败（抖音页面结构变化）
- 网络连接问题
- 视频已被删除或设为私密

**解决方案**：
- 检查网络连接
- 更新脚本以适配新的页面结构
- 跳过失败的视频，继续下载其他视频

### 4. 无法读取视频列表

**问题**：`❌ 未找到视频列表`

**解决方案**：
- 确认 Tampermonkey 脚本已运行
- 手动点击"🔍 扫描爆款视频"按钮
- 检查浏览器控制台是否有错误信息

### 5. 进度不更新

**问题**：Web UI 进度条不动

**解决方案**：
- 刷新 Web UI 页面
- 检查后端日志是否有错误
- 确认浏览器未被手动关闭

## 高级配置

### 修改滚动次数

在 `douyin_selenium.py` 中修改：
```python
downloader.run_batch(
    user_urls=accounts,
    scroll_times=20,  # 增加滚动次数以加载更多视频
    min_likes=min_likes,
    auto_mode=auto_next
)
```

### 自定义浏览器选项

在 `douyin_selenium.py` 的 `init_driver()` 方法中添加：
```python
# 启用无头模式（后台运行）
chrome_options.add_argument('--headless')

# 禁用图片加载（加快速度）
prefs = {"profile.managed_default_content_settings.images": 2}
chrome_options.add_experimental_option("prefs", prefs)
```

### 修改最大日志数量

在 `web_app.py` 中修改：
```python
def add_douyin_log(level: str, message: str) -> None:
    # ...
    if len(douyin_task["logs"]) > 200:  # 改为保留200条
        douyin_task["logs"] = douyin_task["logs"][-200:]
```

## 注意事项

1. **登录状态**：首次使用需要在浏览器中登录抖音账号，登录状态会被保存
2. **反爬虫**：下载间隔设置为 2 秒，避免请求过快被限制
3. **存储空间**：确保有足够的磁盘空间存储视频
4. **网络稳定**：建议在网络稳定的环境下使用
5. **合法使用**：仅用于个人学习和研究，请勿用于商业用途

## 技术栈

- **后端**：Python 3.8+
- **Web 框架**：http.server (内置)
- **自动化**：Selenium + ChromeDriver
- **浏览器脚本**：Tampermonkey (JavaScript)
- **前端**：HTML + CSS + JavaScript (原生)

## 更新日志

### v2.0 (2024-01-01)
- ✨ 新增 Web UI 界面
- ✨ 支持多账号批量下载
- ✨ 增强 Tampermonkey 脚本，添加队列显示
- ✨ 实现自动化流程，无需手动操作
- ✨ 添加实时进度显示和日志输出
- 🐛 修复视频地址提取失败的问题
- 🐛 修复文件名非法字符导致保存失败

### v1.0 (2023-12-01)
- 🎉 初始版本
- ✅ 基础的视频下载功能
- ✅ Tampermonkey 脚本扫描视频

## 贡献

欢迎提交 Issue 和 Pull Request！

## 许可证

MIT License
