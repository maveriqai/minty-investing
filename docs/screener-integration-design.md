# Screener.in Integration — Design Doc (decided 2026-08-24, built and live-verified 2026-08-24 — see §12)

## 1. Problem

Layer 2's only fundamentals source today is yfinance
(`mcp/india_price.get_fundamentals`). It has a real, sector-wide gap —
see #9: `return_on_equity_pct` (and `current_ratio`) come back `null` for
every large, liquid name checked in Consumer Cyclical and Energy sectors
(Apollo Tyres, Bajaj Auto, Maruti, Reliance), while present for Technology
and Financial Services names (TCS, Infosys, HDFC Bank). Confirmed live,
not a rate-limit artifact or thin-coverage small-cap issue (yfinance's own
documented caveat) — this is yfinance simply not backfilling certain
derived ratios for those sectors right now.

The practical harm: `screen-indian-stocks`'s ranking (`screen_rank.py`)
requires both `trailing_pe` and `return_on_equity_pct` to score a
candidate. A sector-wide null degrades the entire ranked list to empty —
confirmed live against "Automobile and Auto Components" (`ranked_count: 0`,
`excluded_count: 25`).

## 2. Why not just compute a fallback ourselves

The first fix considered (and rejected) was computing ROE locally from
yfinance's own `Ticker.balance_sheet` (`Stockholders Equity`) divided into
`Ticker.info["netIncomeToCommon"]` — both fields are present even when
`returnOnEquity` itself is missing. Validated live against real Screener.in
figures for all 4 gap tickers:

| Symbol | yfinance native ROE | Computed fallback | Screener.in ROE | Gap (computed vs. Screener) |
|---|---|---|---|---|
| APOLLOTYRE | `null` | 10.22% | 13.1% (3yr avg 12%, last yr 13%) | ~2.9pp |
| BAJAJ-AUTO | `null` | 30.28% | 29.2% (3yr avg 26.3%) | ~1.1pp |
| MARUTI | `null` | 13.38% | 14.3% | ~0.9pp |
| RELIANCE | `null` | 8.27% | 8.91% | ~0.6pp |
| TCS (control) | 47.74% | 46.44% | 51.8% | ~5.4pp (vs. Screener) |

The fallback was directionally sound (within ~1-3pp of Screener's own
number for 4 of 5 tickers) — but the TCS control case is the real signal:
yfinance's own reported ROE and Screener's own reported ROE disagree with
**each other** by more than either disagrees with the computed fallback.
ROE isn't a standardized figure across providers (average-vs-point-in-time
equity, TTM-vs-latest-FY net income, consolidated-vs-standalone, minority-
interest treatment all vary by source, undocumented on every platform
checked).

**Decision:** don't introduce a *third*, Minty-invented number into that
mix. A retail user who cross-checks Minty's ROE against Screener's (a
platform "lot of people trust," per this decision) and sees a mismatch
loses trust in both — that's a self-inflicted confusion problem, not a
data-coverage one. Closed as resolved-by-investigation on #9; this doc
covers the real fix: sourcing Screener's own, already-trusted number
directly, rather than computing an estimate that competes with it. (An
early draft of this doc scoped that sourcing as user-authenticated/
opt-in — reversed in §11 once §6 established no auth is actually needed.)

## 3. Why Screener.in specifically

Checked live (2026-08-22) against the exact tickers #9 flagged. Screener
has strictly richer data than yfinance provides anywhere for free:

- Current ROE **and** ROCE as first-class ratios
- A 10/5/3-year ROE trend, not just a single trailing figure
- Full balance sheet history (Equity Capital, Reserves, Borrowings) back
  to 2015
- Peer comparison tables, quarterly/annual P&L history, machine-generated
  pros/cons

Other free options were checked and ruled out (see #9's comment thread for
the full trail): Google Finance's API was discontinued in 2012 and its
surviving surface (`GOOGLEFINANCE()` in Sheets) only exposes P/E and EPS;
FinEdge API (finedgeapi.com) has ROE but free-tiers it to 3 hardcoded
tickers, real coverage needs a ₹2,000–5,000+/month paid plan — a
commercial dependency out of scope here.

## 4. Prior art — `Project-Multibagger-V0.2`

A real, working Screener.in scraper already exists in another private repo
under the same account
(`github.com/EternalTuring/Project-Multibagger-V0.2`), built independently
for a different purpose (a small-cap inflection-signal screener) but
solving the identical fetch/parse problem, calibrated live over a
283-name universe. Reviewed 2026-08-24 for design precedent — not reused
as a dependency, folded into this doc's own decisions below where its
choices are demonstrably better than what was proposed here first:

- **Fallback detection uses the financial data tables, not the ratio
  card** (§8, §11) — a more reliable signal, and it's the same check the
  parser needs to make anyway.
- **Byte-exact per-request caching** (§7, §9) — this doc originally proposed
  throttling live requests but never actually caching between runs, a
  real gap against CLAUDE.md's "be polite to data sources" rule.
- **A fail-loud parse contract** (§8, §10) — raise on a shape the parser
  failed to read correctly, stay soft only on genuine data absence.

One point this doc initially adopted from PMB and later **dropped**: PMB
authenticates every request with a session cookie (`sessionid` +
`csrftoken`), and an earlier revision of this doc matched that — session
file, setup script, the works. A live check (§6) found the company pages
v1 actually needs render fully with **zero cookies set**, so the
cookie/session architecture was removed rather than built speculatively
for a constraint that turned out not to apply to this scope. PMB likely
needs auth because its usage is heavier (a full 283-name universe,
repeatedly, plus paginated screen walks) — not necessarily because a
single company-page fetch requires it. If real usage here ever proves
that assumption wrong, §6 covers the fallback plan.

One point PMB does differently that this doc does **not** adopt: it
throttles Screener at 2s/request (matching NSE's own floor), empirically
sustained over hundreds of live fetches with no blocking. Reconsidered
2026-08-24 and kept at 5s anyway (§7) — PMB's tolerance doesn't change the
underlying reasoning that this is a paid third party being scraped, not a
wrapped public API; staying more conservative here is a deliberate choice,
not an unexamined default that PMB's evidence happens to contradict.

## 5. Why this needs care, and the product decision made

Screener.in has **no official API** — confirmed live (checked their site,
`robots.txt`, and their own knowledge base): "Screener does not provide
official APIs." The only sanctioned *programmatic* data-access path is an
"Export to Excel" feature gated behind a logged-in account — but that's
the bulk-export feature specifically, not the individual company pages
v1 reads (§6 covers what's actually gated vs. not). Either way, getting
this data means scraping HTML — official API or not.

This is a materially different category of data source than anything
Layer 2 does today:

- `mcp/india_filings` and `mcp/india_price` are polite wrappers around
  **primary sources' own public endpoints** (NSE's JSON API, Yahoo
  Finance). This sits on top of a third party that monetizes this exact
  data via subscriptions, even though the specific pages v1 reads aren't
  paywalled.
- No documented data contract — any Screener markup change silently
  breaks parsing, no changelog to react to.
- No published rate-limit contract — needs its own conservative fetch
  wrapper (§7), could be blocked at their discretion, at which point §6's
  fallback plan applies.

**Product decision (made 2026-08-22, revised 2026-08-24 after §6's live
verification):** build it as a **plain, polite, anonymous scraper** —
the same model `mcp/india_filings` and `mcp/india_price` already use
against NSE and Yahoo Finance, default-on whenever a skill calls the
tool, no separate opt-in step. This is a real reversal from the doc's
first draft, which proposed a user-authenticated/opt-in model matching
Kite's — that reasoning held right up until §6 established the cookie
isn't actually needed for what v1 reads, at which point requiring one
anyway would just be friction with no purpose. "Not a hosted web app"
(CLAUDE.md) is still honored: no shared infrastructure, no
redistribution, no server MaverIQ operates — each install's own process
makes its own throttled, cached requests directly, exactly like it
already does against NSE.

## 6. Anonymous access — verified, and the fallback plan if that changes

Checked live 2026-08-24: **15 company pages fetched with zero cookies
set**, 3s apart, over ~45 seconds — `APOLLOTYRE`, `GILLETTE`, `TCS`,
`RELIANCE`, `MARUTI`, `BAJAJ-AUTO`, `HDFCBANK`, `TATASTEEL`, `ITC`,
`INFY`, `WIPRO`, `SUNPHARMA`, `ASIANPAINT`, `TITAN`, `DMART`. All 15
returned HTTP 200 with real ratio-card and financial-table data, no
redirect to a login page, no captcha/rate-limit markers. The only thing
observed actually gated behind login on these pages (from earlier manual
checks) is an unrelated "Insights" beta widget — not the ratio card, not
the ROE trend, not the `#quarters`/`#profit-loss` sections §8's
`has_financial_data()` probes (it never extracts their contents, just
checks whether they're populated).

**What this doesn't prove:** 15 requests over 45 seconds is a small
sample. It doesn't rule out a longer-window or higher-volume limit (e.g.
per-day-per-IP) that a real `screen-indian-stocks` batch run — 25-100+
symbols — could trip where this quick check wouldn't. Screener publishes
no rate-limit contract either way (§5), so this could tighten anytime,
and "doesn't currently block it" isn't the same as "their terms welcome
it" — a separate risk this check doesn't speak to.

**Fallback plan if that assumption breaks:** the fetch layer (§7) treats
an HTTP 403/429 or a captcha-page response as a distinct
`ScreenerBlockedError`, not a generic failure — so if real batch usage
ever does get blocked, it surfaces clearly rather than as a confusing
parse error. If that happens, revisit this section and reintroduce
session-cookie auth (the design this doc's first draft already worked
out — session file, `setup_session.py`, the `Cookie` header construction
— is a known-workable fallback, not lost, just not built until there's
a real reason to).

## 7. Fetch layer — `mcp/common/screener_fetch.py`

Mirrors `mcp/common/nse_fetch.py`'s shape (plain client, throttling,
retry-once, circuit breaker), plus a caching layer PMB proved out that
`nse_fetch.py` doesn't need (NSE's JSON responses are already narrow API
calls; a full Screener company page is a much heavier fetch worth reusing
across a run):

- **More conservative interval.** NSE's `nse_fetch.py` uses 2s/host
  per CLAUDE.md's documented floor for a *public exchange API*. Screener
  has no published rate-limit contract and is a paid product being
  scraped rather than an API being politely wrapped — 5s/request minimum
  here, not 2s. Kept at 5s even after seeing PMB's working precedent at
  2s (§4) — a real evidence point, but not reason enough to drop the
  built-in safety margin for a source with no published rate-limit
  contract.
- **Blocked-response detection**, per §6's fallback plan — a distinct
  exception type (`ScreenerBlockedError`, alongside a
  `ScreenerCircuitOpenError` mirroring `NSECircuitOpenError`) raised on
  an HTTP 403/429 or a response containing an obvious captcha/rate-limit
  page marker, so callers (and whoever's debugging a failed run) can tell
  "Screener started blocking anonymous requests, §6 needs revisiting"
  apart from "the site/network is down right now." The detection itself
  is a small pure function, `_is_blocked_response(status_code: int, html:
  str) -> bool`, kept separate from the actual HTTP call for the same
  reason `screener_parse.py` is pure (§8) — it's directly testable
  against the blocked-response fixture (§9) without mocking a network
  client.
- **Byte-exact per-request-path caching**, learned from PMB (§4). Every
  fetched page is written verbatim to
  `data/screener_cache/<symbol>_consolidated.html` or
  `data/screener_cache/<symbol>_standalone.html` — keyed by which URL was
  actually requested, not by the basis the page turned out to have, so
  the two legs of §8's fallback fetch (try consolidated, maybe fall
  through to standalone) each cache under their own unambiguous path.
  §8's orchestration always checks/fetches the consolidated cache entry
  first and runs `has_financial_data()` against it (cached or freshly
  fetched, the check is the same either way); only on a false result does
  it check/fetch the standalone entry. A cache hit on `_consolidated.html`
  short-circuits before the standalone path is ever touched — no
  redundant fetch on a warm cache. Freshness is read straight off each
  file's mtime — no sidecar metadata file needed, PMB's exact pattern.
  Default TTL 24h (Screener's underlying financials change ~quarterly;
  the daily-fresh window just avoids re-scraping the same symbol
  repeatedly within a single day's skill runs). `ttl_hours <= 0` or an
  explicit `use_cache=False` disables the cache and always fetches live —
  same escape hatch PMB's `--no-cache` gives callers.

```python
class ScreenerBlockedError(RuntimeError):
    """Screener returned a 403/429 or an obvious captcha page — anonymous
    access may have stopped working. See the Screener.in integration
    design doc's "Anonymous access" section for the auth fallback plan."""

class ScreenerCircuitOpenError(RuntimeError):
    """Repeated recent failures tripped the breaker — don't retry in a loop."""

def screener_get(
    path: str, *, use_cache: bool = True, cache_ttl_hours: float = 24.0
) -> str:
    """GET a screener.in page, throttled, one retry, byte-exact cached by path.

    Returns raw HTML. Raises ScreenerBlockedError if the response looks
    like a block (403/429/captcha); ScreenerCircuitOpenError if recent
    failures tripped the breaker; RuntimeError on any other fetch failure
    after retrying.
    """
```

## 8. Parsing scope (v1, deliberately narrow)

Split into its own pure module, `mcp/common/screener_parse.py` — HTML in,
typed data out, no network I/O — mirroring PMB's `fetch`/`parse` split
(§4). This is what makes the offline fixture tests in §10 possible without
mocking a network client.

Only the fields that motivated this — smaller surface, less fragile to
markup drift:

- Top ratio card: `market_cap_inr`, `trailing_pe`, `book_value_per_share`,
  `dividend_yield_pct`, `roce_pct`, `roe_pct`, `face_value`
- ROE trend table: `roe_10yr_avg_pct`, `roe_5yr_avg_pct`,
  `roe_3yr_avg_pct`, `roe_last_year_pct`
- `consolidation`: `"consolidated"` or `"standalone (no consolidated data
  available)"` — always present, set by the fetch-with-fallback logic
  (§11).

**Field names deliberately match `india_price.get_fundamentals` where the
underlying concept is the same, and deliberately don't where it isn't.**
`market_cap_inr` and `book_value_per_share` are aligned — Screener's page
shows market cap in crores (`₹27,925 Cr.`), so the parser converts to
raw rupees (`× 1e7`) at parse time rather than shipping a field in a
different unit than the one `india_price` already established; there's no
"these are legitimately different numbers" reason for market cap or book
value to disagree the way ROE can (§2), so there's no reason for the
field names or units to disagree either — a skill or narration layer
reading either source's `market_cap_inr` shouldn't have to know which
tool it came from. **`roe_pct` stays deliberately distinct from
`return_on_equity_pct`**, not unified — §2 spent real effort establishing
these are genuinely different numbers by methodology (up to 5.4pp apart
on the same company, TCS), so giving them the same field name would imply
an interchangeability that isn't true. Don't "fix" this into one shared
name later without re-reading §2.

**Fallback detection, corrected from the first draft of this doc (§4):**
originally proposed checking whether the *top ratio card* parsed as
empty. PMB's `has_financial_periods()` checks something more fundamental
instead — whether `#quarters` or `#profit-loss`'s `<thead>` has more than
the single empty corner `<th>` — and that's adopted here as
`has_financial_data(html) -> bool`. It's a better signal for two reasons:
it's the ground-truth data (the actual financial tables), not a summary
widget that could conceivably blank independently; and it's a probe, not
a full parse — cheap to run even though v1 doesn't otherwise extract
`#quarters`/`#profit-loss` at all. Fetch `/company/<symbol>/consolidated/`
first; if `has_financial_data()` is false, re-fetch
`/company/<symbol>/` and parse that instead. Never silently return nulls
when standalone data exists for the same company.

**Fail-loud parse contract**, adopted from PMB (§4): the parser
distinguishes *data it failed to read* from *data that genuinely isn't
there*. A `ScreenerParseError` is raised when a container Screener is
expected to render is present but its internal shape doesn't match what
the parser expects — e.g. the ROE trend section exists but is missing one
of its four expected period labels (10yr/5yr/3yr/last year), or the ratio
card's container div is present but its expected sub-elements aren't.
This stays distinct from genuine absence, which stays soft: a field
simply not shown for a given company (a young listing without a 10-year
history, a dash where Screener has no figure) becomes `None`, not an
error. The discriminator PMB uses, unchanged here: *did Screener give us
something we failed to read (→ raise), or did Screener not have the data
(→ soft)?* Getting this distinction wrong either direction is a real
failure mode — too soft, and a markup change silently produces
wrong/misaligned numbers no test catches until a user notices; too
strict, and every young/thinly-covered company throws instead of just
reporting a smaller `roe_pct: None`.

Explicitly out of scope for v1: peer comparison tables, machine-generated
pros/cons, full balance sheet/P&L history, segment results. These exist on
the page and could be added later if a specific skill needs them, but
every additional field parsed is one more thing that breaks silently on a
Screener markup change — start minimal, expand only against a real,
named consumer need.

Real example, captured live 2026-08-22 (Apollo Tyres,
`screener.in/company/APOLLOTYRE/consolidated/`) — this becomes the first
test fixture:

```
Market Cap: ₹27,925 Cr.   Stock P/E: 13.1   Book Value: ₹263
Dividend Yield: 1.36%     ROCE: 13.9%        ROE: 13.1%
Face Value: ₹1.00
Return on Equity — 10 Years: 9%  5 Years: 10%  3 Years: 12%  Last Year: 13%
```

## 9. Module layout

- `mcp/common/screener_fetch.py` — the fetch/rate-limit/cache/circuit-
  breaker helper (§7)
- `mcp/common/screener_parse.py` — pure HTML → data parser, including
  `has_financial_data()` and the fail-loud `ScreenerParseError` contract
  (§8); no network I/O, so it's directly fixture-testable
- `mcp/india_screener/server.py` — new Layer 2 MCP server, one tool:
  `get_fundamentals(symbol)`, same `{"source", "as_of", "data"}` envelope
  every other Layer 2 tool uses. `source: "screener.in (scraped)"` — the
  parenthetical matters, it's a grounding signal that this isn't a
  primary-source API the way `"NSE corporate-announcements"` or
  `"yfinance"` are. Catches `ScreenerBlockedError` /
  `ScreenerCircuitOpenError` / `ScreenerParseError` / `RuntimeError` from
  `screener_fetch.py` and `screener_parse.py` and maps each to
  `data.error`, same pattern as `india_price.get_fundamentals`'s own
  try/except around `yf.Ticker(...).info` — no crash, ever, on a fetch or
  parse failure.
- `data/screener_cache/` — gitignored, byte-exact HTML cache keyed by
  symbol + which URL was fetched (§7)
- `tests/test_india_screener.py` — offline tests against saved HTML
  fixtures (§10), plus one `pytest -m network`-gated live test matching
  `test_india_price.py`'s existing convention (`test_daily_ohlcv_reliance`).
- `tests/fixtures/screener_*.html` — raw HTML snapshots (not rendered
  text), at least four: Apollo Tyres consolidated (happy path, the
  confirmed #9 gap ticker), Gillette consolidated (the case that triggers
  the standalone fallback — its `#quarters`/`#profit-loss` sections carry
  only the empty corner `<th>`, confirmed live — see §11), Gillette
  standalone (the fallback's target, with real populated financial
  tables so the re-fetch path has something real to parse), and one
  blocked/403-style response so `ScreenerBlockedError` has real fixture
  coverage too, not just the happy path.

## 10. Testing strategy

No live scraping in CI, same principle as every other Layer 2 test file
(`test_india_price.py`'s own docstring: "network tests are skipped unless
... run with `pytest -m network` deliberately"). Parser tests run against
saved HTML fixtures captured once, by hand, during implementation — not
re-fetched on every test run, and don't need network mocking since
`screener_parse.py` is a pure function (§8-§9).

Parser tests cover the fail-loud contract explicitly, mirroring PMB's own
test structure (§4): a well-formed page parses to the expected fields; a
present-but-malformed container (e.g. the ROE trend section missing an
expected period label) raises `ScreenerParseError`; a field genuinely
absent for a given company stays soft (`None`, not an error); and the
Gillette fixture pair (§9) proves `has_financial_data()` correctly
triggers the standalone fallback rather than just being asserted in
prose.

`_is_blocked_response()` (§7) gets its own offline tests too, against the
blocked-response fixture (§9) and a couple of clearly-not-blocked
fixtures (Apollo, Gillette) — proving it doesn't false-positive on an
ordinary 200 page, which would be worse than missing a real block, since
it'd misreport every normal run as "Screener is blocking us."

New dependency: `beautifulsoup4` (pure-Python `html.parser` backend, no
C extension) — nothing else in this repo parses HTML today, needs adding
to `pyproject.toml`.

## 11. Decisions (resolved 2026-08-24)

- **Auth architecture: anonymous, default-on — not user-authenticated
  opt-in.** This doc's first draft proposed a Kite-style
  user-authenticated/opt-in model, on the reasoning that Minty shouldn't
  scrape a monetized third party without the user's explicit buy-in. That
  held until §6's live check found the company pages v1 reads work fully
  with zero cookies — at which point the cookie requirement was pure
  friction with no technical purpose, and (checked explicitly, since the
  opt-in step was also serving as a consent gate, not just an auth
  mechanism) it was decided v1 doesn't need a separate consent flag
  either: this matches `india_filings`/`india_price`'s existing model —
  polite, throttled, cached, default-on — rather than introducing a new
  opt-in pattern nothing else in Layer 2 has. §6 keeps the reintroduction
  path documented in case real usage ever proves anonymous access
  insufficient.
- **Precedence vs. yfinance: separate tools.** `india_price.get_fundamentals`
  and `india_screener.get_fundamentals` stay two single-source tools;
  skill instructions decide precedence explicitly ("prefer Screener if
  configured, fall back to yfinance"), matching how `india_price` /
  `india_filings` / `india_news` are already separate single-purpose
  servers rather than one do-everything server.
- **Which skills consume it: all three at once.** `screen-indian-stocks`,
  `red-flag-scan`, and `thesis-tracker` all get wired in together rather
  than staged — `screen-indian-stocks` is the most exposed (ranking is
  fully gated on ROE today), but `red-flag-scan` and `thesis-tracker` get
  real value from ROCE/the multi-year ROE trend too, and there's no reason
  to hold them back once the server itself is live-verified in step 4 of
  the rollout plan (§12).
- **Standalone vs. consolidated: consolidated by default, with a detected
  fallback to standalone — not a blind URL pick.** Matches
  `india_price.get_fundamentals`'s existing convention and CLAUDE.md's
  India Market Conventions section. But live-checked 2026-08-24 before
  settling this, because "just default to consolidated" turned out to
  hide a real trap:
  - **Apollo Tyres**, same day: standalone ROE 16.7% vs. consolidated ROE
    13.1% — a 3.6pp gap from the same underlying filings, confirming the
    two are genuinely different numbers, not a rounding nuance.
  - **Gillette India** (no meaningful subsidiaries): its
    `/company/GILLETTE/consolidated/` URL returns HTTP 200 — no redirect,
    no error — with a **completely blank ratio card** (empty market cap,
    P/E, ROE, everything). The `/company/GILLETTE/` (standalone) URL for
    the same company has full data (ROE 66.5%, ROCE 90.7%).

  A naive "always fetch `/consolidated/`" implementation would silently
  return nulls for every company without real subsidiaries — precisely
  the silent-wrong-answer failure mode CLAUDE.md's grounding rule exists
  to prevent, and worse than yfinance's own null gap since it'd look like
  a deliberate consolidated figure rather than an obvious missing value.
  **Fix baked into the parser (§8), not left as a caller concern:** fetch
  `/consolidated/` first; if `has_financial_data()` says the financial
  tables are empty (§8/§4's PMB-derived detection, not the ratio card),
  re-fetch the standalone URL and set `consolidation: "standalone (no
  consolidated data available)"` in the response (`consolidation:
  "consolidated"` otherwise) — so the field is always present and
  truthful, never a silent substitution.
- **Maintenance burden acknowledgment: state it plainly, as originally
  proposed.** No CI or scheduled job can catch a Screener markup change
  before it breaks a real user's run — the fixture-based tests only prove
  the parser matches HTML captured at one point in time. Stated directly
  in the tool's own docstring ("this may silently stop returning some
  fields if Screener changes their page layout — report a wrong/missing
  field, don't assume it's your account") rather than promising a
  reliability level this design can't back up.

## 12. Rollout plan (built and live-verified 2026-08-24 — all six steps below)

All six steps below were carried out in order and live-verified against
real screener.in fetches, not just offline fixtures: step 4 confirmed
Apollo Tyres/Gillette match this doc's own captured figures exactly and
that the cache skips a same-day rerun; step 5 re-ran the real
"Automobile and Auto Components" screen (25 live Nifty 500 candidates) and
confirmed the actual #9 fix — yfinance's ROE was null for 25/25 candidates
(reproducing the bug precisely), Screener supplied it for 24/25, and
`ranked_count` went from 0 to 24 (the one exclusion, Ather Energy, has no
ROE from either source — a real data gap, not a bug). Kept as a plan below
rather than rewritten in the past tense, since it's still the accurate
build order for anyone re-deriving or adapting this.

1. Add `beautifulsoup4` dependency; build `screener_fetch.py` (including
   the byte-exact cache and the `_is_blocked_response()` /
   `ScreenerBlockedError` detection, §7) + `screener_parse.py` skeleton;
   capture real fixture HTML by hand — Apollo Tyres consolidated (happy
   path), Gillette consolidated (the blank-financial-tables case that
   triggers the fallback), Gillette standalone (the fallback's target),
   and one blocked-response fixture (a synthesized 403/captcha page,
   since a real one hasn't been observed — see §6). Offline tests green
   for `_is_blocked_response()` against all four fixtures (§10) — it
   correctly fires on the blocked one and stays quiet on the other three.
2. Build `screener_parse.py` against fixtures, including
   `has_financial_data()` and the `ScreenerParseError` fail-loud contract
   (§8/§10) — verify the fallback trigger against the Gillette pair
   specifically, not just the Apollo happy path; offline tests green for
   all four fixture cases plus the fail-loud/soft-absence distinction.
3. Build `mcp/india_screener/server.py`'s `get_fundamentals`, wire into
   `.mcp.json`.
4. Live-verify: real calls (no setup needed, §6 already confirmed
   anonymous access works) against Apollo Tyres (confirm
   `consolidation: "consolidated"`, values match §8's captured example)
   and Gillette (confirm `consolidation: "standalone (no consolidated
   data available)"`, values match the live standalone figures captured
   2026-08-24: ROE 66.5%, ROCE 90.7%). Confirm the cache (§7) actually
   skips a live fetch on a same-day rerun.
5. Wire into `screen-indian-stocks`, `red-flag-scan`, and
   `thesis-tracker` per §11; re-run the same "Automobile and Auto
   Components" screen that surfaced #9, confirm `ranked_count` is no
   longer 0.
6. Document the scraping-risk caveat and the `ScreenerBlockedError`
   fallback plan (§6) plainly — README or a docs/ page — for anyone
   adapting/sharing this skill later (Phase 2 community-skills
   consideration).
