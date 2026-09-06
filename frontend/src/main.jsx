import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'
import axios from 'axios'
import { GoogleOAuthProvider } from '@react-oauth/google'

axios.defaults.withCredentials = true;
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";
axios.defaults.baseURL = API_BASE_URL;

let csrfToken = null;
let csrfPromise = null;

const fetchCsrfToken = () => {
  if (!csrfPromise) {
    csrfPromise = axios.get('/api/csrf').then(response => {
      if (response.data && response.data.csrf_token) {
        csrfToken = response.data.csrf_token;
      }
      return csrfToken;
    }).catch(() => {
      csrfPromise = null;
    });
  }
  return csrfPromise;
};

fetchCsrfToken();

axios.interceptors.request.use(async (config) => {
  // Prevent infinite loop when fetching csrf token itself
  if (config.url === '/api/csrf') {
    return config;
  }

  const methods = ['post', 'put', 'patch', 'delete'];
  if (methods.includes(config.method?.toLowerCase())) {
    if (!csrfToken) {
      await fetchCsrfToken();
    }
    if (csrfToken) {
      config.headers['X-CSRF-Token'] = csrfToken;
    }
  }
  return config;
});

axios.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response && error.response.status === 429) {
      const headers = error.response.headers;
      let retryAfter;
      if (headers && typeof headers.get === 'function') {
        retryAfter = headers.get('retry-after') || headers.get('Retry-After');
      } else if (headers) {
        retryAfter = headers['retry-after'] || headers['Retry-After'];
      }

      if (retryAfter && !isNaN(retryAfter)) {
        const seconds = parseInt(retryAfter, 10);
        if (seconds > 0) {
          let durationStr;
          if (seconds < 60) {
            durationStr = `${seconds} second${seconds !== 1 ? 's' : ''}`;
          } else if (seconds === 60) {
            durationStr = '1 minute';
          } else if (seconds < 3600) {
            const minutes = Math.round(seconds / 60);
            durationStr = `about ${minutes} minute${minutes !== 1 ? 's' : ''}`;
          } else {
            const hours = Math.round(seconds / 3600);
            durationStr = `about ${hours} hour${hours !== 1 ? 's' : ''}`;
          }

          if (error.response.data && typeof error.response.data.detail === 'string') {
            // Check to avoid duplicating if interceptor runs twice (though it shouldn't)
            if (!error.response.data.detail.includes('Try again in')) {
              error.response.data.detail = `${error.response.data.detail} Try again in ${durationStr}.`;
            }
          }
        }
      }
    }
    return Promise.reject(error);
  }
);

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <GoogleOAuthProvider clientId={import.meta.env.VITE_GOOGLE_CLIENT_ID || "YOUR_GOOGLE_CLIENT_ID"}>
      <App />
    </GoogleOAuthProvider>
  </React.StrictMode>,
)
