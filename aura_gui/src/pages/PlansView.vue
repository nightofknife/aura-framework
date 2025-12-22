<template>
  <div class="panel">
    <div class="panel-header">
      <div><strong>方案与任务</strong></div>
      <div class="panel-subtitle">快速浏览任务结果与上下文流向</div>
    </div>

    <div class="panel-body plan-task-grid">
      <div class="panel plan-panel">
        <div class="panel-header">
          <strong>方案列表</strong>
          <input class="input" v-model="planQuery" placeholder="搜索方案…" style="min-width:140px;">
        </div>
        <div class="panel-body" style="padding:0;">
          <div class="plan-list">
            <table>
              <thead>
                <tr><th>名称</th></tr>
              </thead>
              <tbody>
                <tr
                  v-for="p in filteredPlans"
                  :key="p.name"
                  @click="selectPlan(p.name)"
                  :style="{background: selectedPlan===p.name ? 'rgba(88, 101, 242, 0.12)' : 'transparent'}"
                >
                  <td>
                    <strong>{{ p.name }}</strong>
                    <div class="plan-count">{{ p.task_count }} 个任务</div>
                  </td>
                </tr>
                <tr v-if="!filteredPlans.length"><td class="empty-cell">暂无方案</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div class="task-panel">
        <ProFilterBar v-model="filters" :status-options="[]" :plan-options="[]" @reset="onResetFilters">
          <select class="select" v-model="density" title="行高">
            <option value="comfy">舒适</option>
            <option value="compact">紧凑</option>
          </select>
        </ProFilterBar>

        <ProDataTable
          :columns="taskColumns"
          :rows="taskRows"
          row-key="__key"
          :maxHeight="density==='compact' ? '68vh' : '60vh'"
          :sort-default="{key:'title',dir:'asc'}"
          @row-click="openDetail"
        >
          <template #col-title="{ row }">
            <div class="task-title">{{ row.title }}</div>
            <div class="task-desc">{{ row.description || '—' }}</div>
          </template>
          <template #col-result="{ row }">
            <div class="result-preview">{{ row.returnsPreview }}</div>
          </template>
          <template #col-impact="{ row }">
            <div class="impact-tags">
              <span v-for="tag in row.impacts" :key="tag" class="pill">{{ tag }}</span>
              <span v-if="!row.impacts.length" class="empty-tag">无明显影响</span>
            </div>
          </template>
          <template #col-scale="{ row }">
            <div class="scale">{{ row.nodeCount }} 节点</div>
            <div class="scale-sub">{{ row.depCount }} 依赖</div>
          </template>
          <template #actions="{ row }">
            <button class="btn btn-primary" @click.stop="openDetail(row)">任务细节</button>
          </template>
        </ProDataTable>
      </div>
    </div>
  </div>

  <ProContextPanel :open="drawerOpen" :title="drawerTitle" width="640px" @close="drawerOpen=false">
    <div v-if="selectedDetail" class="detail-wrap">
      <div class="detail-header">
        <div>
          <div class="detail-title">{{ selectedDetail.title }}</div>
          <div class="detail-sub">{{ selectedDetail.taskName }}</div>
        </div>
        <div class="detail-plan">{{ selectedPlan }}</div>
      </div>

      <div v-if="selectedDetail.description" class="detail-desc">{{ selectedDetail.description }}</div>

      <div class="detail-tabs">
        <button
          v-for="tab in detailTabs"
          :key="tab.key"
          class="tab-button"
          :class="{ active: detailTab === tab.key }"
          @click="detailTab = tab.key"
        >
          {{ tab.label }}
        </button>
      </div>

      <div v-if="detailTab === 'overview'" class="detail-section">
        <div class="section-title">执行结果</div>
        <div class="return-block">
          <div class="label">returns</div>
          <code>{{ selectedDetail.returnsRaw }}</code>
        </div>
        <div class="section-title">影响摘要</div>
        <div class="impact-tags">
          <span v-for="tag in selectedDetail.impacts" :key="tag" class="pill">{{ tag }}</span>
          <span v-if="!selectedDetail.impacts.length" class="empty-tag">无明显影响</span>
        </div>
        <div class="section-title">上下文读写</div>
        <div class="summary-line">读取 {{ selectedDetail.reads.length }} 项</div>
        <div class="summary-line">写入 {{ selectedDetail.writes.length }} 项</div>
      </div>

      <div v-else-if="detailTab === 'nodes'" class="detail-section">
        <div v-for="node in selectedDetail.nodes" :key="node.id" class="node-card">
          <div class="node-head">
            <strong>{{ node.id }}</strong>
            <span class="node-action">{{ node.action }}</span>
          </div>
          <div class="node-meta">
            <span v-if="node.loopSummary">循环：{{ node.loopSummary }}</span>
            <span v-if="node.retrySummary">重试：{{ node.retrySummary }}</span>
            <span v-if="node.dependencies.length">依赖：{{ node.dependencies.join(', ') }}</span>
            <span v-else>依赖：无</span>
          </div>
          <div class="node-io">
            <div class="io-block">
              <div class="label">读取上下文</div>
              <div class="chips">
                <span v-for="item in node.reads" :key="item" class="chip read">{{ item }}</span>
                <span v-if="!node.reads.length" class="empty-tag">无</span>
              </div>
            </div>
            <div class="io-block">
              <div class="label">写入上下文</div>
              <div class="chips">
                <span v-for="item in node.writes" :key="item" class="chip write">{{ item }}</span>
                <span class="chip system">nodes.{{ node.id }}.run_state</span>
              </div>
            </div>
          </div>
          <div v-if="node.conditions.length" class="node-condition">
            <div class="label">条件</div>
            <div class="code-block" v-for="expr in node.conditions" :key="expr">{{ expr }}</div>
          </div>
        </div>
      </div>

      <div v-else-if="detailTab === 'deps'" class="detail-section deps-section">
        <div
          v-for="node in selectedDetail.nodes"
          :key="node.id"
          :id="`dep-row-${node.id}`"
          class="dep-row"
          :class="{ highlight: hoveredNodeId === node.id || activeNodeId === node.id }"
        >
          <div class="dep-title">{{ node.id }}</div>
          <div class="dep-info">
            <div class="dep-line">
              <span class="dep-label">依赖</span>
              <div class="dep-chips">
                <button
                  v-for="dep in node.dependencies"
                  :key="dep"
                  type="button"
                  class="dep-chip"
                  @mouseenter="setHoverNode(dep)"
                  @mouseleave="clearHoverNode"
                  @click="jumpToNode(dep)"
                >
                  {{ dep }}
                </button>
                <span v-if="!node.dependencies.length" class="empty-tag">无</span>
              </div>
            </div>
            <div class="dep-line">
              <span class="dep-label">被依赖</span>
              <div class="dep-chips">
                <button
                  v-for="dep in node.dependents"
                  :key="dep"
                  type="button"
                  class="dep-chip"
                  @mouseenter="setHoverNode(dep)"
                  @mouseleave="clearHoverNode"
                  @click="jumpToNode(dep)"
                >
                  {{ dep }}
                </button>
                <span v-if="!node.dependents.length" class="empty-tag">无</span>
              </div>
            </div>
            <div v-if="node.conditions.length" class="dep-conditions">
              <div class="dep-label">条件</div>
              <div class="code-block" v-for="expr in node.conditions" :key="expr">{{ expr }}</div>
            </div>
          </div>
        </div>
      </div>

      <div v-else-if="detailTab === 'flow'" class="detail-section flow-section">
        <div class="flow-toolbar">
          <div class="flow-hint">点击节点进入聚焦视图，滚动浏览依赖结构。</div>
          <button v-if="focusNode" class="btn btn-ghost btn-mini" @click="clearFocusNode">退出聚焦</button>
        </div>
        <div class="flow-viewport" ref="flowViewportRef">
          <div
            class="flow-canvas"
            :style="{ width: `${graphLayout.width}px`, height: `${graphLayout.height}px` }"
          >
            <svg class="flow-edges" :width="graphLayout.width" :height="graphLayout.height">
              <defs>
                <marker
                  id="flow-arrow"
                  markerWidth="8"
                  markerHeight="8"
                  refX="6"
                  refY="4"
                  orient="auto"
                >
                  <path d="M0,0 L8,4 L0,8 Z" fill="rgba(88, 101, 242, 0.6)" />
                </marker>
              </defs>
              <path
                v-for="edge in graphLayout.edges"
                :key="edge.key"
                :d="edge.path"
                stroke="rgba(88, 101, 242, 0.45)"
                stroke-width="1.6"
                fill="none"
                marker-end="url(#flow-arrow)"
              />
            </svg>

            <button
              v-for="node in graphLayout.nodes"
              :key="node.id"
              type="button"
              class="flow-node"
              :class="{
                hover: hoveredNodeId === node.id,
                active: activeNodeId === node.id,
                focused: focusNodeId === node.id
              }"
              :style="{ left: `${node.x}px`, top: `${node.y}px` }"
              @mouseenter="setHoverNode(node.id)"
              @mouseleave="clearHoverNode"
              @click="setFocusNode(node.id)"
            >
              <div class="flow-title">{{ node.id }}</div>
              <div class="flow-sub">{{ node.action }}</div>
            </button>
          </div>

          <div v-if="focusNode" class="flow-focus">
            <div class="focus-card">
              <div class="focus-head">
                <div>
                  <div class="focus-title">{{ focusNode.id }}</div>
                  <div class="focus-sub">{{ focusNode.action }}</div>
                </div>
                <button class="btn btn-ghost btn-mini" @click="clearFocusNode">关闭</button>
              </div>
              <div class="focus-body">
                <div class="focus-column">
                  <div class="focus-label">依赖</div>
                  <div class="chips">
                    <button
                      v-for="dep in focusNode.dependencies"
                      :key="dep"
                      type="button"
                      class="dep-chip"
                      @mouseenter="setHoverNode(dep)"
                      @mouseleave="clearHoverNode"
                      @click="setFocusNode(dep)"
                    >
                      {{ dep }}
                    </button>
                    <span v-if="!focusNode.dependencies.length" class="empty-tag">无</span>
                  </div>
                </div>
                <div class="focus-center">
                  <div class="focus-node">
                    <div class="focus-node-title">{{ focusNode.id }}</div>
                    <div class="focus-meta">{{ focusNode.action || '未设置动作' }}</div>
                    <div class="focus-meta" v-if="focusNode.loopSummary">循环：{{ focusNode.loopSummary }}</div>
                    <div class="focus-meta" v-if="focusNode.retrySummary">重试：{{ focusNode.retrySummary }}</div>
                    <div class="focus-meta">读取 {{ focusNode.reads.length }} 项 · 写入 {{ focusNode.writes.length }} 项</div>
                  </div>
                </div>
                <div class="focus-column">
                  <div class="focus-label">被依赖</div>
                  <div class="chips">
                    <button
                      v-for="dep in focusNode.dependents"
                      :key="dep"
                      type="button"
                      class="dep-chip"
                      @mouseenter="setHoverNode(dep)"
                      @mouseleave="clearHoverNode"
                      @click="setFocusNode(dep)"
                    >
                      {{ dep }}
                    </button>
                    <span v-if="!focusNode.dependents.length" class="empty-tag">无</span>
                  </div>
                </div>
              </div>
              <div v-if="focusNode.conditions.length" class="focus-conditions">
                <div class="focus-label">条件</div>
                <div class="code-block" v-for="expr in focusNode.conditions" :key="expr">{{ expr }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-else class="detail-section">
        <div class="section-title">读取上下文</div>
        <div class="chips">
          <span v-for="item in selectedDetail.reads" :key="item" class="chip read">{{ item }}</span>
          <span v-if="!selectedDetail.reads.length" class="empty-tag">无</span>
        </div>
        <div class="section-title">写入上下文</div>
        <div class="chips">
          <span v-for="item in selectedDetail.writes" :key="item" class="chip write">{{ item }}</span>
          <span v-if="!selectedDetail.writes.length" class="empty-tag">无</span>
        </div>
      </div>
    </div>

    <div v-else class="empty-panel">未选择任务</div>
  </ProContextPanel>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue';
import axios from 'axios';
import { getGuiConfig } from '../config.js';
import ProFilterBar from '../components/ProFilterBar.vue';
import ProDataTable from '../components/ProDataTable.vue';
import ProContextPanel from '../components/ProContextPanel.vue';

const cfg = getGuiConfig();
const api = axios.create({
  baseURL: cfg?.api?.base_url || 'http://127.0.0.1:18098/api/v1',
  timeout: cfg?.api?.timeout_ms || 5000,
});

const plans = ref([]);
const planQuery = ref('');
const selectedPlan = ref('');
const tasks = ref([]);
const filters = ref({ query:'', status:'', plan:'' });
const density = ref('comfy');

const taskColumns = [
  { key:'title', label:'任务', sortable:true, width:'36%' },
  { key:'result', label:'结果预览', width:'24%' },
  { key:'impact', label:'影响', width:'22%' },
  { key:'scale', label:'规模', sortable:true, width:'12%' },
];

const CONTEXT_REGEX = /(state|inputs|initial|loop|nodes)\.[A-Za-z0-9_.]+/g;
const FLOW_NODE_WIDTH = 160;
const FLOW_NODE_HEIGHT = 56;
const FLOW_COL_GAP = 36;
const FLOW_ROW_GAP = 80;
const FLOW_PADDING = 40;
const FLOW_MIN_WIDTH = 520;
const FLOW_MIN_HEIGHT = 260;

const clipText = (value, max = 80) => {
  if (!value) return '';
  const text = String(value).replace(/\s+/g, ' ').trim();
  return text.length > max ? `${text.slice(0, max)}…` : text;
};

const formatReturnRaw = (value) => {
  if (value === undefined) return '无显式返回';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
};

const formatReturnPreview = (value) => {
  if (value === undefined) return '无显式返回';
  if (typeof value === 'string') return clipText(value, 80);
  try {
    return clipText(JSON.stringify(value), 80);
  } catch {
    return clipText(String(value), 80);
  }
};

const collectContextRefs = (value, set) => {
  if (value == null) return;
  if (typeof value === 'string') {
    if (!value.includes('{{') && !value.includes('{%')) return;
    const matches = value.match(CONTEXT_REGEX);
    if (matches) matches.forEach((m) => set.add(m));
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((item) => collectContextRefs(item, set));
    return;
  }
  if (typeof value === 'object') {
    Object.values(value).forEach((item) => collectContextRefs(item, set));
  }
};

const collectDependencies = (struct, set) => {
  if (!struct) return;
  if (typeof struct === 'string') {
    if (!struct.startsWith('when:')) set.add(struct);
    return;
  }
  if (Array.isArray(struct)) {
    struct.forEach((item) => collectDependencies(item, set));
    return;
  }
  if (typeof struct === 'object') {
    if (struct.and) return collectDependencies(struct.and, set);
    if (struct.or) return collectDependencies(struct.or, set);
    if (struct.not) return collectDependencies(struct.not, set);
    Object.keys(struct).forEach((key) => set.add(key));
  }
};

const collectWhenExpressions = (struct, list) => {
  if (!struct) return;
  if (typeof struct === 'string') {
    if (struct.startsWith('when:')) {
      list.push(struct.replace(/^when:/, '').trim());
    }
    return;
  }
  if (Array.isArray(struct)) {
    struct.forEach((item) => collectWhenExpressions(item, list));
    return;
  }
  if (typeof struct === 'object') {
    if (struct.and) return collectWhenExpressions(struct.and, list);
    if (struct.or) return collectWhenExpressions(struct.or, list);
    if (struct.not) return collectWhenExpressions(struct.not, list);
  }
};

const summarizeLoop = (loopConfig) => {
  if (!loopConfig || typeof loopConfig !== 'object') return '';
  if (loopConfig.for_each !== undefined) return `遍历: ${clipText(loopConfig.for_each, 40)}`;
  if (loopConfig.times !== undefined) return `重复: ${loopConfig.times} 次`;
  if (loopConfig.while !== undefined) return `条件循环: ${clipText(loopConfig.while, 40)}`;
  return '';
};

const summarizeRetry = (node) => {
  const retry = node.retry;
  const parts = [];
  if (typeof retry === 'number') parts.push(`重试 ${retry} 次`);
  if (retry && typeof retry === 'object') {
    if (retry.count) parts.push(`重试 ${retry.count} 次`);
    if (retry.delay || retry.interval) parts.push(`间隔 ${retry.delay || retry.interval}s`);
    if (retry.condition || retry.retry_condition) parts.push(`条件: ${clipText(retry.condition || retry.retry_condition, 40)}`);
  }
  if (node.retry_condition) parts.push(`条件: ${clipText(node.retry_condition, 40)}`);
  return parts.join(' / ');
};

const buildImpactTags = (steps, returnsValue) => {
  const tags = new Set();
  if (returnsValue !== undefined) tags.add('有返回');
  Object.values(steps || {}).forEach((node) => {
    const action = node.action || '';
    if (node.outputs && Object.keys(node.outputs).length) tags.add('导出输出');
    if (action === 'state.set') tags.add('写入状态');
    if (action === 'state.delete') tags.add('删除状态');
    if (action === 'state.get') tags.add('读取状态');
    if (action === 'aura.run_task') tags.add('调用子任务');
    if (node.loop) tags.add('包含循环');
  });
  return Array.from(tags);
};

const buildNodeDetails = (nodeId, node) => {
  const reads = new Set();
  collectContextRefs(node.params, reads);
  collectContextRefs(node.loop, reads);
  collectContextRefs(node.outputs, reads);
  collectContextRefs(node.retry, reads);
  collectContextRefs(node.retry_condition, reads);
  collectContextRefs(node.depends_on, reads);

  const writes = [];
  if (node.outputs && Object.keys(node.outputs).length) {
    Object.keys(node.outputs).forEach((key) => writes.push(`nodes.${nodeId}.${key}`));
  } else {
    writes.push(`nodes.${nodeId}.output`);
  }

  const deps = new Set();
  collectDependencies(node.depends_on, deps);
  const conditions = [];
  collectWhenExpressions(node.depends_on, conditions);

  return {
    id: nodeId,
    action: node.action || '未设置动作',
    reads: Array.from(reads).sort(),
    writes,
    dependencies: Array.from(deps).sort(),
    conditions,
    loopSummary: summarizeLoop(node.loop),
    retrySummary: summarizeRetry(node),
  };
};

const buildGraphLayout = (nodes) => {
  if (!nodes || nodes.length === 0) {
    return { nodes: [], edges: [], width: FLOW_MIN_WIDTH, height: FLOW_MIN_HEIGHT, positions: {} };
  }

  const nodeIds = nodes.map((node) => node.id);
  const nodeSet = new Set(nodeIds);
  const depsMap = new Map();
  const outgoing = new Map();
  const indegree = new Map();

  nodeIds.forEach((id) => {
    depsMap.set(id, []);
    outgoing.set(id, []);
    indegree.set(id, 0);
  });

  nodes.forEach((node) => {
    const deps = (node.dependencies || []).filter((dep) => nodeSet.has(dep));
    depsMap.set(node.id, deps);
    indegree.set(node.id, deps.length);
    deps.forEach((dep) => outgoing.get(dep).push(node.id));
  });

  const levels = [];
  const visited = new Set();
  let queue = nodeIds.filter((id) => indegree.get(id) === 0).sort();
  if (queue.length === 0) queue = [...nodeIds].sort();

  while (queue.length) {
    levels.push(queue);
    const nextQueue = [];
    queue.forEach((id) => {
      if (visited.has(id)) return;
      visited.add(id);
      outgoing.get(id).forEach((child) => {
        indegree.set(child, indegree.get(child) - 1);
        if (indegree.get(child) === 0) nextQueue.push(child);
      });
    });
    queue = nextQueue.sort();
  }

  if (visited.size < nodeIds.length) {
    const remaining = nodeIds.filter((id) => !visited.has(id));
    levels.push(remaining.sort());
  }

  const maxCols = Math.max(...levels.map((level) => level.length), 1);
  const rowWidthMax = maxCols * FLOW_NODE_WIDTH + (maxCols - 1) * FLOW_COL_GAP;
  const width = Math.max(FLOW_MIN_WIDTH, FLOW_PADDING * 2 + rowWidthMax);
  const height = Math.max(
    FLOW_MIN_HEIGHT,
    FLOW_PADDING * 2 + levels.length * FLOW_NODE_HEIGHT + (levels.length - 1) * FLOW_ROW_GAP
  );

  const positions = {};
  levels.forEach((level, levelIndex) => {
    const rowWidth = level.length * FLOW_NODE_WIDTH + (level.length - 1) * FLOW_COL_GAP;
    const startX = FLOW_PADDING + (rowWidthMax - rowWidth) / 2;
    const y = FLOW_PADDING + levelIndex * (FLOW_NODE_HEIGHT + FLOW_ROW_GAP);
    level.forEach((id, idx) => {
      positions[id] = { x: startX + idx * (FLOW_NODE_WIDTH + FLOW_COL_GAP), y };
    });
  });

  const edges = [];
  nodes.forEach((node) => {
    const deps = depsMap.get(node.id) || [];
    deps.forEach((dep) => {
      const from = positions[dep];
      const to = positions[node.id];
      if (!from || !to) return;
      const x1 = from.x + FLOW_NODE_WIDTH / 2;
      const y1 = from.y + FLOW_NODE_HEIGHT;
      const x2 = to.x + FLOW_NODE_WIDTH / 2;
      const y2 = to.y;
      const midY = (y1 + y2) / 2;
      edges.push({ key: `${dep}->${node.id}`, path: `M ${x1} ${y1} C ${x1} ${midY} ${x2} ${midY} ${x2} ${y2}` });
    });
  });

  const layoutNodes = nodes.map((node) => {
    const pos = positions[node.id] || { x: FLOW_PADDING, y: FLOW_PADDING };
    return { ...node, x: pos.x, y: pos.y };
  });

  return { nodes: layoutNodes, edges, width, height, positions };
};

const taskRows = computed(() => {
  const list = tasks.value.map((t) => {
    const def = t.definition || {};
    const steps = def.steps || {};
    const nodeIds = Object.keys(steps);
    const depSet = new Set();
    nodeIds.forEach((id) => collectDependencies(steps[id]?.depends_on, depSet));
    return {
      __key: t.full_task_id || t.task_name_in_plan || t.task_name,
      title: t.meta?.title || t.task_name_in_plan || t.task_name,
      description: t.meta?.description || '',
      task_name: t.task_name_in_plan || t.task_name,
      definition: def,
      returnsPreview: formatReturnPreview(def.returns),
      impacts: buildImpactTags(steps, def.returns),
      nodeCount: nodeIds.length,
      depCount: depSet.size,
      scale: nodeIds.length,
    };
  });
  const q = (filters.value.query || '').toLowerCase();
  if (!q) return list;
  return list.filter((r) =>
    r.title.toLowerCase().includes(q) ||
    (r.description || '').toLowerCase().includes(q) ||
    (r.task_name || '').toLowerCase().includes(q)
  );
});

const filteredPlans = computed(() => {
  const q = planQuery.value.toLowerCase();
  return q ? plans.value.filter((p) => p.name.toLowerCase().includes(q)) : plans.value;
});

const drawerOpen = ref(false);
const selectedDetail = ref(null);
const detailTab = ref('overview');
const detailTabs = [
  { key: 'overview', label: '概览' },
  { key: 'nodes', label: '节点与上下文' },
  { key: 'deps', label: '依赖与条件' },
  { key: 'flow', label: '依赖流程图' },
  { key: 'context', label: '上下文总览' },
];
const hoveredNodeId = ref('');
const activeNodeId = ref('');
const focusNodeId = ref('');
const flowViewportRef = ref(null);

const nodeLookup = computed(() => {
  const map = new Map();
  selectedDetail.value?.nodes?.forEach((node) => map.set(node.id, node));
  return map;
});

const focusNode = computed(() => nodeLookup.value.get(focusNodeId.value));
const graphLayout = computed(() => buildGraphLayout(selectedDetail.value?.nodes || []));

const setHoverNode = (nodeId) => {
  hoveredNodeId.value = nodeId || '';
};
const clearHoverNode = () => {
  hoveredNodeId.value = '';
};
const jumpToNode = (nodeId) => {
  if (!nodeId) return;
  activeNodeId.value = nodeId;
  nextTick(() => {
    const target = document.getElementById(`dep-row-${nodeId}`);
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  });
};
const setFocusNode = (nodeId) => {
  if (!nodeId) return;
  focusNodeId.value = nodeId;
  activeNodeId.value = nodeId;
  nextTick(() => {
    const viewport = flowViewportRef.value;
    const pos = graphLayout.value?.positions?.[nodeId];
    if (!viewport || !pos) return;
    const centerX = pos.x + FLOW_NODE_WIDTH / 2;
    const centerY = pos.y + FLOW_NODE_HEIGHT / 2;
    viewport.scrollTo({
      left: centerX - viewport.clientWidth / 2,
      top: centerY - viewport.clientHeight / 2,
      behavior: 'smooth'
    });
  });
};
const clearFocusNode = () => {
  focusNodeId.value = '';
};

const drawerTitle = computed(() => selectedDetail.value ? '任务细节' : '任务细节');

async function loadPlans() {
  const { data } = await api.get('/plans');
  plans.value = data || [];
  if (!selectedPlan.value && plans.value.length) selectPlan(plans.value[0].name);
}
async function loadTasks(plan) {
  tasks.value = [];
  const { data } = await api.get(`/plans/${plan}/tasks`);
  tasks.value = data || [];
}
function selectPlan(name) {
  selectedPlan.value = name;
  loadTasks(name);
}
function onResetFilters() {}

function openDetail(row) {
  if (!row || !row.definition) return;
  const def = row.definition || {};
  const steps = def.steps || {};
  const nodes = Object.keys(steps).map((id) => buildNodeDetails(id, steps[id]));
  const nodeIdSet = new Set(nodes.map((node) => node.id));
  const dependentsMap = new Map(nodes.map((node) => [node.id, []]));

  nodes.forEach((node) => {
    (node.dependencies || [])
      .filter((dep) => nodeIdSet.has(dep))
      .forEach((dep) => {
        dependentsMap.get(dep).push(node.id);
      });
  });

  nodes.forEach((node) => {
    node.dependents = (dependentsMap.get(node.id) || []).sort();
  });

  const reads = new Set();
  const writes = new Set();
  nodes.forEach((node) => {
    node.reads.forEach((item) => reads.add(item));
    node.writes.forEach((item) => writes.add(item));
  });
  collectContextRefs(def.returns, reads);

  selectedDetail.value = {
    title: row.title,
    description: row.description,
    taskName: row.task_name,
    impacts: row.impacts,
    returnsRaw: formatReturnRaw(def.returns),
    nodes,
    reads: Array.from(reads).sort(),
    writes: Array.from(writes).sort(),
  };
  detailTab.value = 'overview';
  drawerOpen.value = true;
  hoveredNodeId.value = '';
  activeNodeId.value = '';
  focusNodeId.value = '';
}

onMounted(loadPlans);
</script>

<style scoped>
.panel-subtitle {
  color: var(--text-secondary);
  font-size: 13px;
}
.plan-task-grid {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 16px;
  min-height: 60vh;
}
.plan-panel {
  display: flex;
  flex-direction: column;
}
.plan-list {
  max-height: 60vh;
  overflow: auto;
}
.plan-count {
  color: var(--text-secondary);
  font-size: 12px;
}
.plan-list th {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-frosted);
  background: rgba(249, 250, 251, 0.8);
}
.plan-list td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-frosted);
  cursor: pointer;
}
.empty-cell {
  padding: 12px;
  color: var(--text-secondary);
}
.task-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.task-title {
  font-weight: 700;
}
.task-desc {
  color: var(--text-secondary);
  font-size: 12px;
  max-width: 900px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.result-preview {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.impact-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.empty-tag {
  font-size: 12px;
  color: var(--text-tertiary);
}
.scale {
  font-weight: 600;
}
.scale-sub {
  font-size: 12px;
  color: var(--text-secondary);
}
.detail-wrap {
  display: grid;
  gap: 12px;
}
.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.detail-title {
  font-size: 18px;
  font-weight: 700;
}
.detail-sub {
  font-size: 12px;
  color: var(--text-secondary);
}
.detail-plan {
  font-size: 12px;
  color: var(--text-secondary);
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--border-frosted);
}
.detail-desc {
  color: var(--text-secondary);
}
.detail-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.tab-button {
  border: 1px solid transparent;
  border-radius: 999px;
  padding: 6px 14px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--dur) var(--ease);
}
.tab-button:hover {
  background: rgba(88, 101, 242, 0.08);
  color: var(--text-primary);
}
.tab-button.active {
  background: var(--primary-accent);
  color: #fff;
}
.detail-section {
  display: grid;
  gap: 10px;
}
.section-title {
  font-size: 12px;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.return-block code {
  display: inline-block;
  padding: 4px 8px;
  border-radius: 6px;
  background: rgba(88, 101, 242, 0.08);
  color: var(--text-secondary);
}
.summary-line {
  font-size: 13px;
  color: var(--text-secondary);
}
.node-card {
  border: 1px solid var(--border-frosted);
  border-radius: 12px;
  padding: 12px;
  display: grid;
  gap: 8px;
}
.node-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.node-action {
  font-size: 12px;
  color: var(--text-secondary);
}
.node-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12px;
  color: var(--text-secondary);
}
.node-io {
  display: grid;
  gap: 10px;
}
.io-block .label {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-bottom: 6px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid rgba(88, 101, 242, 0.2);
  color: var(--text-secondary);
  background: rgba(88, 101, 242, 0.08);
}
.chip.write {
  border-color: rgba(16, 185, 129, 0.3);
  background: rgba(16, 185, 129, 0.12);
}
.chip.system {
  border-color: rgba(148, 163, 184, 0.3);
  background: rgba(148, 163, 184, 0.12);
}
.code-block {
  padding: 6px 8px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.04);
  font-size: 12px;
  color: var(--text-secondary);
}
.dep-row {
  border: 1px solid var(--border-frosted);
  border-radius: 10px;
  padding: 10px;
  display: grid;
  gap: 6px;
}
.dep-row.highlight {
  border-color: rgba(88, 101, 242, 0.6);
  box-shadow: 0 0 0 2px rgba(88, 101, 242, 0.12);
}
.dep-title {
  font-weight: 600;
}
.dep-info {
  font-size: 12px;
  color: var(--text-secondary);
}
.dep-line {
  display: grid;
  gap: 6px;
  margin-bottom: 6px;
}
.dep-label {
  font-size: 11px;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.dep-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.dep-chip {
  border: 1px solid rgba(88, 101, 242, 0.2);
  background: rgba(88, 101, 242, 0.08);
  color: var(--text-secondary);
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 12px;
  cursor: pointer;
  transition: all var(--dur) var(--ease);
}
.dep-chip:hover {
  border-color: rgba(88, 101, 242, 0.5);
  color: var(--text-primary);
}
.dep-conditions {
  display: grid;
  gap: 6px;
}
.flow-section {
  display: grid;
  gap: 10px;
}
.flow-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.flow-hint {
  font-size: 12px;
  color: var(--text-secondary);
}
.flow-viewport {
  position: relative;
  border: 1px solid var(--border-frosted);
  border-radius: 12px;
  overflow: auto;
  min-height: 320px;
  background: var(--bg-surface);
}
.flow-canvas {
  position: relative;
}
.flow-edges {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.flow-node {
  position: absolute;
  width: 160px;
  height: 56px;
  border-radius: 12px;
  border: 1px solid var(--border-frosted);
  background: var(--bg-surface);
  box-shadow: 0 6px 12px rgba(30, 35, 48, 0.08);
  display: grid;
  gap: 4px;
  align-content: center;
  padding: 8px 10px;
  text-align: left;
  cursor: pointer;
  transition: all var(--dur) var(--ease);
  z-index: 2;
}
.flow-node.hover,
.flow-node.active {
  border-color: rgba(88, 101, 242, 0.6);
  box-shadow: 0 0 0 2px rgba(88, 101, 242, 0.12), 0 8px 16px rgba(30, 35, 48, 0.1);
}
.flow-node.focused {
  transform: scale(1.05);
}
.flow-title {
  font-weight: 700;
  font-size: 13px;
}
.flow-sub {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.flow-focus {
  position: absolute;
  inset: 0;
  background: rgba(11, 18, 32, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  z-index: 4;
}
.focus-card {
  width: min(640px, 90%);
  background: var(--bg-surface);
  border: 1px solid var(--border-frosted);
  border-radius: 16px;
  padding: 16px;
  box-shadow: 0 18px 36px rgba(30, 35, 48, 0.18);
  display: grid;
  gap: 12px;
}
.focus-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.focus-title {
  font-size: 16px;
  font-weight: 700;
}
.focus-sub {
  font-size: 12px;
  color: var(--text-secondary);
}
.focus-body {
  display: grid;
  grid-template-columns: 1fr 1.4fr 1fr;
  gap: 12px;
  align-items: center;
}
.focus-column {
  display: grid;
  gap: 6px;
}
.focus-label {
  font-size: 11px;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.focus-center {
  display: grid;
  justify-items: center;
}
.focus-node {
  border: 1px solid rgba(88, 101, 242, 0.3);
  background: rgba(88, 101, 242, 0.08);
  border-radius: 14px;
  padding: 12px 14px;
  text-align: center;
  display: grid;
  gap: 6px;
}
.focus-node-title {
  font-size: 15px;
  font-weight: 700;
}
.focus-meta {
  font-size: 12px;
  color: var(--text-secondary);
}
.focus-conditions {
  display: grid;
  gap: 6px;
}
.btn-mini {
  padding: 4px 10px;
  font-size: 12px;
}
.empty-panel {
  color: var(--text-secondary);
}
</style>
