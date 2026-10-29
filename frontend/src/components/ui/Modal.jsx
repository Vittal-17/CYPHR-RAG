import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import clsx from 'clsx';
import { focusablesIn } from '../../lib/focus';

/** Keep in sync with the exit transition below. */
const EXIT_MS = 180;

const SIZES = {
  sm: 'sm:max-w-md',
  md: 'sm:max-w-panel',
  lg: 'sm:max-w-3xl',
};

/**
 * Accessible dialog primitive: portalled to `body`, labelled, focus-trapped,
 * closes on Escape or backdrop click, and returns focus to whatever opened it.
 * On phones it becomes a full-bleed sheet so content is never cramped.
 */
export function Modal({
  isOpen,
  onClose,
  title,
  description,
  eyebrow,
  icon,
  size = 'md',
  footer,
  children,
  className,
  initialFocusRef,
}) {
  const [mounted, setMounted] = useState(isOpen);
  const [visible, setVisible] = useState(false);
  const panelRef = useRef(null);
  const restoreRef = useRef(null);
  const titleId = useId();
  const descriptionId = useId();

  // Mount immediately, animate in on the next frame; on close, animate out
  // first and only then leave the tree.
  useEffect(() => {
    if (isOpen) {
      setMounted(true);
      const frame = requestAnimationFrame(() => setVisible(true));
      return () => cancelAnimationFrame(frame);
    }
    setVisible(false);
    const timer = setTimeout(() => setMounted(false), EXIT_MS);
    return () => clearTimeout(timer);
  }, [isOpen]);

  // Move focus in on open and hand it back on close.
  useEffect(() => {
    if (!isOpen) return undefined;
    restoreRef.current = document.activeElement;
    const frame = requestAnimationFrame(() => {
      const target = initialFocusRef?.current ?? panelRef.current;
      target?.focus?.({ preventScroll: true });
    });
    return () => {
      cancelAnimationFrame(frame);
      const previous = restoreRef.current;
      restoreRef.current = null;
      if (previous && typeof previous.focus === 'function' && document.contains(previous)) {
        previous.focus({ preventScroll: true });
      }
    };
  }, [isOpen, initialFocusRef]);

  const handleKeyDown = useCallback(
    (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose?.();
        return;
      }
      if (event.key !== 'Tab') return;

      const panel = panelRef.current;
      if (!panel) return;
      const items = focusablesIn(panel);
      if (items.length === 0) {
        event.preventDefault();
        return;
      }

      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;

      if (event.shiftKey && (active === first || active === panel)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    },
    [onClose]
  );

  useEffect(() => {
    if (!isOpen) return undefined;
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, handleKeyDown]);

  if (!mounted) return null;

  return createPortal(
    <div className="fixed inset-0 z-modal flex justify-center overflow-y-auto overscroll-contain sm:items-center sm:p-6">
      <button
        type="button"
        aria-label="Close dialog"
        tabIndex={-1}
        onClick={() => onClose?.()}
        className={clsx(
          'fixed inset-0 cursor-default bg-surface-0/75 backdrop-blur-sm transition-opacity duration-normal ease-standard',
          visible ? 'opacity-100' : 'opacity-0'
        )}
      />

      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={clsx(
          'panel hairline relative flex max-h-full w-full flex-col overflow-hidden outline-none',
          'transition-[opacity,transform] duration-normal ease-entrance',
          'max-sm:min-h-full max-sm:rounded-none max-sm:border-x-0',
          SIZES[size],
          visible ? 'translate-y-0 opacity-100 sm:scale-100' : 'translate-y-2 opacity-0 sm:scale-[0.97]',
          className
        )}
      >
        <header className="flex items-start gap-3 border-b border-line-subtle px-comfortable py-normal">
          {icon && (
            <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-md border border-line bg-surface-3 text-accent">
              {icon}
            </span>
          )}
          <div className="min-w-0 flex-1">
            {eyebrow && <p className="eyebrow mb-0.5">{eyebrow}</p>}
            {title && (
              <h2 id={titleId} className="truncate text-head font-semibold text-ink">
                {title}
              </h2>
            )}
            {description && (
              <p id={descriptionId} className="mt-1 text-cap text-ink-dim">
                {description}
              </p>
            )}
          </div>
          <button type="button" onClick={() => onClose?.()} className="icon-btn -mr-1 shrink-0" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-comfortable py-comfortable">{children}</div>

        {footer && (
          <footer className="border-t border-line-subtle bg-surface-1/60 px-comfortable py-normal">{footer}</footer>
        )}
      </div>
    </div>,
    document.body
  );
}

export default Modal;
