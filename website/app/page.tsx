"use client";

import { useEffect, useState } from "react";
import { CONTENT, type Locale, REPOSITORY_URL } from "./content";

const sectionIds = ["capabilities", "architecture", "quick-start"] as const;

export default function Home() {
  const [locale, setLocale] = useState<Locale>("zh");
  const [copyStatus, setCopyStatus] = useState<Record<number, string>>({});
  const copy = CONTENT[locale];

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      try {
        const saved = localStorage.getItem("gaworld-locale") as Locale | null;
        const preferred = navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
        setLocale(saved === "zh" || saved === "en" ? saved : preferred);
      } catch {
        setLocale("zh");
      }
    });
    return () => cancelAnimationFrame(frame);
  }, []);

  function toggleLocale() {
    const next = locale === "zh" ? "en" : "zh";
    setLocale(next);
    document.documentElement.lang = next === "zh" ? "zh-CN" : "en";
    try { localStorage.setItem("gaworld-locale", next); } catch { /* session-only fallback */ }
  }

  async function copyCommand(command: string, index: number) {
    try {
      await navigator.clipboard.writeText(command);
      setCopyStatus({ ...copyStatus, [index]: copy.copied });
    } catch {
      setCopyStatus({ ...copyStatus, [index]: copy.manual });
    }
  }

  return (
    <div className="site-shell">
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="topbar">
        <a className="brand" href="#top" aria-label="GAWorld home"><span className="brand-mark">G</span><span>GAWorld</span></a>
        <nav aria-label="Primary navigation">
          {copy.nav.map((item, index) => <a key={item} href={`#${sectionIds[index]}`}>{item}</a>)}
        </nav>
        <div className="header-actions">
          <button className="language" onClick={toggleLocale} aria-label={`Switch language to ${copy.langName}`}>{copy.langName}</button>
          <a className="button button-small" href={REPOSITORY_URL} target="_blank" rel="noreferrer">GitHub ↗</a>
        </div>
      </header>

      <main id="main">
        <section className="hero section" id="top">
          <div className="hero-copy">
            <p className="eyebrow">{copy.eyebrow}</p>
            <h1>{copy.title}</h1>
            <p className="lead">{copy.intro}</p>
            <div className="hero-actions">
              <a className="button" href={REPOSITORY_URL} target="_blank" rel="noreferrer">{copy.github} <span>↗</span></a>
              <a className="text-link" href="#quick-start">{copy.run} <span>↓</span></a>
            </div>
          </div>
          <div className="city-stage" aria-label="Abstract multi-agent city network">
            <div className="city-grid" />
            {[0,1,2,3,4,5,6,7].map((node) => <span className={`agent-node node-${node}`} key={node} />)}
            <span className="route route-a" /><span className="route route-b" /><span className="route route-c" />
            <div className="city-readout"><span>SIM / DAY 04</span><strong>1,000</strong><small>ACTIVE AGENTS</small></div>
          </div>
        </section>

        <div className="signal-strip" aria-label="Key capabilities">{copy.signals.map((signal) => <span key={signal}>{signal}</span>)}</div>

        <section className="section loop-section">
          <div className="section-heading"><p className="index">01 / CORE LOOP</p><h2>{copy.loopTitle}</h2><p>{copy.loopBody}</p></div>
          <ol className="loop">{copy.loop.map((step, index) => <li key={step}><span>0{index + 1}</span><strong>{step}</strong>{index < copy.loop.length - 1 && <i>→</i>}</li>)}</ol>
        </section>

        <section className="section" id="capabilities">
          <div className="section-heading"><p className="index">02 / CAPABILITIES</p><h2>{copy.capabilitiesTitle}</h2><p>{copy.capabilitiesBody}</p></div>
          <div className="capability-grid">{copy.capabilities.map((item, index) => <article className="capability" key={item[0]}><span className="card-number">0{index + 1}</span><h3>{item[0]}</h3><div><small>{copy.research}</small><p>{item[1]}</p></div><div><small>{copy.developer}</small><p>{item[2]}</p></div></article>)}</div>
        </section>

        <section className="section scenario-section">
          <div className="section-heading"><p className="index">03 / EXPERIMENTS</p><h2>{copy.scenariosTitle}</h2></div>
          <div className="scenario-grid">{copy.scenarios.map((item, index) => <article key={item[0]}><span>{String(index + 1).padStart(2, "0")}</span><h3>{item[0]}</h3><p>{item[1]}</p></article>)}</div>
        </section>

        <section className="section architecture" id="architecture">
          <div className="section-heading"><p className="index">04 / ARCHITECTURE</p><h2>{copy.architectureTitle}</h2><p>{copy.architectureBody}</p></div>
          <div className="architecture-map"><div className="architecture-core">GAWorld<br/><small>SIMULATION KERNEL</small></div>{copy.modules.map((module) => <article key={module[0]}><h3>{module[0]}</h3><p>{module[1]}</p></article>)}</div>
        </section>

        <section className="section quick-start" id="quick-start">
          <div className="quick-copy"><p className="index">05 / QUICK START</p><h2>{copy.quickTitle}</h2><p>{copy.quickBody}</p></div>
          <div className="terminal"><div className="terminal-bar"><span /><span /><span /><b>terminal</b></div>{copy.commands.map((command, index) => <div className="command" key={command}><span className="prompt">$</span><code>{command}</code><button onClick={() => copyCommand(command, index)}>{copy.copy}</button><span className="copy-status" aria-live="polite">{copyStatus[index]}</span></div>)}</div>
        </section>

        <section className="section final-cta"><p className="eyebrow">{copy.ctaEyebrow}</p><h2>{copy.ctaTitle}</h2><p>{copy.ctaBody}</p><div className="hero-actions"><a className="button" href={REPOSITORY_URL} target="_blank" rel="noreferrer">{copy.github} ↗</a><a className="text-link" href={`${REPOSITORY_URL}#quickstart`} target="_blank" rel="noreferrer">{copy.docs}</a></div></section>
      </main>
      <footer><a className="brand" href="#top"><span className="brand-mark">G</span><span>GAWorld</span></a><p>Generative multi-agent simulation for urban social behavior experiments.</p><button className="language" onClick={toggleLocale}>{copy.langName}</button></footer>
    </div>
  );
}
