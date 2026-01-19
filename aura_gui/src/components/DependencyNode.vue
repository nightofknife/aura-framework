<template>
  <div class="tree-node" :style="{ marginLeft: (level * 20) + 'px' }">
    <div class="node-item">
      <span class="node-icon">📦</span>
      <strong class="node-name">{{ node.name }}</strong>
      <span v-if="node.version" class="node-version">v{{ node.version }}</span>
      <span v-if="node.required_version" class="node-required">(需要: {{ node.required_version }})</span>
      <span v-if="node.circular" class="node-warning">⚠️ 循环依赖</span>
      <span v-if="node.not_found" class="node-error">❌ 未找到</span>
      <span v-if="node.error" class="node-error">❌ {{ node.error }}</span>
    </div>
    <div v-if="node.dependencies && node.dependencies.length" class="node-children">
      <DependencyNode
        v-for="(dep, idx) in node.dependencies"
        :key="idx"
        :node="dep"
        :level="level + 1"
      />
    </div>
  </div>
</template>

<script setup>
defineProps({
  node: {
    type: Object,
    required: true
  },
  level: {
    type: Number,
    default: 0
  }
});
</script>

<style scoped>
.tree-node {
  margin-bottom: 8px;
}

.node-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 6px;
  border-left: 3px solid rgba(88, 101, 242, 0.3);
}

.node-icon {
  font-size: 16px;
}

.node-name {
  font-family: 'Consolas', monospace;
  color: var(--text-1);
  font-size: 13px;
}

.node-version {
  font-size: 11px;
  color: var(--text-3);
  font-family: 'Consolas', monospace;
}

.node-required {
  font-size: 11px;
  color: var(--text-3);
}

.node-warning {
  font-size: 11px;
  color: #fbbf24;
}

.node-error {
  font-size: 11px;
  color: #f87171;
}

.node-children {
  margin-top: 4px;
}
</style>
