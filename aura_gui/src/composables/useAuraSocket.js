// src/composables/useAuraSocket.js

import { ref, onMounted, onUnmounted } from 'vue';

// 创建一个 ref 来存储 WebSocket 实例，以便在组件卸载时可以访问它
const socket = ref(null);

// 导出一个可复用的 composable 函数
export function useAuraSocket() {
  // 响应式状态，用于在UI上显示连接状态和最新消息
  const isConnected = ref(false);
  const lastMessage = ref(null);
  const error = ref(null);

  const connect = () => {
    // 如果已经有一个连接，或者正在连接，就不要重复创建
    if (socket.value && socket.value.readyState < 2) {
      return;
    }

    // 创建一个新的WebSocket连接
    // 这里的URL必须和你FastAPI服务器的WebSocket端点完全一致
    socket.value = new WebSocket('ws://127.0.0.1:8000/ws/events');

    socket.value.onopen = () => {
      console.log('WebSocket connection established.');
      isConnected.value = true;
      error.value = null;
    };

    socket.value.onmessage = (event) => {
      // 当收到消息时，解析JSON并更新lastMessage
      const data = JSON.parse(event.data);
      console.log('Received message:', data);
      lastMessage.value = data;
    };

    socket.value.onerror = (err) => {
      console.error('WebSocket error:', err);
      error.value = 'WebSocket connection failed.';
      isConnected.value = false;
    };

    socket.value.onclose = () => {
      console.log('WebSocket connection closed.');
      isConnected.value = false;
      // 可以在这里添加自动重连逻辑
    };
  };

  // onMounted钩子确保只在组件挂载后才尝试连接
  onMounted(connect);

  // onUnmounted钩子确保在组件销毁时关闭连接，防止内存泄漏
  onUnmounted(() => {
    if (socket.value) {
      socket.value.close();
    }
  });

  // 返回UI组件需要的所有状态和方法
  return {
    isConnected,
    lastMessage,
    error,
    connect, // 也可暴露connect方法，以便手动重连
  };
}
