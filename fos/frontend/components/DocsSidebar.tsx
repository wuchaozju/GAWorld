/**
 * Documentation sidebar component.
 *
 * Provides navigation for the documentation page with a list of
 * available documents. Uses i18n for all labels and highlights
 * the currently active document.
 *
 * Exports: DocsSidebar component
 */

import React from "react";
import { useTranslation } from "react-i18next";

export interface DocItem {
  id: string;
  translationKey: string;
}

export interface DocsSidebarProps {
  /** Currently selected document ID */
  currentDoc: string;
  /** Callback when document selection changes */
  onDocChange: (docId: string) => void;
  /** Optional CSS class name */
  className?: string;
}

const sidebarStyles: React.CSSProperties = {
  backgroundColor: "var(--ss-surface)",
  border: "1px solid var(--ss-border)",
  borderRadius: "0.5rem",
  padding: "1rem",
  minWidth: "200px",
};

const titleStyles: React.CSSProperties = {
  fontSize: "var(--ss-type-button)",
  fontWeight: "600",
  color: "var(--ss-text-muted)",
  textTransform: "uppercase",
  letterSpacing: "0.05em",
  marginBottom: "0.75rem",
};

const listStyles: React.CSSProperties = {
  listStyle: "none",
  padding: 0,
  margin: 0,
};

const getItemStyles = (isActive: boolean): React.CSSProperties => ({
  padding: "0.625rem 0.75rem",
  marginBottom: "0.25rem",
  borderRadius: "0.375rem",
  cursor: "pointer",
  transition: "all 0.15s ease",
  fontSize: "var(--ss-type-body)",
  backgroundColor: isActive ? "var(--ss-info-600)" : "transparent",
  color: isActive ? "var(--ss-neutral-0)" : "var(--ss-text-muted)",
  fontWeight: isActive ? "500" : "400",
});

/**
 * DocsSidebar component for documentation navigation
 */
export function DocsSidebar({ currentDoc, onDocChange, className = "" }: DocsSidebarProps) {
  const { t } = useTranslation();

  const docItems: DocItem[] = [
    { id: "getting-started", translationKey: "pages.docsPage.gettingStarted" },
    { id: "llm-config", translationKey: "pages.docsPage.llmConfig" },
    { id: "creating-simulation", translationKey: "pages.docsPage.creatingSimulation" },
    { id: "scenario-guide", translationKey: "pages.docsPage.scenarioGuide" },
    { id: "agents", translationKey: "pages.docsPage.agents" },
    { id: "running-analysis", translationKey: "pages.docsPage.runningAnalysis" },
    { id: "advanced-features", translationKey: "pages.docsPage.advancedFeatures" },
  ];

  return (
    <div className={`docs-sidebar ${className}`} style={sidebarStyles}>
      <div style={titleStyles}>{t("pages.docsPage.documents")}</div>
      <ul style={listStyles}>
        {docItems.map((item) => {
          const isActive = currentDoc === item.id;
          return (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => onDocChange(item.id)}
                style={{
                  ...getItemStyles(isActive),
                  width: "100%",
                  border: "none",
                  textAlign: "left",
                }}
                onMouseEnter={(e) => {
                  if (!isActive) {
                    e.currentTarget.style.backgroundColor = "var(--ss-border)";
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isActive) {
                    e.currentTarget.style.backgroundColor = "transparent";
                  }
                }}
              >
                {t(item.translationKey)}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default DocsSidebar;
