/**
 * This file shows the language button in the top bar.
 * LanguageSwitcher opens the menu and asks the app to swap languages when someone picks one.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Languages } from "lucide-react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";

import { setLanguage } from "../i18n";

export type LanguageSwitcherVariant = "default" | "product";

export function LanguageSwitcher({ variant = "default" }: { variant?: LanguageSwitcherVariant }) {
  const { i18n: i18 } = useTranslation();
  const current = i18.language.startsWith("zh") ? "zh" : "en";
  const [open, setOpen] = useState(false);
  const label = current === "zh" ? "中文" : "EN";

  return (
    <div className="lang-switch">
      <DropdownMenu.Root open={open} onOpenChange={setOpen}>
        <DropdownMenu.Trigger asChild>
          <button
            type="button"
            className={`lang-button ${variant === "product" ? "lang-button--product" : ""}`}
            aria-haspopup="menu"
            aria-expanded={open}
            aria-label={label}
            title={label}
          >
            {variant === "product" ? (
              <>
                <Languages size={15} strokeWidth={2} />
                <span className="lang-button-label">{label}</span>
                <span className="lang-button-caret">▾</span>
              </>
            ) : (
              <>
                🌐 {label} <span style={{ marginLeft: 6, color: "var(--muted)" }}>▾</span>
              </>
            )}
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content
            className="card select-dropdown"
            align="end"
            sideOffset={4}
            style={{ minWidth: "var(--radix-popper-anchor-width)" }}
          >
            <DropdownMenu.Item
              className={`menu-item ${current === "en" ? "active" : ""}`}
              onSelect={() => { void setLanguage("en"); }}
            >
              EN
            </DropdownMenu.Item>
            <DropdownMenu.Item
              className={`menu-item ${current === "zh" ? "active" : ""}`}
              onSelect={() => { void setLanguage("zh"); }}
            >
              中文
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
    </div>
  );
}
