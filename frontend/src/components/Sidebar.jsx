import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import toast from 'react-hot-toast';
import clsx from 'clsx';
import {
  Check,
  Database,
  Loader2,
  LogOut,
  MessageSquare,
  MessagesSquare,
  PanelLeft,
  PanelLeftClose,
  Pencil,
  Plus,
  Trash2,
  X,
} from 'lucide-react';
import CyphrMark from './ui/CyphrMark';
import ChatRow from './ChatRow';
import { groupChatsByRecency, pluralize } from '../lib/format';
import { errorDetail } from '../lib/errors';
import { focusablesIn } from '../lib/focus';

/**
 * Navigation rail for the workspace: identity, primary actions, and the
 * conversation history grouped by recency.
 *
 * Three presentations, one component (and therefore one set of hooks — this
 * component previously returned before `useEffect`, which broke the rules of
 * hooks):
 *   - desktop expanded  → 280px panel in normal flow
 *   - desktop collapsed → 68px icon rail with tooltips
 *   - mobile            → off-canvas drawer over the app
 */
const Sidebar = ({
  isDesktop,
  collapsed,
  mobileOpen,
  onCloseMobile,
  onToggleCollapse,
  user,
  onLogout,
  chats,
  setChats,
  activeChatId,
  onSelectChat,
  onOpenKnowledgeBase,
  documentCount = 0,
}) => {
  const [editingChatId, setEditingChatId] = useState(null);
  const [pendingDeleteId, setPendingDeleteId] = useState(null);
  const [deletingChatId, setDeletingChatId] = useState(null);
  const [creating, setCreating] = useState(false);
  const asideRef = useRef(null);
  const closeRef = useRef(null);
  const restoreFocusRef = useRef(null);

  const isRail = isDesktop && collapsed;
  const isDrawer = !isDesktop;
  const drawerOpen = isDrawer && mobileOpen;
  const groups = useMemo(() => groupChatsByRecency(chats), [chats]);

  useEffect(() => {
    if (!editingChatId) return;
  }, [editingChatId]);

  // The drawer covers the app behind a scrim, so it takes focus while it is
  // open and hands it back to whatever opened it on the way out.
  useEffect(() => {
    if (!drawerOpen) return undefined;
    restoreFocusRef.current = document.activeElement;
    const frame = requestAnimationFrame(() => closeRef.current?.focus({ preventScroll: true }));
    return () => {
      cancelAnimationFrame(frame);
      const previous = restoreFocusRef.current;
      restoreFocusRef.current = null;
      if (previous && typeof previous.focus === 'function' && document.contains(previous)) {
        previous.focus({ preventScroll: true });
      }
    };
  }, [drawerOpen]);

  // Tab must not wander out of the drawer into the content it is covering.
  const handleDrawerKeyDown = useCallback(
    (event) => {
      if (event.key !== 'Tab' || !drawerOpen) return;
      const items = focusablesIn(asideRef.current);
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    },
    [drawerOpen]
  );

  // Collapsing to the rail or closing the drawer must never leave a row stuck
  // mid-rename or mid-confirmation.
  useEffect(() => {
    if (isRail || (!isDesktop && !mobileOpen)) {
      setEditingChatId(null);
      setPendingDeleteId(null);
    }
  }, [isRail, isDesktop, mobileOpen]);

  // A destructive confirmation should not linger indefinitely.
  useEffect(() => {
    if (!pendingDeleteId) return undefined;
    const timer = setTimeout(() => setPendingDeleteId(null), 5000);
    return () => clearTimeout(timer);
  }, [pendingDeleteId]);

  const handleNewChat = useCallback(async () => {
    if (creating) return;
    setCreating(true);
    try {
      const res = await axios.post('/api/chats/new');
      setChats((prev) => [res.data, ...prev]);
      onSelectChat(res.data.chat_id);
    } catch (error) {
      toast.error(errorDetail(error, 'Could not start a new conversation.'));
    } finally {
      setCreating(false);
    }
  }, [creating, onSelectChat, setChats]);

  const handleDelete = useCallback(
    async (chatId) => {
      setPendingDeleteId(null);
      setDeletingChatId(chatId);
      try {
        await axios.delete(`/api/chats/${chatId}`);
        setChats((prev) => prev.filter((chat) => chat.chat_id !== chatId));
        if (activeChatId === chatId) onSelectChat(null);
        toast.success('Conversation deleted');
      } catch (error) {
        toast.error(errorDetail(error, 'Could not delete that conversation.'));
      } finally {
        setDeletingChatId(null);
      }
    },
    [activeChatId, onSelectChat, setChats]
  );

  const saveTitle = useCallback(
    async (chatId, newTitle) => {
      const title = newTitle.trim();
      setEditingChatId(null);
      const current = chats.find((chat) => chat.chat_id === chatId);
      if (!title || title === current?.title) return;
      try {
        await axios.patch(`/api/chats/${chatId}/title`, { title });
        setChats((prev) => prev.map((chat) => (chat.chat_id === chatId ? { ...chat, title } : chat)));
      } catch (error) {
        toast.error(errorDetail(error, 'Could not rename that conversation.'));
      }
    },
    [chats, setChats]
  );

  const startEditing = useCallback((chatId) => {
    setPendingDeleteId(null);
    setEditingChatId(chatId);
  }, []);

  const initial = (user?.fullname || user?.email || '?').trim().charAt(0).toUpperCase() || '?';

  const shell = clsx(
    'z-drawer flex h-full shrink-0 flex-col border-r border-line bg-surface-1/80 backdrop-blur-xl',
    isDesktop
      ? ['relative transition-[width] duration-emphasized ease-standard', isRail ? 'w-rail' : 'w-sidebar']
      : [
          'fixed inset-y-0 left-0 w-sidebar max-w-[85vw] shadow-panel',
          'transition-[transform,visibility] duration-emphasized ease-exit',
          mobileOpen ? 'visible translate-x-0' : 'invisible -translate-x-full',
        ]
  );

  return (
    <>
      {!isDesktop && (
        <button
          type="button"
          aria-label="Close navigation"
          tabIndex={mobileOpen ? 0 : -1}
          onClick={onCloseMobile}
          className={clsx(
            'fixed inset-0 z-chrome cursor-default bg-surface-0/70 backdrop-blur-xs transition-opacity duration-normal ease-standard',
            mobileOpen ? 'opacity-100' : 'pointer-events-none opacity-0'
          )}
        />
      )}

      <aside
        ref={asideRef}
        className={shell}
        aria-label="Workspace navigation"
        onKeyDown={isDrawer ? handleDrawerKeyDown : undefined}
      >

        {/* Identity */}
        <div
          className={clsx(
            'flex h-14 shrink-0 items-center gap-2.5 border-b border-line-subtle',
            isRail ? 'justify-center px-0' : 'px-3'
          )}
        >
          <CyphrMark size={isRail ? 28 : 26} withGlow />
          {!isRail && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sub font-semibold tracking-tight text-ink">CYPHR</p>
              <p className="eyebrow truncate">Knowledge Workspace</p>
            </div>
          )}
          {isDesktop
            ? !isRail && (
                <button
                  type="button"
                  onClick={onToggleCollapse}
                  className="icon-btn tip shrink-0"
                  data-tip="Collapse"
                  aria-label="Collapse sidebar"
                >
                  <PanelLeftClose className="h-4 w-4" />
                </button>
              )
            : (
                <button
                  ref={closeRef}
                  type="button"
                  onClick={onCloseMobile}
                  className="icon-btn shrink-0"
                  aria-label="Close navigation"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
        </div>

        {/* Primary actions */}
        <div className={clsx('shrink-0', isRail ? 'space-y-1.5 px-2 py-3' : 'space-y-2 px-3 py-3')}>
          {isRail ? (
            <>
              <button
                type="button"
                onClick={handleNewChat}
                disabled={creating}
                className="icon-btn icon-btn-primary tip mx-auto"
                data-tip="New chat"
                aria-label="New chat"
              >
                {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              </button>
              <button
                type="button"
                onClick={onOpenKnowledgeBase}
                className="icon-btn tip mx-auto"
                data-tip={`Knowledge base · ${pluralize(documentCount, 'document')}`}
                aria-label="Open knowledge base"
              >
                <Database className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={onToggleCollapse}
                className="icon-btn tip mx-auto"
                data-tip="Expand"
                aria-label="Expand sidebar"
              >
                <PanelLeft className="h-4 w-4" />
              </button>
            </>
          ) : (
            <>
              <button type="button" onClick={handleNewChat} disabled={creating} className="btn btn-primary w-full">
                {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                {creating ? 'Starting...' : 'New chat'}
              </button>
              <button
                type="button"
                onClick={onOpenKnowledgeBase}
                className="btn btn-secondary w-full justify-between"
              >
                <span className="flex items-center gap-2">
                  <Database className="h-4 w-4 text-accent" />
                  Knowledge base
                </span>
                <span className="chip chip-accent tabular">{documentCount}</span>
              </button>
            </>
          )}
        </div>

        {/* Conversations */}
        <nav className="scroll-thin min-h-0 flex-1 overflow-y-auto pb-2" aria-label="Conversations">
          {isRail ? (
            chats.length === 0 ? (
              <div
                className="mx-auto grid h-9 w-9 place-items-center rounded-md border border-dashed border-line text-ink-faint"
                title="No conversations yet"
              >
                <MessagesSquare className="h-4 w-4" aria-hidden="true" />
                <span className="sr-only">No conversations yet</span>
              </div>
            ) : (
              <ul className="space-y-1 px-2">
                {chats.map((chat) => {
                  const isActive = chat.chat_id === activeChatId;
                  // This list scrolls, and a scroll container clips both axes —
                  // so the rail's rows use the native tooltip, which no
                  // ancestor overflow can cut off.
                  return (
                    <li key={chat.chat_id}>
                      <button
                        type="button"
                        onClick={() => onSelectChat(chat.chat_id)}
                        className={clsx(
                          'icon-btn mx-auto',
                          isActive && 'bg-surface-3 text-accent ring-1 ring-line-strong'
                        )}
                        title={chat.title || 'Untitled'}
                        aria-current={isActive ? 'true' : undefined}
                        aria-label={chat.title || 'Untitled conversation'}
                      >
                        <MessageSquare className="h-4 w-4" />
                      </button>
                    </li>
                  );
                })}
              </ul>
            )
          ) : chats.length === 0 ? (
            <div className="mx-3 rounded-lg border border-dashed border-line bg-surface-2/40 px-3 py-7 text-center">
              <MessagesSquare className="mx-auto mb-2 h-5 w-5 text-ink-faint" />
              <p className="text-cap font-medium text-ink-dim">No conversations yet</p>
              <p className="mt-1 text-label leading-relaxed text-ink-faint">
                Ask a question to start your first thread.
              </p>
            </div>
          ) : (
            groups.map((group) => (
              <section key={group.id} className="pb-1">
                <h3 className="eyebrow sticky top-0 z-10 bg-surface-1/95 px-3.5 py-1.5 backdrop-blur-sm">
                  {group.label}
                </h3>
                <ul className="space-y-px px-2">
                                    {group.chats.map((chat) => (
                    <ChatRow
                      key={chat.chat_id}
                      chat={chat}
                      isActive={chat.chat_id === activeChatId}
                      isEditing={editingChatId === chat.chat_id}
                      isConfirming={pendingDeleteId === chat.chat_id}
                      saveTitle={saveTitle}
                      setEditingChatId={setEditingChatId}
                      onSelectChat={onSelectChat}
                      handleDelete={handleDelete}
                      deletingChatId={deletingChatId}
                      setPendingDeleteId={setPendingDeleteId}
                      startEditing={startEditing}
                    />
                  ))}
                </ul>
              </section>
            ))
          )}
        </nav>

        {/* Account */}
        <div
          className={clsx(
            'shrink-0 border-t border-line-subtle bg-surface-2/40',
            isRail ? 'px-2 py-2.5' : 'p-2'
          )}
        >
          {isRail ? (
            <div className="flex flex-col items-center gap-1.5">
              <span
                className="tip grid h-8 w-8 place-items-center rounded-full text-cap font-bold text-ink-inverse"
                style={{ backgroundImage: 'linear-gradient(135deg, rgb(var(--c-accent-soft)), rgb(var(--c-azure)))' }}
                data-tip={user?.email || 'Signed in'}
              >
                {initial}
              </span>
              <button
                type="button"
                onClick={onLogout}
                className="icon-btn icon-btn-danger tip"
                data-tip="Log out"
                aria-label="Log out"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 transition-colors duration-fast hover:bg-surface-3/60">
              <span
                className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-cap font-bold text-ink-inverse"
                style={{ backgroundImage: 'linear-gradient(135deg, rgb(var(--c-accent-soft)), rgb(var(--c-azure)))' }}
              >
                {initial}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-cap font-semibold text-ink">{user?.fullname || 'Signed in'}</p>
                <p className="truncate text-label text-ink-faint">{user?.email}</p>
              </div>
              <button
                type="button"
                onClick={onLogout}
                className="icon-btn icon-btn-danger tip shrink-0"
                data-tip="Log out"
                aria-label="Log out"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>
      </aside>
    </>
  );
};

export default Sidebar;
