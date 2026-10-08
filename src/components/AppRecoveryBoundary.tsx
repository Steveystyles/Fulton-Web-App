import { Component, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { failed: boolean };

/** Keep a stale lazy-loaded route from turning the entire app into a blank page. */
export class AppRecoveryBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="saints-shell-bg flex min-h-dvh items-center justify-center px-4 text-slate-950">
        <div role="alert" className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
          <p className="text-2xl font-black">Couldn't open this screen</p>
          <p className="mt-3 text-sm leading-6 text-slate-700">
            The site may have updated while this tab was open. Reload to continue.
          </p>
          <button
            type="button"
            className="saints-focus mt-5 min-h-11 rounded-xl bg-saints-black px-5 font-bold text-white"
            onClick={() => window.location.reload()}
          >
            Reload page
          </button>
        </div>
      </main>
    );
  }
}
