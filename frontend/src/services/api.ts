import axios from 'axios';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

const getSessionId = () => {
  if (typeof window === 'undefined') return 'default_session';
  let sid = sessionStorage.getItem('session_id');
  if (!sid) {
    sid = (typeof crypto !== 'undefined' && crypto.randomUUID) 
          ? crypto.randomUUID() 
          : Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
    sessionStorage.setItem('session_id', sid);
  }
  return sid;
};

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 300000,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.request.use((config) => {
  config.headers['X-Session-Id'] = getSessionId();
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const errorMsg = 
      error.response?.data?.detail 
      || (typeof error.response?.data === 'string' ? error.response.data : (error.response?.data ? JSON.stringify(error.response.data) : null)) 
      || error.message;

    if (error.code === 'ERR_NETWORK' || error.message === 'Network Error') {
      console.warn(`API Connection Warning: Could not connect to backend at ${API_BASE_URL}. Ensure backend server is running.`);
    } else {
      console.warn('API Response Warning:', errorMsg);
    }
    return Promise.reject(error);
  }
);

