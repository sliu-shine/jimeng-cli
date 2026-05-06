#!/usr/bin/env python3
"""
剪映自动化 Web 服务器 V2（支持视频文件多选）
"""
import os
import sys
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jianying.import_package import create_import_package, natural_sort_key

class JianyingWebHandler(BaseHTTPRequestHandler):
    """剪映自动化 Web 请求处理器"""

    def log_message(self, format, *args):
        """自定义日志格式"""
        print(f"[{self.log_date_time_string()}] {format % args}")

    def do_GET(self):
        """处理 GET 请求"""
        parsed = urlparse(self.path)

        if parsed.path == '/' or parsed.path == '/index.html':
            self.send_html_page()
        elif parsed.path == '/api/videos/list':
            self.handle_list_videos()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Page not found")

    def do_POST(self):
        """处理 POST 请求"""
        parsed = urlparse(self.path)

        if parsed.path == '/api/jianying/create':
            self.handle_create_project()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "API not found")

    def handle_list_videos(self):
        """列出可用的视频文件"""
        try:
            root_dir = Path(__file__).parent
            projects_dir = root_dir / '.webui' / 'projects'
            web_output_dir = root_dir / 'web-output'

            videos = []

            # 扫描 .webui/projects 目录
            if projects_dir.exists():
                for project_folder in projects_dir.iterdir():
                    if project_folder.is_dir():
                        for video_file in project_folder.glob('*.mp4'):
                            videos.append({
                                'path': str(video_file),
                                'name': video_file.name,
                                'project': project_folder.name,
                                'size': video_file.stat().st_size,
                                'modified': video_file.stat().st_mtime
                            })

            # 扫描 web-output 目录
            if web_output_dir.exists():
                for video_file in web_output_dir.rglob('*.mp4'):
                    videos.append({
                        'path': str(video_file),
                        'name': video_file.name,
                        'project': video_file.parent.name,
                        'size': video_file.stat().st_size,
                        'modified': video_file.stat().st_mtime
                    })

            # 按路径自然排序，确保 Seedance动画片段01 排在 02 前面
            videos.sort(key=lambda x: natural_sort_key(f"{x['project']}/{x['name']}"))

            self.send_json_response({'success': True, 'videos': videos})

        except Exception as e:
            self.send_json_response({'success': False, 'error': str(e)})

    def handle_create_project(self):
        """处理创建剪映导入包的请求"""
        try:
            # 读取请求体
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            params = parse_qs(post_data)

            # 提取参数
            project_name = params.get('project_name', ['自动生产视频'])[0]
            transcript = params.get('transcript', [''])[0]
            video_files_str = params.get('video_files', [''])[0]
            add_subtitles = params.get('add_subtitles', ['false'])[0].lower() == 'true'

            # 验证输入
            if not transcript:
                self.send_json_response({'success': False, 'error': '请输入视频文案'})
                return

            if not video_files_str:
                self.send_json_response({'success': False, 'error': '请选择视频文件'})
                return

            # 解析视频文件列表
            video_files = [f.strip() for f in video_files_str.split(',') if f.strip()]
            if not video_files:
                self.send_json_response({'success': False, 'error': '请选择有效的视频文件'})
                return

            # 创建剪映导入包
            result = self.create_import_package(
                project_name=project_name,
                transcript=transcript,
                video_files=video_files,
                add_subtitles=add_subtitles,
            )

            self.send_json_response(result)

        except Exception as e:
            self.send_json_response({'success': False, 'error': f'服务器错误: {str(e)}'})

    def create_import_package(self, project_name, transcript, video_files, add_subtitles):
        """创建剪映导入包（final.mp4 + subtitles.srt）"""
        try:
            package = create_import_package(
                project_name=project_name,
                transcript=transcript,
                video_files=video_files,
                add_subtitles=add_subtitles,
            )

            return {
                'success': True,
                'output_path': package['output_path'],
                'final_video': package['final_video'],
                'subtitles': package['subtitles'],
                'total_duration': package['total_duration'],
                'segments_count': package['segments_count'],
                'message': f'导入包创建成功！共 {package["segments_count"]} 个片段，总时长 {package["total_duration"]:.1f}秒'
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def send_html_page(self):
        """发送 HTML 页面"""
        html = self.get_html_content()
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(html.encode('utf-8'))))
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def send_json_response(self, data):
        """发送 JSON 响应"""
        json_data = json.dumps(data, ensure_ascii=False)
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(json_data.encode('utf-8'))))
        self.end_headers()
        self.wfile.write(json_data.encode('utf-8'))

    def get_html_content(self):
        """获取 HTML 页面内容"""
        return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>剪映导入包生成器</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px 30px;
            text-align: center;
        }
        .header h1 { font-size: 36px; margin-bottom: 10px; font-weight: 700; }
        .header p { opacity: 0.95; font-size: 16px; }
        .content { padding: 40px 30px; }
        .form-group { margin-bottom: 25px; }
        .form-group label {
            display: block;
            font-weight: 600;
            margin-bottom: 8px;
            color: #333;
            font-size: 14px;
        }
        .form-group input[type="text"],
        .form-group textarea,
        .form-group select {
            width: 100%;
            padding: 12px 16px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 14px;
            transition: all 0.3s;
            font-family: inherit;
        }
        .form-group input:focus,
        .form-group textarea:focus,
        .form-group select:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        .form-group textarea {
            min-height: 140px;
            resize: vertical;
            line-height: 1.6;
        }
        .video-selector {
            border: 2px dashed #e0e0e0;
            border-radius: 8px;
            padding: 20px;
            margin-top: 10px;
            max-height: 400px;
            overflow-y: auto;
        }
        .video-selector.loading {
            text-align: center;
            color: #999;
        }
        .video-item {
            display: flex;
            align-items: center;
            padding: 12px;
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            margin-bottom: 10px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .video-item:hover {
            background: #f8f9fa;
            border-color: #667eea;
        }
        .video-item.selected {
            background: #e7f0ff;
            border-color: #667eea;
            border-width: 2px;
        }
        .video-item input[type="checkbox"] {
            width: 20px;
            height: 20px;
            margin-right: 12px;
            cursor: pointer;
            accent-color: #667eea;
        }
        .video-info {
            flex: 1;
        }
        .video-name {
            font-weight: 600;
            color: #333;
            margin-bottom: 4px;
        }
        .video-meta {
            font-size: 12px;
            color: #999;
        }
        .selected-count {
            background: #667eea;
            color: white;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 600;
            display: inline-block;
            margin-top: 10px;
        }
        .checkbox-group {
            display: flex;
            gap: 25px;
            margin-top: 12px;
            flex-wrap: wrap;
        }
        .checkbox-group label {
            display: flex;
            align-items: center;
            gap: 8px;
            font-weight: 500;
            cursor: pointer;
            color: #555;
        }
        .checkbox-group input[type="checkbox"] {
            width: 20px;
            height: 20px;
            cursor: pointer;
            accent-color: #667eea;
        }
        .btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 16px 40px;
            font-size: 16px;
            font-weight: 600;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s;
            width: 100%;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.5);
        }
        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        .example-btn {
            background: #f8f9fa;
            border: 2px solid #dee2e6;
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            margin-top: 10px;
            display: inline-block;
            transition: all 0.2s;
            font-weight: 500;
        }
        .example-btn:hover {
            background: #e9ecef;
            border-color: #adb5bd;
        }
        .result {
            margin-top: 30px;
            padding: 25px;
            border-radius: 12px;
            display: none;
            animation: slideIn 0.3s ease-out;
        }
        @keyframes slideIn {
            from { opacity: 0; transform: translateY(-10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .result.success {
            background: #d4edda;
            border: 2px solid #c3e6cb;
            color: #155724;
        }
        .result.error {
            background: #f8d7da;
            border: 2px solid #f5c6cb;
            color: #721c24;
        }
        .result h3 { margin-bottom: 15px; font-size: 20px; font-weight: 600; }
        .result p { margin: 8px 0; line-height: 1.8; }
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 25px;
        }
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
            .header h1 { font-size: 28px; }
            .content { padding: 30px 20px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎬 剪映导入包生成器</h1>
            <p>自动合并视频片段，生成 final.mp4 与 subtitles.srt</p>
        </div>

        <div class="content">
            <form id="jianyingForm">
                <div class="form-group">
                    <label>📝 项目名称</label>
                    <input type="text" name="project_name" value="自动生产视频" required>
                </div>

                <div class="form-group">
                    <label>📄 视频文案</label>
                    <textarea name="transcript" placeholder="输入视频文案，每句话一行..." required></textarea>
                    <button type="button" class="example-btn" onclick="loadExample()">📋 加载示例文案</button>
                </div>

                <div class="form-group">
                    <label>🎥 选择视频文件（支持多选）</label>
                    <div id="videoSelector" class="video-selector loading">
                        正在加载视频列表...
                    </div>
                    <div id="selectedCount" class="selected-count" style="display:none;">
                        已选择 <span id="countNumber">0</span> 个视频
                    </div>
                    <input type="hidden" name="video_files" id="videoFilesInput">
                </div>

                <div class="grid">
                    <div class="form-group">
                        <label>⚙️ 功能选项</label>
                        <div class="checkbox-group">
                            <label>
                                <input type="checkbox" name="add_subtitles" checked>
                                生成 SRT 字幕文件
                            </label>
                        </div>
                    </div>
                </div>

                <button type="submit" class="btn" id="submitBtn">
                    🎬 生成剪映导入包
                </button>
            </form>

            <div id="result" class="result"></div>
        </div>
    </div>

    <script>
        let selectedVideos = [];
        let allVideos = [];

        // 加载视频列表
        async function loadVideos() {
            try {
                const response = await fetch('/api/videos/list');
                const data = await response.json();

                if (data.success) {
                    allVideos = data.videos;
                    renderVideoList(allVideos);
                } else {
                    document.getElementById('videoSelector').innerHTML =
                        '<p style="color:#dc3545;">加载失败: ' + data.error + '</p>';
                }
            } catch (error) {
                document.getElementById('videoSelector').innerHTML =
                    '<p style="color:#dc3545;">加载失败: ' + error.message + '</p>';
            }
        }

        // 渲染视频列表
        function renderVideoList(videos) {
            const selector = document.getElementById('videoSelector');

            if (videos.length === 0) {
                selector.innerHTML = '<p style="color:#999;">暂无可用视频文件</p>';
                selector.classList.remove('loading');
                return;
            }

            selector.innerHTML = '';
            selector.classList.remove('loading');

            videos.forEach((video, index) => {
                const item = document.createElement('div');
                item.className = 'video-item';
                item.onclick = () => toggleVideo(index);

                const sizeInMB = (video.size / 1024 / 1024).toFixed(2);
                const date = new Date(video.modified * 1000).toLocaleString('zh-CN');

                item.innerHTML = `
                    <input type="checkbox" id="video-${index}" ${selectedVideos.includes(video.path) ? 'checked' : ''}>
                    <div class="video-info">
                        <div class="video-name">${video.name}</div>
                        <div class="video-meta">项目: ${video.project} | 大小: ${sizeInMB}MB | 修改时间: ${date}</div>
                    </div>
                `;

                if (selectedVideos.includes(video.path)) {
                    item.classList.add('selected');
                }

                selector.appendChild(item);
            });

            updateSelectedCount();
        }

        // 切换视频选择
        function toggleVideo(index) {
            const video = allVideos[index];
            const videoIndex = selectedVideos.indexOf(video.path);

            if (videoIndex > -1) {
                selectedVideos.splice(videoIndex, 1);
            } else {
                selectedVideos.push(video.path);
            }

            renderVideoList(allVideos);
        }

        // 更新选择计数
        function updateSelectedCount() {
            const countElement = document.getElementById('selectedCount');
            const countNumber = document.getElementById('countNumber');

            if (selectedVideos.length > 0) {
                countElement.style.display = 'inline-block';
                countNumber.textContent = selectedVideos.length;
            } else {
                countElement.style.display = 'none';
            }

            document.getElementById('videoFilesInput').value = selectedVideos.join(',');
        }

        // 加载示例文案
        function loadExample() {
            document.querySelector('[name="transcript"]').value =
                "你有没有发现，越是没本事的人，越喜欢充大头。\\n" +
                "真正有实力的人，往往都很低调。\\n" +
                "他们不需要通过炫耀来证明自己，因为实力会说话。\\n" +
                "记住，真正的强者，从不需要证明。";
        }

        // 提交表单
        document.getElementById('jianyingForm').addEventListener('submit', async (e) => {
            e.preventDefault();

            const btn = document.getElementById('submitBtn');
            const result = document.getElementById('result');

            if (selectedVideos.length === 0) {
                result.className = 'result error';
                result.innerHTML = '<h3>❌ 请选择至少一个视频文件</h3>';
                result.style.display = 'block';
                return;
            }

            btn.disabled = true;
            btn.textContent = '⏳ 生成中，请稍候...';
            result.style.display = 'none';

            const formData = new FormData(e.target);
            const params = new URLSearchParams();

            for (const [key, value] of formData.entries()) {
                if (e.target.elements[key] && e.target.elements[key].type === 'checkbox') {
                    params.append(key, e.target.elements[key].checked);
                } else {
                    params.append(key, value);
                }
            }

            try {
                const response = await fetch('/api/jianying/create', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: params.toString()
                });

                const data = await response.json();

                if (data.success) {
                    result.className = 'result success';
                    result.innerHTML = `
                        <h3>✅ ${data.message}</h3>
                        <p><strong>📁 导入包路径:</strong> ${data.output_path}</p>
                        <p><strong>🎞️ 视频文件:</strong> ${data.final_video}</p>
                        <p><strong>💬 字幕文件:</strong> ${data.subtitles || '未生成'}</p>
                        <p><strong>⏱️ 总时长:</strong> ${data.total_duration.toFixed(1)}秒</p>
                        <p><strong>🎥 片段数:</strong> ${data.segments_count}个</p>
                        <p style="margin-top: 20px; padding-top: 20px; border-top: 2px solid #c3e6cb;">
                            <strong>📝 下一步操作:</strong><br>
                            1. 打开剪映专业版<br>
                            2. 点击「开始创作」并导入 final.mp4<br>
                            3. 导入 subtitles.srt，或使用剪映自动识别字幕<br>
                            4. 在剪映中继续精修、配音和导出
                        </p>
                    `;
                } else {
                    result.className = 'result error';
                    result.innerHTML = `<h3>❌ 生成失败</h3><p>${data.error}</p>`;
                }

                result.style.display = 'block';
                result.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

            } catch (error) {
                result.className = 'result error';
                result.innerHTML = `<h3>❌ 请求失败</h3><p>${error.message}</p>`;
                result.style.display = 'block';
            } finally {
                btn.disabled = false;
                btn.textContent = '🎬 生成剪映导入包';
            }
        });

        // 页面加载时加载视频列表
        window.addEventListener('load', loadVideos);
    </script>
</body>
</html>"""


def main():
    """启动 Web 服务器"""
    host = '127.0.0.1'
    port = 7862

    server = ThreadingHTTPServer((host, port), JianyingWebHandler)

    print("=" * 60)
    print("🚀 剪映导入包 Web 服务器已启动（支持视频多选）")
    print("=" * 60)
    print(f"📝 访问地址: http://{host}:{port}")
    print(f"⚙️  服务器端口: {port}")
    print(f"🔧 按 Ctrl+C 停止服务器")
    print("=" * 60)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n⏹️  服务器已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
