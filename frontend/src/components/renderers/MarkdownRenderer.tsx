import React, { useMemo } from 'react';
import { TableRenderer } from './TableRenderer';
import { FormulaRenderer } from './FormulaRenderer';

interface MarkdownRendererProps {
  content: string;
  taskMode?: string;
  className?: string;
}

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({
  content,
  taskMode = 'text',
  className = '',
}) => {
  const renderedElements = useMemo(() => {
    if (!content.trim()) {
      return (
        <div className="text-[#5A6478] dark:text-[var(--text-2)] italic p-4 text-center text-[13px]">
          No content extracted for {taskMode} mode
        </div>
      );
    }

    const lines = content.split('\n');
    const elements: React.ReactNode[] = [];
    let tableBuffer: string[] = [];
    let inTable = false;
    let htmlTableBuffer: string[] = [];
    let inHtmlTable = false;

    const flushTable = (key: string) => {
      if (tableBuffer.length === 0) return;
      elements.push(<TableRenderer key={key} markdownRows={[...tableBuffer]} />);
      tableBuffer = [];
      inTable = false;
    };

    const flushHtmlTable = (key: string) => {
      if (htmlTableBuffer.length === 0) {
        inHtmlTable = false;
        return;
      }
      const snippet = htmlTableBuffer.join('\n');
      elements.push(<TableRenderer key={key} tableHtml={snippet} />);
      htmlTableBuffer = [];
      inHtmlTable = false;
    };

    lines.forEach((line, index) => {
      const trimmed = line.trim();

      // HTML Table Line
      if (trimmed.toLowerCase().includes('<table') || inHtmlTable) {
        if (inTable) {
          flushTable(`table-${index}`);
        }
        inHtmlTable = true;
        htmlTableBuffer.push(line);
        if (trimmed.toLowerCase().includes('</table>')) {
          flushHtmlTable(`html-table-${index}`);
        }
        return;
      }

      // Markdown Pipe Table Line
      if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
        inTable = true;
        tableBuffer.push(trimmed);
        return;
      }

      if (inTable) {
        flushTable(`table-${index}`);
      }

      if (!trimmed) {
        elements.push(<div key={`empty-${index}`} className="h-2.5" />);
        return;
      }

      // Formula Line: starts with \, \text, \sum, \frac or $$
      if (
        trimmed.startsWith('$$') ||
        (trimmed.startsWith('$') && trimmed.endsWith('$') && trimmed.length > 2) ||
        trimmed.startsWith('\\') ||
        trimmed.includes('\\text{') ||
        trimmed.includes('\\sum') ||
        trimmed.includes('\\frac')
      ) {
        elements.push(<FormulaRenderer key={`formula-${index}`} latex={trimmed} />);
        return;
      }

      // Headings
      if (trimmed.startsWith('### ')) {
        elements.push(
          <h4 key={`h3-${index}`} className="text-[14px] font-bold text-[#14213D] dark:text-[var(--text-1)] mt-3 mb-1">
            {trimmed.replace('### ', '')}
          </h4>
        );
      } else if (trimmed.startsWith('## ')) {
        elements.push(
          <h3 key={`h2-${index}`} className="text-[15px] font-bold text-[#14213D] dark:text-[var(--text-1)] mt-3.5 mb-1.5 border-b border-black/5 dark:border-[var(--border)] pb-1">
            {trimmed.replace('## ', '')}
          </h3>
        );
      } else if (trimmed.startsWith('# ')) {
        elements.push(
          <h2 key={`h1-${index}`} className="text-[16px] font-bold text-[#14213D] dark:text-[var(--text-1)] mt-4 mb-2">
            {trimmed.replace('# ', '')}
          </h2>
        );
      } else if (trimmed.startsWith('---')) {
        elements.push(<hr key={`hr-${index}`} className="my-3 border-t border-[#8A94A6]/30 dark:border-[var(--border)]" />);
      } else {
        elements.push(
          <p key={`p-${index}`} className="text-[13px] leading-relaxed text-[#14213D] dark:text-[var(--text-1)] mb-1">
            {trimmed}
          </p>
        );
      }
    });

    if (inTable) {
      flushTable('table-end');
    }
    if (inHtmlTable || htmlTableBuffer.length > 0) {
      flushHtmlTable('html-table-end');
    }

    return elements;
  }, [content, taskMode]);

  return <div className={`select-text ${className}`}>{renderedElements}</div>;
};
