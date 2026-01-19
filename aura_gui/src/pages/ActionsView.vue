<template>
  <div class="panel">
    <div class="panel-header">
      <div><strong>Action 管理</strong></div>
      <div class="panel-subtitle">浏览和管理所有已注册的 Action</div>
    </div>

    <div class="panel-body">
      <ProFilterBar v-model="filters" :status-options="[]" :plan-options="[]" @reset="onResetFilters">
        <select class="select" v-model="filters.plan">
          <option value="">全部包</option>
          <option v-for="pkg in packageOptions" :key="pkg" :value="pkg">{{ pkg }}</option>
        </select>
        <button class="btn btn-secondary btn-mini" @click="toggleFavorites" :class="{ active: showFavoritesOnly }">
          {{ showFavoritesOnly ? '显示全部' : '仅收藏' }}
        </button>
      </ProFilterBar>

      <ProDataTable
        :columns="actionColumns"
        :rows="filteredActions"
        row-key="fqid"
        maxHeight="70vh"
        :sort-default="{key:'name',dir:'asc'}"
        @row-click="openDetail"
      >
        <template #col-name="{ row }">
          <div class="action-name-cell">
            <button
              class="star-btn"
              @click.stop="toggleFavorite(row.fqid)"
              :class="{ favorited: isFavorite(row.fqid) }"
              title="收藏"
            >
              {{ isFavorite(row.fqid) ? '★' : '☆' }}
            </button>
            <div>
              <div class="action-name">{{ row.name }}</div>
              <div class="action-fqid">{{ row.fqid }}</div>
            </div>
          </div>
        </template>
        <template #col-docstring="{ row }">
          <div class="action-docstring">{{ row.docstring || '—' }}</div>
        </template>
        <template #col-package="{ row }">
          <span class="pill">{{ row.package }}</span>
        </template>
        <template #col-deps="{ row }">
          <div class="deps-tags">
            <span v-for="dep in row.service_deps" :key="dep" class="pill pill-secondary">{{ dep }}</span>
            <span v-if="!row.service_deps || !row.service_deps.length" class="empty-tag">无依赖</span>
          </div>
        </template>
      </ProDataTable>
    </div>
  </div>

  <ProContextPanel :open="detailOpen" :title="currentAction?.name || 'Action 详情'" width="640px" @close="detailOpen=false">
    <div v-if="currentAction" class="detail-wrap">
      <div class="detail-header">
        <div>
          <div class="detail-title">{{ currentAction.name }}</div>
          <div class="detail-sub">{{ currentAction.fqid }}</div>
        </div>
        <div class="detail-package">{{ currentAction.package }}</div>
      </div>

      <div v-if="currentAction.docstring" class="detail-desc">{{ currentAction.docstring }}</div>

      <div class="detail-section">
        <h4>签名</h4>
        <pre class="code-block">{{ currentAction.signature }}</pre>
      </div>

      <div class="detail-section" v-if="currentAction.service_deps && currentAction.service_deps.length">
        <h4>依赖服务</h4>
        <div class="deps-list">
          <span v-for="dep in currentAction.service_deps" :key="dep" class="pill pill-secondary">{{ dep }}</span>
        </div>
      </div>

      <div class="detail-section">
        <h4>属性</h4>
        <div class="properties-grid">
          <div class="property-item">
            <span class="property-label">只读:</span>
            <span class="property-value">{{ currentAction.read_only ? '是' : '否' }}</span>
          </div>
          <div class="property-item">
            <span class="property-label">公开:</span>
            <span class="property-value">{{ currentAction.public ? '是' : '否' }}</span>
          </div>
          <div class="property-item">
            <span class="property-label">异步:</span>
            <span class="property-value">{{ currentAction.is_async ? '是' : '否' }}</span>
          </div>
        </div>
      </div>

      <div class="detail-section" v-if="currentAction.plugin">
        <h4>所属插件</h4>
        <div class="plugin-info">
          <div><strong>ID:</strong> {{ currentAction.plugin.canonical_id }}</div>
          <div><strong>版本:</strong> {{ currentAction.plugin.version }}</div>
        </div>
      </div>
    </div>
  </ProContextPanel>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import axios from 'axios';
import { getGuiConfig } from '../config.js';
import ProFilterBar from '../components/ProFilterBar.vue';
import ProDataTable from '../components/ProDataTable.vue';
import ProContextPanel from '../components/ProContextPanel.vue';

const cfg = getGuiConfig();
const api = axios.create({
  baseURL: cfg?.api?.base_url || 'http://127.0.0.1:18098/api/v1',
  timeout: cfg?.api?.timeout_ms || 10000,
});

const actions = ref([]);
const filters = ref({ query: '', plan: '' });
const detailOpen = ref(false);
const currentAction = ref(null);
const showFavoritesOnly = ref(false);
const favorites = ref(new Set());

const actionColumns = [
  { key: 'name', label: 'Action 名称', sortable: true, width: '30%' },
  { key: 'docstring', label: '描述', width: '35%' },
  { key: 'package', label: '所属包', sortable: true, width: '20%' },
  { key: 'deps', label: '依赖服务', width: '15%' },
];

// 从 localStorage 加载收藏
onMounted(async () => {
  const stored = localStorage.getItem('aura_favorite_actions');
  if (stored) {
    try {
      favorites.value = new Set(JSON.parse(stored));
    } catch (e) {
      console.error('Failed to load favorites:', e);
    }
  }
  await loadActions();
});

async function loadActions() {
  try {
    const { data } = await api.get('/actions');
    // 后端已经返回了 package 字段，直接使用
    actions.value = data;
  } catch (err) {
    console.error('Failed to load actions:', err);
  }
}

const packageOptions = computed(() => {
  const packages = [...new Set(actions.value.map(a => a.package))];
  return packages.sort();
});

const filteredActions = computed(() => {
  let result = actions.value;

  // 收藏筛选
  if (showFavoritesOnly.value) {
    result = result.filter(a => favorites.value.has(a.fqid));
  }

  // 搜索筛选
  if (filters.value.query) {
    const q = filters.value.query.toLowerCase();
    result = result.filter(a =>
      a.name.toLowerCase().includes(q) ||
      a.fqid.toLowerCase().includes(q) ||
      (a.docstring && a.docstring.toLowerCase().includes(q))
    );
  }

  // 包筛选
  if (filters.value.plan) {
    result = result.filter(a => a.package === filters.value.plan);
  }

  return result;
});

async function openDetail(action) {
  try {
    const { data } = await api.get(`/actions/${action.fqid}`);
    currentAction.value = {
      ...data,
      package: extractPackageName(data.fqid)
    };
    detailOpen.value = true;
  } catch (err) {
    console.error('Failed to load action detail:', err);
  }
}

function toggleFavorite(fqid) {
  if (favorites.value.has(fqid)) {
    favorites.value.delete(fqid);
  } else {
    favorites.value.add(fqid);
  }
  saveFavorites();
}

function isFavorite(fqid) {
  return favorites.value.has(fqid);
}

function saveFavorites() {
  localStorage.setItem('aura_favorite_actions', JSON.stringify([...favorites.value]));
}

function toggleFavorites() {
  showFavoritesOnly.value = !showFavoritesOnly.value;
}

function onResetFilters() {
  filters.value = { query: '', plan: '' };
  showFavoritesOnly.value = false;
}
</script>

<style scoped>
.panel-subtitle {
  font-size: 13px;
  color: var(--text-3);
  margin-top: 4px;
}

.action-name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.star-btn {
  background: none;
  border: none;
  color: var(--text-3);
  font-size: 18px;
  cursor: pointer;
  padding: 0;
  line-height: 1;
  transition: color 0.2s;
}

.star-btn:hover {
  color: var(--primary);
}

.star-btn.favorited {
  color: #fbbf24;
}

.action-name {
  font-weight: 600;
  color: var(--text-1);
}

.action-fqid {
  font-size: 12px;
  color: var(--text-3);
  font-family: 'Consolas', 'Monaco', monospace;
}

.action-docstring {
  color: var(--text-2);
  font-size: 13px;
  line-height: 1.4;
}

.deps-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.pill {
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
  background: rgba(88, 101, 242, 0.12);
  color: var(--primary);
  white-space: nowrap;
}

.pill-secondary {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-2);
}

.empty-tag {
  color: var(--text-3);
  font-size: 12px;
}

.detail-wrap {
  padding: 16px;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-frosted);
}

.detail-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-1);
}

.detail-sub {
  font-size: 12px;
  color: var(--text-3);
  font-family: 'Consolas', 'Monaco', monospace;
  margin-top: 4px;
}

.detail-package {
  padding: 4px 12px;
  border-radius: 12px;
  background: rgba(88, 101, 242, 0.12);
  color: var(--primary);
  font-size: 12px;
  font-weight: 500;
}

.detail-desc {
  color: var(--text-2);
  line-height: 1.6;
  margin-bottom: 20px;
  padding: 12px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 6px;
  border-left: 3px solid var(--primary);
}

.detail-section {
  margin-bottom: 20px;
}

.detail-section h4 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-1);
  margin-bottom: 8px;
}

.code-block {
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--border-frosted);
  border-radius: 6px;
  padding: 12px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  color: var(--text-2);
  overflow-x: auto;
  white-space: pre-wrap;
  word-wrap: break-word;
}

.deps-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.properties-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
}

.property-item {
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 6px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.property-label {
  color: var(--text-3);
  font-size: 12px;
}

.property-value {
  color: var(--text-1);
  font-weight: 500;
  font-size: 13px;
}

.plugin-info {
  padding: 12px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: var(--text-2);
}

.plugin-info strong {
  color: var(--text-1);
}

.btn-mini.active {
  background: var(--primary);
  color: white;
}
</style>
