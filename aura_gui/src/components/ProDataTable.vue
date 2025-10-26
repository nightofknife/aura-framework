<!-- === src/components/ProDataTable.vue === -->
<template>
  <div class="table-wrap" :style="{maxHeight}">
    <table>
      <thead>
      <tr>
        <th v-for="c in columns" :key="c.key" :style="{width:c.width||'auto'}"
            :class="{sortable:c.sortable}" @click="toggleSort(c)">
          <span>{{ c.label }}</span>
          <span class="arrow" v-if="c.sortable">
            <span v-if="sort.key===c.key">{{ sort.dir === 'asc' ? '▲' : '▼' }}</span>
            <span v-else>▲▼</span>
          </span>
        </th>
        <th v-if="$slots.actions" style="width:1%; white-space:nowrap;">Actions</th>
      </tr>
      </thead>
      <tbody>
      <tr v-for="(row,idx) in viewRows" :key="getRowKey(row, idx)" @click="$emit('row-click', row)"
          style="cursor:pointer;">
        <td v-for="c in columns" :key="c.key">
          <slot :name="'col-'+c.key" :row="row" :value="row[c.key]">
            <span v-if="c.formatter">{{ c.formatter(row[c.key], row) }}</span>
            <span v-else>{{ row[c.key] }}</span>
          </slot>
        </td>
        <td v-if="$slots.actions">
          <slot name="actions" :row="row"/>
        </td>
      </tr>
      <tr v-if="!viewRows.length">
        <td :colspan="columns.length + ($slots.actions?1:0)" style="color:var(--text-3);">No data.</td>
      </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { computed, reactive } from 'vue';

const props = defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  rowKey: { type: [String, Function], default: '' }, // ✅ 修改：支持函数
  maxHeight: { type: String, default: '60vh' },
  sortDefault: { type: Object, default: () => ({key: '', dir: 'asc'}) },
});
defineEmits(['row-click']);

const sort = reactive({...props.sortDefault});

function toggleSort(c) {
  if (!c.sortable) return;
  if (sort.key !== c.key) {
    sort.key = c.key;
    sort.dir = 'asc';
  } else {
    sort.dir = sort.dir === 'asc' ? 'desc' : 'asc';
  }
}

// ✅ 新增：统一的 key 获取函数
function getRowKey(row, idx) {
  if (typeof props.rowKey === 'function') {
    return props.rowKey(row);
  }
  if (typeof props.rowKey === 'string' && props.rowKey) {
    return row[props.rowKey];
  }
  return idx;
}

const viewRows = computed(() => {
  if (!sort.key) return props.rows;
  const arr = [...props.rows];
  arr.sort((a, b) => {
    const av = a[sort.key];
    const bv = b[sort.key];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === 'number' && typeof bv === 'number') {
      return sort.dir === 'asc' ? av - bv : bv - av;
    }
    return sort.dir === 'asc'
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av));
  });
  return arr;
});
</script>

<style scoped>
.table-wrap {
  overflow-y: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
}
th, td {
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid var(--border-frosted);
  font-size: 13px;
}
thead th {
  position: sticky;
  top: 0;
  background: var(--bg-panel-header);
  backdrop-filter: blur(4px);
  font-size: 12px;
  color: var(--text-secondary);
}
th.sortable {
  cursor: pointer;
  user-select: none;
}
th.sortable:hover {
  background: rgba(0, 0, 0, 0.02);
}
.arrow {
  margin-left: 4px;
  font-size: 10px;
  opacity: 0.5;
}
</style>
