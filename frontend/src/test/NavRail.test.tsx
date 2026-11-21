import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { NavRail } from '../components/workspace/NavRail';
import fs from 'node:fs';
import path from 'node:path';

describe('NavRail Component & WAI-ARIA Roving Tabindex', () => {
  it('renders 48px navigation rail, AksaraSight app mark, and all three navigation tabs', () => {
    render(<NavRail activeTab="workspace" onSelectTab={vi.fn()} />);

    const nav = screen.getByLabelText('Application Navigation');
    expect(nav).toBeInTheDocument();
    expect(nav).toHaveClass('w-12');
    expect(nav).toHaveClass('bg-[#202020]');

    // Verify App Mark
    expect(screen.getByLabelText('AksaraSight')).toBeInTheDocument();

    // Verify tablist and tabs
    const tablist = screen.getByRole('tablist', { name: 'Views' });
    expect(tablist).toBeInTheDocument();
    expect(tablist).toHaveAttribute('aria-orientation', 'vertical');

    expect(screen.getByRole('tab', { name: 'Workspace' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Queue' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Settings' })).toBeInTheDocument();

    // Verify Server Logs action button
    expect(screen.getByRole('button', { name: 'Server Logs' })).toBeInTheDocument();
  });

  it('renders active indicator pill and manages WAI-ARIA tab attributes', () => {
    const { rerender } = render(
      <NavRail activeTab="workspace" onSelectTab={vi.fn()} />
    );

    const workspaceTab = screen.getByRole('tab', { name: 'Workspace' });
    const queueTab = screen.getByRole('tab', { name: 'Queue' });
    const settingsTab = screen.getByRole('tab', { name: 'Settings' });

    expect(workspaceTab).toHaveAttribute('aria-selected', 'true');
    expect(workspaceTab).toHaveAttribute('tabindex', '0');
    expect(workspaceTab).toHaveAttribute('aria-controls', 'nav-panel-workspace');
    expect(queueTab).toHaveAttribute('aria-selected', 'false');
    expect(queueTab).toHaveAttribute('tabindex', '-1');
    expect(queueTab).toHaveAttribute('aria-controls', 'nav-panel-queue');
    expect(settingsTab).toHaveAttribute('aria-selected', 'false');
    expect(settingsTab).toHaveAttribute('tabindex', '-1');
    expect(settingsTab).toHaveAttribute('aria-controls', 'nav-panel-settings');

    // Indicator inside workspace tab
    const indicator = screen.getByTestId('active-indicator');
    expect(indicator).toBeInTheDocument();
    expect(workspaceTab).toContainElement(indicator);
    expect(indicator).toHaveClass('w-[3px]', 'h-4', 'rounded-full', 'bg-[#60CDFF]');

    // Switch active tab to settings
    rerender(<NavRail activeTab="settings" onSelectTab={vi.fn()} />);
    expect(settingsTab).toHaveAttribute('aria-selected', 'true');
    expect(settingsTab).toHaveAttribute('tabindex', '0');
    expect(workspaceTab).toHaveAttribute('aria-selected', 'false');
    expect(settingsTab).toContainElement(screen.getByTestId('active-indicator'));
  });

  it('invokes onSelectTab when a tab is clicked and onOpenServerLogs on log trigger', async () => {
    const user = userEvent.setup();
    const handleSelectTab = vi.fn();
    const handleOpenLogs = vi.fn();

    render(
      <NavRail
        activeTab="workspace"
        onSelectTab={handleSelectTab}
        onOpenServerLogs={handleOpenLogs}
      />
    );

    await user.click(screen.getByRole('tab', { name: 'Queue' }));
    expect(handleSelectTab).toHaveBeenCalledWith('queue');

    await user.click(screen.getByRole('tab', { name: 'Settings' }));
    expect(handleSelectTab).toHaveBeenCalledWith('settings');

    await user.click(screen.getByRole('button', { name: 'Server Logs' }));
    expect(handleOpenLogs).toHaveBeenCalledTimes(1);
  });

  it('navigates tabs using ArrowDown, ArrowUp, Home, and End keys (Roving Tabindex)', () => {
    const handleSelectTab = vi.fn();
    render(<NavRail activeTab="workspace" onSelectTab={handleSelectTab} />);

    const workspaceTab = screen.getByRole('tab', { name: 'Workspace' });
    const queueTab = screen.getByRole('tab', { name: 'Queue' });
    const settingsTab = screen.getByRole('tab', { name: 'Settings' });

    workspaceTab.focus();
    expect(document.activeElement).toBe(workspaceTab);

    // ArrowDown -> Queue
    fireEvent.keyDown(workspaceTab, { key: 'ArrowDown' });
    expect(handleSelectTab).toHaveBeenCalledWith('queue');
    expect(document.activeElement).toBe(queueTab);

    // ArrowDown -> Settings
    fireEvent.keyDown(queueTab, { key: 'ArrowDown' });
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

    // Home -> Workspace
    fireEvent.keyDown(settingsTab, { key: 'Home' });
    expect(handleSelectTab).toHaveBeenCalledWith('workspace');
    expect(document.activeElement).toBe(workspaceTab);

    // End -> Settings
    fireEvent.keyDown(workspaceTab, { key: 'End' });
    expect(handleSelectTab).toHaveBeenCalledWith('settings');
    expect(document.activeElement).toBe(settingsTab);
  });

  it('handles global keyboard shortcuts Ctrl+1 for Workspace and Ctrl+, for Settings', () => {
    const handleSelectTab = vi.fn();
    const { unmount } = render(
      <NavRail activeTab="queue" onSelectTab={handleSelectTab} />
    );

    // Trigger Ctrl+1
    fireEvent.keyDown(window, { key: '1', ctrlKey: true });
    expect(handleSelectTab).toHaveBeenCalledWith('workspace');

    // Trigger Ctrl+,
    fireEvent.keyDown(window, { key: ',', ctrlKey: true });
    expect(handleSelectTab).toHaveBeenCalledWith('settings');

    // Trigger Cmd+1 (macOS metaKey)
    fireEvent.keyDown(window, { key: '1', metaKey: true });
    expect(handleSelectTab).toHaveBeenCalledWith('workspace');

    // Verify unmount unregisters listener
    unmount();
    handleSelectTab.mockClear();
    fireEvent.keyDown(window, { key: '1', ctrlKey: true });
    expect(handleSelectTab).not.toHaveBeenCalled();
  });

  it('strictly adheres to WinUI 3 constraints and bans rounded-xl, rounded-2xl, and drop shadows in shell files', () => {
    const files = [
      path.resolve(__dirname, '../components/workspace/NavRail.tsx'),
      path.resolve(__dirname, '../components/workspace/TopNavBar.tsx'),
      path.resolve(__dirname, '../App.tsx'),
      path.resolve(__dirname, '../index.css'),
    ];

    for (const filePath of files) {
      const sourceCode = fs.readFileSync(filePath, 'utf8');
      expect(sourceCode).not.toMatch(/rounded-(xl|2xl)/);
      expect(sourceCode).not.toMatch(/shadow-(lg|xl|2xl)/);
    }

    const navRailSource = fs.readFileSync(files[0], 'utf8');
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
