// Small wrapper around the server API calls.
// The X-Requested-With header is required by the server for every request that
// changes data (CSRF protection).
// The computer cannot be reached (Wi-Fi, server off): the only case in which a
// request is worth sending again. Any other error is not retried.
export class NetworkError extends Error {}

async function send(url, options) {
  try {
    return await fetch(url, options);
  } catch {
    throw new NetworkError('Rete non raggiungibile');
  }
}

export class ApiError extends Error {
  // data: the JSON body of the response (e.g. data.reason for a closed session)
  constructor(message, status, data = null) { super(message); this.status = status; this.data = data || {}; }
}

async function handle(resp) {
  if (resp.status === 401) {
    location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
    throw new ApiError('Sessione scaduta', 401);
  }
  let data = null;
  try { data = await resp.json(); } catch { /* response is not JSON */ }
  if (!resp.ok) throw new ApiError((data && data.error) || `Errore ${resp.status}`, resp.status, data);
  return data;
}

export async function apiGet(url, params = {}) {
  const qs = new URLSearchParams(params).toString();
  return handle(await send(qs ? `${url}?${qs}` : url, { credentials: 'same-origin' }));
}

export async function apiPost(url, body) {
  const isForm = body instanceof FormData;
  return handle(await send(url, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'X-Requested-With': 'notes-app', ...(isForm ? {} : { 'Content-Type': 'application/json' }) },
    body: isForm ? body : JSON.stringify(body),
  }));
}

export function parentOf(path) {
  const i = path.lastIndexOf('/');
  return i < 0 ? '' : path.slice(0, i);
}

// Like apiPost, but with progress: fetch does not say how much has been sent or
// received, XMLHttpRequest does. Same rules (anti-CSRF header, session).
//   onUpload(sent, total)         while sending (for example a PDF to import)
//   onWaiting()                   sending finished: the computer is working
//   onDownload(received, total)   while receiving the response
export function apiPostProgress(url, body, { onUpload, onWaiting, onDownload } = {}) {
  return new Promise((resolve, reject) => {
    const isForm = body instanceof FormData;
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    xhr.withCredentials = true;
    xhr.setRequestHeader('X-Requested-With', 'notes-app');
    if (!isForm) xhr.setRequestHeader('Content-Type', 'application/json');
    if (onUpload) xhr.upload.onprogress = (e) => onUpload(e.loaded, e.lengthComputable ? e.total : 0);
    if (onWaiting) xhr.upload.onload = () => onWaiting();
    if (onDownload) xhr.onprogress = (e) => onDownload(e.loaded, e.lengthComputable ? e.total : 0);
    xhr.onerror = () => reject(new NetworkError('Rete non raggiungibile'));
    xhr.onload = () => {
      if (xhr.status === 401) {
        location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
        reject(new ApiError('Sessione scaduta', 401));
        return;
      }
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch { /* response is not JSON */ }
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new ApiError((data && data.error) || `Errore ${xhr.status}`, xhr.status, data));
      } else {
        resolve(data);
      }
    };
    xhr.send(isForm ? body : JSON.stringify(body));
  });
}

// Download of a binary file (a document's PDF) with progress.
export function apiGetBinary(url, params = {}, onProgress = null) {
  return new Promise((resolve, reject) => {
    const qs = new URLSearchParams(params).toString();
    const xhr = new XMLHttpRequest();
    xhr.open('GET', qs ? `${url}?${qs}` : url);
    xhr.withCredentials = true;
    xhr.responseType = 'arraybuffer';
    if (onProgress) xhr.onprogress = (e) => onProgress(e.loaded, e.lengthComputable ? e.total : 0);
    xhr.onerror = () => reject(new NetworkError('Rete non raggiungibile'));
    xhr.onload = () => {
      if (xhr.status === 401) {
        location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
        reject(new ApiError('Sessione scaduta', 401));
      } else if (xhr.status < 200 || xhr.status >= 300) {
        let data = null;
        try { data = JSON.parse(new TextDecoder().decode(xhr.response)); } catch { /* not JSON */ }
        reject(new ApiError((data && data.error) || `Errore ${xhr.status}`, xhr.status, data));
      } else {
        resolve(new Uint8Array(xhr.response));
      }
    };
    xhr.send();
  });
}

// Unexpected errors are reported to the computer (client-errors.log in its data
// folder): on the iPad nobody sees the browser console. At most a few per minute.
const reported = [];
export function reportError(message, source, stack) {
  const now = Date.now();
  while (reported.length && now - reported[0] > 60000) reported.shift();
  if (reported.length >= 5) return;
  reported.push(now);
  try {
    fetch('/api/client-error', {
      method: 'POST', credentials: 'same-origin', keepalive: true,
      headers: { 'X-Requested-With': 'notes-app', 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: String(message).slice(0, 2000), source: String(source || '').slice(0, 500),
        stack: String(stack || '').slice(0, 4000), page: location.pathname + location.search, agent: navigator.userAgent }),
    }).catch(() => {});
  } catch { /* nothing else to do */ }
}
