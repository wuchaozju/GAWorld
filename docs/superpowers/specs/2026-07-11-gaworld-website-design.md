# GAWorld Website Design

## Goal

Create a bilingual Chinese/English public website for GAWorld that establishes research credibility while primarily converting AI developers and open-source contributors into GitHub visitors and first-time users.

The primary user journey is:

1. Understand GAWorld's differentiating value within the first viewport.
2. See credible technical and research capabilities.
3. Understand the simulator's core loop and architecture.
4. Copy the quick-start commands or open the GitHub repository.

The primary call to action is **View on GitHub**. The secondary call to action is **Run in one minute**.

## Audience

- Academic researchers working on multi-agent simulation, social behavior, urban governance, policy interventions, or complex systems.
- AI developers and open-source contributors evaluating agent frameworks, memory systems, social simulations, and LLM-driven applications.

## Product Direction

Use an immersive single-page project website rather than a paper-only project page or a documentation portal. The page combines academic credibility with a short, action-oriented developer path.

The visual concept is a **city-scale digital social laboratory**: a dark ink-blue canvas, cool cyan network traces, and sparse amber event nodes. The design should feel specific to GAWorld rather than like a generic gradient-heavy AI landing page.

## Information Architecture

The page contains the following sections in order:

1. **Hero** — bilingual value proposition, animated abstract city-agent network, GitHub button, and quick-start button.
2. **Credibility strip** — concise signals for multi-agent simulation, long-term memory, social networks, policy intervention, and closed-loop economy.
3. **Core loop** — perception, planning, action, reflection, and memory update.
4. **Capability matrix** — paired research and developer value for the major GAWorld subsystems.
5. **Simulation scenarios** — urban governance, social propagation, behavioral consistency, and complex-systems education.
6. **Quick start** — install and run commands with copy affordances.
7. **System architecture** — relationships among agents, environment, memory, economy, social network, and policy modules.
8. **Open-source action area** — GitHub, documentation, and local Dashboard entry points.
9. **Footer** — project description, repository link, and language switch. Show license or citation details only when the repository provides authoritative text.

All claims and commands must be grounded in the current repository README and source structure. Unsupported metrics or adoption claims must not be invented.

## Content and Localization

The interface supports immediate Chinese/English switching. Both languages use one shared, typed content structure with matching keys so that sections cannot silently diverge. The initial language may follow browser preference; the explicit user choice is stored locally and takes precedence on later visits.

The English and Chinese copy should be equivalent in meaning but idiomatic in each language. The site must not depend on machine translation at runtime.

## Visual System

- Background: deep ink/navy with subtle grid and spatial depth.
- Primary accent: cool cyan for relationships, routes, and active controls.
- Secondary accent: restrained amber for shocks, events, and highlights.
- Typography: clear, rational sans-serif families with compact English headings and comfortable Chinese line height.
- Illustration: lightweight CSS composition of city blocks, agent nodes, relationship lines, and event pulses. Avoid decorative model-authored SVG illustrations.
- Cards: restrained borders, slight translucency, and strong typographic hierarchy rather than heavy glass effects.

The abstract hero network should evoke a live simulation without implying that it is connected to real runtime data.

## Interaction Design

- Sticky or compact navigation scrolls to capabilities, architecture, and quick start.
- Language switching updates the page immediately and persists the choice locally.
- The hero network uses slow ambient motion and becomes static under `prefers-reduced-motion`.
- Quick-start commands have keyboard-accessible copy buttons with visible success feedback.
- Capability cards reveal concise research/developer context on hover and keyboard focus without hiding essential content.
- GitHub remains the visually dominant action throughout the page.
- Mobile layouts reduce decorative motion and visual density while retaining all core information.

## Technical Shape

Build the site as a dedicated Sites frontend surface in the repository, isolated from the Python simulator and the existing `site/` Dashboard, simulation viewer, and city-map tools. Preserve the repository's existing application surfaces.

The first release is a static, single-route website with no account system, durable database, uploads, or live simulation dependency. It uses structured local content, reusable presentational components, and minimal client state for language preference and copy feedback.

The deployment must use the Sites-compatible project structure and Cloudflare Worker-compatible ESM output supplied by the Sites starter.

## Responsive and Accessible Behavior

- No horizontal overflow at common phone, tablet, and desktop widths.
- Complex architecture content becomes a vertical module sequence on narrow screens.
- Every interactive element supports keyboard use and visible focus.
- Text and controls meet accessible contrast targets.
- Motion is nonessential and disabled or simplified when reduced motion is requested.
- Semantic landmarks and heading order support assistive navigation.

## Resilience

- If clipboard access fails, commands remain selectable and the interface gives a nonblocking manual-copy message.
- If local storage is unavailable, language switching still works for the current session.
- If animation support is limited, the hero renders as a static composition.
- External links use clear destinations; unavailable external content must not break the core page.

## Validation

Before publishing:

- Run the production build and resolve compilation failures.
- Confirm that all starter sample UI and metadata are removed.
- Verify that every main section has complete Chinese and English content.
- Confirm GitHub, navigation, quick-start, and copy interactions.
- Check desktop and mobile layout, focus visibility, contrast, and reduced-motion behavior.
- Create one bespoke social-preview image that matches the final site's palette, typography, and motifs; omit it if its text cannot be validated.

## Scope Boundaries

The first release does not include live simulation telemetry, hosted documentation search, user accounts, community feeds, CMS editing, blog content, or an embedded runnable GAWorld instance. These can be considered after the core website has proven useful.
