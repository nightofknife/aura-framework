<template>
  <div class="page-shell">
    <div class="page-heading">
      <div class="heading-block">
        <span class="eyebrow">Workspace Lifecycle</span>
        <h1 class="page-title">Packages</h1>
        <p class="page-subtitle">Local package state, validation, enablement, and lock drift for the active workspace profile.</p>
      </div>
      <div class="heading-actions">
        <button class="btn btn-ghost" @click="lockPackages">Write Lock</button>
        <button class="btn btn-primary" @click="refresh">Refresh</button>
      </div>
    </div>

    <div v-if="message" class="notice">{{ message }}</div>
    <div v-if="errorMessage" class="notice-error">{{ errorMessage }}</div>

    <section class="upgrade-panel">
      <div>
        <span class="label">Local Upgrade Plan</span>
        <p>Dry-run a local directory, zip, or .aura package against the selected workspace package.</p>
      </div>
      <div class="upgrade-form">
        <select v-model="upgradePackageId" class="input">
          <option value="">Select package</option>
          <option v-for="pkg in packages" :key="pkg.id" :value="pkg.id">{{ pkg.id }}</option>
        </select>
        <input v-model="upgradeSource" class="input" placeholder="Local path to package directory, zip, or .aura" />
        <button class="btn btn-ghost" :disabled="tokenActionDisabled" :title="tokenGateTitle" @click="planUpgrade">Dry-run</button>
        <button v-if="localAdminEnabled" class="btn btn-primary" :disabled="adminActionDisabled" :title="adminGateTitle" @click="applyUpgrade">Apply</button>
      </div>
      <pre v-if="upgradeResult" class="json upgrade-result">{{ stringifyPretty(upgradeResult) }}</pre>
    </section>

    <section class="package-table">
      <div class="package-row package-row-head">
        <span>Package</span>
        <span>Version</span>
        <span>State</span>
        <span>Validation</span>
        <span>Lock</span>
        <span></span>
      </div>
      <div v-for="pkg in packages" :key="pkg.id" class="package-row">
        <div>
          <strong>{{ pkg.id }}</strong>
          <p>{{ pkg.source }}</p>
        </div>
        <code>{{ pkg.version }}</code>
        <span class="pill" :class="pkg.enabled ? 'pill-green' : 'pill-gray'">{{ pkg.enabled ? 'enabled' : 'disabled' }}</span>
        <span class="pill" :class="pkg.validationStatus === 'ok' ? 'pill-green' : 'pill-red'">{{ pkg.validationStatus }}</span>
        <span class="pill" :class="pkg.lockDrift ? 'pill-red' : 'pill-gray'">{{ pkg.lockDrift ? 'drift' : 'clean' }}</span>
        <button class="btn btn-ghost" :disabled="adminActionDisabled" :title="adminGateTitle" @click="togglePackage(pkg)">
          {{ pkg.enabled ? 'Disable' : 'Enable' }}
        </button>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { getGuiConfig } from '../config.js'
import {
  applyPackageUpgrade,
  listWorkspacePackages,
  planPackageUpgrade,
  setPackageEnabled,
  writePackageLock,
} from '../api/workspace.js'
import { useApiTokenStatus } from '../composables/useApiToken.js'

const cfg = getGuiConfig()
const { hasToken: apiTokenConfigured } = useApiTokenStatus()

const packages = ref([])
const message = ref('')
const errorMessage = ref('')
const upgradePackageId = ref('')
const upgradeSource = ref('')
const upgradeResult = ref(null)
const localAdminEnabled = !!cfg?.features?.local_admin
const tokenActionDisabled = computed(() => !apiTokenConfigured.value)
const adminActionDisabled = computed(() => !apiTokenConfigured.value || !localAdminEnabled)
const tokenGateTitle = computed(() =>
  apiTokenConfigured.value ? '' : 'Local API token required. Configure it in Settings.'
)
const adminGateTitle = computed(() => {
  if (!apiTokenConfigured.value) return 'Local API token required. Configure it in Settings.'
  if (!localAdminEnabled) return 'Local admin is disabled in GUI config.'
  return ''
})

async function refresh() {
  try {
    packages.value = await listWorkspacePackages()
    if (!upgradePackageId.value && packages.value.length) upgradePackageId.value = packages.value[0].id
    errorMessage.value = ''
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || error?.message || 'Unable to load packages.'
  }
}

async function planUpgrade() {
  if (!apiTokenConfigured.value) {
    errorMessage.value = 'Local API token required. Configure it in Settings.'
    return
  }
  if (!upgradePackageId.value || !upgradeSource.value) {
    errorMessage.value = 'Select a package and enter a local package path.'
    return
  }
  try {
    upgradeResult.value = await planPackageUpgrade(upgradePackageId.value, {
      source: upgradeSource.value,
    })
    errorMessage.value = ''
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || error?.message || 'Unable to create upgrade plan.'
  }
}

async function applyUpgrade() {
  if (adminActionDisabled.value) {
    errorMessage.value = adminGateTitle.value
    return
  }
  try {
    upgradeResult.value = await applyPackageUpgrade(upgradePackageId.value, {
      source: upgradeSource.value,
    })
    message.value = 'Package upgrade applied; run runtime reload before dispatching tasks from the package.'
    await refresh()
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || error?.message || 'Unable to apply upgrade.'
  }
}

function stringifyPretty(value) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

async function togglePackage(pkg) {
  if (adminActionDisabled.value) {
    errorMessage.value = adminGateTitle.value
    return
  }
  const action = pkg.enabled ? 'disable' : 'enable'
  try {
    const data = await setPackageEnabled(pkg.id, !pkg.enabled)
    message.value = data?.message || `Package ${action}d. Reload API to apply runtime changes.`
    await refresh()
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || error?.message || `Unable to ${action} package.`
  }
}

async function lockPackages() {
  if (adminActionDisabled.value) {
    errorMessage.value = adminGateTitle.value
    return
  }
  try {
    await writePackageLock()
    message.value = 'packages.lock.yaml updated.'
    await refresh()
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || error?.message || 'Unable to write lock.'
  }
}

onMounted(refresh)
</script>

<style scoped>
.package-table {
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(224, 214, 186, 0.1);
  background: rgba(35, 43, 46, 0.9);
}

.upgrade-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 16px;
  padding: 16px;
  border: 1px solid rgba(224, 214, 186, 0.1);
  background: rgba(35, 43, 46, 0.9);
}

.upgrade-panel p {
  margin: 6px 0 0;
  color: var(--text-soft);
}

.upgrade-form {
  display: grid;
  grid-template-columns: minmax(220px, 0.4fr) minmax(280px, 1fr) auto auto;
  gap: 10px;
  align-items: center;
}

.upgrade-result {
  max-height: 260px;
  overflow: auto;
}

.package-row {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) 90px 100px 110px 90px 110px;
  gap: 12px;
  align-items: center;
  padding: 12px 14px;
  border-top: 1px solid rgba(224, 214, 186, 0.08);
}

.package-row:first-child {
  border-top: 0;
}

.package-row-head {
  color: var(--text-soft);
  font-size: 12px;
  text-transform: uppercase;
}

.package-row strong {
  color: var(--paper-2);
}

.package-row p {
  margin: 4px 0 0;
  color: var(--text-soft);
  font-size: 12px;
}

.notice,
.notice-error {
  margin-bottom: 16px;
}

.notice {
  color: var(--paper);
}

.notice-error {
  color: #e8c1bb;
}
</style>
