import { Orbit } from "lucide-react";

type BrandLogoLayout = "inline" | "stacked";

interface BrandLogoProps {
  subtitle?: string;
  layout?: BrandLogoLayout;
  titleClassName?: string;
  className?: string;
}

export function BrandLogo({
  subtitle,
  layout = "inline",
  titleClassName = "",
  className = "",
}: BrandLogoProps) {
  return (
    <span className={`brand-logo brand-logo--${layout} ${className}`.trim()}>
      <span className="brand-logo__mark" aria-hidden="true">
        <Orbit size={18} strokeWidth={1.95} />
      </span>

      <span className="brand-logo__text">
        <span className={`brand-logo__title ${titleClassName}`.trim()}>FOS</span>
        {subtitle ? <span className="brand-logo__subtitle">{subtitle}</span> : null}
      </span>
    </span>
  );
}

export default BrandLogo;