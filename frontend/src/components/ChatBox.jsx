import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import toast from 'react-hot-toast';
import { AlertTriangle, RotateCw } from 'lucide-react';
import ChatMessage from './ChatMessage';
import Composer from './Composer';
import EmptyChatState from './EmptyChatState';
import CyphrMark from './ui/CyphrMark';
import useMediaQuery from '../hooks/useMediaQuery';
import { errorDetail } from '../lib/errors';

const COPIED_MS = 2000;
const REDUCED_MOTION = '(prefers-reduced-motion: reduce)';

/** `composer-input` is the id the composer's own <label> already points at. */
const focusComposer = () => {
  requestAnimationFrame(() => document.getElementById('composer-input')?.focus());
};

/**
 * Placeholder for an answer that is still being generated. It repeats the
 * assistant identity row so the real answer replaces it without a layout shift.
 */
const PendingAnswer = () => (
  <div className="animate-rise-sm" role="status">
    <div className="mb-2 flex items-center gap-2">
      <CyphrMark size={17} />
      <span className="eyebrow">CYPHR</span>
    </div>
    <p className="flex items-center gap-2.5 text-sub text-ink-dim">
      <span className="flex items-center gap-1" aria-hidden="true">
        <span className="h-1.5 w-1.5 animate-dot-pulse rounded-pill bg-accent" />
        <span className="h-1.5 w-1.5 animate-dot-pulse rounded-pill bg-accent [animation-delay:150ms]" />
        <span className="h-1.5 w-1.5 animate-dot-pulse rounded-pill bg-accent [animation-delay:300ms]" />
      </span>
      Searching your documents…
    </p>
  </div>
);

/** Shaped like a real exchange, so arriving history does not jolt the layout. */
const HistorySkeleton = () => (
  <div className="space-y-6" aria-hidden="true">
    <div className="flex justify-end">
      <div className="skeleton h-12 w-3/5 rounded-lg" />
    </div>
    <div className="space-y-2.5">
      <div className="skeleton h-3 w-20" />
      <div className="skeleton h-3.5 w-full" />
      <div className="skeleton h-3.5 w-11/12" />
      <div className="skeleton h-3.5 w-3/5" />
    </div>
  </div>
);

/**
 * The conversation surface: history, the thread, and the composer.
 *
 * Two races are handled explicitly. The history fetch is AbortController-bound
 * so a fast sequence of chat switches can only ever paint the last one. And an
 * answer that arrives after the user has moved to a different conversation is
 * dropped rather than appended to the wrong thread — the reply is still stored
 * server-side, so it reappears the next time that conversation is opened.
 */
const ChatBox = ({
  activeChatId,
  onChatCreated,
  onChatRenamed,
  providerId,
  modelId,
  modelLabel,
  documentCount = 0,
  onOpenKnowledgeBase,
  onDocumentUploaded,
}) => {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [historyStatus, setHistoryStatus] = useState('idle');
  const [copiedIndex, setCopiedIndex] = useState(null);
  const [retryToken, setRetryToken] = useState(0);

  const endRef = useRef(null);
  const mountedRef = useRef(true);
  const inFlightRef = useRef(null);
  const skipNextFetchRef = useRef(null);
  const lastChatIdRef = useRef(activeChatId);
  const scrollModeRef = useRef('jump');
  const copyTimerRef = useRef(null);

  const reduceMotion = useMediaQuery(REDUCED_MOTION);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
    };
  }, []);

  useEffect(() => {
    const switched = lastChatIdRef.current !== activeChatId;
    lastChatIdRef.current = activeChatId;

    // The chat we just created already has both turns on screen; re-fetching
    // would only repaint the same thread and could race the pending append.
    if (skipNextFetchRef.current && skipNextFetchRef.current === activeChatId) {
      skipNextFetchRef.current = null;
      return undefined;
    }

    // Only a real switch abandons work in progress: anything still in flight
    // belongs to the conversation the user just left, so it must not land here.
    // Retrying a failed history load is *not* a switch — it must not disown an
    // answer that is still on its way to the thread being looked at.
    if (switched) {
      if (inFlightRef.current) inFlightRef.current.valid = false;
      scrollModeRef.current = 'jump';
      setIsLoading(false);
      setCopiedIndex(null);
    }

    if (!activeChatId) {
      setMessages([]);
      setHistoryStatus('idle');
      return undefined;
    }

    const controller = new AbortController();
    setHistoryStatus('loading');

    (async () => {
      try {
        const res = await axios.get(`/api/chats/${activeChatId}`, { signal: controller.signal });
        if (controller.signal.aborted || !mountedRef.current) return;
        const raw = Array.isArray(res.data?.messages) ? res.data.messages : [];
        setMessages(raw.map((m, i) => ({
          ...m,
          id: m.id || `${activeChatId}-${i}-${m.role}`,
        })));
        setHistoryStatus('idle');
      } catch {
        if (controller.signal.aborted || !mountedRef.current) return;
        setMessages([]);
        setHistoryStatus('error');
      }
    })();

    return () => controller.abort();
  }, [activeChatId, retryToken]);

  const handleSend = useCallback(async () => {
    const question = input.trim();
    if (!question || isLoading) return;

    const chatIdAtSend = activeChatId;
    const entry = { chatId: chatIdAtSend, valid: true };
    inFlightRef.current = entry;

    setMessages((prev) => [
      ...prev,
      {
        id: `user-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        role: 'user',
        content: question,
      },
    ]);
    setInput('');
    setIsLoading(true);
    scrollModeRef.current = reduceMotion ? 'jump' : 'smooth';

    try {
      const res = await axios.post('/chat', {
        message: question,
        chat_id: chatIdAtSend,
        provider: providerId || null,
        model: modelId || null,
      });

      const chatId = res.data?.chat_id || chatIdAtSend;
      const title = res.data?.title;

      // The conversation exists on the server either way, so the sidebar is
      // updated even when the answer itself is no longer wanted here. It only
      // steals focus back to this thread if the user never left it.
      if (!chatIdAtSend && chatId) {
        if (entry.valid) skipNextFetchRef.current = chatId;
        onChatCreated?.(chatId, title, { activate: entry.valid });
      } else if (chatId && title) {
        onChatRenamed?.(chatId, title);
      }

      if (!entry.valid || !mountedRef.current) return;
      setMessages((prev) => [
        ...prev,
        {
          id: `asst-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
          role: 'assistant',
          content: res.data?.response ?? '',
        },
      ]);
    } catch (error) {
      if (!entry.valid || !mountedRef.current) return;
      const detail = errorDetail(error, '');
      toast.error(detail || 'That question could not be answered.');
      setMessages((prev) => [
        ...prev,
        {
          id: `err-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
          role: 'assistant',
          error: true,
          content: detail || 'This request did not complete. Please try asking again.',
        },
      ]);
    } finally {
      if (inFlightRef.current === entry) inFlightRef.current = null;
      if (entry.valid && mountedRef.current) setIsLoading(false);
    }
  }, [input, isLoading, activeChatId, providerId, modelId, reduceMotion, onChatCreated, onChatRenamed]);

  const handleCopy = useCallback(async (index, content) => {
    if (!navigator.clipboard?.writeText) {
      toast.error('Copying is unavailable in this browser.');
      return;
    }
    try {
      await navigator.clipboard.writeText(content);
    } catch {
      toast.error('Copying was blocked by the browser.');
      return;
    }
    if (!mountedRef.current) return;
    setCopiedIndex(index);
    if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
    copyTimerRef.current = setTimeout(() => {
      if (mountedRef.current) setCopiedIndex(null);
    }, COPIED_MS);
  }, []);

  const handleSelectPrompt = useCallback((text) => {
    setInput(text);
    focusComposer();
  }, []);

  const retryHistory = useCallback(() => setRetryToken((token) => token + 1), []);

  // Follows the newest turn. Switching conversations jumps; new turns glide.
  useEffect(() => {
    const node = endRef.current;
    if (!node) return;
    node.scrollIntoView({
      behavior: scrollModeRef.current === 'smooth' ? 'smooth' : 'auto',
      block: 'end',
    });
  }, [messages, isLoading]);

  const showThread = messages.length > 0 || isLoading;

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div className="scroll-thin scroll-anchor min-h-0 flex-1 overflow-y-auto">
        {historyStatus === 'loading' && (
          <div className="mx-auto w-full max-w-thread px-4 py-6 sm:px-6">
            <HistorySkeleton />
            <span className="sr-only" role="status">
              Loading conversation
            </span>
          </div>
        )}

        {historyStatus === 'error' && !showThread && (
          <div className="mx-auto flex min-h-full w-full max-w-thread items-center justify-center px-4 py-6 sm:px-6">
            <div className="panel hairline relative w-full max-w-md p-comfortable text-center">
              <span className="mx-auto flex h-9 w-9 items-center justify-center rounded-md border border-danger/30 bg-danger/10 text-danger">
                <AlertTriangle className="h-4 w-4" aria-hidden="true" />
              </span>
              <p className="mt-3 text-sub font-medium text-ink">This conversation could not be loaded</p>
              <p className="mt-1.5 text-cap leading-relaxed text-ink-dim">
                Nothing was lost — the request for its history did not complete.
              </p>
              <button type="button" onClick={retryHistory} className="btn btn-secondary btn-sm mx-auto mt-normal">
                <RotateCw className="h-3.5 w-3.5" aria-hidden="true" />
                Try again
              </button>
            </div>
          </div>
        )}

        {historyStatus === 'idle' && !showThread && (
          <EmptyChatState
            documentCount={documentCount}
            onOpenKnowledgeBase={onOpenKnowledgeBase}
            onSelectPrompt={handleSelectPrompt}
          />
        )}

        {historyStatus !== 'loading' && showThread && (
          <div className="mx-auto w-full max-w-thread space-y-6 px-4 py-6 sm:px-6">
            {/* A failed history load must not swallow the exchange the user is
                having right now, so it steps aside and becomes a notice. */}
            {historyStatus === 'error' && (
              <div className="panel-flat flex flex-wrap items-center gap-x-3 gap-y-2 px-3.5 py-2.5" role="status">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden="true" />
                <p className="min-w-0 flex-1 text-cap leading-relaxed text-ink-dim">
                  Earlier messages could not be loaded. Nothing was lost — only the request for them failed.
                </p>
                <button type="button" onClick={retryHistory} className="btn btn-secondary btn-sm">
                  <RotateCw className="h-3.5 w-3.5" aria-hidden="true" />
                  Try again
                </button>
              </div>
            )}

            {messages.map((message, index) => (
              <ChatMessage
                key={message.id || `${message.role}-${message.content?.slice(0, 16)}`}
                index={index}
                role={message.role}
                content={message.content}
                error={Boolean(message.error)}
                copied={copiedIndex === index}
                onCopy={handleCopy}
              />
            ))}

            {isLoading && <PendingAnswer />}

            <div ref={endRef} className="h-px w-full" aria-hidden="true" />
          </div>
        )}
      </div>

      <Composer
        value={input}
        onChange={setInput}
        onSubmit={handleSend}
        isLoading={isLoading}
        documentCount={documentCount}
        modelLabel={modelLabel}
        onOpenKnowledgeBase={onOpenKnowledgeBase}
        onDocumentUploaded={onDocumentUploaded}
      />
    </div>
  );
};

export default ChatBox;
