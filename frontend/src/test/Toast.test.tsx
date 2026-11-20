import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ToastProvider, useToastContext } from '../context/ToastContext';
import { ToastContainer } from '../components/common/ToastContainer';

function ToastTestTrigger() {
  const { toast } = useToastContext();
  return (
    <div>
      <button type="button" onClick={() => toast.error('Failure occurred')}>
        Show Error Toast
      </button>
      <button type="button" onClick={() => toast.success('Action completed successfully')}>
        Show Success Toast
      </button>
      <button type="button" onClick={() => toast.info('Informational notice')}>
        Show Info Toast
      </button>
      <ToastContainer />
    </div>
  );
}

describe('Toast and ToastContainer accessibility', () => {
  it('renders error toast with role="alert" and assertive live region', async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <ToastTestTrigger />
      </ToastProvider>
    );

    const errorBtn = screen.getByRole('button', { name: 'Show Error Toast' });
    await user.click(errorBtn);

    const alertElement = await screen.findByRole('alert');
    expect(alertElement).toBeInTheDocument();
    expect(alertElement).toHaveTextContent('Failure occurred');
    expect(alertElement).toHaveAttribute('aria-live', 'assertive');
  });

  it('renders success toast with role="status" and polite live region', async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <ToastTestTrigger />
      </ToastProvider>
    );

    const successBtn = screen.getByRole('button', { name: 'Show Success Toast' });
    await user.click(successBtn);

    const statusElement = await screen.findByRole('status');
    expect(statusElement).toBeInTheDocument();
    expect(statusElement).toHaveTextContent('Action completed successfully');
    expect(statusElement).toHaveAttribute('aria-live', 'polite');
  });

  it('removes toast when dismiss button is clicked', async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <ToastTestTrigger />
      </ToastProvider>
    );

    const errorBtn = screen.getByRole('button', { name: 'Show Error Toast' });
    await user.click(errorBtn);

    expect(await screen.findByRole('alert')).toBeInTheDocument();

    const dismissBtn = screen.getByRole('button', { name: 'Dismiss notification' });
    await user.click(dismissBtn);

    await waitFor(() => {
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
  });
});
