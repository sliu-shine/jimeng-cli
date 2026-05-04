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
- ✅ 支持按标签分类保存
- ✅ 智能文件命名：`[标签]标题_videoId_点赞数.mp4`
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

**文件命名规则**：

- 格式：`[标签]标题_videoId_点赞数.mp4`
- 示例：`[舞蹈]超燃街舞表演_7123456789_125000.mp4`
- 如果有标签，会按标签创建子目录分类存储
- 每个视频会生成对应的 `.json` 元数据文件

### 2. 视频分析

使用 `douyin_analysis/` 中的工具对下载的视频进行分析。

### 3. 知识库导入

将下载的视频导入到爆款文案知识库：

```bash
python douyin/import_videos.py
```

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
