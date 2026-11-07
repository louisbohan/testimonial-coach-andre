# Coach Andre — Testimonial Page (Minimal Variant)

**Purpose:** One screen that gets a client to answer two questions and send it in under 90 seconds.
**File:** `minimal/index.html` (13.6 KB, single file, no build step) + `hero.jpg` + `wrangler.jsonc`

---

## What It Is

A stripped-down alternative to the full testimonial page. Same job — collect before/after stories — but with the guardrails UI, multi-step flow, and toolkit removed. Everything on one scrollable page.

Deploy target: Cloudflare Workers static assets (`testimonial-minimal`, compatibility date 2026-01-01).

---

## Structure (top to bottom)

1. **Header** — kicker "Coach Andre · San Francisco → Reno", headline *"Share what changed for you."*, sub-line "Two questions, 60–90 seconds. Audio or written — whatever's easier." Hero photo (3:2, rounded, bordered).
2. **The two questions** — two textareas:
   - 1 — Where were you before we started?
   - 2 — What's different now?
   - Optional one-liner field ("I came for my knee. I stayed for everything else.")
3. **Your voice** — MediaRecorder in-browser recording (5-minute hard cap with live timer), or upload an audio/video clip from phone. In-page playback before sending.
4. **Who you are** — Display name, optional context line ("Trained 4 years · 62"), optional training photo upload.
5. **Send** — Primary "Send it to Coach Andre" (Formspree), plus fallbacks: "Copy my words" (clipboard, with execCommand fallback) and "Text instead" (sms: deep link).
6. **Footer** — "Nothing gets posted without you saying yes — just reply and ask."

---

## Design System

| Token | Light | Dark |
|---|---|---|
| Background | `#FCFAF7` cream | `#121614` |
| Surface | `#FFFFFF` | `#1A201D` |
| Field | `#F5F2EC` | `#222A26` |
| Ink | `#1B2420` | `#EDE9E1` |
| Muted | `#6A736C` | `#A2ABA4` |
| Line | `#E4DFD4` | `#2C3630` |
| Moss (primary) | `#2F4A3E` | `#8FB09E` |
| Clay (record/accent) | `#C25E3A` | `#E08A66` |

- **Type:** Lora (serif) for h1/h2, Public Sans for body. h1 clamps 30→42px.
- **Layout:** Single column, max-width 660px, 22px gutters.
- 14px radius on photo, rec panel, and inputs. 10px on buttons/fields.
- Auto dark mode via `prefers-color-scheme`. Primary button inverts in dark.
- No icons, no illustration, no animation beyond focus rings.

---

## Behavior Notes

- **Zero required permissions up front.** Mic prompt fires only on Record tap.
- **Recording failure is graceful:** blocked mic → "upload a clip" message; unsupported browser → same.
- **Consent is a fixed safe default:** `"Ask me first before posting"`. No tri-state UI (this was deliberately removed from the minimal version). Nothing auto-publishes.
- **Submission payload:** name, context, q1, q2, oneLiner, consent, format, plaintext summary, recording blob, photo blob → Formspree `xjyylrzn`.
- **Validation:** name required; at least one answer or one clip required.
- **Failure path:** shows error, re-enables button, points at Copy / Text fallbacks.

---

## Contacts Baked In

- Phone: 415-215-1088 (`sms:` link)
- Email: andreluiorozco@gmail.com
- Endpoint: `https://formspree.io/xjyylrzn`

---

## What Was Cut vs. Full Version

Removed: multi-section guardrail flow, tri-state consent selector, scope-of-practice guidance, testimonial toolkit, review checklist UI, ~1 MB of inline assets.
Kept: the two core questions, voice capture, attribution, photo, three ways to submit.

Trade-off: faster completion and less friction, but fewer structured prompts — expect shorter, less polished raw material.
