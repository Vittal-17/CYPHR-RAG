import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import axios from 'axios';
import toast from 'react-hot-toast';

import AuthScreen from '../components/AuthScreen';
import { getAccessToken, clearAccessToken } from '../utils/token';

vi.mock('axios');
vi.mock('react-hot-toast');
vi.mock('../utils/authDelay', () => ({
  withAuthDelay: (fn) => fn(),
}));

describe('components/AuthScreen', () => {
  beforeEach(() => {
    clearAccessToken();
    vi.clearAllMocks();
    window.history.replaceState({}, document.title, '/');
  });

  it('renders sign in screen by default with accessible inputs', () => {
    render(<AuthScreen onAuthSuccess={vi.fn()} />);

    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.getByLabelText(/Email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Password$/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Full name/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Confirm password/i)).not.toBeInTheDocument();
  });

  it('switches between Sign In and Register modes', async () => {
    const user = userEvent.setup();
    render(<AuthScreen onAuthSuccess={vi.fn()} />);

    const registerTab = screen.getByRole('button', { name: 'Register' });
    await user.click(registerTab);

    expect(screen.getByRole('heading', { name: 'Create your account' })).toBeInTheDocument();
    expect(screen.getByLabelText(/Full name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Confirm password/i)).toBeInTheDocument();

    const signInTab = screen.getByRole('button', { name: 'Sign in' });
    await user.click(signInTab);
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.queryByLabelText(/Full name/i)).not.toBeInTheDocument();
  });

  it('toggles password visibility between text and password types', async () => {
    const user = userEvent.setup();
    render(<AuthScreen onAuthSuccess={vi.fn()} />);

    const passwordInput = screen.getByLabelText(/^Password$/i);
    expect(passwordInput).toHaveAttribute('type', 'password');

    const toggleBtn = screen.getByLabelText('Show password');
    await user.click(toggleBtn);

    expect(passwordInput).toHaveAttribute('type', 'text');
    expect(screen.getByLabelText('Hide password')).toBeInTheDocument();

    await user.click(screen.getByLabelText('Hide password'));
    expect(passwordInput).toHaveAttribute('type', 'password');
  });

  it('validates email and password requirements on login', async () => {
    const user = userEvent.setup();
    const { container } = render(<AuthScreen onAuthSuccess={vi.fn()} />);
    const submitBtn = container.querySelector('button[type="submit"]');

    // Empty submission
    await user.click(submitBtn);

    expect(screen.getByText('That email address does not look complete.')).toBeInTheDocument();

    // Invalid email
    await user.type(screen.getByLabelText(/Email/i), 'not-an-email');
    await user.click(submitBtn);
    expect(screen.getByText('That email address does not look complete.')).toBeInTheDocument();

    // Missing password
    await user.clear(screen.getByLabelText(/Email/i));
    await user.type(screen.getByLabelText(/Email/i), 'user@example.com');
    await user.click(submitBtn);
    expect(screen.getByText('Enter your password.')).toBeInTheDocument();
  });

  it('validates fullname and password match on registration', async () => {
    const user = userEvent.setup();
    render(<AuthScreen onAuthSuccess={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: 'Register' }));
    const submitBtn = screen.getByRole('button', { name: 'Create account' });

    // Missing name
    await user.click(submitBtn);
    expect(screen.getByText('Enter the name you would like to be called by.')).toBeInTheDocument();

    await user.type(screen.getByLabelText(/Full name/i), 'Marie Curie');
    await user.type(screen.getByLabelText(/Email/i), 'marie@example.com');
    await user.type(screen.getByLabelText(/^Password$/i), 'secret123');
    await user.type(screen.getByLabelText(/Confirm password/i), 'differentpassword');
    await user.click(submitBtn);

    expect(screen.getByText('Those two passwords do not match.')).toBeInTheDocument();
  });

  it('executes login and sets token on success', async () => {
    const user = userEvent.setup();
    const onAuthSuccess = vi.fn();
    axios.post.mockResolvedValueOnce({
      data: {
        access_token: 'auth-jwt-token-999',
        user: { email: 'user@example.com', name: 'John Doe' },
      },
    });

    const { container } = render(<AuthScreen onAuthSuccess={onAuthSuccess} />);

    await user.type(screen.getByLabelText(/Email/i), 'user@example.com');
    await user.type(screen.getByLabelText(/^Password$/i), 'correct-password');
    await user.click(container.querySelector('button[type="submit"]'));

    await waitFor(() => {
      expect(axios.post).toHaveBeenCalledWith('/api/login', {
        email: 'user@example.com',
        password: 'correct-password',
      });
      expect(getAccessToken()).toBe('auth-jwt-token-999');
      expect(onAuthSuccess).toHaveBeenCalledWith({ email: 'user@example.com', name: 'John Doe' });
      expect(toast.success).toHaveBeenCalledWith('Welcome back');
    });
  });

  it('displays API error detail on authentication failure', async () => {
    const user = userEvent.setup();
    axios.post.mockRejectedValueOnce({
      response: { data: { detail: 'Account locked due to too many attempts' } },
    });

    const { container } = render(<AuthScreen onAuthSuccess={vi.fn()} />);

    await user.type(screen.getByLabelText(/Email/i), 'locked@example.com');
    await user.type(screen.getByLabelText(/^Password$/i), 'password');
    await user.click(container.querySelector('button[type="submit"]'));

    await waitFor(() => {
      expect(screen.getByText('Account locked due to too many attempts')).toBeInTheDocument();
    });
  });

  it('extracts error from URL query parameter on OAuth redirect failure', () => {
    window.history.replaceState({}, document.title, '/?error=OAuth+authentication+cancelled');
    render(<AuthScreen onAuthSuccess={vi.fn()} />);

    expect(screen.getByText('OAuth authentication cancelled')).toBeInTheDocument();
  });
});
