import { QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'

import App from './App.tsx'
import { AppErrorFallback, ErrorBoundary } from './components/ErrorBoundary'
import { createQueryClient } from './lib/queryClient'
import { logError } from './lib/recovery'
import '@fontsource-variable/inter'
import './index.css'

const queryClient = createQueryClient()

createRoot(document.getElementById('root')!, {
  // React's default prints the whole error, whose message can carry figures from the page. The
  // boundaries log a safe summary themselves (lib/recovery.ts), so caught errors need nothing here.
  onCaughtError: () => {},
  onUncaughtError: (error) => logError('app', error),
}).render(
  <StrictMode>
    <ErrorBoundary name="app" fallback={() => <AppErrorFallback />}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
)
