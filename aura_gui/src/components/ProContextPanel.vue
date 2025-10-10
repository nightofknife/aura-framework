<template>
  <Teleport to="body">
    <!-- 遮罩 -->
    <Transition name="overlay-fade">
      <div v-if="openLocal" class="overlay" @click="requestClose" />
    </Transition>

    <!-- 抽屉 -->
    <Transition name="drawer-slide" @after-leave="$emit('closed')">
      <section
          v-if="openLocal"
          class="drawer"
          :style="{ width }"
          role="dialog"
          aria-modal="true"
          :aria-label="title || 'Panel'"
          @keydown.esc.stop.prevent="requestClose"
      >
        <header class="drawer-head">
          <strong class="drawer-title">{{ title }}</strong>
          <button class="btn-close" aria-label="Close" @click="requestClose">✕</button>
        </header>
        <div class="drawer-body">
          <slot/>
        </div>
      </section>
    </Transition>
  </Teleport>
</template>

<script setup>
import {ref, watch, onMounted, onBeforeUnmount} from 'vue';

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '' },
  width: { type: String, default: '520px' },
});
const emit = defineEmits(['close', 'update:open', 'closed']);

const openLocal = ref(!!props.open);
watch(() => props.open, v => openLocal.value = v);

function requestClose(){
  openLocal.value = false;
  emit('update:open', false);
  emit('close');
}

// 防止背景滚动
function lockScroll(lock){
  const cls = 'body-lock-scroll';
  document.documentElement.classList.toggle(cls, !!lock);
  document.body.classList.toggle(cls, !!lock);
}
watch(openLocal, v => lockScroll(v));
onMounted(()=> lockScroll(openLocal.value));
onBeforeUnmount(()=> lockScroll(false));
</script>

<style scoped>
/* 遮罩 */
.overlay{
  position: fixed; inset: 0;
  background: rgba(15, 23, 42, .48); /* 深色半透明 */
  z-index: 1000;
}

/* 抽屉主体 */
.drawer{
  position: fixed; top: 0; right: 0; height: 100vh;
  background: #fff; box-shadow: -8px 0 24px rgba(0,0,0,.08);
  z-index: 1001; display:flex; flex-direction:column;
  will-change: transform;
}
.drawer-head{
  display:flex; align-items:center; justify-content:space-between;
  padding:12px 14px; border-bottom: 1px solid var(--border);
}
.drawer-title{ font-weight: 700; }
.btn-close{
  border:none; background:transparent; cursor:pointer; font-size:16px;
  width:28px; height:28px; line-height:28px; border-radius:8px;
}
.btn-close:hover{ background:#F3F4F6; }
.drawer-body{ padding:12px 14px; overflow:auto; }

/* 过渡动画 */
.overlay-fade-enter-active, .overlay-fade-leave-active{ transition: opacity .18s ease; }
.overlay-fade-enter-from, .overlay-fade-leave-to{ opacity: 0; }

.drawer-slide-enter-active, .drawer-slide-leave-active{ transition: transform .22s ease, opacity .22s ease; }
.drawer-slide-enter-from, .drawer-slide-leave-to{ transform: translateX(16px); opacity: 0; }

/* 背景滚动锁定 */
:global(html.body-lock-scroll, body.body-lock-scroll){
  overflow: hidden !important;
}
</style>
