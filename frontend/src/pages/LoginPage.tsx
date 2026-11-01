import { useState, type FormEvent } from 'react'
import { Link, useLocation } from 'react-router'

import { ApiError } from '../api/client'
import { useLogin } from '../api/queries'
import { AuthLayout } from '../components/AuthLayout'
import { Button, Field, FormError, linkClass } from '../components/ui'
import { describedBy, inputClass } from '../lib/styles'

type Errors = Partial<Record<'email' | 'password', string>>

export function LoginPage() {
  const login = useLogin()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<Errors>({})

  // Field-level problems come from the form or a 422; anything else (401, network) is general.
  const serverError = login.error instanceof ApiError ? login.error : null
  const fieldErrors: Errors = { ...serverError?.fieldErrors, ...errors }
  const formError = serverError && Object.keys(serverError.fieldErrors).length === 0 ? serverError.message : null

  function submit(event: FormEvent) {
    event.preventDefault()
    const found: Errors = {}
    if (!email.trim()) found.email = 'Enter your email.'
    if (!password) found.password = 'Enter your password.'
    setErrors(found)
    if (Object.keys(found).length > 0) return
    // On success the session is stored and the route guard continues to the requested page.
    login.mutate({ email: email.trim(), password })
  }

  return (
    <AuthLayout
      title="Log in"
      description="Welcome back to SpendWise."
      footer={
        <>
          No account yet?{' '}
          <Link to="/register" state={location.state} className={linkClass}>Create one</Link>
        </>
      }
    >
      <form onSubmit={submit} noValidate className="flex flex-col gap-4">
        <FormError message={formError} />
        <Field id="login-email" label="Email" error={fieldErrors.email}>
          <input
            id="login-email"
            type="email"
            autoComplete="email"
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-invalid={!!fieldErrors.email}
            aria-describedby={describedBy('login-email', fieldErrors.email)}
            className={inputClass(!!fieldErrors.email)}
          />
        </Field>
        <Field id="login-password" label="Password" error={fieldErrors.password}>
          <input
            id="login-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={!!fieldErrors.password}
            aria-describedby={describedBy('login-password', fieldErrors.password)}
            className={inputClass(!!fieldErrors.password)}
          />
        </Field>
        <Button type="submit" size="lg" disabled={login.isPending} className="mt-1 w-full">
          {login.isPending ? 'Logging in…' : 'Log in'}
        </Button>
      </form>
    </AuthLayout>
  )
}
