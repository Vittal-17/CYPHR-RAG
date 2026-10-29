import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import axios from 'axios';
import toast from 'react-hot-toast';

import Modal from '../components/ui/Modal';
import ThemeSelector from '../components/ThemeSelector';
import ProviderSelector from '../components/ProviderSelector';
import SourceList from '../components/SourceList';
import ChatMessage from '../components/ChatMessage';
import KnowledgeBaseModal from '../components/KnowledgeBaseModal';
import TopBar from '../components/TopBar';
import FileUpload from '../components/FileUpload';

vi.mock('axios');
vi.mock('react-hot-toast');

describe('components/ui/Modal', () => {
  it('renders nothing when isOpen is false', () => {
    const { container } = render(
      <Modal isOpen={false} onClose={vi.fn()} title="Test Dialog">
        <p>Dialog content</p>
      </Modal>
    );
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText('Dialog content')).not.toBeInTheDocument();
  });

  it('renders modal content and accessible dialog when isOpen is true', () => {
    render(
      <Modal isOpen onClose={vi.fn()} title="Test Dialog" description="Description text">
        <p>Dialog content</p>
      </Modal>
    );

    const dialog = screen.getByRole('dialog');
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText('Test Dialog')).toBeInTheDocument();
    expect(screen.getByText('Description text')).toBeInTheDocument();
    expect(screen.getByText('Dialog content')).toBeInTheDocument();
  });

  it('calls onClose when clicking close button or backdrop', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();

    render(
      <Modal isOpen onClose={onClose} title="Test Dialog">
        <p>Dialog content</p>
      </Modal>
    );

    const closeBtn = screen.getByLabelText('Close dialog');
    await user.click(closeBtn);
    expect(onClose).toHaveBeenCalled();
  });

  it('calls onClose when pressing Escape key', () => {
    const onClose = vi.fn();
    render(
      <Modal isOpen onClose={onClose} title="Test Dialog">
        <button type="button">Inside</button>
      </Modal>
    );

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('traps Tab focus inside the modal dialog', () => {
    render(
      <Modal isOpen onClose={vi.fn()} title="Focus Trap Dialog">
        <button id="first-btn" type="button">First</button>
        <button id="second-btn" type="button">Second</button>
      </Modal>
    );

    const closeBtn = screen.getByLabelText('Close');
    const secondBtn = screen.getByText('Second');

    secondBtn.focus();
    expect(document.activeElement).toBe(secondBtn);

    // Tab on last element wraps around to first element (header close button)
    fireEvent.keyDown(window, { key: 'Tab', shiftKey: false });
    expect(document.activeElement).toBe(closeBtn);

    // Shift+Tab on first element wraps around to last element
    fireEvent.keyDown(window, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(secondBtn);
  });
});

describe('components/ThemeSelector', () => {
  beforeEach(() => {
    document.documentElement.removeAttribute('data-theme');
  });

  it('toggles theme menu and selects theme', async () => {
    const user = userEvent.setup();
    render(<ThemeSelector />);

    const button = screen.getByLabelText('Select theme');
    expect(button).toBeInTheDocument();

    await user.click(button);
    expect(screen.getByText('Dark')).toBeInTheDocument();

    await user.click(screen.getByText('Dark'));
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(screen.queryByText('Dark')).not.toBeInTheDocument();
  });

  it('closes dropdown when clicking backdrop', async () => {
    const user = userEvent.setup();
    render(<ThemeSelector />);

    await user.click(screen.getByLabelText('Select theme'));
    const backdrop = screen.getByLabelText('Close theme menu');
    expect(backdrop).toBeInTheDocument();

    await user.click(backdrop);
    expect(screen.queryByLabelText('Close theme menu')).not.toBeInTheDocument();
  });
});

describe('components/ProviderSelector', () => {
  const mockProviders = [
    {
      id: 'gemini',
      name: 'Google Gemini',
      models: [
        { id: 'gemini-1.5-flash', name: 'Gemini 1.5 Flash' },
        { id: 'gemini-1.5-pro', name: 'Gemini 1.5 Pro' },
      ],
    },
    {
      id: 'groq',
      name: 'Groq',
      models: [{ id: 'llama-3.1-70b', name: 'Llama 3.1 70B' }],
    },
  ];

  it('renders provider trigger and opens model menu', async () => {
    const user = userEvent.setup();
    const selectProvider = vi.fn();
    const selectModel = vi.fn();

    render(
      <ProviderSelector
        providers={mockProviders}
        status="ready"
        providerId="gemini"
        modelId="gemini-1.5-flash"
        activeProvider={mockProviders[0]}
        activeModel={mockProviders[0].models[0]}
        selectProvider={selectProvider}
        selectModel={selectModel}
      />
    );

    const trigger = screen.getByRole('button');
    expect(trigger).toHaveTextContent('Google Gemini');
    expect(trigger).toHaveTextContent('Gemini 1.5 Flash');

    await user.click(trigger);
    expect(screen.getByRole('menu', { name: 'Model selection' })).toBeInTheDocument();

    await user.click(screen.getByText('Gemini 1.5 Pro'));
    expect(selectModel).toHaveBeenCalledWith('gemini-1.5-pro');
  });

  it('navigates menu with keyboard ArrowDown / ArrowUp and Escape to close', async () => {
    const user = userEvent.setup();
    render(
      <ProviderSelector
        providers={mockProviders}
        status="ready"
        providerId="gemini"
        modelId="gemini-1.5-flash"
        activeProvider={mockProviders[0]}
        activeModel={mockProviders[0].models[0]}
      />
    );

    const trigger = screen.getByRole('button');
    await user.click(trigger);

    const menu = screen.getByRole('menu', { name: 'Model selection' });
    expect(menu).toBeInTheDocument();

    fireEvent.keyDown(menu, { key: 'Escape' });
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });
});

describe('components/SourceList', () => {
  it('returns null when sources is empty', () => {
    const { container } = render(<SourceList sources={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders sorted citations and groups by filename', () => {
    const sources = [
      { filename: 'doc1.pdf', page: '10' },
      { filename: 'doc1.pdf', page: '2' },
      { filename: 'doc2.pdf', page: '5' },
    ];

    render(<SourceList sources={sources} />);
    expect(screen.getByText('Sources')).toBeInTheDocument();
    expect(screen.getByText('doc1')).toBeInTheDocument();
    expect(screen.getByText('doc2')).toBeInTheDocument();
    expect(screen.getByText('pp. 2, 10')).toBeInTheDocument();
    expect(screen.getByText('p. 5')).toBeInTheDocument();
  });

  it('collapses list when there are more than 3 documents and expands on click', async () => {
    const user = userEvent.setup();
    const sources = [
      { filename: 'doc1.pdf', page: '1' },
      { filename: 'doc2.pdf', page: '1' },
      { filename: 'doc3.pdf', page: '1' },
      { filename: 'doc4.pdf', page: '1' },
      { filename: 'doc5.pdf', page: '1' },
    ];

    render(<SourceList sources={sources} />);
    expect(screen.getByText('+2 more')).toBeInTheDocument();
    expect(screen.queryByText('doc4')).not.toBeInTheDocument();

    await user.click(screen.getByText('+2 more'));
    expect(screen.getByText('doc4')).toBeInTheDocument();
    expect(screen.getByText('Show fewer')).toBeInTheDocument();
  });
});

describe('components/ChatMessage', () => {
  it('renders user message cleanly', () => {
    render(<ChatMessage role="user" content="What is CYPHR?" />);
    expect(screen.getByLabelText('Your message')).toBeInTheDocument();
    expect(screen.getByText('What is CYPHR?')).toBeInTheDocument();
  });

  it('renders assistant message with sources and copy action', async () => {
    const user = userEvent.setup();
    const onCopy = vi.fn();
    const content = `CYPHR is an enterprise RAG system.

### Sources:
- **overview.pdf** (Page 1)`;

    const { rerender } = render(
      <ChatMessage
        index={0}
        role="assistant"
        content={content}
        copied={false}
        onCopy={onCopy}
      />
    );

    expect(screen.getByLabelText('CYPHR response')).toBeInTheDocument();
    expect(screen.getByText('CYPHR is an enterprise RAG system.')).toBeInTheDocument();
    expect(screen.getByText('overview')).toBeInTheDocument();

    const copyBtn = screen.getByLabelText('Copy response');
    await user.click(copyBtn);
    expect(onCopy).toHaveBeenCalledWith(0, content);

    rerender(
      <ChatMessage
        index={0}
        role="assistant"
        content={content}
        copied
        onCopy={onCopy}
      />
    );
    expect(screen.getByLabelText('Response copied')).toBeInTheDocument();
    expect(screen.getByText('Copied')).toBeInTheDocument();
  });

  it('displays failed chip when error is true', () => {
    render(
      <ChatMessage
        role="assistant"
        content="Request timed out."
        error
      />
    );
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.queryByLabelText('Copy response')).not.toBeInTheDocument();
  });
});

describe('components/KnowledgeBaseModal', () => {
  const documents = [
    { filename: 'financial_q1.pdf' },
    { filename: 'financial_q2.pdf' },
    { filename: 'hr_policy.pdf' },
    { filename: 'engineering_spec.pdf' },
    { filename: 'security_whitepaper.pdf' },
    { filename: 'onboarding_guide.pdf' },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('filters documents by query and allows clearing filter', async () => {
    const user = userEvent.setup();
    render(
      <KnowledgeBaseModal
        isOpen
        onClose={vi.fn()}
        documents={documents}
      />
    );

    const searchInput = screen.getByPlaceholderText('Filter by filename');
    fireEvent.change(searchInput, { target: { value: 'financial' } });

    expect(screen.getByText('financial_q1')).toBeInTheDocument();
    expect(screen.getByText('financial_q2')).toBeInTheDocument();
    expect(screen.queryByText('hr_policy')).not.toBeInTheDocument();

    fireEvent.change(searchInput, { target: { value: 'nonexistent' } });
    expect(screen.getByText(/No document matches/i)).toBeInTheDocument();

    await user.click(screen.getByText('Clear filter'));
    expect(screen.getByText('hr_policy')).toBeInTheDocument();
  });

  it('deletes document with two-step confirmation', async () => {
    const user = userEvent.setup();
    const onRemoved = vi.fn();
    axios.delete.mockResolvedValueOnce({ data: { message: 'Deleted' } });

    render(
      <KnowledgeBaseModal
        isOpen
        onClose={vi.fn()}
        documents={documents}
        onRemoved={onRemoved}
      />
    );

    const trashBtn = screen.getByLabelText('Remove financial_q1.pdf');
    await user.click(trashBtn);

    const confirmBtn = screen.getByText('Remove');
    const keepBtn = screen.getByText('Keep');
    expect(confirmBtn).toBeInTheDocument();
    expect(keepBtn).toBeInTheDocument();

    await user.click(confirmBtn);
    expect(axios.delete).toHaveBeenCalledWith('/api/documents/financial_q1.pdf');

    await waitFor(() => {
      expect(onRemoved).toHaveBeenCalledWith('financial_q1.pdf');
      expect(toast.success).toHaveBeenCalledWith('Document removed');
    });
  });

  it('cancels armed delete when Keep is clicked', async () => {
    const user = userEvent.setup();
    render(
      <KnowledgeBaseModal
        isOpen
        onClose={vi.fn()}
        documents={documents}
      />
    );

    const trashBtn = screen.getByLabelText('Remove hr_policy.pdf');
    await user.click(trashBtn);
    expect(screen.getByText('Keep')).toBeInTheDocument();

    await user.click(screen.getByText('Keep'));
    expect(screen.queryByText('Keep')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Remove hr_policy.pdf')).toBeInTheDocument();
  });
});

describe('components/TopBar', () => {
  const mockProviders = {
    status: 'ready',
    providers: [
      {
        id: 'gemini',
        name: 'Google Gemini',
        models: [{ id: 'gemini-1.5-flash', name: 'Gemini 1.5 Flash' }],
      },
    ],
    providerId: 'gemini',
    modelId: 'gemini-1.5-flash',
    activeModel: { id: 'gemini-1.5-flash', name: 'Gemini 1.5 Flash' },
    setProviderId: vi.fn(),
    setModelId: vi.fn(),
  };

  it('renders title, contextLabel, document count chip, and controls in desktop mode', async () => {
    const user = userEvent.setup();
    const onOpenKnowledgeBase = vi.fn();

    render(
      <TopBar
        isDesktop
        onOpenMobileNav={vi.fn()}
        title="Q1 Earnings Call"
        contextLabel="3 documents ready to query"
        documentCount={3}
        onOpenKnowledgeBase={onOpenKnowledgeBase}
        providers={mockProviders}
      />
    );

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Q1 Earnings Call');
    expect(screen.getByText('3 documents ready to query')).toBeInTheDocument();
    expect(screen.queryByLabelText('Open navigation')).not.toBeInTheDocument();

    const kbChip = screen.getByLabelText('Open knowledge base, 3 documents indexed');
    await user.click(kbChip);
    expect(onOpenKnowledgeBase).toHaveBeenCalled();
  });

  it('renders hamburger menu button in mobile mode and triggers onOpenMobileNav', async () => {
    const user = userEvent.setup();
    const onOpenMobileNav = vi.fn();

    render(
      <TopBar
        isDesktop={false}
        onOpenMobileNav={onOpenMobileNav}
        title="Mobile Chat"
        contextLabel="No documents indexed yet"
        documentCount={0}
        onOpenKnowledgeBase={vi.fn()}
        providers={mockProviders}
      />
    );

    const hamburger = screen.getByLabelText('Open navigation');
    expect(hamburger).toBeInTheDocument();
    await user.click(hamburger);
    expect(onOpenMobileNav).toHaveBeenCalled();
  });
});

describe('components/FileUpload', () => {
  it('renders idle dropzone, handles drag interactions, and accepts file upload', async () => {
    const onUploaded = vi.fn();
    axios.post.mockResolvedValueOnce({
      data: { filename: 'annual_report.pdf', status: 'indexed' },
    });

    const { container } = render(<FileUpload onUploaded={onUploaded} />);

    const dropzone = screen.getByText('Drop a PDF here, or click to browse');
    expect(dropzone).toBeInTheDocument();

    // Test drag enter and drag leave
    fireEvent.dragEnter(dropzone, {
      dataTransfer: { types: ['Files'] },
    });
    expect(screen.getByText('Drop to index this PDF')).toBeInTheDocument();

    fireEvent.dragLeave(dropzone);
    expect(screen.getByText('Drop a PDF here, or click to browse')).toBeInTheDocument();

    // Test file input change
    const fileInput = container.querySelector('input[type="file"]');
    const validFile = new File(['%PDF-1.4 report content'], 'annual_report.pdf', {
      type: 'application/pdf',
    });

    fireEvent.change(fileInput, { target: { files: [validFile] } });

    await waitFor(() => {
      expect(axios.post).toHaveBeenCalledWith(
        '/upload',
        expect.any(FormData),
        expect.objectContaining({
          headers: { 'Content-Type': 'multipart/form-data' },
        })
      );
      expect(onUploaded).toHaveBeenCalledWith('annual_report.pdf');
    });
  });
});
