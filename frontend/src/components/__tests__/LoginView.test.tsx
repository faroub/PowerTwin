import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { LoginView } from '../LoginView';
import { platformSession } from '../../services/api';

import { TOKEN_RESPONSE, USER_DETAILS } from '../../test/fixtures';
import { installFetchMock, jsonResponse } from '../../test/fetchMock';

function renderLoginView(onLoginSuccess = vi.fn()) {
  const user = userEvent.setup();
  render(<LoginView onLoginSuccess={onLoginSuccess} />);
  return { user, onLoginSuccess };
}

const USERNAME_FIELD = 'Username (observer, engineer, admin)';

describe('Login View', () => {
  it('keeps the consent button disabled until both credentials are entered', async () => {
    const { user } = renderLoginView();
    const submit = screen.getByRole('button', { name: 'Consent & Login' });

    expect(submit).toBeDisabled();

    await user.type(screen.getByPlaceholderText(USERNAME_FIELD), 'engineer');
    expect(submit).toBeDisabled();

    await user.type(screen.getByPlaceholderText('Password'), 'secret');
    expect(submit).toBeEnabled();
  });

  it('states that no hardware equipment is detected during the login', () => {
    renderLoginView();

    expect(screen.getByText(/LOGIN SHELTER/i)).toBeInTheDocument();
    expect(screen.getByText(/No hardware equipment is detected during login/i)).toBeInTheDocument();
  });

  it('records the session and reports the success once the backend accepts the credentials', async () => {
    installFetchMock({
      '/api/v1/auth/login': () => jsonResponse(TOKEN_RESPONSE),
      '/api/v1/auth/me': () => jsonResponse(USER_DETAILS),
    });
    const { user, onLoginSuccess } = renderLoginView();

    await user.type(screen.getByPlaceholderText(USERNAME_FIELD), 'engineer');
    await user.type(screen.getByPlaceholderText('Password'), 'secret');
    await user.click(screen.getByRole('button', { name: 'Consent & Login' }));

    await waitFor(() => expect(onLoginSuccess).toHaveBeenCalledTimes(1));
    expect(platformSession.isAuthenticated).toBe(true);
    expect(platformSession.token).toBe('test-access-token');
    expect(platformSession.user?.username).toBe('engineer');
  });

  it('reports rejected credentials without opening a session', async () => {
    installFetchMock({
      '/api/v1/auth/login': () => jsonResponse({ detail: 'invalid credentials' }, 401),
    });
    const { user, onLoginSuccess } = renderLoginView();

    await user.type(screen.getByPlaceholderText(USERNAME_FIELD), 'engineer');
    await user.type(screen.getByPlaceholderText('Password'), 'wrong');
    await user.click(screen.getByRole('button', { name: 'Consent & Login' }));

    await waitFor(() =>
      expect(screen.getByText(/invalid credentials, or the backend is unavailable/i)).toBeInTheDocument(),
    );
    expect(onLoginSuccess).not.toHaveBeenCalled();
    expect(platformSession.isAuthenticated).toBe(false);
  });

  it('reports a failure when the session cannot be verified', async () => {
    installFetchMock({
      '/api/v1/auth/login': () => jsonResponse(TOKEN_RESPONSE),
      '/api/v1/auth/me': () => jsonResponse({ detail: 'invalid token' }, 401),
    });
    const { user, onLoginSuccess } = renderLoginView();

    await user.type(screen.getByPlaceholderText(USERNAME_FIELD), 'engineer');
    await user.type(screen.getByPlaceholderText('Password'), 'secret');
    await user.click(screen.getByRole('button', { name: 'Consent & Login' }));

    await waitFor(() =>
      expect(screen.getByText(/could not verify the session details/i)).toBeInTheDocument(),
    );
    expect(onLoginSuccess).not.toHaveBeenCalled();
    expect(platformSession.isAuthenticated).toBe(false);
  });

  it('offers no disassociation while there is no session', () => {
    renderLoginView();

    expect(screen.queryByText(/Disassociate/i)).not.toBeInTheDocument();
  });

  it('ends the session when the operator disassociates', async () => {
    platformSession.setAuthenticated(
      { username: 'engineer', role: 'ENGINEER', permissions: new Set() },
      'a-token',
    );
    const { user, onLoginSuccess } = renderLoginView();

    await user.click(screen.getByText(/Disassociate \(Session: engineer\)/));

    expect(platformSession.isAuthenticated).toBe(false);
    expect(onLoginSuccess).toHaveBeenCalledTimes(1);
  });

  it('keeps the password out of any client-side storage', async () => {
    installFetchMock({
      '/api/v1/auth/login': () => jsonResponse(TOKEN_RESPONSE),
      '/api/v1/auth/me': () => jsonResponse(USER_DETAILS),
    });
    const { user } = renderLoginView();

    await user.type(screen.getByPlaceholderText(USERNAME_FIELD), 'engineer');
    await user.type(screen.getByPlaceholderText('Password'), 'secret');
    await user.click(screen.getByRole('button', { name: 'Consent & Login' }));

    await waitFor(() => expect(platformSession.isAuthenticated).toBe(true));

    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(document.cookie).toBe('');
  });
});
