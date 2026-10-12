import React from "react";
import { ChevronDown } from "lucide-react";

interface CollapsibleInsightSectionProps {
  title: string;
  subtitle?: string;
  badge?: React.ReactNode;
  defaultOpen?: boolean;
  open?: boolean;
  onToggle?: () => void;
  children: React.ReactNode;
  tone?: "details" | "metrics" | "logs" | "outputs";
}

export const CollapsibleInsightSection: React.FC<CollapsibleInsightSectionProps> = ({
  title,
  subtitle,
  badge,
  defaultOpen = false,
  open,
  onToggle,
  children,
  tone = "details",
}) => {
  const [internalOpen, setInternalOpen] = React.useState(defaultOpen);
  const resolvedOpen = open ?? internalOpen;

  const handleToggle = () => {
    if (onToggle) {
      onToggle();
      return;
    }
    setInternalOpen(!resolvedOpen);
  };

  return (
    <section className={`ss-insight-section ss-insight-section--${tone}${resolvedOpen ? " is-open" : ""}`}>
      <button type="button" onClick={handleToggle} className="ss-insight-section__summary">
        <div className="ss-insight-section__copy">
          <div className="ss-insight-section__title-row">
            <strong>{title}</strong>
            {badge ? <span className="ss-insight-section__badge">{badge}</span> : null}
          </div>
          {subtitle ? <span>{subtitle}</span> : null}
        </div>
        <ChevronDown
          size={16}
          className={`ss-insight-section__chevron${resolvedOpen ? " is-open" : ""}`}
        />
      </button>

      {resolvedOpen ? <div className="ss-insight-section__body">{children}</div> : null}
    </section>
  );
};

export default CollapsibleInsightSection;
