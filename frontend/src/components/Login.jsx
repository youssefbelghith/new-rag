import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';

export default function Login() {
  const [isLogin, setIsLogin] = useState(true);
  const [formData, setFormData] = useState({ nom: '', prenom: '', email: '', password: '', confirmPassword: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleChange = (e) => setFormData({ ...formData, [e.target.name]: e.target.value });

  const validateForm = () => {
    const email = formData.email.trim();
    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

    if (!emailPattern.test(email)) {
      return 'Please enter a valid email address, such as name@example.com.';
    }

    if (!formData.password.trim()) {
      return 'Password cannot be empty.';
    }

    if (!isLogin) {
      if (formData.password.length < 8) {
        return 'Password must be at least 8 characters long.';
      }
      if (!/[A-Za-z]/.test(formData.password) || !/[0-9]/.test(formData.password)) {
        return 'Password must contain at least one letter and one number.';
      }
      if (formData.password !== formData.confirmPassword) {
        return 'Passwords do not match.';
      }
    }

    return '';
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    const validationError = validateForm();
    if (validationError) {
      setError(validationError);
      return;
    }

    setLoading(true);
    try {
      const url = isLogin ? '/login' : '/signup';
      const payload = isLogin
        ? { email: formData.email.trim(), password: formData.password }
        : { nom: formData.nom, prenom: formData.prenom, email: formData.email.trim(), password: formData.password };

      const response = await axios.post(url, payload);
      const { access_token, user_id, prenom, email } = response.data;
      login(access_token, { id: user_id, prenom, email });
      navigate('/chat');
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : detail?.[0]?.msg || 'Something went wrong');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="navbar-mark">A</span>
          <span className="navbar-word">Alex</span>
        </div>
        <h1 className="auth-title">{isLogin ? 'Welcome back' : 'Create your account'}</h1>

        <form onSubmit={handleSubmit} noValidate>
          {!isLogin && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
              <div>
                <label htmlFor="nom" className="field-label">Last name</label>
                <input
                  id="nom"
                  name="nom"
                  type="text"
                  required
                  value={formData.nom}
                  onChange={handleChange}
                  className="field-input"
                />
              </div>
              <div>
                <label htmlFor="prenom" className="field-label">First name</label>
                <input
                  id="prenom"
                  name="prenom"
                  type="text"
                  required
                  value={formData.prenom}
                  onChange={handleChange}
                  className="field-input"
                />
              </div>
            </div>
          )}

          <div style={{ marginBottom: 14 }}>
            <label htmlFor="email" className="field-label">Email address</label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              pattern="[^\s@]+@[^\s@]+\.[^\s@]{2,}"
              value={formData.email}
              onChange={handleChange}
              className="field-input"
            />
          </div>

          <div style={{ marginBottom: 14 }}>
            <label htmlFor="password" className="field-label">Password</label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              minLength={isLogin ? undefined : 8}
              value={formData.password}
              onChange={handleChange}
              className="field-input"
            />
          </div>

          {!isLogin && (
            <div style={{ marginBottom: 14 }}>
              <label htmlFor="confirmPassword" className="field-label">Confirm password</label>
              <input
                id="confirmPassword"
                name="confirmPassword"
                type="password"
                required
                value={formData.confirmPassword}
                onChange={handleChange}
                className="field-input"
              />
            </div>
          )}

          {error && <p className="auth-error">{error}</p>}

          <button type="submit" disabled={loading} className="auth-submit">
            {loading ? 'Processing…' : isLogin ? 'Sign in' : 'Sign up'}
          </button>

          <button type="button" onClick={() => setIsLogin(!isLogin)} className="auth-switch">
            {isLogin ? "Need an account? Sign up" : 'Already have an account? Sign in'}
          </button>
        </form>
      </div>
    </div>
  );
}
