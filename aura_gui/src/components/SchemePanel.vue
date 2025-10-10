<template>
  <div class="scheme">
    <button class="scheme-head" @click="toggle" :aria-expanded="openLocal ? 'true' : 'false'">
      <div class="title">
        <span class="chev" :class="{ open: openLocal }" aria-hidden="true">▸</span>
        <strong>{{ title }}</strong>
      </div>
      <div class="desc" v-if="description">{{ description }}</div>
      <div class="actions"><slot name="actions"/></div>
    </button>

    <!-- 高度过渡：使用 Transition + JS hooks 计算真实高度 -->
    <Transition
        @enter="onEnter"
        @after-enter="onAfterEnter"
        @leave="onLeave"
        @after-leave="onAfterLeave"
    >
      <div v-show="openLocal" ref="bodyEl" class="scheme-body">
        <slot/>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import {ref, watch, onBeforeUnmount} from 'vue';

const props = defineProps({
  title: String,
  description: String,
  open: { type: Boolean, default: false },
});
const emit = defineEmits(['update:open']);

const openLocal = ref(!!props.open);
watch(() => props.open, v => openLocal.value = v);

function toggle(){
  openLocal.value = !openLocal.value;
  emit('update:open', openLocal.value);
}

const bodyEl = ref(null);

// —— 折叠动画（计算高度）——
function onEnter(el){
  el.style.height = '0px';
  el.style.overflow = 'hidden';
  void el.offsetHeight; // 强制回流
  const h = bodyEl.value?.scrollHeight || el.scrollHeight || 0;
  el.style.transition = 'height .2s ease';
  el.style.height = h + 'px';
}
function onAfterEnter(el){
  el.style.height = '';
  el.style.overflow = '';
  el.style.transition = '';
}
function onLeave(el){
  const h = bodyEl.value?.scrollHeight || el.scrollHeight || 0;
  el.style.height = h + 'px';
  el.style.overflow = 'hidden';
  void el.offsetHeight;
  el.style.transition = 'height .2s ease';
  el.style.height = '0px';
}
function onAfterLeave(el){
  el.style.height = '';
  el.style.overflow = '';
  el.style.transition = '';
}

onBeforeUnmount(()=>{ /* no-op */ });
</script>

<style scoped>
.scheme{ border:1px solid var(--border); border-radius:12px; background:#fff; }
.scheme-head{
  width:100%; display:flex; gap:12px; align-items:center; justify-content:space-between;
  padding:10px 12px; cursor:pointer; background:transparent; border:none; text-align:left;
}
.title{ display:flex; gap:8px; align-items:center; }
.chev{
  width:14px; display:inline-block; color:var(--text-2);
  transition: transform .18s ease;
  transform: rotate(0deg);
}
.chev.open{ transform: rotate(90deg); }
.desc{ color:var(--text-3); font-size:12px; flex:1; margin-left:8px; }
.actions{ display:flex; gap:6px; }
.scheme-body{ padding:10px 12px; border-top:1px dashed var(--border); }
</style>
