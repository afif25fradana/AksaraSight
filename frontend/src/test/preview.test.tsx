import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ExtractedTextPanel } from '../components/workspace/ExtractedTextPanel';
import { DocumentItem } from '../types';

const defaultProps = {
  document: null,
  runningJobDocId: null,
  isEngineOnline: true,
  onStartEngine: vi.fn(),
  onOpenSettings: vi.fn(),
  onExport: vi.fn(),
  onRunDocumentExtraction: vi.fn(),
  onAddToQueue: vi.fn(),
  onRemoveFromQueue: vi.fn(),
  onCancelExtraction: vi.fn(),
  onReExtractDocument: vi.fn(),
};

const createMockDoc = (extractedText: string, extra?: Partial<DocumentItem>): DocumentItem => ({
  id: 'test-doc-1',
  name: 'test.pdf',
  pages: 1,
  status: 'Done',
  currentPage: 1,
  processedPages: 1,
  extractedText,
  docType: 'legal-agreement',
  ...extra,
});

describe('ExtractedTextPanel table preview DOMParser logic', () => {
  it('parses malformed HTML tables without crashing and renders table content', () => {
    const malformedHtml = `
      <table>
        <tr>
          <th>Header 1
          <th>Header 2</tr>
        <tr>
          <td>Cell 1
          <td>Cell 2
      </table>
    `;

    const doc = createMockDoc(malformedHtml);
    render(<ExtractedTextPanel {...defaultProps} document={doc} />);

    expect(screen.getByText('Header 1')).toBeInTheDocument();
    expect(screen.getByText('Header 2')).toBeInTheDocument();
    expect(screen.getByText('Cell 1')).toBeInTheDocument();
    expect(screen.getByText('Cell 2')).toBeInTheDocument();
  });

  it('safely strips script tags and renders only textContent in cells', () => {
    const xssHtml = `
      <table>
        <thead>
          <tr>
            <th>Security Test</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><script>alert("xss")</script><img src="x" onerror="alert(1)" /><iframe src="javascript:alert(1)" onload="alert(2)"></iframe>Safe Content</td>
          </tr>
        </tbody>
      </table>
    `;

    const doc = createMockDoc(xssHtml);
    const { container } = render(<ExtractedTextPanel {...defaultProps} document={doc} />);

    // Ensure no <script>, <img>, or <iframe> elements exist in the rendered DOM
    expect(container.querySelectorAll('script')).toHaveLength(0);
    expect(container.querySelectorAll('img')).toHaveLength(0);
    expect(container.querySelectorAll('iframe')).toHaveLength(0);

    // Ensure no element in container has an attribute starting with 'on'
    const allElements = Array.from(container.querySelectorAll('*'));
    for (const el of allElements) {
      for (const attr of Array.from(el.attributes)) {
        expect(attr.name.toLowerCase().startsWith('on')).toBe(false);
      }
    }

    // Ensure the text content is extracted cleanly without executing script
    expect(screen.getByText('alert("xss")Safe Content')).toBeInTheDocument();
  });

  it('applies text alignment classes and inline styles correctly', () => {
    const alignedHtml = `
      <table>
        <thead>
          <tr>
            <th align="center">Centered Header</th>
            <th align="right">Right Header</th>
            <th style="text-align: justify">Justified Header</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td align="center">Center Body</td>
            <td align="right">Right Body</td>
            <td align="left">Left Body</td>
          </tr>
        </tbody>
      </table>
    `;

    const doc = createMockDoc(alignedHtml);
    render(<ExtractedTextPanel {...defaultProps} document={doc} />);

    const centerHeader = screen.getByText('Centered Header');
    expect(centerHeader).toHaveClass('text-center');
    expect(centerHeader).toHaveStyle({ textAlign: 'center' });

    const rightHeader = screen.getByText('Right Header');
    expect(rightHeader).toHaveClass('text-right');
    expect(rightHeader).toHaveStyle({ textAlign: 'right' });

    const justifiedHeader = screen.getByText('Justified Header');
    expect(justifiedHeader).toHaveClass('text-justify');
    expect(justifiedHeader).toHaveStyle({ textAlign: 'justify' });

    const centerCell = screen.getByText('Center Body');
    expect(centerCell).toHaveClass('text-center');

    const rightCell = screen.getByText('Right Body');
    expect(rightCell).toHaveClass('text-right');
  });

  it('handles standard markdown pipe tables alongside HTML tables', () => {
    const markdownTable = `
| Item | Price |
|---|---|
| Mango | $10 |
| Durian | $25 |
    `;

    const doc = createMockDoc(markdownTable);
    render(<ExtractedTextPanel {...defaultProps} document={doc} />);

    expect(screen.getByText('Mango')).toBeInTheDocument();
    expect(screen.getByText('Durian')).toBeInTheDocument();
  });
});

describe('ExtractedTextPanel JSON Tree OCRResult schema parity', () => {
  it('renders JSON Tree adhering to OCRResult.to_dict() schema parity', async () => {
    const user = userEvent.setup();
    const doc = createMockDoc('Page 1 Content', {
      id: 'doc-schema-test',
      name: 'invoice-sample.pdf',
      pages: 2,
      status: 'Done',
      pagesData: {
        1: { pageNumber: 1, text: 'Page 1 Content', latency: 1.25, tokens: 42, isTruncated: false },
        2: { pageNumber: 2, text: 'Page 2 Content', latency: 0.85, tokens: 28, isTruncated: false },
      },
    });

    render(<ExtractedTextPanel {...defaultProps} document={doc} />);

    // Click JSON Tree tab
    const jsonTab = screen.getByRole('tab', { name: /JSON Tree/i });
    await user.click(jsonTab);

    // Verify copy JSON button is displayed
    const copyButton = screen.getByRole('button', { name: /Copy JSON/i });
    expect(copyButton).toBeInTheDocument();

    // Verify the JSON tree contains expected schema keys
    expect(screen.getByText(/"file_path"/)).toBeInTheDocument();
    expect(screen.getByText(/"invoice-sample\.pdf"/)).toBeInTheDocument();
    expect(screen.getByText(/"total_duration"/)).toBeInTheDocument();
    expect(screen.getByText(/"page_count"/)).toBeInTheDocument();
    expect(screen.getByText(/"pages"/)).toBeInTheDocument();
    expect(screen.getAllByText(/"page_num"/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/"latency"/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/"tokens"/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/"markdown"/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/"truncated"/).length).toBeGreaterThan(0);
  });
});
