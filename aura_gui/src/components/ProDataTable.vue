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
      <tr v-for="(row,idx) in viewRows" :key="rowKey ? row[rowKey] : idx" @click="$emit('row-click', row)"
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
import {computed, reactive} from 'vue';

const props = defineProps({
  columns: {type: Array, required: true}, // [{key,label,sortable,width,formatter}]
  rows: {type: Array, default: () => []},
  rowKey: {type: String, default: ''},
  maxHeight: {type: String, default: '60vh'},
  sortDefault: {type: Object, default: () => ({key: '', dir: 'asc'})},
});
defineEmits(['row-click']);

const sort = reactive({...props.sortDefault});

function toggleSort(c) {
  if (!c.sortable) return;
  if (sort.key !== c.key) {
    sort.key = c.key;
    sort.dir = 'asc';
  } else sort.dir = sort.dir === 'asc' ? 'desc' : 'asc';
}

const viewRows = computed(() => {
  if (!sort.key) return props.rows;
  const arr = [...props.rows];
  arr.sort((a, b) => {
    const av = a[sort.key], bv = b[sort.key];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === 'number' && typeof bv === 'number') return sort.dir === 'asc' ? av - bv : bv - av;
    return sort.dir === 'asc' ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
  });
  return arr;
});
</script>
