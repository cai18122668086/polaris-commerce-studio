export type UploadProgress = { loaded: number; total?: number; complete: boolean };

// Use the runtime XHR, including SuperTokens' installed refresh/CSRF interceptor.
// openapi-fetch still applies request metadata and final 401 handling. Never use
// an original/unwrapped XHR or copy authentication data out of the browser.
export function uploadWithProgress(body: FormData, progress: (value: UploadProgress) => void) {
  return (request: Request): Promise<Response> => new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const abort = () => { xhr.abort(); finish(); reject(new DOMException("Upload aborted", "AbortError")); };
    const finish = () => request.signal.removeEventListener("abort", abort);
    if (request.signal.aborted) { abort(); return; }
    xhr.open(request.method, request.url);
    xhr.withCredentials = request.credentials === "include";
    request.headers.forEach((value, key) => {
      // XHR must choose the boundary for the actual FormData it sends.
      if (key.toLowerCase() !== "content-type") xhr.setRequestHeader(key, value);
    });
    xhr.upload.onprogress = event => progress({ loaded: event.loaded, total: event.lengthComputable ? event.total : undefined, complete: false });
    xhr.upload.onload = event => progress({ loaded: event.loaded, total: event.lengthComputable ? event.total : undefined, complete: true });
    xhr.onload = () => {
      finish();
      if (xhr.status === 0) { reject(new TypeError("Upload connection failed")); return; }
      const headers = new Headers();
      xhr.getAllResponseHeaders().trim().split(/[\r\n]+/).forEach(line => {
        const colon = line.indexOf(":");
        if (colon > 0) headers.append(line.slice(0, colon).trim(), line.slice(colon + 1).trim());
      });
      resolve(new Response([204, 205, 304].includes(xhr.status) ? null : xhr.responseText, { status: xhr.status, statusText: xhr.statusText, headers }));
    };
    xhr.onerror = () => { finish(); reject(new TypeError("Upload connection failed")); };
    xhr.onabort = () => { finish(); reject(new DOMException("Upload aborted", "AbortError")); };
    xhr.ontimeout = () => { finish(); reject(new DOMException("Upload timed out", "TimeoutError")); };
    request.signal.addEventListener("abort", abort, { once: true });
    try { xhr.send(body); } catch (error) { finish(); reject(error); }
  });
}
