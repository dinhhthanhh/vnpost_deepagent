import React, { useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  Check,
  ChevronDown,
  Copy,
  FileText,
  Headphones,
  Home,
  Image as ImageIcon,
  Info,
  LayoutGrid,
  Mail,
  MapPin,
  MessageCircle,
  MessageSquare,
  Mic,
  Navigation,
  Paperclip,
  Plus,
  Send,
  Settings,
  ShieldCheck,
  Sparkles,
  Square,
  Star,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  Upload,
  User,
  Volume2,
  X,
} from "lucide-react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faBan,
  faBolt,
  faBoxArchive,
  faBrain,
  faCircleCheck,
  faCircleInfo,
  faCircleXmark,
  faClock,
  faLocationDot,
  faMagnifyingGlass,
  faMicrophone,
  faPenToSquare,
  faTriangleExclamation,
  faWandMagicSparkles,
} from "@fortawesome/free-solid-svg-icons";
import { audioBlob, request, streamChat, transcribeAudio } from "./api";
import { playWavStream } from "./wav-stream";
import { marked } from "marked";
import DOMPurify from "dompurify";

marked.setOptions({
  breaks: true,
  gfm: true,
});

// Danh sách các Chatbot đúng như ảnh chụp màn hình
const CHATBOT_OPTIONS = [
  "Chatbot mvno",
  "Chatbot bccp_qt",
  "Chatbot dịch vụ công",
  "Chatbot CSKH TCT",
  "Chatbot Kho Tri Thức EMS",
  "Chatbot ĐKCL",
  "Chatbot CSKH EMS",
  "Chatbot Stream Test",
  "Chatbot Memory",
  "Chatbot biểu đồ",
  "Trợ lý email",
];

// Các câu văn chạy hiệu ứng gõ chữ (typing effect)
const TYPING_PHRASES = [
  "[Tôi muốn có nhiều thông tin khác nữa]",
  "[Tôi muốn biết thông tin về VNPost?]",
  "[Tra cứu tỷ lệ phát thành công theo bưu cục]",
  "[Thời gian toàn trình dịch vụ chuyển phát EMS]",
];

// Component gõ chữ động (Typing animation với con trỏ nhấp nháy)
function TypingEffect() {
  const [phraseIndex, setPhraseIndex] = useState(0);
  const [displayText, setDisplayText] = useState("");
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    const current = TYPING_PHRASES[phraseIndex];
    let timer;

    if (!isDeleting) {
      if (displayText.length < current.length) {
        timer = setTimeout(() => {
          setDisplayText(current.slice(0, displayText.length + 1));
        }, 55);
      } else {
        timer = setTimeout(() => {
          setIsDeleting(true);
        }, 2200);
      }
    } else {
      if (displayText.length > 0) {
        timer = setTimeout(() => {
          setDisplayText(current.slice(0, displayText.length - 1));
        }, 28);
      } else {
        setIsDeleting(false);
        setPhraseIndex((prev) => (prev + 1) % TYPING_PHRASES.length);
      }
    }

    return () => clearTimeout(timer);
  }, [displayText, isDeleting, phraseIndex]);

  return (
    <div className="typing-wrapper">
      <span className="typing-text">{displayText}</span>
      <span className="typed-cursor" aria-hidden="true">|</span>
    </div>
  );
}

// Biểu tượng Nhận diện bì thư (Envelope có chữ AI bên trong)
function EnvelopeAiIcon({ size = 18 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="#475569"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="2" y="4" width="20" height="16" rx="2" />
      <path d="M22 7l-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
      <text
        x="3.5"
        y="18.5"
        fill="#334155"
        stroke="none"
        fontSize="5.5"
        fontWeight="800"
        fontFamily="Inter, system-ui, sans-serif"
      >
        AI
      </text>
    </svg>
  );
}

// Huy hiệu Google Play
function GooglePlayBadge() {
  return (
    <div className="store-badge">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none">
        <path d="M3.6 1.8L13.8 12L3.6 22.2C3.2 21.8 3 21.2 3 20.4V3.6C3 2.8 3.2 2.2 3.6 1.8Z" fill="#2196F3" />
        <path d="M17.2 8.6L13.8 12L3.6 1.8C4.1 1.5 4.8 1.5 5.4 1.9L17.2 8.6Z" fill="#4CAF50" />
        <path d="M17.2 15.4L5.4 22.1C4.8 22.5 4.1 22.5 3.6 22.2L13.8 12L17.2 15.4Z" fill="#F44336" />
        <path d="M21.2 10.9L17.2 8.6L13.8 12L17.2 15.4L21.2 13.1C22.3 12.5 22.3 11.5 21.2 10.9Z" fill="#FFEB3B" />
      </svg>
      <div className="store-text">
        <span className="store-sub">GET IT ON</span>
        <span className="store-main">Google Play</span>
      </div>
    </div>
  );
}

// Huy hiệu Apple App Store
function AppStoreBadge() {
  return (
    <div className="store-badge">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="white">
        <path d="M18.7 19.5C17.7 21 16.6 22.5 15 22.5C13.4 22.5 12.9 21.5 11.1 21.5C9.3 21.5 8.7 22.5 7.2 22.5C5.6 22.5 4.5 21 3.5 19.5C1.5 16.5 0 11.5 1.6 8.7C2.4 7.3 3.9 6.4 5.5 6.4C7 6.4 8 7.3 9.1 7.3C10.1 7.3 11.3 6.4 12.9 6.4C13.5 6.4 15.7 6.6 17.1 8.5C17 8.6 14.5 10.1 14.5 13.1C14.5 16.6 17.6 17.8 17.7 17.9C17.6 18.2 17.1 19.9 18.7 19.5ZM12 6.4C12.7 5.5 13.2 4.3 13.1 3C12 3.1 10.6 3.8 9.9 4.7C9.3 5.4 8.7 6.7 8.9 7.9C10.2 8 11.4 7.3 12 6.4Z" />
      </svg>
      <div className="store-text">
        <span className="store-sub">Download on the</span>
        <span className="store-main">App Store</span>
      </div>
    </div>
  );
}

// Xử lý hiển thị văn bản Markdown đẹp mắt, an toàn chống XSS và highlight mã trích nguồn [S1], [S2]
function FormattedAnswer({ text }) {
  if (!text) return null;
  try {
    let rawHtml = marked.parse(text);
    rawHtml = rawHtml.replace(
      /\[(S\d+)\]/g,
      '<span class="citation-badge">[$1]</span>'
    );
    // Chuyển đổi mọi link Google Maps thành đúng 1 nút 'Google Maps' duy nhất trong box
    rawHtml = rawHtml.replace(
      /([Cc]hỉ đường(?:\s+(?:trên|qua))?(?:\s+Google Maps)?\s*:\s*)?<a\s+(?:[^>]*?\s+)?href="([^"]*(?:google\.com\/maps|maps\.google\.com)[^"]*)"[^>]*>.*?<\/a>/gi,
      (match, prefix, href) => {
        const cleanPrefix = prefix ? "Chỉ đường: " : "";
        return `${cleanPrefix}<a href="${href}" target="_blank" rel="noopener noreferrer" class="maps-direction-link"><span class="map-pin-svg-icon"></span>Google Maps</a>`;
      }
    );
    // Sanitize HTML strictly before injecting into DOM to prevent XSS
    const cleanHtml = DOMPurify.sanitize(rawHtml, {
      ALLOWED_TAGS: [
        "p", "br", "strong", "em", "u", "s", "ul", "ol", "li",
        "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "code",
        "table", "thead", "tbody", "tr", "th", "td", "span", "a", "hr"
      ],
      ALLOWED_ATTR: ["class", "href", "target", "rel", "title"],
      ALLOW_DATA_ATTR: false
    });
    return (
      <div
        className="answer-text markdown-body"
        dangerouslySetInnerHTML={{ __html: cleanHtml }}
      />
    );
  } catch (err) {
    return <div className="answer-text">{text}</div>;
  }
}

// Thẻ Hành Động Tương Tác: Hỗ trợ Human-in-the-Loop xác nhận/hủy đơn nháp và quản lý bưu gửi trực quan
function PostalActionCard({ text, onSend, onSetInput }) {
  if (!text || typeof text !== "string") return null;

  const textLower = text.toLowerCase();

  // Danh sách mã vận đơn giả lập / minh họa mẫu (không bao giờ được sinh thẻ hành động)
  const isDummyTrackingCode = (code) =>
    /123456789|012345678|000000000|987654321|111111111/i.test(code);

  // BẢO VỆ NGHIỆP VỤ: Loại bỏ ngay nếu đây là câu trả lời hướng dẫn, giải thích quy trình hoặc đưa ví dụ mã mẫu
  const isExplanationOrTutorial =
    textLower.includes("ví dụ") ||
    textLower.includes("quy trình") ||
    textLower.includes("hướng dẫn") ||
    textLower.includes("chuẩn quốc tế") ||
    textLower.includes("cần cung cấp mã") ||
    textLower.includes("định dạng mã") ||
    textLower.includes("kiểm tra định dạng") ||
    textLower.includes("mã vận đơn là gì") ||
    textLower.includes("tra cứu trạng thái");

  if (isExplanationOrTutorial) return null;

  // 1. Nhận diện Đơn hàng nháp chờ duyệt (WAITING_CONFIRMATION / draft_id)
  const draftBookingMatch = text.match(/\b(BK-DRAFT-[A-Za-z0-9]+|DRAFT-[A-Za-z0-9]+)\b/i);
  const isDraftBooking = draftBookingMatch && (
    textLower.includes("bản nháp đơn hàng") ||
    textLower.includes("chờ duyệt") ||
    textLower.includes("chờ xác nhận") ||
    textLower.includes("waiting_confirmation") ||
    textLower.includes("xác nhận (hitl)")
  );

  // 2. Nhận diện Khiếu nại nháp chờ duyệt
  const draftComplaintMatch = text.match(/\b(KN-DRAFT-[A-Za-z0-9]+)\b/i);
  const isDraftComplaint = draftComplaintMatch && (
    textLower.includes("nháp") ||
    textLower.includes("chờ duyệt") ||
    textLower.includes("chờ xác nhận")
  );

  // 3. Nhận diện Vận đơn bưu chính VNPost thực sự vừa tạo/xác nhận thành công
  const trackingMatch = text.match(/\b(EB|CP|RA|LP)\d{9}VN\b/i);
  const isConfirmedOrder = trackingMatch && !isDummyTrackingCode(trackingMatch[0]) && (
    textLower.includes("tạo đơn gửi hàng thành công") ||
    textLower.includes("đã xác nhận đơn hàng") ||
    textLower.includes("phát hành mã vận đơn chính thức")
  );

  if (isDraftBooking) {
    const draftId = draftBookingMatch[0];
    return (
      <div className="postal-action-card booking-card">
        <div className="action-card-header">
          <span className="action-card-badge status-waiting">
            <FontAwesomeIcon icon={faClock} /> Chờ duyệt đơn (HITL)
          </span>
          <span className="action-card-id">{draftId}</span>
        </div>
        <div className="action-card-body">
          <p className="action-card-desc">
            Bản nháp đơn hàng đã sẵn sàng. Quý khách vui lòng bấm xác nhận để phát hành mã vận đơn VNPost và điều phối bưu tá thu gom.
          </p>
        </div>
        <div className="action-card-buttons">
          <button
            type="button"
            className="action-card-btn btn-confirm"
            onClick={() => onSend(`Tôi xác nhận đồng ý tạo đơn hàng ${draftId}`)}
          >
            <FontAwesomeIcon icon={faCircleCheck} /> Xác nhận đặt đơn
          </button>
          <button
            type="button"
            className="action-card-btn btn-cancel"
            onClick={() => onSend(`Tôi muốn hủy đơn nháp ${draftId}`)}
          >
            <FontAwesomeIcon icon={faCircleXmark} /> Hủy đơn nháp
          </button>
          <button
            type="button"
            className="action-card-btn btn-edit"
            onClick={() => onSetInput(`Tôi muốn sửa đơn ${draftId}: `)}
          >
            <FontAwesomeIcon icon={faPenToSquare} /> Sửa thông tin
          </button>
        </div>
      </div>
    );
  }

  if (isDraftComplaint) {
    const draftTicketId = draftComplaintMatch[0];
    return (
      <div className="postal-action-card complaint-card">
        <div className="action-card-header">
          <span className="action-card-badge status-waiting">
            <FontAwesomeIcon icon={faTriangleExclamation} /> Chờ nộp khiếu nại (HITL)
          </span>
          <span className="action-card-id">{draftTicketId}</span>
        </div>
        <div className="action-card-body">
          <p className="action-card-desc">
            Hồ sơ khiếu nại bưu gửi đã được lập nháp. Vui lòng xác nhận để chính thức nộp vào hệ thống CSKH VNPost (SLA 20 ngày).
          </p>
        </div>
        <div className="action-card-buttons">
          <button
            type="button"
            className="action-card-btn btn-confirm"
            onClick={() => onSend(`Tôi xác nhận nộp phiếu khiếu nại ${draftTicketId}`)}
          >
            <FontAwesomeIcon icon={faCircleCheck} /> Xác nhận nộp khiếu nại
          </button>
          <button
            type="button"
            className="action-card-btn btn-cancel"
            onClick={() => onSend(`Tôi muốn hủy phiếu khiếu nại ${draftTicketId}`)}
          >
            <FontAwesomeIcon icon={faCircleXmark} /> Hủy khiếu nại
          </button>
        </div>
      </div>
    );
  }

  if (isConfirmedOrder) {
    const itemCode = trackingMatch[0];
    return (
      <div className="postal-action-card confirmed-card">
        <div className="action-card-header">
          <span className="action-card-badge status-confirmed">
            <FontAwesomeIcon icon={faBoxArchive} /> Đã phát hành vận đơn
          </span>
          <span className="action-card-id tracking-code">{itemCode}</span>
        </div>
        <div className="action-card-buttons">
          <button
            type="button"
            className="action-card-btn btn-track"
            onClick={() => onSend(`Tra cứu hành trình vận đơn ${itemCode}`)}
          >
            <FontAwesomeIcon icon={faMagnifyingGlass} /> Định vị bưu gửi
          </button>
          <button
            type="button"
            className="action-card-btn btn-cancel-confirmed"
            onClick={() => onSend(`Tôi muốn hủy đơn hàng ${itemCode}`)}
          >
            <FontAwesomeIcon icon={faBan} /> Hủy đơn lấy hàng
          </button>
        </div>
      </div>
    );
  }

  return null;
}

export default function App() {
  // Session-based authentication / dynamic token; no static secret hardcoded in client bundle
  const [key, setKey] = useState(() => sessionStorage.getItem("auth-token") || "");
  const [health, setHealth] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [grounded, setGrounded] = useState(true);
  const [selectedBot, setSelectedBot] = useState("Chatbot mvno");
  const [routeMode, setRouteMode] = useState("auto"); // auto, fast, deep
  const [voice, setVoice] = useState(false);
  const [voices, setVoices] = useState([]);
  const [voiceName, setVoiceName] = useState("maichi");
  const [notice, setNotice] = useState("");
  const [events, setEvents] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [session, setSession] = useState(() => localStorage.getItem("chat-session") || null);
  const [sessions, setSessions] = useState([]);
  const [sessionDocs, setSessionDocs] = useState([]);
  const [showDocModal, setShowDocModal] = useState(false);
  const [showGuideModal, setShowGuideModal] = useState(false);
  const [showContactModal, setShowContactModal] = useState(false);
  const [showSettingsModal, setShowSettingsModal] = useState(false);
  const [showBotDropdown, setShowBotDropdown] = useState(false);
  const [showToolsDropdown, setShowToolsDropdown] = useState(false);
  const [showModeDropdown, setShowModeDropdown] = useState(false);
  const [streamingAudio, setStreamingAudio] = useState(false);
  const [playingMessageId, setPlayingMessageId] = useState(null);
  const [attachedImage, setAttachedImage] = useState(null);
  const [likedMap, setLikedMap] = useState({});
  const [dislikedMap, setDislikedMap] = useState({});
  const [copiedId, setCopiedId] = useState(null);
  const [locating, setLocating] = useState(false);
  const [userLocation, setUserLocation] = useState(null);
  const [isRecording, setIsRecording] = useState(false);
  const speechRecRef = useRef(null);
  const mediaRecRef = useRef(null);
  const audioChunksRef = useRef([]);

  function requestUserLocation(callback) {
    if (!navigator.geolocation) {
      setNotice("Trình duyệt không hỗ trợ định vị GPS.");
      if (callback) callback(null);
      return;
    }
    setLocating(true);
    setNotice("Đang xin quyền truy cập vị trí GPS của thiết bị...");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        const loc = {
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          accuracy: pos.coords.accuracy,
        };
        setUserLocation(loc);
        setNotice(`Đã lấy vị trí GPS (${loc.latitude.toFixed(4)}, ${loc.longitude.toFixed(4)}). Đang tìm bưu cục gần nhất...`);
        setTimeout(() => setNotice(""), 3500);
        if (callback) callback(loc);
      },
      (err) => {
        setLocating(false);
        let errMsg = "Không thể lấy vị trí GPS. Bạn có thể nhập quận/huyện để tìm kiếm.";
        if (err.code === 1) {
          errMsg = "Bạn đã từ chối quyền truy cập vị trí. Hãy bật định vị hoặc nhập quận/huyện/địa chỉ để tìm bưu cục nhé!";
        } else if (err.code === 2) {
          errMsg = "Không xác định được vị trí GPS hiện tại. Vui lòng nhập địa chỉ/quận huyện.";
        } else if (err.code === 3) {
          errMsg = "Quá thời gian lấy vị trí GPS. Vui lòng thử lại.";
        }
        setNotice(errMsg);
        if (callback) callback(null);
      },
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 }
    );
  }

  function handleFindNearestPostOffice() {
    requestUserLocation((loc) => {
      if (loc) {
        send(null, "Tìm bưu điện VNPost gần vị trí của tôi nhất", loc);
      } else {
        setInput("Tìm bưu điện gần ");
      }
    });
  }

  const endRef = useRef();
  const uploadInput = useRef();
  const imageInput = useRef();
  const envelopeInput = useRef();
  const abort = useRef();
  const audio = useRef();
  const blobs = useRef([]);
  const stream = useRef(null);
  const botDropdownRef = useRef();
  const toolsDropdownRef = useRef();
  const modeDropdownRef = useRef();

  const releaseBlobs = () => {
    blobs.current.forEach(URL.revokeObjectURL);
    blobs.current = [];
  };

  const stopAudio = () => {
    stream.current?.controller.abort();
    stream.current?.context.close().catch(() => { });
    stream.current = null;
    if (audio.current) {
      audio.current.pause();
      audio.current.currentTime = 0;
    }
    setStreamingAudio(false);
    setPlayingMessageId(null);
  };

  const handleToggleVoice = () => {
    const next = !voice;
    setVoice(next);
    if (next) {
      try {
        if (!audio.current) {
          audio.current = new Audio();
        }
        audio.current.src = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA";
        audio.current.play().catch(() => { });
      } catch { }
    }
  };

  const handleMicClick = async () => {
    if (isRecording) {
      if (speechRecRef.current) {
        try { speechRecRef.current.stop(); } catch { }
        speechRecRef.current = null;
      }
      if (mediaRecRef.current && mediaRecRef.current.state === "recording") {
        mediaRecRef.current.stop();
      }
      setIsRecording(false);
      setNotice("Đã dừng lắng nghe giọng nói.");
      return;
    }

    // 1. Ưu tiên Web Speech API (nhận diện giọng nói tiếng Việt trực tiếp với độ trễ cực thấp)
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRec) {
      try {
        const recognition = new SpeechRec();
        recognition.lang = "vi-VN";
        recognition.continuous = false;
        recognition.interimResults = true;
        recognition.maxAlternatives = 1;

        recognition.onstart = () => {
          setIsRecording(true);
          setNotice("Đang lắng nghe giọng nói tiếng Việt... Hãy nói câu hỏi của bạn.");
        };

        recognition.onresult = (event) => {
          let transcript = "";
          for (let i = event.resultIndex; i < event.results.length; i++) {
            transcript += event.results[i][0].transcript;
          }
          if (transcript) {
            setInput(transcript);
          }
        };

        recognition.onerror = (event) => {
          console.warn("Speech recognition error:", event.error);
          setIsRecording(false);
          if (event.error === "not-allowed") {
            setNotice("Trình duyệt chưa được cấp quyền Microphone.");
          } else if (event.error === "no-speech") {
            setNotice("Chưa nhận diện được giọng nói, vui lòng thử lại.");
          }
        };

        recognition.onend = () => {
          setIsRecording(false);
        };

        speechRecRef.current = recognition;
        recognition.start();
        return;
      } catch (err) {
        console.warn("Lỗi SpeechRecognition, chuyển sang MediaRecorder fallback:", err);
      }
    }

    // 2. Fallback: Dùng MediaRecorder ghi âm gửi lên backend /api/voice/transcribe
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setNotice("Trình duyệt không hỗ trợ truy cập Microphone.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioChunksRef.current = [];
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        setIsRecording(false);
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
        if (blob.size > 100) {
          setNotice("Đang chuyển đổi âm thanh sang văn bản tiếng Việt qua STT...");
          try {
            const result = await transcribeAudio(blob, key);
            if (result && result.text) {
              setInput(result.text);
              setNotice("Đã nhận diện giọng nói thành công!");
            }
          } catch (err) {
            setNotice(`Lỗi STT: ${err.message}`);
          }
        }
      };

      mediaRecorder.start();
      setIsRecording(true);
      setNotice("Đang ghi âm Microphone (bấm lại nút Mic để hoàn tất)...");
    } catch (err) {
      console.error("Lỗi Microphone:", err);
      setIsRecording(false);
      setNotice("Không thể truy cập Microphone thiết bị.");
    }
  };

  // Đóng dropdown khi click ra ngoài
  useEffect(() => {
    function handleClickOutside(event) {
      if (botDropdownRef.current && !botDropdownRef.current.contains(event.target)) {
        setShowBotDropdown(false);
      }
      if (toolsDropdownRef.current && !toolsDropdownRef.current.contains(event.target)) {
        setShowToolsDropdown(false);
      }
      if (modeDropdownRef.current && !modeDropdownRef.current.contains(event.target)) {
        setShowModeDropdown(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    return () => {
      abort.current?.abort();
      stopAudio();
      releaseBlobs();
      if (speechRecRef.current) {
        try { speechRecRef.current.stop(); } catch { }
      }
      if (mediaRecRef.current && mediaRecRef.current.state === "recording") {
        try { mediaRecRef.current.stop(); } catch { }
      }
    };
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, events, busy]);

  useEffect(() => {
    request("/api/health", "")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => { });
  }, []);

  async function loadSessions(activeKey = key) {
    try {
      const data = await request("/api/sessions", activeKey).then((r) => r.json());
      setSessions(data.sessions || []);
    } catch {
      setSessions([]);
    }
  }

  async function loadSessionDocs(sid, activeKey = key) {
    if (!sid) {
      setSessionDocs([]);
      return;
    }
    try {
      const data = await request(`/api/documents?session_id=${sid}&only_session=true`, activeKey).then((r) =>
        r.json()
      );
      setSessionDocs(data.documents || []);
    } catch {
      setSessionDocs([]);
    }
  }

  async function loadVoices(activeKey = key) {
    try {
      const voiceResponse = await request("/api/tts/voices", activeKey)
        .then((r) => r.json())
        .catch(() => ({ voices: [] }));
      setVoices(voiceResponse.voices || []);
    } catch {
      setVoices([]);
    }
  }

  async function selectSession(sid) {
    if (busy || sid === session) return;
    abort.current?.abort();
    stopAudio();
    releaseBlobs();
    setSession(sid);
    localStorage.setItem("chat-session", sid);
    setNotice("");
    setAttachedImage(null);
    setEvents([]);
    try {
      const data = await request(`/api/sessions/${sid}`, key).then((r) => r.json());
      setMessages(
        data.messages.map((m) => ({
          ...m,
          id: m.request_id || crypto.randomUUID(),
          text: m.content,
          answer: m.content,
          time: getCurrentTimeString(m.created),
        }))
      );
      await loadSessionDocs(sid, key);
    } catch (e) {
      setNotice(e.message);
    }
  }

  async function deleteSession(sid) {
    if (!sid) return;
    setNotice("Đang xóa đoạn trò chuyện…");
    try {
      await request(`/api/sessions/${encodeURIComponent(sid)}`, key, { method: "DELETE" });
      setSessions((prev) => prev.filter((s) => s.id !== sid));
      if (session === sid) {
        await newChat();
      }
      setNotice("Đã xóa đoạn trò chuyện.");
      await loadSessions(key);
    } catch (e) {
      setNotice(`Lỗi xóa phiên: ${e.message}`);
      await loadSessions(key);
    }
  }

  useEffect(() => {
    loadSessions(key);
    loadVoices(key);
    if (session) {
      request(`/api/sessions/${session}`, key)
        .then((r) => r.json())
        .then((data) => {
          setMessages(
            data.messages.map((m) => ({
              ...m,
              id: m.request_id || crypto.randomUUID(),
              text: m.content,
              answer: m.content,
              time: getCurrentTimeString(m.created),
            }))
          );
        })
        .catch(() => { });
      loadSessionDocs(session, key);
    }
  }, [key]);

  // Nút tạo New Chat: đưa về màn hình khởi tạo sạch sẽ đúng như ảnh
  async function newChat() {
    abort.current?.abort();
    stopAudio();
    releaseBlobs();
    setSession(null);
    localStorage.removeItem("chat-session");
    setMessages([]);
    setEvents([]);
    setNotice("");
    setAttachedImage(null);
    setSessionDocs([]);
  }

  async function compressImageFile(file, maxWidth = 1600, maxHeight = 1600, quality = 0.82) {
    return new Promise((resolve) => {
      if (file.type === "image/svg+xml" || file.type === "image/gif") {
        const reader = new FileReader();
        reader.onload = (ev) => resolve(ev.target.result);
        reader.onerror = () => resolve(null);
        reader.readAsDataURL(file);
        return;
      }
      const reader = new FileReader();
      reader.onload = (ev) => {
        const img = new Image();
        img.onload = () => {
          let { width, height } = img;
          if (width > maxWidth || height > maxHeight) {
            const ratio = Math.min(maxWidth / width, maxHeight / height);
            width = Math.round(width * ratio);
            height = Math.round(height * ratio);
          }
          const canvas = document.createElement("canvas");
          canvas.width = width;
          canvas.height = height;
          const ctx = canvas.getContext("2d");
          if (!ctx) {
            resolve(ev.target.result);
            return;
          }
          ctx.drawImage(img, 0, 0, width, height);
          const dataUrl = canvas.toDataURL("image/jpeg", quality);
          resolve(dataUrl);
        };
        img.onerror = () => resolve(ev.target.result);
        img.src = ev.target.result;
      };
      reader.onerror = () => resolve(null);
      reader.readAsDataURL(file);
    });
  }

  async function handleImageSelect(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setNotice("Chỉ hỗ trợ tệp định dạng hình ảnh (PNG, JPG, WebP...).");
      return;
    }
    if (file.size > 15 * 1024 * 1024) {
      setNotice("Kích thước ảnh tối đa là 15MB.");
      return;
    }
    setNotice("Đang tối ưu hóa dung lượng ảnh...");
    try {
      const compressed = await compressImageFile(file);
      if (compressed) {
        setAttachedImage(compressed);
        setNotice("Đã nén tối ưu ảnh thành công.");
        setTimeout(() => setNotice(""), 2500);
      } else {
        setNotice("Không thể xử lý hình ảnh này.");
      }
    } catch {
      setNotice("Lỗi khi xử lý hình ảnh.");
    } finally {
      e.target.value = "";
    }
  }

  async function handlePaste(e) {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
      if (item.type.startsWith("image/")) {
        const file = item.getAsFile();
        if (file) {
          e.preventDefault();
          setNotice("Đang tối ưu hóa ảnh từ clipboard...");
          const compressed = await compressImageFile(file);
          if (compressed) {
            setAttachedImage(compressed);
            setNotice("Đã đính kèm ảnh từ clipboard.");
            setTimeout(() => setNotice(""), 2500);
          }
          break;
        }
      }
    }
  }

  async function uploadFiles(files) {
    if (!files.length) return;
    setUploading(true);
    setNotice("");
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
      setNotice("Tải tài liệu thành công. Tài liệu này sẽ được dùng riêng trong phiên chat hiện tại.");
    } catch (e) {
      setNotice(e.message);
    } finally {
      setUploading(false);
      if (uploadInput.current) uploadInput.current.value = "";
    }
  }

  async function deleteDoc(doc) {
    if (!confirm(`Xóa tài liệu “${doc.filename}” khỏi phiên chat này?`)) return;
    try {
      await request(`/api/documents/${doc.id}`, key, { method: "DELETE" });
      await loadSessionDocs(session);
    } catch (e) {
      setNotice(e.message);
    }
  }

  async function prepareAudio(url, id) {
    try {
      const blob = await audioBlob(url, key);
      blobs.current.push(blob);
      setMessages((previous) => previous.map((m) => (m.id === id ? { ...m, blob } : m)));

      let audioEl = audio.current;
      if (!audioEl) {
        audioEl = new Audio();
        audio.current = audioEl;
      }
      audioEl.pause();
      audioEl.src = blob;
      audioEl.currentTime = 0;
      audioEl.onplay = () => {
        setStreamingAudio(true);
        setPlayingMessageId(id);
      };
      audioEl.onended = () => {
        setStreamingAudio(false);
        setPlayingMessageId(null);
      };
      audioEl.onpause = () => {
        setStreamingAudio(false);
        setPlayingMessageId(null);
      };
      audioEl.play().catch((err) => {
        console.warn("Autoplay notice:", err);
        setNotice("Âm thanh đã sẵn sàng. Bấm nút loa ở câu trả lời để nghe.");
      });
    } catch (e) {
      setNotice(e.message);
    }
  }

  function createStreamingSpeech(targetMessageId) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return null;

    stopAudio();
    const controller = new AbortController();
    const context = new AudioContextClass();
    const current = { controller, context };
    stream.current = current;
    // Called in the Send handler, so browsers can authorize Web Audio playback.
    context.resume().catch(() => { });
    if (targetMessageId) setPlayingMessageId(targetMessageId);

    let pending = "";
    let queue = Promise.resolve();
    let hasText = false;
    const enqueue = (text, flush = false) => {
      pending += text;
      const matches = [...pending.matchAll(/[,.!?:;\n](?=\s|$)/g)];
      const boundary = matches.length ? matches.at(-1).index + 1 : 0;
      const chunk = flush ? pending.trim() : (boundary >= 24 ? pending.slice(0, boundary).trim() : "");
      if (!chunk) return;
      pending = flush ? "" : pending.slice(boundary);
      hasText = true;
      queue = queue.then(async () => {
        if (stream.current !== current || controller.signal.aborted) return;
        const response = await request("/api/tts/stream", key, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: chunk, voice: voiceName }),
          signal: controller.signal,
        });
        await playWavStream(response, context, {
          signal: controller.signal,
          onFirstAudio: () => {
            setStreamingAudio(true);
            if (targetMessageId) setPlayingMessageId(targetMessageId);
          },
        });
      }).catch((error) => {
        if (error.name !== "AbortError") setNotice(error.message);
      });
    };

    const enqueueSegment = (segmentText, segmentVoice) => {
      if (!segmentText) return;
      hasText = true;
      queue = queue.then(async () => {
        if (stream.current !== current || controller.signal.aborted) return;
        const response = await request("/api/tts/stream", key, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: segmentText, voice: segmentVoice || voiceName }),
          signal: controller.signal,
        });
        await playWavStream(response, context, {
          signal: controller.signal,
          onFirstAudio: () => {
            setStreamingAudio(true);
            if (targetMessageId) setPlayingMessageId(targetMessageId);
          },
        });
      }).catch((error) => {
        if (error.name !== "AbortError") setNotice(error.message);
      });
    };

    return {
      add: (text) => enqueue(text),
      addSegment: (text, voice) => enqueueSegment(text, voice),
      get hasText() { return hasText; },
      finish: () => {
        enqueue("", true);
        queue.finally(() => {
          if (stream.current === current) {
            setStreamingAudio(false);
            setPlayingMessageId(null);
          }
        });
      },
    };
  }

  function getCurrentTimeString(timestamp) {
    let now = new Date();
    if (typeof timestamp === "number") {
      now = new Date(timestamp * 1000);
    } else if (typeof timestamp === "string" && timestamp.includes("T")) {
      now = new Date(timestamp);
    }
    return now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  async function send(event, text = input, locOverride = null) {
    event?.preventDefault();
    text = text.trim();
    if ((!text && !attachedImage) || busy) return;
    if (!text && attachedImage) text = "Hãy phân tích hình ảnh này.";

    const nowStr = getCurrentTimeString();
    const assistantMsgId = crypto.randomUUID();
    const speech = voice ? createStreamingSpeech(assistantMsgId) : null;
    if (voice && !speech) {
      try {
        if (!audio.current) {
          audio.current = new Audio();
        }
        audio.current.src = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA";
        audio.current.play().catch(() => { });
      } catch { }
    }

    setInput("");
    setBusy(true);
    setNotice("");
    setEvents([]);
    const currentImage = attachedImage;
    setAttachedImage(null);

    // Thêm câu hỏi của user và bubble chờ của assistant
    setMessages((previous) => [
      ...previous,
      { id: crypto.randomUUID(), role: "user", text, image: currentImage, time: nowStr },
      { id: assistantMsgId, role: "assistant", pending: true, time: nowStr },
    ]);

    abort.current = new AbortController();
    let receivedAnswer = false;

    try {
      await streamChat(
        {
          message: text,
          image: currentImage,
          session_id: session,
          grounded,
          mode: routeMode,
          voice,
          stream_voice: Boolean(speech),
          voice_name: voiceName,
          location: locOverride || userLocation || null,
        },
        key,
        (item) => {
          if (item.type === "start") {
            setSession(item.session_id);
            localStorage.setItem("chat-session", item.session_id);
          }
          if (item.type === "token" || item.type === "chunk") {
            receivedAnswer = true;
            speech?.add(item.delta);
            setMessages((previous) =>
              previous.map((m) =>
                m.id === assistantMsgId
                  ? {
                    ...m,
                    answer: (m.answer || "") + item.delta,
                    pending: false,
                    time: m.time || nowStr,
                  }
                  : m
              )
            );
          } else if (item.type === "tts_segment") {
            speech?.addSegment(item.text, item.voice);
            setEvents((previous) => [...previous.slice(-30), item]);
          } else if (item.type === "answer" || item.type === "done") {
            receivedAnswer = true;
            // Fast RAG has already supplied text as tokens; Deep Agent replies
            // arrive as one answer, so queue that one here.
            if (item.type === "answer" && !speech?.hasText) speech?.add(item.data.answer || "");
            setMessages((previous) =>
              previous.map((m) =>
                m.id === assistantMsgId ? { ...m, ...item.data, pending: false, time: m.time || nowStr } : m
              )
            );
            if (item.type === "done") {
              loadSessions(key);
              speech?.finish();
              if (item.data.warnings?.length) setNotice(item.data.warnings.join(" "));
            }
          } else if (item.type === "speech_ready") {
            prepareAudio(item.audio_url, assistantMsgId);
          } else if (item.type === "speech_error" || item.type === "error") {
            setNotice(item.message);
            if (item.type === "error") {
              setMessages((previous) =>
                previous.map((m) =>
                  m.id === assistantMsgId ? { ...m, pending: false, error: item.message, time: m.time || nowStr } : m
                )
              );
            }
          } else {
            setEvents((previous) => [...previous.slice(-30), item]);
          }
        },
        abort.current.signal
      );
    } catch (e) {
      const message = e.name === "AbortError" ? "Đã dừng yêu cầu." : e.message;
      setNotice(message);
      if (!receivedAnswer) {
        setMessages((previous) =>
          previous.map((m) =>
            m.id === assistantMsgId ? { ...m, pending: false, error: message, time: m.time || nowStr } : m
          )
        );
      }
    } finally {
      setBusy(false);
      loadSessions(key);
    }
  }

  function handleFormSubmit(e) {
    e?.preventDefault();
    const text = input.trim();
    if ((!text && !attachedImage) || busy) return;
    const lower = text.toLowerCase();
    const isNearestQuery =
      (lower.includes("bưu điện") || lower.includes("bưu cục")) &&
      (lower.includes("gần") || lower.includes("ở đâu") || lower.includes("quanh đây") || lower.includes("gần tôi") || lower.includes("gần nhất"));
    if (isNearestQuery && !userLocation && navigator.geolocation) {
      requestUserLocation((loc) => {
        send(null, text, loc);
      });
      return;
    }
    send(e, text);
  }

  // Khi click vào thẻ gợi ý (Suggestion Card)
  function handleSuggestionClick(text) {
    setInput(text);
    send(null, text);
  }

  async function readAnswer(message) {
    if (playingMessageId === message.id) {
      stopAudio();
      return;
    }
    stopAudio();
    const text = message.answer || message.text;
    if (!text) return;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) {
      setNotice("Trình duyệt không hỗ trợ Web Audio.");
      return;
    }
    const controller = new AbortController();
    const context = new AudioContextClass();
    stream.current = { controller, context };
    context.resume().catch(() => { });
    setStreamingAudio(true);
    setPlayingMessageId(message.id);

    try {
      const response = await request("/api/tts/stream", key, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, voice: voiceName }),
        signal: controller.signal,
      });
      await playWavStream(response, context, {
        signal: controller.signal,
        onFirstAudio: () => {
          setStreamingAudio(true);
          setPlayingMessageId(message.id);
        },
      });
    } catch (e) {
      if (e.name !== "AbortError") setNotice(e.message);
    } finally {
      if (stream.current?.controller === controller) {
        setStreamingAudio(false);
        setPlayingMessageId(null);
      }
    }
  }

  function handleCopy(id, text) {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  }

  function toggleLike(id) {
    setLikedMap((prev) => ({ ...prev, [id]: !prev[id] }));
    if (!likedMap[id]) setDislikedMap((prev) => ({ ...prev, [id]: false }));
  }

  function toggleDislike(id) {
    setDislikedMap((prev) => ({ ...prev, [id]: !prev[id] }));
    if (!dislikedMap[id]) setLikedMap((prev) => ({ ...prev, [id]: false }));
  }

  // Phân loại lịch sử chat THẬT (Từ backend SQLite)
  const isToday = (dateVal) => {
    if (!dateVal) return false;
    const date = typeof dateVal === "number" ? new Date(dateVal * 1000) : new Date(dateVal);
    const today = new Date();
    return (
      date.getDate() === today.getDate() &&
      date.getMonth() === today.getMonth() &&
      date.getFullYear() === today.getFullYear()
    );
  };

  const realTodaySessions = sessions.filter((s) => isToday(s.updated || s.updated_at || s.created_at));
  const realEarlierSessions = sessions.filter((s) => !isToday(s.updated || s.updated_at || s.created_at));

  return (
    <div className="mipo-layout">
      {/* 1. THANH ĐIỀU HƯỚNG TRÊN CÙNG (HEADER) */}
      <header className="mipo-header">
        {/* Logo chính thức từ logo-mipo.png */}
        <div className="header-brand">
          <img
            src="/logo-mipo.png"
            alt="MiPo - Hỏi gì khó, có MiPo!"
            className="header-logo-image"
            onClick={newChat}
          />
        </div>

        {/* Các nút bấm điều hướng bên phải */}
        <div className="header-nav">
          <button className="nav-pill active" title="Trang chủ" onClick={newChat}>
            <Home size={15} />
            <span>Trang chủ</span>
          </button>
          <button className="nav-pill" onClick={() => setShowGuideModal(true)} title="Hướng dẫn sử dụng">
            <Star size={15} />
            <span>Hướng dẫn</span>
          </button>
          <button className="nav-pill" onClick={() => setShowContactModal(true)} title="Liên hệ hỗ trợ">
            <Mail size={15} />
            <span>Liên hệ</span>
          </button>

          {/* Nút 4 ô vuông mở Menu Công cụ (Nhận diện bì thư, Voice-AI) */}
          <div className="tools-dropdown-wrapper" ref={toolsDropdownRef}>
            <button
              className={`icon-circle-btn ${showToolsDropdown ? "active" : ""}`}
              onClick={() => setShowToolsDropdown(!showToolsDropdown)}
              title="Công cụ tiện ích"
            >
              <LayoutGrid size={18} />
            </button>

            {showToolsDropdown && (
              <div className="tools-popover-card">
                <div className="tools-popover-title">Công cụ</div>
                <button
                  className="tool-action-row"
                  onClick={() => {
                    setShowToolsDropdown(false);
                    envelopeInput.current?.click();
                  }}
                >
                  <EnvelopeAiIcon size={19} />
                  <span>Nhận diện bì thư</span>
                </button>
                <button
                  className="tool-action-row"
                  onClick={() => {
                    setShowToolsDropdown(false);
                    setVoice(!voice);
                    setNotice(
                      !voice
                        ? "Đã kích hoạt chế độ Voice-AI (Tự động đọc to sau khi trả lời)."
                        : "Đã tắt chế độ Voice-AI."
                    );
                  }}
                >
                  <Volume2 size={18} color={voice ? "#2563eb" : "#475569"} />
                  <span>Đọc to giọng nói (TTS){voice ? " (Bật)" : ""}</span>
                </button>
              </div>
            )}
          </div>

          <div
            className="user-avatar-circle"
            title="Tài khoản / Cài đặt"
            onClick={() => setShowSettingsModal(true)}
          >
            <User size={20} color="#94a3b8" />
          </div>
        </div>
      </header>

      {/* 2. KHU VỰC THÂN GỒM SIDEBAR VÀ KHUNG CHAT */}
      <div className="mipo-body">
        {/* SIDEBAR BÊN TRÁI */}
        <aside className="mipo-sidebar">
          {/* Nút tạo đoạn trò chuyện mới */}
          <button className="new-chat-button" onClick={newChat} disabled={busy}>
            <Plus size={16} />
            <span>Đoạn trò chuyện mới</span>
          </button>

          {/* Danh sách lịch sử chat THẬT */}
          <div className="history-container">
            {sessions.length === 0 ? (
              <div className="history-empty-note">
                Chưa có đoạn trò chuyện nào. Bấm nút trên hoặc nhập câu hỏi để bắt đầu!
              </div>
            ) : (
              <>
                {/* Nhóm Hôm nay nếu có */}
                {realTodaySessions.length > 0 && (
                  <div className="history-group">
                    <div className="history-group-title">Hôm nay</div>
                    <div className="history-list">
                      {realTodaySessions.map((s) => (
                        <div
                          key={s.id}
                          className={`history-item ${session === s.id ? "active" : ""}`}
                          onClick={() => selectSession(s.id)}
                        >
                          <MessageCircle size={15} className="history-icon" />
                          <span className="history-title" title={s.title}>
                            {s.title}
                          </span>
                          <button
                            type="button"
                            className="delete-item-btn"
                            title="Xóa phiên"
                            onClick={(e) => {
                              e.stopPropagation();
                              deleteSession(s.id);
                            }}
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Nhóm Các ngày trước nếu có */}
                {realEarlierSessions.length > 0 && (
                  <div className="history-group">
                    <div className="history-group-title">07 Ngày trước</div>
                    <div className="history-list">
                      {realEarlierSessions.map((s) => (
                        <div
                          key={s.id}
                          className={`history-item ${session === s.id ? "active" : ""}`}
                          onClick={() => selectSession(s.id)}
                        >
                          <MessageCircle size={15} className="history-icon" />
                          <span className="history-title" title={s.title}>
                            {s.title}
                          </span>
                          <button
                            type="button"
                            className="delete-item-btn"
                            title="Xóa phiên"
                            onClick={(e) => {
                              e.stopPropagation();
                              deleteSession(s.id);
                            }}
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>

          {/* Hai huy hiệu Google Play và App Store ở chân sidebar */}
          <div className="sidebar-app-stores">
            <GooglePlayBadge />
            <AppStoreBadge />
          </div>
        </aside>

        {/* KHUNG CHAT CHÍNH (MAIN CHAT AREA) */}
        <main className="mipo-chat-area">
          {/* Menu trỏ xuống chọn Chatbot ĐKCL / Chatbot mvno */}
          {/* Thanh điều khiển góc trên: Menu Chatbot */}
          <div className="chat-top-control">
            <div className="bot-dropdown-wrapper" ref={botDropdownRef}>
              <button
                className="bot-pill-selector-btn"
                onClick={() => setShowBotDropdown(!showBotDropdown)}
                title="Chọn Chatbot"
              >
                <span>{selectedBot}</span>
                <ChevronDown size={14} className={showBotDropdown ? "rotate" : ""} />
              </button>

              {showBotDropdown && (
                <div className="bot-dropdown-popover">
                  {CHATBOT_OPTIONS.map((botName) => {
                    const isSelected = selectedBot === botName;
                    return (
                      <button
                        key={botName}
                        className={`bot-dropdown-option ${isSelected ? "selected" : ""}`}
                        onClick={() => {
                          setSelectedBot(botName);
                          setShowBotDropdown(false);
                          setNotice(`Đã chuyển sang ${botName}.`);
                        }}
                      >
                        {botName}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          {/* Khu vực luồng tin nhắn (Conversation View) */}
          <div className="chat-messages-scroll" aria-live="polite">
            {/* KHI NEW CHAT (Chưa có tin nhắn nào): HIỂN THỊ CHÍNH XÁC NHƯ ẢNH MẪU */}
            {messages.length === 0 ? (
              <div className="new-chat-hero">
                <div className="hero-greeting">
                  Xin chào <span className="demo-name-purple">Demo</span>
                </div>
                <h1 className="hero-heading">Tôi có thể giúp gì cho bạn?</h1>
                <TypingEffect />
              </div>
            ) : (
              /* Khi đã bắt đầu hội thoại: Hiển thị các tin nhắn */
              messages.map((message) =>
                message.role === "user" ? (
                  <div className="chat-row user-row" key={message.id}>
                    <div className="user-avatar-small">
                      <User size={18} color="#94a3b8" />
                    </div>
                    <div className="user-bubble-box">
                      {message.image && (
                        <div className="attached-image-wrapper">
                          <img src={message.image} alt="Đính kèm" className="attached-image-render" />
                        </div>
                      )}
                      <div className="user-message-text">{message.text}</div>
                      <span className="bubble-timestamp">{message.time || getCurrentTimeString(message.created)}</span>
                    </div>
                  </div>
                ) : (
                  <div className="chat-row bot-row" key={message.id}>
                    <div className="bot-left-col">
                      <img
                        src="/bot.jpg"
                        alt="MiPo Avatar"
                        className="mipo-avatar-img"
                      />
                      {!message.pending && Boolean(message.answer || message.error) && (
                        <div className="bot-quick-actions">
                          <button
                            className="quick-action-btn"
                            title="Hữu ích"
                            onClick={() => toggleLike(message.id)}
                          >
                            <ThumbsUp
                              size={14}
                              color={likedMap[message.id] ? "#2563eb" : "#94a3b8"}
                              fill={likedMap[message.id] ? "#2563eb" : "none"}
                            />
                          </button>
                          <button
                            className="quick-action-btn"
                            title="Chưa đúng"
                            onClick={() => toggleDislike(message.id)}
                          >
                            <ThumbsDown
                              size={14}
                              color={dislikedMap[message.id] ? "#ef4444" : "#94a3b8"}
                              fill={dislikedMap[message.id] ? "#ef4444" : "none"}
                            />
                          </button>
                          <button
                            className="quick-action-btn"
                            title="Sao chép"
                            onClick={() => handleCopy(message.id, message.answer || message.error || "")}
                          >
                            {copiedId === message.id ? (
                              <Check size={14} color="#16a34a" />
                            ) : (
                              <Copy size={14} />
                            )}
                          </button>
                          <button
                            className={`quick-action-btn ${playingMessageId === message.id ? "tts-playing" : ""}`}
                            title={
                              playingMessageId === message.id
                                ? "Đang phát giọng đọc — Bấm để dừng nói"
                                : "Nghe giọng đọc (TTS)"
                            }
                            onClick={() => readAnswer(message)}
                          >
                            {playingMessageId === message.id ? (
                              <Square size={12} fill="currentColor" />
                            ) : (
                              <Volume2 size={14} />
                            )}
                          </button>
                        </div>
                      )}
                    </div>

                    <div className="bot-content-col">
                      <div className="bot-top-time">{message.time || getCurrentTimeString(message.created)}</div>

                      {message.pending ? (
                        <div className="bot-thinking-card">
                          <div className="thinking-header">
                            <span className="thinking-pulse-dot" />
                            <span className="thinking-title">MiPo đang suy nghĩ và tổng hợp dữ liệu</span>
                            <span className="thinking-typing-dots">
                              <span />
                              <span />
                              <span />
                            </span>
                          </div>

                          {/* Chi tiết tiến trình định tuyến và Sub-agent đang xử lý trực tiếp */}
                          {events.length > 0 && (
                            <div className="thinking-steps-box">
                              {events
                                .filter((e) => e.type === "router_decision")
                                .slice(-1)
                                .map((e, idx) => (
                                  <div key={`r-${idx}`} className="thinking-step-item">
                                    <span className={`step-badge ${e.route === "fast" ? "fast-rag" : "deep-agent"}`}>
                                      {e.route === "fast" ? "Tuyến nhanh" : "Deep Agent"}
                                    </span>
                                    <span className="step-text">{e.reason}</span>
                                  </div>
                                ))}
                              {events
                                .filter((e) => e.type === "task_start" || e.type === "task_end")
                                .slice(-2)
                                .map((e, idx) => (
                                  <div key={`task-${idx}`} className="thinking-step-item">
                                    <span className="step-pulse-dot" />
                                    <span className="step-agent-name">{e.agent}</span>
                                    <span className="step-status">
                                      {e.type === "task_start" ? "đang phân tích dữ liệu..." : "hoàn tất"}
                                    </span>
                                  </div>
                                ))}
                            </div>
                          )}

                          {/* Thanh Shimmer Skeleton tạo cảm giác tải mượt mà */}
                          <div className="thinking-skeleton">
                            <div className="skeleton-line w-75" />
                            <div className="skeleton-line w-50" />
                          </div>
                        </div>
                      ) : (
                        <>
                          <FormattedAnswer text={message.answer || message.error} />

                          {/* Thẻ hành động tương tác cho Đơn hàng nháp (HITL) hoặc Vận đơn đã tạo */}
                          {message.answer && (
                            <PostalActionCard
                              text={message.answer}
                              onSend={(actionText) => send(null, actionText)}
                              onSetInput={(val) => setInput(val)}
                            />
                          )}

                          {/* Nguồn trích dẫn nếu có */}
                          {message.sources?.length > 0 && (
                            <details className="mipo-sources-panel">
                              <summary>
                                <FileText size={13} />
                                <span>{message.sources.length} tài liệu nguồn tham chiếu</span>
                              </summary>
                              <div className="sources-list-box">
                                {message.sources.map((src) => (
                                  <div className="source-item" key={src.citation_id}>
                                    <div className="source-meta">
                                      <span className="source-badge">[{src.citation_id}]</span>
                                      <strong>{src.filename}</strong>
                                      <span className="source-loc">({src.location})</span>
                                    </div>
                                    <p className="source-excerpt">{src.excerpt}</p>
                                  </div>
                                ))}
                              </div>
                            </details>
                          )}

                          {/* Thông tin tuyến xử lý và độ trễ */}
                          {message.answer && (
                            <div className="message-sub-info">
                              {message.route && (
                                <span className={`route-tag ${message.route}`}>
                                  {message.route === "calculator" ? "Tính toán" : message.route === "local" ? "Phản hồi tức thì" : message.route === "fast" || message.route === "fast_fallback" ? "Fast RAG" : "Deep Agent"}
                                </span>
                              )}
                              <span className="latency-text">
                                {((message.elapsed_ms || 0) / 1000).toFixed(1)}s
                              </span>
                              {message.blob && (
                                <a href={message.blob} download="mipo_answer.wav" className="download-wav-link">
                                  Tải WAV
                                </a>
                              )}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                )
              )
            )}

            {/* Trạng thái tiến trình của Agent khi đang chạy (chỉ hiển thị nếu không có tin nhắn đang pending) */}
            {busy && events.length > 0 && !messages.some((m) => m.pending) && (
              <div className="activity-floating-bar">
                {events
                  .filter((e) => e.type === "router_decision")
                  .slice(-1)
                  .map((e, idx) => (
                    <span key={`r-${idx}`} className="activity-chip route-chip">
                      {e.route === "fast" ? "Tuyến nhanh" : "Deep Agent"}: {e.reason}
                    </span>
                  ))}
                {events
                  .filter((e) => e.type === "task_start" || e.type === "task_end")
                  .slice(-3)
                  .map((e, idx) => (
                    <span key={idx} className="activity-chip">
                      {e.agent} · {e.type === "task_start" ? "đang xử lý" : "hoàn thành"}
                    </span>
                  ))}
              </div>
            )}

            <div ref={endRef} />
          </div>

          {/* 3. KHU VỰC NHẬP DƯỚI CÙNG (COMPOSER) */}
          <div className="chat-composer-wrapper">
            {/* KHI Ở MÀN HÌNH MỚI: HIỂN THỊ CÁC THẺ GỢI Ý (SUGGESTIONS) PHÍA TRÊN KHUNG NHẬP */}
            {messages.length === 0 && (
              <div className="suggestions-wrapper">
                <div className="suggestions-heading">Gợi ý dành cho bạn</div>
                <div className="suggestions-cards-row">
                  <button
                    type="button"
                    className="suggestion-box"
                    onClick={() => handleSuggestionClick("Tra cứu trạng thái bưu gửi có mã vận đơn là gì?")}
                    disabled={busy}
                  >
                    <Sparkles size={16} className="sparkle-blue" />
                    <span>Tra cứu trạng thái bưu gửi có mã vận đơn là gì?</span>
                  </button>
                  <button
                    type="button"
                    className="suggestion-box"
                    onClick={handleFindNearestPostOffice}
                    disabled={busy || locating}
                  >
                    <MapPin size={16} color="#2563eb" />
                    <span>Định vị GPS: Tìm bưu điện VNPost gần tôi nhất</span>
                  </button>
                  <button
                    type="button"
                    className="suggestion-box"
                    onClick={() => handleSuggestionClick("Tra cứu quy định về thủ tục hải quan cho hàng quốc tế")}
                    disabled={busy}
                  >
                    <Sparkles size={16} className="sparkle-blue" />
                    <span>Tra cứu quy định về thủ tục hải quan cho hàng quốc tế</span>
                  </button>
                </div>
              </div>
            )}

            {/* Hiển thị ảnh xem trước nếu đã đính kèm */}
            {attachedImage && (
              <div className="attached-preview-chip">
                <img src={attachedImage} alt="Đính kèm" />
                <span>Đã đính kèm ảnh</span>
                <button onClick={() => setAttachedImage(null)}>
                  <X size={12} />
                </button>
              </div>
            )}

            {/* Hiển thị chip vị trí GPS nếu người dùng cho phép định vị */}
            {userLocation && (
              <div className="attached-preview-chip location-chip">
                <MapPin size={13} color="#2563eb" />
                <span>GPS: {userLocation.latitude.toFixed(4)}, {userLocation.longitude.toFixed(4)}</span>
                <button type="button" onClick={() => setUserLocation(null)} title="Bỏ định vị">
                  <X size={12} />
                </button>
              </div>
            )}

            {/* Thông báo lỗi hoặc cảnh báo */}
            {notice && (
              <div className="mipo-notice-bar">
                <FontAwesomeIcon
                  icon={
                    notice.includes("Lỗi") || notice.includes("không")
                      ? faTriangleExclamation
                      : notice.includes("thành công")
                      ? faCircleCheck
                      : faCircleInfo
                  }
                  className="notice-fa-icon"
                />
                <span>{notice}</span>
                <button onClick={() => setNotice("")} title="Đóng thông báo">
                  <X size={13} />
                </button>
              </div>
            )}

            {/* Hiển thị chỉ báo khi đang lắng nghe giọng nói */}
            {isRecording && (
              <div className="voice-recording-badge">
                <FontAwesomeIcon icon={faMicrophone} className="voice-recording-icon animate-pulse" />
                <span>Đang lắng nghe giọng nói tiếng Việt... Bấm lại nút Mic để kết thúc</span>
              </div>
            )}

            {/* Hiển thị chỉ báo khi đang phát âm thanh TTS */}
            {streamingAudio && (
              <div className="audio-playing-badge" onClick={stopAudio} title="Bấm để dừng nói">
                <span className="audio-playing-dot" />
                <span>Mipo đang đọc câu trả lời... (Bấm để dừng nói)</span>
                <Square size={11} fill="currentColor" className="audio-stop-btn-badge" />
              </div>
            )}

            {/* Khung nhập hình viên thuốc tròn đúng ảnh mẫu */}
            <form className="mipo-input-box" onSubmit={handleFormSubmit}>
              {/* Nút đính kèm ẩn */}
              <input
                ref={imageInput}
                type="file"
                accept="image/*"
                hidden
                onChange={handleImageSelect}
              />
              <input
                ref={envelopeInput}
                type="file"
                accept="image/*"
                hidden
                onChange={(e) => {
                  handleImageSelect(e);
                  setInput("Hãy đọc và nhận diện thông tin người gửi, người nhận, mã bưu gửi trên bì thư này.");
                }}
              />
              <input
                ref={uploadInput}
                type="file"
                accept=".docx,.txt,.pdf"
                multiple
                hidden
                onChange={(e) => uploadFiles(Array.from(e.target.files))}
              />

              <button
                type="button"
                className="input-attach-btn"
                title="Đính kèm ảnh"
                onClick={() => imageInput.current?.click()}
                disabled={busy}
              >
                <Paperclip size={18} color="#94a3b8" />
              </button>

              <button
                type="button"
                className={`input-attach-btn ${userLocation ? "loc-active" : ""}`}
                title={userLocation ? `Đã có vị trí GPS (${userLocation.latitude.toFixed(3)}, ${userLocation.longitude.toFixed(3)}). Bấm để tìm bưu điện gần nhất!` : "Cho phép vị trí GPS để tìm bưu điện VNPost gần nhất"}
                onClick={handleFindNearestPostOffice}
                disabled={busy || locating}
              >
                <MapPin size={18} color={userLocation ? "#2563eb" : locating ? "#f59e0b" : "#94a3b8"} />
              </button>

              <input
                type="text"
                className="mipo-text-input"
                placeholder={isRecording ? "Đang lắng nghe giọng nói của bạn..." : "Vui lòng đặt câu hỏi!"}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onPaste={handlePaste}
                disabled={busy}
              />

              <div className="input-right-actions">
                {/* Dải ô chọn chế độ xử lý mở lên trên: Tự động / Nhanh / Chuyên sâu (đặt bên phải cùng cụm action) */}
                <div className="input-mode-dropdown-wrapper" ref={modeDropdownRef}>
                  <button
                    type="button"
                    className={`input-mode-pill mode-${routeMode} ${showModeDropdown ? "active" : ""}`}
                    onClick={() => setShowModeDropdown(!showModeDropdown)}
                    title="Chọn chế độ xử lý (Tự động / Nhanh / Chuyên sâu)"
                  >
                    {routeMode === "auto" && <FontAwesomeIcon icon={faWandMagicSparkles} className="mode-pill-icon icon-auto" />}
                    {routeMode === "fast" && <FontAwesomeIcon icon={faBolt} className="mode-pill-icon icon-fast" />}
                    {routeMode === "deep" && <FontAwesomeIcon icon={faBrain} className="mode-pill-icon icon-deep" />}
                    <span className="mode-pill-label">
                      {routeMode === "auto" ? "Tự động" : routeMode === "fast" ? "Nhanh" : "Chuyên sâu"}
                    </span>
                    <ChevronDown size={12} className={`mode-pill-chevron ${showModeDropdown ? "rotate" : ""}`} />
                  </button>

                  {showModeDropdown && (
                    <div className="mode-popover-card">
                      <div className="mode-popover-header">Chế độ xử lý</div>
                      <button
                        type="button"
                        className={`mode-popover-option ${routeMode === "auto" ? "selected" : ""}`}
                        onClick={() => {
                          setRouteMode("auto");
                          setShowModeDropdown(false);
                          setNotice("Chế độ Tự động: Hệ thống sẽ tự phân tích câu hỏi để chọn Fast RAG hoặc Deep Agent.");
                        }}
                      >
                        <div className="mode-option-icon icon-auto">
                          <FontAwesomeIcon icon={faWandMagicSparkles} />
                        </div>
                        <div className="mode-option-content">
                          <div className="mode-option-title">
                            <span>Tự động (Auto)</span>
                            {routeMode === "auto" && <Check size={14} className="mode-option-check" />}
                          </div>
                          <div className="mode-option-desc">Tự phân loại tuyến xử lý phù hợp theo độ phức tạp câu hỏi</div>
                        </div>
                      </button>

                      <button
                        type="button"
                        className={`mode-popover-option ${routeMode === "fast" ? "selected" : ""}`}
                        onClick={() => {
                          setRouteMode("fast");
                          setShowModeDropdown(false);
                          setNotice("Chế độ Nhanh: Tra cứu tài liệu 1 bước, tối ưu tốc độ.");
                        }}
                      >
                        <div className="mode-option-icon icon-fast">
                          <FontAwesomeIcon icon={faBolt} />
                        </div>
                        <div className="mode-option-content">
                          <div className="mode-option-title">
                            <span>Nhanh (Fast RAG)</span>
                            {routeMode === "fast" && <Check size={14} className="mode-option-check" />}
                          </div>
                          <div className="mode-option-desc">Tra cứu nhanh tài liệu bưu chính 1 bước, độ trễ thấp</div>
                        </div>
                      </button>

                      <button
                        type="button"
                        className={`mode-popover-option ${routeMode === "deep" ? "selected" : ""}`}
                        onClick={() => {
                          setRouteMode("deep");
                          setShowModeDropdown(false);
                          setNotice("Chế độ Chuyên sâu: Kích hoạt hệ thống đa tác tử Deep Agent.");
                        }}
                      >
                        <div className="mode-option-icon icon-deep">
                          <FontAwesomeIcon icon={faBrain} />
                        </div>
                        <div className="mode-option-content">
                          <div className="mode-option-title">
                            <span>Chuyên sâu (Deep Agent)</span>
                            {routeMode === "deep" && <Check size={14} className="mode-option-check" />}
                          </div>
                          <div className="mode-option-desc">Đa tác tử phân tích, lập luận, so sánh và tính cước</div>
                        </div>
                      </button>
                    </div>
                  )}
                </div>
                {/* Nút Microphone: Nhận diện giọng nói STT */}
                <button
                  type="button"
                  className={`input-action-btn ${isRecording ? "recording-active animate-pulse" : ""}`}
                  title={
                    isRecording
                      ? "Dừng ghi âm (Đang lắng nghe...)"
                      : "Nói câu hỏi (Voice STT tiếng Việt)"
                  }
                  onClick={handleMicClick}
                >
                  <Mic size={18} color={isRecording ? "#dc2626" : "#64748b"} />
                </button>

                {/* Nút TTS: Đọc to giọng nói */}
                <button
                  type="button"
                  className={`input-action-btn ${streamingAudio ? "tts-playing" : voice ? "voice-active" : ""}`}
                  title={
                    streamingAudio
                      ? "Đang phát giọng đọc — Bấm để dừng nói"
                      : voice
                      ? "Đọc to giọng nói (TTS): Đang BẬT — Bấm để tắt"
                      : "Bật chế độ đọc to giọng nói (TTS)"
                  }
                  onClick={() => {
                    if (streamingAudio) {
                      stopAudio();
                    } else {
                      handleToggleVoice();
                    }
                  }}
                >
                  {streamingAudio ? (
                    <Square size={14} fill="currentColor" color="#2563eb" />
                  ) : (
                    <Volume2 size={18} color={voice ? "#2563eb" : "#64748b"} />
                  )}
                </button>

                {/* Nút Gửi câu hỏi */}
                <button
                  type={busy ? "button" : "submit"}
                  className="input-send-btn"
                  title={busy ? "Dừng phản hồi" : "Gửi"}
                  disabled={!busy && !input.trim() && !attachedImage}
                  onClick={busy ? () => abort.current?.abort() : undefined}
                >
                  {busy ? <Square size={16} /> : <Send size={16} />}
                </button>
              </div>
            </form>

            {/* Dòng ghi chú bản quyền và miễn trừ trách nhiệm ở chân trang */}
            <div className="composer-disclaimer">
              Trợ lý ảo là công cụ hỗ trợ. Hãy kiểm chứng lại thông tin trước khi xử lý những công việc quan
              trọng!
            </div>
          </div>
        </main>
      </div>

      {/* 4. CÁC MODAL TIỆN ÍCH BỔ SUNG */}
      {/* Modal Hướng dẫn */}
      {showGuideModal && (
        <div className="modal-backdrop" onClick={() => setShowGuideModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h3>Hướng dẫn sử dụng MiPo VNPost</h3>
              <button onClick={() => setShowGuideModal(false)}>
                <X size={18} />
              </button>
            </div>
            <div className="modal-content-scroll">
              <p>MiPo là trợ lý AI thông minh chuyên tra cứu tình hình và chất lượng phát bưu gửi:</p>
              <ul>
                <li>
                  <strong>Chất lượng phát:</strong> Hỏi các câu như: <em>"Tỷ lệ phát thành công của Bưu điện Cần Thơ tháng vừa rồi?"</em>
                </li>
                <li>
                  <strong>So sánh &amp; Xu hướng:</strong> Hỏi: <em>"So sánh sản lượng phát giữa quý 1 và quý 2."</em>
                </li>
                <li>
                  <strong>Vận chuyển (Leg):</strong> Hỏi: <em>"Thời gian chạy các leg tại bưu điện tỉnh Bình Dương."</em>
                </li>
                <li>
                  <strong>Báo cáo chi tiết:</strong> Hỏi: <em>"Báo cáo tổng hợp bưu cục Thủ Đức."</em>
                </li>
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Modal Liên hệ */}
      {showContactModal && (
        <div className="modal-backdrop" onClick={() => setShowContactModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h3>Liên hệ Tổng công ty Bưu điện Việt Nam</h3>
              <button onClick={() => setShowContactModal(false)}>
                <X size={18} />
              </button>
            </div>
            <div className="modal-content-scroll">
              <p>
                <strong>Tổng công ty Bưu điện Việt Nam - VNPost</strong>
              </p>
              <p>Địa chỉ: Số 5 Phạm Hùng, Mỹ Đình 2, Nam Từ Liêm, Hà Nội</p>
              <p>Hotline hỗ trợ khách hàng: <strong>1900 54 54 81</strong></p>
              <p>Cổng thông tin: <a href="https://vnpost.vn" target="_blank" rel="noreferrer">vnpost.vn</a></p>
            </div>
          </div>
        </div>
      )}

      {/* Modal Quản lý tài liệu của phiên chat */}
      {showDocModal && (
        <div className="modal-backdrop" onClick={() => setShowDocModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h3>Tài liệu của phiên trò chuyện ({sessionDocs.length})</h3>
              <button onClick={() => setShowDocModal(false)}>
                <X size={18} />
              </button>
            </div>
            <div className="modal-content-scroll">
              <p className="modal-help-text">
                Tải lên file DOCX, TXT để chatbot tra cứu và trích dẫn nguồn riêng trong phiên trò chuyện này:
              </p>
              <button
                className="modal-upload-btn"
                disabled={uploading}
                onClick={() => uploadInput.current?.click()}
              >
                <Upload size={15} />
                <span>{uploading ? "Đang xử lý & lập chỉ mục…" : "Tải lên tệp DOCX / TXT"}</span>
              </button>
              <div className="modal-doc-list">
                {sessionDocs.map((doc) => (
                  <div className="modal-doc-row" key={doc.id}>
                    <FileText size={15} color="#2563eb" />
                    <span className="doc-name">{doc.filename}</span>
                    <button className="doc-del-btn" onClick={() => deleteDoc(doc)}>
                      <Trash2 size={14} color="#ef4444" />
                    </button>
                  </div>
                ))}
                {!sessionDocs.length && (
                  <div className="modal-empty-doc">Chưa có tài liệu nào tải lên trong phiên chat này.</div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Modal Cài đặt & Tiện ích */}
      {showSettingsModal && (
        <div className="modal-backdrop" onClick={() => setShowSettingsModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h3>Cài đặt &amp; Giọng đọc AI</h3>
              <button onClick={() => setShowSettingsModal(false)}>
                <X size={18} />
              </button>
            </div>
            <div className="modal-content-scroll">
              <div className="setting-field">
                <label>Chế độ định tuyến câu hỏi (Router Mode):</label>
                <select
                  value={routeMode}
                  onChange={(e) => setRouteMode(e.target.value)}
                  className="setting-select"
                >
                  <option value="auto">Tự động (Auto) - Hệ thống tự chọn route</option>
                  <option value="fast">Nhanh (Fast RAG) - Trực tiếp 1 bước</option>
                  <option value="deep">Chuyên sâu (Deep Agent) - Đa tác tử</option>
                </select>
              </div>
              <div className="setting-field">
                <label>Giọng đọc ZeroTTS:</label>
                <select
                  value={voiceName}
                  onChange={(e) => setVoiceName(e.target.value)}
                  className="setting-select"
                >
                  {voices.length ? (
                    voices.map((v) => (
                      <option key={v.name} value={v.name}>
                        {v.name}
                      </option>
                    ))
                  ) : (
                    <option value="maichi">maichi (Mặc định)</option>
                  )}
                </select>
              </div>
              <div className="setting-field">
                <label>Trạng thái máy chủ:</label>
                <span className="status-badge-inline">
                  {health ? `Đang hoạt động (${health.version})` : "Đang kiểm tra kết nối"}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
