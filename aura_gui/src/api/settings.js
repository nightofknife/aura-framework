import { getHealth } from './system.js'
import { getWorkspace, listWorkspacePackages } from './workspace.js'
import { getMigrationStatus, getPolicy, getReloadStatus, listDiagnostics } from './advanced.js'

export async function loadSettingsOverview() {
  const [system, workspace, packages, policy, diagnostics, reload, migrations] = await Promise.all([
    getHealth(),
    getWorkspace().catch(() => ({})),
    listWorkspacePackages().catch(() => []),
    getPolicy().catch(() => ({ profile: 'default' })),
    listDiagnostics().catch(() => []),
    getReloadStatus().catch((error) => ({ featureUnavailable: error?.featureUnavailable, status: 'unavailable' })),
    getMigrationStatus().catch(() => ({ status: 'unavailable' })),
  ])

  return {
    system,
    workspace,
    packages,
    policy,
    diagnostics: Array.isArray(diagnostics) ? diagnostics : [],
    reload,
    migrations,
  }
}
