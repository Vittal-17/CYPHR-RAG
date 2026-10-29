import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import { AlertTriangle, Check, ChevronDown, Cpu } from 'lucide-react';
import clsx from 'clsx';

const MENU_ITEM = '[role="menuitemradio"]';

/**
 * Model control for the top bar. Presents the provider catalogue exactly as the
 * backend publishes it (`/api/llm/providers` → id + display name only) as a
 * menu-button with two radio groups, so provider and model can be changed in
 * one visit without ever surfacing endpoints or credentials.
 */
const ProviderSelector = ({
  providers = [],
  status = 'idle',
  providerId,
  modelId,
  activeProvider,
  activeModel,
  selectProvider,
  selectModel,
  compact = false,
}) => {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef(null);
  const popoverRef = useRef(null);
  const menuId = useId();

  const close = useCallback((refocus = false) => {
    setOpen(false);
    if (refocus) triggerRef.current?.focus();
  }, []);

  // Dismiss on outside pointer and on window resize (the popover is anchored).
  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event) => {
      if (popoverRef.current?.contains(event.target) || triggerRef.current?.contains(event.target)) return;
      setOpen(false);
    };
    const onResize = () => setOpen(false);
    document.addEventListener('pointerdown', onPointerDown, true);
    window.addEventListener('resize', onResize);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true);
      window.removeEventListener('resize', onResize);
    };
  }, [open]);

  // Focus the current selection when the menu opens.
  useEffect(() => {
    if (!open) return undefined;
    const frame = requestAnimationFrame(() => {
      const panel = popoverRef.current;
      if (!panel) return;
      const items = Array.from(panel.querySelectorAll(MENU_ITEM));
      const checked = items.filter((item) => item.getAttribute('aria-checked') === 'true');
      (checked[checked.length - 1] ?? items[0])?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [open]);

  const moveFocus = useCallback((direction) => {
    const panel = popoverRef.current;
    if (!panel) return;
    const items = Array.from(panel.querySelectorAll(MENU_ITEM)).filter((item) => !item.disabled);
    if (items.length === 0) return;
    const index = items.indexOf(document.activeElement);
    const next =
      direction === 'first'
        ? 0
        : direction === 'last'
          ? items.length - 1
          : (index + (direction === 'next' ? 1 : -1) + items.length) % items.length;
    items[next]?.focus();
  }, []);

  const handleMenuKeyDown = useCallback(
    (event) => {
      switch (event.key) {
        case 'Escape':
          event.preventDefault();
          close(true);
          break;
        case 'ArrowDown':
          event.preventDefault();
          moveFocus('next');
          break;
        case 'ArrowUp':
          event.preventDefault();
          moveFocus('previous');
          break;
        case 'Home':
          event.preventDefault();
          moveFocus('first');
          break;
        case 'End':
          event.preventDefault();
          moveFocus('last');
          break;
        case 'Tab':
          // Closing without moving focus would drop it on <body> and lose the
          // user's place; handing it back to the trigger lets Tab carry on from
          // the control they opened.
          close(true);
          break;
        default:
          break;
      }
    },
    [close, moveFocus]
  );

  // `idle` is the state before the effect that fetches the catalogue has run,
  // so it reads as "not loaded yet" — not as "nothing is configured", which
  // would flash a warning on the first painted frame after sign-in.
  if (status === 'loading' || status === 'idle') {
    return (
      <span className="chip" aria-busy="true">
        <span className="skeleton h-3 w-16 rounded-pill" />
        <span className="sr-only">Loading available models</span>
      </span>
    );
  }

  if (status === 'error' || providers.length === 0) {
    const label = status === 'error' ? 'Models unavailable' : 'No models configured';
    return (
      <span className="chip tip tip-below border-warning/30 text-warning" data-tip={label} role="status">
        <AlertTriangle className="h-3.5 w-3.5" />
        {!compact && <span>{label}</span>}
      </span>
    );
  }

  const models = Array.isArray(activeProvider?.models) ? activeProvider.models : [];
  const modelLabel = activeModel?.name || activeModel?.id || 'Select a model';

  const itemClass = (checked) =>
    clsx(
      'group flex w-full items-center justify-between gap-2 rounded-sm px-2 py-2 text-left text-cap transition-all duration-fast ease-standard hover:-translate-y-px',
      checked ? 'bg-accent/10 font-medium text-accent shadow-subtle' : 'text-ink-dim hover:bg-surface-3 hover:text-ink hover:shadow-subtle'
    );

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (!open && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
            event.preventDefault();
            setOpen(true);
          }
        }}
        aria-haspopup="true"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        className={clsx(
          'flex h-9 max-w-[13rem] items-center gap-2 rounded-md border px-2.5 transition-colors duration-fast ease-standard',
          open
            ? 'border-accent/45 bg-surface-3 text-ink shadow-ring-accent'
            : 'border-line bg-surface-2/70 text-ink-dim hover:border-line-strong hover:bg-surface-3 hover:text-ink'
        )}
      >
        <Cpu className="h-3.5 w-3.5 shrink-0 text-accent" />
        <span className="flex min-w-0 flex-col items-start gap-0.5 leading-none">
          {!compact && activeProvider?.name && (
            <span className="max-w-[9.5rem] truncate text-label uppercase tracking-wide text-ink-faint">
              {activeProvider.name}
            </span>
          )}
          <span className={clsx('truncate text-cap font-medium', compact ? 'max-w-[6rem]' : 'max-w-[9.5rem]')}>
            {modelLabel}
          </span>
        </span>
        <ChevronDown
          className={clsx('h-3.5 w-3.5 shrink-0 transition-transform duration-fast ease-standard', open && 'rotate-180')}
        />
      </button>

      {open && (
        <div
          ref={popoverRef}
          id={menuId}
          role="menu"
          aria-label="Model selection"
          tabIndex={-1}
          onKeyDown={handleMenuKeyDown}
          className="panel absolute right-0 top-full z-chrome mt-2 w-64 origin-top-right animate-scale-in p-1.5"
        >
          <div role="group" aria-label="Provider">
            {/* The group already carries the name; the visible heading would
                otherwise be announced a second time as stray menu text. */}
            <p className="eyebrow px-2 py-1" aria-hidden="true">
              Provider
            </p>
            {providers.map((provider) => {
              const checked = provider.id === providerId;
              return (
                <button
                  key={provider.id}
                  type="button"
                  role="menuitemradio"
                  aria-checked={checked}
                  onClick={() => selectProvider?.(provider.id)}
                  className={itemClass(checked)}
                >
                  <span className="truncate">{provider.name || provider.id}</span>
                  {checked && <Check className="h-3.5 w-3.5 shrink-0" />}
                </button>
              );
            })}
          </div>

          <hr className="divider my-1.5" />

          <div role="group" aria-label="Model">
            <p className="eyebrow px-2 py-1" aria-hidden="true">
              Model
            </p>
            {models.length === 0 ? (
              <p className="px-2 pb-1.5 text-cap text-ink-faint">No models available for this provider.</p>
            ) : (
              <div className="scroll-thin max-h-56 overflow-y-auto">
                {models.map((model) => {
                  const checked = model.id === modelId;
                  return (
                    <button
                      key={model.id}
                      type="button"
                      role="menuitemradio"
                      aria-checked={checked}
                      onClick={() => {
                        selectModel?.(model.id);
                        close(true);
                      }}
                      className={itemClass(checked)}
                    >
                      <span className="truncate">{model.name || model.id}</span>
                      {checked && <Check className="h-3.5 w-3.5 shrink-0" />}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default ProviderSelector;
