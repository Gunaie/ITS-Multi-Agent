import axios from 'axios'

const service = axios.create({
  baseURL: '/app',
  timeout: 100000
})

service.interceptors.request.use(
  config => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`
    }
    return config
  },
  error => Promise.reject(error)
)

service.interceptors.response.use(
  response => response.data,
  error => {
    // 只有在非登录接口返回 401 时才强制刷新，防止登录失败时死循环
    const isLoginRequest = error.config.url.includes('/auth/login')
    if (error.response && error.response.status === 401 && !isLoginRequest) {
      localStorage.removeItem('token')
      window.location.reload()
    }
    console.error('App Request Error:', error)
    return Promise.reject(error)
  }
)

export function login(username, password) {
  const params = new URLSearchParams()
  params.append('username', username)
  params.append('password', password)
  return service({
    url: '/auth/login',
    method: 'post',
    data: params,
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded'
    }
  })
}

export function register(username, password) {
  return service({
    url: '/auth/register',
    method: 'post',
    data: { username, password }
  })
}

export function chatWithAgent(data) {
  return service({
    url: '/chat',
    method: 'post',
    data
  })
}

export function getSessions() {
  return service({
    url: '/sessions',
    method: 'get',
    params: { app_type: 'agent' }
  })
}

export function getSessionDetail(sessionId) {
  return service({
    url: `/sessions/${sessionId}`,
    method: 'get'
  })
}

export function deleteSession(sessionId) {
  return service({
    url: `/sessions/${sessionId}`,
    method: 'delete',
    params: { app_type: 'agent' }
  })
}

export function updateSessionTitle(sessionId, title) {
  return service({
    url: `/sessions/${sessionId}`,
    method: 'patch',
    data: { title, app_type: 'agent' }
  })
}

export function getLocationByIp() {
  return service({
    url: '/location/ip',
    method: 'get',
    timeout: 8000
  })
}

export function getLocationConfig() {
  return service({
    url: '/location/config',
    method: 'get',
    timeout: 8000
  })
}

export function chatStreamWithAgent(data, onMessage, onDone, onError) {
  const controller = new AbortController();
  const signal = controller.signal;
  const token = localStorage.getItem('token');

  fetch('/app/chat_stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': token ? `Bearer ${token}` : '',
    },
    body: JSON.stringify(data),
    signal
  }).then(response => {
    if (response.status === 401) {
      localStorage.removeItem('token');
      window.location.reload();
      return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    function read() {
      reader.read().then(({ done, value }) => {
        if (done) {
          if (buffer) {
            processLines(buffer);
          }
          onDone();
          return;
        }

        buffer += decoder.decode(value, { stream: true });
        buffer = processLines(buffer);
        read();
      }).catch(error => {
        if (error.name === 'AbortError') {
          console.log('Stream aborted');
        } else {
          onError(error);
        }
      });
    }

    function processLines(data) {
      const lines = data.split('\n');
      // 最后一行可能是不完整的，保留在 buffer 中
      const lastLine = lines.pop();
      
      for (const line of lines) {
        const trimmedLine = line.trim();
        if (!trimmedLine) continue;

        if (trimmedLine.startsWith('data: ')) {
          const dataStr = trimmedLine.slice(6).trim();
          if (dataStr === '[DONE]') {
            onDone();
            return ''; // 清空 buffer
          }
          try {
            const eventData = JSON.parse(dataStr);
            onMessage(eventData);
          } catch (e) {
            console.error('Parse SSE error:', e, dataStr);
          }
        }
      }
      return lastLine;
    }
    read();
  }).catch(error => {
    onError(error);
  });

  return controller;
}
