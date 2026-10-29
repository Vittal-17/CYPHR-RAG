import { describe, it, expect, beforeEach, vi } from 'vitest';
import { getAccessToken, setAccessToken, clearAccessToken } from '../utils/token';
import { withAuthDelay } from '../utils/authDelay';

describe('token utils', () => {
  beforeEach(() => {
    clearAccessToken();
    localStorage.clear();
  });

  it('stores and retrieves access token from memory and localStorage', () => {
    expect(getAccessToken()).toBeNull();

    setAccessToken('test-jwt-token-123');
    expect(getAccessToken()).toBe('test-jwt-token-123');
    expect(localStorage.getItem('cyphr_access_token')).toBe('test-jwt-token-123');
  });

  it('reads token from localStorage if in-memory token is empty', () => {
    localStorage.setItem('cyphr_access_token', 'persisted-token');
    // Clear memory reference without clearing localStorage
    clearAccessToken();
    localStorage.setItem('cyphr_access_token', 'persisted-token');

    expect(getAccessToken()).toBe('persisted-token');
  });

  it('clears token properly from both memory and localStorage', () => {
    setAccessToken('temp-token');
    expect(getAccessToken()).toBe('temp-token');

    clearAccessToken();
    expect(getAccessToken()).toBeNull();
    expect(localStorage.getItem('cyphr_access_token')).toBeNull();
  });

  it('handles null or empty token passed to setAccessToken', () => {
    setAccessToken('valid-token');
    setAccessToken(null);
    expect(getAccessToken()).toBeNull();
    expect(localStorage.getItem('cyphr_access_token')).toBeNull();
  });

  it('tolerates localStorage exceptions in strict privacy environments', () => {
    const originalGetItem = localStorage.getItem;
    const originalSetItem = localStorage.setItem;
    const originalRemoveItem = localStorage.removeItem;

    localStorage.getItem = vi.fn().mockImplementation(() => {
      throw new Error('SecurityError: Access is denied');
    });
    localStorage.setItem = vi.fn().mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    localStorage.removeItem = vi.fn().mockImplementation(() => {
      throw new Error('SecurityError');
    });

    expect(() => setAccessToken('fallback-token')).not.toThrow();
    expect(getAccessToken()).toBe('fallback-token');
    expect(() => clearAccessToken()).not.toThrow();

    localStorage.getItem = originalGetItem;
    localStorage.setItem = originalSetItem;
    localStorage.removeItem = originalRemoveItem;
  });
});

describe('authDelay utils', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('resolves after at least 4000ms delay for fast actions', async () => {
    const action = vi.fn().mockResolvedValue('success-payload');

    const promise = withAuthDelay(action);
    expect(action).toHaveBeenCalled();

    // Fast-forward by 3999ms - should still be pending
    vi.advanceTimersByTime(3999);
    let resolved = false;
    promise.then(() => {
      resolved = true;
    });
    await Promise.resolve();
    expect(resolved).toBe(false);

    // Advance 1ms more to reach 4000ms
    vi.advanceTimersByTime(1);
    await Promise.resolve();
    const result = await promise;
    expect(result).toBe('success-payload');
  });

  it('waits for minDelay even when action fails', async () => {
    const actionError = new Error('Auth failed');
    const action = vi.fn().mockRejectedValue(actionError);

    const promise = withAuthDelay(action);
    let errorCaught = null;
    promise.catch((err) => {
      errorCaught = err;
    });

    vi.advanceTimersByTime(3999);
    await Promise.resolve();
    expect(errorCaught).toBeNull();

    vi.advanceTimersByTime(1);
    await Promise.resolve();
    await expect(promise).rejects.toThrow('Auth failed');
  });
});
