import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

import type { FullConfig } from '@playwright/test'

import { runStack } from './support/stack'

/** Keep the container logs next to the other test artifacts, then remove the stack and volume. */
export default function globalTeardown(config: FullConfig) {
  const outputDir = config.projects[0]?.outputDir ?? 'test-results'
  mkdirSync(outputDir, { recursive: true })
  writeFileSync(path.join(outputDir, 'compose-logs.txt'), runStack('logs').output)

  const { ok, output } = runStack('down')
  console.log(output.trim() || 'Removed the isolated SpendWise stack and its volume.')
  if (!ok) throw new Error('Could not remove the isolated SpendWise stack; see the output above.')
}
