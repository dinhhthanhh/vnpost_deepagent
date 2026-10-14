const DEFAULT_KEY = "458d41f783134eb3715cc8f371af8351";

export async function request(path, key = DEFAULT_KEY, options = {}) {
  const headers = { ...(options.headers || {}) };
  const activeKey = key || DEFAULT_KEY;
  if (activeKey) headers["X-API-Key"] = activeKey;
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try { const data = await response.json(); message = typeof data.detail === "string" ? data.detail : "Dữ liệu gửi chưa hợp lệ."; } catch {}
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
