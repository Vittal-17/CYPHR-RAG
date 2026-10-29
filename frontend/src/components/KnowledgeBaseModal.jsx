import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import toast from 'react-hot-toast';
import { FileText, Library, Loader2, Search, Trash2 } from 'lucide-react';
import clsx from 'clsx';
import Modal from './ui/Modal';
import FileUpload from './FileUpload';
import { pluralize, splitFilename } from '../lib/format';
import { errorDetail } from '../lib/errors';

/** Filtering only earns its space once a list is long enough to scan poorly. */
const FILTER_THRESHOLD = 6;
const CONFIRM_MS = 5000;

/**
 * The knowledge base: add PDFs, review what is indexed, remove what is not
 * wanted.
 *
 * `/api/documents` reports filenames and nothing else, so filenames are all
 * this shows — no size, page count or date is implied that the server never
 * sent.
 */
const KnowledgeBaseModal = ({ isOpen, onClose, documents, onUploaded, onRemoved }) => {
  const [query, setQuery] = useState('');
  const [pendingDelete, setPendingDelete] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const mountedRef = useRef(true);
  const confirmTimerRef = useRef(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (confirmTimerRef.current) clearTimeout(confirmTimerRef.current);
    };
  }, []);

  // Nothing half-finished survives a close.
  useEffect(() => {
    if (isOpen) return;
    setQuery('');
    setPendingDelete(null);
  }, [isOpen]);

  // An armed confirmation expires instead of lying in wait.
  useEffect(() => {
    if (!pendingDelete) return undefined;
    confirmTimerRef.current = setTimeout(() => setPendingDelete(null), CONFIRM_MS);
    return () => clearTimeout(confirmTimerRef.current);
  }, [pendingDelete]);

  const list = useMemo(() => (Array.isArray(documents) ? documents : []), [documents]);
  const term = query.trim().toLowerCase();
  const visible = useMemo(
    () => (term ? list.filter((doc) => doc?.filename?.toLowerCase().includes(term)) : list),
    [list, term]
  );

  const handleDelete = useCallback(
    async (filename) => {
      setDeleting(filename);
      try {
        await axios.delete(`/api/documents/${encodeURIComponent(filename)}`);
        if (!mountedRef.current) return;
        onRemoved?.(filename);
        toast.success('Document removed');
      } catch (error) {
        if (!mountedRef.current) return;
        toast.error(errorDetail(error, 'That document could not be removed.'));
      } finally {
        if (mountedRef.current) {
          setDeleting(null);
          setPendingDelete(null);
        }
      }
    },
    [onRemoved]
  );

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size="lg"
      eyebrow="Knowledge base"
      title="Your documents"
      description={
        list.length > 0
          ? `${pluralize(list.length, 'document')} indexed — every answer cites the pages it used`
          : 'Nothing is indexed yet. Add a PDF and CYPHR can start answering from it.'
      }
      icon={<Library className="h-4 w-4" aria-hidden="true" />}
      footer={
        <p className="text-cap leading-relaxed text-ink-dim">
          Documents are private to your account. Removing one deletes its indexed passages, so answers
          can no longer cite it.
        </p>
      }
    >
      <FileUpload onUploaded={onUploaded} />

      <div className="mt-comfortable flex items-center justify-between gap-3">
        <h3 className="eyebrow">Indexed documents</h3>
        {term ? (
          <span className="text-label text-ink-faint">
            {visible.length} of {list.length}
          </span>
        ) : (
          list.length > 0 && <span className="text-label text-ink-faint">{list.length}</span>
        )}
      </div>

      {list.length >= FILTER_THRESHOLD && (
        <div className="relative mt-normal">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint"
            aria-hidden="true"
          />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter by filename"
            aria-label="Filter documents by filename"
            className="field py-2 pl-9 text-cap"
          />
        </div>
      )}

      {list.length === 0 && (
        <div className="mt-normal rounded-lg border border-line-subtle bg-surface-2/40 px-4 py-large text-center">
          <span className="mx-auto grid h-10 w-10 place-items-center rounded-md border border-line bg-surface-3/70 text-ink-faint">
            <Library className="h-4 w-4" aria-hidden="true" />
          </span>
          <p className="mt-2.5 text-sub font-medium text-ink">No documents yet</p>
          <p className="mx-auto mt-1 max-w-xs text-cap leading-relaxed text-ink-dim">
            Add a PDF above. CYPHR reads it once, then searches it every time you ask a question.
          </p>
        </div>
      )}

      {list.length > 0 && visible.length === 0 && (
        <div className="mt-normal rounded-lg border border-line-subtle bg-surface-2/40 px-4 py-comfortable text-center">
          <p className="text-sub text-ink-dim">
            No document matches <span className="font-medium text-ink">{query.trim()}</span>
          </p>
          <button type="button" onClick={() => setQuery('')} className="btn btn-ghost btn-sm mx-auto mt-2">
            Clear filter
          </button>
        </div>
      )}

      {visible.length > 0 && (
        <ul className="mt-normal space-y-1.5">
          {visible.map(({ filename }) => {
            const { stem, ext } = splitFilename(filename);
            const armed = pendingDelete === filename;
            const busy = deleting === filename;

            return (
              <li key={filename}>
                <div className={clsx('group/doc flex items-center gap-2.5 rounded-lg border border-line-subtle bg-surface-2/60 px-3 py-2.5 transition-all duration-fast ease-standard hover:shadow-subtle hover:-translate-y-px hover:border-line-strong hover:bg-surface-3/90', armed && 'border-danger/40 bg-danger/5', busy && 'opacity-50 grayscale')}>
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-line bg-surface-3/70 text-accent">
                    <FileText className="h-4 w-4" aria-hidden="true" />
                  </span>

                  <p className="flex min-w-0 flex-1 items-baseline text-sub text-ink" title={filename}>
                    <span className="truncate">{stem}</span>
                    {ext && <span className="shrink-0 text-ink-faint">{ext}</span>}
                  </p>

                  {armed ? (
                    <span className="flex shrink-0 items-center gap-1">
                      <button
                        type="button"
                        onClick={() => handleDelete(filename)}
                        disabled={busy}
                        className="btn btn-danger btn-sm"
                      >
                        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : null}
                        {busy ? 'Removing' : 'Remove'}
                      </button>
                      <button type="button" onClick={() => setPendingDelete(null)} className="btn btn-ghost btn-sm">
                        Keep
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setPendingDelete(filename)}
                      className="icon-btn icon-btn-danger h-8 w-8 shrink-0 opacity-0 transition-opacity duration-fast focus-visible:opacity-100 group-hover/doc:opacity-100 [@media(hover:none)]:opacity-100"
                      aria-label={`Remove ${filename}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Modal>
  );
};

export default KnowledgeBaseModal;
