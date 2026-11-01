import { useState, type FormEvent } from 'react'
import { Link, useLocation } from 'react-router'

import { ApiError } from '../api/client'
import { useSignup } from '../api/queries'
import { AuthLayout } from '../components/AuthLayout'
import { Button, Field, FormError, linkClass } from '../components/ui'
import { describedBy, inputClass } from '../lib/styles'

// Must match the backend (app/schemas/auth.py); the server checks again.
const PASSWORD_MIN = 12
const PASSWORD_MAX = 128

const PASSWORD_HINT = `At least ${PASSWORD_MIN} characters. There is no password reset yet, so keep it somewhere safe.`

type Errors = Partial<Record<'email' | 'password' | 'confirm', string>>

export function RegisterPage() {
  const signup = useSignup()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [errors, setErrors] = useState<Errors>({})

  const serverError = signup.error instanceof ApiError ? signup.error : null
  const fieldErrors: Errors = { ...serverError?.fieldErrors, ...errors }
  if (serverError?.status === 409) fieldErrors.email = serverError.message
  const formError =
    serverError && serverError.status !== 409 && Object.keys(serverError.fieldErrors).length === 0
      ? serverError.message
      : null

  function submit(event: FormEvent) {
    event.preventDefault()
    const found: Errors = {}
    if (!email.trim()) found.email = 'Enter your email.'
    if (password.length < PASSWORD_MIN) found.password = `Use at least ${PASSWORD_MIN} characters.`
    else if (password.length > PASSWORD_MAX) found.password = `Use at most ${PASSWORD_MAX} characters.`
    if (!found.password && confirm !== password) found.confirm = 'The passwords don’t match.'
    setErrors(found)
    if (Object.keys(found).length > 0) return
    signup.mutate({ email: email.trim(), password })
  }

  return (
    <AuthLayout
      title="Create your account"
      description="Your transactions and categories are private to your account."
      footer={
        <>
          Already have an account?{' '}
          <Link to="/login" state={location.state} className={linkClass}>Log in</Link>
        </>
      }
    >
      <form onSubmit={submit} noValidate className="flex flex-col gap-4">
        <FormError message={formError} />
        <Field id="register-email" label="Email" error={fieldErrors.email}>
          <input
            id="register-email"
            type="email"
            autoComplete="email"
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-invalid={!!fieldErrors.email}
            aria-describedby={describedBy('register-email', fieldErrors.email)}
            className={inputClass(!!fieldErrors.email)}
          />
        </Field>
        <Field
          id="register-password"
          label="Password"
          error={fieldErrors.password}
          hint={PASSWORD_HINT}
        >
          <input
            id="register-password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={!!fieldErrors.password}
            aria-describedby={describedBy('register-password', fieldErrors.password, PASSWORD_HINT)}
            className={inputClass(!!fieldErrors.password)}
          />
        </Field>
        <Field id="register-confirm" label="Confirm password" error={fieldErrors.confirm}>
          <input
            id="register-confirm"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            aria-invalid={!!fieldErrors.confirm}
            aria-describedby={describedBy('register-confirm', fieldErrors.confirm)}
            className={inputClass(!!fieldErrors.confirm)}
          />
        </Field>
        <Button type="submit" size="lg" disabled={signup.isPending} className="mt-1 w-full">
          {signup.isPending ? 'Creating account…' : 'Create account'}
        </Button>
      </form>
    </AuthLayout>
  )
}
