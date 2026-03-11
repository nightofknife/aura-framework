// 轻量 Toast 管理（无外部依赖）
import {ref} from 'vue';

const toasts = ref([]);
let seed = 0;

function push({title, message = '', type = 'info', timeout = 3000, action} = {}) {
    const id = ++seed;
    const t = {id, title, message, type, timeout, createdAt: Date.now(), action};
    toasts.value.push(t);
    if (timeout > 0) {
        setTimeout(() => dismiss(id), timeout);
    }
    return id;
}

function dismiss(id) {
    toasts.value = toasts.value.filter(t => t.id !== id);
}

export function useToasts() {
    return {toasts, push, dismiss};
}
