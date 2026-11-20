import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TableRenderer } from '../components/renderers/TableRenderer';

describe('TableRenderer Component', () => {
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

  const sampleHtmlTable = `
    <table>
      <thead>
        <tr>
          <th>Item</th>
          <th>Qty</th>
          <th>Price</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Arsip A</td>
          <td>2</td>
          <td>50000</td>
        </tr>
        <tr>
          <td>Arsip B</td>
          <td>5</td>
          <td>120000</td>
        </tr>
      </tbody>
    </table>
  `;

  it('renders OTSL HTML table with header and body rows and columns', () => {
    render(<TableRenderer tableHtml={sampleHtmlTable} />);

    expect(screen.getByText('Structured Table')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Item' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Qty' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Price' })).toBeInTheDocument();

    expect(screen.getByRole('cell', { name: 'Arsip A' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: '2' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: '50000' })).toBeInTheDocument();

    expect(screen.getByRole('cell', { name: 'Arsip B' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: '5' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: '120000' })).toBeInTheDocument();
  });

  it('copies table data as CSV to clipboard when Copy CSV button is clicked', async () => {
    const user = userEvent.setup();
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: writeTextMock },
      writable: true,
      configurable: true,
    });

    render(<TableRenderer tableHtml={sampleHtmlTable} />);

    const copyCsvBtn = screen.getByRole('button', { name: /Copy CSV/i });
    await user.click(copyCsvBtn);

    expect(writeTextMock).toHaveBeenCalledWith('Item,Qty,Price\nArsip A,2,50000\nArsip B,5,120000');
    expect(await screen.findByText('CSV Copied')).toBeInTheDocument();
  });

  it('copies table data as TSV to clipboard when Copy TSV button is clicked', async () => {
    const user = userEvent.setup();
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: writeTextMock },
      writable: true,
      configurable: true,
    });

    render(<TableRenderer tableHtml={sampleHtmlTable} />);

    const copyTsvBtn = screen.getByRole('button', { name: /Copy TSV/i });
    await user.click(copyTsvBtn);

    expect(writeTextMock).toHaveBeenCalledWith('Item\tQty\tPrice\nArsip A\t2\t50000\nArsip B\t5\t120000');
    expect(await screen.findByText('TSV Copied')).toBeInTheDocument();
  });

  it('renders markdown pipe table rows correctly', () => {
    const mdLines = [
      '| Name | Type | Value |',
      '| --- | :---: | ---: |',
      '| Alpha | Doc | 100 |',
      '| Beta | Image | 200 |',
    ];

    render(<TableRenderer markdownRows={mdLines} />);

    expect(screen.getByRole('columnheader', { name: 'Name' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: 'Alpha' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: '200' })).toBeInTheDocument();
  });
});
