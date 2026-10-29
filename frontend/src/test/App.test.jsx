import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import axios from 'axios';
import toast from 'react-hot-toast';

import App from '../App';
import { getAccessToken, clearAccessToken } from '../utils/token';

vi.mock('axios');
vi.mock('react-hot-toast');
vi.mock('../utils/authDelay', () => ({
  withAuthDelay: vi.fn(async (action) => action()),
}));

describe('App Integration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearAccessToken();
    window.history.replaceState({}, document.title, '/');
  });

  it('renders loading overlay while booting and transitions to AuthScreen when unauthenticated', async () => {
    axios.get.mockImplementation((url) => {
      if (url === '/api/me') {
        return Promise.reject(new Error('Unauthenticated'));
      }
      return Promise.resolve({ data: {} });
    });

    render(<App />);

    // Initially displays auth loading overlay while booting
    expect(screen.getByRole('status', { hidden: true })).toBeInTheDocument();

    // After boot completes with 401/unauthenticated, shows AuthScreen
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    });

    expect(getAccessToken()).toBeNull();
  });

  it('extracts token from URL hash, cleans history, authenticates user, and renders workspace', async () => {
    window.location.hash = '#token=secret-oauth-hash-token&other=param';

    axios.get.mockImplementation((url) => {
      if (url === '/api/me') {
        return Promise.resolve({
          data: {
            user: { email: 'researcher@cyphr.ai', fullname: 'Dr. Ada Lovelace' },
          },
        });
      }
      if (url === '/api/chats') {
        return Promise.resolve({
          data: [{ chat_id: 'chat-alpha', title: 'Project Arch Review' }],
        });
      }
      if (url === '/api/documents') {
        return Promise.resolve({
          data: [{ filename: 'spec_v1.pdf' }],
        });
      }
      if (url === '/api/chats/chat-alpha') {
        return Promise.resolve({
          data: {
            chat_id: 'chat-alpha',
            messages: [{ id: 'm-1', role: 'user', content: 'What is the latency SLA?' }],
          },
        });
      }
      if (url === '/api/models') {
        return Promise.resolve({
          data: {
            providers: [
              {
                id: 'gemini',
                name: 'Google Gemini',
                models: [{ id: 'gemini-1.5-flash', name: 'Gemini 1.5 Flash' }],
              },
            ],
            default_provider: 'gemini',
            default_model: 'gemini-1.5-flash',
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('Dr. Ada Lovelace')).toBeInTheDocument();
      expect(screen.getAllByText('Project Arch Review').length).toBeGreaterThanOrEqual(1);
    });

    // Token extracted and saved
    expect(getAccessToken()).toBe('secret-oauth-hash-token');
    // Hash was sanitized (token parameter removed)
    expect(window.location.hash).not.toContain('token=secret-oauth-hash-token');
  });

  it('allows opening and closing the Knowledge Base modal from the header', async () => {
    const user = userEvent.setup();

    axios.get.mockImplementation((url) => {
      if (url === '/api/me') {
        return Promise.resolve({
          data: {
            user: { email: 'dev@cyphr.ai', fullname: 'Dev User' },
          },
        });
      }
      if (url === '/api/chats') {
        return Promise.resolve({
          data: [{ chat_id: 'chat-1', title: 'General QA' }],
        });
      }
      if (url === '/api/documents') {
        return Promise.resolve({
          data: [{ filename: 'guidelines.pdf' }],
        });
      }
      if (url === '/api/chats/chat-1') {
        return Promise.resolve({
          data: { chat_id: 'chat-1', messages: [] },
        });
      }
      if (url === '/api/models') {
        return Promise.resolve({
          data: {
            providers: [
              {
                id: 'gemini',
                name: 'Google Gemini',
                models: [{ id: 'gemini-1.5-flash', name: 'Gemini 1.5 Flash' }],
              },
            ],
            default_provider: 'gemini',
            default_model: 'gemini-1.5-flash',
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('Dev User')).toBeInTheDocument();
      expect(screen.getAllByText('General QA').length).toBeGreaterThanOrEqual(1);
    });

    // Open Knowledge Base
    const kbButtons = screen.getAllByLabelText('Open knowledge base, 1 document indexed');
    await user.click(kbButtons[0]);

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('guidelines')).toBeInTheDocument();

    // Close Knowledge Base modal
    const closeBtn = screen.getByLabelText('Close dialog');
    await user.click(closeBtn);

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  it('signs out the user when log out is clicked and redirects to auth screen', async () => {
    const user = userEvent.setup();

    axios.get.mockImplementation((url) => {
      if (url === '/api/me') {
        return Promise.resolve({
          data: {
            user: { email: 'logout@cyphr.ai', fullname: 'Log Out Tester' },
          },
        });
      }
      if (url === '/api/chats') {
        return Promise.resolve({ data: [] });
      }
      if (url === '/api/documents') {
        return Promise.resolve({ data: [] });
      }
      if (url === '/api/models') {
        return Promise.resolve({
          data: {
            providers: [],
            default_provider: '',
            default_model: '',
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    axios.post.mockImplementation((url) => {
      if (url === '/api/logout') {
        return Promise.resolve({ data: { message: 'Logged out' } });
      }
      return Promise.resolve({ data: {} });
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('Log Out Tester')).toBeInTheDocument();
    });

    const logoutBtn = screen.getByLabelText('Log out');
    await user.click(logoutBtn);

    await waitFor(() => {
      expect(axios.post).toHaveBeenCalledWith('/api/logout');
      expect(toast.success).toHaveBeenCalledWith('Signed out');
      expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    });

    expect(getAccessToken()).toBeNull();
  });
});
