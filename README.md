# Dreamina 串行队列器

这个仓库现在有两种用法：

- 命令行队列脚本：`dreamina_queue.py`
- 可视化页面：`web_app.py`

两者底层都用同一个队列执行器。

适用场景：

- 即梦视频生成需要排队
- 当前账号/模型只适合单并发
- 你不想盯着上一个任务什么时候结束

脚本会做三件事：

1. 逐条提交队列里的 `dreamina` 命令
2. 根据返回的 `submit_id` 持续调用 `dreamina query_result`
3. 当前任务 `success` 或 `fail` 后，再继续下一个任务

## 前提

- 已安装并能直接执行 `dreamina`
- 已经登录过 `dreamina`
- 队列里的命令本身是正确可跑的

建议先单独跑通一条命令，再放进队列。

## 可视化页面

启动本地页面：

```bash
python3 web_app.py
```

默认地址：

```txt
http://127.0.0.1:8765
```

页面能力：

- 给小白用的“视频快速添加”表单
- 直接编辑队列内容
- 配置 `dreamina` 路径、输出目录、轮询间隔、超时时间
- 一键启动队列
- 一键停止队列
- 查看任务列表、`submit_id`、成功失败情况
- 查看最近运行日志

页面默认会把：

- 队列文件写到 `.webui/web.queue.json`
- 启动日志写到 `.webui/runner.log`
- 运行元信息写到 `.webui/runner.json`

如果你完全不懂 CLI，就只看页面左上那块“视频快速添加”：

1. 填提示词
2. 选时长、比例、模型
3. 上传图片/视频/音频，或者直接粘素材路径
4. 点“加入队列”
5. 再点“启动队列”

它会根据素材情况自动选择命令：

- 单张图片：`image2video`
- 多张图片故事分镜：`multiframe2video`
- 图/视频/音频混合参考：`multimodal2video`

页面里的 `@图片名 / @视频名 / @音频名` 只是本地编辑辅助，提交前会自动转成普通文字，不是即梦 CLI 官方支持的素材绑定语法。

多图时不要把它理解成“给每张图绑定一个角色名”。当前 CLI 更适合按顺序做分镜：

- 第 1 张图
- 过渡到第 2 张图
- 再过渡到第 3 张图

页面里已经加了“多图过渡提示词”，一行对应一个过渡段。

## 命令行用法

先准备一个队列文件，例如 [example.queue.txt](/Users/sliu/web-project/rich-projects/jimeng-cli/example.queue.txt)：

```txt
# 每行一条 dreamina 生成命令
multimodal2video --image ./assets/shot-01.png --prompt "把画面做成真实电影感，轻微推镜" --model_version=seedance2.0fast --duration=5 --ratio=9:16
multimodal2video --image ./assets/shot-02.png --prompt "延续上一镜的情绪，角色继续前进" --model_version=seedance2.0fast --duration=5 --ratio=9:16
text2video --prompt "手机竖屏9:16，真实纪实风格，女孩在便利店门口回头" --model_version=seedance2.0fast --duration=5 --ratio=9:16
```

然后执行：

```bash
python3 dreamina_queue.py \
  --queue-file ./example.queue.txt \
  --output-root ./queue-output
```

如果中途断了，可以续跑：

```bash
python3 dreamina_queue.py \
  --queue-file ./example.queue.txt \
  --output-root ./queue-output \
  --resume
```

## 队列文件格式

- 每行一条命令
- 可以写完整命令：`dreamina multimodal2video ...`
- 也可以省略前缀，只写子命令：`multimodal2video ...`
- 支持空行
- 支持 `#` 注释

## 输出内容

默认输出到 `./queue-output`：

- `queue-state.json`
  记录每个任务的状态、`submit_id`、失败原因、下载目录
- `logs/<任务名>/`
  保存提交和轮询的 stdout/stderr
- `<任务名>/`
  成功后通过 `dreamina query_result --download_dir` 下载的结果文件

如果你走可视化页面，默认输出目录会是 `./web-output`。

## 常用参数

```bash
python3 dreamina_queue.py \
  --queue-file ./example.queue.txt \
  --output-root ./queue-output \
  --poll-interval 20 \
  --timeout-seconds 7200 \
  --stop-on-failure
```

- `--poll-interval`
  轮询间隔，默认 30 秒
- `--timeout-seconds`
  单任务最长等待时间，默认 3 小时
- `--resume`
  从已有状态恢复
- `--stop-on-failure`
  一旦某个任务失败就停止；默认失败后继续跑后面的任务
- `--dreamina`
  指定 `dreamina` 可执行路径

## 建议

- 真正批量跑之前，先拿 2 条命令试跑
- 队列里尽量混合质量接近的任务，避免单个超长任务把后面全部堵住
- 如果 CLI 返回 `AigcComplianceConfirmationRequired`，先去 Dreamina Web 完成授权，再继续队列
