<template>
  <div class="filterbar">
    <input class="input" v-model="local.query" placeholder="Search…" style="min-width:220px;" @input="emitChange"/>
    <select class="select" v-if="statusOptions?.length" v-model="local.status" @change="emitChange">
      <option value="">All statuses</option>
      <option v-for="s in statusOptions" :key="s" :value="s">{{ s }}</option>
    </select>
    <select class="select" v-if="planOptions?.length" v-model="local.plan" @change="emitChange">
      <option value="">All plans</option>
      <option v-for="p in planOptions" :key="p" :value="p">{{ p }}</option>
    </select>
    <slot/>
    <div style="flex:1"></div>
    <button class="btn btn-ghost" @click="onReset">Reset</button>
  </div>
</template>

<script setup>
import {reactive, watch} from 'vue';

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

function onReset() {
  Object.assign(local, {query: '', status: '', plan: ''});
  emitChange();
  emit('reset');
}
</script>
