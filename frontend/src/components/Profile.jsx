import { useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const MAX_AVATAR_BYTES = 5 * 1024 * 1024; // 5MB

export default function Profile() {
  const { user, updateAvatar } = useAuth();
  const navigate = useNavigate();
  const [info, setInfo] = useState(null);
  const [history, setHistory] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [search, setSearch] = useState('');
  const [avatarError, setAvatarError] = useState('');
  const [avatarSaving, setAvatarSaving] = useState(false);
  const avatarInputRef = useRef(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [infoRes, historyRes, conversationsRes] = await Promise.all([
          axios.get('/user/info'),
          axios.get('/user/history?limit=100'),
          axios.get('/user/conversations?limit=100'),
        ]);
        setInfo(infoRes.data);
        setHistory(historyRes.data);
        setConversations(conversationsRes.data);
      } catch (err) {
        console.error(err);
      }
    };
    fetchData();
  }, []);

  const initials =
    ((info?.prenom?.[0] || user?.prenom?.[0] || '') + (info?.nom?.[0] || user?.email?.[0] || ''))
      .toUpperCase()
      .slice(0, 2) || 'U';

  const handleAvatarPick = () => avatarInputRef.current?.click();

  const handleAvatarChange = (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setAvatarError('');

    if (!file.type.startsWith('image/')) {
      setAvatarError('Please choose an image file.');
      return;
    }
    if (file.size > MAX_AVATAR_BYTES) {
      setAvatarError('Image is too large — keep it under 5MB.');
      return;
    }

    setAvatarSaving(true);
    const reader = new FileReader();
    reader.onload = () => {
      updateAvatar(reader.result);
      setAvatarSaving(false);
    };
    reader.onerror = () => {
      setAvatarError('Could not read that image, try another one.');
      setAvatarSaving(false);
    };
    reader.readAsDataURL(file);
  };

  const filteredHistory = useMemo(() => {
    if (!search.trim()) return conversations;
    const q = search.toLowerCase();
    return conversations.filter(
      (h) =>
        h.title?.toLowerCase().includes(q)
    );
  }, [conversations, search]);

  return (
    <div className="profile-page">
      <div className="profile-inner">
        <div className="profile-hero">
          <div className="profile-avatar-wrap">
            <span className="avatar-ring is-lg">
              <span className="avatar-ring-inner">
                {user?.avatar ? (
                  <img src={user.avatar} alt="Your profile" className="avatar-img" />
                ) : (
                  <span className="avatar-initials is-lg">{initials}</span>
                )}
              </span>
            </span>
            <button
              type="button"
              className="avatar-upload-btn"
              onClick={handleAvatarPick}
              disabled={avatarSaving}
              aria-label="Change profile photo"
              title="Change profile photo"
            >
              {avatarSaving ? (
                <span className="attachment-spinner" />
              ) : (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
                  <circle cx="12" cy="13" r="4" />
                </svg>
              )}
            </button>
            <input
              type="file"
              accept="image/*"
              ref={avatarInputRef}
              onChange={handleAvatarChange}
              className="hidden-input"
            />
          </div>
          <div>
            <h1 className="profile-hero-name">
              {info ? `${info.prenom} ${info.nom}` : user?.prenom || 'Your profile'}
            </h1>
            <p className="profile-hero-email">{info?.email || user?.email}</p>
            {info?.date_creation && (
              <p className="profile-hero-since">
                MEMBER SINCE {new Date(info.date_creation).toLocaleDateString()}
              </p>
            )}
            {avatarError && <p className="auth-error" style={{ margin: '8px 0 0' }}>{avatarError}</p>}
          </div>
        </div>

        <div className="profile-section-head">
          <h2 className="profile-section-title">Conversation history</h2>
          {history.length > 0 && (
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search history…"
              className="history-search"
            />
          )}
        </div>

        {conversations.length === 0 ? (
          <div className="profile-empty">
            No questions asked yet — head to Chat and send Marginalia a file to get started.
          </div>
        ) : filteredHistory.length === 0 ? (
          <div className="profile-empty">No conversations match "{search}".</div>
        ) : (
            <div className="history-list">
            {filteredHistory.map((h) => (
              <button
                type="button"
                key={h.conversation_id}
                className="history-item"
                onClick={() => navigate('/chat', { state: { conversationId: h.conversation_id } })}
              >
                <div className="history-q-row">
                  <span className="history-q-mark">“</span>
                  <p className="history-question">{h.title || 'Conversation'}</p>
                </div>
                <p className="history-meta">
                  {h.message_count} {h.message_count === 1 ? 'exchange' : 'exchanges'}
                  {' · '}
                  {new Date(h.date_message).toLocaleString()}
                </p>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
