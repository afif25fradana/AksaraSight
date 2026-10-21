import React, { useState } from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useFocusTrap } from '../hooks/useFocusTrap';

const TestModal: React.FC<{ isOpen: boolean }> = ({ isOpen }) => {
  const trapRef = useFocusTrap<HTMLDivElement>(isOpen);
  if (!isOpen) return null;
  return (
    <div ref={trapRef} role="dialog" aria-modal="true" data-testid="modal">
      <button data-testid="btn-1">Button 1</button>
      <input data-testid="input-1" placeholder="Type here" />
      <button data-testid="btn-2">Button 2</button>
    </div>
  );
};

const ModalWrapper: React.FC = () => {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button data-testid="trigger-btn" onClick={() => setOpen((prev) => !prev)}>
        Toggle Modal
      </button>
      <TestModal isOpen={open} />
    </div>
  );
};

describe('useFocusTrap Hook', () => {
  it('manages initial focus, tab cycling, and restores focus on close', async () => {
    const user = userEvent.setup();
    render(<ModalWrapper />);

    const trigger = screen.getByTestId('trigger-btn');
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    // Open modal
    await user.click(trigger);
    expect(screen.getByTestId('modal')).toBeInTheDocument();

    // Initial focus on first element
    await vi.waitFor(() => {
      expect(document.activeElement).toBe(screen.getByTestId('btn-1'));
    });

    const btn1 = screen.getByTestId('btn-1');
    const input1 = screen.getByTestId('input-1');
    const btn2 = screen.getByTestId('btn-2');

    // Tab moves to next element
    await user.tab();
    expect(document.activeElement).toBe(input1);

    await user.tab();
    expect(document.activeElement).toBe(btn2);

    // Tab on last element wraps back to first element
    await user.tab();
    expect(document.activeElement).toBe(btn1);

    // Shift+Tab on first element wraps back to last element
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(btn2);

    // Close modal
    await user.keyboard('{Escape}'); // If handled, or toggle trigger
    act(() => {
      trigger.click();
    });

    // Check return focus restored to trigger
    await vi.waitFor(() => {
      expect(document.activeElement).toBe(trigger);
    });
  });
});
