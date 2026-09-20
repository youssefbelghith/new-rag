import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function Navbar() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => {
    const onClick = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  const initials =
    ((user?.prenom?.[0] || '') + (user?.nom?.[0] || user?.email?.[0] || ''))
      .toUpperCase()
      .slice(0, 2) || 'U';

  const handleLogout = () => {
    window.dispatchEvent(new Event('chat:finish'));
    logout();
    navigate('/login');
  };

  const goTo = (path) => {
    window.dispatchEvent(new Event('chat:finish'));
    navigate(path);
  };

  const handleBrandClick = () => {
    if (location.pathname !== '/chat') {
      navigate('/chat');
      return;
    }

    window.dispatchEvent(new CustomEvent('chat:finish', {
      detail: {
        startNew: true,
        onComplete: () => navigate('/chat'),
      },
    }));
  };

  return (
    <header className="navbar">
      <div className="navbar-inner">
        <button
          className="navbar-brand"
          onClick={handleBrandClick}
        >
          <span className="navbar-mark">A</span>
          <span className="navbar-word">Alex</span>
        </button>

        <div className="navbar-profile" ref={menuRef}>
          <button
            className="avatar-btn"
            onClick={() => setMenuOpen((v) => !v)}
            aria-haspopup="true"
            aria-expanded={menuOpen}
            aria-label="Open account menu"
          >
            <span className="avatar-ring">
              <span className="avatar-ring-inner">
                {user?.avatar ? (
                  <img src={user.avatar} alt="Your profile" className="avatar-img" />
                ) : (
                  <span className="avatar-initials">{initials}</span>
                )}
              </span>
            </span>
          </button>

          {menuOpen && (
            <div className="profile-menu" role="menu">
              <div className="profile-menu-header">
                <p className="profile-menu-name">{user?.prenom || 'Your account'}</p>
                <p className="profile-menu-email">{user?.email}</p>
              </div>
              <button
                className="profile-menu-item"
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false);
                  goTo('/profile');
                }}
              >
                View profile
              </button>
              <button className="profile-menu-item is-danger" role="menuitem" onClick={handleLogout}>
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
