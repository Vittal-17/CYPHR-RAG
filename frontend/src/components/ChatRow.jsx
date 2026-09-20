import React, { memo, useState, useEffect, useRef } from 'react';
import clsx from 'clsx';
import {
  Check,
  Loader2,
  MessageSquare,
  Pencil,
  Trash2,
  X,
} from 'lucide-react';

/*
 * ⚡ Bolt Optimization: Extracted ChatRow into a memoized component and moved the
 * `editTitle` state locally. Previously, typing in the rename input updated the
 * parent Sidebar's state, causing the entire list of chat histories to re-render
 * on every single keystroke. Now, only the actively editing row re-renders,
 * significantly reducing React render time for users with many chats.
 */
const ChatRow = ({
  chat,
  isActive,
  isEditing,
  isConfirming,
  saveTitle,
  setEditingChatId,
  onSelectChat,
  handleDelete,
  deletingChatId,
  setPendingDeleteId,
  startEditing,
}) => {
  const [editTitle, setEditTitle] = useState(chat.title || '');
  const inputRef = useRef(null);

  useEffect(() => {
    if (isEditing) {
      setEditTitle(chat.title || '');
      // Use requestAnimationFrame to ensure the input is rendered before focusing
      requestAnimationFrame(() => {
        inputRef.current?.focus();
        inputRef.current?.select();
      });
    }
  }, [isEditing, chat.title]);

  const title = chat.title || 'Untitled';

  return (
    <li>
      <div
        className={clsx(
          'group relative flex items-center gap-1 rounded-md pl-2.5 pr-1.5 transition-all duration-fast ease-standard hover:-translate-y-px hover:shadow-subtle',
          isActive ? 'active-rule bg-surface-3 text-ink shadow-subtle' : 'text-ink-dim hover:bg-surface-3/60 hover:text-ink',
          isConfirming && 'bg-danger/10'
        )}
      >
        {isEditing ? (
          <input
            ref={inputRef}
            value={editTitle}
            aria-label="Conversation title"
            onChange={(event) => setEditTitle(event.target.value)}
            onBlur={() => saveTitle(chat.chat_id, editTitle)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                saveTitle(chat.chat_id, editTitle);
              } else if (event.key === 'Escape') {
                event.preventDefault();
                setEditingChatId(null);
              }
            }}
            className="field my-1 h-8 w-full py-0 text-cap"
          />
        ) : (
          <>
            <button
              type="button"
              onClick={() => onSelectChat(chat.chat_id)}
              aria-current={isActive ? 'true' : undefined}
              className="flex min-w-0 flex-1 items-center gap-2.5 rounded-sm py-2 text-left"
            >
              <MessageSquare
                className={clsx(
                  'h-3.5 w-3.5 shrink-0 transition-colors duration-fast',
                  isActive ? 'text-accent' : 'text-ink-faint group-hover:text-accent'
                )}
              />
              <span className="truncate text-cap font-medium">{title}</span>
            </button>

            {isConfirming ? (
              <span className="flex shrink-0 items-center gap-0.5">
                <button
                  type="button"
                  onClick={() => handleDelete(chat.chat_id)}
                  disabled={deletingChatId === chat.chat_id}
                  className="icon-btn icon-btn-danger h-7 w-7"
                  aria-label={`Confirm deleting ${title}`}
                >
                  {deletingChatId === chat.chat_id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                </button>
                <button
                  type="button"
                  onClick={() => setPendingDeleteId(null)}
                  disabled={deletingChatId === chat.chat_id}
                  className="icon-btn h-7 w-7"
                  aria-label="Keep conversation"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </span>
            ) : (
              <span
                className={clsx(
                  'flex shrink-0 items-center gap-0.5 transition-opacity duration-fast',
                  'opacity-0 focus-within:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100',
                  isActive && 'opacity-70'
                )}
              >
                <button
                  type="button"
                  onClick={() => startEditing(chat.chat_id)}
                  className="icon-btn h-7 w-7"
                  aria-label={`Rename ${title}`}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => setPendingDeleteId(chat.chat_id)}
                  disabled={deletingChatId === chat.chat_id}
                  className="icon-btn icon-btn-danger h-7 w-7"
                  aria-label={`Delete ${title}`}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </span>
            )}
          </>
        )}
      </div>
    </li>
  );
};

export default memo(ChatRow);
