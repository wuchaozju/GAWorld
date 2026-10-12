import { ReactNode } from "react";

export function TitleCard({
  title,
  subtitle,
  actions,
  center,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  center?: ReactNode;
}) {
  const hasCenter = Boolean(center);
  return (
    <div
      className="panel title-card"
      style={{
        marginBottom: "0.75rem",
        display: "grid",
        alignItems: "center",
        gap: "var(--ss-space-2)",
        gridTemplateColumns: hasCenter ? "1fr minmax(0, 2fr) auto" : "1fr auto",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <h1 style={{ margin: 0 }}>{title}</h1>
        {subtitle && <div className="panel-subtitle">{subtitle}</div>}
      </div>
      {hasCenter && (
        <div style={{ justifySelf: "center", width: "100%", maxWidth: 560 }}>{center}</div>
      )}
      {actions && (
        <div style={{ justifySelf: "end", display: "flex", gap: "var(--ss-space-2)" }}>{actions}</div>
      )}
    </div>
  );
}

