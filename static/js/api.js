// One place for talking to the Flask backend, with friendly errors.
export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

export async function api(url, { method = 'GET', body } = {}) {
  let res;
  try {
    res = await fetch(url, {
      method,
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new ApiError('Cannot reach the app server. Make sure it is still running, then try again.', 0);
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* non-JSON body */ }
  if (!res.ok) throw new ApiError((data && data.error) || `Request failed (${res.status}).`, res.status);
  return data;
}
