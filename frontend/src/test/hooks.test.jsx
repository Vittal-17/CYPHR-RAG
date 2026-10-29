import React from 'react';
import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import axios from 'axios';
import toast from 'react-hot-toast';
import useMediaQuery from '../hooks/useMediaQuery';
import useTheme from '../hooks/useTheme';
import useProviders from '../hooks/useProviders';
import useDocumentUpload from '../hooks/useDocumentUpload';

vi.mock('axios');
vi.mock('react-hot-toast');

describe('hooks/useMediaQuery', () => {
  it('returns false by default and handles media query changes', () => {
    let changeHandler = null;
    const mediaQueryList = {
      matches: false,
      media: '(min-width: 1024px)',
      addEventListener: vi.fn((event, handler) => {
        changeHandler = handler;
      }),
      removeEventListener: vi.fn(),
    };
    window.matchMedia = vi.fn().mockReturnValue(mediaQueryList);

    const { result, unmount } = renderHook(() => useMediaQuery('(min-width: 1024px)'));
    expect(result.current).toBe(false);

    // Simulate match change event
    act(() => {
      changeHandler?.({ matches: true });
    });
    expect(result.current).toBe(true);

    unmount();
    expect(mediaQueryList.removeEventListener).toHaveBeenCalledWith('change', changeHandler);
  });
});

describe('hooks/useTheme', () => {
  afterEach(() => {
    document.documentElement.removeAttribute('data-theme');
  });

  it('reads initial theme from data-theme attribute', () => {
    document.documentElement.setAttribute('data-theme', 'matrix');
    const { result } = renderHook(() => useTheme());
    expect(result.current).toBe('matrix');
  });

  it('updates when documentElement data-theme attribute mutates', async () => {
    document.documentElement.setAttribute('data-theme', 'light');
    const { result } = renderHook(() => useTheme());
    expect(result.current).toBe('light');

    act(() => {
      document.documentElement.setAttribute('data-theme', 'cyberpunk');
    });

    await waitFor(() => {
      expect(result.current).toBe('cyberpunk');
    });
  });
});

describe('hooks/useProviders', () => {
  const mockProvidersData = {
    providers: [
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
        models: [
          { id: 'llama-3.1-70b', name: 'Llama 3.1 70B' },
        ],
      },
    ],
    default_provider: 'gemini',
    default_model: 'gemini-1.5-flash',
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('remains idle and empty when enabled is false', () => {
    const { result } = renderHook(() => useProviders(false));
    expect(result.current.status).toBe('idle');
    expect(result.current.providers).toEqual([]);
    expect(result.current.providerId).toBe('');
    expect(result.current.modelId).toBe('');
  });

  it('fetches providers and sets defaults when enabled is true', async () => {
    axios.get.mockResolvedValueOnce({ data: mockProvidersData });

    const { result } = renderHook(() => useProviders(true));
    expect(result.current.status).toBe('loading');

    await waitFor(() => {
      expect(result.current.status).toBe('ready');
    });

    expect(result.current.providers).toHaveLength(2);
    expect(result.current.providerId).toBe('gemini');
    expect(result.current.modelId).toBe('gemini-1.5-flash');
    expect(result.current.activeProvider?.name).toBe('Google Gemini');
    expect(result.current.activeModel?.name).toBe('Gemini 1.5 Flash');
  });

  it('allows selecting another provider and updates active model to first of that provider', async () => {
    axios.get.mockResolvedValueOnce({ data: mockProvidersData });
    const { result } = renderHook(() => useProviders(true));

    await waitFor(() => expect(result.current.status).toBe('ready'));

    act(() => {
      result.current.selectProvider('groq');
    });

    expect(result.current.providerId).toBe('groq');
    expect(result.current.modelId).toBe('llama-3.1-70b');
    expect(result.current.activeProvider?.name).toBe('Groq');
  });

  it('allows selecting a specific model', async () => {
    axios.get.mockResolvedValueOnce({ data: mockProvidersData });
    const { result } = renderHook(() => useProviders(true));

    await waitFor(() => expect(result.current.status).toBe('ready'));

    act(() => {
      result.current.selectModel('gemini-1.5-pro');
    });

    expect(result.current.modelId).toBe('gemini-1.5-pro');
    expect(result.current.activeModel?.name).toBe('Gemini 1.5 Pro');
  });

  it('handles provider fetch error', async () => {
    axios.get.mockRejectedValueOnce(new Error('Network error'));
    const { result } = renderHook(() => useProviders(true));

    await waitFor(() => {
      expect(result.current.status).toBe('error');
    });
  });
});

describe('hooks/useDocumentUpload', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('validates files before upload', () => {
    const { result } = renderHook(() => useDocumentUpload());

    expect(result.current.validate(null)).toBe('No file selected.');

    const txtFile = new File(['hello'], 'test.txt', { type: 'text/plain' });
    expect(result.current.validate(txtFile)).toBe('Only PDF files can be added to the knowledge base.');

    const emptyPdf = new File([], 'empty.pdf', { type: 'application/pdf' });
    expect(result.current.validate(emptyPdf)).toBe('That file is empty.');

    const bigBuffer = new Uint8Array(26 * 1024 * 1024);
    const bigPdf = new File([bigBuffer], 'huge.pdf', { type: 'application/pdf' });
    expect(result.current.validate(bigPdf)).toContain('larger than 25 MB');

    const validPdf = new File(['%PDF-1.4 content'], 'valid.pdf', { type: 'application/pdf' });
    expect(result.current.validate(validPdf)).toBeNull();
  });

  it('handles successful file upload and progress transitions', async () => {
    const onUploaded = vi.fn();
    let progressCallback = null;

    axios.post.mockImplementationOnce((url, data, config) => {
      progressCallback = config.onUploadProgress;
      // Simulate halfway progress
      progressCallback?.({ loaded: 50, total: 100 });
      return Promise.resolve({ data: { message: 'Success' } });
    });

    const { result } = renderHook(() => useDocumentUpload({ onUploaded }));
    const validPdf = new File(['%PDF-1.4 dummy'], 'sample.pdf', { type: 'application/pdf' });

    let promise;
    await act(async () => {
      promise = result.current.upload(validPdf);
    });

    const success = await promise;
    expect(success).toBe(true);
    expect(result.current.status).toBe('success');
    expect(onUploaded).toHaveBeenCalledWith('sample.pdf');
    expect(toast.success).toHaveBeenCalledWith('sample.pdf added to your knowledge base');
  });

  it('handles upload errors and displays message', async () => {
    axios.post.mockRejectedValueOnce({
      response: { data: { detail: 'Corrupt PDF structure' } },
    });

    const { result } = renderHook(() => useDocumentUpload());
    const validPdf = new File(['corrupt data'], 'bad.pdf', { type: 'application/pdf' });

    let success;
    await act(async () => {
      success = await result.current.upload(validPdf);
    });

    expect(success).toBe(false);
    expect(result.current.status).toBe('error');
    expect(result.current.error).toBe('Corrupt PDF structure');
    expect(toast.error).toHaveBeenCalledWith('Corrupt PDF structure');
  });

  it('cancels active upload', async () => {
    axios.post.mockImplementationOnce(() => new Promise(() => {}));

    const { result } = renderHook(() => useDocumentUpload());
    const validPdf = new File(['%PDF'], 'test.pdf', { type: 'application/pdf' });

    act(() => {
      result.current.upload(validPdf);
    });

    expect(result.current.status).toBe('uploading');

    act(() => {
      result.current.cancel();
    });

    expect(result.current.status).toBe('idle');
  });
});
