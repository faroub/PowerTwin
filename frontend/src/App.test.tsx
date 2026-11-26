import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';

import { App } from './App';
import { platformSession } from './services/api';

import {
  CONNECTED_TELEMETRY,
  HEALTHY_SYSTEM_INFO,
  REFERENCE_PLANT_TOPOLOGY,
  TOKEN_RESPONSE,
  USER_DETAILS,
} from './test/fixtures';
import { installFetchMock, jsonResponse } from './test/fetchMock';

const USERNAME_FIELD = 'Username (observer, engineer, admin)';

function installPlatformMock() {
  return installFetchMock({
    '/api/v1/auth/login': () => jsonResponse(TOKEN_RESPONSE),
    '/api/v1/auth/me': () => jsonResponse(USER_DETAILS),
    '/api/v1/info': () => jsonResponse(HEALTHY_SYSTEM_INFO),
    '/api/v1/overview': () => jsonResponse(CONNECTED_TELEMETRY),
    '/api/v1/topology': () => jsonResponse(REFERENCE_PLANT_TOPOLOGY),
    '/api/v1/simulation/control': () => jsonResponse({ status: 'SUCCESS' }),
  });
}

async function logIn(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByPlaceholderText(USERNAME_FIELD), 'engineer');
  await user.type(screen.getByPlaceholderText('Password'), 'secret');
  await user.click(screen.getByRole('button', { name: 'Consent & Login' }));
  await screen.findByRole('heading', { level: 1, name: 'Plant Overview' });
}

describe('HMI Application', () => {
  beforeEach(() => {
    installPlatformMock();
  });

  it('asks the operator to log in before any control page renders', () => {
    render(<App />);

    expect(screen.getByRole('heading', { level: 1, name: 'PowerTwin BESS Platform' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 1, name: 'Plant Overview' })).not.toBeInTheDocument();
  });

  it('opens the HMI on the plant overview once the operator logs in', async () => {
    const user = userEvent.setup();
    render(<App />);

    await logIn(user);

    expect(screen.getByRole('heading', { level: 1, name: 'Plant Overview' })).toBeInTheDocument();
    expect(screen.getByText(/SIMULATION ONLY \| No hardware equipment is detected/i)).toBeInTheDocument();
    expect(platformSession.isAuthenticated).toBe(true);
  });

  it('shows the operator in the frame of the HMI', async () => {
    const user = userEvent.setup();
    render(<App />);

    await logIn(user);

    expect(screen.getByText(/User: engineer/)).toBeInTheDocument();
    expect(screen.getByText(/Session: engineer \[ENGINEER\]/)).toBeInTheDocument();
  });

  it('switches to the view the operator selects in the sidebar', async () => {
    const user = userEvent.setup();
    const { container } = render(<App />);
    await logIn(user);

    const sidebar = container.querySelector('.sidebar') as HTMLElement;
    await user.click(sidebar.querySelector('.nav-item:nth-child(13)') as HTMLElement);

    expect(screen.getByRole('heading', { level: 1, name: 'Alarms & Events' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 1, name: 'Plant Overview' })).not.toBeInTheDocument();
  });

  it('reaches every view of the HMI through the sidebar', async () => {
    const user = userEvent.setup();
    const { container } = render(<App />);
    await logIn(user);

    const sidebar = container.querySelector('.sidebar') as HTMLElement;
    const items = Array.from(sidebar.querySelectorAll('.nav-item'));
    expect(items).toHaveLength(20);

    for (const item of items) {
      await user.click(item);
      expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
    }
  });

  it('returns to the login view and drops the session when the operator logs out', async () => {
    const user = userEvent.setup();
    render(<App />);
    await logIn(user);

    await user.click(screen.getByText('LOGOUT'));

    expect(
      screen.getByRole('heading', { level: 1, name: 'PowerTwin BESS Platform' }),
    ).toBeInTheDocument();
    expect(platformSession.isAuthenticated).toBe(false);
    expect(platformSession.token).toBeNull();
  });

  it('opens on the plant overview again after a logout and a new login', async () => {
    const user = userEvent.setup();
    const { container } = render(<App />);
    await logIn(user);

    const sidebar = container.querySelector('.sidebar') as HTMLElement;
    await user.click(sidebar.querySelector('.nav-item:nth-child(16)') as HTMLElement);
    expect(screen.getByRole('heading', { level: 1, name: 'Simulation Control' })).toBeInTheDocument();

    await user.click(screen.getByText('LOGOUT'));
    await logIn(user);

    expect(screen.getByRole('heading', { level: 1, name: 'Plant Overview' })).toBeInTheDocument();
  });

  it('keeps the session token out of every client-side storage', async () => {
    const user = userEvent.setup();
    render(<App />);

    await logIn(user);

    await waitFor(() => expect(platformSession.isAuthenticated).toBe(true));
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(document.cookie).toBe('');
  });
});
