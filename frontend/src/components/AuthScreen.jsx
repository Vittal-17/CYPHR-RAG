import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import axios from 'axios';
import toast from 'react-hot-toast';
import {
  AlertTriangle,
  Eye,
  EyeOff,
  Github,
  FileText,
  Loader2,
  Quote,
  ShieldCheck,
  SlidersHorizontal,
} from 'lucide-react';
import clsx from 'clsx';
import AuthLoadingOverlay from './AuthLoadingOverlay';
import Atmosphere from './ui/Atmosphere';
import CyphrMark from './ui/CyphrMark';
import { withAuthDelay } from '../utils/authDelay';
import { setAccessToken } from '../utils/token';
import { errorDetail } from '../lib/errors';

const EMPTY_FORM = { fullname: '', email: '', password: '', confirmPassword: '' };

/** Deliberately permissive — it only catches a plainly incomplete address. */
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** What the product does today. Nothing here promises unbuilt behaviour. */
const CAPABILITIES = [
  {
    icon: FileText,
    title: 'Your own documents',
    body: 'Add PDFs to a private knowledge base and question them in plain language.',
  },
  {
    icon: Quote,
    title: 'Answers with sources',
    body: 'Every response lists the files and pages the answer was drawn from.',
  },
  {
    icon: SlidersHorizontal,
    title: 'Your choice of model',
    body: 'Move between the configured providers and models whenever you like.',
  },
];

/**
 * Sign-in and registration, built from the same tokens and primitives as the
 * workspace so authentication reads as part of the product rather than a gate
 * in front of it.
 *
 * Validation mirrors only what the server actually enforces: a well-formed
 * address and fields that are present. The API sets no password length or
 * complexity rules, so this screen invents none — the single extra check is the
 * register-time confirmation, which exists purely to catch typing mistakes.
 */
const AuthScreen = ({ onAuthSuccess }) => {
  const [isLogin, setIsLogin] = useState(true);
  const [form, setForm] = useState(EMPTY_FORM);
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const mountedRef = useRef(true);
  const errorId = useId();

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const handleChange = useCallback((event) => {
    const { name, value } = event.target;
    setForm((prev) => ({ ...prev, [name]: value }));
    setError(null);
  }, []);

  // Switching intent clears the secrets: the two modes want different
  // autocomplete values, and a manager-filled password should not silently
  // become a new account's password.

  useEffect(() => {
    const searchParams = new URLSearchParams(window.location.search);
    let err = searchParams.get('error');
    if (!err && window.location.hash) {
      const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ''));
      err = hashParams.get('error');
    }
    if (err) {
      setError(err.replace(/\+/g, ' '));
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  }, []);

  const switchMode = useCallback((login) => {
    setIsLogin(login);
    setError(null);
    setShowPassword(false);
    setForm((prev) => ({ ...prev, password: '', confirmPassword: '' }));
  }, []);

  const authenticate = useCallback(
    async (request, success, fallback) => {
      setLoading(true);
      setError(null);
      try {
        const res = await withAuthDelay(request);
        const token = res.data?.access || res.data?.access_token;
        if (token) {
          setAccessToken(token);
        }
        toast.success(success);
        // App swaps this screen for the workspace, so no state is reset here.
        onAuthSuccess?.(res.data?.user);
      } catch (err) {
        if (!mountedRef.current) return;
        setError(errorDetail(err, fallback));
        setLoading(false);
      }
    },
    [onAuthSuccess]
  );

  const handleSubmit = (event) => {
    event.preventDefault();
    if (loading) return;

    const fullname = form.fullname.trim();
    const email = form.email.trim();

    if (!isLogin && !fullname) {
      setError('Enter the name you would like to be called by.');
      return;
    }
    if (!EMAIL_RE.test(email)) {
      setError('That email address does not look complete.');
      return;
    }
    if (!form.password) {
      setError('Enter your password.');
      return;
    }
    if (!isLogin && form.password !== form.confirmPassword) {
      setError('Those two passwords do not match.');
      return;
    }

    authenticate(
      () =>
        axios.post(
          isLogin ? '/api/login' : '/api/register',
          isLogin ? { email, password: form.password } : { fullname, email, password: form.password }
        ),
      isLogin ? 'Welcome back' : 'Account created',
      isLogin ? 'Those credentials were not accepted.' : 'That account could not be created.'
    );
  };
  const handleGithubLogin = () => {
    setLoading(true);
    setError(null);
    const backendUrl = axios.defaults.baseURL || '';
    const returnTo = encodeURIComponent(window.location.origin);
    window.location.href = `${backendUrl}/api/auth/github/login?return_to=${returnTo}`;
  };
  const handleGoogleLogin = () => {
    setLoading(true);
    setError(null);
    const backendUrl = axios.defaults.baseURL || '';
    const returnTo = encodeURIComponent(window.location.origin);
    window.location.href = `${backendUrl}/api/auth/google/login?return_to=${returnTo}`;
  };

  return (
    <>
      <Atmosphere />
      <AuthLoadingOverlay isVisible={loading} />

      <div className="scroll-thin relative z-content h-full w-full overflow-y-auto">
        <div className="grid min-h-full place-items-center px-4 py-large sm:px-6">
          <div className="grid w-full max-w-5xl items-center gap-large lg:grid-cols-[minmax(0,1fr)_25rem] lg:gap-section">
            {/* Below lg the card carries the identity on its own. */}
            <section className="hidden lg:block">
              <div className="flex items-center gap-3">
                <CyphrMark size={34} withGlow />
                <span className="text-head font-semibold tracking-[0.16em] text-ink">CYPHR</span>
              </div>

              <h1 className="mt-comfortable max-w-md text-display font-semibold leading-tight text-ink">
                Answers you can trace back to the page.
              </h1>
              <p className="mt-normal max-w-md text-body leading-relaxed text-ink-dim">
                CYPHR indexes the documents you give it, retrieves the passages that matter, and shows its
                working — so every answer can be checked against its source.
              </p>

              <ul className="mt-large max-w-md space-y-normal">
                {CAPABILITIES.map(({ icon: Icon, title, body }) => (
                  <li key={title} className="flex gap-3">
                    <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-md border border-line bg-surface-2/70 text-accent">
                      <Icon className="h-4 w-4" aria-hidden="true" />
                    </span>
                    <div className="min-w-0">
                      <p className="text-sub font-medium text-ink">{title}</p>
                      <p className="mt-0.5 text-cap leading-relaxed text-ink-dim">{body}</p>
                    </div>
                  </li>
                ))}
              </ul>

              <p className="mt-large flex items-center gap-2 text-cap text-ink-faint">
                <ShieldCheck className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                Documents and conversations stay scoped to your account.
              </p>
            </section>

            <div className="panel hairline relative mx-auto w-full max-w-md overflow-hidden p-comfortable sm:p-large">
              <div className="flex items-center gap-2.5 lg:hidden">
                <CyphrMark size={26} withGlow />
                <span className="text-sub font-semibold tracking-[0.16em] text-ink">CYPHR</span>
              </div>

              <h2 className="mt-normal text-title font-semibold text-ink lg:mt-0">
                {isLogin ? 'Sign in' : 'Create your account'}
              </h2>
              <p className="mt-1 text-cap leading-relaxed text-ink-dim">
                {isLogin
                  ? 'Pick up where you left off.'
                  : 'A workspace of your own, for your own documents.'}
              </p>

              <div
                className="mt-comfortable grid grid-cols-2 gap-1 rounded-lg border border-line-subtle bg-surface-1/70 p-1"
                role="group"
                aria-label="Choose sign in or register"
              >
                {[
                  { label: 'Sign in', login: true },
                  { label: 'Register', login: false },
                ].map(({ label, login }) => (
                  <button
                    key={label}
                    type="button"
                    onClick={() => switchMode(login)}
                    aria-pressed={isLogin === login}
                    className={clsx(
                      'rounded-md py-2 text-cap font-semibold transition-all duration-fast ease-standard',
                      isLogin === login
                        ? 'border border-accent/30 bg-accent/10 text-accent shadow-subtle'
                        : 'border border-transparent text-ink-dim hover:bg-surface-3/60 hover:text-ink hover:-translate-y-px'
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>

              <form onSubmit={handleSubmit} className="mt-comfortable space-y-normal" noValidate>
                {!isLogin && (
                  <div className="animate-rise-sm">
                    <label htmlFor="auth-fullname" className="eyebrow mb-1.5 block">
                      Full name
                    </label>
                    <input
                      id="auth-fullname"
                      name="fullname"
                      type="text"
                      required
                      autoComplete="name"
                      value={form.fullname}
                      onChange={handleChange}
                      disabled={loading}
                      placeholder="Ada Lovelace"
                      className="field disabled:opacity-60"
                    />
                  </div>
                )}

                <div>
                  <label htmlFor="auth-email" className="eyebrow mb-1.5 block">
                    Email
                  </label>
                  <input
                    id="auth-email"
                    name="email"
                    type="email"
                    required
                    autoComplete="email"
                    inputMode="email"
                    value={form.email}
                    onChange={handleChange}
                    disabled={loading}
                    placeholder="you@example.com"
                    className="field disabled:opacity-60"
                  />
                </div>

                <div>
                  <label htmlFor="auth-password" className="eyebrow mb-1.5 block">
                    Password
                  </label>
                  <div className="relative">
                    <input
                      id="auth-password"
                      name="password"
                      type={showPassword ? 'text' : 'password'}
                      required
                      autoComplete={isLogin ? 'current-password' : 'new-password'}
                      value={form.password}
                      onChange={handleChange}
                      disabled={loading}
                      className="field pr-11 disabled:opacity-60"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((visible) => !visible)}
                      aria-label={showPassword ? 'Hide password' : 'Show password'}
                      aria-pressed={showPassword}
                      className="icon-btn absolute right-1 top-1/2 h-8 w-8 -translate-y-1/2"
                    >
                      {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>

                {!isLogin && (
                  <div className="animate-rise-sm">
                    <label htmlFor="auth-confirm" className="eyebrow mb-1.5 block">
                      Confirm password
                    </label>
                    <input
                      id="auth-confirm"
                      name="confirmPassword"
                      type={showPassword ? 'text' : 'password'}
                      required
                      autoComplete="new-password"
                      value={form.confirmPassword}
                      onChange={handleChange}
                      disabled={loading}
                      className="field disabled:opacity-60"
                    />
                  </div>
                )}

                {/* Present in the DOM at all times so insertions are announced. */}
                <div aria-live="polite" id={errorId}>
                  {error && (
                    <p className="flex items-start gap-2 rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-cap leading-relaxed text-danger">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                      {error}
                    </p>
                  )}
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  aria-describedby={error ? errorId : undefined}
                  className="btn btn-primary btn-lg w-full"
                >
                  {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
                  {loading
                    ? isLogin
                      ? 'Signing in'
                      : 'Creating account'
                    : isLogin
                      ? 'Sign in'
                      : 'Create account'}
                </button>
              </form>

              <div className="mt-comfortable flex items-center gap-3">
                <span className="divider flex-1" aria-hidden="true" />
                <span className="eyebrow">or</span>
                <span className="divider flex-1" aria-hidden="true" />
              </div>

              <div
                className={clsx(
                  'mt-comfortable flex flex-col items-center gap-3',
                  loading && 'pointer-events-none opacity-55'
                )}
              >
                <button
                  type="button"
                  onClick={handleGoogleLogin}
                  className="flex w-[240px] items-center justify-center gap-3 rounded-md border border-line-strong bg-surface-0 py-[9px] text-sub font-medium text-ink shadow-sm transition-all hover:bg-surface-2 hover:-translate-y-px"
                >
                  <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
                    <path
                      d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                      fill="#4285F4"
                    />
                    <path
                      d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                      fill="#34A853"
                    />
                    <path
                      d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                      fill="#FBBC05"
                    />
                    <path
                      d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                      fill="#EA4335"
                    />
                    <path d="M1 1h22v22H1z" fill="none" />
                  </svg>
                  {isLogin ? 'Sign in with Google' : 'Sign up with Google'}
                </button>
                <button
                  type="button"
                  onClick={handleGithubLogin}
                  className="flex w-[240px] items-center justify-center gap-3 rounded-md border border-line-strong bg-surface-0 py-[9px] text-sub font-medium text-ink shadow-sm transition-all hover:bg-surface-2 hover:-translate-y-px"
                >
                  <Github className="h-4 w-4" />
                  {isLogin ? 'Sign in with GitHub' : 'Sign up with GitHub'}
                </button>
              </div>

              <div className="mt-comfortable border-t border-line-subtle pt-3 text-center">
                <a
                  href="/privacy"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-cap text-ink-faint hover:text-ink transition-colors underline decoration-line-subtle underline-offset-4"
                >
                  Privacy Policy
                </a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
};

export default AuthScreen;
