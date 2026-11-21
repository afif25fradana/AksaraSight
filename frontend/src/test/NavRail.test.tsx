import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { NavRail } from '../components/workspace/NavRail';
import fs from 'node:fs';
import path from 'node:path';

describe('NavRail Component & WAI-ARIA Roving Tabindex', () => {
  it('renders 48px navigation rail, AksaraSight app mark, exactly two navigation tabs, and queue disclosure', () => {
    render(<NavRail activeTab="workspace" onSelectTab={vi.fn()} isQueueOpen={true} onToggleQueue={vi.fn()} />);

    const nav = screen.getByLabelText('Application Navigation');
    expect(nav).toBeInTheDocument();
    expect(nav).toHaveClass('w-12');
    expect(nav).toHaveClass('bg-[#202020]');

    // Verify App Mark
    expect(screen.getByLabelText('AksaraSight')).toBeInTheDocument();

    // Verify tablist contains exactly 2 tabs (Workspace and Settings)
    const tablist = screen.getByRole('tablist', { name: 'Views' });
    expect(tablist).toBeInTheDocument();
    expect(tablist).toHaveAttribute('aria-orientation', 'vertical');

    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(2);
    expect(screen.getByRole('tab', { name: 'Workspace' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Settings' })).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Queue' })).not.toBeInTheDocument();

    // Verify standalone Queue disclosure button outside tablist
    const queueBtn = screen.getByRole('button', { name: 'Collapse File Queue' });
    expect(queueBtn).toBeInTheDocument();
    expect(queueBtn).toHaveAttribute('aria-expanded', 'true');
    expect(queueBtn).toHaveAttribute('aria-controls', 'workspace-file-queue');

    // Verify Server Logs action button
    expect(screen.getByRole('button', { name: 'Server Logs' })).toBeInTheDocument();
  });

  it('renders active indicator pill and manages WAI-ARIA tab attributes', () => {
    const { rerender } = render(
      <NavRail activeTab="workspace" onSelectTab={vi.fn()} isQueueOpen={true} />
    );

    const workspaceTab = screen.getByRole('tab', { name: 'Workspace' });
    const settingsTab = screen.getByRole('tab', { name: 'Settings' });

    expect(workspaceTab).toHaveAttribute('aria-selected', 'true');
    expect(workspaceTab).toHaveAttribute('tabindex', '0');
    expect(workspaceTab).toHaveAttribute('aria-controls', 'nav-panel-workspace');
    expect(settingsTab).toHaveAttribute('aria-selected', 'false');
    expect(settingsTab).toHaveAttribute('tabindex', '-1');
    expect(settingsTab).toHaveAttribute('aria-controls', 'nav-panel-settings');

    // Indicator inside workspace tab
    const indicator = screen.getByTestId('active-indicator');
    expect(indicator).toBeInTheDocument();
    expect(workspaceTab).toContainElement(indicator);
    expect(indicator).toHaveClass('w-[3px]', 'h-4', 'rounded-full', 'bg-[#60CDFF]');

    // Switch active tab to settings
    rerender(<NavRail activeTab="settings" onSelectTab={vi.fn()} isQueueOpen={false} />);
    expect(settingsTab).toHaveAttribute('aria-selected', 'true');
    expect(settingsTab).toHaveAttribute('tabindex', '0');
    expect(workspaceTab).toHaveAttribute('aria-selected', 'false');
    expect(settingsTab).toContainElement(screen.getByTestId('active-indicator'));

    // Queue button reflects isQueueOpen=false
    const collapsedQueueBtn = screen.getByRole('button', { name: 'Expand File Queue' });
    expect(collapsedQueueBtn).toHaveAttribute('aria-expanded', 'false');
  });

  it('invokes onSelectTab when a tab is clicked, onToggleQueue on queue disclosure, and onOpenServerLogs on log trigger', async () => {
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

    await user.click(screen.getByRole('tab', { name: 'Settings' }));
    expect(handleSelectTab).toHaveBeenCalledWith('settings');

    await user.click(screen.getByRole('button', { name: 'Server Logs' }));
    expect(handleOpenLogs).toHaveBeenCalledTimes(1);
  });

  it('navigates tabs using ArrowDown, ArrowUp, Home, and End keys (Roving Tabindex cycling 2 tabs)', () => {
    const handleSelectTab = vi.fn();
    render(<NavRail activeTab="workspace" onSelectTab={handleSelectTab} />);

    const workspaceTab = screen.getByRole('tab', { name: 'Workspace' });
    const settingsTab = screen.getByRole('tab', { name: 'Settings' });

    workspaceTab.focus();
    expect(document.activeElement).toBe(workspaceTab);

    // ArrowDown -> Settings
    fireEvent.keyDown(workspaceTab, { key: 'ArrowDown' });
    expect(handleSelectTab).toHaveBeenCalledWith('settings');
    expect(document.activeElement).toBe(settingsTab);

    // ArrowDown -> cycles back to Workspace
    fireEvent.keyDown(settingsTab, { key: 'ArrowDown' });
    expect(handleSelectTab).toHaveBeenCalledWith('workspace');
    expect(document.activeElement).toBe(workspaceTab);

    // ArrowUp -> cycles back to Settings
    fireEvent.keyDown(workspaceTab, { key: 'ArrowUp' });
    expect(handleSelectTab).toHaveBeenCalledWith('settings');
    expect(document.activeElement).toBe(settingsTab);

    // ArrowUp -> Workspace
    fireEvent.keyDown(settingsTab, { key: 'ArrowUp' });
    expect(handleSelectTab).toHaveBeenCalledWith('workspace');
    expect(document.activeElement).toBe(workspaceTab);

    // Home -> Workspace
    fireEvent.keyDown(settingsTab, { key: 'Home' });
    expect(handleSelectTab).toHaveBeenCalledWith('workspace');
    expect(document.activeElement).toBe(workspaceTab);

    // End -> Settings
    fireEvent.keyDown(workspaceTab, { key: 'End' });
    expect(handleSelectTab).toHaveBeenCalledWith('settings');
    expect(document.activeElement).toBe(settingsTab);
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

  it('declares WAI-ARIA tabpanel semantics and links in App.tsx', () => {
    const appPath = path.resolve(__dirname, '../App.tsx');
    const appSource = fs.readFileSync(appPath, 'utf8');

    expect(appSource).toMatch(
      /role="tabpanel"\s+id="nav-panel-settings"\s+aria-labelledby="nav-tab-settings"/
    );
    expect(appSource).toMatch(
      /role="tabpanel"\s+id="nav-panel-workspace"\s+aria-labelledby="nav-tab-workspace"/
    );
  });
});
