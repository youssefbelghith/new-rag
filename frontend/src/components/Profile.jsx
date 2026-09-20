import { useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const MAX_AVATAR_BYTES = 5 * 1024 * 1024; // 5MB

const EditIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 20h9" />
    <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 4Z" />
  </svg>
);

const TrashIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3 6h18" />
    <path d="M8 6V4h8v2" />
    <path d="M19 6l-1 14H6L5 6" />
    <path d="M10 11v5M14 11v5" />
  </svg>
);

export default function Profile() {
  const { user, updateAvatar } = useAuth();
  const navigate = useNavigate();
  const [info, setInfo] = useState(null);
  const [conversations, setConversations] = useState([]);
  const [search, setSearch] = useState('');
  const [editingSessionId, setEditingSessionId] = useState(null);
  const [editingTitle, setEditingTitle] = useState('');
  const [sessionPendingDeletion, setSessionPendingDeletion] = useState(null);
  const [deletingSession, setDeletingSession] = useState(false);
  const [avatarError, setAvatarError] = useState('');
  const [avatarSaving, setAvatarSaving] = useState(false);
  const avatarInputRef = useRef(null);
  const titleInputRef = useRef(null);
  const skipRenameBlurRef = useRef(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [infoRes, conversationsRes] = await Promise.all([
          axios.get('/user/info'),
          axios.get('/user/conversations?limit=100'),
        ]);
        setInfo(infoRes.data);
        setConversations(conversationsRes.data.filter((session) => Number(session.message_count) > 0));
      } catch (err) {
        console.error(err);
      }
    };
    fetchData();
  }, []);

  useEffect(() => {
    if (editingSessionId !== null) {
      titleInputRef.current?.focus();
      titleInputRef.current?.select();
    }
  }, [editingSessionId]);

  const startRenaming = (session) => {
    skipRenameBlurRef.current = false;
    setEditingSessionId(session.id);
    setEditingTitle(session.title || '');
  };

  const cancelRenaming = (session) => {
    setEditingSessionId(null);
    setEditingTitle(session.title || '');
  };

  const saveRenaming = async (session) => {
    if (skipRenameBlurRef.current) {
      skipRenameBlurRef.current = false;
      return;
    }
    const title = editingTitle.trim();
    if (!title || title === session.title) {
      cancelRenaming(session);
      return;
    }

    try {
      const response = await axios.patch(`/user/sessions/${session.id}`, { title });
      setConversations((current) => current.map((item) => item.id === session.id ? response.data : item));
    } catch (error) {
      console.error('Could not rename session', error);
    } finally {
      setEditingSessionId(null);
    }
  };

  const requestSessionDeletion = (session) => {
    setSessionPendingDeletion(session);
  };

  const cancelSessionDeletion = () => {
    if (deletingSession) return;
    setSessionPendingDeletion(null);
  };

  const confirmSessionDeletion = async () => {
    if (!sessionPendingDeletion || deletingSession) return;
    setDeletingSession(true);
    try {
      await axios.delete(`/user/sessions/${sessionPendingDeletion.id}`);
      setConversations((current) => current.filter((item) => item.id !== sessionPendingDeletion.id));
      setSessionPendingDeletion(null);
    } catch (error) {
      console.error('Could not delete session', error);
    } finally {
      setDeletingSession(false);
    }
  };

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
    reader.onload = async () => {
      try {
        await axios.put('/user/avatar', { avatar: reader.result });
        updateAvatar(reader.result);
        setInfo((current) => ({ ...(current || {}), avatar: reader.result }));
      } catch (error) {
        setAvatarError(error.response?.data?.detail || 'Could not save that image.');
      } finally {
        setAvatarSaving(false);
      }
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
                {(info?.avatar || user?.avatar) ? (
                  <img src={info?.avatar || user.avatar} alt="Your profile" className="avatar-img" />
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
          <div className="history-actions">
          {conversations.length > 0 && (
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search history…"
              className="history-search"
            />
          )}
          </div>
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
              <div
                key={h.id}
                className="history-item"
                role="button"
                tabIndex={0}
                onClick={() => navigate('/chat', { state: { sessionId: h.id } })}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    navigate('/chat', { state: { sessionId: h.id } });
                  }
                }}
              >
                <div className="history-q-row">
                  <span className="history-q-mark">“</span>
                  {editingSessionId === h.id ? (
                    <input
                      ref={titleInputRef}
                      className="history-title-input"
                      type="text"
                      value={editingTitle}
                      onChange={(event) => setEditingTitle(event.target.value)}
                      onBlur={() => saveRenaming(h)}
                      onClick={(event) => event.stopPropagation()}
                      onKeyDown={(event) => {
                        event.stopPropagation();
                        if (event.key === 'Enter') {
                          event.preventDefault();
                          event.currentTarget.blur();
                        }
                        if (event.key === 'Escape') {
                          event.preventDefault();
                          skipRenameBlurRef.current = true;
                          cancelRenaming(h);
                        }
                      }}
                      aria-label="Session title"
                    />
                  ) : (
                    <p className="history-question">{h.title || 'Conversation'}</p>
                  )}
                </div>
                <p className="history-meta">
                  {Math.floor((h.message_count || 0) / 2)} exchanges
                  {' · '}
                  {new Date(h.updated_at || h.date_message).toLocaleString()}
                </p>
                <div className="history-item-actions">
                  <button
                    type="button"
                    className="history-action-btn"
                    onClick={(event) => { event.stopPropagation(); startRenaming(h); }}
                    aria-label={`Rename ${h.title || 'conversation'}`}
                    title="Rename session"
                  >
                    <EditIcon />
                    <span>Rename</span>
                  </button>
                  <button
                    type="button"
                    className="history-action-btn is-danger"
                    onClick={(event) => { event.stopPropagation(); requestSessionDeletion(h); }}
                    aria-label={`Delete ${h.title || 'conversation'}`}
                    title="Delete session"
                  >
                    <TrashIcon />
                    <span>Delete</span>
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      {sessionPendingDeletion && (
        <div
          className="delete-modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) cancelSessionDeletion();
          }}
        >
          <div className="delete-modal" role="dialog" aria-modal="true" aria-labelledby="delete-session-title">
            <div className="delete-modal-icon"><TrashIcon /></div>
            <h2 id="delete-session-title">Delete session?</h2>
            <p>
              This will permanently delete <strong>{sessionPendingDeletion.title || 'this session'}</strong> and its messages.
            </p>
            <div className="delete-modal-actions">
              <button type="button" className="modal-cancel-btn" onClick={cancelSessionDeletion} disabled={deletingSession}>
                Cancel
              </button>
              <button type="button" className="modal-delete-btn" onClick={confirmSessionDeletion} disabled={deletingSession}>
                {deletingSession ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
