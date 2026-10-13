import React, { useEffect, useRef, useState } from "react";
import { ArrowUp, BookOpen, FileText, Headphones, Image as ImageIcon, MessageSquare, Plus, ShieldCheck, Square, Trash2, Upload, Volume2, X } from "lucide-react";
import { audioBlob, request, streamChat } from "./api";
import { playWavStream } from "./wav-stream";

const agentNames = { "rag-agent": "Tìm tài liệu", "analyst-agent": "Phân tích", "writer-agent": "Soạn nội dung" };
const suggestions = ["Tài liệu này quy định những bước xử lý nào?", "So sánh hai quy trình trong tài liệu.", "Tóm tắt các nội dung quan trọng và trích nguồn."];

function AnswerText({ text }) {
  return <div className="answer-text">{text.split(/(\[S\d+\])/g).map((part, i) => /^\[S\d+\]$/.test(part) ? <span key={i} className="citation">{part}</span> : part)}</div>;
}

export default function App() {
  const [key, setKey] = useState("");
  const [draftKey, setDraftKey] = useState(""), [health, setHealth] = useState(null);
  const [messages, setMessages] = useState([]), [input, setInput] = useState(""), [busy, setBusy] = useState(false);
  const [grounded, setGrounded] = useState(true), [routeMode, setRouteMode] = useState("auto");
  const [voice, setVoice] = useState(false), [voices, setVoices] = useState([]), [voiceName, setVoiceName] = useState("maichi");
  const [notice, setNotice] = useState(""), [events, setEvents] = useState([]), [uploading, setUploading] = useState(false);
  const [session, setSession] = useState(() => localStorage.getItem("chat-session") || null);
  const [sessions, setSessions] = useState([]);
  const [sessionDocs, setSessionDocs] = useState([]);
  const [showDocTab, setShowDocTab] = useState(false);
  const [streamingAudio, setStreamingAudio] = useState(false);
  const [attachedImage, setAttachedImage] = useState(null);
  const end = useRef(), uploadInput = useRef(), imageInput = useRef(), abort = useRef(), audio = useRef(), blobs = useRef([]), stream = useRef(null);

  const releaseBlobs = () => { blobs.current.forEach(URL.revokeObjectURL); blobs.current = []; };
  const stopAudio = () => {
    stream.current?.controller.abort(); stream.current?.context.close().catch(() => {}); stream.current = null;
    if (audio.current) { audio.current.pause(); audio.current = null; }
    setStreamingAudio(false);
  };

  useEffect(() => () => { abort.current?.abort(); stopAudio(); releaseBlobs(); }, []);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, events]);
  useEffect(() => { request("/api/health", "").then(r => r.json()).then(setHealth).catch(e => setNotice(e.message)); }, []);

  async function loadSessions(activeKey = key) {
    try {
      const data = await request("/api/sessions", activeKey).then(r => r.json());
      setSessions(data.sessions || []);
    } catch {
      setSessions([]);
    }
  }

  async function loadSessionDocs(sid, activeKey = key) {
    if (!sid) { setSessionDocs([]); return; }
    try {
      const data = await request(`/api/documents?session_id=${sid}&only_session=true`, activeKey).then(r => r.json());
      setSessionDocs(data.documents || []);
    } catch {
      setSessionDocs([]);
    }
  }

  async function loadVoices(activeKey = key) {
    try {
      const voiceResponse = await request("/api/tts/voices", activeKey).then(r => r.json()).catch(() => ({ voices: [] }));
      setVoices(voiceResponse.voices || []);
    } catch {
      setVoices([]);
    }
  }

  async function selectSession(sid) {
    if (busy || sid === session) return;
    abort.current?.abort(); stopAudio(); releaseBlobs();
    setSession(sid); localStorage.setItem("chat-session", sid);
    setNotice(""); setAttachedImage(null); setEvents([]);
    try {
      const data = await request(`/api/sessions/${sid}`, key).then(r => r.json());
      setMessages(data.messages.map(m => ({ ...m, id: m.request_id || crypto.randomUUID(), text: m.content, answer: m.content })));
      await loadSessionDocs(sid, key);
    } catch (e) { setNotice(e.message); }
  }

  async function deleteSession(sid) {
    if (!confirm("Xóa phiên trò chuyện này?")) return;
    try {
      await request(`/api/sessions/${sid}`, key, { method: "DELETE" });
      if (session === sid) {
        newChat();
      }
      await loadSessions(key);
    } catch (e) { setNotice(e.message); }
  }

  useEffect(() => {
    loadSessions(key);
    loadVoices(key);
    if (session) {
      request(`/api/sessions/${session}`, key).then(r => r.json()).then(data => {
        setMessages(data.messages.map(m => ({ ...m, id: m.request_id || crypto.randomUUID(), text: m.content, answer: m.content })));
      }).catch(() => {});
      loadSessionDocs(session, key);
    }
  }, [key]);

  async function newChat() {
    abort.current?.abort(); stopAudio(); releaseBlobs();
    setSession(null); localStorage.removeItem("chat-session");
    setMessages([]); setEvents([]); setNotice(""); setAttachedImage(null);
    setSessionDocs([]); setShowDocTab(false);
  }

  function handleImageSelect(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setNotice("Chỉ hỗ trợ tệp định dạng hình ảnh (PNG, JPG, WebP...).");
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      setNotice("Kích thước ảnh tối đa là 8MB.");
      return;
    }
    const reader = new FileReader();
    reader.onload = ev => setAttachedImage(ev.target.result);
    reader.readAsDataURL(file);
    e.target.value = "";
  }

  function handlePaste(e) {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
      if (item.type.startsWith("image/")) {
        const file = item.getAsFile();
        if (file) {
          const reader = new FileReader();
          reader.onload = ev => setAttachedImage(ev.target.result);
          reader.readAsDataURL(file);
          e.preventDefault();
          break;
        }
      }
    }
  }

  async function uploadFiles(files) {
    setUploading(true); setNotice("");
    try {
      let currentSession = session;
      if (!currentSession) {
        currentSession = crypto.randomUUID();
        setSession(currentSession);
        localStorage.setItem("chat-session", currentSession);
      }
      for (const file of files) {
        const body = new FormData();
        body.append("file", file);
        body.append("session_id", currentSession);
        await request(`/api/documents?session_id=${currentSession}`, key, { method: "POST", body });
      }
      await loadSessionDocs(currentSession);
      setShowDocTab(true);
      setNotice("Tải tài liệu thành công. Tài liệu này sẽ được dùng riêng trong phiên chat hiện tại.");
    } catch (e) { setNotice(e.message); }
    finally { setUploading(false); if (uploadInput.current) uploadInput.current.value = ""; }
  }

  async function deleteDoc(doc) {
    if (!confirm(`Xóa tài liệu “${doc.filename}” khỏi phiên chat này?`)) return;
    try {
      await request(`/api/documents/${doc.id}`, key, { method: "DELETE" });
      await loadSessionDocs(session);
    } catch (e) { setNotice(e.message); }
  }

  async function prepareAudio(url, id) {
    try {
      const blob = await audioBlob(url, key); blobs.current.push(blob);
      setMessages(previous => previous.map(m => m.id === id ? { ...m, blob } : m));
      stopAudio(); audio.current = new Audio(blob);
      audio.current.play().catch(() => setNotice("Âm thanh đã sẵn sàng. Bấm Nghe để phát."));
    } catch (e) { setNotice(e.message); }
  }

  async function send(event, text = input) {
    event?.preventDefault(); text = text.trim(); if ((!text && !attachedImage) || busy) return;
    if (!text && attachedImage) text = "Hãy phân tích hình ảnh này.";
    const id = crypto.randomUUID(); setInput(""); setBusy(true); setNotice(""); setEvents([]);
    const currentImage = attachedImage; setAttachedImage(null);
    setMessages(previous => [...previous, { id: crypto.randomUUID(), role: "user", text, image: currentImage }, { id, role: "assistant", pending: true }]);
    abort.current = new AbortController(); let receivedAnswer = false;
    try {
      await streamChat({ message: text, image: currentImage, session_id: session, grounded, mode: routeMode, voice, voice_name: voiceName }, key, item => {
        if (item.type === "start") {
          setSession(item.session_id);
          localStorage.setItem("chat-session", item.session_id);
        }
        if (item.type === "answer" || item.type === "done") {
          receivedAnswer = true;
          setMessages(previous => previous.map(m => m.id === id ? { ...m, ...item.data, pending: false } : m));
          if (item.type === "done") {
            loadSessions(key);
            if (item.data.warnings?.length) setNotice(item.data.warnings.join(" "));
          }
        } else if (item.type === "speech_ready") prepareAudio(item.audio_url, id);
        else if (item.type === "speech_error" || item.type === "error") {
          setNotice(item.message); if (item.type === "error") setMessages(previous => previous.map(m => m.id === id ? { ...m, pending: false, error: item.message } : m));
        } else setEvents(previous => [...previous.slice(-30), item]);
      }, abort.current.signal);
    } catch (e) {
      const message = e.name === "AbortError" ? "Đã dừng yêu cầu." : e.message;
      setNotice(message);
      if (!receivedAnswer) setMessages(previous => previous.map(m => m.id === id ? { ...m, pending: false, error: message } : m));
    } finally {
      setBusy(false);
      loadSessions(key);
    }
  }

  async function readAnswer(message) {
    stopAudio();
    if (message.blob) { audio.current = new Audio(message.blob); audio.current.play().catch(e => setNotice(e.message)); return; }
    try {
      setNotice("Đang tạo giọng đọc…");
      const data = await request("/api/tts", key, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: message.answer, voice: voiceName }) }).then(r => r.json());
      await prepareAudio(data.audio_url, message.id); setNotice("");
    } catch (e) { setNotice(e.message); }
  }

  async function streamAnswer(message) {
    stopAudio(); const controller = new AbortController(), context = new AudioContext();
    stream.current = { controller, context }; setStreamingAudio(true);
    const started = performance.now();
    try {
      await context.resume();
      const response = await request("/api/tts/stream", key, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: message.answer, voice: voiceName }), signal: controller.signal });
      await playWavStream(response, context, { signal: controller.signal, onFirstAudio: () => setNotice(`Bắt đầu phát sau ${((performance.now() - started) / 1000).toFixed(2)} giây.`) });
    } catch (e) { if (e.name !== "AbortError") setNotice(e.message); }
    finally { await context.close().catch(() => {}); if (stream.current?.controller === controller) { stream.current = null; setStreamingAudio(false); } }
  }

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-icon"><BookOpen size={21} /></div>
        <div><strong>VNPost</strong><span>Trợ lý AI</span></div>
      </div>

      <button className="new-chat" disabled={busy} onClick={newChat}>
        <Plus size={17} /> Cuộc trò chuyện mới
      </button>

      {/* 1. Phần Giọng đọc được đưa lên trên */}
      <div className="sidebar-section">
        <div className="section-label">GIỌNG ĐỌC</div>
        <select aria-label="Giọng đọc" value={voiceName} onChange={e => setVoiceName(e.target.value)}>
          {voices.length ? voices.map(v => <option key={v.name} value={v.name}>{v.name}</option>) : <option value="maichi">maichi</option>}
        </select>
        <label className="check">
          <input type="checkbox" checked={voice} onChange={e => setVoice(e.target.checked)} disabled={!health?.tts_enabled} />
          Tự đọc câu trả lời
        </label>
        {!health?.tts_enabled && <p className="small muted">Giọng đọc chưa được bật trên máy chủ.</p>}
      </div>

      {/* 2. Lịch sử các session chat */}
      <div className="sidebar-section" style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
        <div className="section-label">LỊCH SỬ TRÒ CHUYỆN <span>{sessions.length}</span></div>
        <div className="session-list">
          {sessions.map(s => (
            <div
              key={s.id}
              className={`session-item ${session === s.id ? "active" : ""}`}
              onClick={() => selectSession(s.id)}
            >
              <MessageSquare size={14} style={{ flexShrink: 0 }} />
              <span title={s.title}>{s.title}</span>
              <button
                className="delete-session-btn"
                title="Xóa phiên trò chuyện"
                onClick={(e) => { e.stopPropagation(); deleteSession(s.id); }}
              >
                <X size={12} />
              </button>
            </div>
          ))}
          {!sessions.length && <div className="empty-docs">Chưa có phiên trò chuyện nào được lưu.</div>}
        </div>
      </div>

      <div className="sidebar-bottom">
        <ShieldCheck size={15} /> {grounded ? "Trả lời dựa trên tài liệu" : "Chế độ trao đổi chung"}
      </div>
    </aside>

    <main className="main">
      <header className="topbar">
        <div>
          <span className="overline">WORKSPACE</span>
          <h1>Hỏi đáp & tra cứu</h1>
        </div>
        <div className="topbar-actions">
          {/* Tab nhỏ ở trên: Hiển thị và quản lý tài liệu đã tải lên của session */}
          <button
            className={`session-docs-tab-btn ${showDocTab ? "active" : ""}`}
            onClick={() => setShowDocTab(!showDocTab)}
            title="Xem và tải lên tài liệu cho phiên chat này"
          >
            <FileText size={15} />
            <span>Tài liệu đã tải ({sessionDocs.length})</span>
          </button>
          <span className="status"><i />{health ? "Đang hoạt động" : "Đang kết nối"}</span>
        </div>
      </header>

      {/* Panel tab nhỏ ở trên: Hiện tài liệu đã tải lên của phiên chat */}
      {showDocTab && (
        <div className="session-docs-panel">
          <div className="session-docs-header">
            <div className="session-docs-title">
              <FileText size={16} />
              <strong>Tài liệu của phiên chat này ({sessionDocs.length})</strong>
            </div>
            <div className="session-docs-actions">
              <button
                className="upload-tab-btn"
                disabled={uploading || busy}
                onClick={() => uploadInput.current?.click()}
              >
                <Upload size={14} /> {uploading ? "Đang lập chỉ mục…" : "Tải lên tài liệu"}
              </button>
              <button className="close-tab-btn" onClick={() => setShowDocTab(false)}>
                <X size={15} />
              </button>
            </div>
          </div>
          <input
            ref={uploadInput}
            type="file"
            accept=".docx,.txt,.pdf"
            multiple
            hidden
            onChange={e => uploadFiles(Array.from(e.target.files))}
          />
          <div className="session-docs-list">
            {sessionDocs.map(doc => (
              <div className="session-doc-chip" key={doc.id}>
                <FileText size={13} />
                <span title={doc.filename}>{doc.filename}</span>
                <button
                  aria-label={`Xóa ${doc.filename}`}
                  disabled={busy || uploading}
                  onClick={() => deleteDoc(doc)}
                >
                  <X size={12} />
                </button>
              </div>
            ))}
            {!sessionDocs.length && (
              <span className="session-docs-empty">
                Chưa có tài liệu nào tải lên trong phiên chat này. Bấm "Tải lên tài liệu" (.docx, .pdf, .txt) để thêm tài liệu riêng.
              </span>
            )}
          </div>
        </div>
      )}

      <section className="conversation" aria-live="polite">
        {!messages.length && <div className="welcome">
          <div className="welcome-icon"><BookOpen size={29} /></div>
          <span className="overline">TRỢ LÝ NGUỒN VNPOST</span>
          <h2>Bạn muốn tìm điều gì?</h2>
          <p>Đặt câu hỏi trực tiếp để tra cứu quy định VNPost,<br />hoặc bấm tab "Tài liệu đã tải" ở trên để nạp thêm tài liệu riêng cho phiên chat.</p>
          <div className="suggestions">{suggestions.map(s => <button key={s} onClick={() => setInput(s)}>{s}<ArrowUp size={14} /></button>)}</div>
        </div>}

        {messages.map(message => <article className={`message ${message.role}`} key={message.id}>
          <div className="message-avatar">{message.role === "user" ? "Bạn" : <BookOpen size={17} />}</div>
          <div className="message-content">
            {message.role === "user" ? <div className="user-text">
              {message.image && <div className="user-image-container"><img src={message.image} alt="Đính kèm" className="user-attached-image" /></div>}
              <div>{message.text}</div>
            </div> : message.pending ? <div className="pending"><span /> Đang xử lý yêu cầu…</div> : <>
              <AnswerText text={message.answer || message.error || ""} />
              {message.sources?.length > 0 && <details className="sources"><summary><FileText size={14} /> {message.sources.length} đoạn nguồn tham chiếu</summary>{message.sources.map(source => <div className="source" key={source.citation_id}><strong>[{source.citation_id}] {source.filename}</strong><span>{source.location}</span><p>{source.excerpt}</p></div>)}</details>}
              {message.answer && <div className="answer-actions">
                {message.route && <span className={`route-badge ${message.route}`} title={message.route_reason || ""}>{message.route === "fast" ? "⚡ Fast RAG" : "🤖 Deep Agent"}</span>}
                <span>{message.grounding_status === "cited" ? "Có trích nguồn · " : ""}{((message.elapsed_ms || 0) / 1000).toFixed(1)} giây</span>
                {health?.tts_enabled && <>
                  <button onClick={() => readAnswer(message)}><Volume2 size={14} /> Nghe</button>
                  <button onClick={() => streamAnswer(message)} disabled={streamingAudio}><Headphones size={14} /> Phát streaming</button>
                </>}
                {message.blob && <a href={message.blob} download="answer.wav">Tải âm thanh</a>}
              </div>}
            </>}
          </div>
        </article>)}

        {busy && events.length > 0 && <div className="activity">
          {events.filter(e => e.type === "router_decision").slice(-1).map((e, i) => <span key={`r-${i}`} className="route-activity">{e.route === "fast" ? "⚡ Đường nhanh (Direct RAG)" : "🤖 Đường sâu (Deep Agent)"}: {e.reason}</span>)}
          {events.filter(e => e.type === "task_start" || e.type === "task_end").slice(-5).map((e, i) => <span key={i}>{agentNames[e.agent] || e.agent} · {e.type === "task_start" ? "đang chạy" : (e.status === "ok" ? "xong" : "lỗi")}</span>)}
        </div>}
        <div ref={end} />
      </section>

      <div className="composer-area">
        {notice && <div className="notice" role="status">{notice}<button aria-label="Đóng thông báo" onClick={() => setNotice("")}><X size={14} /></button></div>}
        <div className="composer-options">
          <label className="check"><input type="checkbox" checked={grounded} onChange={e => setGrounded(e.target.checked)} disabled={busy} /> Yêu cầu trích nguồn tài liệu</label>
          <div className="route-select-wrapper">
            <span className="route-select-label">Chế độ:</span>
            <select aria-label="Chế độ xử lý" value={routeMode} onChange={e => setRouteMode(e.target.value)} disabled={busy} className="route-select">
              <option value="auto">Tự động (Hybrid Router)</option>
              <option value="fast">⚡ Đường nhanh (Fast RAG · ~1.8s)</option>
              <option value="deep">🤖 Đường sâu (Deep Multi-Agent)</option>
            </select>
          </div>
          {streamingAudio && <button className="stop-audio" onClick={stopAudio}><Square size={12} /> Dừng âm thanh</button>}
        </div>

        {attachedImage && <div className="attached-preview-bar">
          <div className="attached-thumb">
            <img src={attachedImage} alt="Ảnh đính kèm" />
            <button type="button" aria-label="Bỏ ảnh" onClick={() => setAttachedImage(null)}><X size={12} /></button>
          </div>
          <span className="small muted">Ảnh đã đính kèm (mô hình sẽ phân tích hình ảnh này)</span>
        </div>}

        <form className="composer" onSubmit={send}>
          <input ref={imageInput} type="file" accept="image/*" hidden onChange={handleImageSelect} />
          <button type="button" className="attach-btn" onClick={() => imageInput.current?.click()} title="Đính kèm ảnh" disabled={busy}><ImageIcon size={18} /></button>
          <textarea rows={2} aria-label="Câu hỏi" placeholder="Đặt câu hỏi hoặc dán (Ctrl+V) ảnh để hỏi…" value={input} onChange={e => setInput(e.target.value)} onPaste={handlePaste} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(e); } }} />
          <button aria-label={busy ? "Dừng yêu cầu" : "Gửi câu hỏi"} type={busy ? "button" : "submit"} disabled={!busy && !input.trim() && !attachedImage} onClick={busy ? () => abort.current?.abort() : undefined}>{busy ? <Square size={18} /> : <ArrowUp size={21} />}</button>
        </form>
        <p className="composer-note">Kiểm tra nguồn trước khi sử dụng thông tin cho quyết định quan trọng.</p>
      </div>
    </main>
  </div>;
}
