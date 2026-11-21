import React, { Component, ErrorInfo, ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Unhandled render error in component tree:', error, errorInfo);
  }

  private handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  public render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="min-h-screen bg-[#202020] text-[#F3F3F3] flex items-center justify-center p-6">
          <div className="max-w-md w-full bg-[#272727] border border-white/[0.08] rounded-lg p-6 shadow-xs text-center">
            <div className="w-12 h-12 rounded-full bg-red-500/15 text-[#e58383] flex items-center justify-center mx-auto mb-4">
              <AlertTriangle className="w-6 h-6" aria-hidden="true" />
            </div>
            <h1 className="text-lg font-semibold text-[#F3F3F3] mb-2">Something went wrong</h1>
            <p className="text-sm text-[#A6A6A6] mb-4">
              An unexpected render error occurred in the workspace. You can refresh the view to recover.
            </p>
            {this.state.error && (
              <pre className="text-xs bg-[#202020] border border-white/[0.04] p-3 rounded-md text-left overflow-x-auto text-[#e58383] mb-4 font-mono">
                {this.state.error.message}
              </pre>
            )}
            <button
              onClick={this.handleReset}
              className="inline-flex items-center gap-2 px-4 py-2 bg-[#60CDFF] hover:bg-[#4CC2FF] active:bg-[#0091E6] text-[#000000] rounded-md text-sm font-semibold transition-colors cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none"
            >
              <RefreshCw className="w-4 h-4" />
              <span>Retry Component</span>
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
