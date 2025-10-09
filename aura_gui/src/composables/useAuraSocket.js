// src/composables/useAuraSocket.js
import { ref, onMounted, onUnmounted } from 'vue';

const socket = ref(null);

export function useAuraSocket() {
  const isConnected = ref(false);
  const lastMessage = ref(null);
  const error = ref(null);

  const connect = () => {
    if (socket.value && socket.value.readyState < 2) return;

    socket.value = new WebSocket('ws://127.0.0.1:8000/ws/events');

    socket.value.onopen = () => {
      isConnected.value = true;
      error.value = null;
    };

    socket.value.onmessage = (event) => {
      let msg = null;
      try {
        const raw = JSON.parse(event.data);
        // 你的后端发的是 {type:"event", payload:{ id,name,timestamp,channel,payload:{...} }}
        if (raw && raw.type === 'event' && raw.payload) {
          // 传给前端的就是“事件对象”本身（含 name / payload / timestamp）
          msg = raw.payload;
        } else {
          // 兜底：有些情况下可能直接就是事件对象
          msg = raw;
        }
      } catch (e) {
        msg = { name: 'unknown', payload: { message: String(event.data) } };
      }
      lastMessage.value = msg;
    };

    socket.value.onerror = (err) => {
      error.value = 'WebSocket connection failed.';
      isConnected.value = false;
    };

    socket.value.onclose = () => {
      isConnected.value = false;
    };
  };

  onMounted(connect);
  onUnmounted(() => { if (socket.value) socket.value.close(); });

  return { isConnected, lastMessage, error, connect };
}
