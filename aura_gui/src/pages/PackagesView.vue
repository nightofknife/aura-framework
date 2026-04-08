<template>
  <div class="panel">
    <div class="panel-header">
      <div><strong>Package 管理</strong></div>
      <div class="panel-subtitle">管理所有 Packages 和 Plans</div>
    </div>

    <div class="panel-body packages-grid">
      <!-- 左侧包列表 -->
      <div class="panel packages-list-panel">
        <div class="panel-header">
          <div class="tabs">
            <button
              class="tab-btn"
              :class="{ active: activeTab === 'packages' }"
              @click="activeTab = 'packages'"
            >
              Packages ({{ packagesData.packages?.length || 0 }})
            </button>
            <button
              class="tab-btn"
              :class="{ active: activeTab === 'plans' }"
              @click="activeTab = 'plans'"
            >
              Plans ({{ packagesData.plans?.length || 0 }})
            </button>
          </div>
          <input
            class="input"
            v-model="searchQuery"
            placeholder="搜索..."
            style="min-width:120px;"
          >
        </div>

        <div class="panel-body" style="padding:0;">
          <div class="package-list">
            <div
              v-for="pkg in filteredPackages"
              :key="pkg.name"
              class="package-item"
              :class="{ selected: selectedPackage?.name === pkg.name }"
              @click="selectPackage(pkg)"
            >
              <div class="package-icon">{{ pkg.type === 'plan' ? '📋' : '📦' }}</div>
              <div class="package-info">
                <div class="package-name">{{ pkg.name }}</div>
                <div class="package-meta">
                  <span class="package-version">v{{ pkg.version }}</span>
                  <span v-if="pkg.task_count !== undefined" class="package-tasks">
                    {{ pkg.task_count }} 任务 (task_paths)
                  </span>
                </div>
              </div>
            </div>
            <div v-if="!filteredPackages.length" class="empty-state">
              暂无{{ activeTab === 'packages' ? 'Package' : 'Plan' }}
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧详情 -->
      <div class="package-details" v-if="selectedPackage">
        <div class="panel-header details-header">
          <div>
            <strong>{{ selectedPackage.name }}</strong>
            <span class="version-badge">v{{ selectedPackage.version }}</span>
          </div>
        </div>

        <div class="tabs-container">
          <div class="tabs">
            <button
              class="tab-btn"
              :class="{ active: detailTab === 'manifest' }"
              @click="detailTab = 'manifest'"
            >
              Manifest
            </button>
            <button
              class="tab-btn"
              :class="{ active: detailTab === 'dependencies' }"
              @click="detailTab = 'dependencies'"
            >
              依赖关系
            </button>
          </div>
        </div>

        <!-- Manifest 标签页 -->
        <div v-if="detailTab === 'manifest'" class="manifest-editor">
          <div class="editor-header">
            <span class="editor-title">manifest.yaml</span>
            <span class="manifest-hint">
              提示：运行时任务来自 `task_paths` 扫描，`exports.tasks` 仅作元数据展示。
            </span>
            <div class="editor-actions">
              <button
                class="btn btn-primary btn-mini"
                :disabled="!manifestChanged"
                @click="saveManifest"
              >
                保存更改
              </button>
            </div>
          </div>
          <MonacoYamlEditor
            v-model="manifestContent"
            height="calc(100vh - 320px)"
            @change="handleManifestChange"
          />
        </div>

        <!-- 依赖关系标签页 -->
        <div v-if="detailTab === 'dependencies'" class="dependencies-view">
          <div v-if="loadingDeps" class="loading-state">加载依赖关系中...</div>
          <div v-else-if="dependencyTree" class="dependency-tree">
            <DependencyNode :node="dependencyTree" :level="0" />
          </div>
          <div v-else class="empty-state">无依赖信息</div>
        </div>
      </div>

      <div v-else class="empty-details">
        <div class="empty-icon">📦</div>
        <div class="empty-text">选择一个 Package 或 Plan 查看详情</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue';
import axios from 'axios';
import yaml from 'yaml';
import { getGuiConfig } from '../config.js';
import MonacoYamlEditor from '../components/MonacoYamlEditor.vue';
import DependencyNode from '../components/DependencyNode.vue';

const cfg = getGuiConfig();
const api = axios.create({
  baseURL: cfg?.api?.base_url || 'http://127.0.0.1:18098/api/v1',
  timeout: cfg?.api?.timeout_ms || 10000,
});

const packagesData = ref({ packages: [], plans: [] });
const activeTab = ref('packages');
const searchQuery = ref('');
const selectedPackage = ref(null);
const detailTab = ref('manifest');
const manifestContent = ref('');
const originalManifest = ref('');
const manifestChanged = ref(false);
const dependencyTree = ref(null);
const loadingDeps = ref(false);

onMounted(async () => {
  await loadPackages();
});

async function loadPackages() {
  try {
    const { data } = await api.get('/packages');
    packagesData.value = data;
  } catch (err) {
    console.error('Failed to load packages:', err);
  }
}

const filteredPackages = computed(() => {
  const list = activeTab.value === 'packages'
    ? packagesData.value.packages || []
    : packagesData.value.plans || [];

  if (!searchQuery.value) return list;

  const q = searchQuery.value.toLowerCase();
  return list.filter(pkg =>
    pkg.name.toLowerCase().includes(q) ||
    pkg.version.toLowerCase().includes(q)
  );
});

async function selectPackage(pkg) {
  selectedPackage.value = pkg;
  detailTab.value = 'manifest';
  manifestChanged.value = false;

  // 加载 manifest
  try {
    // 对包名进行 URL 编码
    const encodedName = encodeURIComponent(pkg.name);
    const { data } = await api.get(`/packages/${encodedName}/manifest`);
    const yamlStr = yaml.stringify(data, { indent: 2 });
    manifestContent.value = yamlStr;
    originalManifest.value = yamlStr;
  } catch (err) {
    console.error('Failed to load manifest:', err);
    manifestContent.value = '# 加载失败';
  }
}

function handleManifestChange(value) {
  manifestChanged.value = value !== originalManifest.value;
}

async function saveManifest() {
  if (!selectedPackage.value) return;

  try {
    const manifestObj = yaml.parse(manifestContent.value);
    const encodedName = encodeURIComponent(selectedPackage.value.name);
    const { data } = await api.put(`/packages/${encodedName}/manifest`, manifestObj);

    // 后端会对只读段（如 exports.tasks）做保留，成功后回读以保持编辑器与磁盘一致
    const refreshed = await api.get(`/packages/${encodedName}/manifest`);
    manifestContent.value = yaml.stringify(refreshed.data, { indent: 2 });

    originalManifest.value = manifestContent.value;
    manifestChanged.value = false;

    const warnings = Array.isArray(data?.warnings) ? data.warnings : [];
    const warningSuffix = warnings.length ? `\n\n注意:\n- ${warnings.join('\n- ')}` : '';
    alert(`Manifest 保存成功${warningSuffix}`);
  } catch (err) {
    console.error('Failed to save manifest:', err);
    alert(`保存失败: ${err.message}`);
  }
}

watch(() => detailTab.value, async (newTab) => {
  if (newTab === 'dependencies' && selectedPackage.value) {
    loadingDeps.value = true;
    try {
      const encodedName = encodeURIComponent(selectedPackage.value.name);
      const { data } = await api.get(`/packages/${encodedName}/dependencies`);
      dependencyTree.value = data;
    } catch (err) {
      console.error('Failed to load dependencies:', err);
      dependencyTree.value = null;
    } finally {
      loadingDeps.value = false;
    }
  }
});
</script>

<style scoped>
.packages-grid {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 16px;
  height: calc(100vh - 160px);
}

.packages-list-panel {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.tabs {
  display: flex;
  gap: 8px;
}

.tab-btn {
  padding: 6px 12px;
  border: none;
  background: transparent;
  color: var(--text-3);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
}

.tab-btn:hover {
  color: var(--text-1);
}

.tab-btn.active {
  color: var(--primary);
  border-bottom-color: var(--primary);
}

.package-list {
  overflow-y: auto;
  max-height: calc(100vh - 260px);
}

.package-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  cursor: pointer;
  border-bottom: 1px solid var(--border-frosted);
  transition: background 0.2s;
}

.package-item:hover {
  background: rgba(255, 255, 255, 0.03);
}

.package-item.selected {
  background: rgba(88, 101, 242, 0.12);
  border-left: 3px solid var(--primary);
}

.package-icon {
  font-size: 24px;
  flex-shrink: 0;
}

.package-info {
  flex: 1;
  min-width: 0;
}

.package-name {
  font-weight: 600;
  color: var(--text-1);
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.package-meta {
  display: flex;
  gap: 8px;
  margin-top: 4px;
  font-size: 11px;
}

.package-version {
  color: var(--text-3);
  font-family: 'Consolas', monospace;
}

.package-tasks {
  color: var(--text-3);
}

.package-details {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.details-header {
  flex-shrink: 0;
}

.version-badge {
  margin-left: 8px;
  padding: 2px 8px;
  border-radius: 12px;
  background: rgba(88, 101, 242, 0.12);
  color: var(--primary);
  font-size: 11px;
  font-weight: 600;
}

.tabs-container {
  padding: 0 16px;
  border-bottom: 1px solid var(--border-frosted);
  flex-shrink: 0;
}

.manifest-editor {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-frosted);
  flex-shrink: 0;
}

.editor-title {
  font-family: 'Consolas', monospace;
  color: var(--text-2);
  font-size: 13px;
}

.manifest-hint {
  margin-left: 12px;
  color: var(--text-3);
  font-size: 12px;
  flex: 1;
}

.editor-actions {
  display: flex;
  gap: 8px;
}

.dependencies-view {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.dependency-tree {
  padding: 8px;
}

.empty-state, .loading-state {
  padding: 40px;
  text-align: center;
  color: var(--text-3);
}

.empty-details {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-3);
}

.empty-icon {
  font-size: 64px;
  opacity: 0.3;
}

.empty-text {
  font-size: 14px;
}
</style>
