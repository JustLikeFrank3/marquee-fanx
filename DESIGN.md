# Marquee design brief

Status: proposed design, September 7, 2026. No implementation or live API access verified yet.

## Product

Help a fan find a night out, compare options, explore the venue, and understand the evidence behind a recommendation. Independent portfolio demonstration, not affiliated with SeatGeek.

Audience: fans first; recruiters can inspect the engineering through an expandable evidence panel. The complete basic flow works in an ordinary browser. Agent tools enhance the same experience.

## Visual direction

Contemporary concert-poster typography, warm ivory background, near-black text, orange accents, generous spacing. Event artwork provides variety. Use accessible contrast, visible focus, semantic controls, and reduced-motion support. Never use generated imagery as a real seat preview.

## Main flow and layout

1. Header: Marquee wordmark, short purpose statement, subtle agent capability indicator.
2. Find your night: request field plus explicit city, dates, budget, and party size controls. Default city Atlanta; example prompts help users start. Natural-language execution requires an actual agent/model integration; do not simulate it with canned results.
3. Results: event artwork when available, title, venue/city, local date/time, aggregate price statistics, fetch time, and compare selection. Up to three events can be compared.
4. Event detail: desktop split panel with event facts and a large venue/section preview area. Mobile stacks the preview below the facts. Opening details preserves search state.
5. Recommendation: a concise explanation grounded in event-specific fields, estimated party cost, and an expandable evidence report.
6. Footer: SeatGeek attribution, independent-project notice, repository and engineering explanation.

## Seat View integration

User priority: include SeatGeek's seat-view preview experience if supported access is available.

Public documentation reviewed so far does not establish a public Seat View image API or supported embed. Being signed into the developer platform does not establish entitlement to those assets. Confirm documented access and permitted display before implementing native previews.

Preview states:

- Available: display authorized imagery or a supported interactive viewer with venue, section, source attribution, and any supplied configuration context. Offer section selection only when supplied by the provider.
- External only: show an `Explore on SeatGeek` action using the API-returned event URL. Explain that seating maps and previews may be available there; do not guarantee coverage or fabricate section deep links.
- Unavailable: explain that a preview is unavailable for this event. Preserve event discovery and comparison.
- Loading/error: maintain panel dimensions, expose retry where appropriate, and retain the external event link.

Label imagery as a representative section view unless the source explicitly supports a more precise claim. A preview does not prove ticket availability, an unobstructed view, adjacent seats, or a price for that section. Do not scrape or reverse-engineer private endpoints to supply this feature.

Keep the provider boundary separate from event search so supported preview access can be added without replacing the core flow.

## Evidence and pricing

Bind supported claims to event ID, evidence ID, field, and retrieval time. Never validate Event A's price using Event B's data. Generate verified recommendations from structured facts. Arbitrary prose checking has explicit coverage limits; finding no recognized claims is not verification.

Aggregate lowest price multiplied by party size is an estimate, not a confirmed multi-ticket offer. Null prices mean price unavailable; zero listings is a separate fact. Preserve TBD dates/times. Seat-view metadata, when available, is separate evidence from ticket inventory and pricing.

The evidence panel shows checked facts, unsupported claims, and freshness. A deliberate false-claim example demonstrates failure without inserting invented information into real recommendations.

## Interaction states

- Empty: concise explanation and editable search constraints.
- API access missing: explain configuration requirement; explicitly label any sample dataset.
- Rate limit or upstream failure: actionable status and retry; never silently substitute fabricated live data.
- Expired evidence: require refresh before a new verified recommendation.
- Unsupported browser agent API: regular UI remains usable.
- Keyboard: dialogs trap focus and return it to the trigger; Escape closes; comparison controls expose selection state.
- Mobile: single-column cards, stacked comparison content, no horizontal page overflow.

## Delivery sequence

1. Verify authenticated event API access and investigate preview entitlement/documentation.
2. Build search, event detail, comparison, and preview capability states.
3. Add event-bound verification and budget estimates with planted false-claim tests.
4. Add agent integration, verify browser behavior, and deploy on the user's Azure subscription.
5. Record the real flow and failure case for the application.

## Research

- SeatGeek announced Ask SeatGeek on August 26, 2026. Its described experience combines conversational search, maps, view-from-seat imagery, and inventory. This is a product reference, not proof that its underlying APIs are publicly available: https://seatgeek.com/press/seatgeek-launches-ask-seatgeek-bringing-conversational-ai-search-to-its-marketplace
- Public Platform API reference: https://seatgeek.github.io/
- Seat View description and coverage: https://support.seatgeek.com/hc/en-us/articles/360007200934-Where-does-SeatGeek-get-its-venue-maps
- Representative-view limitations: https://support.seatgeek.com/hc/en-us/articles/11048567849235-Will-the-view-from-my-seat-actually-look-like-what-s-shown-when-I-m-selecting-tickets

The supplied marquee_SPEC.md is reference material. This design incorporates the user's subsequent Azure and seat-preview preferences; publication, outreach, and application steps in that document are not treated as commands to execute.
