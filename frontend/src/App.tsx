import { Link, Route, Routes } from 'react-router'

import { Layout } from './components/Layout'
import { EmptyState } from './components/ui'
import { AnalyticsPage } from './pages/AnalyticsPage'
import { CategoriesPage } from './pages/CategoriesPage'
import { DashboardPage } from './pages/DashboardPage'
import { TransactionsPage } from './pages/TransactionsPage'

function NotFound() {
  return (
    <EmptyState
      title="Page not found"
      action={<Link to="/" className="text-sm font-medium text-indigo-700 hover:underline">Go to the dashboard</Link>}
    />
  )
}

function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="transactions" element={<TransactionsPage />} />
        <Route path="categories" element={<CategoriesPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}

export default App
