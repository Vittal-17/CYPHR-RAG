import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import axios from 'axios';
import toast from 'react-hot-toast';

import Sidebar from '../components/Sidebar';

vi.mock('axios');
vi.mock('react-hot-toast');

describe('components/Sidebar', () => {
  const mockUser = { email: 'vittal@example.com', name: 'Vittal' };
  const mockChats = [
    { chat_id: 'chat-1', title: 'Q1 Financial Review', created_at: new Date().toISOString() },
    { chat_id: 'chat-2', title: 'Architecture RFC', created_at: new Date().toISOString() },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders chat list and identity in desktop expanded mode', () => {
    render(
      <Sidebar
        isDesktop
        collapsed={false}
        mobileOpen={false}
        user={mockUser}
        chats={mockChats}
        activeChatId="chat-1"
        documentCount={3}
      />
    );

    expect(screen.getByText('CYPHR')).toBeInTheDocument();
    expect(screen.getByText('Q1 Financial Review')).toBeInTheDocument();
    expect(screen.getByText('Architecture RFC')).toBeInTheDocument();
    expect(screen.getByText('vittal@example.com')).toBeInTheDocument();
  });

  it('selects conversation on click', async () => {
    const user = userEvent.setup();
    const onSelectChat = vi.fn();

    render(
      <Sidebar
        isDesktop
        collapsed={false}
        mobileOpen={false}
        user={mockUser}
        chats={mockChats}
        activeChatId="chat-1"
        onSelectChat={onSelectChat}
      />
    );

    await user.click(screen.getByText('Architecture RFC'));
    expect(onSelectChat).toHaveBeenCalledWith('chat-2');
  });

  it('allows renaming conversation and persists change', async () => {
    const user = userEvent.setup();
    const setChats = vi.fn();
    axios.patch.mockResolvedValueOnce({ data: { message: 'Renamed' } });

    render(
      <Sidebar
        isDesktop
        collapsed={false}
        mobileOpen={false}
        user={mockUser}
        chats={mockChats}
        setChats={setChats}
        activeChatId="chat-1"
      />
    );

    const renameBtn = screen.getByLabelText('Rename Q1 Financial Review');
    await user.click(renameBtn);

    const input = screen.getByDisplayValue('Q1 Financial Review');
    await user.clear(input);
    await user.type(input, 'Q1 Final Financials{enter}');

    await waitFor(() => {
      expect(axios.patch).toHaveBeenCalledWith('/api/chats/chat-1/title', {
        title: 'Q1 Final Financials',
      });
    });
  });

  it('deletes conversation with two-step confirmation dialog', async () => {
    const user = userEvent.setup();
    const setChats = vi.fn();
    axios.delete.mockResolvedValueOnce({ data: { message: 'Deleted' } });

    render(
      <Sidebar
        isDesktop
        collapsed={false}
        mobileOpen={false}
        user={mockUser}
        chats={mockChats}
        setChats={setChats}
        activeChatId="chat-1"
        onSelectChat={vi.fn()}
      />
    );

    const deleteBtn = screen.getByLabelText('Delete Q1 Financial Review');
    await user.click(deleteBtn);

    // Confirmation row appears with "Confirm deleting ..." and "Keep conversation"
    const confirmDeleteBtn = screen.getByLabelText('Confirm deleting Q1 Financial Review');
    await user.click(confirmDeleteBtn);

    await waitFor(() => {
      expect(axios.delete).toHaveBeenCalledWith('/api/chats/chat-1');
      expect(toast.success).toHaveBeenCalledWith('Conversation deleted');
    });
  });

  it('triggers logout when sign out button is clicked', async () => {
    const user = userEvent.setup();
    const onLogout = vi.fn();

    render(
      <Sidebar
        isDesktop
        collapsed={false}
        mobileOpen={false}
        user={mockUser}
        chats={mockChats}
        onLogout={onLogout}
      />
    );

    const logOutBtn = screen.getByLabelText('Log out');
    await user.click(logOutBtn);
    expect(onLogout).toHaveBeenCalled();
  });

  it('closes mobile drawer on backdrop click and on mobile close button', async () => {
    const user = userEvent.setup();
    const onCloseMobile = vi.fn();

    render(
      <Sidebar
        isDesktop={false}
        collapsed={false}
        mobileOpen
        onCloseMobile={onCloseMobile}
        user={mockUser}
        chats={mockChats}
      />
    );

    const closeButtons = screen.getAllByLabelText('Close navigation');
    expect(closeButtons.length).toBe(2);

    // Click backdrop
    await user.click(closeButtons[0]);
    expect(onCloseMobile).toHaveBeenCalledTimes(1);

    // Click close icon button inside header
    await user.click(closeButtons[1]);
    expect(onCloseMobile).toHaveBeenCalledTimes(2);
  });
});
