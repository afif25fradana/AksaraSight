import React from 'react';

export const highlightJson = (json: string): React.ReactNode => {
  if (!json) return null;
  const regex = /("(?:\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*")(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[{}\[\],]|\s+|[^"{}[\],\s:]+/g;
  const nodes: React.ReactNode[] = [];
  let match: RegExpExecArray | null;
  let idx = 0;
  while ((match = regex.exec(json)) !== null) {
    const [token, strWithQuotes, colon] = match;
    if (colon) {
      nodes.push(<span key={idx++} className="text-[#14213D] dark:text-[var(--text-1)] font-semibold">{strWithQuotes}</span>);
      nodes.push(<span key={idx++} className="text-[#5A6478] dark:text-[var(--text-3)]">{colon}</span>);
    } else if (token.startsWith('"')) {
      nodes.push(<span key={idx++} className="text-[#0F766E] dark:text-[var(--accent)]">{token}</span>);
    } else if (/^(true|false|null)$/.test(token) || /^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(token)) {
      nodes.push(<span key={idx++} className="text-[#B45309] dark:text-[var(--warning)]">{token}</span>);
    } else if (/^[{}\[\],]$/.test(token)) {
      nodes.push(<span key={idx++} className="text-[#5A6478] dark:text-[var(--text-3)]">{token}</span>);
    } else {
      nodes.push(token);
    }
  }
  return nodes;
};
