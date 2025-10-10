<template>
  <div class="card" @click="$emit('select')">
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
      <span class="pill pill-gray">{{ plan }}</span>
      <span class="pill pill-blue" v-if="tag">{{ tag }}</span>
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: String,
  description: String,
  plan: String,
  tag: String,
  starred: Boolean,
  /** 新增：可选的 HTML 高亮字段（包含 <mark>） */
  titleHtml: String,
  descHtml: String,
});
</script>

<style scoped>
.card{
  border:1px solid var(--border);
  border-radius:10px;
  padding:10px;
  background:#fff;
  cursor:pointer;
  display:flex;
  flex-direction:column;
  gap:6px;
  transition: box-shadow .18s ease, transform .12s ease;
}
.card:hover{ box-shadow:0 0 0 2px #e5e7ff; transform: translateY(-1px); }

.hd{ display:flex; align-items:center; justify-content:space-between; gap:8px; }
.title{ font-weight:700; }
.desc{ color:var(--text-3); font-size:12px; min-height:34px; overflow:hidden; }
.meta{ display:flex; gap:6px; align-items:center; flex-wrap:wrap; }

.star{
  background:transparent;
  border:none;
  cursor:pointer;
  font-size:18px;       /* 放大，保证可见性 */
  line-height:1;
  color:#9CA3AF;        /* 默认灰 */
  padding:2px;
}
.star.on{ color:#F59E0B; } /* 橙色高亮 */
.star:focus{ outline:2px solid #dbeafe; outline-offset:2px; }

/* 高亮 mark 的样式更柔和一些 */
:deep(mark){
  background: #FFF4CC;
  padding: 0 2px;
  border-radius: 3px;
}
</style>
