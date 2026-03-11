<template>
  <div class="panel">
    <div class="panel-header">
      <div><strong>Service 管理</strong></div>
      <div class="panel-subtitle">浏览和管理所有已注册的服务</div>
    </div>

    <div class="panel-body">
      <ProFilterBar v-model="filters" :status-options="statusOptions" :plan-options="pluginOptions" @reset="onResetFilters">
        <button class="btn btn-secondary btn-mini" @click="refreshServices">
          刷新状态
        </button>
      </ProFilterBar>

      <ProDataTable
        :columns="serviceColumns"
        :rows="filteredServices"
        row-key="id"
        maxHeight="70vh"
        :sort-default="{key:'name',dir:'asc'}"
        @row-click="openDetail"
      >
        <template #col-name="{ row }">
          <div class="service-name-cell">
            <div>
              <div class="service-name">{{ row.name }}</div>
              <div class="service-id">{{ row.id }}</div>
            </div>
          </div>
        </template>
        <template #col-class_name="{ row }">
          <code class="code-inline">{{ row.class_name }}</code>
        </template>
        <template #col-status="{ row }">
          <span class="status-badge" :class="'status-' + row.status">
            {{ statusLabels[row.status] || row.status }}
          </span>
        </template>
        <template #col-dependencies="{ row }">
          <div class="deps-tags">
            <span v-for="dep in row.dependencies" :key="dep" class="pill pill-secondary">{{ dep }}</span>
            <span v-if="!row.dependencies || !row.dependencies.length" class="empty-tag">无依赖</span>
          </div>
        </template>
        <template #col-plugin="{ row }">
          <span v-if="row.plugin" class="pill">{{ row.plugin }}</span>
          <span v-else class="empty-tag">—</span>
        </template>
      </ProDataTable>
    </div>
  </div>

  <ProContextPanel :open="detailOpen" :title="currentService?.name || 'Service 详情'" width="720px" @close="detailOpen=false">
    <div v-if="currentService" class="detail-wrap">
      <div class="detail-header">
        <div>
          <div class="detail-title">{{ currentService.name }}</div>
          <div class="detail-sub">{{ currentService.id }}</div>
        </div>
        <span class="status-badge" :class="'status-' + serviceStatus.status">
          {{ statusLabels[serviceStatus.status] || serviceStatus.status }}
        </span>
      </div>

      <div v-if="currentService.docstring" class="detail-desc">{{ currentService.docstring }}</div>

      <div v-if="serviceStatus.error" class="error-message">
        <strong>错误信息:</strong> {{ serviceStatus.error }}
      </div>

      <div class="detail-section">
        <h4>类信息</h4>
        <div class="properties-grid">
          <div class="property-item">
            <span class="property-label">类名:</span>
            <code class="property-value">{{ currentService.class_name }}</code>
          </div>
          <div class="property-item">
            <span class="property-label">已初始化:</span>
            <span class="property-value">{{ currentService.is_initialized ? '是' : '否' }}</span>
          </div>
        </div>
      </div>

      <div class="detail-section" v-if="currentService.dependencies && currentService.dependencies.length">
        <h4>依赖服务 ({{ currentService.dependencies.length }})</h4>
        <div class="dependency-tree">
          <div v-for="dep in currentService.dependencies" :key="dep" class="dep-item">
            <span class="dep-icon">📦</span>
            <span class="dep-name">{{ dep }}</span>
          </div>
        </div>
      </div>

      <div class="detail-section" v-if="currentService.methods && currentService.methods.length">
        <h4>公开方法 ({{ currentService.methods.length }})</h4>
        <div class="methods-list">
          <div v-for="method in currentService.methods" :key="method.name" class="method-item">
            <div class="method-name">{{ method.name }}</div>
            <div v-if="method.signature" class="method-signature">{{ method.signature }}</div>
          </div>
        </div>
      </div>

      <div class="detail-section" v-if="currentService.plugin">
        <h4>所属插件</h4>
        <div class="plugin-info">
          <div><strong>ID:</strong> {{ currentService.plugin.canonical_id }}</div>
          <div><strong>版本:</strong> {{ currentService.plugin.version }}</div>
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

const services = ref([]);
const filters = ref({ query: '', status: '', plan: '' });
const detailOpen = ref(false);
const currentService = ref(null);
const serviceStatus = ref({ status: 'unknown', error: null });

const serviceColumns = [
  { key: 'name', label: 'Service 名称', sortable: true, width: '25%' },
  { key: 'class_name', label: '类名', width: '20%' },
  { key: 'status', label: '状态', sortable: true, width: '12%' },
  { key: 'dependencies', label: '依赖服务', width: '23%' },
  { key: 'plugin', label: '所属插件', sortable: true, width: '20%' },
];

const statusLabels = {
  'not_initialized': '未初始化',
  'running': '运行中',
  'healthy': '健康',
  'unhealthy': '不健康',
  'error': '错误',
  'unknown': '未知'
};

const statusOptions = ['not_initialized', 'running', 'healthy', 'error'];

onMounted(async () => {
  await loadServices();
});

async function loadServices() {
  try {
    const { data } = await api.get('/services');

    // 为每个服务加载状态
    const servicesWithStatus = await Promise.all(
      data.map(async (service) => {
        try {
          const { data: status } = await api.get(`/services/${service.id}/status`);
          return { ...service, status: status.status };
        } catch (err) {
          return { ...service, status: 'unknown' };
        }
      })
    );

    services.value = servicesWithStatus;
  } catch (err) {
    console.error('Failed to load services:', err);
  }
}

const pluginOptions = computed(() => {
  const plugins = [...new Set(services.value.map(s => s.plugin).filter(Boolean))];
  return plugins;
});

const filteredServices = computed(() => {
  let result = services.value;

  // 搜索筛选
  if (filters.value.query) {
    const q = filters.value.query.toLowerCase();
    result = result.filter(s =>
      s.name.toLowerCase().includes(q) ||
      s.id.toLowerCase().includes(q) ||
      s.class_name.toLowerCase().includes(q)
    );
  }

  // 状态筛选
  if (filters.value.status) {
    result = result.filter(s => s.status === filters.value.status);
  }

  // 插件筛选
  if (filters.value.plan) {
    result = result.filter(s => s.plugin === filters.value.plan);
  }

  return result;
});

async function openDetail(service) {
  try {
    const { data } = await api.get(`/services/${service.id}`);
    currentService.value = data;

    // 获取服务状态
    const { data: status } = await api.get(`/services/${service.id}/status`);
    serviceStatus.value = status;

    detailOpen.value = true;
  } catch (err) {
    console.error('Failed to load service detail:', err);
  }
}

async function refreshServices() {
  await loadServices();
}

function onResetFilters() {
  filters.value = { query: '', status: '', plan: '' };
}
</script>

<style scoped>
.panel-subtitle {
  font-size: 13px;
  color: var(--text-3);
  margin-top: 4px;
}

.service-name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.service-name {
  font-weight: 600;
  color: var(--text-1);
}

.service-id {
  font-size: 12px;
  color: var(--text-3);
  font-family: 'Consolas', 'Monaco', monospace;
}

.code-inline {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  background: rgba(255, 255, 255, 0.05);
  padding: 2px 6px;
  border-radius: 4px;
  color: var(--text-2);
}

.status-badge {
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}

.status-not_initialized {
  background: rgba(128, 128, 128, 0.15);
  color: var(--text-3);
}

.status-running {
  background: rgba(59, 130, 246, 0.15);
  color: #60a5fa;
}

.status-healthy {
  background: rgba(34, 197, 94, 0.15);
  color: #4ade80;
}

.status-unhealthy {
  background: rgba(251, 191, 36, 0.15);
  color: #fbbf24;
}

.status-error {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
}

.status-unknown {
  background: rgba(128, 128, 128, 0.15);
  color: var(--text-3);
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

.detail-desc {
  color: var(--text-2);
  line-height: 1.6;
  margin-bottom: 20px;
  padding: 12px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 6px;
  border-left: 3px solid var(--primary);
}

.error-message {
  color: #f87171;
  background: rgba(239, 68, 68, 0.1);
  padding: 12px;
  border-radius: 6px;
  margin-bottom: 16px;
  font-size: 13px;
  border-left: 3px solid #ef4444;
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

.properties-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
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

.dependency-tree {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dep-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 6px;
}

.dep-icon {
  font-size: 16px;
}

.dep-name {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 13px;
  color: var(--text-2);
}

.methods-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 300px;
  overflow-y: auto;
}

.method-item {
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 6px;
  border-left: 2px solid rgba(88, 101, 242, 0.3);
}

.method-name {
  font-weight: 600;
  color: var(--text-1);
  font-size: 13px;
  font-family: 'Consolas', 'Monaco', monospace;
}

.method-signature {
  font-size: 12px;
  color: var(--text-3);
  font-family: 'Consolas', 'Monaco', monospace;
  margin-top: 4px;
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
</style>
