"""Shared sector-aware materiality rubric for news/announcement text.

Scores whether a headline or filing is *material* for the stock it's about
— never whether it's good or bad news, and never a predicted price impact.
Every signal below carries a static, pre-written rationale; the caller
(morning-digest's `materiality_check.py` today) narrates that rationale as-is
— it never invents a causal or predictive claim on top of it. Same
discipline `docs/morning-digest-actionability-plan.md` locked in for swing
evidence ("an evidence bundle, never an asserted causal sentence"), extended
to news/announcement text.

Sector resolution combines two sources, since neither alone covers the real
instrument universe well: `mcp/common/instruments.py`'s `industry_for()`
(NSE's own Nifty-500-only taxonomy, 20 labels) and, when that misses,
yfinance's `Ticker.info["sector"]` (Yahoo's broader 11-label taxonomy,
verified live 2026-07-21 to cover the large majority of NSE-listed names
NSE's own Nifty-500 list doesn't). The two taxonomies don't match, so both
normalize onto one small set of canonical materiality buckets that the
actual signal content below is authored against exactly once — see
`NSE_TO_CANONICAL`/`YFINANCE_TO_CANONICAL`.

Deliberately not touched: `mcp/common/instruments.py` itself (stays a pure
local-SQLite accessor, per its own docstring) and its `symbols_by_industry()`
reverse lookup (`screen-indian-stocks`'s candidate-universe need — a
full-universe indexed query, different from this module's per-symbol point
lookup; routing that through yfinance would mean iterating the ~22k-row
universe live, exactly what CLAUDE.md's "be polite to data sources" rule
exists to prevent).

Same import-collision note as every other mcp/common module: the top-level
`mcp/` directory shadows the installed `mcp` PyPI package, so import this
the way tests/test_india_price.py imports server.py — `sys.path.insert(0,
"<repo-root>/mcp/common")` then `import sector_materiality`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import instruments  # noqa: E402

# NSE instruments-master label -> canonical bucket. Verified live 2026-07-21
# against data/instruments.db: these are the 20 real labels present. A label
# not in this dict (e.g. "Diversified", or any future label the ingest
# script picks up) is treated as a miss, not force-mapped — sector_for()
# falls through to the yfinance source rather than guessing.
NSE_TO_CANONICAL: dict[str, str] = {
    "Financial Services": "Financial Services",
    "Automobile and Auto Components": "Automobile & Auto Components",
    "Healthcare": "Healthcare",
    "Information Technology": "Information Technology",
    "Fast Moving Consumer Goods": "FMCG & Consumer Staples",
    "Consumer Services": "Consumer Discretionary",
    "Consumer Durables": "Consumer Discretionary",
    "Services": "Consumer Discretionary",
    "Textiles": "Consumer Discretionary",
    "Metals & Mining": "Metals & Mining",
    "Chemicals": "Chemicals",
    "Oil Gas & Consumable Fuels": "Energy",
    "Power": "Power & Utilities",
    "Capital Goods": "Capital Goods & Industrials",
    "Construction": "Capital Goods & Industrials",
    "Construction Materials": "Realty & Construction",
    "Realty": "Realty & Construction",
    "Telecommunication": "Telecommunication & Media",
    "Media Entertainment & Publication": "Telecommunication & Media",
}

# yfinance's own (Yahoo/GICS-style) sector label -> canonical bucket.
# "Basic Materials" is deliberately absent here — it's ambiguous between
# Chemicals and Metals & Mining, so sector_for() disambiguates it using
# info["industry"] instead of a flat mapping (see below).
YFINANCE_TO_CANONICAL: dict[str, str] = {
    "Financial Services": "Financial Services",
    "Healthcare": "Healthcare",
    "Technology": "Information Technology",
    "Consumer Defensive": "FMCG & Consumer Staples",
    "Consumer Cyclical": "Consumer Discretionary",
    "Energy": "Energy",
    "Utilities": "Power & Utilities",
    "Industrials": "Capital Goods & Industrials",
    "Real Estate": "Realty & Construction",
    "Communication Services": "Telecommunication & Media",
}


def sector_for(symbol: str) -> tuple[str | None, str]:
    """Canonical materiality bucket for a symbol, and which source resolved it.

    Tries the local instruments master first (no network call); falls back to
    a live yfinance point lookup only when NSE's Nifty-500-only coverage
    misses. Returns (None, "uncovered") if neither resolves — never guessed.
    Second element is "nse" / "yfinance" / "uncovered", carried into the
    digest's Sources footer so provenance stays honest per-symbol.
    """
    symbol = symbol.strip().upper()
    nse_label = instruments.industry_for(symbol)
    if nse_label and nse_label in NSE_TO_CANONICAL:
        return NSE_TO_CANONICAL[nse_label], "nse"

    try:
        info = yf.Ticker(f"{symbol}.NS").info
    except Exception:
        return None, "uncovered"

    yf_sector = info.get("sector")
    if yf_sector == "Basic Materials":
        industry = (info.get("industry") or "").lower()
        return ("Chemicals" if "chemical" in industry else "Metals & Mining"), "yfinance"
    if yf_sector in YFINANCE_TO_CANONICAL:
        return YFINANCE_TO_CANONICAL[yf_sector], "yfinance"
    return None, "uncovered"


# Sector-specific materiality signals, authored once per canonical bucket.
# Each entry: what actually moves this kind of business, not a generic
# financial-news list. Severity is "does this deserve attention", never
# "is this good or bad" — valence/prediction is out of scope by design.
SECTOR_SIGNALS: dict[str, list[dict[str, Any]]] = {
    "Financial Services": [
        {
            "signal": "RBI policy action",
            "keywords": [
                "rbi", "repo rate", "monetary policy", "reserve bank of india", "crr", "slr",
                "mpc", "monetary policy committee", "cash reserve ratio", "statutory liquidity ratio",
                "rbi governor",
            ],
            "severity": "high",
            "rationale": "First-order relevance for lending margins and credit growth across banks and NBFCs.",
        },
        {
            "signal": "Asset quality",
            "keywords": [
                "npa", "non-performing asset", "asset quality", "slippage", "provisioning", "bad loan",
                "gross npa", "net npa", "restructured loan", "stressed asset", "write-off",
            ],
            "severity": "high",
            "rationale": "Direct signal of credit-book health, the core driver of financial-services earnings.",
        },
        {
            "signal": "Credit growth / margins",
            "keywords": [
                "credit growth", "loan growth", "casa", "deposit growth", "net interest margin", " nim ",
                "disbursement growth", "aum growth", "cost of funds",
            ],
            "severity": "medium",
            "rationale": "Core operating metric for banks/NBFCs; moves margins and growth outlook.",
        },
        {
            "signal": "Capital / rating action",
            "keywords": [
                "capital adequacy", "rating downgrade", "rating upgrade", "car ratio",
                "qip", "rights issue", "crar", "capital raise",
            ],
            "severity": "medium",
            "rationale": "Affects funding cost and regulatory headroom.",
        },
    ],
    "Automobile & Auto Components": [
        {
            "signal": "Monthly volumes",
            "keywords": [
                "monthly sales", "vehicle sales", "volume growth", "dispatch", "wholesale volume",
                "export volume", "domestic sales", "units sold", "market share",
            ],
            "severity": "high",
            "rationale": "Primary monthly demand signal the market prices auto stocks on.",
        },
        {
            "signal": "Input costs",
            "keywords": [
                "steel price", "commodity cost", "semiconductor shortage", "chip shortage", "input cost",
                "raw material price", "rare earth magnet",
            ],
            "severity": "medium",
            "rationale": "Directly affects margins in a low-margin, high-volume business.",
        },
        {
            "signal": "EV / PLI policy",
            "keywords": [
                "ev policy", "pli scheme", "electric vehicle", "fame scheme", "production linked incentive",
                "battery cost", "charging infrastructure",
            ],
            "severity": "medium",
            "rationale": "Structural policy shift affecting long-term positioning, not just a quarter's numbers.",
        },
        {
            "signal": "Discounting / channel stress",
            "keywords": ["discount", "dealer inventory", "inventory pile-up", "channel inventory", "unsold inventory"],
            "severity": "medium",
            "rationale": "Signals demand weakness or channel stress before it shows up in reported numbers.",
        },
    ],
    "Healthcare": [
        {
            "signal": "USFDA action",
            "keywords": [
                "usfda", "us fda", "warning letter", "import alert", "form 483", "fda inspection",
                "483 observations", "oai classification", "establishment inspection report",
            ],
            "severity": "high",
            "rationale": "Can halt US exports for the flagged facility — first-order revenue risk for export-heavy pharma.",
        },
        {
            "signal": "Approval / patent",
            "keywords": [
                "anda approval", "patent", "clinical trial", "drug approval", "nda filing",
                "abbreviated new drug application", "biosimilar approval", "manufacturing license suspended",
            ],
            "severity": "high",
            "rationale": "New approvals or patent outcomes are direct pipeline/revenue events.",
        },
        {
            "signal": "Price control",
            "keywords": ["nppa", "price control", "drug pricing", "essential medicine", "dpco", "ceiling price"],
            "severity": "medium",
            "rationale": "Regulatory price caps directly compress margins on affected products.",
        },
    ],
    "Information Technology": [
        {
            "signal": "Deal win",
            "keywords": [
                "deal win", "contract win", "tcv", "total contract value", "wins order", "partnership",
                "multi-year deal", "large deal", "order booking",
            ],
            "severity": "high",
            "rationale": "Direct revenue-pipeline signal for services-led IT businesses.",
        },
        {
            "signal": "Guidance",
            "keywords": [
                "revenue guidance", "margin guidance", "outlook cut", "outlook raised",
                "guidance cut", "guidance raised", "demand environment",
            ],
            "severity": "high",
            "rationale": "Management's own forward view of demand — the market's primary anchor for IT valuations.",
        },
        {
            "signal": "Attrition / currency",
            "keywords": [
                "attrition", "currency headwind", "usd/inr", "rupee depreciation", "h-1b", "visa",
                "utilization rate", "bench strength",
            ],
            "severity": "medium",
            "rationale": "Affects margins (currency, wage cost) or delivery capacity (attrition, visas).",
        },
    ],
    "FMCG & Consumer Staples": [
        {
            "signal": "Demand mix",
            "keywords": [
                "rural demand", "urban demand", "volume growth", "same-store sales",
                "rural recovery", "consumption slowdown", "premiumisation",
            ],
            "severity": "medium",
            "rationale": "Core demand signal for staples, historically the swing factor in FMCG earnings.",
        },
        {
            "signal": "Input costs",
            "keywords": ["palm oil", "input cost", "raw material cost", "crude derivative", "edible oil price", "packaging cost"],
            "severity": "medium",
            "rationale": "Commodity-linked input costs are the primary margin lever for FMCG.",
        },
        {
            "signal": "Regulatory / duty change",
            "keywords": ["gst", "import duty", "excise duty", "customs duty"],
            "severity": "medium",
            "rationale": "Tax/duty changes flow directly to pricing and margin.",
        },
    ],
    "Consumer Discretionary": [
        {
            "signal": "Demand / footfall",
            "keywords": [
                "same-store sales", "footfall", "occupancy", "same store sales",
                "store addition", "online sales", "e-commerce sales",
            ],
            "severity": "medium",
            "rationale": "Primary demand signal for discretionary consumer/retail/hospitality businesses.",
        },
        {
            "signal": "Input costs",
            "keywords": ["input cost", "raw material cost"],
            "severity": "medium",
            "rationale": "Margin driver for discretionary manufacturers/retailers.",
        },
    ],
    "Metals & Mining": [
        {
            "signal": "Commodity cycle",
            "keywords": [
                "commodity price", "steel price", "iron ore", "china demand", "lme",
                "aluminium price", "copper price", "coking coal",
            ],
            "severity": "high",
            "rationale": "Metals earnings are almost entirely a function of the commodity price cycle.",
        },
        {
            "signal": "Capacity / duty",
            "keywords": ["capacity utilization", "import duty", "export duty", "capacity expansion", "mining lease"],
            "severity": "medium",
            "rationale": "Affects near-term volume and realized pricing.",
        },
    ],
    "Chemicals": [
        {
            "signal": "Feedstock / pricing cycle",
            "keywords": ["feedstock", "input price", "china dumping", "capacity addition", "naphtha price", "anti-dumping duty"],
            "severity": "medium",
            "rationale": "Chemicals margins move with feedstock cost and Chinese oversupply/dumping cycles.",
        },
        {
            "signal": "Export demand",
            "keywords": ["export demand", "export order", "specialty chemical demand"],
            "severity": "medium",
            "rationale": "Significant revenue driver for export-oriented specialty chemical names.",
        },
    ],
    "Energy": [
        {
            "signal": "Crude / refining margins",
            "keywords": ["crude price", "refining margin", "grm", "gross refining margin", "brent crude", "marketing margin"],
            "severity": "high",
            "rationale": "Refining/marketing margins are the primary earnings driver for oil & gas majors.",
        },
        {
            "signal": "Subsidy / fuel pricing",
            "keywords": ["subsidy", "under-recovery", "fuel pricing", "lpg subsidy", "fuel price hike"],
            "severity": "medium",
            "rationale": "Government pricing/subsidy policy directly affects realized margins.",
        },
    ],
    "Power & Utilities": [
        {
            "signal": "Plant / tariff",
            "keywords": [
                "plant load factor", "plf", "tariff order", "power purchase agreement",
                "discom", "transmission license",
            ],
            "severity": "medium",
            "rationale": "Core operating/regulatory metrics that set utility revenue and returns.",
        },
        {
            "signal": "Fuel cost",
            "keywords": ["fuel cost", "coal linkage", "fuel supply agreement", "imported coal", "gas price"],
            "severity": "medium",
            "rationale": "Fuel cost pass-through affects near-term realized margin.",
        },
    ],
    "Capital Goods & Industrials": [
        {
            "signal": "Order book",
            "keywords": [
                "order book", "order inflow", "order win", "l1 bidder",
                "lowest bidder", "work order", "contract awarded",
            ],
            "severity": "high",
            "rationale": "Order inflow is the leading indicator for future revenue in project-based industrials.",
        },
        {
            "signal": "Execution / receivables",
            "keywords": ["execution delay", "project delay", "working capital", "cost overrun", "receivable delay"],
            "severity": "medium",
            "rationale": "Execution and working-capital stress are common early warning signs in this sector.",
        },
    ],
    "Realty & Construction": [
        {
            "signal": "Pre-sales / launches",
            "keywords": [
                "pre-sales", "launches", "bookings", "inventory",
                "project launch", "land acquisition", "joint development agreement",
            ],
            "severity": "high",
            "rationale": "Pre-sales/launch volume is the primary forward revenue indicator for realty.",
        },
        {
            "signal": "Rates / approvals",
            "keywords": ["interest rate", "approval delay", "rera", "occupancy certificate", "environmental clearance"],
            "severity": "medium",
            "rationale": "Buyer affordability (rates) and regulatory approvals directly gate realty demand.",
        },
    ],
    "Telecommunication & Media": [
        {
            "signal": "ARPU / subscribers",
            "keywords": ["arpu", "subscriber addition", "tariff hike", "churn", "5g rollout", "spectrum auction"],
            "severity": "high",
            "rationale": "ARPU and subscriber trends are the core earnings drivers for telecom.",
        },
        {
            "signal": "Ad / content economics",
            "keywords": ["ad revenue", "advertising revenue", "content cost", "viewership", "subscription revenue", "ott platform"],
            "severity": "medium",
            "rationale": "Advertising and content economics are the primary earnings driver for media.",
        },
    ],
}

# Sector-agnostic fallback — broader than red-flag-scan's governance-only
# list, since this scores general materiality (positive, neutral, or
# negative), not just red flags.
GENERIC_SIGNALS: list[dict[str, Any]] = [
    {
        "signal": "Results / guidance",
        "keywords": [
            "quarterly results", "q1 results", "q2 results", "q3 results", "q4 results",
            "earnings summary", "earnings call", "earnings miss", "earnings beat",
            "financial results", "profit warning",
            "board meeting outcome", "standalone results", "consolidated results",
        ],
        "severity": "high",
        "rationale": "Quarterly results and management guidance are the single largest scheduled catalyst for any stock.",
    },
    {
        "signal": "Litigation",
        "keywords": [
            "litigation", "lawsuit", "sues", "legal notice", "court order", "arbitration",
            "writ petition", "injunction", "class action",
        ],
        "severity": "high",
        "rationale": "Legal action carries direct financial and reputational exposure regardless of sector.",
    },
    {
        "signal": "Regulatory order",
        "keywords": [
            "sebi order", "regulatory action", "show cause notice", "penalty imposed", "fine imposed",
            "cci order", "adjudication order", "compliance notice",
        ],
        "severity": "high",
        "rationale": "Regulatory action is a direct, sector-agnostic risk signal.",
    },
    {
        "signal": "M&A / stake change",
        "keywords": [
            "acquisition", "merger", "stake sale", "divestment", "acquires",
            "open offer", "slump sale", "demerger", "scheme of arrangement", "joint venture",
        ],
        "severity": "high",
        "rationale": "Ownership/structure changes are first-order events for valuation and strategy.",
    },
    {
        "signal": "Rating action",
        "keywords": [
            "credit rating", "rating downgrade", "rating upgrade", "outlook revised",
            "placed on watch", "negative outlook", "positive outlook",
        ],
        "severity": "medium",
        "rationale": "Rating actions affect funding cost and can trigger covenant/investor-mandate thresholds.",
    },
    {
        "signal": "Capacity expansion",
        "keywords": [
            "capacity expansion", "new plant", "expansion plan", "capex announcement",
            "brownfield expansion", "greenfield project", "commissioning of plant",
        ],
        "severity": "medium",
        "rationale": "Signals a shift in the company's growth/investment trajectory.",
    },
    {
        "signal": "Leadership change",
        "keywords": [
            "resign", "appointed as", "new ceo", "new cfo", "management change", "steps down",
            "quits as", "additional charge", "elevated to",
        ],
        "severity": "medium",
        "rationale": "Leadership continuity is a standard governance/execution-risk signal.",
    },
]


def score_items(
    symbol: str,
    canonical_sector: str | None,
    items: list[dict[str, Any]],
    text_fields: list[str],
    ref_fields: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Score a list of news/announcement items against the materiality rubric.

    GENERIC_SIGNALS (results, litigation, regulatory action, M&A, rating
    action, capacity expansion, leadership change) always apply — those
    matter regardless of sector. SECTOR_SIGNALS[canonical_sector] is added on
    top when a sector resolved, for sector-specific nuance a generic list
    can't capture (e.g. RBI policy action for banks). text_fields: which
    keys on each item to search (e.g. ["title"] for news, ["desc",
    "attchmntText"] for NSE announcements). ref_fields: keys on the matched
    item to carry through onto the flag as-is (e.g. ["link"] for news,
    ["attchmntFile"] for announcements) — avoids the caller having to
    reverse-match a truncated evidence snippet back to its source item.
    Returns one flag per matched signal per item — never a valence/predictive
    judgment, just "this item mentions X, which is the pre-written reason X
    matters."
    """
    symbol = symbol.strip().upper()
    signals = list(GENERIC_SIGNALS)
    if canonical_sector and canonical_sector in SECTOR_SIGNALS:
        signals += SECTOR_SIGNALS[canonical_sector]
    flags = []
    for item in items:
        haystack = " ".join(str(item.get(f, "")) for f in text_fields).lower()
        for sig in signals:
            if any(kw in haystack for kw in sig["keywords"]):
                flag = {
                    "symbol": symbol,
                    "signal": sig["signal"],
                    "severity": sig["severity"],
                    "rationale": sig["rationale"],
                    "evidence": str(item.get(text_fields[0], ""))[:200],
                }
                for rf in ref_fields or []:
                    flag[rf] = item.get(rf)
                flags.append(flag)
    return flags
