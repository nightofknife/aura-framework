<template>
  <div class="panel validation-panel">
    <div class="panel-header"><strong>校验</strong></div>
    <div class="panel-body">
      <div v-if="!errors.length && !warnings.length" class="empty">暂无问题</div>
      <div v-if="errors.length" class="section">
        <div class="section-title">错误</div>
        <div v-for="(err, idx) in errors" :key="idx" class="issue error" @click="$emit('focus', err)">
          {{ err.message }}
        </div>
      </div>
      <div v-if="warnings.length" class="section">
        <div class="section-title">警告</div>
        <div v-for="(warn, idx) in warnings" :key="idx" class="issue warning" @click="$emit('focus', warn)">
          {{ warn.message }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  errors: { type: Array, default: () => [] },
  warnings: { type: Array, default: () => [] }
})

defineEmits(['focus'])
</script>

<style scoped>
.validation-panel .issue {
  padding: 6px 8px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 6px;
}
.issue.error { background: rgba(220, 38, 38, 0.1); color: var(--error); }
.issue.warning { background: rgba(14, 165, 233, 0.1); color: var(--info); }
.section-title { font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
.empty { color: var(--text-secondary); font-size: 13px; }
</style>
