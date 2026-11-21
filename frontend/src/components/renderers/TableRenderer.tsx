import React, { useState, useMemo, useRef, useEffect } from 'react';
import { Copy, Check, FileSpreadsheet } from 'lucide-react';

export interface ParsedTableCell {
  text: string;
  isHeader?: boolean;
  colSpan?: number;
  rowSpan?: number;
  alignClass: string;
  textAlign: 'left' | 'center' | 'right' | 'justify';
}

export interface ParsedTableRow {
  isHeader: boolean;
  cells: ParsedTableCell[];
}

export interface TableRendererProps {
  tableHtml?: string;
  markdownRows?: string[];
  className?: string;
}

export function parseHtmlTableSnippet(htmlSnippet: string): { headerRows: ParsedTableRow[]; bodyRows: ParsedTableRow[] } {
  if (typeof DOMParser === 'undefined') {
    return { headerRows: [], bodyRows: [] };
  }

  const parser = new DOMParser();
  const doc = parser.parseFromString(htmlSnippet, 'text/html');
  const tableEl = doc.querySelector('table');
  if (!tableEl) return { headerRows: [], bodyRows: [] };

  const trEls = Array.from(tableEl.querySelectorAll('tr'));
  if (trEls.length === 0) return { headerRows: [], bodyRows: [] };

  const parsedRows: ParsedTableRow[] = trEls.map((tr) => {
    const isHeaderRow = tr.closest('thead') !== null || tr.querySelector('th') !== null;
    const cellEls = Array.from(tr.querySelectorAll('th, td'));
    const cells: ParsedTableCell[] = cellEls.map((cell) => {
      const isTh = cell.tagName.toLowerCase() === 'th';
      const colSpanVal = (cell as HTMLTableCellElement).colSpan || parseInt(cell.getAttribute('colspan') || cell.getAttribute('colSpan') || '1', 10);
      const colSpan = colSpanVal > 1 ? colSpanVal : undefined;

      const rowSpanVal = (cell as HTMLTableCellElement).rowSpan || parseInt(cell.getAttribute('rowspan') || cell.getAttribute('rowSpan') || '1', 10);
      const rowSpan = rowSpanVal > 1 ? rowSpanVal : undefined;

      let textAlign: 'left' | 'center' | 'right' | 'justify' = 'left';
      const rawAlign = (cell.getAttribute('align') || '').toLowerCase();
      const styleAttr = (cell.getAttribute('style') || '').toLowerCase();
      if (rawAlign === 'center' || styleAttr.includes('text-align: center') || styleAttr.includes('text-align:center')) {
        textAlign = 'center';
      } else if (rawAlign === 'right' || styleAttr.includes('text-align: right') || styleAttr.includes('text-align:right')) {
        textAlign = 'right';
      } else if (rawAlign === 'justify' || styleAttr.includes('text-align: justify') || styleAttr.includes('text-align:justify')) {
        textAlign = 'justify';
      }

      const alignClass = textAlign === 'center' ? 'text-center' : textAlign === 'right' ? 'text-right' : textAlign === 'justify' ? 'text-justify' : 'text-left';
      const text = (cell.textContent || '').trim();

      return {
        text,
        isHeader: isTh,
        colSpan,
        rowSpan,
        alignClass,
        textAlign,
      };
    });

    return {
      isHeader: isHeaderRow,
      cells,
    };
  }).filter((row) => row.cells.length > 0);

  const headerRows: ParsedTableRow[] = [];
  const bodyRows: ParsedTableRow[] = [];

  parsedRows.forEach((row) => {
    if (row.isHeader && bodyRows.length === 0) {
      headerRows.push(row);
    } else {
      bodyRows.push(row);
    }
  });

  return { headerRows, bodyRows };
}

export function parseMarkdownPipeTable(lines: string[]): { headerRows: ParsedTableRow[]; bodyRows: ParsedTableRow[] } {
  const rows = lines.map((r) =>
    r
      .split('|')
      .slice(1, -1)
      .map((c) => c.trim())
  );

  if (rows.length < 2) {
    return { headerRows: [], bodyRows: [] };
  }

  const header = rows[0];
  const dataRows = rows.slice(1).filter((r) => !r.every((c) => /^[-:]+$/.test(c)));

  const headerRow: ParsedTableRow = {
    isHeader: true,
    cells: header.map((text) => ({
      text,
      isHeader: true,
      alignClass: 'text-left',
      textAlign: 'left',
    })),
  };

  const bodyRows: ParsedTableRow[] = dataRows.map((row) => ({
    isHeader: false,
    cells: row.map((text) => ({
      text,
      isHeader: false,
      alignClass: 'text-left',
      textAlign: 'left',
    })),
  }));

  return {
    headerRows: [headerRow],
    bodyRows,
  };
}

export const TableRenderer: React.FC<TableRendererProps> = ({
  tableHtml,
  markdownRows,
  className = '',
}) => {
  const [copyStatus, setCopyStatus] = useState<'csv' | 'tsv' | null>(null);
  const copyTimeoutRef = useRef<any>(null);

  useEffect(() => {
    return () => {
      if (copyTimeoutRef.current) {
        clearTimeout(copyTimeoutRef.current);
      }
    };
  }, []);

  const { headerRows, bodyRows } = useMemo(() => {
    if (tableHtml) {
      return parseHtmlTableSnippet(tableHtml);
    }
    if (markdownRows && markdownRows.length > 0) {
      return parseMarkdownPipeTable(markdownRows);
    }
    return { headerRows: [], bodyRows: [] };
  }, [tableHtml, markdownRows]);

  const allRows = useMemo(() => [...headerRows, ...bodyRows], [headerRows, bodyRows]);

  const handleCopy = async (format: 'csv' | 'tsv') => {
    if (allRows.length === 0) return;
    const delimiter = format === 'csv' ? ',' : '\t';
    const text = allRows
      .map((row) =>
        row.cells
          .map((c) => {
            let val = c.text;
            if (format === 'csv' && (val.includes(',') || val.includes('"') || val.includes('\n'))) {
              val = `"${val.replace(/"/g, '""')}"`;
            }
            return val;
          })
          .join(delimiter)
      )
      .join('\n');

    try {
      await navigator.clipboard.writeText(text);
      setCopyStatus(format);
      if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current);
      copyTimeoutRef.current = setTimeout(() => setCopyStatus(null), 2000);
    } catch (err) {
      console.warn('Failed to copy table data:', err);
    }
  };

  if (headerRows.length === 0 && bodyRows.length === 0) {
    return null;
  }

  return (
    <div
      className={`my-3 overflow-x-auto rounded-lg border border-white/[0.04] shadow-xs bg-[#272727] ${className}`}
    >
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-white/[0.04] bg-[#2D2D2D] select-none">
        <div className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wider text-[#A6A6A6]">
          <FileSpreadsheet className="w-3.5 h-3.5 text-[#60CDFF]" aria-hidden="true" />
          <span>Structured Table</span>
        </div>

        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => handleCopy('csv')}
            className="h-6 px-2 rounded-md hover:bg-white/5 text-[#A6A6A6] hover:text-[#F3F3F3] flex items-center gap-1 text-[11px] font-medium transition-colors cursor-pointer"
            title="Copy table as CSV"
          >
            {copyStatus === 'csv' ? (
              <>
                <Check className="w-3 h-3 text-[#78c697]" aria-hidden="true" />
                <span className="text-[#78c697] font-medium">CSV Copied</span>
              </>
            ) : (
              <>
                <Copy className="w-3 h-3" aria-hidden="true" />
                <span>Copy CSV</span>
              </>
            )}
          </button>

          <button
            type="button"
            onClick={() => handleCopy('tsv')}
            className="h-6 px-2 rounded-md hover:bg-white/5 text-[#A6A6A6] hover:text-[#F3F3F3] flex items-center gap-1 text-[11px] font-medium transition-colors cursor-pointer"
            title="Copy table as TSV (Excel/Sheets)"
          >
            {copyStatus === 'tsv' ? (
              <>
                <Check className="w-3 h-3 text-[#78c697]" aria-hidden="true" />
                <span className="text-[#78c697] font-medium">TSV Copied</span>
              </>
            ) : (
              <>
                <Copy className="w-3 h-3" aria-hidden="true" />
                <span>Copy TSV</span>
              </>
            )}
          </button>
        </div>
      </div>

      <table className="w-full text-left border-collapse text-[12px]">
        {headerRows.length > 0 && (
          <thead>
            {headerRows.map((row, rIdx) => (
              <tr
                key={`hrow-${rIdx}`}
                className="bg-[#2D2D2D] border-b border-white/[0.06] text-[#F3F3F3] font-semibold"
              >
                {row.cells.map((cell, cIdx) => (
                  <th
                    key={`hcell-${cIdx}`}
                    colSpan={cell.colSpan}
                    rowSpan={cell.rowSpan}
                    scope="col"
                    style={{ textAlign: cell.textAlign }}
                    className={`px-3 py-2 border-r border-white/[0.04] last:border-r-0 ${cell.alignClass}`}
                  >
                    {cell.text}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
        )}

        {bodyRows.length > 0 && (
          <tbody className="divide-y divide-white/[0.04]">
            {bodyRows.map((row, rIdx) => (
              <tr
                key={`brow-${rIdx}`}
                className={`${
                  rIdx % 2 === 0 ? 'bg-[#272727]' : 'bg-[#232323]'
                } hover:bg-white/[0.03] transition-colors duration-100`}
              >
                {row.cells.map((cell, cIdx) => {
                  const CellTag = cell.isHeader ? 'th' : 'td';
                  return (
                    <CellTag
                      key={`bcell-${cIdx}`}
                      colSpan={cell.colSpan}
                      rowSpan={cell.rowSpan}
                      {...(cell.isHeader ? { scope: 'row' } : {})}
                      style={{ textAlign: cell.textAlign }}
                      className={`px-3 py-2 border-r border-white/[0.04] last:border-r-0 text-[#F3F3F3] ${
                        cell.isHeader ? 'font-semibold' : ''
                      } ${cell.alignClass}`}
                    >
                      {cell.text}
                    </CellTag>
                  );
                })}
              </tr>
            ))}
          </tbody>
        )}
      </table>
    </div>
  );
};
