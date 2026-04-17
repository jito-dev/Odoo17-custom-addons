# Card Collector Module

## What the Module Does

A Pokemon-style collectible card application. Users with the **Card Collector User** role create collectible cards with AI-generated artwork (via Google Nano Banana / Gemini API). Cards can be shared publicly via unique links. The website features a public gallery of shared cards and a personal collection page for logged-in users. Cards have holographic shimmer effects, 3D flip animations, silver metallic border, and a configurable **Card Back** image (default per user, with per-card override).

## Main Models

### `card.card` (models/card_card.py)
- **name**: Card title (Char, required)
- **description**: Card description shown on back (Text)
- **image**: AI-generated front artwork (Image, max 1024x1024)
- **user_prompt**: Prompt describing what to generate (Text)
- **user_id**: Card owner (Many2one to res.users)
- **is_shared**: Whether the card has a public URL (Boolean)
- **access_token**: UUID token for public URL (Char, auto-generated)
- **share_url**: Full public URL (Char, computed)
- **ai_generation_status**: draft / generating / done / failed (Selection)
- **back_image**: Optional per-card back artwork override (Image)
- **back_user_prompt**: Prompt for the per-card back image (Text)
- **back_ai_status**: AI status for back generation (Selection)

### `card.back` (models/card_back.py) — one record per user
- **user_id**: Owner (Many2one, unique)
- **image**: Default back artwork for all the user's cards
- **user_prompt**: Back image prompt
- **ai_generation_status**: AI status for the default back

### `res.config.settings` (models/res_config_settings.py)
Inherits res.config.settings with:
- **card_collector_api_key**: Google AI API key
- **card_collector_master_prompt**: Master style prompt for card fronts
- **card_collector_model**: Which Nano Banana model to use

System parameter `card_collector.back_master_prompt` (optional) tunes the
master prompt for back-side generation.

## Views

### Backend
- **Cards form**: title, front image, description tab, AI prompt tab, **Card Back tab** (per-card override + generate/clear buttons), share toggle with copy URL
- **Cards tree/kanban**: Name, owner, AI status, shared
- **Card Back form**: User-scoped; generate default back artwork from a prompt

### Website Templates
- **card_gallery**: Grid of cards with flip animation (used for `/cards` and `/cards/my`). Back face layers the card's effective back image behind a translucent dark panel holding title + description.
- **shared_card_page**: Single card with entrance animation for shared link

## Controllers (controllers/main.py)

- `GET /cards` (auth: public) — Public gallery of shared cards
- `GET /cards/my` (auth: user) — Personal collection; redirects to `/cards` if the user lacks the Card Collector User role
- `GET /cards/share/<id>/<token>` (auth: public) — Single shared card with token validation
- `GET /cards/back/<id>` (auth: public) — Effective back image for a card. Resolves the per-card `back_image` first, then falls back to the owner's `card.back.image`. Returns 404 if neither exists or the requester is not allowed (card must be shared, or requester must be the owner).

## Business Logic

- **AI Generation**: `generate_image_with_gemini(env, prompt, is_back)` is a module-level helper in `card_card.py`. Both `card.card.action_generate_image()` (front) and `card.card.action_generate_back_image()` / `card.back.action_generate_image()` (back) use it. It fetches the API key, master prompt and model from `ir.config_parameter`, then calls `client.models.generate_content(...)` with `response_modalities=['TEXT', 'IMAGE']` and returns base64 PNG bytes.
- **Back image resolution**: Per-card `back_image` takes priority, else fall back to the owner's default `card.back.image`. Handled in the `/cards/back/<id>` controller — templates just point `<img>` at that URL.
- **Sharing**: `action_toggle_share()` generates a UUID on first share. Token validated with `consteq()` for timing-attack safety.
- **Security role**: The `group_card_user` role gates the backend menu, all model access, and the `/cards/my` website route. Internal users do NOT get it by default — admins grant it via Settings > Users.

## Menus

- **Card Collector** (app root) — visible only to `group_card_user`
  - **Cards** — list/kanban/form of `card.card`
  - **Card Back** — server action that opens (or creates) the current user's `card.back` record

## Patterns and Constraints

- **Click UX**: clicking the card opens the fullscreen modal by default (which shows the front image plus title & description). The dedicated flip button (refresh icon, top-right) performs the 3D flip + zoom and reveals only the back image. Clicking a flipped card un-flips it.
- CSS-only holographic effects — no external JS libraries
- 3D card flip via CSS `transform: rotateY(180deg)` with `backface-visibility: hidden`
- Silver spinning conic gradient border shared by all cards
- Card back face shows **only** the back image (`position: absolute`, `object-fit: cover`, filling the frame interior). No title or description text is rendered on the back — description lives on the card wrapper as a `data-description` attribute and is injected into the fullscreen modal by the widget.
- Record rule on `card.back` restricts access to each user's own row; public/portal access to back images is done via sudo in the controller after verifying the parent card is shared.
- Python dependency: `google-genai` package required for AI generation
