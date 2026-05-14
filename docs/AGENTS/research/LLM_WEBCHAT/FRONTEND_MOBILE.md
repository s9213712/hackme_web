# Frontend And Mobile Responsive Design

## WebChat

Files:

```text
public/js/ai_chat.js
public/css/ai_chat.css
```

Requirements:

1. Add WebChat tab.
2. Support normal chat.
3. Show tool-call summaries when present.
4. Show provider: Ollama / LM Studio.
5. Show provider connection status.
6. Show loading / error / retry states.
7. Do not store secrets in frontend state.
8. Mobile usable.

## Agent Console

Files:

```text
public/js/ai_agent.js
public/css/ai_agent.css
```

Requirements:

1. Left: task input.
2. Middle: agent response and step plan.
3. Right: tool-call log, permission, risk level.
4. Each action shows tool name, risk level, read/write, expected changes, status.
5. Write action shows preview.
6. High/critical action shows red warning and manual confirmation area.
7. User can cancel pending action.
8. Mobile uses single-column cards.

## Shared Responsive Layer

Files:

```text
public/css/responsive.css
public/js/mobile-nav.js
```

Breakpoints:

```text
mobile: <= 640px
tablet: 641px-1024px
desktop: >= 1025px
```

General requirements:

- No horizontal page scroll.
- 360px-430px mobile widths work.
- 768px-1024px tablets work.
- Tap target at least 44x44px.
- Tables, cards, sidebar, modal, toast, dropdown, terminal, file list adapt.

## Sidebar

Desktop:

- fixed left sidebar
- main content uses remaining width

Mobile:

- sidebar becomes off-canvas drawer
- top-left menu button
- overlay click closes drawer
- ESC closes drawer
- tab switch closes drawer
- body gets `nav-open`
- no content overlap or horizontal scroll

## Tables

Targets:

- admin users
- logs
- transactions
- points ledger
- snapshot list
- files list
- agent actions
- tool calls

Rules:

- Desktop keeps table.
- Mobile uses card list or horizontal wrapper.
- Important fields show in card.
- Secondary fields use `details/summary`.
- Action buttons become full-width or icon + label.

## Modal

- Inputs width 100%.
- Font size >= 16px.
- Mobile modal becomes bottom sheet or full-screen.
- Max height 90dvh.
- Body scrolls vertically.
- Submit/cancel buttons full-width on mobile.

## WebChat / Agent Mobile

- Single-column layout.
- Input visible near bottom.
- Tool-call detail collapsible.
- High-risk confirmation cannot overflow screen.
- Plan steps use cards.
- Audit detail uses `details/summary`.
- Chat message wraps.
- Code block can scroll horizontally without page-level horizontal scroll.
