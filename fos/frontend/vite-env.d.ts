/// <reference types="vite/client" />

/**
 * TypeScript declarations for Vite-specific imports.
 *
 * Declares module types for importing markdown files as raw strings.
 */

declare module "*.md?raw" {
  const content: string;
  export default content;
}

declare module "*.md" {
  const content: string;
  export default content;
}
