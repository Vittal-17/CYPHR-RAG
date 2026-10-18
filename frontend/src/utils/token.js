const TOKEN_KEY = 'cyphr_access_token';

let inMemoryToken = null;

export const getAccessToken = () => {
  if (inMemoryToken) {
    return inMemoryToken;
  }
  try {
    const stored = localStorage.getItem(TOKEN_KEY);
    if (stored) {
      inMemoryToken = stored;
      return stored;
    }
  } catch {
    // localStorage might be blocked in strict privacy modes
  }
  return null;
};

export const setAccessToken = (token) => {
  inMemoryToken = token || null;
  try {
    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_KEY);
    }
  } catch {
    // localStorage might be blocked in strict privacy modes
  }
};

export const clearAccessToken = () => {
  inMemoryToken = null;
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    // localStorage might be blocked in strict privacy modes
  }
};
