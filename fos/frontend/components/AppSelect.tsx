import * as Select from "@radix-ui/react-select";
import { ReactNode } from "react";

type Option = { value: string; label: string };

export function AppSelect({
  options,
  value,
  placeholder,
  onChange,
  size = "normal",
}: {
  options: Option[];
  value: string;
  placeholder?: string;
  onChange: (value: string) => void;
  size?: "normal" | "small";
}) {
  const label = value || placeholder || (options[0]?.label ?? "");
  const triggerClass = `input fancy-select-trigger${size === "small" ? " small" : ""}`;

  return (
    <Select.Root value={value} onValueChange={onChange}>
      <Select.Trigger className={triggerClass} aria-label={placeholder || "select"} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--ss-space-2)' }}>
        <Select.Value placeholder={label} />
        <span style={{ color: 'var(--ss-text-muted)' }}>▾</span>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content
          className={`card select-dropdown${size === 'small' ? ' small' : ''}`}
          position="popper"
          sideOffset={4}
          style={{ width: 'var(--radix-select-trigger-width)' }}
        >
          <Select.Viewport style={{ display: 'grid', gap: 3 }}>
            {options.map((opt) => (
              <Select.Item key={opt.value} value={opt.value} className="select-option" style={{ textAlign: 'left', border: 'none', padding: '0.2rem 0.32rem', borderRadius: 8, cursor: 'pointer' }}>
                <Select.ItemText>{opt.label}</Select.ItemText>
              </Select.Item>
            ))}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  );
}
