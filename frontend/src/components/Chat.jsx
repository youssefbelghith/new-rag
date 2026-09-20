import { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const ANSWER_STYLES = ['short and crisp', 'Detailed'];

function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function extOf(name = '') {
  const parts = name.split('.');
  return parts.length > 1 ? parts.pop().toLowerCase() : '';
}

function formatTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

const PaperclipIcon = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
  </svg>
);

const SendIcon = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="22" y1="2" x2="11" y2="13" />
    <polygon points="22 2 15 22 11 13 2 9 22 2" />
  </svg>
);

const SlidersIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="4" y1="21" x2="4" y2="14" />
    <line x1="4" y1="10" x2="4" y2="3" />
    <line x1="12" y1="21" x2="12" y2="12" />
    <line x1="12" y1="8" x2="12" y2="3" />
    <line x1="20" y1="21" x2="20" y2="16" />
    <line x1="20" y1="12" x2="20" y2="3" />
    <line x1="1" y1="14" x2="7" y2="14" />
    <line x1="9" y1="8" x2="15" y2="8" />
    <line x1="17" y1="16" x2="23" y2="16" />
  </svg>
);

function makeId() {
  return (crypto.randomUUID && crypto.randomUUID()) || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function AttachmentCard({ file }) {
  const ext = extOf(file.name);
  return (
    <div className="attachment-card">
      <span className={`attachment-tab ${ext === 'md' ? 'is-md' : ''}`} />
      <div className="attachment-body">
        <p className="attachment-name">{file.name}</p>
        <p className="attachment-meta">{ext ? ext.toUpperCase() : 'FILE'} · {formatBytes(file.size)}</p>
      </div>
      <span className="attachment-status">
        {file.parentStatus === 'uploading' && <span className="attachment-spinner" />}
        {file.parentStatus === 'uploaded' && <span className="attachment-check">✓</span>}
        {file.parentStatus === 'error' && <span className="attachment-error">!</span>}
      </span>
    </div>
  );
}

export default function Chat() {
  const { user } = useAuth();
  const location = useLocation();
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState('');
  const [answerStyle, setAnswerStyle] = useState('short and crisp');
  const [styleOpen, setStyleOpen] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [session, setSession] = useState(null);
  const chatEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const sessionIdRef = useRef(location.state?.sessionId || location.state?.conversationId || makeId());
  const messagesRef = useRef(messages);
  const answerStyleRef = useRef(answerStyle);
  const finalizedRef = useRef(false);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    answerStyleRef.current = answerStyle;
  }, [answerStyle]);

  useEffect(() => {
    const loadConversation = async () => {
      try {
        const requestedSessionId = location.state?.sessionId || location.state?.conversationId;
        if (!requestedSessionId) return;
        sessionIdRef.current = requestedSessionId;
        const response = await axios.get(`/user/sessions/${requestedSessionId}`);
        setSession(response.data);
        finalizedRef.current = false;
        const savedFiles = (response.data.files || []).map((file) => ({
          id: makeId(),
          role: 'user',
          kind: 'files',
          status: 'uploaded',
          files: [{ name: file.name || file, size: null }],
          timestamp: file.timestamp || new Date().toISOString(),
        }));
        const savedMessages = response.data.messages.map((item) => ({
          id: item.id,
          role: item.role,
          kind: 'text',
          text: item.content,
          sources: item.source_file
            ? [{ fichier: item.source_file, page: item.source_page || 1 }]
            : [],
          timestamp: item.created_at,
        }));
        setMessages([...savedFiles, ...savedMessages].sort(
          (first, second) => new Date(first.timestamp) - new Date(second.timestamp)
        ));
      } catch (error) {
        setMessages([]);
        console.error('Could not load session', error);
      }
    };

    loadConversation();
  }, [location.state?.sessionId, location.state?.conversationId]);

  useEffect(() => {
    const finishConversation = async (event) => {
      const startNew = event.detail?.startNew;
      const onComplete = event.detail?.onComplete;

      const resetForNewConversation = async () => {
        if (startNew) {
          sessionIdRef.current = makeId();
          finalizedRef.current = false;
          setMessages([]);
          setSession(null);
        }
        onComplete?.();
      };

      if (finalizedRef.current || messagesRef.current.length === 0) {
        await resetForNewConversation();
        return;
      }

      const textMessages = messagesRef.current.filter((message) => message.kind === 'text');
      const exchanges = [];
      for (let index = 0; index < textMessages.length - 1; index += 1) {
        const questionMessage = textMessages[index];
        const answerMessage = textMessages[index + 1];
        if (questionMessage.role === 'user' && answerMessage.role === 'assistant') {
          exchanges.push({
            question: questionMessage.text,
            answer: answerMessage.text,
            sources: answerMessage.sources || [],
          });
          index += 1;
        }
      }
      const files = messagesRef.current
        .filter((message) => message.kind === 'files' && message.status === 'uploaded')
        .flatMap((message) => message.files.map((file) => ({
          name: file.name,
          timestamp: message.timestamp,
        })));

      finalizedRef.current = true;
      try {
        await axios.post('/user/conversations/finalize', {
          session_id: sessionIdRef.current,
          exchanges,
          files,
        });
        await resetForNewConversation();
      } catch (err) {
        finalizedRef.current = false;
        console.error('Could not save conversation', err);
      }
    };

    window.addEventListener('chat:finish', finishConversation);
    return () => window.removeEventListener('chat:finish', finishConversation);
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, processing]);

  const handleFileChange = async (e) => {
    const selected = Array.from(e.target.files || []);
    e.target.value = '';
    if (selected.length === 0) return;

    const id = makeId();
    const fileMsg = {
      id,
      role: 'user',
      kind: 'files',
      status: 'uploading',
      files: selected.map((f) => ({ name: f.name, size: f.size })),
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, fileMsg]);

    const formData = new FormData();
    selected.forEach((file) => formData.append('files', file));

    try {
      await axios.post('/files/upload', formData, {
        params: { session_id: sessionIdRef.current },
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, status: 'uploaded' } : m)));
      setMessages((prev) => [
        ...prev,
        {
          id: makeId(),
          role: 'assistant',
          kind: 'text',
          text:
            selected.length === 1
              ? `Got "${selected[0].name}" — I've read through it. Ask me anything about it.`
              : `Got all ${selected.length} files — I've read through them. Ask me anything.`,
          timestamp: new Date().toISOString(),
        },
      ]);
    } catch (err) {
      setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, status: 'error' } : m)));
      setMessages((prev) => [
        ...prev,
        {
          id: makeId(),
          role: 'assistant',
          kind: 'text',
          text: 'That upload didn\'t go through: ' + (err.response?.data?.detail || err.message),
          timestamp: new Date().toISOString(),
        },
      ]);
    }
  };

  const handleAsk = async (e) => {
    e.preventDefault();
    const text = question.trim();
    if (!text || processing) return;

    setMessages((prev) => [
      ...prev,
      { id: makeId(), role: 'user', kind: 'text', text, timestamp: new Date().toISOString() },
    ]);
    setQuestion('');
    setProcessing(true);

    try {
      if (!session) {
        const created = await axios.post('/user/sessions', {
          session_id: sessionIdRef.current,
          model_settings: { answer_style: answerStyleRef.current },
        });
        setSession(created.data);
      }
      const response = await axios.post('/ask', {
        question: text,
        session_id: sessionIdRef.current,
        answer_style: answerStyle,
        filter_dict: null,
      });
      const { answer, sources } = response.data;
      setMessages((prev) => [
        ...prev,
        {
          id: makeId(),
          role: 'assistant',
          kind: 'text',
          text: answer,
          sources,
          timestamp: new Date().toISOString(),
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: makeId(),
          role: 'assistant',
          kind: 'text',
          text: 'Error: ' + (err.response?.data?.detail || err.message),
          timestamp: new Date().toISOString(),
        },
      ]);
    } finally {
      setProcessing(false);
    }
  };

  return (
    <div className="chat-page">
      <div className="chat-column">
        <div className="chat-header">
          <div className="chat-header-info">
            <span className="chat-avatar assistant-avatar">A</span>
            <div>
              <p className="chat-header-name">{session?.title || 'New conversation'}</p>
              <p className="chat-header-status">
                <span className="status-dot" />
                {processing ? 'typing…' : 'online'}
              </p>
            </div>
          </div>

          <div className="chat-header-actions">
            <button
              type="button"
              className="icon-btn"
              onClick={() => setStyleOpen((v) => !v)}
              aria-label="Answer style settings"
            >
              <SlidersIcon />
            </button>
            {styleOpen && (
              <div className="style-popover">
                <p className="style-popover-title">Answer style</p>
                {ANSWER_STYLES.map((opt) => (
                  <button
                    key={opt}
                    className={`style-option ${answerStyle === opt ? 'is-selected' : ''}`}
                    onClick={() => {
                      setAnswerStyle(opt);
                      setStyleOpen(false);
                    }}
                  >
                    {opt}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="chat-scroll">
          {messages.length === 0 && (
            <div className="chat-empty">
              <span className="chat-empty-mark">A</span>
              <p className="chat-empty-title">Send Alex a file to start</p>
              <p className="chat-empty-sub">
                Drop in a PDF or Markdown file with the paperclip, then ask anything about it — like texting a
                very well-read friend, {user?.prenom || 'hi'}.
              </p>
            </div>
          )}

          {messages.map((msg) => (
            <div key={msg.id} className={`bubble-row ${msg.role === 'user' ? 'is-user' : 'is-assistant'}`}>
              {msg.role === 'assistant' && <span className="chat-avatar assistant-avatar small">A</span>}
              <div className={`bubble ${msg.role === 'user' ? 'is-user' : 'is-assistant'}`}>
                {msg.kind === 'files' ? (
                  <div className="attachment-group">
                    {msg.files.map((f, i) => (
                      <AttachmentCard key={i} file={{ ...f, parentStatus: msg.status }} />
                    ))}
                  </div>
                ) : (
                  <p style={{ margin: 0 }}>{msg.text}</p>
                )}

                {msg.sources && msg.sources.length > 0 && (
                  <div className="source-chips">
                    {msg.sources.map((src, i) => (
                      <span key={i} className="source-chip">
                        {src.fichier} · p.{src.page}
                      </span>
                    ))}
                  </div>
                )}

                <span className="bubble-time">{formatTime(msg.timestamp)}</span>
              </div>
            </div>
          ))}

          {processing && (
            <div className="bubble-row is-assistant">
              <span className="chat-avatar assistant-avatar small">A</span>
              <div className="bubble is-assistant typing-bubble">
                <span className="typing-dot" />
                <span className="typing-dot" />
                <span className="typing-dot" />
              </div>
            </div>
          )}

          <div ref={chatEndRef} />
        </div>

        <form className="chat-input-row" onSubmit={handleAsk}>
          <input
            type="file"
            ref={fileInputRef}
            multiple
            accept=".pdf,.md"
            onChange={handleFileChange}
            className="hidden-input"
          />
          <button
            type="button"
            className="icon-btn"
            onClick={() => fileInputRef.current?.click()}
            aria-label="Attach files"
          >
            <PaperclipIcon />
          </button>
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Message Alex…"
            className="chat-input"
            disabled={processing}
          />
          <button type="submit" className="send-btn" disabled={processing || !question.trim()} aria-label="Send">
            <SendIcon />
          </button>
        </form>
      </div>
    </div>
  );
}
