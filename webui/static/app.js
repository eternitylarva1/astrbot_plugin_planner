/**
 * Planner WebUI - Frontend Logic (Sliding View)
 */

const API_BASE = '';

// State
let currentDate = 'today';
let currentView = 'tasks';
let chartLoaded = {};  // Cache loaded charts

// DOM Elements
const taskList = document.getElementById('taskList');
const emptyState = document.getElementById('emptyState');
const taskInput = document.getElementById('taskInput');
const toast = document.getElementById('toast');
const viewContainer = document.getElementById('viewContainer');
const chartFrame = document.getElementById('chartFrame');
const chartLoading = document.getElementById('chartLoading');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadTasks();
    setupInputHandler();
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
 * Switch view between tasks and chart (sliding)
 */
function switchView(view) {
    currentView = view;
    
    // Update tab bar buttons
    document.querySelectorAll('.tab-item').forEach(tab => {
        const tabView = tab.dataset.view;
        tab.classList.toggle('active', tabView === view);
    });
    
    // Toggle sliding view
    if (view === 'chart') {
        viewContainer.classList.add('show-chart');
        // Load chart if not cached
        const chartDate = document.querySelector('.chart-tab.active')?.dataset.date || 'today';
        loadChart(chartDate);
    } else {
        viewContainer.classList.remove('show-chart');
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
    // Group tasks by date
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
    
    if (isCompleted) {
        return;
    }
    
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
    if (!confirm('确定要取消这个任务吗？')) {
        return;
    }
    
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
    // Update tab buttons
    document.querySelectorAll('.chart-tab').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.date === date);
    });
    
    // Show loading
    chartLoading.style.display = 'flex';
    chartFrame.style.display = 'none';
    
    // Check cache
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
            // Cache the HTML
            chartLoaded[cacheKey] = html;
            
            // Load into iframe
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

// ============ Utility Functions ============

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
        '开会': '💼',
        '代码': '👨‍💻',
        '写代码': '👨‍💻',
        '学习': '📚',
        '运动': '🏃',
        '吃饭': '🍽️',
        '睡觉': '🛌',
        '休息': '☕',
        '阅读': '📖',
        '写作': '✍️',
        '复习': '📖',
        '考试': '📋',
        '面试': '🎯',
        '项目': '📁',
        '视频': '🎬',
        '音乐': '🎵',
        '电影': '🎬',
        '游戏': '🎮',
        '购物': '🛒',
        '旅行': '✈️',
    };
    
    for (const [key, emoji] of Object.entries(keywords)) {
        if (taskName.includes(key)) {
            return emoji;
        }
    }
    return '📌';
}
