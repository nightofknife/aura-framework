<template>
  <header class="tb" @dblclick="toggleMaximize">
    <div class="tb__left">
      <!-- ✅ 默认使用 /favicon.svg -->
      <img class="tb__logo" :src="logoSrc" alt="logo"/>
    </div>

    <!-- 右侧窗口控件（Win/Linux 自绘；macOS 通常使用系统交通灯） -->
    <div class="tb__right no-drag" v-if="isElectron && !isMac">
      <button class="tb-btn" @click.stop="minimize" aria-label="Minimize" title="Minimize">
        <svg viewBox="0 0 24 24" class="ico">
          <path d="M5 19h14"/>
        </svg>
      </button>
      <button class="tb-btn" @click.stop="toggleMaximize" :title="isMax ? 'Restore' : 'Maximize'"
              aria-label="Maximize / Restore">
        <svg v-if="!isMax" viewBox="0 0 24 24" class="ico">
          <path d="M7 7h10v10H7z"/>
        </svg>
        <svg v-else viewBox="0 0 24 24" class="ico">
          <path d="M8 10V8h8v8h-2"/>
          <path d="M8 8h8"/>
          <path d="M8 8v8h8"/>
        </svg>
      </button>
      <button class="tb-btn tb-btn--close" @click.stop="close" aria-label="Close" title="Close">
        <svg viewBox="0 0 24 24" class="ico">
          <path d="M6 6l12 12M18 6L6 18"/>
        </svg>
      </button>
    </div>
  </header>
</template>

<script setup>
import {ref, onMounted, onBeforeUnmount} from 'vue';

const props = defineProps({
  logo: {type: String, default: './favicon.svg'} // ✅ 改成 SVG
});
const logoSrc = props.logo;

const isElectron = !!window.AURA?.isElectron;
const isMac = (window.AURA?.platform || navigator.platform || '').toLowerCase().includes('mac');
const isMax = ref(false);

function minimize() {
  window.AURA?.windowControls?.minimize?.();
}

function toggleMaximize() {
  window.AURA?.windowControls?.toggleMaximize?.();
}

function close() {
  window.AURA?.windowControls?.close?.();
}

let off;
onMounted(() => {
  off = window.AURA?.windowControls?.onMaximizedChange?.((v) => {
    isMax.value = !!v;
  });
});
onBeforeUnmount(() => {
  if (typeof off === 'function') off();
});
</script>

<style scoped>
/* ========= 容器（对齐 aetherium-theme：与 .topbar/.sidebar 一致） ========= */
.tb {
  /* 与布局中的 topbar 高度一致 */
  height: 60px;
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: center;
  padding: 8px 16px;

  /* 主题变量：明暗色自动切换 */
  color: var(--text-primary);
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-frosted);

  /* 玻璃化与动效，保持和主题一致的强度 */
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  transition: color 120ms var(--ease);
  will-change: color;
  will-change: color;
  /* 窗口拖拽区 */
  -webkit-app-region: drag;

  /* 组件内自用变量：不同主题下的 hover 背景 */
  --tb-hover: rgba(128, 128, 128, 0.10); /* light 同侧边栏 item:hover */
  --tb-hover-strong: rgba(255, 255, 255, 0.90); /* 用于浅色按钮高亮（不用时也保留） */
}

:global(.theme-dark) .tb {
  /* 暗色主题时仅切换 hover 语义颜色，其余由变量接管 */
  --tb-hover: rgba(255, 255, 255, 0.08);
  --tb-hover-strong: rgba(255, 255, 255, 0.12);
}

/* ========= 左侧 LOGO ========= */
.tb__left {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.tb__logo {
  width: 18px;
  height: 18px;
  border-radius: 4px;
  box-shadow: 0 1px 2px rgba(30, 35, 48, 0.06);
}

/* ========= 右侧控件（与 .btn-ghost 的交互语义保持一致） ========= */
.tb__right {
  -webkit-app-region: no-drag;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

/* 基础：透明底，文字使用次级文本色；hover 加浅灰罩层（变量控制明暗） */
.tb-btn {
  -webkit-app-region: no-drag;
  width: 44px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  outline: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: background var(--dur) var(--ease),
  color var(--dur) var(--ease),
  box-shadow var(--dur) var(--ease),
  transform 80ms ease;
}

.tb-btn:hover {
  background: var(--tb-hover);
  color: var(--text-primary);
}

.tb-btn:active {
  transform: translateY(1px);
}

/* 关闭键：保持警示色语义（取主题 --error） */
.tb-btn--close:hover {
  background: color-mix(in srgb, var(--error) 92%, transparent);
  color: #fff;
}

/* 焦点可视化（与 .btn:focus-visible 一致的 glow） */
.tb-btn:focus-visible {
  box-shadow: 0 0 0 3px var(--glow-accent);
}

/* 图标风格：跟随文本色 */
.ico {
  width: 16px;
  height: 16px;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
  fill: none;
}

/* 适配窄屏：自动收紧 */
@media (max-width: 820px) {
  .tb {
    height: 56px;
    padding: 6px 12px;
  }

  .tb-btn {
    width: 40px;
    height: 32px;
  }
}

/* 明确不可拖拽区域（中部如放搜索/按钮时务必加此类） */
.no-drag {
  -webkit-app-region: no-drag;
}
</style>
