import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { NavRail } from '../components/workspace/NavRail';
import fs from 'node:fs';
import path from 'node:path';

describe('NavRail Component & Semantic Navigation', () => {
  it('renders 48px navigation rail, AksaraSight app mark, two destination buttons, and queue disclosure', () => {
    render(<NavRail activeTab="workspace" onSelectTab={vi.fn()} isQueueOpen={true} onToggleQueue={vi.fn()} onOpenServerLogs={vi.fn()} />);

    const nav = screen.getByLabelText('Application Navigation');
    expect(nav).toBeInTheDocument();
    expect(nav.tagName.toLowerCase()).toBe('nav');
    expect(nav).toHaveClass('w-12');
    expect(nav).toHaveClass('bg-[#202020]');

    // Verify App Mark
    const appMark = screen.getByLabelText('AksaraSight');
    expect(appMark).toBeInTheDocument();
    const logoSvg = appMark.querySelector('svg');
    expect(logoSvg).toBeInTheDocument();
    expect(logoSvg).toHaveAttribute('viewBox', '0 0 512 512');
    expect(logoSvg).toHaveClass('w-7', 'h-7');
    const logoGroup = logoSvg?.querySelector('g');
    expect(logoGroup).toBeInTheDocument();
    expect(logoGroup).toHaveAttribute('transform', 'translate(256 256) scale(1.12) translate(-256 -256)');

    // Verify destination buttons (Workspace and Settings)
    const workspaceBtn = screen.getByRole('button', { name: 'Workspace' });
    const settingsBtn = screen.getByRole('button', { name: 'Settings' });
    expect(workspaceBtn).toBeInTheDocument();
    expect(settingsBtn).toBeInTheDocument();

    // Verify standalone Queue disclosure button
    const queueBtn = screen.getByRole('button', { name: 'Collapse File Queue' });
    expect(queueBtn).toBeInTheDocument();
    expect(queueBtn).toHaveAttribute('aria-expanded', 'true');
    expect(queueBtn).toHaveAttribute('aria-controls', 'workspace-file-queue');

    // Verify Server Logs action button
    const logsBtn = screen.getByRole('button', { name: 'Server Logs' });
    expect(logsBtn).toBeInTheDocument();
    expect(logsBtn).toHaveAttribute('aria-haspopup', 'dialog');
  });

  it('renders active indicator pill and manages semantic aria-current attributes', () => {
    const { rerender } = render(
      <NavRail activeTab="workspace" onSelectTab={vi.fn()} isQueueOpen={true} />
    );

    const workspaceBtn = screen.getByRole('button', { name: 'Workspace' });
    const settingsBtn = screen.getByRole('button', { name: 'Settings' });

    expect(workspaceBtn).toHaveAttribute('aria-current', 'page');
    expect(settingsBtn).not.toHaveAttribute('aria-current');

    // Indicator inside workspace destination
    const indicator = screen.getByTestId('active-indicator');
    expect(indicator).toBeInTheDocument();
    expect(workspaceBtn).toContainElement(indicator);
    expect(indicator).toHaveClass('w-[3px]', 'h-4', 'rounded-full', 'bg-[#60CDFF]', 'animate-pill-enter');

    // Switch active tab to settings
    rerender(<NavRail activeTab="settings" onSelectTab={vi.fn()} isQueueOpen={false} />);
    expect(settingsBtn).toHaveAttribute('aria-current', 'page');
    expect(workspaceBtn).not.toHaveAttribute('aria-current');
    expect(settingsBtn).toContainElement(screen.getByTestId('active-indicator'));

    // Queue button reflects isQueueOpen=false
    const collapsedQueueBtn = screen.getByRole('button', { name: 'Expand File Queue' });
    expect(collapsedQueueBtn).toHaveAttribute('aria-expanded', 'false');
  });

  it('invokes onSelectTab when a destination is clicked, onToggleQueue on queue disclosure, and onOpenServerLogs on log trigger', async () => {
    const user = userEvent.setup();
    const handleSelectTab = vi.fn();
    const handleToggleQueue = vi.fn();
    const handleOpenLogs = vi.fn();

    render(
      <NavRail
        activeTab="workspace"
        onSelectTab={handleSelectTab}
        onToggleQueue={handleToggleQueue}
        onOpenServerLogs={handleOpenLogs}
        isQueueOpen={true}
      />
    );

    await user.click(screen.getByRole('button', { name: 'Collapse File Queue' }));
    expect(handleToggleQueue).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: 'Settings' }));
    expect(handleSelectTab).toHaveBeenCalledWith('settings');

    await user.click(screen.getByRole('button', { name: 'Server Logs' }));
    expect(handleOpenLogs).toHaveBeenCalledTimes(1);
  });

  it('handles Ctrl+Shift+L and Cmd+Shift+L global shortcuts to trigger onOpenServerLogs', () => {
    const handleOpenLogs = vi.fn();
    const { unmount } = render(
      <NavRail activeTab="workspace" onSelectTab={vi.fn()} onOpenServerLogs={handleOpenLogs} />
    );

    // Ctrl+Shift+L
    fireEvent.keyDown(window, { key: 'l', ctrlKey: true, shiftKey: true });
    expect(handleOpenLogs).toHaveBeenCalledTimes(1);

    // Cmd+Shift+L (macOS)
    fireEvent.keyDown(window, { key: 'L', metaKey: true, shiftKey: true });
    expect(handleOpenLogs).toHaveBeenCalledTimes(2);

    unmount();
    handleOpenLogs.mockClear();
    fireEvent.keyDown(window, { key: 'l', ctrlKey: true, shiftKey: true });
    expect(handleOpenLogs).not.toHaveBeenCalled();
  });

  it('handles global keyboard shortcuts Ctrl+1 for Workspace, Ctrl+, for Settings, and Ctrl+B/Cmd+B for Queue', () => {
    const handleSelectTab = vi.fn();
    const handleToggleQueue = vi.fn();
    const { unmount } = render(
      <NavRail activeTab="workspace" onSelectTab={handleSelectTab} onToggleQueue={handleToggleQueue} />
    );

    // Trigger Ctrl+1 -> Workspace
    fireEvent.keyDown(window, { key: '1', ctrlKey: true });
    expect(handleSelectTab).toHaveBeenCalledWith('workspace');

    // Trigger Ctrl+, -> Settings
    fireEvent.keyDown(window, { key: ',', ctrlKey: true });
    expect(handleSelectTab).toHaveBeenCalledWith('settings');

    // Trigger Cmd+1 (macOS metaKey) -> Workspace
    fireEvent.keyDown(window, { key: '1', metaKey: true });
    expect(handleSelectTab).toHaveBeenCalledWith('workspace');

    // Trigger Ctrl+B -> toggle Queue
    fireEvent.keyDown(window, { key: 'b', ctrlKey: true });
    expect(handleToggleQueue).toHaveBeenCalledTimes(1);

    // Trigger Cmd+B -> toggle Queue
    fireEvent.keyDown(window, { key: 'B', metaKey: true });
    expect(handleToggleQueue).toHaveBeenCalledTimes(2);

    // Verify unmount unregisters listeners
    unmount();
    handleSelectTab.mockClear();
    handleToggleQueue.mockClear();
    fireEvent.keyDown(window, { key: '1', ctrlKey: true });
    fireEvent.keyDown(window, { key: 'b', ctrlKey: true });
    expect(handleSelectTab).not.toHaveBeenCalled();
    expect(handleToggleQueue).not.toHaveBeenCalled();
  });

  it('strictly adheres to WinUI 3 constraints and bans rounded-xl, rounded-2xl, and drop shadows across all Wave 3 workspace components', () => {
    const files = [
      path.resolve(__dirname, '../App.tsx'),
      path.resolve(__dirname, '../components/workspace/TopNavBar.tsx'),
      path.resolve(__dirname, '../components/workspace/NavRail.tsx'),
      path.resolve(__dirname, '../components/workspace/BottomStatusBar.tsx'),
      path.resolve(__dirname, '../components/workspace/FileQueuePanel.tsx'),
      path.resolve(__dirname, '../components/workspace/QueueItemRow.tsx'),
      path.resolve(__dirname, '../components/workspace/DocumentPreviewPanel.tsx'),
      path.resolve(__dirname, '../components/workspace/ExtractedTextPanel.tsx'),
      path.resolve(__dirname, '../components/workspace/ExportDropdown.tsx'),
      path.resolve(__dirname, '../components/workspace/ExtractionOptionsPopover.tsx'),
      path.resolve(__dirname, '../components/settings/SettingsView.tsx'),
    ];

    for (const filePath of files) {
      const sourceCode = fs.readFileSync(filePath, 'utf8');
      expect(sourceCode).not.toMatch(/rounded-(xl|2xl)/);
      expect(sourceCode).not.toMatch(/shadow-(lg|xl|2xl)/);
      expect(sourceCode).not.toMatch(/teal-/);
      expect(sourceCode).not.toMatch(/#0F766E/i);
      expect(sourceCode).not.toMatch(/#115E59/i);
    }

    const navRailSource = fs.readFileSync(path.resolve(__dirname, '../components/workspace/NavRail.tsx'), 'utf8');
    // Enforce 4px control radius and WinUI 3 colors
    expect(navRailSource).toMatch(/rounded-sm/);
    expect(navRailSource).toMatch(/#202020/);
    expect(navRailSource).toMatch(/#60CDFF/);
  });

  it('declares semantic view containers in App.tsx and avoids orphan tabpanel roles', () => {
    const appPath = path.resolve(__dirname, '../App.tsx');
    const appSource = fs.readFileSync(appPath, 'utf8');

    expect(appSource).not.toMatch(/role="tabpanel"/);
    expect(appSource).not.toMatch(/aria-labelledby="nav-tab-/);
    expect(appSource).toMatch(/id="view-settings"/);
    expect(appSource).toMatch(/id="view-workspace"/);
  });
});
