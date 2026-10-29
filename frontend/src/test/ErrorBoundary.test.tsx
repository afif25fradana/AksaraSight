import React, { useState } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ErrorBoundary } from '../components/ErrorBoundary';

const Bomb: React.FC<{ shouldThrow: boolean }> = ({ shouldThrow }) => {
  if (shouldThrow) {
    throw new Error('Test crash in component tree');
  }
  return <div>Component rendered safely</div>;
};

describe('ErrorBoundary', () => {
  const originalConsoleError = console.error;

  beforeEach(() => {
    // Suppress React unhandled exception log during error boundary tests
    console.error = vi.fn();
  });

  afterEach(() => {
    console.error = originalConsoleError;
  });

  it('renders children normally when no render errors occur', () => {
    render(
      <ErrorBoundary>
        <Bomb shouldThrow={false} />
      </ErrorBoundary>
    );
    expect(screen.getByText('Component rendered safely')).toBeInTheDocument();
  });

  it('renders default error UI on uncaught child error and displays error message', () => {
    render(
      <ErrorBoundary>
        <Bomb shouldThrow={true} />
      </ErrorBoundary>
    );

    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    expect(screen.getByText('Test crash in component tree')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry component/i })).toBeInTheDocument();
  });

  it('renders custom fallback when fallback prop is provided', () => {
    render(
      <ErrorBoundary fallback={<div data-testid="custom-fallback">Custom Fallback View</div>}>
        <Bomb shouldThrow={true} />
      </ErrorBoundary>
    );

    expect(screen.getByTestId('custom-fallback')).toBeInTheDocument();
    expect(screen.getByText('Custom Fallback View')).toBeInTheDocument();
    expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument();
  });

  it('recovers from error state when Retry Component is clicked', async () => {
    const ResettableParent: React.FC = () => {
      const [throwError, setThrowError] = useState(true);
      return (
        <div>
          <button onClick={() => setThrowError(false)}>Fix Error</button>
          <ErrorBoundary>
            <Bomb shouldThrow={throwError} />
          </ErrorBoundary>
        </div>
      );
    };

    render(<ResettableParent />);

    // Initially crashed
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();

    // Fix the underlying condition
    await userEvent.click(screen.getByText('Fix Error'));

    // Click Retry Component
    await userEvent.click(screen.getByRole('button', { name: /retry component/i }));

    // Recovers
    expect(screen.getByText('Component rendered safely')).toBeInTheDocument();
    expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument();
  });
});
