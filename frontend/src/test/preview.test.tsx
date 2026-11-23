import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
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

describe('ExtractedTextPanel WAI-ARIA APG Tabs Pattern', () => {
  it('renders tablist and tabs with correct roles, IDs, aria-selected, and roving tabIndex', () => {
    const doc = createMockDoc('Sample extracted content');
    render(<ExtractedTextPanel {...defaultProps} document={doc} />);

    const tablist = screen.getByRole('tablist', { name: 'Preview display modes' });
    expect(tablist).toBeInTheDocument();

    const formattedTab = screen.getByRole('tab', { name: /Formatted Preview/i });
    const rawTab = screen.getByRole('tab', { name: /Raw Markdown/i });
    const jsonTab = screen.getByRole('tab', { name: /JSON Tree/i });

    expect(formattedTab).toHaveAttribute('id', 'preview-tab-formatted');
    expect(rawTab).toHaveAttribute('id', 'preview-tab-raw');
    expect(jsonTab).toHaveAttribute('id', 'preview-tab-json');

    // Default active tab is formatted
    expect(formattedTab).toHaveAttribute('aria-selected', 'true');
    expect(formattedTab).toHaveAttribute('tabIndex', '0');
    expect(rawTab).toHaveAttribute('aria-selected', 'false');
    expect(rawTab).toHaveAttribute('tabIndex', '-1');
    expect(jsonTab).toHaveAttribute('aria-selected', 'false');
    expect(jsonTab).toHaveAttribute('tabIndex', '-1');

    // aria-controls attached when mounted and target panels exist in DOM (no dangling aria-controls)
    expect(formattedTab).toHaveAttribute('aria-controls', 'preview-tabpanel-formatted');
    expect(rawTab).toHaveAttribute('aria-controls', 'preview-tabpanel-raw');
    expect(jsonTab).toHaveAttribute('aria-controls', 'preview-tabpanel-json');

    expect(document.getElementById('preview-tabpanel-formatted')).toBeInTheDocument();
    expect(document.getElementById('preview-tabpanel-raw')).toBeInTheDocument();
    expect(document.getElementById('preview-tabpanel-json')).toBeInTheDocument();
  });

  it('omits aria-controls when preview panel is not mounted (empty or offline state)', () => {
    // Empty state (document = null)
    const { rerender } = render(<ExtractedTextPanel {...defaultProps} document={null} />);
    const formattedTab = screen.getByRole('tab', { name: /Formatted Preview/i });
    expect(formattedTab).not.toHaveAttribute('aria-controls');

    // Offline state
    rerender(<ExtractedTextPanel {...defaultProps} document={createMockDoc('text')} isEngineOnline={false} />);
    const offlineFormattedTab = screen.getByRole('tab', { name: /Formatted Preview/i });
    expect(offlineFormattedTab).not.toHaveAttribute('aria-controls');
  });

  it('supports roving tabindex and keyboard navigation: ArrowRight, ArrowLeft, Home, End with automatic activation', () => {
    const doc = createMockDoc('Sample extracted content');
    render(<ExtractedTextPanel {...defaultProps} document={doc} />);

    const formattedTab = screen.getByRole('tab', { name: /Formatted Preview/i });
    const rawTab = screen.getByRole('tab', { name: /Raw Markdown/i });
    const jsonTab = screen.getByRole('tab', { name: /JSON Tree/i });

    formattedTab.focus();
    expect(document.activeElement).toBe(formattedTab);

    // ArrowRight -> activates and focuses Raw tab
    fireEvent.keyDown(formattedTab, { key: 'ArrowRight' });
    expect(rawTab).toHaveAttribute('aria-selected', 'true');
    expect(rawTab).toHaveAttribute('tabIndex', '0');
    expect(formattedTab).toHaveAttribute('aria-selected', 'false');
    expect(formattedTab).toHaveAttribute('tabIndex', '-1');
    expect(document.activeElement).toBe(rawTab);

    // ArrowRight -> activates and focuses JSON tab
    fireEvent.keyDown(rawTab, { key: 'ArrowRight' });
    expect(jsonTab).toHaveAttribute('aria-selected', 'true');
    expect(document.activeElement).toBe(jsonTab);

    // ArrowRight (wrap) -> activates and focuses Formatted tab
    fireEvent.keyDown(jsonTab, { key: 'ArrowRight' });
    expect(formattedTab).toHaveAttribute('aria-selected', 'true');
    expect(document.activeElement).toBe(formattedTab);

    // ArrowLeft (wrap) -> activates and focuses JSON tab
    fireEvent.keyDown(formattedTab, { key: 'ArrowLeft' });
    expect(jsonTab).toHaveAttribute('aria-selected', 'true');
    expect(document.activeElement).toBe(jsonTab);

    // ArrowLeft -> activates and focuses Raw tab
    fireEvent.keyDown(jsonTab, { key: 'ArrowLeft' });
    expect(rawTab).toHaveAttribute('aria-selected', 'true');
    expect(document.activeElement).toBe(rawTab);

    // Home -> activates and focuses first tab (Formatted)
    fireEvent.keyDown(rawTab, { key: 'Home' });
    expect(formattedTab).toHaveAttribute('aria-selected', 'true');
    expect(document.activeElement).toBe(formattedTab);

    // End -> activates and focuses last tab (JSON)
    fireEvent.keyDown(formattedTab, { key: 'End' });
    expect(jsonTab).toHaveAttribute('aria-selected', 'true');
    expect(document.activeElement).toBe(jsonTab);
  });

  it('renders distinct tabpanels with appropriate aria-labelledby and tabIndex attributes, mounting all panels with hidden attribute', async () => {
    const user = userEvent.setup();
    const doc = createMockDoc('Markdown **bold** content');
    render(<ExtractedTextPanel {...defaultProps} document={doc} />);

    // All 3 tabpanels exist concurrently in DOM to prevent dangling aria-controls
    const formattedPanelEl = document.getElementById('preview-tabpanel-formatted');
    const rawPanelEl = document.getElementById('preview-tabpanel-raw');
    const jsonPanelEl = document.getElementById('preview-tabpanel-json');

    expect(formattedPanelEl).toBeInTheDocument();
    expect(rawPanelEl).toBeInTheDocument();
    expect(jsonPanelEl).toBeInTheDocument();

    // Inactive panels are hidden
    expect(formattedPanelEl).not.toHaveAttribute('hidden');
    expect(rawPanelEl).toHaveAttribute('hidden');
    expect(jsonPanelEl).toHaveAttribute('hidden');

    // Only the active tabpanel is exposed to assistive tech via getByRole
    const formattedPanel = screen.getByRole('tabpanel');
    expect(formattedPanel).toBe(formattedPanelEl);
    expect(formattedPanel).toHaveAttribute('id', 'preview-tabpanel-formatted');
    expect(formattedPanel).toHaveAttribute('aria-labelledby', 'preview-tab-formatted');
    expect(formattedPanel).toHaveAttribute('tabIndex', '0');

    // Switch to Raw tab
    const rawTab = screen.getByRole('tab', { name: /Raw Markdown/i });
    await user.click(rawTab);

    expect(formattedPanelEl).toHaveAttribute('hidden');
    expect(rawPanelEl).not.toHaveAttribute('hidden');
    expect(jsonPanelEl).toHaveAttribute('hidden');

    const rawPanel = screen.getByRole('tabpanel');
    expect(rawPanel).toBe(rawPanelEl);
    expect(rawPanel).toHaveAttribute('id', 'preview-tabpanel-raw');
    expect(rawPanel).toHaveAttribute('aria-labelledby', 'preview-tab-raw');
    // Raw panel wrapper must NOT have tabIndex="0"
    expect(rawPanel).not.toHaveAttribute('tabIndex');
    // Inside rawPanel is the textarea
    const textarea = screen.getByRole('textbox', { name: /OCR extracted text/i });
    expect(rawPanel).toContainElement(textarea);
    expect(textarea).not.toHaveAttribute('role', 'tabpanel');

    // Switch to JSON tab
    const jsonTab = screen.getByRole('tab', { name: /JSON Tree/i });
    await user.click(jsonTab);

    expect(formattedPanelEl).toHaveAttribute('hidden');
    expect(rawPanelEl).toHaveAttribute('hidden');
    expect(jsonPanelEl).not.toHaveAttribute('hidden');

    const jsonPanel = screen.getByRole('tabpanel');
    expect(jsonPanel).toBe(jsonPanelEl);
    expect(jsonPanel).toHaveAttribute('id', 'preview-tabpanel-json');
    expect(jsonPanel).toHaveAttribute('aria-labelledby', 'preview-tab-json');
    expect(jsonPanel).toHaveAttribute('tabIndex', '0');
  });
});
