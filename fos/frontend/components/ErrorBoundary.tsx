/**
 * This file keeps a broken page from leaving the website empty.
 *
 * ErrorBoundary catches page drawing errors, shows what happened, and lets the person retry or reload.
 */

import React from "react";

import i18n from "../i18n";

interface Props {
  children: React.ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends React.Component<Props, State> {
  public state: State = { hasError: false, error: null };

  public static getDerivedStateFromError(error: unknown): State {
    return {
      hasError: true,
      error: error instanceof Error ? error : new Error(String(error)),
    };
  }

  public componentDidCatch(error: Error, info: React.ErrorInfo): void {
    console.error("Page rendering failed", error, info);
  }

  private retry = (): void => {
    this.setState({ hasError: false, error: null });
  };

  private reload = (): void => {
    window.location.reload();
  };

  public render(): React.ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div className="route-error" role="alert">
        <h1>{i18n.t("components.errorBoundary.title")}</h1>
        <p className="route-error__message">{this.state.error?.message}</p>
        <p>{i18n.t("components.errorBoundary.instructions")}</p>
        <div className="route-error__actions">
          <button type="button" className="ss-button-secondary" onClick={this.retry}>
            {i18n.t("components.errorBoundary.retry")}
          </button>
          <button type="button" className="ss-button" onClick={this.reload}>
            {i18n.t("components.errorBoundary.reload")}
          </button>
        </div>
      </div>
    );
  }
}
