/**
 * Planner WebUI - Frontend Logic (Sliding View with Breakdown)
 */

const API_BASE = '';

// State
let currentDate = 'today';
let currentView = 'tasks';
let chartLoaded = {};  // Cache loaded charts
let breakdownTasks = [];  // Current breakdown result
let breakdownTaskName = '';  // Current breakdown task name

// Load from localStorage
function loadBreakdownFromStorage() {
    try {
        const saved = localStorage.getItem('planner_breakdown');
        if (saved) {
            const data = JSON.parse(saved);
            breakdownTasks = data.tasks || [];
            breakdownTaskName = data.taskName || '';
            return true;
        }
    } catch (e) {}
    return false;
}

function saveBreakdownToStorage() {
    try {
        localStorage.setItem('planner_breakdown', JSON.stringify({
            tasks: breakdownTasks,
            taskName: breakdownTaskName
        }));
    } catch (e) {}
}

function clearBreakdownInStorage() {
    try {
        localStorage.removeItem('planner_breakdown');
    } catch (e) {}
}

// DOM Elements
const taskList = document.getElementById('taskList');
const emptyState = document.getElementById('emptyState');
const taskInput = document.getElementById('taskInput');
const toast = document.getElementById('toast');
const viewContainer = document.getElementById('viewContainer');
const chartFrame = document.getElementById('chartFrame');
const chartLoading = document.getElementById('chartLoading');
const dateTabs = document.getElementById('dateTabs');
const statsBar = document.getElementById('statsBar');
const inputArea = document.getElementById('inputArea');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadTasks();
    setupInputHandler();
    // Load saved breakdown from localStorage
    if (loadBreakdownFromStorage() && breakdownTasks.length > 0) {
        document.getElementById('breakdownTitle').textContent = `拆解：${breakdownTaskName}`;
        renderBreakdownList();
        document.getElementById('breakdownEmpty').style.display = 'none';
        document.getElementById('breakdownResult').style.display = 'block';
    }
});

/**
 * Setup input handler for Enter key
 */
function setupInputHandler() {
    taskInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            createTask();
        }
    });
}

/**
 * Switch date filter
 */
function switchDate(date) {
    currentDate = date;
    
    // Update tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.date === date);
    });
    
    loadTasks();
}

/**
 * Switch view between tasks/breakdown/chart (sliding)
 */
function switchView(view) {
    currentView = view;
    
    // Update tab bar buttons
    document.querySelectorAll('.tab-item').forEach(tab => {
        const tabView = tab.dataset.view;
        tab.classList.toggle('active', tabView === view);
    });
    
    // Toggle sliding view - calculate offset
    viewContainer.classList.remove('show-chart', 'show-breakdown');
    
    if (view === 'chart') {
        viewContainer.classList.add('show-chart');
        dateTabs.style.display = 'none';
        statsBar.style.display = 'none';
        inputArea.style.display = 'none';
        // Load chart if not cached
        const chartDate = document.querySelector('.chart-tab.active')?.dataset.date || 'today';
        loadChart(chartDate);
    } else if (view === 'breakdown') {
        viewContainer.classList.add('show-breakdown');
        dateTabs.style.display = 'none';
        statsBar.style.display = 'none';
        inputArea.style.display = 'none';
    } else {
        dateTabs.style.display = 'flex';
        statsBar.style.display = 'flex';
        inputArea.style.display = 'block';
    }
}

/**
 * Load tasks from API
 */
async function loadTasks() {
    taskList.innerHTML = `
        <div class="loading">
            <div class="spinner"></div>
            <p>加载中...</p>
        </div>
    `;
    
    try {
        const response = await fetch(`${API_BASE}/api/tasks?date=${currentDate}`);
        const result = await response.json();
        
        if (result.code === 0) {
            renderTasks(result.data);
            updateStats();
        } else {
            showToast(result.message || '加载失败', 'error');
        }
    } catch (error) {
        console.error('Error loading tasks:', error);
        showToast('网络错误', 'error');
        renderTasks([]);
    }
}

/**
 * Render tasks to DOM
 */
function renderTasks(tasks) {
    if (!tasks || tasks.length === 0) {
        taskList.innerHTML = '';
        emptyState.style.display = 'flex';
        return;
    }
    
    emptyState.style.display = 'none';
    
    if (currentDate === 'week' || currentDate === 'next_week') {
        renderWeekTasks(tasks);
    } else {
        renderDayTasks(tasks);
    }
}

/**
 * Render day tasks
 */
function renderDayTasks(tasks) {
    const html = tasks.map(task => createTaskItemHTML(task)).join('');
    taskList.innerHTML = html;
}

/**
 * Render week tasks grouped by date
 */
function renderWeekTasks(tasks) {
    const grouped = {};
    tasks.forEach(task => {
        const date = task.date || task.start_time?.split('T')[0];
        if (!grouped[date]) {
            grouped[date] = [];
        }
        grouped[date].push(task);
    });
    
    let html = '';
    const sortedDates = Object.keys(grouped).sort();
    
    sortedDates.forEach(date => {
        const dayTasks = grouped[date];
        const dateObj = new Date(date);
        const weekday = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][dateObj.getDay()];
        const dateStr = `${dateObj.getMonth() + 1}月${dateObj.getDate()}日`;
        const isToday = date === new Date().toISOString().split('T')[0];
        
        html += `
            <div class="day-group">
                <div class="day-header">
                    <span class="day-title">${isToday ? '📅 ' : ''}${weekday}</span>
                    <span class="day-date">${dateStr}</span>
                </div>
                <div class="day-tasks">
                    ${dayTasks.map(task => createTaskItemHTML(task)).join('')}
                </div>
            </div>
        `;
    });
    
    taskList.innerHTML = html;
}

/**
 * Create task item HTML
 */
function createTaskItemHTML(task) {
    const isCompleted = task.status === 'done';
    const startTime = task.start_time ? new Date(task.start_time) : null;
    const timeStr = startTime ? formatTime(startTime) : '待定';
    const duration = task.duration_minutes || 60;
    const emoji = getTaskEmoji(task.name);
    
    return `
        <div class="task-item ${isCompleted ? 'completed' : ''}" data-id="${task.id}">
            <div class="task-checkbox ${isCompleted ? 'checked' : ''}" onclick="toggleTask('${task.id}')">
                ${isCompleted ? '✓' : ''}
            </div>
            <div class="task-content">
                <div class="task-name">${emoji} ${escapeHtml(task.name)}</div>
                <div class="task-meta">
                    <span class="task-time">⏰ ${timeStr}</span>
                    <span class="task-duration">⏱️ ${duration}分钟</span>
                </div>
            </div>
            <div class="task-actions">
                ${!isCompleted ? `
                    <button class="task-action-btn delete" onclick="cancelTask('${task.id}')" title="取消">🗑️</button>
                ` : ''}
            </div>
        </div>
    `;
}

/**
 * Update stats display
 */
async function updateStats() {
    try {
        const response = await fetch(`${API_BASE}/api/stats`);
        const result = await response.json();
        
        if (result.code === 0) {
            const data = result.data;
            document.getElementById('statTotal').textContent = data.total;
            document.getElementById('statCompleted').textContent = data.completed;
            document.getElementById('statPending').textContent = data.pending;
            document.getElementById('statRate').textContent = data.completion_rate + '%';
        }
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

/**
 * Create new task
 */
async function createTask() {
    const description = taskInput.value.trim();
    
    if (!description) {
        showToast('请输入任务描述', 'error');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/tasks`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ description }),
        });
        
        const result = await response.json();
        
        if (result.code === 0) {
            showToast('任务创建成功', 'success');
            taskInput.value = '';
            loadTasks();
        } else {
            showToast(result.message || '创建失败', 'error');
        }
    } catch (error) {
        console.error('Error creating task:', error);
        showToast('网络错误', 'error');
    }
}

/**
 * Toggle task completion
 */
async function toggleTask(taskId) {
    const taskEl = document.querySelector(`.task-item[data-id="${taskId}"]`);
    const isCompleted = taskEl.classList.contains('completed');
    
    if (isCompleted) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/tasks/${taskId}/complete`, {
            method: 'PUT',
        });
        
        const result = await response.json();
        
        if (result.code === 0) {
            showToast('任务已完成', 'success');
            loadTasks();
        } else {
            showToast(result.message || '操作失败', 'error');
        }
    } catch (error) {
        console.error('Error completing task:', error);
        showToast('网络错误', 'error');
    }
}

/**
 * Cancel task
 */
async function cancelTask(taskId) {
    if (!confirm('确定要取消这个任务吗？')) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/tasks/${taskId}`, {
            method: 'DELETE',
        });
        
        const result = await response.json();
        
        if (result.code === 0) {
            showToast('任务已取消', 'success');
            loadTasks();
        } else {
            showToast(result.message || '操作失败', 'error');
        }
    } catch (error) {
        console.error('Error cancelling task:', error);
        showToast('网络错误', 'error');
    }
}

/**
 * Load chart into iframe
 */
async function loadChart(date) {
    document.querySelectorAll('.chart-tab').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.date === date);
    });
    
    chartLoading.style.display = 'flex';
    chartFrame.style.display = 'none';
    
    const cacheKey = date;
    if (chartLoaded[cacheKey]) {
        chartFrame.srcdoc = chartLoaded[cacheKey];
        chartLoading.style.display = 'none';
        chartFrame.style.display = 'block';
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/chart?date=${date}`);
        const html = await response.text();
        
        if (html && html.length > 100) {
            chartLoaded[cacheKey] = html;
            chartFrame.srcdoc = html;
            chartFrame.onload = () => {
                chartLoading.style.display = 'none';
                chartFrame.style.display = 'block';
            };
        } else {
            chartLoading.innerHTML = '<p>暂无图表数据</p>';
        }
    } catch (error) {
        console.error('Error loading chart:', error);
        chartLoading.innerHTML = '<p>加载失败</p>';
    }
}

// ==================== Breakdown Functions ====================

/**
 * Break down a task
 */
async function breakdownTask() {
    const input = document.getElementById('breakdownInput');
    const taskName = input.value.trim();
    
    if (!taskName) {
        showToast('请输入要拆解的任务', 'error');
        return;
    }
    
    const resultDiv = document.getElementById('breakdownResult');
    const emptyDiv = document.getElementById('breakdownEmpty');
    const loadingDiv = document.getElementById('breakdownLoading');
    
    emptyDiv.style.display = 'none';
    loadingDiv.style.display = 'flex';
    resultDiv.style.display = 'none';
    
    try {
        const response = await fetch(`${API_BASE}/api/breakdown`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ task_name: taskName }),
        });
        
        const result = await response.json();
        
        loadingDiv.style.display = 'none';
        
        if (result.code === 0) {
            // 显示拆解结果
            breakdownTaskName = taskName;
            breakdownTasks = result.data.tasks || [];  // 使用 LLM 返回的任务
            document.getElementById('breakdownTitle').textContent = `拆解：${taskName}`;
            renderBreakdownList();
            saveBreakdownToStorage();  // 保存到 localStorage
            resultDiv.style.display = 'block';
        } else {
            showToast(result.message || '拆解失败', 'error');
            emptyDiv.style.display = 'flex';
        }
    } catch (error) {
        console.error('Error in breakdown:', error);
        loadingDiv.style.display = 'none';
        showToast('网络错误', 'error');
        emptyDiv.style.display = 'flex';
    }
}

/**
 * Render breakdown task list
 */
function renderBreakdownList() {
    const listDiv = document.getElementById('breakdownList');
    
    if (breakdownTasks.length === 0) {
        listDiv.innerHTML = '<div class="breakdown-empty-hint">还没有子任务，请添加或输入任务名自动拆解</div>';
        return;
    }
    
    let html = '';
    breakdownTasks.forEach((task, index) => {
        html += `
            <div class="breakdown-item" data-index="${index}">
                <div class="breakdown-item-index">${index + 1}</div>
                <div class="breakdown-item-content">
                    <input type="text" class="breakdown-item-name" value="${escapeHtml(task.name)}" 
                           onchange="updateBreakdownTask(${index}, 'name', this.value)">
                    <div class="breakdown-item-duration">
                        <input type="number" class="breakdown-item-time" value="${task.duration}" min="5" max="240"
                               onchange="updateBreakdownTask(${index}, 'duration', parseInt(this.value))">
                        <span>分钟</span>
                    </div>
                </div>
                <button class="breakdown-item-delete" onclick="deleteBreakdownTask(${index})">🗑️</button>
            </div>
        `;
    });
    
    listDiv.innerHTML = html;
}

/**
 * Update a breakdown task
 */
function updateBreakdownTask(index, field, value) {
    if (field === 'name') {
        breakdownTasks[index].name = value;
    } else if (field === 'duration') {
        breakdownTasks[index].duration = value;
    }
    saveBreakdownToStorage();
}

/**
 * Delete a breakdown task
 */
function deleteBreakdownTask(index) {
    breakdownTasks.splice(index, 1);
    renderBreakdownList();
    saveBreakdownToStorage();
}

/**
 * Add a new breakdown task
 */
function addBreakdownTask() {
    breakdownTasks.push({
        name: '新任务',
        duration: 30
    });
    renderBreakdownList();
    saveBreakdownToStorage();
}

/**
 * Import breakdown tasks
 */
async function importBreakdown() {
    if (breakdownTasks.length === 0) {
        showToast('没有可导入的任务', 'error');
        return;
    }
    
    // 过滤掉空任务
    const validTasks = breakdownTasks.filter(t => t.name && t.name.trim());
    if (validTasks.length === 0) {
        showToast('没有有效的任务可导入', 'error');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/breakdown/import`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ tasks: validTasks }),
        });
        
        const result = await response.json();
        
        if (result.code === 0) {
            showToast(result.message || `已导入 ${validTasks.length} 个任务`, 'success');
            // 清空拆解结果
            breakdownTasks = [];
            breakdownTaskName = '';
            clearBreakdownInStorage();  // 清除 localStorage
            document.getElementById('breakdownInput').value = '';
            document.getElementById('breakdownResult').style.display = 'none';
            document.getElementById('breakdownEmpty').style.display = 'flex';
            // 切换到任务视图
            switchView('tasks');
        } else {
            showToast(result.message || '导入失败', 'error');
        }
    } catch (error) {
        console.error('Error importing breakdown:', error);
        showToast('网络错误', 'error');
    }
}

// ==================== Utility Functions ====================

function showToast(message, type = 'info') {
    toast.textContent = message;
    toast.className = 'toast show';
    if (type === 'success') toast.classList.add('success');
    if (type === 'error') toast.classList.add('error');
    
    setTimeout(() => {
        toast.classList.remove('show');
    }, 2500);
}

function formatTime(date) {
    if (!date) return '--:--';
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${hours}:${minutes}`;
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML.replace(/'/g, '&apos;').replace(/"/g, '&quot;');
}

function getTaskEmoji(taskName) {
    const keywords = {
        '开会': '💼', '代码': '👨‍💻', '写代码': '👨‍💻', '学习': '📚',
        '运动': '🏃', '吃饭': '🍽️', '睡觉': '🛌', '休息': '☕',
        '阅读': '📖', '写作': '✍️', '复习': '📖', '考试': '📋',
        '面试': '🎯', '项目': '📁', '视频': '🎬', '音乐': '🎵',
        '电影': '🎬', '游戏': '🎮', '购物': '🛒', '旅行': '✈️',
    };
    
    for (const [key, emoji] of Object.entries(keywords)) {
        if (taskName.includes(key)) return emoji;
    }
    return '📌';
}
