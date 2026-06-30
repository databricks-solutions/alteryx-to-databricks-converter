import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  /** When this value changes, the boundary clears its error state. */
  resetKey?: string | number;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidUpdate(prevProps: Props) {
    if (
      this.state.hasError &&
      prevProps.resetKey !== this.props.resetKey
    ) {
      this.setState({ hasError: false, error: null });
    }
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="flex flex-col items-center justify-center min-h-[300px] p-8 text-center">
          <h2 className="text-lg font-semibold text-[var(--fg)] mb-2">
            Something went wrong
          </h2>
          <p className="text-sm text-[var(--fg-muted)] mb-4">
            {this.state.error?.message || "An unexpected error occurred."}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="px-4 py-2 text-sm font-medium rounded-lg bg-[var(--ring)] text-white hover:opacity-90 transition-opacity"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
