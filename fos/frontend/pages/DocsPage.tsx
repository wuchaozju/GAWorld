// frontend/pages/DocsPage.tsx
/**
 * Documentation page component.
 *
 * Displays documentation content with a sidebar navigation and
 * markdown rendering. Supports multiple languages and loads
 * markdown content dynamically based on current language.
 *
 * Exports: DocsPage component
 */

import React, { useEffect, useMemo, useRef, useState } from "react";
import { BookOpen, Download, ExternalLink } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { TitleCard } from "../components/TitleCard";
import { MarkdownRenderer } from "../components/MarkdownRenderer";
import { DocsSidebar } from "../components/DocsSidebar";
import { useTranslation } from "react-i18next";
import { resolveStaticAssetPath } from "../utils/assets";

// Import markdown files
import docsEn from "../docs/docs-en.md?raw";
import docsZh from "../docs/docs-zh.md?raw";

const DOC_IDS = [
  "getting-started",
  "llm-config",
  "creating-simulation",
  "scenario-guide",
  "agents",
  "running-analysis",
  "advanced-features",
] as const;

const DEFAULT_DOC_ID = "getting-started";
const SCENARIO_GUIDE_ID = "scenario-guide";

const scenarioGuideOutline = [
  { title: "目录", page: 1 },
  { title: "FOS模板的社会科学基础", page: 2 },
  { title: "囚徒困境（Prisoner's Dilemma）", page: 2 },
  { title: "性别战（Battle of the Sexes）", page: 3 },
  { title: "猎鹿博弈（Stag Hunt）", page: 5 },
  { title: "社会规范破坏（Social Norm Disruption）", page: 6 },
  { title: "政策意义侵蚀（Policy Meaning Erosion）", page: 8 },
  { title: "回声室（Echo Chamber）", page: 9 },
  { title: "资源稀缺（Resource Scarcity）", page: 11 },
  { title: "西湖益联保参保扩散（Xihu Yilianbao Enrollment Diffusion）", page: 12 },
  { title: "自由讨论（Open Discussion）", page: 13 },
  { title: "议事厅（Council Chamber）", page: 15 },
  { title: "网格世界（Grid World）", page: 16 },
  { title: "GAWorld 城市模拟（GAWorld City Simulation）", page: 17 },
  { title: "公共品博弈（Public Goods Game）", page: 19 },
  { title: "协调博弈（Coordination Game）", page: 20 },
  { title: "传染扩散（Contagion Spread）", page: 21 },
  { title: "自定义场景（Custom Scenario）", page: 23 },
];

function isDocId(docId: string | null): docId is (typeof DOC_IDS)[number] {
  return Boolean(docId && (DOC_IDS as readonly string[]).includes(docId));
}

function getDocSection(content: string, docId: string) {
  if (docId === SCENARIO_GUIDE_ID) return "";

  const titleMatch = content.match(/^# .+$/m);
  const sectionPattern = new RegExp(
    `<h2\\s+id=["']${docId}["'][^>]*>[\\s\\S]*?(?=\\n---\\n\\n<h2\\s+id=|\\n<h2\\s+id=|$)`,
  );
  const sectionMatch = content.match(sectionPattern);

  if (!sectionMatch) return content;

  return [titleMatch?.[0], sectionMatch[0].replace(/\n---\s*$/, "")].filter(Boolean).join("\n\n");
}

function ScenarioGuideViewer() {
  const { t } = useTranslation();
  const [selectedOutlineIndex, setSelectedOutlineIndex] = useState(0);
  const [isCompact, setIsCompact] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia("(max-width: 900px)").matches : false,
  );
  const page = scenarioGuideOutline[selectedOutlineIndex]?.page ?? 1;
  const pdfPath = resolveStaticAssetPath("/docs/fos-scenario-introduction.pdf");
  const pdfSrc = `${pdfPath}#page=${page}&view=FitH`;

  useEffect(() => {
    const mediaQuery = window.matchMedia("(max-width: 900px)");
    const updateLayout = () => setIsCompact(mediaQuery.matches);
    updateLayout();
    mediaQuery.addEventListener("change", updateLayout);
    return () => mediaQuery.removeEventListener("change", updateLayout);
  }, []);

  const shellStyles: React.CSSProperties = {
    display: "grid",
    gridTemplateColumns: isCompact ? "1fr" : "minmax(220px, 280px) minmax(0, 1fr)",
    gap: "1rem",
    height: isCompact ? "auto" : "calc(100vh - 13rem)",
    minHeight: isCompact ? "auto" : "34rem",
  };

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <section
        style={{
          border: "1px solid var(--ss-border)",
          borderRadius: "0.5rem",
          background: "var(--ss-page-surface)",
          padding: "1rem",
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "1rem" }}>
          <div>
            <h1 style={{ margin: 0, color: "var(--ss-heading)", fontSize: "1.5rem" }}>
              {t("pages.docsPage.scenarioGuideTitle")}
            </h1>
            <p style={{ margin: "0.5rem 0 0", color: "var(--ss-text-muted)", lineHeight: 1.6 }}>
              {t("pages.docsPage.scenarioGuideDescription")}
            </p>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", justifyContent: "flex-end" }}>
            <a
              href={pdfSrc}
              target="_blank"
              rel="noopener noreferrer"
              style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem", color: "var(--ss-link)" }}
            >
              <ExternalLink size={16} />
              {t("pages.docsPage.openPdf")}
            </a>
            <a
              href={pdfPath}
              download
              style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem", color: "var(--ss-link)" }}
            >
              <Download size={16} />
              {t("pages.docsPage.downloadPdf")}
            </a>
          </div>
        </div>
      </section>

      <div style={shellStyles}>
        <aside
          style={{
            overflow: "auto",
            border: "1px solid var(--ss-border)",
            borderRadius: "0.5rem",
            background: "var(--ss-surface)",
            padding: "0.75rem",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.45rem",
              color: "var(--ss-text-muted)",
              fontSize: "var(--ss-type-button)",
              fontWeight: 600,
              marginBottom: "0.75rem",
            }}
          >
            <BookOpen size={16} />
            {t("pages.docsPage.scenarioGuideToc")}
          </div>
          <div style={{ display: "grid", gap: "0.25rem" }}>
            {scenarioGuideOutline.map((item, index) => {
              const isActive = index === selectedOutlineIndex;
              return (
                <button
                  key={`${item.title}-${item.page}`}
                  type="button"
                  onClick={() => setSelectedOutlineIndex(index)}
                  style={{
                    border: "none",
                    borderRadius: "0.375rem",
                    background: isActive ? "var(--ss-info-600)" : "transparent",
                    color: isActive ? "var(--ss-neutral-0)" : "var(--ss-text)",
                    cursor: "pointer",
                    display: "flex",
                    gap: "0.5rem",
                    justifyContent: "space-between",
                    padding: "0.55rem 0.65rem",
                    textAlign: "left",
                  }}
                >
                  <span>{item.title}</span>
                  <span style={{ color: isActive ? "var(--ss-neutral-0)" : "var(--ss-text-muted)", whiteSpace: "nowrap" }}>
                    {t("pages.docsPage.pageLabel", { page: item.page })}
                  </span>
                </button>
              );
            })}
          </div>
        </aside>

        <iframe
          key={pdfSrc}
          src={pdfSrc}
          title={t("pages.docsPage.scenarioGuideTitle")}
          style={{
            width: "100%",
            height: isCompact ? "32rem" : "100%",
            border: "1px solid var(--ss-border)",
            borderRadius: "0.5rem",
            background: "var(--ss-page-surface)",
          }}
        />
      </div>
    </div>
  );
}

export function DocsPage() {
  const { t, i18n } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialDoc = isDocId(searchParams.get("doc")) ? searchParams.get("doc")! : DEFAULT_DOC_ID;
  const [currentDoc, setCurrentDocState] = useState<string>(initialDoc);
  const contentRef = useRef<HTMLDivElement | null>(null);

  // Get markdown content based on current language
  const markdownContent = useMemo(() => {
    return i18n.language.startsWith("zh") ? docsZh : docsEn;
  }, [i18n.language]);

  const selectedMarkdownContent = useMemo(() => {
    return getDocSection(markdownContent, currentDoc);
  }, [currentDoc, markdownContent]);

  useEffect(() => {
    const requestedDoc = searchParams.get("doc");
    if (isDocId(requestedDoc) && requestedDoc !== currentDoc) {
      setCurrentDocState(requestedDoc);
    }
  }, [currentDoc, searchParams]);

  useEffect(() => {
    contentRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, [currentDoc]);

  const setCurrentDoc = (docId: string) => {
    setCurrentDocState(docId);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("doc", docId);
    setSearchParams(nextParams, { replace: true });
  };

  const containerStyles: React.CSSProperties = {
    display: "flex",
    gap: "1.5rem",
    height: "100%",
  };

  const sidebarWrapperStyles: React.CSSProperties = {
    flexShrink: 0,
  };

  const contentStyles: React.CSSProperties = {
    flex: 1,
    overflow: "auto",
    padding: "0.5rem",
  };

  return (
    <div
      style={{
        height: "100%",
        overflow: "hidden",
        padding: "1rem 1.5rem",
        boxSizing: "border-box",
      }}
    >
      <TitleCard title={t("pages.docsPage.documentation")} />

      <div style={containerStyles}>
        <div style={sidebarWrapperStyles}>
          <DocsSidebar currentDoc={currentDoc} onDocChange={setCurrentDoc} />
        </div>

        <div ref={contentRef} style={contentStyles}>
          {currentDoc === SCENARIO_GUIDE_ID ? (
            <ScenarioGuideViewer />
          ) : (
            <MarkdownRenderer content={selectedMarkdownContent} />
          )}
        </div>
      </div>
    </div>
  );
}

export default DocsPage;
