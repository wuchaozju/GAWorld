import { NavBar, type NavBarVariant } from "./NavBar";
import { useThemeStore } from "../store/theme";

export function Layout({
  children,
  navVariant = "default",
}: {
  children: React.ReactNode;
  navVariant?: NavBarVariant;
}) {
  const isProduct = navVariant === "product";
  const mode = useThemeStore((state) => state.mode);
  const themeClass = mode === "dark" ? "is-dark" : "is-light";

  return (
    <div className={`app-container ${isProduct ? "app-container--product-shell" : ""} ${themeClass}`.trim()}>
      <NavBar variant={navVariant} />
      <main
        className={`app-main ${isProduct ? "app-main--product-shell" : "compact ss-workbench"} ${themeClass}`.trim()}
      >
        {children}
      </main>
    </div>
  );
}
