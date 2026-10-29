import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DocumentPreviewPanel } from '../components/DocumentPreviewPanel';
import { DocumentItem } from '../types';

const mockDoc: DocumentItem = {
  id: 'doc-preview-123',
  name: 'test-document.pdf',
  pages: 5,
  status: 'Waiting',
  currentPage: 1,
  processedPages: 0,
  previewImageUrl: '/api/documents/doc-preview-123/preview?page=1',
  extractedText: '# Sample Extracted Markdown',
  docType: 'legal-agreement',
};

describe('DocumentPreviewPanel', () => {
  it('renders empty placeholder view when document is null', () => {
    render(<DocumentPreviewPanel document={null} onPageChange={vi.fn()} />);
    expect(screen.getByText('No document selected')).toBeInTheDocument();
    expect(screen.getByText('0 of 0')).toBeInTheDocument();
  });

  it('renders document title, page counter, and handles page navigation', async () => {
    const onPageChange = vi.fn();
    const { rerender } = render(
      <DocumentPreviewPanel document={mockDoc} onPageChange={onPageChange} />
    );

    expect(screen.getByText('test-document.pdf')).toBeInTheDocument();
    expect(screen.getByText('1 of 5')).toBeInTheDocument();

    const prevBtn = screen.getByRole('button', { name: 'Previous' });
    const nextBtn = screen.getByRole('button', { name: 'Next' });

    // Previous is disabled on page 1
    expect(prevBtn).toBeDisabled();
    expect(nextBtn).not.toBeDisabled();

    await userEvent.click(nextBtn);
    expect(onPageChange).toHaveBeenCalledWith(2);

    // Re-render on last page (5 of 5)
    rerender(
      <DocumentPreviewPanel
        document={{ ...mockDoc, currentPage: 5 }}
        onPageChange={onPageChange}
      />
    );

    expect(screen.getByText('5 of 5')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Previous' })).not.toBeDisabled();

    await userEvent.click(screen.getByRole('button', { name: 'Previous' }));
    expect(onPageChange).toHaveBeenCalledWith(4);
  });

  it('manages zoom in, zoom out with bounds (50% - 200%), and Fit reset (100%)', async () => {
    render(<DocumentPreviewPanel document={mockDoc} onPageChange={vi.fn()} />);

    expect(screen.getByText('100%')).toBeInTheDocument();

    const zoomInBtn = screen.getByRole('button', { name: 'Zoom in' });
    const zoomOutBtn = screen.getByRole('button', { name: 'Zoom out' });
    const fitBtn = screen.getByRole('button', { name: 'Fit' });

    // Zoom in steps
    await userEvent.click(zoomInBtn);
    expect(screen.getByText('125%')).toBeInTheDocument();

    await userEvent.click(zoomInBtn);
    expect(screen.getByText('150%')).toBeInTheDocument();

    await userEvent.click(zoomInBtn);
    await userEvent.click(zoomInBtn);
    // Upper clamp bound 200%
    await userEvent.click(zoomInBtn);
    expect(screen.getByText('200%')).toBeInTheDocument();

    // Fit resets to 100%
    await userEvent.click(fitBtn);
    expect(screen.getByText('100%')).toBeInTheDocument();

    // Zoom out steps
    await userEvent.click(zoomOutBtn);
    expect(screen.getByText('75%')).toBeInTheDocument();
    await userEvent.click(zoomOutBtn);
    expect(screen.getByText('50%')).toBeInTheDocument();

    // Lower clamp bound 50%
    await userEvent.click(zoomOutBtn);
    expect(screen.getByText('50%')).toBeInTheDocument();
  });

  it('renders image preview and switches to raster error fallback on load failure', () => {
    render(<DocumentPreviewPanel document={mockDoc} onPageChange={vi.fn()} />);

    const img = screen.getByRole('img', { name: 'test-document.pdf page 1' });
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute('src', '/api/documents/doc-preview-123/preview?page=1');

    // Simulate image error event
    fireEvent.error(img);

    // Fallback error message appears
    expect(
      screen.getByText(/Raster preview could not be loaded from backend/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/Sample Extracted Markdown/i)).toBeInTheDocument();
  });
});
