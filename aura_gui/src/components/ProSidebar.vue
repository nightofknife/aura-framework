<template>
  <aside class="sidebar">
    <nav class="nav">
      <div v-for="i in items" :key="i.key" class="item" :class="{active: i.key===active}"
           @click="$emit('navigate', i.key)">
        <span>{{ i.icon }}</span>
        <span>{{ i.label }}</span>
      </div>
    </nav>
  </aside>
</template>

<script setup>
defineProps({
  active: {type: String, default: 'dashboard'},
  items: {
    type: Array, default: () => [
      {key: 'dashboard', label: 'Dashboard', icon: '📊'},
      {key: 'plans', label: 'Plans', icon: '🗂️'},
      {key: 'runs', label: 'Runs', icon: '🏃'},
      {key: 'queue', label: 'Queue', icon: '🧺'},
      {key: 'logs', label: 'Logs', icon: '🧾'},
      {key: 'settings', label: 'Settings', icon: '⚙️'},
    ]
  }
});
defineEmits(['navigate']);
</script>
