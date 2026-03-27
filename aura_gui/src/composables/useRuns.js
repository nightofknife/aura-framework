import { computed, ref } from 'vue';

const allRuns = ref([]);

function normalizeRun(run) {
  const startedAt = run?.started_at ?? run?.startedAt ?? null;
  const finishedAt = run?.finished_at ?? run?.finishedAt ?? null;
  const taskName = run?.task_name ?? run?.task_ref ?? run?.task ?? null;
  const elapsed = run?.duration_ms ?? (
    startedAt && finishedAt
      ? ((finishedAt > 1e12 ? finishedAt : finishedAt * 1000) - (startedAt > 1e12 ? startedAt : startedAt * 1000))
      : null
  );

  return {
    ...run,
    task_name: taskName,
    task_ref: run?.task_ref ?? taskName,
    started_at: startedAt,
    finished_at: finishedAt,
    startedAt,
    finishedAt,
    elapsed,
  };
}

function setRuns(newRuns) {
  allRuns.value = Array.isArray(newRuns) ? newRuns.map(normalizeRun) : [];
}

export function useRuns() {
  const activeRuns = computed(() =>
    allRuns.value
      .filter((run) => run.status === 'running')
      .sort((a, b) => (b.startedAt || 0) - (a.startedAt || 0))
  );

  const recentRuns = computed(() =>
    allRuns.value
      .filter((run) => run.status !== 'running')
      .sort((a, b) => (b.finishedAt || b.startedAt || 0) - (a.finishedAt || a.startedAt || 0))
      .slice(0, 200)
  );

  const runsById = computed(() =>
    Object.fromEntries(allRuns.value.map((run) => [run.cid || run.id, run]))
  );

  return {
    activeRuns,
    recentRuns,
    runsById,
    setRuns,
  };
}
