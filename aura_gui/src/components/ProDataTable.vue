<template>
  <div class="table-wrap" :style="{ maxHeight }">
    <table>
      <thead>
        <tr>
          <th
            v-for="column in columns"
            :key="column.key"
            :style="{ width: column.width || 'auto' }"
            :class="{ sortable: column.sortable }"
            @click="toggleSort(column)"
          >
            <span>{{ column.label }}</span>
            <span v-if="column.sortable" class="arrow">{{ sortIcon(column.key) }}</span>
          </th>
          <th v-if="$slots.actions" class="actions-col">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="(row, index) in viewRows"
          :key="getRowKey(row, index)"
          :class="{ clickable }"
          @click="clickable && $emit('row-click', row)"
        >
          <td v-for="column in columns" :key="column.key">
            <slot :name="`col-${column.key}`" :row="row" :value="row[column.key]">
              <span v-if="column.formatter">{{ column.formatter(row[column.key], row) }}</span>
              <span v-else>{{ row[column.key] }}</span>
            </slot>
          </td>
          <td v-if="$slots.actions">
            <slot name="actions" :row="row" />
          </td>
        </tr>
        <tr v-if="!viewRows.length">
          <td :colspan="columns.length + ($slots.actions ? 1 : 0)" class="empty-cell">暂无数据</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { computed, reactive } from 'vue'

const props = defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  rowKey: { type: [String, Function], default: '' },
  maxHeight: { type: String, default: '60vh' },
  sortDefault: { type: Object, default: () => ({ key: '', dir: 'asc' }) },
  clickable: { type: Boolean, default: true },
})

defineEmits(['row-click'])

const sort = reactive({ ...props.sortDefault })

function toggleSort(column) {
  if (!column.sortable) return
  if (sort.key !== column.key) {
    sort.key = column.key
    sort.dir = 'asc'
    return
  }
  sort.dir = sort.dir === 'asc' ? 'desc' : 'asc'
}

function sortIcon(key) {
  if (sort.key !== key) return '↕'
  return sort.dir === 'asc' ? '↑' : '↓'
}

function getRowKey(row, index) {
  if (typeof props.rowKey === 'function') return props.rowKey(row)
  if (typeof props.rowKey === 'string' && props.rowKey) return row[props.rowKey]
  return index
}

const viewRows = computed(() => {
  if (!sort.key) return props.rows
  const rows = [...props.rows]
  rows.sort((a, b) => {
    const av = a[sort.key]
    const bv = b[sort.key]
    if (av == null && bv == null) return 0
    if (av == null) return 1
    if (bv == null) return -1
    if (typeof av === 'number' && typeof bv === 'number') {
      return sort.dir === 'asc' ? av - bv : bv - av
    }
    return sort.dir === 'asc'
      ? String(av).localeCompare(String(bv))
      : String(bv).localeCompare(String(av))
  })
  return rows
})
</script>

<style scoped>
.table-wrap {
  overflow: auto;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--bg-surface);
}

thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--bg-surface-2);
}

th.sortable {
  cursor: pointer;
  user-select: none;
}

tr.clickable {
  cursor: pointer;
}

.actions-col {
  width: 1%;
  white-space: nowrap;
}

.arrow {
  margin-left: 4px;
  color: var(--text-muted);
  font-size: 11px;
}
</style>
