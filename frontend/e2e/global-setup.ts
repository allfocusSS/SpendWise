import { BASE_URL, runStack } from './support/stack'

/** Build and start the isolated stack once for the whole run (it cleans up itself on failure). */
export default function globalSetup() {
  console.log(`Starting the isolated SpendWise stack for end-to-end tests (${BASE_URL})…`)
  const { ok, output } = runStack('up')
  console.log(output.trim())
  if (!ok) throw new Error('The isolated SpendWise stack did not start; see the output above.')
}
