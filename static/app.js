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
const loadedSheets = { character: null, scene: null, item: null };

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
    loadStyles();    // [NEW] 加载风格列表
    setupSettingsAutoSave(); // [NEW] 设置自动保存

    // 定期刷新状态
    setInterval(refreshStatus, 5000);
});

// ===== 设置自动保存 =====
function setupSettingsAutoSave() {
    const settingsPanel = document.getElementById('settingsPanel');
    if (!settingsPanel) return;

    // 为所有 input 和 textarea 添加自动保存
    const inputs = settingsPanel.querySelectorAll('input, textarea');
    inputs.forEach(input => {
        input.addEventListener('input', debouncedSaveSettings);
        input.addEventListener('change', debouncedSaveSettings);
    });

    console.log(`[Settings] Auto-save bound to ${inputs.length} inputs`);
}

// ===== 风格管理 =====
let currentStyleName = null;

async function loadStyles() {
    try {
        const response = await fetch('/api/styles');
        const result = await response.json();

        if (result.success) {
            const select = document.getElementById('styleSelect');
            select.innerHTML = '<option value="">-- 无风格 --</option>';

            result.styles.forEach(style => {
                const option = document.createElement('option');
                option.value = style.name;
                option.textContent = style.name;
                select.appendChild(option);
            });

            // 设置当前选中
            if (result.current_style) {
                select.value = result.current_style;
                currentStyleName = result.current_style;
                updateStylePreview(result.styles.find(s => s.name === result.current_style));
            }

            // [NEW] 同时填充设置中的默认风格下拉框
            const defaultStyleSelect = document.getElementById('defaultStyle');
            if (defaultStyleSelect) {
                defaultStyleSelect.innerHTML = '<option value="">-- 无默认风格 --</option>';
                result.styles.forEach(style => {
                    const option = document.createElement('option');
                    option.value = style.name;
                    option.textContent = style.name;
                    defaultStyleSelect.appendChild(option);
                });

                // 读取配置中的默认风格并选中
                const configDefaultStyle = currentConfig?.generation?.default_style || '';
                if (configDefaultStyle) {
                    defaultStyleSelect.value = configDefaultStyle;
                    // 如果当前没有选中风格，且有默认风格，则应用默认风格
                    if (!currentStyleName && result.styles.find(s => s.name === configDefaultStyle)) {
                        select.value = configDefaultStyle;
                        currentStyleName = configDefaultStyle;
                        updateStylePreview(result.styles.find(s => s.name === configDefaultStyle));
                        // 同步到后端
                        selectStyle(configDefaultStyle);
                    }
                }
            }
        }
    } catch (error) {
        console.error('加载风格列表失败', error);
    }
}

function updateStylePreview(style) {
    const preview = document.getElementById('stylePreview');
    const img = document.getElementById('stylePreviewImg');
    const deleteBtn = document.getElementById('deleteStyleBtn');

    if (style && style.path) {
        img.src = style.path;
        preview.style.display = 'block';
        deleteBtn.style.display = 'block';
    } else {
        preview.style.display = 'none';
        deleteBtn.style.display = 'none';
    }
}

async function selectStyle(name) {
    try {
        const response = await fetch('/api/styles/current', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name || null })
        });
        const result = await response.json();

        if (result.success) {
            currentStyleName = result.current_style;

            // 更新预览
            if (name) {
                const stylesRes = await fetch('/api/styles');
                const stylesData = await stylesRes.json();
                const style = stylesData.styles.find(s => s.name === name);
                updateStylePreview(style);
            } else {
                updateStylePreview(null);
            }

            showToast(name ? `已选择风格: ${name}` : '已清除风格', 'success');
        }
    } catch (error) {
        showToast('选择风格失败: ' + error.message, 'error');
    }
}

async function uploadStyleFile(input) {
    if (!input.files || !input.files[0]) return;

    const file = input.files[0];
    const name = prompt('请输入风格名称（便于识别）:', file.name.replace(/\.[^.]+$/, ''));

    if (!name) {
        input.value = '';
        return;
    }

    const formData = new FormData();
    formData.append('file', file);
    formData.append('name', name);

    try {
        const response = await fetch('/api/styles', {
            method: 'POST',
            body: formData
        });
        const result = await response.json();

        if (result.success) {
            showToast(result.message, 'success');
            loadStyles();  // 刷新列表
        } else {
            showToast('上传失败: ' + result.error, 'error');
        }
    } catch (error) {
        showToast('上传失败: ' + error.message, 'error');
    }

    input.value = '';  // 清空以允许重复上传同一文件
}

async function deleteCurrentStyle() {
    const name = document.getElementById('styleSelect').value;
    if (!name) return;

    if (!confirm(`确定删除风格 "${name}" 吗？`)) return;

    try {
        const response = await fetch(`/api/styles/${encodeURIComponent(name)}`, {
            method: 'DELETE'
        });
        const result = await response.json();

        if (result.success) {
            showToast(result.message, 'success');
            loadStyles();
        } else {
            showToast('删除失败: ' + result.error, 'error');
        }
    } catch (error) {
        showToast('删除失败: ' + error.message, 'error');
    }
}

// ===== 原始提示词存储 (用于恢复原版) =====
const originalImagePrompts = {}; // {pageIndex: originalPrompt}
const originalVideoPrompts = {}; // {pageIndex: originalPrompt}

// ===== 加载故事数据 =====
async function loadStory() {
    try {
        const response = await fetch('/api/story');
        const result = await response.json();

        if (result.success) {
            storyData = result.data;

            // [NEW] 保存原始提示词
            if (storyData && storyData.script) {
                storyData.script.forEach(page => {
                    originalImagePrompts[page.page_index] = page.image_prompt || '';
                    originalVideoPrompts[page.page_index] = page.video_prompt || '';
                });
            }

            updateHeader();
            renderPages();
            refreshStatus();
            populateSheetPrompts(); // [NEW] 填充设计稿提示词
        } else {
            showToast('加载故事失败: ' + result.error, 'error');
        }
    } catch (error) {
        showToast('网络错误: ' + error.message, 'error');
    }
}

// ===== 填充设计稿提示词 =====
function populateSheetPrompts() {
    if (!storyData) return;

    const charInput = document.getElementById('characterPromptInput');
    const sceneInput = document.getElementById('scenePromptInput');
    const itemInput = document.getElementById('itemPromptInput');

    if (charInput && storyData.character_sheet_prompt) {
        charInput.value = storyData.character_sheet_prompt;
    }
    if (sceneInput && storyData.scene_sheet_prompt) {
        sceneInput.value = storyData.scene_sheet_prompt;
    }
    if (itemInput && storyData.item_sheet_prompt) {
        itemInput.value = storyData.item_sheet_prompt;
    }
}

// ===== 更新设计稿提示词 =====
async function updateSheetPrompt(promptType, value) {
    try {
        const response = await fetch('/api/story/update-prompt', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt_type: promptType,
                value: value
            })
        });
        const result = await response.json();

        if (result.success) {
            // 更新本地数据
            storyData[promptType] = value;
            showToast('提示词已保存', 'success');
        } else {
            showToast('保存失败: ' + result.error, 'error');
        }
    } catch (error) {
        showToast('保存失败: ' + error.message, 'error');
    }
}

// ===== 加载配置 =====
async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        const result = await response.json();

        if (result.success) {
            currentConfig = result.config;

            // [NEW] 检查并提示配置错误
            if (result.config_error) {
                showToast(`⚠️ 配置加载失败: ${result.config_error}`, 'error', 10000);
            } else {
                console.log('配置加载成功');
            }

            // 更新 UI
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

    // 图片 API V1
    document.getElementById('imageApiUrl').value = currentConfig.image_api?.base_url || '';
    document.getElementById('imageApiKey').value = currentConfig.image_api?.api_key || '';
    document.getElementById('imageModel').value = currentConfig.image_api?.model || '';

    // 图片 API V2
    if (currentConfig.image_api_v2) {
        document.getElementById('imageApiUrlV2').value = currentConfig.image_api_v2.base_url || '';
        document.getElementById('imageApiKeyV2').value = currentConfig.image_api_v2.api_key || '';
        document.getElementById('imageModelV2').value = currentConfig.image_api_v2.model || '';
        document.getElementById('imageSizeV2').value = currentConfig.image_api_v2.image_size || '';
    }

    // 视频 API
    document.getElementById('videoApiUrl').value = currentConfig.video_api.base_url;
    document.getElementById('videoApiKey').value = currentConfig.video_api.api_key;
    document.getElementById('videoModel').value = currentConfig.video_api.model;

    // 音频 API
    if (currentConfig.audio_api) {
        document.getElementById('audioApiUrl').value = currentConfig.audio_api.base_url || '';
        document.getElementById('referenceAudioCn').value = currentConfig.audio_api.reference_audio_cn || '';
        document.getElementById('referenceAudioEn').value = currentConfig.audio_api.reference_audio_en || '';
    }

    // 优化 API
    if (currentConfig.optimize_api) {
        document.getElementById('optimizeApiUrl').value = currentConfig.optimize_api.base_url || '';
        document.getElementById('optimizeApiKey').value = currentConfig.optimize_api.api_key || '';
        document.getElementById('optimizeModel').value = currentConfig.optimize_api.model || '';
        document.getElementById('imagePromptTemplate').value = currentConfig.optimize_api.image_prompt_template || '';
        document.getElementById('videoPromptTemplate').value = currentConfig.optimize_api.video_prompt_template || '';
    }

    // 图片生成器模式
    document.getElementById('imageGeneratorMode').value = currentConfig.generation?.image_generator_mode || 'v1';

    // 默认值处理
    document.getElementById('batchSize').value = currentConfig.generation.batch_size || 1;

    // 读取嵌套的并发设置
    const concurrency = (currentConfig.generation && currentConfig.generation.concurrency) || {};
    document.getElementById('concurrencyImage').value = concurrency.image || 2;
    document.getElementById('concurrencyVideo').value = concurrency.video || 1;

    // 图片重试次数
    document.getElementById('imageMaxRetries').value = currentConfig.generation.image_max_retries ?? 3;

    // 视频重试次数
    document.getElementById('videoMaxRetries').value = currentConfig.generation.video_max_retries ?? 10;

    // 视频后处理配置
    const postProcessing = currentConfig.video_post_processing || {};
    document.getElementById('sceneThreshold').value = postProcessing.scene_threshold ?? 27.0;
    document.getElementById('videoVolume').value = postProcessing.video_volume ?? 0.05;
    document.getElementById('audioVolume').value = postProcessing.audio_volume ?? 4.0;
    document.getElementById('skipFirstScene').checked = postProcessing.skip_first_scene !== false;

    console.log(`[Config] Loaded concurrency: Image=${concurrency.image}, Video=${concurrency.video}`);
    console.log(`[Config] Loaded post processing: threshold=${postProcessing.scene_threshold}, video_vol=${postProcessing.video_volume}, audio_vol=${postProcessing.audio_volume}`);
}

// ===== 切换设置面板 =====
function toggleSettings() {
    loadConfig();
    const panel = document.getElementById('settingsPanel');
    panel.classList.toggle('expanded');

}

// ===== 防抖函数用于自动保存 =====
let saveSettingsTimeout = null;
function debouncedSaveSettings() {
    if (saveSettingsTimeout) {
        clearTimeout(saveSettingsTimeout);
    }
    saveSettingsTimeout = setTimeout(() => {
        saveSettings(true); // 静默保存模式
    }, 500); // 500ms 防抖
}

// ===== 保存设置 =====
async function saveSettings(silent = false) {
    const newConfig = {
        image_api: {
            base_url: document.getElementById('imageApiUrl').value.trim(),
            api_key: document.getElementById('imageApiKey').value.trim(),
            model: document.getElementById('imageModel').value.trim()
        },
        image_api_v2: {
            base_url: document.getElementById('imageApiUrlV2').value.trim(),
            api_key: document.getElementById('imageApiKeyV2').value.trim(),
            model: document.getElementById('imageModelV2').value.trim(),
            image_size: document.getElementById('imageSizeV2').value.trim()
        },
        video_api: {
            base_url: document.getElementById('videoApiUrl').value.trim(),
            api_key: document.getElementById('videoApiKey').value.trim(),
            model: document.getElementById('videoModel').value.trim()
        },
        audio_api: {
            base_url: document.getElementById('audioApiUrl').value.trim(),
            reference_audio_cn: document.getElementById('referenceAudioCn').value.trim(),
            reference_audio_en: document.getElementById('referenceAudioEn').value.trim()
        },
        optimize_api: {
            base_url: document.getElementById('optimizeApiUrl').value.trim(),
            api_key: document.getElementById('optimizeApiKey').value.trim(),
            model: document.getElementById('optimizeModel').value.trim(),
            image_prompt_template: document.getElementById('imagePromptTemplate').value.trim(),
            video_prompt_template: document.getElementById('videoPromptTemplate').value.trim()
        },
        generation: {
            batch_size: parseInt(document.getElementById('batchSize').value) || 1,
            image_max_retries: parseInt(document.getElementById('imageMaxRetries').value) ?? 3,
            video_max_retries: parseInt(document.getElementById('videoMaxRetries').value) ?? 10,
            default_style: document.getElementById('defaultStyle').value || '',
            image_generator_mode: document.getElementById('imageGeneratorMode').value || 'v1',
            concurrency: {
                image: parseInt(document.getElementById('concurrencyImage').value) || 2,
                video: parseInt(document.getElementById('concurrencyVideo').value) || 1
            }
        },
        video_post_processing: {
            scene_threshold: parseFloat(document.getElementById('sceneThreshold').value) || 27.0,
            video_volume: parseFloat(document.getElementById('videoVolume').value) || 0.05,
            audio_volume: parseFloat(document.getElementById('audioVolume').value) || 4.0,
            skip_first_scene: document.getElementById('skipFirstScene').checked
        }
    };

    try {
        if (!silent) {
            updateProgress('正在保存设置...');
        }

        const response = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(newConfig)
        });

        const result = await response.json();

        if (result.success) {
            currentConfig = result.config;
            if (!silent) {
                showToast('设置已保存', 'success');
                // 手动保存时收起面板
                document.getElementById('settingsPanel').classList.remove('expanded');
                updateProgress('设置保存成功');
            } else {
                // 静默保存时只显示简短提示
                console.log('[Settings] Auto-saved');
            }
        } else {
            showToast('保存失败: ' + result.error, 'error');
        }
    } catch (error) {
        if (!silent) {
            showToast('网络错误: ' + error.message, 'error');
        } else {
            console.error('[Settings] Auto-save failed:', error);
        }
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

        // [NEW] 当并发 >= 2 时，添加 3 秒错开延迟
        const delayMs = concurrency >= 2 ? count * 3000 : 0;

        queue.add(async () => {
            if (delayMs > 0) {
                await new Promise(r => setTimeout(r, delayMs));
            }
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

// ===== 批量生成图片 (跳过已完成) =====
async function generateAllImages(isChained = false) {
    if (!storyData || !storyData.script) {
        showToast('请先加载故事数据', 'error');
        return;
    }

    // 先获取最新状态
    let statusMap = {};
    try {
        const response = await fetch('/api/status');
        const result = await response.json();
        if (result.success) {
            statusMap = result.status.pages || {};
        }
    } catch (e) {
        console.error('获取状态失败', e);
    }

    // 计算需要生成的任务数
    let pending = 0, skipped = 0;
    storyData.script.forEach(page => {
        const pageStatus = statusMap[page.page_index];
        if (pageStatus?.image === 'completed') {
            skipped++;
        } else {
            pending++;
        }
    });

    if (pending === 0 && !isChained) {
        showToast('所有分镜图片已生成完毕，无需重复生成', 'info');
        return;
    }

    const concurrency = currentConfig?.generation?.concurrency?.image || 2;
    const queue = new TaskQueue(concurrency);

    if (!isChained) {
        updateProgress(`开始批量生成图片 (待生成: ${pending}, 已跳过: ${skipped}, 并发: ${concurrency})...`);
    }

    // 1. 确保设计稿 (串行)
    if (!loadedSheets.character) await generateCharacterSheet();
    if (!loadedSheets.scene) await generateSceneSheet();

    // 2. 提交分镜任务 (跳过已完成)
    for (const page of storyData.script) {
        const pageStatus = statusMap[page.page_index];
        if (pageStatus?.image === 'completed') {
            continue; // 跳过已完成
        }

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

            // 刷新页面以确保状态完全更新
            location.reload();
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
                // 刷新页面以确保状态完全更新
                location.reload();
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


// ===== 视频提示词历史 (用于撤销) =====
const videoPromptHistory = {}; // {pageIndex: oldPrompt}

// ===== 优化视频提示词 =====
async function optimizeVideoPrompt(pageIndex) {
    const page = storyData.script.find(p => p.page_index === pageIndex);
    if (!page) return;

    const oldPrompt = page.video_prompt || '';
    const engNarration = page.eng_narration || '';
    const imagePrompt = page.image_prompt || '';  // [NEW] 参考图片提示词

    if (!oldPrompt) {
        showToast('请先填写视频提示词', 'error');
        return;
    }

    const optBtn = document.getElementById(`opt-btn-${pageIndex}`);
    const undoBtn = document.getElementById(`undo-btn-${pageIndex}`);
    const textarea = document.getElementById(`video-prompt-${pageIndex}`);

    if (optBtn) {
        optBtn.disabled = true;
        optBtn.textContent = '⏳ 优化中...';
    }

    try {
        const response = await fetch('/api/optimize/video-prompt', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                page_index: pageIndex,
                video_prompt: oldPrompt,
                image_prompt: imagePrompt,  // [NEW]
                eng_narration: engNarration
            })
        });

        const result = await response.json();

        if (result.success) {
            // 保存旧版本用于撤销
            videoPromptHistory[pageIndex] = oldPrompt;

            // 更新 UI
            if (textarea) {
                textarea.value = result.new_prompt;
            }

            // 更新本地数据
            page.video_prompt = result.new_prompt;

            // 保存到后端
            await updatePrompt(pageIndex, 'video_prompt', result.new_prompt);

            // 显示撤销按钮
            if (undoBtn) {
                undoBtn.style.display = 'inline-block';
            }

            showToast('✨ 视频提示词优化成功', 'success');
        } else {
            showToast('优化失败: ' + result.error, 'error');
        }
    } catch (error) {
        showToast('网络错误: ' + error.message, 'error');
    } finally {
        if (optBtn) {
            optBtn.disabled = false;
            optBtn.textContent = '✨ 优化';
        }
    }
}

// ===== 撤销视频提示词优化 =====
async function undoVideoPrompt(pageIndex) {
    const oldPrompt = videoPromptHistory[pageIndex];
    if (!oldPrompt) {
        showToast('没有可撤销的历史', 'error');
        return;
    }

    const page = storyData.script.find(p => p.page_index === pageIndex);
    if (!page) return;

    const textarea = document.getElementById(`video-prompt-${pageIndex}`);
    const undoBtn = document.getElementById(`undo-btn-${pageIndex}`);

    // 更新 UI
    if (textarea) {
        textarea.value = oldPrompt;
    }

    // 更新本地数据
    page.video_prompt = oldPrompt;

    // 保存到后端
    await updatePrompt(pageIndex, 'video_prompt', oldPrompt);

    // 隐藏撤销按钮
    if (undoBtn) {
        undoBtn.style.display = 'none';
    }

    // 清除历史
    delete videoPromptHistory[pageIndex];

    showToast('↩️ 已恢复上一版本', 'success');
}

// ===== 恢复原始视频提示词 =====
async function restoreOriginalVideoPrompt(pageIndex) {
    const originalPrompt = originalVideoPrompts[pageIndex];
    if (!originalPrompt) {
        showToast('没有原始版本', 'error');
        return;
    }

    const page = storyData.script.find(p => p.page_index === pageIndex);
    if (!page) return;

    const textarea = document.getElementById(`video-prompt-${pageIndex}`);
    const undoBtn = document.getElementById(`undo-btn-${pageIndex}`);

    // 更新 UI
    if (textarea) {
        textarea.value = originalPrompt;
    }

    // 更新本地数据
    page.video_prompt = originalPrompt;

    // 保存到后端
    await updatePrompt(pageIndex, 'video_prompt', originalPrompt);

    // 隐藏撤销按钮并清除历史
    if (undoBtn) {
        undoBtn.style.display = 'none';
    }
    delete videoPromptHistory[pageIndex];
    optimizedPrompts.delete(pageIndex);

    showToast('🔄 已恢复原始版本', 'success');
}

// ===== 已优化标记集合 =====
const optimizedPrompts = new Set(); // 存储已优化的页面索引

// ===== 批量优化所有未优化的视频提示词 =====
async function optimizeAllVideoPrompts() {
    if (!storyData || !storyData.script) {
        showToast('请先加载故事数据', 'error');
        return;
    }

    // 找出未优化的页面
    const pending = storyData.script.filter(page =>
        page.video_prompt && !optimizedPrompts.has(page.page_index)
    );

    if (pending.length === 0) {
        showToast('所有视频提示词都已优化过', 'info');
        return;
    }

    if (!confirm(`将优化 ${pending.length} 个未优化的视频提示词。是否继续？`)) {
        return;
    }

    updateProgress(`开始批量优化 ${pending.length} 个视频提示词...`);

    let success = 0, failed = 0;

    for (const page of pending) {
        const pageIndex = page.page_index;
        updateProgress(`正在优化第 ${pageIndex} 页... (${success + failed + 1}/${pending.length})`);

        try {
            const response = await fetch('/api/optimize/video-prompt', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    page_index: pageIndex,
                    video_prompt: page.video_prompt,
                    image_prompt: page.image_prompt || '',  // [NEW]
                    eng_narration: page.eng_narration || ''
                })
            });

            const result = await response.json();

            if (result.success) {
                // 保存旧版本
                videoPromptHistory[pageIndex] = page.video_prompt;

                // 更新数据
                page.video_prompt = result.new_prompt;

                // 更新 UI
                const textarea = document.getElementById(`video-prompt-${pageIndex}`);
                const undoBtn = document.getElementById(`undo-btn-${pageIndex}`);
                if (textarea) textarea.value = result.new_prompt;
                if (undoBtn) undoBtn.style.display = 'inline-block';

                // 保存到后端
                await updatePrompt(pageIndex, 'video_prompt', result.new_prompt);

                // 标记为已优化
                optimizedPrompts.add(pageIndex);

                success++;
            } else {
                console.error(`优化第 ${pageIndex} 页失败:`, result.error);
                failed++;
            }
        } catch (error) {
            console.error(`优化第 ${pageIndex} 页出错:`, error);
            failed++;
        }
    }

    updateProgress(`✅ 批量优化完成: ${success} 成功, ${failed} 失败`);
    showToast(`✨ 批量优化完成: ${success} 成功, ${failed} 失败`, success > 0 ? 'success' : 'error');
}


// ===== 图片提示词历史 (用于撤销) =====
const imagePromptHistory = {}; // {pageIndex: oldPrompt}
const optimizedImagePrompts = new Set(); // 存储已优化的页面索引

// ===== 优化图片提示词 =====
async function optimizeImagePrompt(pageIndex) {
    const page = storyData.script.find(p => p.page_index === pageIndex);
    if (!page) return;

    const oldPrompt = page.image_prompt || '';
    const engNarration = page.eng_narration || '';
    const videoPrompt = page.video_prompt || '';  // [NEW] 参考视频提示词

    if (!oldPrompt) {
        showToast('请先填写图片提示词', 'error');
        return;
    }

    const optBtn = document.getElementById(`img-opt-btn-${pageIndex}`);
    const undoBtn = document.getElementById(`img-undo-btn-${pageIndex}`);
    const textarea = document.getElementById(`image-prompt-${pageIndex}`);

    if (optBtn) {
        optBtn.disabled = true;
        optBtn.textContent = '⏳ 优化中...';
    }

    try {
        const response = await fetch('/api/optimize/image-prompt', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                page_index: pageIndex,
                image_prompt: oldPrompt,
                video_prompt: videoPrompt,  // [NEW]
                eng_narration: engNarration
            })
        });

        const result = await response.json();

        if (result.success) {
            // 保存旧版本用于撤销
            imagePromptHistory[pageIndex] = oldPrompt;

            // 更新 UI
            if (textarea) {
                textarea.value = result.new_prompt;
            }

            // 更新本地数据
            page.image_prompt = result.new_prompt;

            // 保存到后端
            await updatePrompt(pageIndex, 'image_prompt', result.new_prompt);

            // 标记为已优化
            optimizedImagePrompts.add(pageIndex);

            // 显示撤销按钮
            if (undoBtn) {
                undoBtn.style.display = 'inline-block';
            }

            showToast('✨ 图片提示词优化成功', 'success');
        } else {
            showToast('优化失败: ' + result.error, 'error');
        }
    } catch (error) {
        showToast('网络错误: ' + error.message, 'error');
    } finally {
        if (optBtn) {
            optBtn.disabled = false;
            optBtn.textContent = '✨ 优化';
        }
    }
}

// ===== 撤销图片提示词优化 =====
async function undoImagePrompt(pageIndex) {
    const oldPrompt = imagePromptHistory[pageIndex];
    if (!oldPrompt) {
        showToast('没有可撤销的历史', 'error');
        return;
    }

    const page = storyData.script.find(p => p.page_index === pageIndex);
    if (!page) return;

    const textarea = document.getElementById(`image-prompt-${pageIndex}`);
    const undoBtn = document.getElementById(`img-undo-btn-${pageIndex}`);

    // 更新 UI
    if (textarea) {
        textarea.value = oldPrompt;
    }

    // 更新本地数据
    page.image_prompt = oldPrompt;

    // 保存到后端
    await updatePrompt(pageIndex, 'image_prompt', oldPrompt);

    // 隐藏撤销按钮
    if (undoBtn) {
        undoBtn.style.display = 'none';
    }

    // 清除历史和已优化标记
    delete imagePromptHistory[pageIndex];
    optimizedImagePrompts.delete(pageIndex);

    showToast('↩️ 已恢复上一版本', 'success');
}

// ===== 恢复原始图片提示词 =====
async function restoreOriginalImagePrompt(pageIndex) {
    const originalPrompt = originalImagePrompts[pageIndex];
    if (!originalPrompt) {
        showToast('没有原始版本', 'error');
        return;
    }

    const page = storyData.script.find(p => p.page_index === pageIndex);
    if (!page) return;

    const textarea = document.getElementById(`image-prompt-${pageIndex}`);
    const undoBtn = document.getElementById(`img-undo-btn-${pageIndex}`);

    // 更新 UI
    if (textarea) {
        textarea.value = originalPrompt;
    }

    // 更新本地数据
    page.image_prompt = originalPrompt;

    // 保存到后端
    await updatePrompt(pageIndex, 'image_prompt', originalPrompt);

    // 隐藏撤销按钮并清除历史
    if (undoBtn) {
        undoBtn.style.display = 'none';
    }
    delete imagePromptHistory[pageIndex];
    optimizedImagePrompts.delete(pageIndex);

    showToast('🔄 已恢复原始版本', 'success');
}

// ===== 批量优化所有未优化的图片提示词 =====
async function optimizeAllImagePrompts() {
    if (!storyData || !storyData.script) {
        showToast('请先加载故事数据', 'error');
        return;
    }

    // 找出未优化的页面
    const pending = storyData.script.filter(page =>
        page.image_prompt && !optimizedImagePrompts.has(page.page_index)
    );

    if (pending.length === 0) {
        showToast('所有图片提示词都已优化过', 'info');
        return;
    }

    if (!confirm(`将优化 ${pending.length} 个未优化的图片提示词。是否继续？`)) {
        return;
    }

    updateProgress(`开始批量优化 ${pending.length} 个图片提示词...`);

    let success = 0, failed = 0;

    for (const page of pending) {
        const pageIndex = page.page_index;
        updateProgress(`正在优化图片提示词 第 ${pageIndex} 页... (${success + failed + 1}/${pending.length})`);

        try {
            const response = await fetch('/api/optimize/image-prompt', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    page_index: pageIndex,
                    image_prompt: page.image_prompt,
                    video_prompt: page.video_prompt || '',  // [NEW]
                    eng_narration: page.eng_narration || ''
                })
            });

            const result = await response.json();

            if (result.success) {
                // 保存旧版本
                imagePromptHistory[pageIndex] = page.image_prompt;

                // 更新数据
                page.image_prompt = result.new_prompt;

                // 更新 UI
                const textarea = document.getElementById(`image-prompt-${pageIndex}`);
                const undoBtn = document.getElementById(`img-undo-btn-${pageIndex}`);
                if (textarea) textarea.value = result.new_prompt;
                if (undoBtn) undoBtn.style.display = 'inline-block';

                // 保存到后端
                await updatePrompt(pageIndex, 'image_prompt', result.new_prompt);

                // 标记为已优化
                optimizedImagePrompts.add(pageIndex);

                success++;
            } else {
                console.error(`优化第 ${pageIndex} 页图片提示词失败:`, result.error);
                failed++;
            }
        } catch (error) {
            console.error(`优化第 ${pageIndex} 页图片提示词出错:`, error);
            failed++;
        }
    }

    updateProgress(`✅ 图片提示词批量优化完成: ${success} 成功, ${failed} 失败`);
    showToast(`✨ 图片提示词批量优化完成: ${success} 成功, ${failed} 失败`, success > 0 ? 'success' : 'error');
}


// ===== 一键生成所有图片 =====
// function generateAllSequential removed (replaced by generateAllImages)

// ===== 更新头部信息 =====
function updateHeader() {
    document.getElementById('storyTitle').textContent = storyData.title || '儿童故事';
    // storySubtitle removed
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
        
        <!-- 2. 图片提示词 (可编辑 + 优化按钮) -->
        <div class="prompt-section image-prompt-section">
            <div class="prompt-header" style="display: flex; justify-content: space-between; align-items: center;">
                <span class="prompt-label">📷 图片提示词</span>
                <div style="display: flex; gap: 5px;">
                    <button class="btn btn-secondary btn-xs" onclick="optimizeImagePrompt(${page.page_index})" id="img-opt-btn-${page.page_index}">
                        ✨ 优化
                    </button>
                    <button class="btn btn-secondary btn-xs" onclick="undoImagePrompt(${page.page_index})" id="img-undo-btn-${page.page_index}" style="display: none;">
                        ↩️ 撤销
                    </button>
                    <button class="btn btn-secondary btn-xs" onclick="restoreOriginalImagePrompt(${page.page_index})" title="恢复原始版本">
                        🔄 原版
                    </button>
                </div>
            </div>
            <textarea class="prompt-input" id="image-prompt-${page.page_index}"
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
        
        <!-- 4. 视频提示词 (可编辑 + 优化按钮) -->
        <div class="prompt-section video-prompt-section">
            <div class="prompt-header" style="display: flex; justify-content: space-between; align-items: center;">
                <span class="prompt-label">🎬 视频提示词</span>
                <div style="display: flex; gap: 5px;">
                    <button class="btn btn-secondary btn-xs" onclick="optimizeVideoPrompt(${page.page_index})" id="opt-btn-${page.page_index}">
                        ✨ 优化
                    </button>
                    <button class="btn btn-secondary btn-xs" onclick="undoVideoPrompt(${page.page_index})" id="undo-btn-${page.page_index}" style="display: none;">
                        ↩️ 撤销
                    </button>
                    <button class="btn btn-secondary btn-xs" onclick="restoreOriginalVideoPrompt(${page.page_index})" title="恢复原始版本">
                        🔄 原版
                    </button>
                </div>
            </div>
             <textarea class="prompt-input" id="video-prompt-${page.page_index}"
                      onchange="updatePrompt(${page.page_index}, 'video_prompt', this.value)"
                      placeholder="在此输入视频提示词...">${(page.video_prompt || '').replace(/</g, '&lt;')}</textarea>
        </div>
        
        <!-- 5. 中文旁白 (可编辑) -->
        <div class="prompt-section narration-section">
            <div class="prompt-header">
                <span class="prompt-label">🇨🇳 中文旁白</span>
            </div>
            <textarea class="prompt-input" 
                      onchange="updatePrompt(${page.page_index}, 'narration', this.value)"
                      placeholder="在此输入中文旁白...">${(page.narration || '').replace(/</g, '&lt;')}</textarea>
        </div>

        <!-- 6. 英文旁白 (可编辑) -->
        <div class="prompt-section narration-section">
             <div class="prompt-header">
                <span class="prompt-label">🇺🇸 英文旁白</span>
            </div>
            <textarea class="prompt-input" 
                      onchange="updatePrompt(${page.page_index}, 'eng_narration', this.value)"
                      placeholder="在此输入英文旁白...">${(page.eng_narration || '').replace(/</g, '&lt;')}</textarea>
        </div>

        <!-- 7. 配音区域 (双语) -->
        <div class="audio-section-group">
            <!-- 中文配音 -->
            <div class="audio-section">
                 <div class="section-header-small">
                    <span>🔊 中文配音</span>
                    <button class="btn btn-secondary btn-xs" onclick="generatePageAudio(${page.page_index}, 'cn')" id="audio-btn-cn-${page.page_index}">
                        生成
                    </button>
                </div>
                <div class="audio-preview" id="audio-preview-cn-${page.page_index}">
                    <div class="audio-placeholder">
                        <span style="color: #888; font-size: 12px;">暂无</span>
                    </div>
                </div>
            </div>
            
            <!-- 英文配音 -->
            <div class="audio-section">
                 <div class="section-header-small">
                    <span>🔊 英文配音</span>
                    <button class="btn btn-secondary btn-xs" onclick="generatePageAudio(${page.page_index}, 'en')" id="audio-btn-en-${page.page_index}">
                        生成
                    </button>
                </div>
                <div class="audio-preview" id="audio-preview-en-${page.page_index}">
                    <div class="audio-placeholder">
                        <span style="color: #888; font-size: 12px;">暂无</span>
                    </div>
                </div>
            </div>
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

    // 更新物品设计稿状态
    updateSheetStatus('item', status.item_sheet, paths.item_sheet);

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

    // 更新音频状态 (双语)
    // 助手函数: 更新单个音频播放器状态
    const updateAudioUI = (lang) => {
        const btn = document.getElementById(`audio-btn-${lang}-${pageIndex}`);
        const preview = document.getElementById(`audio-preview-${lang}-${pageIndex}`);

        if (!btn || !preview) return;

        // 兼容旧数据: 如果 audio 是 null 或字符串(旧格式)，这就当作 dict处理时会出错，需防御
        let status = null;
        if (pageStatus.audio && typeof pageStatus.audio === 'object') {
            status = pageStatus.audio[lang];
        } else if (lang === 'cn' && typeof pageStatus.audio === 'string') {
            // 旧数据兼容
            status = pageStatus.audio;
        }

        if (status === 'generating') {
            btn.disabled = true;
            btn.textContent = '⏳ ...';
            preview.innerHTML = `
                <div class="audio-placeholder">
                    <div class="spinner-small"></div>
                    <span>生成中...</span>
                </div>
            `;
        } else if (status === 'completed') {
            btn.disabled = false;
            btn.textContent = '生成';

            const projectPath = currentProjectName ? `${currentProjectName}/` : '';
            const suffix = lang === 'en' ? 'en' : 'cn';
            // 注意: 后端已经统一为 _cn.wav 和 _en.wav，但为了兼容旧数据，如果是 cn 且 _cn.wav 不存在可能需要fallback? 
            // 前端只管请求路径。后端 init 逻辑保证了 status=completed 时文件肯定存在 (init会检查 _cn 或 无后缀)
            // 这里我们请求 _cn.wav 即可，因为后端 generate_page_audio 保证生成带后缀的。
            // 对于旧文件 (无后缀)，init logic 虽认为 completed，但前端请求可能 404？
            // 简单处理: 优先请求带后缀，onerror fallback? 不，太复杂。
            // 假设后端 migrate 或 generate 新文件覆盖。
            // 实际上 app.py 里 generate_page_audio 生成的是 _cn.wav。
            // 对于旧文件 page_001.wav, init 逻辑把它算作 cn completed。但前端如果请求 _cn.wav 会挂。
            // 让前端请求带后缀的，如果旧项目只有无后缀文件，用户需要点击重新生成来“升级”到带后缀文件。

            const audioPath = `/output/${projectPath}audio/page_${String(pageIndex).padStart(3, '0')}_${suffix}.wav`;
            // 如果是 CN 且 status completed，但文件可能是旧版(无后缀)？
            // 这是一个小坑。我们在 app.py init 里做了兼容检查。
            // 为了显示正确，这里路径最好能动态... 但前端不知道具体文件名。
            // 策略：统一只请求 _cn/_en。如果旧文件存在但新文件不存在，用户点播放404，被迫重新生成。这是可接受的。

            const cacheKey = `audio-${lang}-${pageIndex}`;
            if (!preview.querySelector('audio') || loadedImages.get(cacheKey) !== audioPath) {
                loadedImages.set(cacheKey, audioPath);
                preview.innerHTML = `
                    <audio controls controlsList="nodownload" src="${audioPath}?t=${Date.now()}" style="width: 100%; height: 30px;"></audio>
                `;
            }
        } else if (status === 'failed') {
            btn.disabled = false;
            btn.textContent = '重试';
            preview.innerHTML = `
                <div class="audio-placeholder">
                    <span style="color: red; font-size: 12px;">失败</span>
                </div>
            `;
        } else {
            // None / Init
            btn.disabled = false;
            btn.textContent = '生成';
            if (!preview.querySelector('audio')) {
                preview.innerHTML = `
                    <div class="audio-placeholder">
                        <span style="color: #888; font-size: 12px;">暂无</span>
                    </div>
                `;
            }
        }
    };

    updateAudioUI('cn');
    updateAudioUI('en');

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

// 注入动态样式
const style = document.createElement('style');
style.textContent = `
    .audio-section-group {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 10px;
        padding: 5px 15px 15px;
    }
    .audio-section-group .audio-section {
        background: rgba(0,0,0,0.1);
        border-radius: 8px;
        padding: 8px;
        margin-bottom: 0;
    }
`;
document.head.appendChild(style);

// ===== 生成单页音频 =====
async function generatePageAudio(pageIndex, lang = 'cn') {
    const btn = document.getElementById(`audio-btn-${lang}-${pageIndex}`);
    if (btn) {
        btn.disabled = true;
        btn.textContent = '⏳ ...';
    }

    try {
        const response = await fetch(`/api/generate/page-audio/${pageIndex}?lang=${lang}`, { method: 'POST' });
        const result = await response.json();

        if (result.success) {
            showToast(`${lang === 'cn' ? '中文' : '英文'}音频生成成功`, 'success');
            refreshStatus();
        } else {
            showToast(`生成失败: ${result.error}`, 'error');
            if (btn) {
                btn.disabled = false;
                btn.textContent = '生成';
            }
        }
    } catch (error) {
        showToast('请求失败: ' + error.message, 'error');
        if (btn) {
            btn.disabled = false;
            btn.textContent = '生成';
        }
    }
}

// ===== 批量生成音频 (双语, 跳过已完成) =====
async function generateAllAudio() {
    if (!storyData || !storyData.script) return;

    // 先获取最新状态
    let statusMap = {};
    try {
        const response = await fetch('/api/status');
        const result = await response.json();
        if (result.success) {
            statusMap = result.status.pages || {};
        }
    } catch (e) {
        console.error('获取状态失败', e);
    }

    // 计算需要生成的任务数
    let pendingCn = 0, pendingEn = 0, skippedCn = 0, skippedEn = 0;

    storyData.script.forEach(page => {
        const pageStatus = statusMap[page.page_index];
        const audioStatus = pageStatus?.audio || {};

        if (audioStatus.cn === 'completed') {
            skippedCn++;
        } else {
            pendingCn++;
        }

        if (audioStatus.en === 'completed') {
            skippedEn++;
        } else {
            pendingEn++;
        }
    });

    const totalPending = pendingCn + pendingEn;
    const totalSkipped = skippedCn + skippedEn;

    if (totalPending === 0) {
        showToast('所有音频已生成完毕，无需重复生成', 'info');
        return;
    }

    if (!confirm(`批量生成双语音频：\n- 待生成: ${totalPending} 个 (中文 ${pendingCn}, 英文 ${pendingEn})\n- 已跳过: ${totalSkipped} 个\n\nAPI 不支持并发，将逐个生成。是否继续？`)) {
        return;
    }

    showToast(`开始批量生成音频 (跳过 ${totalSkipped} 个)...`, 'info');

    // 串行队列
    const queue = new TaskQueue(1);
    queue.active = true;

    storyData.script.forEach(page => {
        const pageStatus = statusMap[page.page_index];
        const audioStatus = pageStatus?.audio || {};

        // 中文: 仅当未完成时加入队列
        if (audioStatus.cn !== 'completed') {
            queue.add(async () => {
                await generatePageAudio(page.page_index, 'cn');
            });
        }

        // 英文: 仅当未完成时加入队列
        if (audioStatus.en !== 'completed') {
            queue.add(async () => {
                await generatePageAudio(page.page_index, 'en');
            });
        }
    });

    queue.start();
}

// ===== 生成项目 SRT =====
async function generateProjectSRT() {
    try {
        updateProgress('正在生成 SRT 字幕...');
        const response = await fetch('/api/generate/project-srt', { method: 'POST' });
        const result = await response.json();

        if (result.success) {
            showToast('SRT 字幕生成成功', 'success');
        } else {
            showToast('SRT 生成失败: ' + result.error, 'error');
        }
    } catch (error) {
        showToast('请求失败: ' + error.message, 'error');
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
function showToast(message, type = 'success', duration = 3000) {
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
    }, duration);
}

// ===== 生成角色设计稿 =====
async function generateCharacterSheet() {
    const btn = document.querySelector('#characterSheet button');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="btn-icon">⏳</span> 生成中...';
    }

    try {
        const response = await fetch('/api/generate/character-sheet', { method: 'POST' });
        const result = await response.json();

        if (result.success) {
            showToast(result.message, 'success');
            refreshStatus();
        } else {
            showToast('生成失败: ' + result.error, 'error');
        }
    } catch (error) {
        showToast('网络错误: ' + error.message, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<span class="btn-icon">✨</span> 生成角色设计稿';
        }
    }
}

// ===== 生成场景设计稿 =====
async function generateSceneSheet() {
    const btn = document.querySelector('#sceneSheet button');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="btn-icon">⏳</span> 生成中...';
    }

    try {
        const response = await fetch('/api/generate/scene-sheet', { method: 'POST' });
        const result = await response.json();

        if (result.success) {
            showToast(result.message, 'success');
            refreshStatus();
        } else {
            showToast('生成失败: ' + result.error, 'error');
        }
    } catch (error) {
        showToast('网络错误: ' + error.message, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<span class="btn-icon">✨</span> 生成场景设计稿';
        }
    }
}

// ===== 生成物品设计稿 =====
async function generateItemSheet() {
    const btn = document.querySelector('#itemSheet button');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="btn-icon">⏳</span> 生成中...';
    }

    try {
        const response = await fetch('/api/generate/item-sheet', { method: 'POST' });
        const result = await response.json();

        if (result.success) {
            showToast(result.message, 'success');
            refreshStatus();
        } else {
            showToast('生成失败: ' + result.error, 'error');
        }
    } catch (error) {
        showToast('网络错误: ' + error.message, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<span class="btn-icon">✨</span> 生成物品设计稿';
        }
    }
}

// ===== 一键生成设计稿 (角色 → 场景) =====
// ===== 一键生成设计稿 (角色 → 场景 → 物品) =====
async function generateAllSheets(skipConfirm = false) {
    if (!skipConfirm && !confirm('将按顺序生成: 角色设计稿 → 场景设计稿 → 物品设计稿。是否继续？')) {
        return;
    }

    showToast('🚀 正在生成角色设计稿...', 'info');

    try {
        // 1. 生成角色设计稿
        const charResponse = await fetch('/api/generate/character-sheet', { method: 'POST' });
        const charResult = await charResponse.json();

        if (!charResult.success) {
            showToast('❌ 角色设计稿生成失败: ' + charResult.error, 'error');
            return;
        }
        refreshStatus();
        showToast('✅ 角色设计稿完成，正在生成场景设计稿...', 'info');

        // 2. 生成场景设计稿
        const sceneResponse = await fetch('/api/generate/scene-sheet', { method: 'POST' });
        const sceneResult = await sceneResponse.json();

        if (!sceneResult.success) {
            showToast('❌ 场景设计稿生成失败: ' + sceneResult.error, 'error');
            return;
        }
        refreshStatus();
        showToast('✅ 场景设计稿完成，正在生成物品设计稿...', 'info');

        // 3. 生成物品设计稿
        const itemResponse = await fetch('/api/generate/item-sheet', { method: 'POST' });
        const itemResult = await itemResponse.json();

        if (itemResult.success) {
            showToast('🎉 所有设计稿生成完成！', 'success');
            refreshStatus();
        } else {
            showToast('❌ 物品设计稿生成失败: ' + itemResult.error, 'error');
        }

    } catch (error) {
        showToast('❌ 生成失败: ' + error.message, 'error');
    }
}

// ===== 一键生成设计稿 + 分镜图片 =====
async function generateAllSheetsAndImages() {
    if (!confirm('此操作将执行以下流程：\n1. 生成所有设计稿 (角色, 场景, 物品)\n2. 批量生成所有分镜图片\n\n这可能耗时较长，是否继续？')) {
        return;
    }

    // 1. 生成设计稿 (跳过内部确认)
    await generateAllSheets(true);

    // 2. 批量生成分镜图片 (chained 模式)
    // 注意: generateAllSheets 是异步的，上面已经 await 了
    // 检查设计稿是否都已存在（简单检查: loadedSheets 状态或重新检查 DOM）
    // 稍微延迟一下确保状态刷新
    setTimeout(() => {
        showToast('🚀 设计稿阶段结束，开始批量生成分镜...', 'info');
        generateAllImages(true);
    }, 1000);
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

// ===== 生成最终视频 =====
async function generateFinalVideo(lang = 'cn') {
    const btnId = lang === 'cn' ? 'generateFinalVideoCnBtn' : 'generateFinalVideoEnBtn';
    const btn = document.getElementById(btnId);
    const langText = lang === 'cn' ? '中文' : '英文';

    if (!currentProjectName) {
        showToast('请先加载一个项目', 'error');
        return;
    }

    // 确认操作
    if (!confirm(`确定要生成${langText}版最终视频吗？\n\n此操作可能需要较长时间，请耐心等待。`)) {
        return;
    }

    // 更新 UI 状态
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-icon">⏳</span> 生成中...';

    // 更新状态显示
    const statusId = lang === 'cn' ? 'finalVideoCnStatus' : 'finalVideoEnStatus';
    document.getElementById(statusId).textContent = '生成中...';

    updateProgress(`🎬 正在生成${langText}版最终视频，请稍候...`);

    try {
        const response = await fetch('/api/generate/final-video', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lang: lang })
        });

        const result = await response.json();

        if (result.success) {
            showToast(result.message, 'success');
            updateProgress(`✅ ${result.message}`);

            // 更新预览
            updateFinalVideoPreview(lang, result.video_path, result.file_size_mb);

        } else {
            showToast('生成失败: ' + result.error, 'error');
            updateProgress('❌ 生成失败: ' + result.error);
            document.getElementById(statusId).textContent = '生成失败';
        }
    } catch (error) {
        showToast('网络错误: ' + error.message, 'error');
        updateProgress('❌ 网络错误: ' + error.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

// ===== 更新最终视频预览 =====
function updateFinalVideoPreview(lang, videoPath, fileSizeMb) {
    const previewId = lang === 'cn' ? 'finalVideoCnPreview' : 'finalVideoEnPreview';
    const statusId = lang === 'cn' ? 'finalVideoCnStatus' : 'finalVideoEnStatus';
    const downloadId = lang === 'cn' ? 'finalVideoCnDownload' : 'finalVideoEnDownload';

    const previewContainer = document.getElementById(previewId);
    const statusSpan = document.getElementById(statusId);
    const downloadLink = document.getElementById(downloadId);

    // 更新状态
    statusSpan.textContent = `${fileSizeMb} MB`;
    statusSpan.style.color = 'var(--success-color)';

    // 创建视频预览
    previewContainer.innerHTML = `
        <video controls style="width: 100%; max-height: 300px;">
            <source src="${videoPath}?t=${Date.now()}" type="video/mp4">
            您的浏览器不支持视频播放
        </video>
    `;

    // 显示下载链接
    downloadLink.href = videoPath;
    downloadLink.textContent = `📥 下载 (${fileSizeMb} MB)`;
    downloadLink.style.display = 'block';
}

// ===== 加载已生成的最终视频 =====
async function loadFinalVideos() {
    if (!currentProjectName) {
        return;
    }

    try {
        const response = await fetch('/api/final-videos');
        const result = await response.json();

        if (result.success) {
            const videos = result.videos;

            // 更新中文版
            if (videos.cn && videos.cn.exists) {
                updateFinalVideoPreview('cn', videos.cn.path, videos.cn.file_size_mb);
            } else {
                document.getElementById('finalVideoCnStatus').textContent = '未生成';
                document.getElementById('finalVideoCnPreview').innerHTML = '<p style="color: #666; text-align: center;">点击"生成中文版"开始</p>';
                document.getElementById('finalVideoCnDownload').style.display = 'none';
            }

            // 更新英文版
            if (videos.en && videos.en.exists) {
                updateFinalVideoPreview('en', videos.en.path, videos.en.file_size_mb);
            } else {
                document.getElementById('finalVideoEnStatus').textContent = '未生成';
                document.getElementById('finalVideoEnPreview').innerHTML = '<p style="color: #666; text-align: center;">点击"生成英文版"开始</p>';
                document.getElementById('finalVideoEnDownload').style.display = 'none';
            }
        }
    } catch (error) {
        console.error('加载最终视频状态失败:', error);
    }
}

// 页面加载时检查已生成的最终视频
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(loadFinalVideos, 2000); // 延迟加载，等待项目信息加载完成
});
