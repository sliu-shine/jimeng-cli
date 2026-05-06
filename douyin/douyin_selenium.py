#!/usr/bin/env python3
"""
抖音视频自动化下载脚本
配合 Tampermonkey 脚本使用
"""

import os
import json
import random
import re
import shutil
import subprocess
import time
import requests
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from typing import Callable, Optional, Dict, List


class DouyinSeleniumDownloader:
    MEDIA_SUFFIXES = {".mp4", ".m4a", ".mp3", ".aac", ".wav"}
    VIDEO_DELAY_RANGE = (3.0, 8.0)
    ACCOUNT_DELAY_RANGE = (30.0, 90.0)
    PAGE_LOAD_DELAY_RANGE = (4.0, 7.0)
    SCROLL_DELAY_RANGE = (2.0, 5.0)
    SHORT_DELAY_RANGE = (1.5, 3.5)
    RETRY_DELAY_RANGE = (2.5, 5.0)
    MAX_CONSECUTIVE_DOWNLOAD_FAILURES = 3
    MIN_VALID_VIDEO_BYTES = 1024

    def __init__(self, output_dir="douyin_videos", organize_by_tag=False,
                 progress_callback: Optional[Callable] = None,
                 log_callback: Optional[Callable] = None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.organize_by_tag = organize_by_tag
        self.driver = None
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.is_stopped = False  # 停止标志
        self.existing_video_index = self._build_existing_video_index()

    def _log(self, message: str, level: str = "info"):
        """统一的日志输出"""
        print(message)
        if self.log_callback:
            self.log_callback(level, message)

    def _update_progress(self, account_index: int, status: str, progress: int = 0, **kwargs):
        """更新进度"""
        if self.progress_callback:
            self.progress_callback(account_index, status, progress, **kwargs)

    def _random_sleep(self, min_seconds: float, max_seconds: float, reason: str = ""):
        """随机等待，降低固定节奏带来的异常行为特征。"""
        delay = random.uniform(min_seconds, max_seconds)
        if reason:
            self._log(f"⏳ {reason}，等待 {delay:.1f}s")
        time.sleep(delay)

    def _build_existing_video_index(self) -> Dict[str, Path]:
        """扫描已下载视频，建立 video_id -> mp4 路径索引"""
        index: Dict[str, Path] = {}

        for meta_file in self.output_dir.rglob("*.json"):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue

            video_id = (
                metadata.get("video_id")
                or metadata.get("videoId")
                or metadata.get("aweme_id")
            )
            if not video_id:
                continue

            for suffix in self.MEDIA_SUFFIXES:
                media_file = meta_file.with_suffix(suffix)
                if media_file.exists():
                    index[str(video_id)] = media_file
                    break

        for media_file in self.output_dir.rglob("*"):
            if not media_file.is_file() or media_file.suffix.lower() not in self.MEDIA_SUFFIXES:
                continue
            for video_id in self._extract_video_ids_from_filename(media_file.stem):
                index.setdefault(video_id, media_file)

        return index

    def _extract_video_ids_from_filename(self, filename: str) -> List[str]:
        """从文件名中提取抖音长数字 videoId"""
        return re.findall(r"(?<!\d)(\d{10,})(?!\d)", filename)

    def find_existing_video(self, video_id: str) -> Optional[Path]:
        """按 video_id 查找已下载的视频文件"""
        video_id = str(video_id)

        existing = self.existing_video_index.get(video_id)
        if existing and existing.exists():
            return existing

        for video_file in self.output_dir.rglob(f"*{video_id}*.mp4"):
            self.existing_video_index[video_id] = video_file
            return video_file

        return None

    def _extract_tags_from_text(self, text: str) -> List[str]:
        """只从当前视频文案中的 #话题 提取标签。"""
        if not text:
            return []
        tags = []
        for tag in re.findall(r"#([^#\s，,。！!？?、]+)", text):
            tag = tag.strip()
            if 0 < len(tag) < 30 and tag not in tags:
                tags.append(tag)
        return tags

    def _normalize_video_tags(self, *tag_sources) -> List[str]:
        """合并标签并保持顺序，避免页面推荐/商品标签混入。"""
        tags = []
        for source in tag_sources:
            if not source:
                continue
            if isinstance(source, str):
                candidates = self._extract_tags_from_text(source)
                if not candidates and not source.startswith("#"):
                    candidates = [source]
            else:
                candidates = list(source)

            for tag in candidates:
                clean_tag = str(tag).strip().lstrip("#").strip()
                if 0 < len(clean_tag) < 30 and clean_tag not in tags:
                    tags.append(clean_tag)

        return tags[:10]

    def _probe_video_file(self, filepath: Path) -> tuple[bool, str]:
        """校验下载结果是否是可用于转录的视频文件。"""
        if not filepath.exists():
            return False, "文件不存在"

        size = filepath.stat().st_size
        if size < self.MIN_VALID_VIDEO_BYTES:
            return False, f"文件过小（{size} 字节）"

        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "stream=codec_type:format=duration",
            "-of", "json",
            str(filepath),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return False, "未找到 ffprobe，无法校验视频"

        if result.returncode != 0:
            reason = (result.stderr or "").strip().splitlines()
            return False, reason[0] if reason else f"ffprobe 退出码 {result.returncode}"

        try:
            probe = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            return False, f"ffprobe 输出无法解析: {exc}"

        streams = probe.get("streams") or []
        stream_types = [stream.get("codec_type") for stream in streams]
        if "video" not in stream_types:
            return False, "没有视频流"
        if "audio" not in stream_types:
            return False, "没有音频流，无法转录"

        duration_raw = (probe.get("format") or {}).get("duration")
        try:
            duration = float(duration_raw) if duration_raw is not None else None
        except (TypeError, ValueError):
            duration = None
        if duration is not None and duration <= 0:
            return False, f"时长异常: {duration}"

        return True, f"校验通过，大小 {size} 字节，时长 {duration or '未知'} 秒"

    def _probe_audio_file(self, filepath: Path) -> tuple[bool, str]:
        """校验下载结果是否是可用于转录的音频文件。"""
        if not filepath.exists():
            return False, "文件不存在"

        size = filepath.stat().st_size
        if size < self.MIN_VALID_VIDEO_BYTES:
            return False, f"文件过小（{size} 字节）"

        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "stream=codec_type:format=duration",
            "-of", "json",
            str(filepath),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return False, "未找到 ffprobe，无法校验音频"

        if result.returncode != 0:
            reason = (result.stderr or "").strip().splitlines()
            return False, reason[0] if reason else f"ffprobe 退出码 {result.returncode}"

        try:
            probe = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            return False, f"ffprobe 输出无法解析: {exc}"

        streams = probe.get("streams") or []
        stream_types = [stream.get("codec_type") for stream in streams]
        if "audio" not in stream_types:
            return False, "没有音频流，无法转录"

        duration_raw = (probe.get("format") or {}).get("duration")
        try:
            duration = float(duration_raw) if duration_raw is not None else None
        except (TypeError, ValueError):
            duration = None
        if duration is not None and duration <= 0:
            return False, f"时长异常: {duration}"

        return True, f"音频校验通过，大小 {size} 字节，时长 {duration or '未知'} 秒"

    def _is_likely_video_media_url(self, url: str, mime_type: str = "") -> bool:
        """判断网络请求是否是真正的视频媒体地址。"""
        if not url or not url.startswith("http"):
            return False

        lower_url = url.lower()
        lower_mime = (mime_type or "").lower()

        reject_markers = [
            "/aweme/v1/",
            "/web/api/",
            "/api/",
            "media-audio",
            "/audio/",
            "mime_type=audio",
            ".m4a",
            ".mp3",
        ]
        if any(marker in lower_url for marker in reject_markers):
            return False

        if lower_mime and not lower_mime.startswith("video/"):
            return False

        accept_markers = [
            "media-video",
            "mime_type=video",
            ".mp4",
            ".m4s",
        ]
        return lower_mime.startswith("video/") or any(marker in lower_url for marker in accept_markers)

    def _is_likely_audio_media_url(self, url: str, mime_type: str = "") -> bool:
        """判断网络请求是否是真正的音频媒体地址。"""
        if not url or not url.startswith("http"):
            return False

        lower_url = url.lower()
        lower_mime = (mime_type or "").lower()

        reject_markers = [
            "/aweme/v1/",
            "/web/api/",
            "/api/",
        ]
        if any(marker in lower_url for marker in reject_markers):
            return False

        accept_markers = [
            "media-audio",
            "mime_type=audio",
            ".m4a",
            ".mp3",
            ".aac",
        ]
        return lower_mime.startswith("audio/") or any(marker in lower_url for marker in accept_markers)

    def _video_media_url_score(self, url: str, mime_type: str = "") -> int:
        """视频候选地址打分，优先选完整视频分片。"""
        lower_url = url.lower()
        lower_mime = (mime_type or "").lower()
        score = 0
        if lower_mime.startswith("video/"):
            score += 20
        if "media-video" in lower_url:
            score += 30
        if "mime_type=video_mp4" in lower_url:
            score += 20
        elif "mime_type=video" in lower_url:
            score += 10
        if ".mp4" in lower_url:
            score += 10
        if "dash" in lower_url:
            score += 3
        return score

    def _audio_media_url_score(self, url: str, mime_type: str = "") -> int:
        """音频候选地址打分。"""
        lower_url = url.lower()
        lower_mime = (mime_type or "").lower()
        score = 0
        if lower_mime.startswith("audio/"):
            score += 20
        if "media-audio" in lower_url:
            score += 30
        if "mime_type=audio" in lower_url:
            score += 15
        if ".m4a" in lower_url or ".mp3" in lower_url:
            score += 10
        return score

    def stop(self):
        """停止下载任务"""
        self.is_stopped = True
        self._log("⚠️ 收到停止信号", "warning")

    def init_driver(self):
        """初始化 Chrome 浏览器"""
        chrome_options = Options()
        # chrome_options.add_argument('--headless')  # 无头模式（可选）
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        # 启用性能日志以捕获网络请求
        chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

        # 设置用户代理
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

        # 使用持久化的用户数据目录，保持登录状态和插件
        user_data_dir = Path.home() / '.douyin_selenium_profile'
        user_data_dir.mkdir(exist_ok=True)
        chrome_options.add_argument(f'--user-data-dir={user_data_dir}')

        # 使用独立的 profile，避免与正常浏览器冲突
        chrome_options.add_argument('--profile-directory=DouyinDownloader')

        # 使用 webdriver-manager 自动管理 ChromeDriver
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)

        # 隐藏 webdriver 特征
        self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            '''
        })

        self._log("✅ 浏览器初始化完成")

    def open_user_page(self, user_url):
        """打开用户主页"""
        self._log(f"📱 正在打开: {user_url}")
        self.driver.get(user_url)
        self._random_sleep(*self.SHORT_DELAY_RANGE, reason="等待用户主页加载")

    def dismiss_alert_if_present(self):
        """如果存在 alert 对话框，自动关闭它"""
        try:
            alert = self.driver.switch_to.alert
            alert_text = alert.text
            self._log(f"  ℹ️  检测到弹窗: {alert_text}")
            alert.accept()  # 点击确定
            self._log(f"  ✅ 已关闭弹窗")
            time.sleep(1)
        except:
            pass  # 没有 alert，忽略

    def scroll_to_load_videos(self, scroll_times=10):
        """滚动页面加载更多视频"""
        self._log(f"📜 开始滚动加载视频（{scroll_times}次）...")

        for i in range(scroll_times):
            # 先检查并关闭可能的 alert
            self.dismiss_alert_if_present()

            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            self._random_sleep(*self.SCROLL_DELAY_RANGE)
            self._log(f"  [{i+1}/{scroll_times}] 已滚动")

        # 滚动完成后再检查一次
        self.dismiss_alert_if_present()
        self._log("✅ 视频加载完成")

    def get_video_list_from_storage(self):
        """从 localStorage 读取 Tampermonkey 准备的视频列表"""
        # 先关闭可能的 alert
        self.dismiss_alert_if_present()

        video_list_json = self.driver.execute_script(
            "return localStorage.getItem('douyin_download_list');"
        )

        if not video_list_json:
            self._log("❌ 未找到视频列表，请先在页面上点击「扫描爆款视频」")
            return []

        video_list = json.loads(video_list_json)
        self._log(f"✅ 读取到 {len(video_list)} 个视频")
        return video_list

    def extract_video_metadata(self):
        """从页面提取视频元数据（标题、标签等）"""
        metadata = {
            'title': '',
            'tags': [],
            'author': '',
            'description': ''
        }

        try:
            # 等待页面内容加载
            self._random_sleep(*self.SHORT_DELAY_RANGE)

            # 方法1: 使用 JavaScript 从页面数据中提取
            try:
                js_data = self.driver.execute_script("""
                    // 尝试从页面的 __RENDER_DATA__ 或其他数据源提取
                    const renderData = window.__RENDER_DATA__ || window.__INITIAL_STATE__;
                    if (renderData) {
                        try {
                            const dataStr = JSON.stringify(renderData);
                            const data = JSON.parse(dataStr);
                            return data;
                        } catch(e) {
                            return null;
                        }
                    }
                    return null;
                """)

                if js_data:
                    self._log(f"  ✓ 从页面数据中提取到信息")
            except:
                pass

            # 方法2: 提取标题 - 尝试多个选择器
            title_selectors = [
                'h1[data-e2e="video-title"]',
                'h1.video-title',
                '[class*="title"]',
                'h1',
                'title'
            ]

            for selector in title_selectors:
                try:
                    if selector == 'title':
                        # 从页面 title 标签提取
                        page_title = self.driver.title
                        # 抖音的 title 格式通常是 "标题 - 作者的作品 - 抖音"
                        if ' - ' in page_title:
                            metadata['title'] = page_title.split(' - ')[0].strip()
                            break
                    else:
                        title_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                        title_text = title_element.text.strip()
                        if title_text and len(title_text) > 3:  # 确保不是空标题
                            metadata['title'] = title_text
                            break
                except:
                    continue

            # 方法3: 提取描述
            desc_selectors = [
                '[data-e2e="video-desc"]',
                '.video-desc',
                '[class*="desc"]',
                'p[class*="desc"]'
            ]

            for selector in desc_selectors:
                try:
                    desc_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    desc_text = desc_element.text.strip()
                    if desc_text:
                        metadata['description'] = desc_text
                        break
                except:
                    continue

            # 方法4: 只从当前视频标题/描述提取 #标签，避免把推荐/商品标签混进来
            metadata['tags'] = self._normalize_video_tags(
                metadata['title'],
                metadata['description']
            )

            # 方法5: 提取作者
            author_selectors = [
                '[data-e2e="video-author-name"]',
                '.author-name',
                '[class*="author"]'
            ]

            for selector in author_selectors:
                try:
                    author_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    author_text = author_element.text.strip()
                    if author_text:
                        metadata['author'] = author_text
                        break
                except:
                    continue

            # 日志输出提取结果
            if metadata['title']:
                self._log(f"  ✓ 标题: {metadata['title'][:50]}")
            if metadata['tags']:
                self._log(f"  ✓ 标签: {', '.join(metadata['tags'][:5])}")
            if metadata['author']:
                self._log(f"  ✓ 作者: {metadata['author']}")

        except Exception as e:
            self._log(f"  ⚠️  提取元数据失败: {e}")

        return metadata

    def sanitize_filename(self, text, max_length=50):
        """清理文件名，移除非法字符"""
        # 移除非法字符
        illegal_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|', '\n', '\r']
        for char in illegal_chars:
            text = text.replace(char, '')

        # 限制长度
        if len(text) > max_length:
            text = text[:max_length]

        return text.strip()

    def download_video(self, video_info):
        """下载单个视频"""
        video_id = video_info['videoId']
        video_url = video_info['videoUrl']
        likes = video_info['likes']

        existing_video = self.find_existing_video(video_id)
        if existing_video:
            self._log(f"\n⏭️  视频已采集，跳过: {video_id}")
            self._log(f"  📁 已有文件: {existing_video}")
            return True

        self._log(f"\n⬇️  下载视频: {video_id} ({int(likes)}赞)")

        try:
            # 先关闭可能的 alert
            self.dismiss_alert_if_present()

            # 打开视频页面
            self.driver.get(video_url)

            # 等待页面加载完成
            self._random_sleep(*self.PAGE_LOAD_DELAY_RANGE, reason="等待视频页加载")

            # 再次检查 alert
            self.dismiss_alert_if_present()

            # 等待视频元素出现
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, 'video'))
                )
            except:
                self._log(f"  ⚠️  视频元素未加载")

            # 提取视频元数据
            metadata = self.extract_video_metadata()
            title = (
                metadata.get('title')
                or video_info.get('title')
                or video_info.get('desc')
                or ''
            )
            description = metadata.get('description') or video_info.get('desc') or ''
            tags = self._normalize_video_tags(title, description)
            if not tags:
                tags = self._normalize_video_tags(video_info.get('tags', []))

            # 转录优先：优先抓取音频媒体；没有音频时才退回单文件视频
            media_urls = self.extract_media_urls()
            audio_src = media_urls.get("audio")
            video_src = media_urls.get("video")

            if audio_src or video_src:
                # 构建文件名：[点赞数]_[标题]_[视频ID].m4a/mp4
                title_part = self.sanitize_filename(title) if title else ''
                likes_str = f"{int(likes/10000)}w" if likes >= 10000 else str(int(likes))
                suffix = ".m4a" if audio_src else ".mp4"

                if title_part:
                    filename = f"[{likes_str}赞]_{title_part}_{video_id}{suffix}"
                else:
                    filename = f"[{likes_str}赞]_{video_id}{suffix}"

                # 根据标签分类保存
                if self.organize_by_tag and tags:
                    # 使用第一个标签作为分类目录
                    tag_dir = self.output_dir / self.sanitize_filename(tags[0], max_length=20)
                    tag_dir.mkdir(exist_ok=True)
                    filepath = tag_dir / filename
                else:
                    filepath = self.output_dir / filename

                if filepath.exists():
                    self.existing_video_index[str(video_id)] = filepath
                    self._log(f"  ⏭️  文件已存在，跳过: {filename}")
                    return True

                source_url = audio_src or video_src
                temp_filepath = filepath.with_name(filepath.name + ".part")
                if audio_src:
                    self._log("  ✓ 捕获到音频媒体地址，按转录优先保存音频")
                download_info = self.download_file(source_url, temp_filepath)
                if download_info.get("error"):
                    temp_filepath.unlink(missing_ok=True)
                    self._log(
                        "  ❌ 媒体下载请求失败，已放弃: "
                        f"{download_info.get('error')} | "
                        f"Content-Type: {download_info.get('content_type') or '未知'} | "
                        f"字节数: {download_info.get('bytes', 0)} | "
                        f"使用浏览器 Cookie: {download_info.get('used_browser_cookies')} | "
                        f"URL: {download_info.get('url')}",
                        "error"
                    )
                    try:
                        filepath.parent.rmdir()
                    except OSError:
                        pass
                    return False

                if audio_src:
                    is_valid, validation_reason = self._probe_audio_file(temp_filepath)
                else:
                    is_valid, validation_reason = self._probe_video_file(temp_filepath)
                if not is_valid:
                    temp_filepath.unlink(missing_ok=True)
                    self._log(
                        "  ❌ 下载结果无效，已删除临时文件: "
                        f"{validation_reason} | HTTP {download_info.get('status_code')} | "
                        f"Content-Type: {download_info.get('content_type') or '未知'} | "
                        f"字节数: {download_info.get('bytes', 0)} | URL: {download_info.get('url')}",
                        "error"
                    )
                    try:
                        filepath.parent.rmdir()
                    except OSError:
                        pass
                    return False

                shutil.move(str(temp_filepath), str(filepath))
                self.existing_video_index[str(video_id)] = filepath

                # 校验通过后再保存元数据，避免损坏视频留下 json
                metadata_file = filepath.with_suffix('.json')
                metadata_data = {
                    'video_id': video_id,
                    'video_url': video_url,
                    'likes': int(likes),
                    'title': title,
                    'description': description,
                    'tags': tags,
                    'author': metadata['author'],
                    'media_type': 'audio' if audio_src else 'video',
                    'download_time': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'download': download_info,
                    'validation': validation_reason
                }

                with open(metadata_file, 'w', encoding='utf-8') as f:
                    json.dump(metadata_data, f, ensure_ascii=False, indent=2)

                self._log(f"  ✅ 已保存: {filename}")
                if audio_src:
                    self._log("  🎧 已保存音频用于转录，不保存分离流视频")
                if title:
                    self._log(f"  📝 标题: {title}")
                if tags:
                    self._log(f"  🏷️  标签: {', '.join(tags[:5])}")
                return True
            else:
                self._log(f"  ❌ 无法提取视频地址")
                return False

        except Exception as e:
            self._log(f"  ❌ 下载失败: {e}")
            import traceback
            self._log(f"  详细错误: {traceback.format_exc()}", "error")
            return False

    def extract_media_urls(self):
        """从页面提取媒体地址，优先返回音频地址用于转录。"""
        max_retries = 3

        for attempt in range(max_retries):
            try:
                # 等待视频元素加载并可交互
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.TAG_NAME, 'video'))
                )

                # 方法1: 使用 CDP 监听网络请求（最可靠）
                try:
                    # 启用网络监听
                    self.driver.execute_cdp_cmd('Network.enable', {})

                    # 触发视频播放
                    self.driver.execute_script("""
                        const video = document.querySelector('video');
                        if (video) {
                            video.play();
                        }
                    """)

                    # 等待视频开始加载
                    self._random_sleep(*self.SHORT_DELAY_RANGE)

                    # 获取所有网络请求
                    logs = self.driver.get_log('performance')

                    # 查找媒体请求，区分音频和视频
                    video_candidates = []
                    audio_candidates = []
                    for log in logs:
                        try:
                            message = json.loads(log['message'])
                            method = message.get('message', {}).get('method', '')

                            if method == 'Network.responseReceived':
                                response = message.get('message', {}).get('params', {}).get('response', {})
                                url = response.get('url', '')
                                mime_type = response.get('mimeType', '')

                                if self._is_likely_audio_media_url(url, mime_type):
                                    audio_candidates.append((url, mime_type))
                                elif self._is_likely_video_media_url(url, mime_type):
                                    video_candidates.append((url, mime_type))
                        except:
                            continue

                    media_urls = {}
                    if audio_candidates:
                        audio_candidates.sort(
                            key=lambda item: self._audio_media_url_score(item[0], item[1]),
                            reverse=True
                        )
                        url, mime_type = audio_candidates[0]
                        self._log(f"  ✓ 从网络请求捕获到音频媒体地址 ({mime_type or 'unknown'})")
                        media_urls["audio"] = url

                    if video_candidates:
                        video_candidates.sort(
                            key=lambda item: self._video_media_url_score(item[0], item[1]),
                            reverse=True
                        )
                        url, mime_type = video_candidates[0]
                        self._log(f"  ✓ 从网络请求捕获到视频媒体地址 ({mime_type or 'unknown'})")
                        media_urls["video"] = url

                    if media_urls:
                        return media_urls

                except Exception as cdp_error:
                    self._log(f"  ⚠️  CDP 监听失败: {cdp_error}")

                # 方法2: 从 JavaScript 获取
                try:
                    # 确保视频正在播放
                    self.driver.execute_script("""
                        const video = document.querySelector('video');
                        if (video) {
                            video.play();
                        }
                    """)
                    self._random_sleep(*self.SHORT_DELAY_RANGE)

                    video_src = self.driver.execute_script("""
                        const video = document.querySelector('video');
                        if (!video) return null;

                        // 尝试多个属性
                        let src = video.currentSrc || video.src;

                        // 如果还是没有，尝试从 source 标签获取
                        if (!src) {
                            const sources = video.querySelectorAll('source');
                            for (let source of sources) {
                                if (source.src) {
                                    src = source.src;
                                    break;
                                }
                            }
                        }

                        return src || null;
                    """)

                    if self._is_likely_video_media_url(video_src):
                        self._log(f"  ✓ 从 JavaScript 提取到地址")
                        return {"video": video_src}
                except Exception as js_error:
                    self._log(f"  ⚠️  JavaScript 提取失败: {js_error}")

                # 方法2: 从 video 标签获取
                try:
                    video_element = self.driver.find_element(By.TAG_NAME, 'video')
                    video_src = video_element.get_attribute('src')

                    if self._is_likely_video_media_url(video_src):
                        self._log(f"  ✓ 从 video.src 提取到地址")
                        return {"video": video_src}

                    # 尝试 currentSrc 属性
                    video_src = video_element.get_attribute('currentSrc')
                    if self._is_likely_video_media_url(video_src):
                        self._log(f"  ✓ 从 video.currentSrc 提取到地址")
                        return {"video": video_src}
                except Exception as elem_error:
                    self._log(f"  ⚠️  元素提取失败: {elem_error}")

                # 方法3: 从 source 标签获取
                try:
                    source_elements = self.driver.find_elements(By.TAG_NAME, 'source')
                    for source in source_elements:
                        video_src = source.get_attribute('src')
                        if self._is_likely_video_media_url(video_src):
                            self._log(f"  ✓ 从 source.src 提取到地址")
                            return {"video": video_src}
                except Exception as source_error:
                    self._log(f"  ⚠️  source 提取失败: {source_error}")

                # 如果所有方法都失败，尝试刷新页面重试
                if attempt < max_retries - 1:
                    self._log(f"  ⚠️  第 {attempt + 1} 次尝试失败，刷新页面后重试...")
                    self.driver.refresh()
                    self._random_sleep(*self.RETRY_DELAY_RANGE)
                else:
                    self._log(f"  ⚠️  未找到有效的视频地址")
                    return {}

            except Exception as e:
                if attempt < max_retries - 1:
                    self._log(f"  ⚠️  提取失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                    self._random_sleep(*self.RETRY_DELAY_RANGE)
                else:
                    self._log(f"  ❌ 提取视频地址失败: {e}")
                    return {}

        return {}

    def extract_video_url(self):
        """兼容旧调用：从页面提取视频地址。"""
        return self.extract_media_urls().get("video")

    def _browser_cookie_header(self) -> str:
        """把当前 Selenium 浏览器 cookie 转成 requests 可用的 Cookie header。"""
        if not self.driver:
            return ""
        try:
            cookies = self.driver.get_cookies()
        except Exception:
            return ""
        return "; ".join(
            f"{cookie.get('name')}={cookie.get('value')}"
            for cookie in cookies
            if cookie.get("name") and cookie.get("value") is not None
        )

    def download_file(self, url, filepath):
        """下载文件"""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "Origin": "https://www.douyin.com",
            "Referer": "https://www.douyin.com/",
            "Range": "bytes=0-",
            "Sec-Fetch-Dest": "video",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
        }
        cookie_header = self._browser_cookie_header()
        if cookie_header:
            headers["Cookie"] = cookie_header

        filepath = Path(filepath)
        filepath.unlink(missing_ok=True)

        response = requests.get(url, headers=headers, stream=True, timeout=60)
        download_info = {
            "url": response.url,
            "status_code": response.status_code,
            "content_type": response.headers.get("Content-Type", ""),
            "content_length": response.headers.get("Content-Length", ""),
            "bytes": 0,
            "used_browser_cookies": bool(cookie_header),
        }
        if response.status_code not in {200, 206}:
            download_info["error"] = f"HTTP {response.status_code}"
            return download_info

        bytes_written = 0
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                f.write(chunk)
                bytes_written += len(chunk)

        download_info["bytes"] = bytes_written
        return download_info

    def run_batch(self, user_urls, scroll_times=10, min_likes=1000, auto_mode=False):
        """批量运行多个账号的下载流程

        Args:
            user_urls: 账号链接列表
            scroll_times: 滚动次数
            min_likes: 最低点赞数
            auto_mode: 自动模式（配合 Tampermonkey 脚本自动扫描）
        """
        try:
            self.init_driver()

            # 将账号队列写入 localStorage，供 Tampermonkey 脚本读取
            if auto_mode:
                account_queue = [
                    {
                        "url": url,
                        "status": "pending",
                        "progress": 0,
                        "min_likes": min_likes
                    }
                    for url in user_urls
                ]

                # 先打开第一个账号，然后注入队列数据
                self._log(f"📋 准备处理 {len(user_urls)} 个账号")
                self.driver.get(user_urls[0])
                self._random_sleep(2.0, 4.0, reason="等待账号主页初始化")

                # 关闭可能的 alert
                self.dismiss_alert_if_present()

                # 注入账号队列到 localStorage
                self.driver.execute_script(
                    f"localStorage.setItem('douyin_account_queue', '{json.dumps(account_queue)}');"
                )
                self._log("✅ 账号队列已注入到浏览器")

            for idx, user_url in enumerate(user_urls, 1):
                if self.is_stopped:
                    self._log("⚠️ 任务已停止", "warning")
                    break

                self._log("\n" + "="*60)
                self._log(f"📱 账号 [{idx}/{len(user_urls)}]: {user_url}")
                self._log("="*60)

                self._update_progress(idx - 1, "processing", 10)

                # 打开用户主页
                self.open_user_page(user_url)
                self._update_progress(idx - 1, "processing", 20)

                # 滚动加载视频
                self.scroll_to_load_videos(scroll_times)
                self._update_progress(idx - 1, "processing", 40)

                if auto_mode:
                    # 自动模式：等待 Tampermonkey 脚本完成扫描
                    self._log("\n⏳ 等待 Tampermonkey 脚本扫描视频...")
                    self._log("   （脚本会自动扫描并保存视频列表）")

                    # 轮询检查扫描状态
                    max_wait = 60  # 最多等待60秒
                    for i in range(max_wait):
                        if self.is_stopped:
                            break

                        # 关闭可能的 alert
                        self.dismiss_alert_if_present()

                        # 检查当前账号是否已完成
                        queue_json = self.driver.execute_script(
                            "return localStorage.getItem('douyin_account_queue');"
                        )
                        if queue_json:
                            queue = json.loads(queue_json)
                            current_account = next((acc for acc in queue if acc['url'] == user_url), None)
                            if current_account and current_account.get('status') == 'completed':
                                self._log("✅ Tampermonkey 脚本扫描完成")
                                break

                        time.sleep(1)
                        if i % 10 == 0 and i > 0:
                            self._log(f"   等待中... ({i}s)")

                    self._update_progress(idx - 1, "processing", 60)
                else:
                    # 手动模式：等待用户操作
                    self._log("\n" + "="*60)
                    self._log("📌 请在浏览器中：")
                    self._log("   1. 点击右侧的「🔍 扫描爆款视频」按钮")
                    self._log("   2. 确认视频列表")
                    self._log("   3. 点击「⬇️ 下载选中视频」按钮")
                    self._log("   4. 然后回到终端按 Enter 继续")
                    self._log("="*60)
                    input("\n按 Enter 继续...")

                # 读取视频列表
                self.dismiss_alert_if_present()  # 关闭可能的弹窗
                storage_key = f"douyin_videos_{user_url}" if auto_mode else "douyin_download_list"
                video_list_json = self.driver.execute_script(
                    f"return localStorage.getItem('{storage_key}');"
                )

                if not video_list_json:
                    self._log("❌ 没有读取到视频列表，停止后续账号以避免连续异常", "error")
                    self._update_progress(idx - 1, "completed", 100, video_count=0)
                    self.is_stopped = True
                    break

                video_list = json.loads(video_list_json)
                if not video_list:
                    self._log("❌ 视频列表为空，停止后续账号以避免连续异常", "error")
                    self._update_progress(idx - 1, "completed", 100, video_count=0)
                    self.is_stopped = True
                    break

                self._log(f"✅ 读取到 {len(video_list)} 个视频")
                self._update_progress(idx - 1, "processing", 70, video_count=len(video_list))

                # 下载视频
                success_count = 0
                failure_count = 0
                consecutive_failure_count = 0
                for i, video_info in enumerate(video_list, 1):
                    if self.is_stopped:
                        break

                    self._log(f"\n[{i}/{len(video_list)}]")
                    if self.download_video(video_info):
                        success_count += 1
                        consecutive_failure_count = 0
                    else:
                        failure_count += 1
                        consecutive_failure_count += 1

                    if consecutive_failure_count >= self.MAX_CONSECUTIVE_DOWNLOAD_FAILURES:
                        self._log(
                            f"❌ 连续 {consecutive_failure_count} 个视频下载失败，停止后续任务",
                            "error"
                        )
                        self.is_stopped = True
                        break

                    # 更新进度
                    progress = 70 + int((i / len(video_list)) * 25)
                    self._update_progress(idx - 1, "processing", progress,
                                        downloaded=success_count, total=len(video_list))

                    if i < len(video_list) and not self.is_stopped:
                        self._random_sleep(*self.VIDEO_DELAY_RANGE, reason="视频间隔")

                self._log("\n" + "="*60)
                self._log(
                    f"✅ 账号 [{idx}] 下载完成: 成功 {success_count} / 失败 {failure_count} / 总数 {len(video_list)}",
                    "success"
                )
                self._log(f"📁 保存位置: {self.output_dir.absolute()}")
                self._log("="*60)

                self._update_progress(idx - 1, "completed", 100,
                                    video_count=len(video_list), success_count=success_count,
                                    failure_count=failure_count)

                if success_count == 0 and failure_count > 0:
                    self._log("❌ 当前账号没有任何视频下载成功，停止后续账号", "error")
                    self.is_stopped = True

                # 清空 localStorage，准备下一个账号
                self.driver.execute_script(f"localStorage.removeItem('{storage_key}');")

                # 如果不是最后一个账号
                if idx < len(user_urls) and not self.is_stopped:
                    if not auto_mode:
                        continue_next = input("\n继续下载下一个账号? (y/n, 默认y): ").strip().lower()
                        if continue_next == 'n':
                            self._log("⚠️  用户选择停止", "warning")
                            break
                    else:
                        self._log(f"\n⏭️  准备处理下一个账号...")
                        self._random_sleep(*self.ACCOUNT_DELAY_RANGE, reason="账号切换冷却")

        except KeyboardInterrupt:
            self._log("\n\n⚠️  用户中断", "warning")
        except Exception as e:
            self._log(f"\n❌ 发生错误: {e}", "error")
            import traceback
            self._log(traceback.format_exc(), "error")
        finally:
            if self.driver:
                self._log("\n🔒 关闭浏览器...")
                self.driver.quit()

    def run(self, user_url, scroll_times=10):
        """运行单个账号的下载流程"""
        self.run_batch([user_url], scroll_times)


def main():
    self._log("="*60)
    self._log("🎬 抖音视频自动化下载工具")
    self._log("="*60)

    # 用户输入
    self._log("\n请输入抖音用户主页链接（多个链接用逗号或换行分隔）:")
    self._log("示例: https://www.douyin.com/user/xxx")
    self._log("或者输入多个:")
    self._log("  https://www.douyin.com/user/xxx1,https://www.douyin.com/user/xxx2")
    self._log()

    user_input = input("链接: ").strip()

    if not user_input:
        self._log("❌ 链接不能为空")
        return

    # 解析多个链接（支持逗号或换行分隔）
    user_urls = [url.strip() for url in user_input.replace('\n', ',').split(',') if url.strip()]

    if not user_urls:
        self._log("❌ 没有有效的链接")
        return

    scroll_times = input("\n滚动加载次数 (默认10次): ").strip()
    scroll_times = int(scroll_times) if scroll_times else 10

    organize_by_tag = input("是否按标签分类保存? (y/n, 默认n): ").strip().lower() == 'y'

    # 运行下载器
    downloader = DouyinSeleniumDownloader(organize_by_tag=organize_by_tag)

    if len(user_urls) == 1:
        downloader.run(user_urls[0], scroll_times)
    else:
        self._log(f"\n📋 将下载 {len(user_urls)} 个账号的视频")
        downloader.run_batch(user_urls, scroll_times)


if __name__ == "__main__":
    main()
