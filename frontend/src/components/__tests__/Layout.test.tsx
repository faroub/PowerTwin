import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { Layout } from '../Layout';

import { HEALTHY_SYSTEM_INFO } from '../../test/fixtures';
import { installFetchMock, jsonResponse } from '../../test/fetchMock';

describe('Layout', () => {
  it('renders the active view inside the HMI frame', () => {
    installFetchMock({
      '/api/v1/info': () => jsonResponse(HEALTHY_SYSTEM_INFO),
    });

    render(
      <Layout currentView="overview" onSelectView={vi.fn()}>
        <p>The active view body</p>
      </Layout>,
    );

    expect(screen.getByText('The active view body')).toBeInTheDocument();
  });

  it('reports the API as connected once the health check answers', async () => {
    installFetchMock({
      '/api/v1/info': () => jsonResponse(HEALTHY_SYSTEM_INFO),
    });

    render(
      <Layout currentView="overview" onSelectView={vi.fn()}>
        <p>The active view body</p>
      </Layout>,
    );

    await waitFor(() => expect(screen.getByText(/API:/)).toHaveTextContent('CONNECTED'));
  });

  it('reports the API as disconnected when the health check fails', async () => {
    installFetchMock({
      '/api/v1/info': () => jsonResponse({ detail: 'not ready' }, 503),
    });

    render(
      <Layout currentView="overview" onSelectView={vi.fn()}>
        <p>The active view body</p>
      </Layout>,
    );

    await waitFor(() => expect(screen.getByText(/API:/)).toHaveTextContent('DISCONNECTED'));
  });

  it('states in the footer that the platform is a simulation and reaches no hardware', () => {
    installFetchMock({
      '/api/v1/info': () => jsonResponse(HEALTHY_SYSTEM_INFO),
    });

    const { container } = render(
      <Layout currentView="overview" onSelectView={vi.fn()}>
        <p>The active view body</p>
      </Layout>,
    );
    const footer = container.querySelector('.safety-footer') as HTMLElement;

    expect(footer).toHaveTextContent('SIMULATION ONLY');
    expect(footer).toHaveTextContent('No hardware equipment is detected');
  });

  it('names the signed-in operator in the footer', () => {
    installFetchMock({
      '/api/v1/info': () => jsonResponse(HEALTHY_SYSTEM_INFO),
    });

    render(
      <Layout
        currentView="overview"
        onSelectView={vi.fn()}
        user={{ username: 'engineer', role: 'ENGINEER', permissions: new Set() }}
      >
        <p>The active view body</p>
      </Layout>,
    );

    expect(screen.getByText(/Session: engineer \[ENGINEER\]/)).toBeInTheDocument();
  });

  it('reports that no session is active when there is none', () => {
    installFetchMock({
      '/api/v1/info': () => jsonResponse(HEALTHY_SYSTEM_INFO),
    });

    render(
      <Layout currentView="overview" onSelectView={vi.fn()}>
        <p>The active view body</p>
      </Layout>,
    );

    expect(screen.getByText(/No active session/)).toBeInTheDocument();
  });

  it('ends the session when the operator logs out', async () => {
    installFetchMock({
      '/api/v1/info': () => jsonResponse(HEALTHY_SYSTEM_INFO),
    });
    const onLogout = vi.fn();
    const user = userEvent.setup();
    render(
      <Layout
        currentView="overview"
        onSelectView={vi.fn()}
        user={{ username: 'engineer', role: 'ENGINEER', permissions: new Set() }}
        onLogout={onLogout}
      >
        <p>The active view body</p>
      </Layout>,
    );

    await user.click(screen.getByText('LOGOUT'));

    expect(onLogout).toHaveBeenCalledTimes(1);
  });

  it('offers no logout when the frame was built without one', () => {
    installFetchMock({
      '/api/v1/info': () => jsonResponse(HEALTHY_SYSTEM_INFO),
    });

    render(
      <Layout currentView="overview" onSelectView={vi.fn()}>
        <p>The active view body</p>
      </Layout>,
    );

    expect(screen.queryByText('LOGOUT')).not.toBeInTheDocument();
  });
});
