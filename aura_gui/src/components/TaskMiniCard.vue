<!-- === src/components/TaskMiniCard.vue === -->
<template>
  <div class="task-card" v-tilt :class="{ starred }" @click="$emit('select')">
    <div class="color-stripe"></div>
    <div class="hd">
      <div class="title" v-if="titleHtml" v-html="titleHtml"></div>
      <div class="title" v-else>{{ title }}</div>
      <button
          class="star"
          :class="{ on: starred }"
          aria-label="toggle favorite"
          title="收藏/取消收藏"
          @click.stop="$emit('toggle-fav')"
      >
        {{ starred ? '★' : '☆' }}
      </button>
    </div>
    <div class="desc" v-if="descHtml" v-html="descHtml"></div>
    <div class="desc" v-else-if="description">{{ description }}</div>
    <div class="meta">
      <span class="pill">{{ plan }}</span>
      <span class="pill pill-blue" v-if="tag">{{ tag }}</span>
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: String, description: String, plan: String, tag: String,
  starred: Boolean, titleHtml: String, descHtml: String,
});
</script>

<style scoped>
.task-card {
  position: relative;
  backdrop-filter: blur(12px);
  background: var(--bg-surface);
  border: 1px solid var(--border-frosted);
  border-radius: var(--radius);
  padding: 12px 12px 12px 24px; /* 左侧留出彩带空间 */
  cursor: pointer;
  display: flex; flex-direction: column; gap: 6px;
  transition: all var(--dur) var(--ease);
  overflow: hidden;
}
.task-card:hover {
  transform: translateY(-2px);
  border-color: var(--primary-accent);
  box-shadow: var(--shadow-glow);
}
.color-stripe {
  position: absolute;
  left: 6px; top: 10px; bottom: 10px; width: 4px;
  border-radius: 4px;
  background: var(--border-frosted);
  transition: background var(--dur) var(--ease);
}
.task-card.starred .color-stripe {
  background: var(--primary-accent);
}

.hd { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.title { font-weight: 700; color: var(--text-primary); }
.desc { color: var(--text-secondary); font-size: 13px; min-height: 38px; overflow: hidden; }
.meta { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }

.star { transition: transform .15s var(--ease), color .15s var(--ease); }
.star:active { transform: scale(0.9); }
.star.on { color: #F59E0B; text-shadow: 0 0 8px rgba(245,158,11,.35); }


:deep(mark) {
  background: color-mix(in oklab, var(--primary-accent) 20%, transparent);
  padding: 0 2px; border-radius: 3px;
  color: var(--text-primary);
}
</style>
<!-- === END src/components/TaskMiniCard.vue === -->
