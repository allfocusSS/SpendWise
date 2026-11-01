import { Link, Route, Routes } from 'react-router'

import { Layout } from './components/Layout'
import { EmptyState, linkClass } from './components/ui'
import { AnalyticsPage } from './pages/AnalyticsPage'
import { CategoriesPage } from './pages/CategoriesPage'
import { DashboardPage } from './pages/DashboardPage'
import { TransactionsPage } from './pages/TransactionsPage'

function NotFound() {
  return (
    <div className="mx-auto mt-10 max-w-md">
      <EmptyState
        title="Page not found"
        description="The page you are looking for does not exist."
        action={<Link to="/" className={linkClass}>Go to the dashboard</Link>}
      />
    </div>
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
