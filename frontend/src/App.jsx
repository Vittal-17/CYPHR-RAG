import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import { Toaster, toast } from 'react-hot-toast';
import ChatBox from './components/ChatBox';
import AuthScreen from './components/AuthScreen';
import Sidebar from './components/Sidebar';
import TopBar from './components/TopBar';
import KnowledgeBaseModal from './components/KnowledgeBaseModal';
import AuthLoadingOverlay from './components/AuthLoadingOverlay';
import Atmosphere from './components/ui/Atmosphere';
import useMediaQuery from './hooks/useMediaQuery';
import useProviders from './hooks/useProviders';
import { groupChatsByRecency, pluralize } from './lib/format';
import { errorDetail } from './lib/errors';
import { withAuthDelay } from './utils/authDelay';
import { getAccessToken, setAccessToken, clearAccessToken } from './utils/token';

/** The persistent rail needs real room; below this the nav becomes a drawer. */
const DESKTOP_QUERY = '(min-width: 1024px)';

const TOAST_OPTIONS = {
  duration: 4000,
  style: {
    background: 'rgb(16 32 55 / 0.96)',
    color: 'rgb(228 240 250)',
    border: '1px solid rgb(27 49 79)',
    borderRadius: '10px',
    boxShadow: '0 18px 40px -12px rgb(2 6 14 / 0.75)',
    fontSize: '0.8125rem',
    maxWidth: '22rem',
  },
  success: { iconTheme: { primary: 'rgb(34 211 238)', secondary: 'rgb(3 10 20)' } },
  error: { iconTheme: { primary: 'rgb(248 113 113)', secondary: 'rgb(3 10 20)' } },
};

function App() {
  const [user, setUser] = useState(null);
  const [booting, setBooting] = useState(true);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [isKBOpen, setIsKBOpen] = useState(false);
  const [documents, setDocuments] = useState([]);
  const [chats, setChats] = useState([]);
  const [activeChatId, setActiveChatId] = useState(null);

  const isDesktop = useMediaQuery(DESKTOP_QUERY);
  const providers = useProviders(Boolean(user));
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const loadUserData = useCallback(async () => {
    try {
      const [chatsRes, docsRes] = await Promise.all([axios.get('/api/chats'), axios.get('/api/documents')]);
      if (!mountedRef.current) return;
      const list = Array.isArray(chatsRes.data) ? chatsRes.data : [];
      setChats(list);
      setActiveChatId(list.length > 0 ? list[0].chat_id : null);
      setDocuments(Array.isArray(docsRes.data) ? docsRes.data : []);
    } catch (error) {
      if (!mountedRef.current) return;
      toast.error(errorDetail(error, 'Could not load your workspace.'));
    }
  }, []);

  useEffect(() => {
    let active = true;
    const bootstrap = async () => {
      try {
        let urlToken = null;

        // 1. Check secure client-side hash fragment (#token=...)
        if (window.location.hash) {
          const rawHash = window.location.hash.startsWith('#')
            ? window.location.hash.substring(1)
            : window.location.hash;
          const hashParams = new URLSearchParams(rawHash);
          if (hashParams.has('token')) {
            urlToken = hashParams.get('token');
            hashParams.delete('token');
            const remainingHash = hashParams.toString();
            const cleanUrl =
              window.location.pathname +
              window.location.search +
              (remainingHash ? `#${remainingHash}` : '');
            window.history.replaceState({}, document.title, cleanUrl);
          }
        }

        // 2. Fallback to query parameter (?token=...) for backward compatibility
        if (!urlToken && window.location.search) {
          const searchParams = new URLSearchParams(window.location.search);
          if (searchParams.has('token')) {
            urlToken = searchParams.get('token');
            searchParams.delete('token');
            const remainingQuery = searchParams.toString();
            const cleanUrl =
              window.location.pathname +
              (remainingQuery ? `?${remainingQuery}` : '') +
              window.location.hash;
            window.history.replaceState({}, document.title, cleanUrl);
          }
        }

        if (urlToken) {
          setAccessToken(urlToken);
        }

        const res = await axios.get('/api/me');
        if (!active) return;
        setUser(res.data.user);
        await loadUserData();
      } catch {
        if (active) {
          clearAccessToken();
          setUser(null);
        }
      }
    };

    withAuthDelay(bootstrap).finally(() => {
      if (active) setBooting(false);
    });

    return () => {
      active = false;
    };
  }, [loadUserData]);

  // The drawer is a phone/tablet affordance; it must never survive a resize
  // into the desktop layout.
  useEffect(() => {
    if (isDesktop && mobileNavOpen) setMobileNavOpen(false);
  }, [isDesktop, mobileNavOpen]);

  useEffect(() => {
    if (!mobileNavOpen) return undefined;
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setMobileNavOpen(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [mobileNavOpen]);

  const handleAuthSuccess = useCallback(
    async (userData) => {
      setUser(userData);
      await loadUserData();
    },
    [loadUserData]
  );

  const handleLogout = useCallback(async () => {
    try {
      setIsLoggingOut(true);
      await withAuthDelay(() => axios.post('/api/logout'));
      clearAccessToken();
      setUser(null);
      setChats([]);
      setActiveChatId(null);
      setDocuments([]);
      setIsKBOpen(false);
      setMobileNavOpen(false);
      toast.success('Signed out');
    } catch (error) {
      clearAccessToken();
      toast.error(errorDetail(error, 'Sign out failed.'));
    } finally {
      setIsLoggingOut(false);
    }
  }, []);

  const selectChat = useCallback((chatId) => {
    setActiveChatId(chatId);
    setMobileNavOpen(false);
  }, []);

  /**
   * `/chat` mints a chat_id on the first message; adopt it without a refetch.
   * `activate` is false when the answer came back after the user had already
   * moved to another conversation — the new chat still belongs in the list,
   * but pulling them out of what they are reading would be hostile.
   */
  const registerChat = useCallback((chatId, title, { activate = true } = {}) => {
    if (!chatId) return;
    setChats((prev) =>
      prev.some((chat) => chat.chat_id === chatId)
        ? prev.map((chat) => (chat.chat_id === chatId && title ? { ...chat, title } : chat))
        : [{ chat_id: chatId, title: title || 'New conversation' }, ...prev]
    );
    if (activate) setActiveChatId(chatId);
  }, []);

  const renameChat = useCallback((chatId, title) => {
    if (!chatId || !title) return;
    setChats((prev) => prev.map((chat) => (chat.chat_id === chatId ? { ...chat, title } : chat)));
  }, []);

  const addDocument = useCallback((filename) => {
    if (!filename) return;
    setDocuments((prev) =>
      prev.some((doc) => doc.filename === filename) ? prev : [...prev, { filename }]
    );
  }, []);

  const removeDocument = useCallback((filename) => {
    setDocuments((prev) => prev.filter((doc) => doc.filename !== filename));
  }, []);

  const activeChat = useMemo(
    () => chats.find((chat) => chat.chat_id === activeChatId) ?? null,
    [chats, activeChatId]
  );

  const contextLabel = useMemo(() => {
    if (activeChat) return groupChatsByRecency([activeChat])[0]?.label ?? null;
    return documents.length > 0
      ? `${pluralize(documents.length, 'document')} ready to query`
      : 'No documents indexed yet';
  }, [activeChat, documents.length]);

  const openKB = useCallback(() => setIsKBOpen(true), []);
  const closeKB = useCallback(() => setIsKBOpen(false), []);
  const closeMobileNav = useCallback(() => setMobileNavOpen(false), []);
  const toggleCollapsed = useCallback(() => setCollapsed((value) => !value), []);

  if (booting) {
    return (
      <>
        <Atmosphere />
        <AuthLoadingOverlay isVisible />
      </>
    );
  }

  if (!user) {
    return (
      <>
        <Toaster position="top-center" toastOptions={TOAST_OPTIONS} />
        <AuthScreen onAuthSuccess={handleAuthSuccess} />
      </>
    );
  }

  return (
    <>
      <Atmosphere />
      <Toaster position="top-center" toastOptions={TOAST_OPTIONS} containerStyle={{ top: 68 }} />

      <div className="relative z-content flex h-full w-full overflow-hidden">
        <Sidebar
          isDesktop={isDesktop}
          collapsed={collapsed}
          mobileOpen={mobileNavOpen}
          onCloseMobile={closeMobileNav}
          onToggleCollapse={toggleCollapsed}
          user={user}
          onLogout={handleLogout}
          chats={chats}
          setChats={setChats}
          activeChatId={activeChatId}
          onSelectChat={selectChat}
          onOpenKnowledgeBase={openKB}
          documentCount={documents.length}
        />

        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar
            isDesktop={isDesktop}
            onOpenMobileNav={() => setMobileNavOpen(true)}
            title={activeChat?.title || 'New conversation'}
            contextLabel={contextLabel}
            documentCount={documents.length}
            onOpenKnowledgeBase={openKB}
            providers={providers}
          />

          <ChatBox
            activeChatId={activeChatId}
            onChatCreated={registerChat}
            onChatRenamed={renameChat}
            providerId={providers.providerId}
            modelId={providers.modelId}
            modelLabel={providers.activeModel?.name || providers.activeModel?.id || ''}
            documentCount={documents.length}
            onOpenKnowledgeBase={openKB}
            onDocumentUploaded={addDocument}
          />
        </div>
      </div>

      <KnowledgeBaseModal
        isOpen={isKBOpen}
        onClose={closeKB}
        documents={documents}
        onUploaded={addDocument}
        onRemoved={removeDocument}
      />
      <AuthLoadingOverlay isVisible={isLoggingOut} />
    </>
  );
}

export default App;
