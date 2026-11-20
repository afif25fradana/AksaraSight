import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FormulaRenderer } from '../components/renderers/FormulaRenderer';

describe('FormulaRenderer Component', () => {
  const originalClipboard = navigator.clipboard;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    Object.defineProperty(navigator, 'clipboard', {
      value: originalClipboard,
      writable: true,
      configurable: true,
    });
  });

  it('renders mathematical formula offline using KaTeX', () => {
    const latexExpr = 'E = mc^2';
    const { container } = render(<FormulaRenderer latex={latexExpr} />);

    // KaTeX outputs mathml or katex-html classes
    const katexElement = container.querySelector('.katex');
    expect(katexElement).toBeInTheDocument();
    expect(screen.getByText('Mathematical Formula')).toBeInTheDocument();
  });

  it('enforces trust: false to prevent dangerous macro execution or malicious javascript', () => {
    const maliciousLatex = '\\href{javascript:alert(1)}{ClickMe}';
    const { container } = render(<FormulaRenderer latex={maliciousLatex} />);

    // With trust: false, KaTeX does not produce a clickable javascript link
    const anchor = container.querySelector('a[href^="javascript:"]');
    expect(anchor).toBeNull();
  });

  it('toggles between rendered formula and raw LaTeX code view', async () => {
    const user = userEvent.setup();
    const latexExpr = '\\frac{a}{b} = c';
    const { container } = render(<FormulaRenderer latex={latexExpr} />);

    // Initially, rendered KaTeX is displayed and raw <pre> is not rendered
    expect(container.querySelector('.katex')).toBeInTheDocument();
    expect(container.querySelector('pre')).not.toBeInTheDocument();

    // Click toggle button to view LaTeX source
    const toggleButton = screen.getByRole('button', { name: /LaTeX Source/i });
    await user.click(toggleButton);

    // Now raw LaTeX code inside <pre> is visible
    expect(container.querySelector('pre')).toBeInTheDocument();
    expect(container.querySelector('pre')).toHaveTextContent(latexExpr);
    expect(screen.getByRole('button', { name: /View Rendered/i })).toBeInTheDocument();

    // Click again to return to rendered view
    await user.click(screen.getByRole('button', { name: /View Rendered/i }));
    expect(container.querySelector('.katex')).toBeInTheDocument();
    expect(container.querySelector('pre')).not.toBeInTheDocument();
  });

  it('copies clean LaTeX source to clipboard', async () => {
    const user = userEvent.setup();
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: writeTextMock },
      writable: true,
      configurable: true,
    });

    const latexExpr = '$$\\int_0^1 x^2 dx = \\frac{1}{3}$$';
    render(<FormulaRenderer latex={latexExpr} />);

    const copyBtn = screen.getByRole('button', { name: /Copy/i });
    await user.click(copyBtn);

    expect(writeTextMock).toHaveBeenCalledWith('\\int_0^1 x^2 dx = \\frac{1}{3}');
    expect(await screen.findByText('Copied')).toBeInTheDocument();
  });
});
