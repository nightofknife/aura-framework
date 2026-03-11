<template>
  <div class="filterbar">
    <input class="input" v-model="local.query" placeholder="搜索…" style="min-width:220px;" @input="debouncedEmitChange"/>
    <select class="select" v-if="statusOptions?.length" v-model="local.status" @change="emitChange">
      <option value="">全部状态</option>
      <option v-for="s in statusOptions" :key="s" :value="s">{{ s }}</option>
    </select>
    <select class="select" v-if="planOptions?.length" v-model="local.plan" @change="emitChange">
      <option value="">全部方案</option>
      <option v-for="p in planOptions" :key="p" :value="p">{{ p }}</option>
    </select>
    <slot/>
    <div style="flex:1"></div>
    <button class="btn btn-ghost" @click="onReset">重置</button>
  </div>
</template>

<script setup>
import { reactive, watch } from 'vue';
import { useDebounceFn } from '@vueuse/core';

const props = defineProps({
  modelValue: {type: Object, default: () => ({query: '', status: '', plan: ''})},
  statusOptions: {type: Array, default: () => []},
  planOptions: {type: Array, default: () => []},
});
const emit = defineEmits(['update:modelValue', 'reset']);
const local = reactive({...props.modelValue});

watch(() => props.modelValue, v => Object.assign(local, v));

function emitChange() {
  emit('update:modelValue', {...local});
}

// 防抖搜索输入（300ms）
const debouncedEmitChange = useDebounceFn(() => {
  emitChange();
}, 300);

function onReset() {
  Object.assign(local, {query: '', status: '', plan: ''});
  emitChange();
  emit('reset');
}
</script>
