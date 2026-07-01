# Flight Research & Recommendation Agent

## What this project is
A Python tool that searches flights for a route I specify, scores the results
against my preferences, and outputs a ranked recommendation (not an automatic
booking — I will book manually).

Originally a CLI tool (Phase 1, complete). Now adding a local web UI
(Phase 2) on top of the same search/scoring logic — the CLI should keep
working, this is an additional way to run it, not a replacement.

I am a beginner with Claude Code. Prefer simple, readable code over clever
abstractions. Explain non-obvious choices in code comments. When you're about
to make an architectural decision (new dependency, new file, changing how
something works), tell me what you're doing and why before doing it for
anything beyond a trivial fix.

## Current status
Phases 1–4 complete and working: CLI, Web UI, Render deployment, and Notion
export. Notion export had two bugs since fixed: ranking was inverted (now
correct, #1 appears first) and all data was crammed into one Name column
(now split into proper columns: Route, Name, Duration, Price, Stops, Reason).
Phase 5 (Notion log usability + price tracking groundwork) in progress —
part A not yet built, part B needs my confirmation before building (see
Phase 5 plan). Phase 6 (search by city/place name) is scoped and queued
next — see plan below. Work through Phase 5 before starting Phase 6 unless
I say otherwise.

## How I run this today (Phase 1 — CLI, keep working)
Manually from the terminal, on demand.
`python3 main.py --from NBO --to LHR --depart 2026-08-10 --return 2026-08-20`

## How I want to run this next (Phase 2 — Web UI)
Open a local web page in my browser, type in a route + dates via a form,
click search, see the ranked results displayed on the page. No scheduling,
no email/notifications, no deployment to the internet — local only, for now.

## Flight data source
**Duffel API** (https://duffel.com/docs) — chosen because it has clean docs,
a real Python-friendly REST API, and a usable free test/sandbox mode.

Key facts about Duffel (verified June 2026 — re-check docs if anything here
seems to not match what you see):
- Auth: `Authorization: Bearer <token>` header on every request.
- Also required on every request: `Duffel-Version` header and `Accept: application/json`.
- Flight search = create an "Offer Request" (POST), describing origin,
  destination, date(s) as "slices", plus passenger info. Response is a list
  of "Offers" (price, airline, segments/times).
- Test mode tokens mostly return a sandbox airline ("Duffel Airways", code ZZ)
  with unrealistic prices/schedules, sometimes mixed in alongside real
  airline results — don't treat sandbox offers as real pricing. Filter or
  clearly flag them in any UI.
- We call the REST API directly with `requests`, not the official SDK, so I
  can see exactly what's happening. Keep it this way in Phase 2 as well.

⚠️ Do NOT integrate the Amadeus Self-Service API. It was decommissioned
July 17, 2026 and any tutorial/code suggesting it is now stale.

## Phase 1 build plan (CLI) — COMPLETE
1. Project skeleton ✅
2. Config & secrets (.env, python-dotenv) ✅
3. Minimal search against Duffel Offer Request endpoint ✅
4. Parsing raw offers into clean internal structure (price, duration, stops,
   layovers, times, airline, bags) ✅
5. Scoring/ranking against my preferences ✅
6. Terminal output, top recommendation highlighted ✅
7. CLI args via argparse ✅
8. (Later/optional) round-trip refinements, multiple cabin classes, saved
   searches, price-history tracking — not started, not urgent.

## Phase 2 build plan (Web UI) — do these in order, one at a time
Goal: reuse the existing search/scoring/parsing logic as-is, just called from
a web server instead of `main()`. Don't rewrite working logic to "fit" the
web app — wrap it.

1. **Refactor for reuse**: confirm the core search→parse→score pipeline is
   callable as a plain function (e.g. `find_best_flights(origin, dest,
   depart, return_date) -> list[ScoredOffer]`) independent of argparse or
   print statements. If `main.py` currently mixes CLI parsing and logic
   together, separate them first. CLI (`main.py`) keeps working by calling
   this same function — don't duplicate logic between CLI and web paths.
2. **Add Flask**: add `flask` to `requirements.txt`, create `app.py` with a
   single route that, for now, just returns a hardcoded "hello" page — prove
   the server runs and I can see it in the browser before wiring up real
   logic.
3. **Backend search endpoint**: add a route (e.g. `POST /search`) that takes
   route/date inputs, calls the existing pipeline function, and returns
   results as JSON.
4. **Frontend form**: one HTML page for from/to/depart/return, that calls
   `/search` and renders the ranked results in a readable list, similar
   structure to the current terminal output (top pick highlighted, price,
   times, duration, stops, layovers, bags, airline).
   **Visual design matters here — I want this to look genuinely good, not
   bare-bones.** Use real CSS (can still be a single file, no build tools
   needed), thoughtful typography and spacing, a clear visual hierarchy that
   makes the #1 ranked flight obviously stand out from the rest, and tasteful
   use of color (e.g. to distinguish airline tiers or flag the top pick) —
   not just default browser styling. Reference the frontend-design guidance
   if available rather than guessing at styling from scratch.
5. **Polish**: loading state while a search is running, clear error message
   in the UI if the API call fails or returns no offers (don't fail silently
   — same principle as the CLI).
6. **(Later, optional)**: basic styling beyond plain HTML, remembering last
   search, saving favorite results — not before 1–5 work end to end.

Don't jump to step 4 before steps 1–3 actually work — same pacing principle
as Phase 1. Show me each step's code before running it for anything beyond a
trivial fix.

## How I'll run this in Phase 2
One terminal command to start the server: `python3 app.py`, then open
`http://localhost:5002` in my browser. (Port 5002 — macOS AirPlay Receiver uses 5000.)
I run that one command once per session — everything after that happens in
the browser, no further terminal interaction needed for search itself.

## My preferences for "best flight" (tune the scoring function around these)

**This replaces the old single-weighted-score approach. Ranking is now
TIERED/LEXICOGRAPHIC — sort by each criterion in order below, only using the
next criterion to break ties within the previous one. Do not blend these
into one combined numeric score; that obscures why something ranked where it
did, and I want to be able to explain any ranking simply.**

Sort order (highest priority first):
1. **Airline tier**:
   - Tier 1 (rank first): United Airlines, American Airlines
   - Tier 2 (rank second): British Airways, Air France
   - Tier 3 (rank below both): everyone else
   - If no Tier 1 airline serves the route, offers fall through normally to
     be ranked by Tier 2 first — no special flag or warning needed, this is
     expected and normal.
2. **Directness, within the same airline tier**: direct flights always rank
   above indirect ones, even if the direct option costs meaningfully more.
   Do not let price override this — directness beats price within a tier.
3. **Price, as the tiebreaker within same airline tier + same directness**:
   lowest price wins.
4. Everything else (total duration, layover length/quality, baggage, time of
   day) ranks below all of the above — use only as a final tiebreaker if 1–3
   are identical, or to inform the one-line "reason" text, not to reorder
   results.

Default cabin: **business** (changed from economy). Confirm with me whether
the Duffel search request itself is scoped to business cabin (i.e. only
business fares are fetched), or whether all cabins are fetched and business
is just preferred in scoring — I want to know which one we're doing, since
they produce different result sets.

Other standing preferences (lower priority than the above, used only as
tiebreakers or in the reason text):
- Max acceptable layovers: 1
- Max acceptable total travel time: prefer under 12 hours where realistic,
  flag anything over but don't exclude it
- Avoid red-eye-only options if there's a reasonable alternative, but don't
  hard-exclude them

(Updated after seeing real Phase 1 output. This tiered approach replaces the
earlier "price matters most, but use judgment" framing — that was too vague
once I knew what I actually cared about.)

## Phase 3 build plan (Deploy for shared access) — do these in order
Goal: let 1–2 trusted people (friends/family) use this from anywhere, while
keeping it simple. Explicitly NOT building per-user accounts or per-user API
keys — everyone shares my Duffel key and my hosting. Revisit only if this
becomes a real problem (e.g. rate limits, cost, abuse) — not preemptively.

Platform: **Render** (https://render.com), chosen because it deploys
straight from a GitHub repo, auto-redeploys on every push, handles HTTPS
automatically, and has a real free tier with no credit card required. Trade-
off accepted: free-tier Render apps sleep after ~15 minutes of inactivity,
so the first request after a quiet period takes up to ~60 seconds to wake up
— acceptable for occasional use by 1-2 people, not worth paying to avoid yet.

1. **Get the app onto GitHub**: if this project isn't already in a git repo,
   initialize one, confirm `.gitignore` correctly excludes `.env` and `venv/`
   (verify before pushing — the API key must never end up on GitHub), then
   push to a new repository.
2. **Production server**: the Flask dev server (`app.run(debug=True, ...)`)
   must not be used in production. Add `gunicorn` to `requirements.txt` and
   confirm the correct start command (e.g. `gunicorn app:app`). Explain what
   changes for me vs. running `python3 app.py` locally — I should understand
   this, not just have it silently swapped in.
3. **Environment variables on Render**: set `DUFFEL_API_KEY` in Render's
   dashboard (their secrets/environment variables section), not in any file
   that gets committed. Confirm the app reads it the same way in production
   as it does locally via `.env` (same `python-dotenv`/`os.environ` pattern,
   just sourced differently in each environment).
4. **Basic access gate**: add a single shared password the app asks for
   before allowing any search — this is NOT full user accounts, just enough
   that the app isn't wide open to anyone who finds the URL. Simplest
   reasonable approach: a password field on first load, stored as a session
   cookie after entry, password itself stored as an environment variable
   (not hardcoded, not committed). Explain the approach before building it
   — I want to understand how someone could still get around it, if at all.
5. **Deploy & verify**: connect the GitHub repo in Render, deploy, confirm
   the live HTTPS URL works end to end — password gate, search, results —
   exactly like the local version.
6. **Share access**: give the URL + shared password to the 1-2 people
   directly (not posted anywhere public). Confirm with me before doing
   anything that would make the URL more discoverable (e.g. don't add it to
   a public GitHub README).

Don't skip the access gate (step 4) to "get it live faster" — deploying
without it first, even briefly, means the URL is genuinely public the moment
it's live.

## How I'll run this in Phase 3
No "running" required day-to-day once deployed — it's always on (subject to
the free-tier sleep/wake behavior above). I update it by pushing code changes
to GitHub; Render redeploys automatically. Local development (Phase 1/2
commands below) keeps working exactly as before for testing changes before
pushing.

## Phase 4 build plan (Share results to Notion) — COMPLETE
Goal: after a search returns ranked results, a button on the page lets me
send that search's top 5 to Notion, appended to one running log page/database
I keep there. Manual trigger only — never automatic, never on every search.

Actual columns in use: Route, Name (airline + rank), Duration, Price, Stops,
Reason. Ranking order bug (inverted) and single-column-cramming bug are both
fixed — #1 now appears first, data is split across proper typed columns.

Notion setup (I do this manually, not Claude Code):
1. Create an internal integration at notion.so/my-integrations (no OAuth
   needed — single workspace, single user). Copy the Internal Integration
   Token (starts with `secret_`) — this is the API key, treat it exactly
   like the Duffel key (`.env`, never committed, Render env var once
   deployed).
2. Create or choose the Notion page/database that will serve as the running
   log, and explicitly share it with the integration via that page's "Add
   connections" menu in Notion. **This step is required and easy to miss —
   the integration has zero access to anything until manually shared with
   it, even with a valid token.** If API calls fail with a vague
   "could not find object" error, this is almost always the cause — check
   here first before debugging code.
3. Note the database/page ID (visible in its Notion URL) — this gets stored
   alongside the token, not hardcoded.

Build steps:
1. **Config**: add `NOTION_API_KEY` and `NOTION_DATABASE_ID` (or page ID) to
   `.env` / `.env.example` / Render env vars, following the same pattern as
   `DUFFEL_API_KEY`.
2. **Notion client function**: a function that takes the top 5 scored offers
   from a completed search and formats them as Notion content — one entry
   per offer (or one block per offer if appending to a single page), each
   showing: rank, price, airline, stops, duration, and the one-line ranking
   "reason" text already produced by the scoring step. Reuse that reason
   text — don't regenerate or rephrase it for Notion, keep the explanation
   consistent with what's shown in the web UI.
3. **API call**: implement the actual call to Notion's API (Bearer token +
   `Notion-Version` header, like Duffel's pattern) to append this content to
   the existing running page/database — never create a new page per search,
   per my preference. Use `requests` directly, consistent with how Duffel is
   called — no new SDK dependency unless there's a real reason to.
4. **Button + endpoint**: add a "Send to Notion" button on the results page,
   wired to a new backend route (e.g. `POST /export-notion`) that takes the
   most recent search's results and calls the function from step 2-3. Only
   fires on click — never automatically after a search completes.
5. **Feedback**: show a clear success or failure message in the UI after
   clicking — don't fail silently if the Notion call errors (same principle
   as everywhere else in this app). On failure, show enough detail to know
   if it's a missing-share issue (step 2 above) vs. something else.
6. **(Later, optional)**: include the actual search route/dates as context
   in the Notion entry, not just the 5 offers — not essential for v1.

Notion's API allows roughly 3 requests/second — irrelevant at this usage
(a manual button click), no rate-limit handling needed for v1.

## Phase 5 build plan (Notion log usability + price tracking groundwork)
Goal: make the Notion log actually browsable over time, and lay the
groundwork to compare a re-run search against a past one. Two related but
separable pieces — do step set A first, it's small; B is bigger.

**A. Search identity in Notion (small, do first)**
1. Add two more Notion columns: **Search Date** (the date the search was
   run, not the flight's depart date — use a Notion date property) and
   **Search Route+Dates** (e.g. "EWR→SFO, depart 2026-07-10" as one text
   value) so every row is traceable back to which search produced it.
2. Every row already saved to Notion stays as-is — don't backfill or modify
   old rows, just start populating these two columns going forward.
3. Confirm in the UI/console output which search just got saved (route,
   dates) so I can sanity-check against what shows up in Notion.

**B. Price tracking groundwork (medium — scope before building)**
Idea: let me revisit a route/date I've searched before and see if the price
moved since last time, using the Notion log itself as the historical record
(no separate database needed — reuse what's already there).

Before writing code, answer these for me first, then we'll confirm the
approach together:
- How do we match "this is the same search as before"? Likely: same route +
  same depart/return dates + same cabin. Confirm this is enough, or if
  something else (e.g. same passenger count) should factor in too.
- When I run a search that matches a past one in Notion, how should the UI
  show the comparison? (e.g. "previous best was $552, now $480 — down $72")
  Keep this simple for v1 — a single price delta on the #1 ranked offer is
  enough, not a full historical chart.
- This only ever **reads** from Notion to compare, never auto-modifies past
  rows — each search still appends a new row as before via the existing
  "Save to Notion" button.

Don't start the actual price-comparison logic until I've confirmed the
matching rule and the UI approach above — this is exactly the kind of
ambiguous architectural decision worth a quick check-in first, not a
"pick the simplest interpretation and go" situation.

**Noted but deferred**: multi-city / multiple-route comparison (e.g. compare
NBO→LHR vs NBO→CDG side by side in one search) is a real idea I want
eventually, but it's a bigger change — the current pipeline assumes one
route per search. Not part of Phase 5. Revisit as its own phase after price
tracking is solid.

## Phase 6 build plan (Search by city/place name, not just airport codes)
Goal: let me type a city or place name (e.g. "Lisbon") instead of needing to
already know the IATA code, with live typeahead suggestions as I type — like
a normal flight booking site. When a city has multiple airports (e.g.
London: LHR, LGW, LCY, STN, LTN), show them as separate selectable options —
I pick the specific one. Internally everything still resolves to a single
IATA code per side before hitting the existing search pipeline — no changes
needed to search/scoring/Notion logic, this is purely a front-end input
layer.

Data source: **Duffel's own Places suggestions endpoint**
(`GET https://api.duffel.com/places/suggestions?query=...`), not a separate
dataset or third-party service. Key facts (verified June 2026 — re-check if
anything doesn't match what you see):
- Returns Places (airports, cities, countries) matching a free-text query
  string — handles partial matches (e.g. "Lis" → Lisbon results) and IATA
  codes alike, so it also works as a way to validate a code someone already
  knows.
- Each airport result includes a `city_name` field and, for airports in a
  metropolitan area, a nested `city` object listing all airports belonging
  to that city (e.g. querying "London" surfaces the London city entry with
  LHR, LGW, LCY, STN, LTN all listed under it).
- Same auth pattern as flight search: Bearer token, `Duffel-Version` header.
- No new API key needed — this is the same `DUFFEL_API_KEY` already in use.

Build steps:
1. **Backend suggestions endpoint**: add a route (e.g. `GET
   /places?query=...`) that calls Duffel's places/suggestions endpoint and
   returns simplified results (name, IATA code, city name) as JSON — keep
   this as a thin proxy, not a place to add business logic.
2. **Frontend typeahead**: as I type in the From/To fields, call `/places`
   (debounced — don't fire a request on every keystroke, wait for a brief
   pause) and show a dropdown of matching airports. If a city has multiple
   airports, list each one individually with its own name/code visible
   (e.g. "London Heathrow (LHR)", "London Gatwick (LGW)") — not collapsed
   into one "London" entry, since I want to pick the specific airport.
3. **Selection behavior**: picking a suggestion fills the field with a
   readable label (e.g. "Lisbon (LIS)") but stores the actual IATA code
   internally for the search request — the existing `/search` endpoint and
   pipeline don't change at all, they still just receive IATA codes.
4. **Fallback**: if someone types an IATA code directly (e.g. "LIS") instead
   of using a suggestion, that should still work as before — don't require
   the typeahead to be used, just support it.
5. **Empty/no-match handling**: if a typed query returns no matches, show
   that clearly rather than a silently empty dropdown (same no-silent-
   failures principle as the rest of the app).

Keep this self-contained — don't let it touch scoring, Notion export, or
anything downstream of "user picked an origin and destination IATA code,"
which is exactly what the app already expects today.

## Phase 7 (future direction — NOT STARTED, do not build any of this yet)
Idea for later: run searches automatically on a schedule, email me the
results, and only ever proceed to an actual booking if I explicitly approve.
Documenting this now so the idea isn't lost, not as something to act on.

Rough shape, for whenever this gets picked up:
- Scheduled search: something runs the existing pipeline on a timer (e.g.
  cron) without me opening a terminal.
- Email notification: sends me the ranked results (e.g. via Gmail API or a
  transactional email service) — this is a "send a message on my behalf"
  capability and needs explicit setup/consent, not silent automation.
- Approval-gated booking: a real booking (not search) only happens after my
  explicit approval — exact approval mechanism (reply to email, click a
  link, separate confirmation step) is undecided and needs real thought
  before building, since this touches actual payment and real orders, not
  just data. Needs careful handling of: what happens if the price changed
  since the email was sent, what happens if I don't respond in time, how
  payment details are handled (never typed/stored in plain text).

This is materially higher-stakes than Phases 1–6 (real money, real bookings,
sending email on my behalf) and should be scoped deliberately and discussed
in detail before any code is written — not treated as a quick add-on once
earlier phases are done. Phase 6 (city/place search) is the current
priority; do not start any Phase 7 work until I explicitly ask for it.

## Conventions
- Python 3.11+ target, though dev venv currently on 3.9 (macOS system
  Python/OpenSSL warning seen — harmless for now, revisit if a future
  dependency requires newer Python).
- Standard `venv`, dependencies in `requirements.txt`.
- One concern per file: `duffel_client.py`, `scoring.py`, `cli.py` (Phase 1),
  and now `app.py` (Phase 2 web server) + a `templates/` or static HTML file
  for the frontend. Don't over-split before there's a reason to.
- Use type hints on function signatures.
- No silent failures: if the API call fails or returns no offers, say so
  clearly — in the terminal for CLI, visibly in the UI for the web app.
- Log/print what search was actually run (route, dates, filters) before
  showing results, so it's easy to sanity-check the input wasn't mis-parsed.

## Secrets & safety
- API key(s) live in `.env`, loaded via `python-dotenv`, never committed —
  this applies equally to `DUFFEL_API_KEY` and the new `NOTION_API_KEY`.
- `.env` must be in `.gitignore`.
- This tool only ever reads flight data. It must never attempt to create an
  order/booking via the API, and must never send email or any other message
  on my behalf. See "Phase 7" above for the future direction on this — not
  started, needs explicit discussion before any of it is built.
- Phase 3 deployment (Render) is for 1-2 trusted people only, gated by a
  single shared password — not a public app. Do not add user accounts,
  per-user API keys, public sign-up, or remove the access gate unless I
  explicitly ask. Never commit the Duffel API key, Notion key, or the
  access-gate password to GitHub — all live as environment variables on
  Render.
- The Notion integration only ever appends to the one running log page I've
  explicitly shared with it. Never create new pages/databases, never write
  to any other Notion content, never request broader Notion permissions than
  what's needed to append content to that one shared page.

## What to do when something's ambiguous
Pick the simplest reasonable interpretation, tell me what you assumed, and
keep going. Don't stop and ask unless it's something that would be wasteful
to redo (e.g. a real architecture choice), not a small detail.

## Commands
- Setup: `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
- Run CLI: `python3 main.py --from <IATA> --to <IATA> --depart YYYY-MM-DD [--return YYYY-MM-DD]`
- Run web app locally: `python3 app.py`, then open `http://localhost:5002`
- Deploy: `git push` to the connected GitHub repo — Render auto-redeploys
- (Add test commands here once tests exist)

## Progress
Phase 1 (CLI) complete: steps 1–7 done — project skeleton, API key loading,
Duffel search calls, offer parsing, scoring and ranking, output, CLI args.
Verified working against real Duffel data, results look good.

Phase 2 (Web UI) complete: Flask backend, /search endpoint, frontend form
with ranked results, working end to end locally at localhost:5002.

Phase 3 (Deploy to Render for shared access) complete: live on Render behind
a shared password, accessible to 1-2 trusted people.

Phase 4 (Share results to Notion) complete: working end to end, including
fixes for two bugs found after initial build — inverted ranking (fixed, #1
now appears first) and all data crammed into one column (fixed, now split
across Route/Name/Duration/Price/Stops/Reason columns).

Phase 5 (Notion log usability + price tracking groundwork) starting: not yet
built. Start with part A (Search Date + Search Route+Dates columns) — small
and self-contained. Part B (price comparison logic) needs a quick
confirmation of the matching rule and UI approach before building, per the
notes in the Phase 5 plan above.

Phase 6 (Search by city/place name via Duffel Places suggestions) scoped and
queued: not yet built. Do this after Phase 5, unless told otherwise.