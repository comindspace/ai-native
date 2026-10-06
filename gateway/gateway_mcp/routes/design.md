# Gateway admin design

Gateway admin starts with «Команда и AI»: people, their observed clients,
explicit favorite skills and autonomous agents. The main directory and agent
rail come before skill rankings and activity charts. «Использование AI» contains
the detailed analytics. «Состояние шлюза» belongs to administration.

## Visual system

- Use the coMind identity: near-black text, white and cool-neutral surfaces,
  restrained violet accent. The accent marks selection and primary actions;
  risk and success states use semantic colors instead.
- Use a 4 px spacing rhythm. Showcase headings use a restrained 32–48 px display
  scale and 16 px card radius; administrative forms remain compact. Alternate
  a metric strip, an activity chart and directory cards to establish hierarchy.
  Initial avatars and client abbreviations identify entries without external
  assets. Avoid decorative illustrations, gradients and nested cards.
- Use the shared tokens and components in `admin_ui.py`. Route-specific CSS may
  add layout but must reuse those tokens.

## Interaction

- Make the overview useful with partial data. A failed source shows a local
  recovery state and never replaces the whole dashboard.
- Every metric names its source and time window. Missing values are not zero.
- The user selected «Команда и AI» as the default and removed deals, projects and
  contract economics from the overview and visible metrics. Those pages must
  not load Tracker or CRM business data, including through legacy section URLs.
- Put actionable items ahead of exhaustive tables; link to the existing detail
  pages for investigation and changes.
- Keep the full desktop navigation and a compact native mobile disclosure.
  All controls are keyboard accessible and have visible focus states.
- AI directory counts describe Gateway accounts and telemetry, not the HR roster
  or installed software. Favorites are explicit personal choices. Never infer
  agent autonomy from a runtime name or an online state from last activity.
- Keep preferences self-service and autonomous source assignment in the admin
  catalog. A source assignment classifies the selected period using the current
  mapping; the form explains this before saving.
- Validate showcase layouts at 320, 375, 414, 768 and desktop widths. No motion
  is required; existing reduced-motion behavior applies to hover transitions.
