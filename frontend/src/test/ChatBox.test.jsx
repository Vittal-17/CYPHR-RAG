import React from 'react';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import axios from 'axios';
import toast from 'react-hot-toast';

import ChatBox from '../components/ChatBox';

vi.mock('axios');
vi.mock('react-hot-toast');

describe('components/ChatBox - Stable Message Identity & Lifecycles', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders empty chat state when activeChatId is null and messages are empty', () => {
    render(<ChatBox activeChatId={null} />);
    expect(screen.getByText('Ask your documents anything')).toBeInTheDocument();
  });

  it('loads chat history and assigns stable unique message IDs', async () => {
    const mockMessages = [
      { role: 'user', content: 'What was the Q2 revenue?' },
      { role: 'assistant', content: 'Q2 revenue was $5.2M.' },
    ];
    axios.get.mockResolvedValueOnce({
      data: { chat_id: 'chat-abc', messages: mockMessages },
    });

    render(<ChatBox activeChatId="chat-abc" />);

    await waitFor(() => {
      expect(screen.getByText('What was the Q2 revenue?')).toBeInTheDocument();
      expect(screen.getByText('Q2 revenue was $5.2M.')).toBeInTheDocument();
    });

    expect(axios.get).toHaveBeenCalledWith('/api/chats/chat-abc', expect.any(Object));
  });

  it('preserves message identity across rerenders and assigns stable IDs', async () => {
    const mockMessages = [
      { id: 'custom-server-id-1', role: 'user', content: 'Hello server' },
      { role: 'assistant', content: 'Hello back' },
    ];
    axios.get.mockResolvedValueOnce({
      data: { chat_id: 'chat-100', messages: mockMessages },
    });

    const { rerender } = render(
      <ChatBox activeChatId="chat-100" modelLabel="Gemini 1.5 Flash" />
    );

    await waitFor(() => {
      expect(screen.getByText('Hello server')).toBeInTheDocument();
    });

    rerender(<ChatBox activeChatId="chat-100" modelLabel="Groq Llama 3" />);

    expect(screen.getByText('Hello server')).toBeInTheDocument();
    expect(screen.getByText('Hello back')).toBeInTheDocument();
    expect(axios.get).toHaveBeenCalledTimes(1);
  });

  it('handles chat switching by resetting or loading new thread', async () => {
    axios.get.mockResolvedValueOnce({
      data: {
        chat_id: 'chat-1',
        messages: [{ role: 'user', content: 'First chat message' }],
      },
    });

    const { rerender } = render(<ChatBox activeChatId="chat-1" />);

    await waitFor(() => {
      expect(screen.getByText('First chat message')).toBeInTheDocument();
    });

    axios.get.mockResolvedValueOnce({
      data: {
        chat_id: 'chat-2',
        messages: [{ role: 'user', content: 'Second chat message' }],
      },
    });

    rerender(<ChatBox activeChatId="chat-2" />);

    await waitFor(() => {
      expect(screen.getByText('Second chat message')).toBeInTheDocument();
    });
    expect(screen.queryByText('First chat message')).not.toBeInTheDocument();
  });

  it('disowns in-flight answer when user switches conversation during generation', async () => {
    const user = userEvent.setup();
    let resolvePost;
    axios.post.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolvePost = resolve;
        })
    );

    const { rerender } = render(<ChatBox activeChatId="chat-initial" />);

    const textarea = screen.getByPlaceholderText(/Ask anything about your documents/i);
    await user.type(textarea, 'Question for initial chat');
    await user.click(screen.getByLabelText('Send message'));

    expect(screen.getByText('Question for initial chat')).toBeInTheDocument();
    expect(screen.getByText('Searching your documents…')).toBeInTheDocument();

    axios.get.mockResolvedValueOnce({
      data: { chat_id: 'chat-other', messages: [] },
    });
    rerender(<ChatBox activeChatId="chat-other" />);

    await act(async () => {
      resolvePost?.({
        data: { chat_id: 'chat-initial', response: 'Delayed answer to chat-initial' },
      });
    });

    expect(screen.queryByText('Delayed answer to chat-initial')).not.toBeInTheDocument();
  });

  it('sends question, updates messages with assistant reply, and calls onChatCreated if new chat', async () => {
    const user = userEvent.setup();
    const onChatCreated = vi.fn();
    axios.post.mockResolvedValueOnce({
      data: {
        chat_id: 'newly-created-chat-id',
        title: 'Summary of Quarterly Report',
        response: 'Here is your report summary.',
      },
    });

    render(
      <ChatBox
        activeChatId={null}
        onChatCreated={onChatCreated}
        providerId="gemini"
        modelId="gemini-1.5-flash"
      />
    );

    const textarea = screen.getByPlaceholderText(/Ask anything about your documents/i);
    await user.type(textarea, 'Summarize quarterly report');
    await user.click(screen.getByLabelText('Send message'));

    expect(screen.getByText('Summarize quarterly report')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('Here is your report summary.')).toBeInTheDocument();
    });

    expect(onChatCreated).toHaveBeenCalledWith(
      'newly-created-chat-id',
      'Summary of Quarterly Report',
      { activate: true }
    );
  });

  it('renders error turn and triggers toast when message generation fails', async () => {
    const user = userEvent.setup();
    axios.post.mockRejectedValueOnce({
      response: { data: { detail: 'Model rate limit exceeded. Please wait 60 seconds.' } },
    });

    render(<ChatBox activeChatId="chat-err" />);

    const textarea = screen.getByPlaceholderText(/Ask anything about your documents/i);
    await user.type(textarea, 'Query that will fail');
    await user.click(screen.getByLabelText('Send message'));

    await waitFor(() => {
      expect(
        screen.getByText('Model rate limit exceeded. Please wait 60 seconds.')
      ).toBeInTheDocument();
      expect(toast.error).toHaveBeenCalledWith('Model rate limit exceeded. Please wait 60 seconds.');
    });
  });

  it('shows retry button on history load failure and retries on click', async () => {
    const user = userEvent.setup();
    axios.get.mockRejectedValueOnce(new Error('Network failure'));

    render(<ChatBox activeChatId="chat-retry" />);

    await waitFor(() => {
      expect(screen.getByText(/This conversation could not be loaded/i)).toBeInTheDocument();
    });

    const retryBtn = screen.getByRole('button', { name: /Try again/i });
    expect(retryBtn).toBeInTheDocument();

    axios.get.mockResolvedValueOnce({
      data: { chat_id: 'chat-retry', messages: [{ role: 'user', content: 'Recovered message' }] },
    });

    await user.click(retryBtn);

    await waitFor(() => {
      expect(screen.getByText('Recovered message')).toBeInTheDocument();
    });
  });
});
