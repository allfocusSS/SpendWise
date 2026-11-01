/**
 * The isolated Docker Compose stack the end-to-end tests run against.
 *
 * Starting and stopping it is delegated to the same Python tooling the integration tests use
 * (backend/integration/stack.py), so there is one implementation of "build, start, wait until
 * healthy, clean up" and one place that keeps test stacks apart from the developer's own.
 *
 * Settings (all optional):
 *   SPENDWISE_E2E_PORT     port on 127.0.0.1           (default 18100)
 *   SPENDWISE_E2E_PROJECT  Compose project name        (default spendwise-e2e)
 *   SPENDWISE_E2E_IMAGE    tag for the built app image (default spendwise:e2e)
 *   SPENDWISE_E2E_KEEP=1   leave the stack running afterwards, for debugging
 */
import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const E2E_PORT = Number(process.env.SPENDWISE_E2E_PORT ?? 18100)
export const BASE_URL = `http://127.0.0.1:${E2E_PORT}`

const BACKEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../backend')

export function runStack(command: 'up' | 'down' | 'logs'): { ok: boolean; output: string } {
  const result = spawnSync('uv', ['run', 'python', '-m', 'integration.stack', command], {
    cwd: BACKEND_DIR,
    encoding: 'utf8',
    env: {
      ...process.env,
      SPENDWISE_IT_PROJECT: process.env.SPENDWISE_E2E_PROJECT ?? 'spendwise-e2e',
      SPENDWISE_IT_PORT: String(E2E_PORT),
      SPENDWISE_IT_IMAGE: process.env.SPENDWISE_E2E_IMAGE ?? 'spendwise:e2e',
      SPENDWISE_IT_KEEP: process.env.SPENDWISE_E2E_KEEP ?? '',
    },
  })
  if (result.error) {
    return { ok: false, output: `Could not run uv (${result.error.message}). Install uv: https://docs.astral.sh/uv/` }
  }
  return { ok: result.status === 0, output: `${result.stdout}${result.stderr}` }
}
