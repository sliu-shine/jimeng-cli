// ==UserScript==
// @name         抖音视频批量下载助手（增强版）
// @namespace    http://tampermonkey.net/
// @version      2.1
// @description  在抖音用户主页添加批量下载功能，支持多账号队列显示
// @author       You
// @match        https://www.douyin.com/user/*
// @grant        GM_download
// @grant        GM_xmlhttpRequest
// @connect      *
// ==/UserScript==

(function() {
    'use strict';

    // 全局状态
    let scannedVideos = [];
    let accountQueue = [];
    let currentAccountIndex = 0;
    let isProcessing = false;

    // 从 localStorage 读取账号队列
    function loadAccountQueue() {
        try {
            const queueData = localStorage.getItem('douyin_account_queue');
            if (queueData) {
                accountQueue = JSON.parse(queueData);
                console.log('加载账号队列:', accountQueue);
                return true;
            }
        } catch (e) {
            console.error('加载账号队列失败:', e);
        }
        return false;
    }

    // 保存账号队列状态
    function saveAccountQueue() {
        try {
            localStorage.setItem('douyin_account_queue', JSON.stringify(accountQueue));
        } catch (e) {
            console.error('保存账号队列失败:', e);
        }
    }

    // 获取当前账号信息
    function getCurrentAccount() {
        const currentUrl = window.location.href;
        return accountQueue.find(acc => acc.url === currentUrl);
    }

    function cleanText(text) {
        return (text || '').replace(/\s+/g, ' ').trim();
    }

    function getCurrentAccountName() {
        const selectors = [
            '[data-e2e="user-title"]',
            '[data-e2e="user-info"] h1',
            'h1',
            '[class*="user"] [class*="name"]',
            '[class*="nickname"]',
            '[class*="author"]'
        ];

        for (const selector of selectors) {
            const el = document.querySelector(selector);
            const text = cleanText(el?.textContent);
            if (text && text.length <= 60 && !/^抖音$/.test(text)) {
                return text;
            }
        }

        const title = cleanText(document.title);
        if (title) {
            const name = title
                .replace(/的主页.*$/, '')
                .replace(/ - 抖音.*$/, '')
                .replace(/_抖音.*$/, '')
                .replace(/抖音.*$/, '')
                .trim();
            if (name) {
                return name;
            }
        }

        return '';
    }

    // 创建队列显示面板
    function createQueuePanel() {
        const panel = document.createElement('div');
        panel.id = 'douyin-queue-panel';
        panel.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            width: 350px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 12px;
            padding: 20px;
            z-index: 99999;
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            color: white;
        `;

        panel.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                <h3 style="margin: 0; font-size: 18px; font-weight: 600;">📥 下载队列</h3>
                <button id="toggle-queue" style="background: rgba(255,255,255,0.2); border: none; color: white; padding: 5px 10px; border-radius: 6px; cursor: pointer; font-size: 12px;">
                    收起
                </button>
            </div>
            <div id="queue-content">
                <div id="queue-stats" style="background: rgba(255,255,255,0.15); padding: 12px; border-radius: 8px; margin-bottom: 15px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                        <span>总账号数：</span>
                        <strong id="total-accounts">0</strong>
                    </div>
                    <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                        <span>已完成：</span>
                        <strong id="completed-accounts" style="color: #4ade80;">0</strong>
                    </div>
                    <div style="display: flex; justify-content: space-between;">
                        <span>待处理：</span>
                        <strong id="pending-accounts" style="color: #fbbf24;">0</strong>
                    </div>
                </div>
                <div id="current-account" style="background: rgba(255,255,255,0.15); padding: 12px; border-radius: 8px; margin-bottom: 15px;">
                    <div style="font-size: 12px; opacity: 0.8; margin-bottom: 5px;">当前账号</div>
                    <div id="current-account-name" style="font-weight: 600; font-size: 14px;">-</div>
                    <div id="current-progress" style="margin-top: 8px;">
                        <div style="background: rgba(255,255,255,0.3); height: 6px; border-radius: 3px; overflow: hidden;">
                            <div id="progress-bar" style="background: #4ade80; height: 100%; width: 0%; transition: width 0.3s;"></div>
                        </div>
                        <div style="font-size: 11px; margin-top: 5px; opacity: 0.9;" id="progress-text">等待开始...</div>
                    </div>
                </div>
                <div id="account-list" style="max-height: 200px; overflow-y: auto; margin-bottom: 15px;">
                    <!-- 账号列表 -->
                </div>
                <div style="display: flex; gap: 10px;">
                    <button id="start-scan" style="flex: 1; padding: 10px; background: #4ade80; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 14px;">
                        🔍 开始扫描
                    </button>
                    <button id="next-account" style="flex: 1; padding: 10px; background: #fbbf24; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 14px;" disabled>
                        ⏭️ 下一个
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(panel);

        // 绑定事件
        document.getElementById('toggle-queue').addEventListener('click', toggleQueuePanel);
        document.getElementById('start-scan').addEventListener('click', startScan);
        document.getElementById('next-account').addEventListener('click', goToNextAccount);
    }

    // 切换面板显示/隐藏
    function toggleQueuePanel() {
        const content = document.getElementById('queue-content');
        const btn = document.getElementById('toggle-queue');
        if (content.style.display === 'none') {
            content.style.display = 'block';
            btn.textContent = '收起';
        } else {
            content.style.display = 'none';
            btn.textContent = '展开';
        }
    }

    // 更新队列统计
    function updateQueueStats() {
        const total = accountQueue.length;
        const completed = accountQueue.filter(acc => acc.status === 'completed').length;
        const pending = accountQueue.filter(acc => acc.status === 'pending').length;

        document.getElementById('total-accounts').textContent = total;
        document.getElementById('completed-accounts').textContent = completed;
        document.getElementById('pending-accounts').textContent = pending;
    }

    // 更新当前账号显示
    function updateCurrentAccount() {
        const currentAccount = getCurrentAccount();
        if (currentAccount) {
            const nameEl = document.getElementById('current-account-name');
            // 从 URL 提取用户 ID
            const userId = currentAccount.url.match(/user\/([^?]+)/)?.[1] || '未知';
            nameEl.textContent = `账号 ${userId}`;

            const progress = currentAccount.progress || 0;
            document.getElementById('progress-bar').style.width = progress + '%';
            document.getElementById('progress-text').textContent =
                currentAccount.status === 'completed' ? '✅ 已完成' :
                currentAccount.status === 'processing' ? `处理中... ${progress}%` :
                '等待开始...';
        }
    }

    // 更新账号列表
    function updateAccountList() {
        const listDiv = document.getElementById('account-list');
        listDiv.innerHTML = accountQueue.map((acc, i) => {
            const userId = acc.url.match(/user\/([^?]+)/)?.[1] || '未知';
            const statusIcon =
                acc.status === 'completed' ? '✅' :
                acc.status === 'processing' ? '🔄' :
                '⏳';
            const statusText =
                acc.status === 'completed' ? '已完成' :
                acc.status === 'processing' ? '处理中' :
                '待处理';

            return `
                <div style="background: rgba(255,255,255,0.1); padding: 10px; border-radius: 6px; margin-bottom: 8px; font-size: 12px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span>${statusIcon} 账号 ${i + 1}: ${userId.substring(0, 15)}...</span>
                        <span style="font-size: 11px; opacity: 0.8;">${statusText}</span>
                    </div>
                </div>
            `;
        }).join('');
    }

    // 开始扫描当前账号
    function startScan() {
        const currentAccount = getCurrentAccount();
        if (!currentAccount) {
            alert('当前页面不在队列中');
            return;
        }

        if (currentAccount.status === 'completed') {
            if (!confirm('该账号已完成，是否重新扫描？')) {
                return;
            }
        }

        // 更新状态
        currentAccount.status = 'processing';
        currentAccount.progress = 10;
        saveAccountQueue();
        updateUI();

        // 模拟扫描过程
        document.getElementById('progress-text').textContent = '正在扫描视频...';

        setTimeout(() => {
            scanVideos();
        }, 500);
    }

    // 扫描页面上的视频
    function scanVideos() {
        const currentAccount = getCurrentAccount();
        const minLikes = currentAccount?.min_likes || 1000;
        const accountName = getCurrentAccountName();

        scannedVideos = [];

        // 更新进度
        if (currentAccount) {
            currentAccount.progress = 30;
            saveAccountQueue();
            updateUI();
        }

        // 尝试多种选择器策略
        const selectors = [
            'ul li',
            '[class*="video"]',
            'a[href*="/video/"]',
        ];

        let videoElements = [];
        for (const selector of selectors) {
            const elements = document.querySelectorAll(selector);
            if (elements.length > 0) {
                console.log(`使用选择器 "${selector}" 找到 ${elements.length} 个元素`);
                videoElements = Array.from(elements);
                break;
            }
        }

        // 如果是链接元素，需要获取父容器
        if (videoElements.length > 0 && videoElements[0].tagName === 'A') {
            videoElements = videoElements.map(a => a.closest('li') || a.parentElement);
        }

        console.log(`总共找到 ${videoElements.length} 个视频元素`);

        // 更新进度
        if (currentAccount) {
            currentAccount.progress = 50;
            saveAccountQueue();
            updateUI();
        }

        videoElements.forEach(el => {
            const info = getVideoInfo(el);
            if (info && info.likes >= minLikes) {
                scannedVideos.push(info);
            }
        });

        // 按点赞数排序
        scannedVideos.sort((a, b) => b.likes - a.likes);

        // 更新进度
        if (currentAccount) {
            currentAccount.progress = 80;
            saveAccountQueue();
            updateUI();
        }

        // 保存到 localStorage
        const storageKey = `douyin_videos_${currentAccount.url}`;
        localStorage.setItem(storageKey, JSON.stringify(scannedVideos));

        // 完成
        if (currentAccount) {
            if (accountName) {
                currentAccount.name = accountName;
            }
            currentAccount.status = 'completed';
            currentAccount.progress = 100;
            currentAccount.video_count = scannedVideos.length;
            saveAccountQueue();
            updateUI();
        }

        document.getElementById('progress-text').textContent = `✅ 扫描完成！找到 ${scannedVideos.length} 个爆款视频`;
        document.getElementById('next-account').disabled = false;

        // 如果还有待处理的账号，提示用户
        const pendingCount = accountQueue.filter(acc => acc.status === 'pending').length;
        if (pendingCount > 0) {
            setTimeout(() => {
                if (confirm(`扫描完成！找到 ${scannedVideos.length} 个视频\n\n还有 ${pendingCount} 个账号待处理，是否继续？`)) {
                    goToNextAccount();
                }
            }, 1000);
        } else {
            setTimeout(() => {
                alert(`🎉 所有账号扫描完成！\n\n共处理 ${accountQueue.length} 个账号\n请返回 Web UI 查看结果`);
            }, 1000);
        }
    }

    // 获取视频信息
    function getVideoInfo(videoElement) {
        try {
            const currentAccount = getCurrentAccount();
            const accountName = getCurrentAccountName() || currentAccount?.name || '';
            const link = videoElement.querySelector('a[href*="/video/"]') || videoElement.querySelector('a');
            if (!link) return null;

            const videoUrl = link.href;
            const videoId = videoUrl.match(/video\/(\d+)/)?.[1];
            if (!videoId) return null;

            // 获取点赞数
            let likes = 0;
            const likeElement = videoElement.querySelector('[class*="like"]') ||
                               videoElement.querySelector('span[title]') ||
                               Array.from(videoElement.querySelectorAll('span')).find(s => /\d+[wW万]?/.test(s.textContent));

            if (likeElement) {
                const likeText = likeElement.textContent || likeElement.getAttribute('title') || '0';
                likes = parseLikeCount(likeText);
            }

            // 获取封面图
            const img = videoElement.querySelector('img');
            const cover = img?.src || '';

            // 获取视频标题
            let title = '';
            const titleElement = videoElement.querySelector('[class*="title"]') ||
                                videoElement.querySelector('h3') ||
                                videoElement.querySelector('h4') ||
                                videoElement.querySelector('[class*="desc"]') ||
                                link.getAttribute('title');

            if (titleElement) {
                title = typeof titleElement === 'string' ? titleElement : titleElement.textContent?.trim() || '';
            }

            if (!title) {
                const allText = videoElement.textContent?.trim() || '';
                const meaningfulText = allText.replace(/[\d.]+[wW万]?\s*赞?/g, '').trim();
                title = meaningfulText.substring(0, 100) || `视频_${videoId}`;
            }

            // 获取视频标签：只从当前视频标题里的 #话题 提取，避免混入推荐/商品标签
            const tags = [];
            const hashtagMatches = title.match(/#([^\s#，,。！!？?、]+)/g);
            if (hashtagMatches) {
                hashtagMatches.forEach(tag => {
                    const cleanTag = tag.replace(/^#/, '').trim();
                    if (cleanTag.length > 0 && cleanTag.length < 30 && !tags.includes(cleanTag)) {
                        tags.push(cleanTag);
                    }
                });
            }

            const desc = title.substring(0, 50) || videoId;

            return {
                videoId,
                videoUrl,
                likes,
                cover,
                desc,
                title,
                tags,
                accountName
            };
        } catch (e) {
            console.error('解析视频信息失败:', e);
            return null;
        }
    }

    // 解析点赞数
    function parseLikeCount(text) {
        text = text.replace(/[^0-9.wW万]/g, '');
        if (text.includes('w') || text.includes('W') || text.includes('万')) {
            return parseFloat(text) * 10000;
        }
        return parseFloat(text) || 0;
    }

    // 跳转到下一个账号
    function goToNextAccount() {
        const nextAccount = accountQueue.find(acc => acc.status === 'pending');
        if (nextAccount) {
            window.location.href = nextAccount.url;
        } else {
            alert('所有账号已处理完成！');
        }
    }

    // 更新所有 UI
    function updateUI() {
        updateQueueStats();
        updateCurrentAccount();
        updateAccountList();
    }

    // 初始化
    function init() {
        setTimeout(() => {
            // 加载账号队列
            const hasQueue = loadAccountQueue();

            if (hasQueue && accountQueue.length > 0) {
                // 显示队列面板
                createQueuePanel();
                updateUI();

                console.log('抖音下载助手已启动，队列中有', accountQueue.length, '个账号');
            } else {
                console.log('未检测到下载队列，请从 Web UI 启动下载任务');
            }
        }, 2000);
    }

    // 页面加载完成后初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
