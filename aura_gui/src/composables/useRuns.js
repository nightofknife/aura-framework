import { ref, computed } from 'vue';

// 纯粹的数据存储，不再有复杂的 ingest 逻辑
const allRuns = ref([]); // 单一的、权威的运行列表

/**
 * 由外部（useStagingRunner）调用的函数，用于完全替换当前的运行数据。
 * @param {Array} newRuns - 从后端获取的新的、完整的运行列表。
 */
function setRuns(newRuns) {
    // 直接用后端权威数据替换本地数据
    allRuns.value = newRuns;
}

export function useRuns() {
    // 派生出 active 和 recent，就像以前一样，但数据源更可靠
    const activeRuns = computed(() =>
        allRuns.value
            .filter(r => r.status === 'running')
            .sort((a, b) => (b.startedAt || 0) - (a.startedAt || 0))
    );

    const recentRuns = computed(() =>
        allRuns.value
            .filter(r => r.status !== 'running')
            .sort((a, b) => (b.finishedAt || b.startedAt || 0) - (a.finishedAt || a.startedAt || 0))
            .slice(0, 200) // 保持最近200条的限制
    );

    // runsById 仍然可以提供，方便按ID查找
    const runsById = computed(() =>
        Object.fromEntries(allRuns.value.map(r => [r.cid || r.id, r]))
    );

    return {
        activeRuns,
        recentRuns,
        runsById,
        setRuns, // 暴露给 useStagingRunner 使用
    };
}
