# 抖音相关工具

本目录包含所有抖音视频下载、分析和导入相关的工具。

## 目录结构

```
douyin/
├── douyin_downloader/      # 抖音视频下载器核心模块
│   └── tampermonkey_script.js  # 浏览器脚本
├── douyin_analysis/        # 视频分析工具
├── douyin_cli.py          # 命令行工具
├── douyin_selenium.py     # Selenium 自动化脚本（推荐）
├── import_videos.py       # 视频导入到知识库
├── import_douyin_samples.py  # 导入抖音样本
├── manual_import_samples.py  # 手动导入样本
└── requirements_selenium.txt  # Selenium 依赖
```

## 主要功能

### 1. Selenium 自动化下载（推荐）

**特点**：
- ✅ 自动化浏览器操作，模拟真实用户行为
- ✅ 支持采集视频标题和标签
- ✅ 按对标账号命名一级目录：`douyin_videos/账号名/视频标题/文件`
- ✅ 支持 `.m4a`、`.mp3`、`.mp4` 等媒体文件
- ✅ 多音频候选或无声视频流时优先用 yt-dlp 按视频页兜底下载音频
- ✅ 自动保存元数据 JSON 文件
- ✅ **支持多账号连续下载**

**使用步骤**：

```bash
# 1. 安装依赖
pip install -r requirements_selenium.txt

# 2. 安装 Tampermonkey 脚本
# 在 Chrome 浏览器中安装 Tampermonkey 扩展
# 然后导入 douyin/douyin_downloader/tampermonkey_script.js

# 3. 运行下载脚本
python douyin/douyin_selenium.py

# 4. 输入账号链接
# 单个账号：https://www.douyin.com/user/xxx
# 多个账号：https://www.douyin.com/user/xxx1,https://www.douyin.com/user/xxx2
# 或者分行输入多个链接

# 5. 在浏览器中操作
# - 点击「🔍 扫描爆款视频」按钮
# - 确认视频列表
# - 点击「⬇️ 下载选中视频」按钮
# - 回到终端按 Enter 继续

# 6. 多账号模式
# 下载完第一个账号后，浏览器不会关闭
# 可以选择继续下载下一个账号，或者手动停止
```

**多账号下载示例**：

```bash
# 输入多个链接（逗号分隔）
链接: https://www.douyin.com/user/xxx1,https://www.douyin.com/user/xxx2,https://www.douyin.com/user/xxx3

# 或者分行输入
链接: https://www.douyin.com/user/xxx1
https://www.douyin.com/user/xxx2
https://www.douyin.com/user/xxx3

# 脚本会依次处理每个账号
# 每个账号下载完成后，会询问是否继续下一个
# 浏览器会保持打开状态，直到所有账号处理完毕
```

**文件目录规则**：

- 格式：`douyin_videos/账号名/视频标题/[点赞]_标题_videoId.m4a`
- 示例：`douyin_videos/狗狗执行官-Kiki/给小狗听一下这首歌/[17w赞]_给小狗听一下这首歌_7635636890410044722.m4a`
- 如果浏览器只能抓到分离流视频，脚本会跳过无声视频并尝试下载对应音频
- 每个视频会生成对应的 `.json` 元数据文件

### 2. 视频分析

使用 `douyin_analysis/` 中的工具对下载的视频进行分析。

### 3. 知识库导入

将下载的视频导入到爆款文案知识库：

```bash
# 推荐先预检：不调用 AI、不写知识库
python douyin/import_videos.py douyin_videos --no-transcribe --dry-run

# 使用已有 .transcription.json/.transcript.json/.txt 导入，不重新转录
python douyin/import_videos.py douyin_videos --no-transcribe

# 小批量试跑：只分析某个账号的前 5 条
python douyin/import_videos.py douyin_videos --no-transcribe --account "狗狗执行官-Kiki" --limit 5
```

导入脚本会递归扫描 `.mp4`、`.m4a`、`.mp3`、`.aac`、`.wav`，并按 `video_id` 去重；同一条视频同时有 `.mp4` 和 `.mp3` 时，优先选已有转录的音频文件。导入时会把点赞/互动数、互动等级、来源账号、频道分类、媒体路径和转录路径写入知识库 metadata。

支持的转录文件名：

- `视频名.transcription.json`
- `视频名.transcript.json`
- `视频名.txt`

## 注意事项

1. **登录状态**：首次运行需要手动登录抖音账号，后续会保持登录状态
2. **反爬虫**：脚本已隐藏 webdriver 特征，但仍需注意频率控制
3. **视频质量**：下载的是网页播放的视频质量，非原始上传质量
4. **存储空间**：确保有足够的磁盘空间存储视频文件
5. **网络稳定**：建议在网络稳定的环境下运行

## 故障排除

- **浏览器无法启动**：检查 Chrome 和 ChromeDriver 版本是否匹配
- **视频下载失败**：检查网络连接，或尝试降低下载频率
- **Tampermonkey 脚本不工作**：确认脚本已启用，刷新页面重试
- **元数据缺失**：确认使用的是最新版本的 Tampermonkey 脚本
