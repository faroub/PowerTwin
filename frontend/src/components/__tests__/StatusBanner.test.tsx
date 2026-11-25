import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { StatusBanner } from '../StatusBanner';

import { HEALTHY_SYSTEM_INFO } from '../../test/fixtures';

describe('Status Banner', () => {
  it('names the platform', () => {
    render(<StatusBanner isOnline systemInfo={null} />);

    expect(screen.getByText(/PowerTwin BESS Platform/i)).toBeInTheDocument();
  });

  it('falls back to the simulation-only mode when the backend reported nothing yet', () => {
    render(<StatusBanner isOnline={false} systemInfo={null} />);

    expect(screen.getByText(/MODE:/)).toHaveTextContent('SIMULATION ONLY');
  });

  it('shows the application mode the backend reports', () => {
    render(<StatusBanner isOnline systemInfo={HEALTHY_SYSTEM_INFO} />);

    expect(screen.getByText(/MODE:/)).toHaveTextContent('SIMULATION ONLY');
  });

  it('reports the API as disconnected when the backend cannot be reached', () => {
    render(<StatusBanner isOnline={false} systemInfo={null} />);

    expect(screen.getByText(/API:/)).toHaveTextContent('DISCONNECTED');
  });

  it('reports the API as connected when the backend answered', () => {
    render(<StatusBanner isOnline systemInfo={HEALTHY_SYSTEM_INFO} />);

    expect(screen.getByText(/API:/)).toHaveTextContent('CONNECTED');
  });

  it('states that the safety guardrails are active regardless of the connection state', () => {
    const { rerender } = render(<StatusBanner isOnline={false} systemInfo={null} />);
    expect(screen.getByText(/SAFETY:/)).toHaveTextContent('GUARDRAILS ACTIVE');

    rerender(<StatusBanner isOnline systemInfo={HEALTHY_SYSTEM_INFO} />);
    expect(screen.getByText(/SAFETY:/)).toHaveTextContent('GUARDRAILS ACTIVE');
  });

  it('names the signed-in operator and their role', () => {
    render(<StatusBanner isOnline systemInfo={HEALTHY_SYSTEM_INFO} username="engineer" role="ENGINEER" />);

    expect(screen.getByText(/User: engineer/)).toBeInTheDocument();
    expect(screen.getByText('ENGINEER')).toBeInTheDocument();
  });

  it('shows no operator when there is no session', () => {
    render(<StatusBanner isOnline systemInfo={HEALTHY_SYSTEM_INFO} />);

    expect(screen.queryByText(/User:/)).not.toBeInTheDocument();
  });
});
