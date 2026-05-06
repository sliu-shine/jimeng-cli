# 剪映导入包生成器

本模块不再生成剪映私有草稿 JSON。新版剪映的本地草稿格式包含私有编码文件，手写 `draft_info.json` / `draft_content.json` 不稳定。

当前稳定方案是生成剪映可以正常导入的媒体包：

```text
jianying_import_packages/项目名_时间戳/
├── final.mp4
├── subtitles.srt
└── import_guide.json
```

## 命令行使用

```bash
python3 jianying/auto_workflow.py \
  --transcript "你的视频文案" \
  --videos "./web-output/**/*.mp4" \
  --project-name "自动生产视频"
```

也可以从文案文件读取：

```bash
python3 jianying/auto_workflow.py \
  --transcript ./script.txt \
  --videos "./videos/*.mp4"
```

## Web 使用

```bash
python3 jianying_web_server.py
```

打开：

```text
http://127.0.0.1:7862
```

选择视频和文案后，工具会输出 `final.mp4` 和 `subtitles.srt`。

## 导入剪映

1. 打开剪映专业版，点击「开始创作」。
2. 导入生成的 `final.mp4`。
3. 导入 `subtitles.srt`，或使用剪映自动识别字幕。
4. 在剪映中继续添加配音、滤镜、转场和精修。

## 依赖

需要安装 `ffmpeg`：

```bash
brew install ffmpeg
```
