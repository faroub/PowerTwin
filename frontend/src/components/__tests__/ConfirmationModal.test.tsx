import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ConfirmationModal } from '../ConfirmationModal';

describe('Confirmation Modal', () => {
  it('renders nothing while it is closed', () => {
    render(
      <ConfirmationModal
        isOpen={false}
        title="Confirm Engine Control Action"
        actionDetails="Are you sure you want to execute: Pause Engine?"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.queryByText('Confirm Engine Control Action')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /CONFIRM & EXECUTE/ })).not.toBeInTheDocument();
  });

  it('names the action the operator is about to execute', () => {
    render(
      <ConfirmationModal
        isOpen
        title="Confirm Engine Control Action"
        actionDetails="Are you sure you want to execute: Pause Engine?"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText('Confirm Engine Control Action')).toBeInTheDocument();
    expect(
      screen.getByText('Are you sure you want to execute: Pause Engine?'),
    ).toBeInTheDocument();
  });

  it('states that the action reaches no real equipment', () => {
    render(
      <ConfirmationModal
        isOpen
        title="Confirm Engine Control Action"
        actionDetails="Are you sure you want to execute: Pause Engine?"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText(/SIMULATION ACTION CONFIRMATION/i)).toBeInTheDocument();
    expect(screen.getByText(/Zero real equipment is targeted/i)).toBeInTheDocument();
  });

  it('executes the action only when the operator confirms', async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(
      <ConfirmationModal
        isOpen
        title="Confirm Engine Control Action"
        actionDetails="Are you sure you want to execute: Pause Engine?"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    await user.click(screen.getByRole('button', { name: /CONFIRM & EXECUTE/ }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('abandons the action when the operator cancels', async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(
      <ConfirmationModal
        isOpen
        title="Confirm Engine Control Action"
        actionDetails="Are you sure you want to execute: Pause Engine?"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    await user.click(screen.getByRole('button', { name: /CANCEL/ }));

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
