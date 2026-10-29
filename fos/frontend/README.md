# FOS Frontend

React + TypeScript frontend for FOS.

## Required Runtime

- Node.js 22 or later
- npm 10 or later

The frontend has `engine-strict=true` in `.npmrc`, so dependency installation fails early when the local Node/npm version falls outside the supported range (Node 22+, npm 10+).

## Setup

```bash
nvm use
npm ci
```

If you do not use `nvm`, install Node.js 22 or later with your preferred version manager and confirm:

```bash
node --version
npm --version
```

## Local Development

```bash
npm run dev
```

The dev server listens on http://localhost:5173.

Optional video configuration:

```bash
VITE_BILIBILI_VIDEO_BVID=BVxxxxxxxxx
```

Leave `VITE_BILIBILI_VIDEO_BVID` empty to hide the landing page preview video.

## Test And Build Commands

```bash
npm run test:run
npm run build
npm run test:e2e:smoke
```

Use `npm ci`, not `npm install`, for reproducible dependency installs from `package-lock.json`.

## Which build to run

- `npm run build` — standalone/root-base build (`/` base; the FOS/auth
  standalone deployment). Asset refs come out as `/assets/…`.
- `npm run build:integrated` — the build GAWorld's console hosts. Uses the
  `integrated` mode (`.env.integrated` sets `FRONTEND_BASE_URL=/fos/`), so
  asset refs come out as `/fos/assets/…`. This is what `gaworld dashboard`
  expects in `fos/frontend/dist`; it validates that on startup and refuses to
  serve a standalone build. Cross-platform: no POSIX-only env syntax.
