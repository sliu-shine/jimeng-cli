#!/usr/bin/env python3
"""
抖音视频自动化下载脚本
配合 Tampermonkey 脚本使用
"""

import os
import json
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

    def _log(self, message: str, level: str = "info"):
        """统一的日志输出"""
        print(message)
        if self.log_callback:
            self.log_callback(level, message)

    def _update_progress(self, account_index: int, status: str, progress: int = 0, **kwargs):
        """更新进度"""
        if self.progress_callback:
            self.progress_callback(account_index, status, progress, **kwargs)

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
        time.sleep(3)

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
            time.sleep(2)
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
            time.sleep(2)

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

            # 方法4: 提取标签 - 从多个来源
            tags_set = set()

            # 4.1 从链接提取
            try:
                tag_links = self.driver.find_elements(By.CSS_SELECTOR, 'a[href*="/search/"]')
                for link in tag_links:
                    tag_text = link.text.strip().replace('#', '').strip()
                    if tag_text and len(tag_text) < 30:  # 过滤过长的文本
                        tags_set.add(tag_text)
            except:
                pass

            # 4.2 从标题中提取 #标签
            if metadata['title']:
                import re
                hashtags = re.findall(r'#([^#\s]+)', metadata['title'])
                for tag in hashtags:
                    if tag and len(tag) < 30:
                        tags_set.add(tag)

            # 4.3 从描述中提取 #标签
            if metadata['description']:
                import re
                hashtags = re.findall(r'#([^#\s]+)', metadata['description'])
                for tag in hashtags:
                    if tag and len(tag) < 30:
                        tags_set.add(tag)

            metadata['tags'] = list(tags_set)[:10]  # 最多保留10个标签

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

        self._log(f"\n⬇️  下载视频: {video_id} ({int(likes)}赞)")

        try:
            # 先关闭可能的 alert
            self.dismiss_alert_if_present()

            # 打开视频页面
            self.driver.get(video_url)

            # 等待页面加载完成
            time.sleep(5)  # 增加等待时间，确保页面完全加载

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

            # 方法1: 尝试从页面提取真实视频地址
            video_src = self.extract_video_url()

            if video_src:
                # 构建文件名：[点赞数]_[标题]_[视频ID].mp4
                title_part = self.sanitize_filename(metadata['title']) if metadata['title'] else ''
                likes_str = f"{int(likes/10000)}w" if likes >= 10000 else str(int(likes))

                if title_part:
                    filename = f"[{likes_str}赞]_{title_part}_{video_id}.mp4"
                else:
                    filename = f"[{likes_str}赞]_{video_id}.mp4"

                # 根据标签分类保存
                if self.organize_by_tag and metadata['tags']:
                    # 使用第一个标签作为分类目录
                    tag_dir = self.output_dir / self.sanitize_filename(metadata['tags'][0], max_length=20)
                    tag_dir.mkdir(exist_ok=True)
                    filepath = tag_dir / filename
                else:
                    filepath = self.output_dir / filename

                # 保存元数据到 JSON
                metadata_file = filepath.with_suffix('.json')
                metadata_data = {
                    'video_id': video_id,
                    'video_url': video_url,
                    'likes': int(likes),
                    'title': metadata['title'],
                    'description': metadata['description'],
                    'tags': metadata['tags'],
                    'author': metadata['author'],
                    'download_time': time.strftime('%Y-%m-%d %H:%M:%S')
                }

                with open(metadata_file, 'w', encoding='utf-8') as f:
                    json.dump(metadata_data, f, ensure_ascii=False, indent=2)

                self.download_file(video_src, filepath)
                self._log(f"  ✅ 已保存: {filename}")
                if metadata['title']:
                    self._log(f"  📝 标题: {metadata['title']}")
                if metadata['tags']:
                    self._log(f"  🏷️  标签: {', '.join(metadata['tags'][:5])}")
                return True
            else:
                self._log(f"  ❌ 无法提取视频地址")
                return False

        except Exception as e:
            self._log(f"  ❌ 下载失败: {e}")
            import traceback
            self._log(f"  详细错误: {traceback.format_exc()}", "error")
            return False

    def extract_video_url(self):
        """从页面提取真实视频地址"""
        max_retries = 3
        retry_delay = 3

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
                    time.sleep(3)

                    # 获取所有网络请求
                    logs = self.driver.get_log('performance')

                    # 查找视频请求
                    for log in logs:
                        try:
                            message = json.loads(log['message'])
                            method = message.get('message', {}).get('method', '')

                            if method == 'Network.responseReceived':
                                response = message.get('message', {}).get('params', {}).get('response', {})
                                url = response.get('url', '')
                                mime_type = response.get('mimeType', '')

                                # 查找视频文件
                                if 'video' in mime_type or url.endswith('.mp4') or 'video' in url:
                                    if url.startswith('http'):
                                        self._log(f"  ✓ 从网络请求捕获到视频地址")
                                        return url
                        except:
                            continue

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
                    time.sleep(2)

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

                    if video_src and video_src.startswith('http'):
                        self._log(f"  ✓ 从 JavaScript 提取到地址")
                        return video_src
                except Exception as js_error:
                    self._log(f"  ⚠️  JavaScript 提取失败: {js_error}")

                # 方法2: 从 video 标签获取
                try:
                    video_element = self.driver.find_element(By.TAG_NAME, 'video')
                    video_src = video_element.get_attribute('src')

                    if video_src and video_src.startswith('http'):
                        self._log(f"  ✓ 从 video.src 提取到地址")
                        return video_src

                    # 尝试 currentSrc 属性
                    video_src = video_element.get_attribute('currentSrc')
                    if video_src and video_src.startswith('http'):
                        self._log(f"  ✓ 从 video.currentSrc 提取到地址")
                        return video_src
                except Exception as elem_error:
                    self._log(f"  ⚠️  元素提取失败: {elem_error}")

                # 方法3: 从 source 标签获取
                try:
                    source_elements = self.driver.find_elements(By.TAG_NAME, 'source')
                    for source in source_elements:
                        video_src = source.get_attribute('src')
                        if video_src and video_src.startswith('http'):
                            self._log(f"  ✓ 从 source.src 提取到地址")
                            return video_src
                except Exception as source_error:
                    self._log(f"  ⚠️  source 提取失败: {source_error}")

                # 如果所有方法都失败，尝试刷新页面重试
                if attempt < max_retries - 1:
                    self._log(f"  ⚠️  第 {attempt + 1} 次尝试失败，刷新页面后重试...")
                    self.driver.refresh()
                    time.sleep(retry_delay)
                else:
                    self._log(f"  ⚠️  未找到有效的视频地址")
                    return None

            except Exception as e:
                if attempt < max_retries - 1:
                    self._log(f"  ⚠️  提取失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                    time.sleep(retry_delay)
                else:
                    self._log(f"  ❌ 提取视频地址失败: {e}")
                    return None

        return None

    def download_file(self, url, filepath):
        """下载文件"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Referer': 'https://www.douyin.com/'
        }

        response = requests.get(url, headers=headers, stream=True)
        response.raise_for_status()

        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

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
                time.sleep(2)

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
                    self._log("❌ 没有视频可下载，跳过此账号", "error")
                    self._update_progress(idx - 1, "completed", 100, video_count=0)
                    continue

                video_list = json.loads(video_list_json)
                self._log(f"✅ 读取到 {len(video_list)} 个视频")
                self._update_progress(idx - 1, "processing", 70, video_count=len(video_list))

                # 下载视频
                success_count = 0
                for i, video_info in enumerate(video_list, 1):
                    if self.is_stopped:
                        break

                    self._log(f"\n[{i}/{len(video_list)}]")
                    if self.download_video(video_info):
                        success_count += 1

                    # 更新进度
                    progress = 70 + int((i / len(video_list)) * 25)
                    self._update_progress(idx - 1, "processing", progress,
                                        downloaded=success_count, total=len(video_list))

                    time.sleep(2)  # 避免请求过快

                self._log("\n" + "="*60)
                self._log(f"✅ 账号 [{idx}] 下载完成: {success_count}/{len(video_list)}", "success")
                self._log(f"📁 保存位置: {self.output_dir.absolute()}")
                self._log("="*60)

                self._update_progress(idx - 1, "completed", 100,
                                    video_count=len(video_list), success_count=success_count)

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
                        time.sleep(2)

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
