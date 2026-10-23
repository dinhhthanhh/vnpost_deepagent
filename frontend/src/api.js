export async function request(path, key = null, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (key) {
    headers["X-API-Key"] = key;
  }
  const fetchOptions = {
    credentials: "same-origin",
    ...options,
    headers,
  };
  const response = await fetch(path, fetchOptions);
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") {
        message = data.detail;
      } else if (Array.isArray(data.detail)) {
        message = data.detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
      } else if (data.message) {
        message = data.message;
      } else {
        message = "Dữ liệu gửi chưa hợp lệ.";
      }
    } catch {}
    throw new Error(message);
  }
  return response;
}

export function parseSSE(buffer) {
  const frames = buffer.replace(/\r\n/g, "\n").split("\n\n");
  const pending = frames.pop();
  const items = [];
  for (const frame of frames) {
    const data = frame.split("\n").filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n");
    if (data) items.push(JSON.parse(data));
  }
  return { items, pending };
}

export async function streamChat(payload, key, onEvent, signal) {
  const response = await request("/api/chat/stream", key, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal,
  });
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let pending = "", terminal = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      pending += decoder.decode(value, { stream: true });
      const parsed = parseSSE(pending);
      pending = parsed.pending;
      for (const item of parsed.items) {
        onEvent(item);
        if (item.type === "done" || item.type === "error") terminal = true;
      }
    }
    if (!terminal) throw new Error("Kết nối bị ngắt trước khi hoàn tất. Có thể thử lại.");
  } finally { reader.releaseLock(); }
}

export async function audioBlob(url, key) {
  const response = await request(url, key);
  return URL.createObjectURL(await response.blob());
}

export async function transcribeAudio(blob, key = null, filename = "audio.webm") {
  const formData = new FormData();
  formData.append("file", blob, filename);
  const response = await request("/api/voice/transcribe", key, {
    method: "POST",
    body: formData,
  });
  return await response.json();
}

export async function truncateSession(sessionId, index, key = null) {
  const response = await request(`/api/sessions/${encodeURIComponent(sessionId)}/truncate`, key, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ index }),
  });
  return await response.json();
}
