/**
 * Platform login view.
 *
 * Operators authenticate against the backend (`/api/v1/auth/login`) before any HMI
 * control page renders. No credentials are validated or stored in the frontend: the
 * backend is the sole authority for authentication, permissions and session validation.
 */

import React, { useState } from 'react';

import { fetchUserDetails, login, logout, platformSession } from '../services/api';

interface LoginViewProps {
  /** Called once the platform session holds the authenticated user snapshot. */
  onLoginSuccess: () => void;
  /** Optional extra content rendered inside the login panel. */
  children?: React.ReactNode;
}

export const LoginView: React.FC<LoginViewProps> = (props) => {
  const { onLoginSuccess, children } = props;
  const [username, setUsername] = useState<string>('');
  const [password, setPassword] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  const isDisabled = !username || !password || loading;

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setLoading(true);

    const tokenResponse = await login({ username, password });
    if (!tokenResponse) {
      setError('Login failed: invalid credentials, or the backend is unavailable.');
      setLoading(false);
      return;
    }

    const user = await fetchUserDetails(tokenResponse.access_token);
    if (!user) {
      setError('Login failed: could not verify the session details.');
      setLoading(false);
      return;
    }

    platformSession.setAuthenticated(user, tokenResponse.access_token);
    onLoginSuccess();
  };

  const handleDisassociate = () => {
    if (platformSession.token) {
      logout();
    }
    onLoginSuccess();
  };

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        backgroundColor: '#0f172a',
        gap: '16px',
      }}
    >
      <h1 style={{ color: '#38bdf8', fontSize: '1.75rem' }}>PowerTwin BESS Platform</h1>
      <div style={{ color: '#94a3b8', marginBottom: '8px' }}>Log in to the HMI session</div>

      <form
        onSubmit={handleSubmit}
        style={{ display: 'flex', flexDirection: 'column', gap: '12px', width: '320px' }}
      >
        <input
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="Username (observer, engineer, admin)"
          autoComplete="username"
          style={{
            padding: '10px',
            borderRadius: '6px',
            backgroundColor: '#1e293b',
            border: '1px solid #334155',
            color: '#f8fafc',
          }}
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          autoComplete="current-password"
          style={{
            padding: '10px',
            borderRadius: '6px',
            backgroundColor: '#1e293b',
            border: '1px solid #334155',
            color: '#f8fafc',
          }}
        />
        {error && <div style={{ color: '#ef4444', fontSize: '0.85rem' }}>{error}</div>}

        <button
          type="submit"
          disabled={isDisabled}
          style={{
            padding: '10px',
            borderRadius: '6px',
            backgroundColor: isDisabled ? '#334155' : '#22c55e',
            color: isDisabled ? '#94a3b8' : '#0f172a',
            border: 'none',
            fontWeight: 'bold',
            cursor: isDisabled ? 'not-allowed' : 'pointer',
          }}
        >
          {loading ? 'Authenticating...' : 'Consent & Login'}
        </button>
      </form>

      <div style={{ color: '#94a3b8', fontSize: '0.8rem', maxWidth: '320px', textAlign: 'center' }}>
        <strong>LOGIN SHELTER:</strong> No hardware equipment is detected during login. All data
        sources available to this session are simulated.
      </div>

      {children}

      {platformSession.isAuthenticated && (
        <div
          style={{ color: '#ef4444', fontSize: '0.85rem', cursor: 'pointer' }}
          onClick={handleDisassociate}
        >
          Disassociate (Session: {platformSession.user?.username})
        </div>
      )}
    </div>
  );
};
