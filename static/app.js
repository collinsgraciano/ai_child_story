/**
 * 儿童故事图片视频生成工具 - 前端交互逻辑
 */

// 全局状态
let storyData = null;
let currentModalPageIndex = null;
let currentConfig = null;
let currentProjectName = null;  // 当前项目名称
let isGenerating = false;  // 是否正在批量生成
let jsonInputVisible = false;  // JSON 输入区域是否可见

// 图片缓存，用于避免重复刷新导致闪烁
const loadedImages = new Map();  // {key: imagePath}
const loadedSheets = { character: null, scene: null };

// ===== 初始化 =====
document.addEventListener('DOMContentLoaded', async () => {
    // 尝试恢复上次项目
    const lastProject = localStorage.getItem('lastProjectName');
    if (lastProject) {
        await switchProject(lastProject, true);  // 静默切换
    } else {
        await loadStory();
    }

    loadConfig();
    loadProjects();  // 加载项目列表

    // 定期刷新状态
    setInterval(refreshStatus, 5000);
});

// ===== 加载故事数据 =====
async function loadStory() {
    try {
        const response = await fetch('/api/story');
        const result = await response.json();

        if (result.success) {
            storyData = result.data;
            updateHeader();
            renderPages();
            refreshStatus();
        } else {
            showToast('加载故事失败: ' + result.error, 'error');
        }
    } catch (error) {
        showToast('网络错误: ' + error.message, 'error');
    }
}

// ===== 加载配置 =====
async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        const result = await response.json();

        if (result.success) {
            currentConfig = result.config;
            populateSettingsForm();
        }
    } catch (error) {
        console.error('加载配置失败:', error);
    }
}

// ===== 任务队列类 =====
class TaskQueue {
    constructor(concurrency = 1) {
        this.concurrency = concurrency;
        this.queue = [];
        this.running = 0;
        this.active = false;
        this.stats = { total: 0, completed: 0, failed: 0 };
    }

    add(task) {
        this.queue.push(task);
        this.stats.total++;
        this.process();
    }

    async process() {
        if (!this.active || this.running >= this.concurrency || this.queue.length === 0) {
            return;
        }

        this.running++;
        const task = this.queue.shift();

        // 关键修复: 立即尝试启动下一个任务，填满并发槽
        this.process();

        try {
            await task();
            this.stats.completed++;
        } catch (e) {
            console.error(e);
            this.stats.failed++;
        } finally {
            this.running--;
            this.process();
        }
    }

    start() {
        this.active = true;
        this.stats = { total: this.queue.length, completed: 0, failed: 0 }; // 重置统计
        this.process();
    }

    stop() {
        this.active = false;
        this.queue = [];
    }

    // 等待队列空闲
    async waitIdle() {
        return new Promise(resolve => {
            const check = () => {
                if (this.queue.length === 0 && this.running === 0) {
                    resolve();
                } else {
                    setTimeout(check, 500);
                }
            };
            check();
        });
    }
}

// ===== 填充设置表单 =====
function populateSettingsForm() {
    if (!currentConfig) return;

    // 图片 API
    document.getElementById('imageApiUrl').value = currentConfig.image_api?.base_url || '';
    document.getElementById('imageApiKey').value = currentConfig.image_api?.api_key || '';
    document.getElementById('imageModel').value = currentConfig.image_api.model;

    document.getElementById('videoApiUrl').value = currentConfig.video_api.base_url;
    document.getElementById('videoApiKey').value = currentConfig.video_api.api_key;
    document.getElementById('videoModel').value = currentConfig.video_api.model;

    // 默认值处理
    document.getElementById('batchSize').value = currentConfig.generation.batch_size || 1;

    // 读取嵌套的并发设置
    const concurrency = (currentConfig.generation && currentConfig.generation.concurrency) || {};
    document.getElementById('concurrencyImage').value = concurrency.image || 2;
    document.getElementById('concurrencyVideo').value = concurrency.video || 1;
    console.log(`[Config] Loaded concurrency: Image=${concurrency.image}, Video=${concurrency.video}`);
}

// ===== 切换设置面板 =====
function toggleSettings() {
    loadConfig();
    const panel = document.getElementById('settingsPanel');
    panel.classList.toggle('expanded');

}

// ===== 保存设置 =====
async function saveSettings() {
    const newConfig = {
        image_api: {
            base_url: document.getElementById('imageApiUrl').value.trim(),
            api_key: document.getElementById('imageApiKey').value.trim(),
            model: document.getElementById('imageModel').value.trim()
        },
        video_api: {
            base_url: document.getElementById('videoApiUrl').value.trim(),
            api_key: document.getElementById('videoApiKey').value.trim(),
            model: document.getElementById('videoModel').value.trim()
        },
        generation: {
            batch_size: parseInt(document.getElementById('batchSize').value) || 1,
            concurrency: {
                image: parseInt(document.getElementById('concurrencyImage').value) || 2,
                video: parseInt(document.getElementById('concurrencyVideo').value) || 1
            }
        }
    };

    try {
        updateProgress('正在保存设置...');

        const response = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(newConfig)
        });

        const result = await response.json();

        if (result.success) {
            currentConfig = result.config;
            showToast('设置已保存', 'success');
            // 自动收起
            document.getElementById('settingsPanel').classList.remove('expanded');
            updateProgress('设置保存成功');
        } else {
            showToast('保存失败: ' + result.error, 'error');
        }
    } catch (error) {
        showToast('网络错误: ' + error.message, 'error');
    }
}

// ===== 批量生成视频 =====
async function generateAllVideos() {
    if (!storyData || !storyData.script) {
        showToast('请先加载故事数据', 'error');
        return;
    }

    // 从配置读取并发数
    const concurrency = (currentConfig && currentConfig.generation && currentConfig.generation.concurrency && currentConfig.generation.concurrency.video) || 1;
    const queue = new TaskQueue(concurrency);
    const btn = event.currentTarget; // 获取点击的按钮

    // UI 状态
    updateProgress(`正在获取生成状态...`);
    btn.disabled = true;

    // 获取最新状态以决定跳过哪些
    let statusMap = {};
    try {
        const response = await fetch('/api/status');
        const result = await response.json();
        if (result.success) {
            statusMap = result.status.pages;
        }
    } catch (e) {
        console.error("获取状态失败", e);
        // 如果获取失败，则不跳过（或者提示错误），这里选择继续尝试但不跳过
    }

    updateProgress(`开始批量生成视频 (并发: ${concurrency})...`);

    // 筛选任务：已完成图片但未完成视频的页面
    let count = 0;
    let skippedVideo = 0;
    let skippedNoImage = 0;

    for (const page of storyData.script) {
        const pageIndex = page.page_index;
        const pageStatus = statusMap[pageIndex] || {};

        // 1. 如果视频已生成，跳过
        if (pageStatus.video === 'completed') {
            skippedVideo++;
            continue;
        }

        // 2. 如果图片未生成，跳过
        if (pageStatus.image !== 'completed') {
            skippedNoImage++;
            continue;
        }

        queue.add(async () => {
            updateProgress(`正在请求第 ${pageIndex} 页视频...`);
            await generatePageVideo(pageIndex);
        });
        count++;
    }

    if (count === 0) {
        updateProgress(`没有需要生成的视频 (跳过: 已有${skippedVideo}, 无图${skippedNoImage})`);
        showToast(`没有任务: ${skippedVideo}个已有视频, ${skippedNoImage}个无图片`, 'info');
        btn.disabled = false;
        return;
    }

    updateProgress(`已添加 ${count} 个视频任务到队列...`);
    queue.start();

    await queue.waitIdle();

    updateProgress('✅ 批量视频生成完成');
    showToast('批量视频生成完成', 'success');
    btn.disabled = false;
}

// ===== 全流程生成 (图片 -> 视频) =====
async function generateAllImagesAndVideos() {
    if (!storyData) {
        showToast('请先加载故事数据', 'error');
        return;
    }

    if (!confirm("⚠️ 确定要开始全流程生成吗？\n这将先批量生成所有图片，然后自动开始生成视频。")) return;

    // 1. 批量生成图片
    updateProgress('🚀 阶段 1/2: 批量生成图片...');
    await generateAllImages(true); // 传入 true 表示静默/非阻塞或者复用逻辑

    // 2. 批量生成视频
    // 2. 批量生成视频
    updateProgress('🚀 阶段 2/2: 批量生成视频...');

    // 获取最新状态以决定跳过哪些
    let statusMap = {};
    try {
        const response = await fetch('/api/status');
        const result = await response.json();
        if (result.success) {
            statusMap = result.status.pages;
        }
    } catch (e) {
        console.error("获取状态失败", e);
    }

    // 从配置读取并发数
    let concurrency = 1;
    if (currentConfig && currentConfig.generation) {
        if (currentConfig.generation.concurrency && currentConfig.generation.concurrency.video) {
            concurrency = currentConfig.generation.concurrency.video;
        } else if (currentConfig.generation.video_concurrency) {
            concurrency = currentConfig.generation.video_concurrency;
        }
    }

    const queue = new TaskQueue(concurrency);

    let count = 0;
    let skippedVideo = 0;

    for (const page of storyData.script) {
        const pageIndex = page.page_index;
        const pageStatus = statusMap[pageIndex] || {};

        // 1. 如果视频已生成，跳过
        if (pageStatus.video === 'completed') {
            skippedVideo++;
            continue;
        }
        // Pipeline 模式下通常不跳过“无图”，因为刚才已经生成了。如果真失败了，下面的 video 生成自然会失败。

        queue.add(async () => {
            updateProgress(`正在生成视频: 第 ${pageIndex} 页...`);
            await generatePageVideo(pageIndex);
        });
        count++;
    }

    if (count === 0) {
        updateProgress(`没有需要生成的视频 (跳过: ${skippedVideo} 个已存在)`);
    } else {
        updateProgress(`已添加 ${count} 个视频任务到队列 (并发: ${concurrency})...`);
        queue.start();
        await queue.waitIdle();
    }

    updateProgress('✅ 全流程生成任务完成！');
    showToast('全流程生成任务完成！', 'success');
}

// ===== 批量生成图片 (重构支持并发) =====
async function generateAllImages(isChained = false) {
    if (!storyData || !storyData.script) {
        showToast('请先加载故事数据', 'error');
        return;
    }

    const concurrency = currentConfig?.generation?.concurrency?.image || 2;
    const queue = new TaskQueue(concurrency);

    updateProgress(`开始批量生成图片 (并发: ${concurrency})...`);

    // 1. 确保设计稿 (串行)
    if (!loadedSheets.character) await generateCharacterSheet();
    if (!loadedSheets.scene) await generateSceneSheet();

    // 2. 提交分镜任务
    for (const page of storyData.script) {
        queue.add(async () => {
            updateProgress(`正在请求第 ${page.page_index} 页图片...`);
            await generatePageImage(page.page_index);
        });
    }

    queue.start();
    await queue.waitIdle();

    if (!isChained) {
        updateProgress('✅ 批量图片生成完成');
        showToast('批量图片生成完成', 'success');
    }
}

// ===== 切换 JSON 输入区域 =====
function toggleJsonInput() {
    jsonInputVisible = !jsonInputVisible;
    const wrapper = document.getElementById('jsonInputWrapper');
    const toggleText = document.getElementById('toggleJsonText');

    if (jsonInputVisible) {
        wrapper.style.display = 'block';
        toggleText.textContent = '收起输入';
    } else {
        wrapper.style.display = 'none';
        toggleText.textContent = '展开输入';
    }
}

// ===== 加载 JSON 输入 =====
async function loadJsonInput() {
    const jsonContent = document.getElementById('jsonInput').value.trim();
    const jsonStatus = document.getElementById('jsonStatus');
    const loadBtn = document.getElementById('loadJsonBtn');

    if (!jsonContent) {
        showToast('请先粘贴 JSON 数据', 'error');
        return;
    }

    // 更新状态
    jsonStatus.textContent = '正在解析...';
    loadBtn.disabled = true;

    try {
        const response = await fetch('/api/story/upload', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ json_content: jsonContent })
        });

        const result = await response.json();

        if (result.success) {
            jsonStatus.textContent = `✅ ${result.message}`;
            showToast(result.message, 'success');

            // 清空缓存并重新加载页面数据
            loadedImages.clear();
            loadedSheets.character = null;
            loadedSheets.scene = null;
            currentProjectName = result.project_name;

            // 重新加载故事
            await loadStory();

            // 收起 JSON 输入区
            if (jsonInputVisible) {
                toggleJsonInput();
            }
        } else {
            jsonStatus.textContent = `❌ ${result.error}`;
            showToast('加载失败: ' + result.error, 'error');
        }
    } catch (error) {
        jsonStatus.textContent = `❌ 网络错误`;
        showToast('网络错误: ' + error.message, 'error');
    } finally {
        loadBtn.disabled = false;
    }
}

// ===== 加载项目列表 =====
async function loadProjects() {
    try {
        const response = await fetch('/api/projects');
        const result = await response.json();

        if (result.success) {
            const selector = document.getElementById('projectSelector');
            selector.innerHTML = '<option value="">-- 选择项目 --</option>';

            result.projects.forEach(project => {
                const option = document.createElement('option');
                option.value = project.name;
                option.textContent = `${project.title} (${project.pages}页)`;
                if (project.name === result.current) {
                    option.selected = true;
                }
                selector.appendChild(option);
            });
        }
    } catch (error) {
        console.error('加载项目列表失败:', error);
    }
}

// ===== 切换项目 =====
async function switchProject(projectName, silent = false) {
    if (!projectName) return;

    try {
        const response = await fetch('/api/project/switch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_name: projectName })
        });

        const result = await response.json();

        if (result.success) {
            // 清空缓存
            loadedImages.clear();
            loadedSheets.character = null;
            loadedSheets.scene = null;
            currentProjectName = result.project_name;

            // 保存到 localStorage
            localStorage.setItem('lastProjectName', projectName);

            // 重新加载故事
            await loadStory();
            await loadProjects();

            if (!silent) {
                showToast(`已切换到项目: ${result.title}`, 'success');
            }
        } else if (!silent) {
            showToast('切换项目失败: ' + result.error, 'error');
        }
    } catch (error) {
        if (!silent) {
            showToast('网络错误: ' + error.message, 'error');
        }
    }
}

// ===== 删除当前项目 =====
async function deleteCurrentProject() {
    const selector = document.getElementById('projectSelector');
    const projectName = selector.value;

    if (!projectName) {
        showToast('请先选择一个项目', 'error');
        return;
    }

    const projectTitle = selector.options[selector.selectedIndex].text;

    if (!confirm(`⚠️ 警告：确定要永久删除项目 "${projectTitle}" 吗？\n删除后无法恢复，所有生成的图片和视频都将丢失！`)) {
        return;
    }

    try {
        const response = await fetch('/api/project/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_name: projectName })
        });

        const result = await response.json();

        if (result.success) {
            showToast(result.message, 'success');

            // 重新加载项目列表
            await loadProjects();

            // 如果删除了当前项目，清空状态并刷新页面
            if (result.is_current) {
                // 尝试切换到第一个可用项目，或者重置
                const remainingOptions = document.getElementById('projectSelector').options;
                if (remainingOptions.length > 1) { // 索引0是占位符
                    await switchProject(remainingOptions[1].value);
                } else {
                    location.reload(); // 无项目，刷新页面重置
                }
            }
        } else {
            showToast('删除失败: ' + result.error, 'error');
        }
    } catch (error) {
        showToast('网络错误: ' + error.message, 'error');
    }
}

// ===== 更新提示词 =====
async function updatePrompt(pageIndex, promptType, newValue) {
    try {
        const response = await fetch('/api/story/update-prompt', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                page_index: pageIndex,
                prompt_type: promptType,
                value: newValue
            })
        });

        const result = await response.json();

        if (result.success) {
            showToast(result.message, 'success');
            // 更新本地数据
            const page = storyData.script.find(p => p.page_index === pageIndex);
            if (page) {
                page[promptType] = newValue;
            }
        } else {
            showToast('更新失败: ' + result.error, 'error');
        }
    } catch (error) {
        showToast('网络错误: ' + error.message, 'error');
    }
}



// ===== 一键生成所有图片 =====
// function generateAllSequential removed (replaced by generateAllImages)

// ===== 更新头部信息 =====
function updateHeader() {
    document.getElementById('storyTitle').textContent = storyData.title || '儿童故事';
    document.getElementById('storySubtitle').textContent = storyData.story_insight || '';
}

// ===== 渲染分镜页面 =====
function renderPages() {
    const grid = document.getElementById('pagesGrid');
    grid.innerHTML = '';

    if (!storyData || !storyData.script) {
        grid.innerHTML = '<div class="loading-placeholder"><p>暂无分镜数据</p></div>';
        return;
    }

    storyData.script.forEach(page => {
        const card = createPageCard(page);
        grid.appendChild(card);
    });
}

// ===== 创建分镜卡片 =====
function createPageCard(page) {
    const card = document.createElement('div');
    card.className = 'page-card';
    card.id = `page-${page.page_index}`;

    const shortNarration = page.narration ?
        (page.narration.length > 150 ? page.narration.substring(0, 150) + '...' : page.narration)
        : '暂无旁白';

    card.innerHTML = `
        <div class="page-header">
            <span class="page-number">第 ${page.page_index} 页</span>
            <div class="page-header-actions">
                <button class="btn btn-primary btn-xs" onclick="generatePageImage(${page.page_index})">
                    🖼️ 图片
                </button>
                <button class="btn btn-secondary btn-xs" onclick="generatePageVideo(${page.page_index})" 
                        id="video-btn-${page.page_index}" disabled>
                    🎬 视频
                </button>
                <input type="checkbox" class="page-select" 
                       onchange="toggleSelect(${page.page_index})" 
                       id="select-${page.page_index}">
            </div>
        </div>
        
        <!-- 1. 图片预览 -->
        <div class="page-preview" id="preview-${page.page_index}">
            <div class="placeholder">
                <span class="icon">📷</span>
                <p>点击生成图片</p>
            </div>
        </div>
        
        <!-- 2. 图片提示词 (可编辑) -->
        <div class="prompt-section image-prompt-section">
            <div class="prompt-header">
                <span class="prompt-label">📷 图片提示词</span>
            </div>
            <textarea class="prompt-input" 
                      onchange="updatePrompt(${page.page_index}, 'image_prompt', this.value)"
                      placeholder="在此输入图片提示词...">${(page.image_prompt || '').replace(/</g, '&lt;')}</textarea>
        </div>
        
        <!-- 3. 视频预览区域 -->
        <div class="video-preview-section" id="video-preview-${page.page_index}">
            <div class="video-placeholder">
                <span class="icon">🎬</span>
                <span>视频待生成</span>
            </div>
        </div>
        
        <!-- 4. 视频提示词 (可编辑) -->
        <div class="prompt-section video-prompt-section">
            <div class="prompt-header">
                <span class="prompt-label">🎬 视频提示词</span>
            </div>
             <textarea class="prompt-input" 
                      onchange="updatePrompt(${page.page_index}, 'video_prompt', this.value)"
                      placeholder="在此输入视频提示词...">${(page.video_prompt || '').replace(/</g, '&lt;')}</textarea>
        </div>
        
        <!-- 5. 旁白 -->
        <div class="narration-section">
            <div class="prompt-label">📖 旁白</div>
            <div class="narration-text">${shortNarration}</div>
        </div>
    `;

    return card;
}

// ===== 刷新状态 =====
async function refreshStatus() {
    try {
        const response = await fetch('/api/status');
        const result = await response.json();

        if (result.success) {
            updateStatusUI(result);
        }
    } catch (error) {
        console.error('刷新状态失败:', error);
    }
}

// ===== 更新状态 UI =====
function updateStatusUI(result) {
    const { status, paths, project_name } = result;

    // 更新项目名称
    if (project_name) {
        currentProjectName = project_name;
    }

    // 更新角色设计稿状态
    updateSheetStatus('character', status.character_sheet, paths.character_sheet);

    // 更新场景设计稿状态
    updateSheetStatus('scene', status.scene_sheet, paths.scene_sheet);

    // 更新每页状态
    for (const [pageIndex, pageStatus] of Object.entries(status.pages)) {
        updatePageStatus(parseInt(pageIndex), pageStatus);
    }
}

// ===== 更新设计稿状态 =====
function updateSheetStatus(type, status, path) {
    const statusBadge = document.getElementById(`${type}Status`);
    const preview = document.getElementById(`${type}Preview`);

    if (statusBadge) {
        statusBadge.className = 'status-badge';
        if (status === 'generating') {
            statusBadge.textContent = '生成中...';
            statusBadge.classList.add('generating');
        } else if (status === 'completed') {
            statusBadge.textContent = '已完成';
            statusBadge.classList.add('completed');
        } else if (status === 'failed') {
            statusBadge.textContent = '失败';
            statusBadge.classList.add('failed');
        } else {
            statusBadge.textContent = '未生成';
        }
    }

    // 仅在路径变化时更新 DOM，避免闪烁
    if (preview && path && loadedSheets[type] !== path) {
        loadedSheets[type] = path;
        preview.innerHTML = `<img src="${path}?t=${Date.now()}" alt="${type}设计稿" onclick="openImageModal('${path}', -1)">`;
    }
}

// ===== 更新分镜页面状态 =====
function updatePageStatus(pageIndex, pageStatus) {
    const previewDiv = document.getElementById(`preview-${pageIndex}`);
    const videoBtn = document.getElementById(`video-btn-${pageIndex}`);
    const selectBox = document.getElementById(`select-${pageIndex}`);
    const card = document.getElementById(`page-${pageIndex}`);

    // 更新图片预览
    if (previewDiv && pageStatus.image === 'completed') {
        const projectPath = currentProjectName ? `${currentProjectName}/` : '';
        const imgPath = `/output/${projectPath}images/page_${String(pageIndex).padStart(3, '0')}.png`;
        const cacheKey = `page-${pageIndex}`;
        const cachedPath = loadedImages.get(cacheKey);

        // 仅在首次加载或路径变化时更新 DOM，避免闪烁
        if (!cachedPath || cachedPath !== imgPath) {
            loadedImages.set(cacheKey, imgPath);
            previewDiv.innerHTML = `
                <img src="${imgPath}?t=${Date.now()}" alt="第${pageIndex}页" onclick="openImageModal('${imgPath}', ${pageIndex})">
            `;
        }

        // 添加视频已完成标记（不覆盖图片点击）
        if (pageStatus.video === 'completed' && !previewDiv.querySelector('.video-badge')) {
            previewDiv.insertAdjacentHTML('beforeend', '<span class="video-badge has-video">🎬</span>');
        }
    } else if (previewDiv && pageStatus.image === 'generating') {
        loadedImages.delete(`page-${pageIndex}`);  // 清除缓存
        previewDiv.innerHTML = `
            <div class="placeholder">
                <div class="spinner"></div>
                <p>生成中...</p>
            </div>
        `;
    }

    // 更新视频按钮状态
    if (videoBtn) {
        videoBtn.disabled = pageStatus.image !== 'completed';
        if (pageStatus.video === 'generating') {
            videoBtn.textContent = '⏳ 生成中...';
            videoBtn.disabled = true;
        } else if (pageStatus.video === 'completed') {
            videoBtn.textContent = '▶️ 查看视频';
            videoBtn.onclick = () => openVideoModal(pageIndex);
        }
    }

    // 更新视频预览区域
    const videoPreviewSection = document.getElementById(`video-preview-${pageIndex}`);
    if (videoPreviewSection) {
        if (pageStatus.video === 'completed') {
            const projectPath = currentProjectName ? `${currentProjectName}/` : '';
            const videoPath = `/output/${projectPath}videos/page_${String(pageIndex).padStart(3, '0')}.mp4`;
            if (!videoPreviewSection.querySelector('video')) {
                videoPreviewSection.innerHTML = `
                    <video src="${videoPath}" muted loop 
                           onmouseenter="this.play()" onmouseleave="this.pause()"
                           onclick="openVideoModal(${pageIndex})" style="cursor: pointer;"></video>
                `;
            }
        } else if (pageStatus.video === 'generating') {
            videoPreviewSection.innerHTML = `
                <div class="video-placeholder">
                    <div class="spinner"></div>
                    <span>视频生成中...</span>
                </div>
            `;
        }
    }

    // 更新选中状态
    if (selectBox) {
        selectBox.checked = pageStatus.selected;
    }

    if (card) {
        card.classList.toggle('selected', pageStatus.selected);
    }
}

// ===== 生成角色设计稿 =====
async function generateCharacterSheet() {
    updateProgress('正在生成角色设计稿...');
    document.getElementById('characterStatus').textContent = '生成中...';
    document.getElementById('characterStatus').className = 'status-badge generating';

    try {
        const response = await fetch('/api/generate/character-sheet', { method: 'POST' });
        const result = await response.json();

        if (result.success) {
            updateProgress('角色设计稿生成成功！');
            showToast('角色设计稿生成成功', 'success');
            refreshStatus();
        } else {
            showToast('生成失败: ' + result.error, 'error');
            document.getElementById('characterStatus').textContent = '失败';
            document.getElementById('characterStatus').className = 'status-badge failed';
        }
    } catch (error) {
        showToast('网络错误: ' + error.message, 'error');
    }
}

// ===== 生成场景设计稿 =====
async function generateSceneSheet() {
    updateProgress('正在生成场景设计稿...');
    document.getElementById('sceneStatus').textContent = '生成中...';
    document.getElementById('sceneStatus').className = 'status-badge generating';

    try {
        const response = await fetch('/api/generate/scene-sheet', { method: 'POST' });
        const result = await response.json();

        if (result.success) {
            updateProgress('场景设计稿生成成功！');
            showToast('场景设计稿生成成功', 'success');
            refreshStatus();
        } else {
            showToast('生成失败: ' + result.error, 'error');
            document.getElementById('sceneStatus').textContent = '失败';
            document.getElementById('sceneStatus').className = 'status-badge failed';
        }
    } catch (error) {
        showToast('网络错误: ' + error.message, 'error');
    }
}

// ===== 生成分镜图片 =====
async function generatePageImage(pageIndex) {
    updateProgress(`正在生成第 ${pageIndex} 页图片...`);

    try {
        const response = await fetch(`/api/generate/page-image/${pageIndex}`, { method: 'POST' });
        const text = await response.text();
        let result;
        try {
            result = JSON.parse(text);
        } catch (e) {
            throw new Error(`服务器响应错误: ${text.substring(0, 100)}...`);
        }

        if (result.success) {
            updateProgress(`第 ${pageIndex} 页图片生成成功！`);
            showToast(`第 ${pageIndex} 页图片生成成功`, 'success');
            refreshStatus();
        } else {
            showToast('生成失败: ' + result.error, 'error');
        }
    } catch (error) {
        showToast('网络错误: ' + error.message, 'error');
    }
}

// ===== 生成分镜视频 =====
async function generatePageVideo(pageIndex) {
    updateProgress(`正在生成第 ${pageIndex} 页视频...`);

    const btn = document.getElementById(`video-btn-${pageIndex}`);
    if (btn) {
        btn.textContent = '⏳ 生成中...';
        btn.disabled = true;
    }

    try {
        const response = await fetch(`/api/generate/page-video/${pageIndex}`, { method: 'POST' });
        const text = await response.text();
        let result;
        try {
            result = JSON.parse(text);
        } catch (e) {
            throw new Error(`服务器响应错误: ${text.substring(0, 100)}...`);
        }

        if (result.success) {
            updateProgress(`第 ${pageIndex} 页视频生成成功！`);
            showToast(`第 ${pageIndex} 页视频生成成功`, 'success');
            refreshStatus();
        } else {
            showToast('生成失败: ' + result.error, 'error');
            if (btn) {
                btn.textContent = '🎬 生成视频';
                btn.disabled = false;
            }
        }
    } catch (error) {
        showToast('网络错误: ' + error.message, 'error');
        if (btn) {
            btn.textContent = '🎬 生成视频';
            btn.disabled = false;
        }
    }
}

// ===== 切换选中状态 =====
async function toggleSelect(pageIndex) {
    try {
        const response = await fetch(`/api/select/${pageIndex}`, { method: 'POST' });
        const result = await response.json();

        if (result.success) {
            const card = document.getElementById(`page-${pageIndex}`);
            card.classList.toggle('selected', result.selected);
        }
    } catch (error) {
        console.error('切换选中失败:', error);
    }
}

// ===== 批量生成图片 =====
// function generateAllImages (serial) removed (replaced by concurrent version)

// ===== 生成选中视频 =====
async function generateSelectedVideos() {
    // 获取所有选中的页面
    const selectedPages = [];
    document.querySelectorAll('.page-select:checked').forEach(checkbox => {
        const pageIndex = parseInt(checkbox.id.replace('select-', ''));
        selectedPages.push(pageIndex);
    });

    if (selectedPages.length === 0) {
        showToast('请先选择要生成视频的页面', 'error');
        return;
    }

    updateProgress(`开始生成 ${selectedPages.length} 个视频...`);

    // 从配置读取并发数
    let concurrency = 1;
    let source = "default";

    // Debug: 打印完整配置
    console.log("[BatchVideo] Current Config:", JSON.stringify(currentConfig, null, 2));

    if (currentConfig && currentConfig.generation) {
        if (currentConfig.generation.concurrency && currentConfig.generation.concurrency.video) {
            concurrency = currentConfig.generation.concurrency.video;
            source = "concurrency.video";
        } else if (currentConfig.generation.video_concurrency) {
            concurrency = currentConfig.generation.video_concurrency;
            source = "video_concurrency";
        }
    }

    // 强制转换为整数
    concurrency = parseInt(concurrency, 10) || 1;

    const msg = `开始生成 ${selectedPages.length} 个视频 (并发: ${concurrency}, 源: ${source})`;
    updateProgress(msg);
    showToast(msg, 'info'); // 显式提示
    console.log(`[BatchVideo] ${msg}`);

    // 使用任务队列
    const queue = new TaskQueue(concurrency);
    let completedCount = 0;

    for (let i = 0; i < selectedPages.length; i++) {
        const pageIndex = selectedPages[i];
        queue.add(async () => {
            updateProgress(`正在生成视频: 第 ${pageIndex} 页...`);
            await generatePageVideo(pageIndex);
            completedCount++;
            updateProgress(`视频生成进度: ${completedCount}/${selectedPages.length}`);
        });
    }

    queue.start();
    await queue.waitIdle();

    updateProgress('选中视频全部生成完成！');
    showToast('选中视频全部生成完成', 'success');
}

// ===== 打开图片模态框 =====
function openImageModal(path, pageIndex) {
    currentModalPageIndex = pageIndex;
    const modal = document.getElementById('imageModal');
    const img = document.getElementById('modalImage');
    img.src = path + '?t=' + Date.now();
    modal.classList.add('show');
}

// ===== 关闭图片模态框 =====
function closeModal() {
    document.getElementById('imageModal').classList.remove('show');
    currentModalPageIndex = null;
}

// ===== 打开视频模态框 =====
function openVideoModal(pageIndex) {
    currentModalPageIndex = pageIndex;
    const modal = document.getElementById('videoModal');
    const video = document.getElementById('modalVideo');
    const projectPath = currentProjectName ? `${currentProjectName}/` : '';
    const videoPath = `/output/${projectPath}videos/page_${String(pageIndex).padStart(3, '0')}.mp4`;
    video.src = videoPath + '?t=' + Date.now();
    modal.classList.add('show');
}

// ===== 关闭视频模态框 =====
function closeVideoModal() {
    document.getElementById('videoModal').classList.remove('show');
    document.getElementById('modalVideo').pause();
    currentModalPageIndex = null;
}

// ===== 重新生成当前图片 =====
async function regenerateCurrentImage() {
    if (currentModalPageIndex === null) return;

    // 必须先保存索引，因为 closeModal 会重置 currentModalPageIndex
    const pageIndex = currentModalPageIndex;

    closeModal();

    if (pageIndex === -1) {
        showToast('请使用设计稿区域的按钮重新生成', 'error');
    } else {
        await generatePageImage(pageIndex);
    }
}

// ===== 重新生成当前视频 =====
async function regenerateCurrentVideo() {
    if (currentModalPageIndex === null) return;

    // 必须先保存索引，因为 closeVideoModal 会重置 currentModalPageIndex
    const pageIndex = currentModalPageIndex;

    closeVideoModal();
    await generatePageVideo(pageIndex);
}

// ===== 更新进度提示 =====
function updateProgress(text) {
    document.getElementById('progressText').textContent = text;
}

// ===== 显示 Toast 提示 =====
function showToast(message, type = 'success') {
    // 移除现有 toast
    const existingToast = document.querySelector('.toast');
    if (existingToast) {
        existingToast.remove();
    }

    // 创建新 toast
    const toast = document.createElement('div');
    toast.className = `toast ${type} show`;
    toast.innerHTML = `${type === 'success' ? '✅' : '❌'} ${message}`;
    document.body.appendChild(toast);

    // 3 秒后自动隐藏
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ===== 点击模态框外部关闭 =====
document.getElementById('imageModal').addEventListener('click', (e) => {
    if (e.target.id === 'imageModal') {
        closeModal();
    }
});

document.getElementById('videoModal').addEventListener('click', (e) => {
    if (e.target.id === 'videoModal') {
        closeVideoModal();
    }
});

document.getElementById('settingsModal').addEventListener('click', (e) => {
    if (e.target.id === 'settingsModal') {
        closeSettings();
    }
});

// ===== 键盘事件 =====
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeModal();
        closeVideoModal();
        closeSettings();
    }
});
