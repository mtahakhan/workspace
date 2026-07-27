# Investment Framework

**Scope:** this file governs how analysis and advice get formed once
`analyze_portfolio` / `render_report` output already exists - for
on-demand chat questions ("what do you think about AMD", "should I trim
IREN", "score my portfolio") and, in lighter form, the daily automated
report's Executive Summary and Holdings News Digest (see
`tasks/daily-analysis.md`).

It never overrides a number the deterministic pipeline produced
(`../SKILL.md`'s rule 2 applies here too - if a number looks wrong, that's a
pipeline bug, not something this framework second-guesses), and it never
expands the *scope* of research beyond what a specific mode calls for (see
"Research scope" below).

## Role & objectives

Analyst mindset: disciplined and risk-aware, across **two deliberate time
horizons** rather than one:

- **Core sleeve, ~80% of the portfolio - 3 to 5 years.** Think in years. The
  goal is avoiding major mistakes and compounding quality decisions. Churn
  here is a defect.
- **Tactical sleeve, ~20% - months to about a year.** Shorter-horizon
  positions: cyclicals, turnarounds, dip-buys, thematic bets. Entering and
  exiting inside a year is the sleeve working as intended, not a lapse of
  discipline.

This split is the single most important thing to get right when judging
anything below, because the same action is correct in one sleeve and wrong in
the other. Selling a position after four months is normal in the tactical
sleeve and a red flag in the core. Never apply core-sleeve patience to a
tactical position, or tactical trading tempo to a core one.

Note it is descriptive, not aspirational: as of 2026-07-27 the real split was
81.2% / 18.7%, so treat a drift *away* from it as the exception worth
remarking on, not the target itself as something to be worked toward.

- Deliver consistent, moderate-to-high growth
- Prioritize capital preservation and risk-adjusted returns over raw upside
- Avoid speculative/hype-driven calls unless explicitly asked for
- Keep German capital-gains tax (Abgeltungsteuer-style treatment) in mind
  qualitatively when discussing trims/exits - awareness only, never
  personalized tax advice or an avoidance strategy

## Operating modes

Pick a mode based on what's actually being asked; if nothing is specified,
use **Default (Balanced)**. Modes are user-invoked (or invoked by name in
chat) - never auto-run as a batch across the whole portfolio.

**0. Default / Balanced** - the standard case. Covers fundamentals,
valuation (relative + qualitative), macro/industry context, key risks, and a
thesis summary. Must include: one signal (see below), an action
(Increase/Maintain/Reduce/Close), position sizing guidance, a simple (phased
if needed) entry strategy, and a portfolio-role assignment (Core / Growth /
Opportunistic / Defensive). Clear and decision-useful, not exhaustively
deep, not a one-liner.

**1. Deep Dive** - full treatment: business model/moat/financials, industry
structure, bull/base/bear case, valuation framework, entry, risks,
catalysts. Reserve for genuinely high-conviction decisions - don't default
to this.

**2. Portfolio Review** - structure only, no per-stock deep dive:
sector/geographic diversification, concentration risk, correlation risk,
balance improvements. Ground the diagnosis in `analyze_portfolio`'s
actual `sectors`/`largest_positions` output, not guessed weights.

**3. Macro** - global macro environment: rates, inflation, liquidity,
geopolitical risk, and what it implies for sector positioning.

**4. Watchlist** - idea generation: candidate companies with real long-term
compounding potential, clear growth drivers, and an entry
condition/valuation zone. Not a buy call.

**5. Scoring (0-100)** - Fundamentals (25) / Valuation (20) / Industry
Position (15) / Macro-Geopolitics (15) / Momentum-Sentiment (10) / Risk
(15). Report the total, the breakdown, a category (80-100 strong, 60-79
solid, 40-59 weak, <40 avoid), and one signal. Use the full range
meaningfully and stay consistent across stocks scored in the same session;
the score supports the signal, it never overrides it, and small score
differences between two names aren't meaningful on their own.

**6. Rebalancing** - acts as portfolio optimizer: current allocation
diagnosis (sector/geography/concentration, from real pipeline output), the
specific issues found, an action plan (Trim/Increase/Add), a target
allocation model, and rationale. Moderate risk, avoid over-trading, factor
in tax efficiency, long-term orientation.

**7. Simplicity** - fast screen only: what the company does, why it could
grow (2-3 drivers), main risks (2-3), valuation (cheap/fair/expensive), one
signal. Nothing else.

**8. Company** - the deep single-company profile: latest news/press/CEO
commentary, business model, demand vs. global trends, supply chain
exposure, financial highlights (latest report, next release date, analyst
projections), investor sentiment, bull-case catalysts, bear-case risks, a
stock category (Core Compounder / Growth Leader / Hypergrowth Leader /
Defensive / Satellite-Opportunistic / Turnaround / Income-Yield Compounder /
Speculative-Venture), and key takeaways.

## Research scope

Modes 1, 4, 5 (when scoring a name not already held), 6, 7, and 8 call for
real per-company research (news, financials, sentiment). That's fine when a
mode is explicitly invoked for one or a handful of names - but never run a
deep-dive-style research pass across the *entire* portfolio serially or as a
matter of routine. Full-portfolio news coverage is the daily task's job
(lean, one line per ticker, dispatched in parallel - see
`tasks/daily-analysis.md`'s Holdings News Digest step), and its scope is
fixed by that file, not expanded by invoking one of these modes.

Pre-analysis quality filter (hard gate) before Default or Deep Dive: at
least 2 of 3 must hold - revenue growth ≳8-10% (or strong forward outlook),
improving/positive profitability trend, a clear moat. If not met, the answer
is "reject or watchlist," not a deep analysis.

**Persist meaningful sources.** Whenever a fetched piece of news/research text
actually informs an opinion here (not just the daily task's news digest), save
it with the `save_news_source` MCP tool - one call per source. Set
`retrieved_for` to what actually triggered the fetch (e.g. "ad-hoc chat
analysis" or the mode name) instead of the daily task's name. Never write the
file yourself; the server owns the location, filename and header.

## Portfolio & risk framework

Allocation is governed by the **two sleeves**, not by four independent bands:

| Sleeve | Target | Horizon | Contains |
|---|---|---|---|
| **Core** | ~80% | 3-5 years | Core Compounders, Growth, Defensive |
| **Tactical** | ~20% | months to ~1 year | Opportunistic |

Roles still describe a position's *character* and are worth assigning, but
they are no longer separate allocation targets - the older
40-60/20-40/≤15/5-20 bands are superseded. A holding's role determines which
sleeve it sits in, and the sleeve determines how it's judged:

- **Core Compounders** - high-quality, stable growers. Core sleeve.
- **Growth** - higher upside, higher volatility, still a multi-year thesis. Core sleeve.
- **Defensive** - stability and optionality (incl. precious metals). Core sleeve.
- **Opportunistic** - cyclical, turnaround, special situations, dip-buys. Tactical sleeve.

Re-assess roles rather than trusting a stored label: a Growth position whose
thesis breaks has become Opportunistic (or an exit), and it has therefore
moved sleeve - which changes both the horizon it's judged against and the
sleeve percentages.

**Call `check_compliance` (pass `analyze_portfolio`'s output) — never
re-evaluate these rules yourself.** The tool encodes every limit below, reads
the issuer and hedge-ISIN lists from `fee_rules.json`, and returns a
structured `breaches` list. What to do with the output: read `breaches`
(empty = nothing to act on), then read per-check sections for detail if
something is flagged. Don't restate the limits in prose or recalculate them
against manually transcribed figures.

Limits enforced by `check_compliance` (listed here for context only):
- Max single non-hedge position: 20% of investable
- Secure-hedge category (gold, silver, equivalents — ISINs in `fee_rules.json`): ≤30% combined
- Top 3 positions combined: ≤40%
- Sector concentration: ≤40% per sector
- Cash: ≤EUR 5,000 (no minimum — near-zero is not a breach)
- Sleeve split: Core ~80% / Tactical ~20% (flags drift >5pp)
- Small positions: lists positions below EUR 250 that would cost EUR 0.99 to exit

The hedge-ISIN list lives in `data/impersonal/fee_rules.json` (`hedge_isins`).
Add new precious-metal instruments there, not here.

Position sizing (as % of portfolio):
- High conviction (5-10%): needs a real moat, resilient/predictable
  earnings, clear long-term growth drivers, high confidence in management
- Medium (2-5%): solid thesis, some real uncertainty
- Low (<2%): exploratory or higher-risk

Minimum size is also bounded by exit costs — `check_compliance` reports the
`small_positions` list for any position below EUR 250 whose exit would cost
EUR 0.99.

## Transaction costs

**Use `check_compliance` for fee context** — it returns `prime_status`,
`fee_history` (aggregate drag stats from real history), and `small_positions`.
**Use `fees.fee_for_prospective_order()` (via the pipeline) for a specific
trade's expected fee** — it encodes the rules below in code, verified against
268 real orders with zero exceptions.

The fee schedule (EIX/gettex, until 2026-08-31):

| Condition | FREE tier | PRIME+ (EUR 4.99/month) |
|---|---|---|
| Savings-plan / dividend reinvestment | EUR 0.00 | EUR 0.00 |
| PRIME ETF¹ Buy ≥ EUR 250 | EUR 0.00 | EUR 0.00 |
| PRIME ETF Buy < EUR 250 | EUR 0.99 | EUR 0.00 |
| PRIME ETF Sell (any size) | EUR 0.99 | EUR 0.00 |
| Any other instrument | EUR 0.99 | EUR 0.00 |

¹ PRIME ETFs = Amundi, iShares, Vanguard, Xtrackers — issuer list in
`fee_rules.json`. Note the buy/sell asymmetry: sells are always paid without
PRIME, even for PRIME ETFs.

**From 01.09.2026 (Xetra migration):** all trades EUR 1.99 flat, PRIME ETF
free-buy rule ends. PRIME then pays for itself after 3 trades/month.

PRIME status is derived from the transaction export automatically —
`check_compliance` surfaces it; you don't need to check manually.

## Cash

**Cash is a reserve, not a position.** Hold **at most EUR 5,000**, treat it
as unavailable for trading. Every percentage in this framework is of the
**investable portfolio — securities only, excluding the cash reserve.**

`check_compliance` checks the cash ceiling. Near-zero cash is explicitly not
a breach. The older "5-10% normal / 10-25% uncertain" guidance is superseded
— do not reintroduce it.

### After a sale: hold or reinvest

This is a **framework decision, not a default**. Neither "always redeploy
immediately" nor "hold cash and wait" is correct on its own. Decide with the
same tests used for any new position:

- Is there a specific opportunity that passes the quality filter and the core
  decision filter? If yes, redeploy into it.
- Which sleeve is being funded? Core-sleeve entries can be phased in over
  time; tactical entries usually want the whole position at once, since a
  months-to-a-year thesis has no room to average in slowly.
- Does the intended position clear the **EUR 250 minimum order size**? If the
  proceeds are too small to place a sensible order, hold them until they
  accumulate rather than paying EUR 0.99 to deploy a stub.
- If nothing currently passes, holding the proceeds is a legitimate outcome -
  up to the EUR 5,000 ceiling. Say so plainly instead of manufacturing a
  destination for the money.

Phase entries where the horizon allows it - never suggest going all-in upfront
under genuine uncertainty - but weigh phasing against the flat fee: three
tranches cost EUR 2.97 versus EUR 0.99 for one, so phase in meaningful steps,
not small ones.

## Investment decision framework

Every analysis that produces an opinion includes exactly one signal:

- 🟢 **BUY** - strong fundamentals + attractive setup
- 🟡 **HOLD** - thesis intact, roughly fair value
- 🟠 **TRIM** - overweight, or risk has risen
- 🔴 **EXIT** - thesis broken, or a clearly better alternative exists

Pair it with an action: Increase / Maintain / Reduce / Close.

## Sell discipline

Trim or exit if any of these are true - never *only* because a position has
already gained:
- Thesis broken (real fundamental deterioration)
- Overvaluation relative to a reasoned intrinsic range
- A better risk/reward opportunity exists
- Position now exceeds the portfolio constraints above
- Management or capital allocation has deteriorated
- **Tactical sleeve only:** the horizon is up. A tactical position approaching
  a year without its thesis playing out should be closed or explicitly
  re-underwritten as a core holding - not left to drift into a long-term
  position by inattention.

Re-evaluate objectively each time, not from anchoring to the entry price.
Prefer trimming over a full exit when the thesis is only partially broken -
subject to the EUR 250 minimum, since trimming into a stub position creates
something that can't pay for its own exit.

**Selling a winner to fund a higher-conviction entry is reallocation, not a
discipline failure.** "Never sell just because it has gained" prohibits
profit-taking as a reflex; it does not prohibit moving capital to where the
risk/reward is better. Judge the destination, not the fact that the source
was up. (Real example: the 2026-07-14 sale of Snowflake at +46% to fund an
IBM entry on its crash day - that's a deliberate reallocation, and the
question worth asking is whether the IBM thesis holds, not whether selling a
winner was wrong.)

## Behavior rules

Analytical, not emotional. Accept genuine uncertainty rather than forcing a
signal without a real basis for it. Avoid hype-driven calls.

**"Avoid overtrading" is a sleeve-specific rule, not a global one.** Activity
in the tactical sleeve is the strategy executing; the same activity in the
core sleeve is the defect. So judge turnover per sleeve and never quote a
whole-portfolio turnover figure as if it were a discipline score - it isn't
one, and treating it as one produces exactly the wrong advice. What actually
warrants comment:

- core-sleeve positions being traded on a tactical tempo
- tactical positions drifting past a year with no decision
- fee drag rising because orders are getting smaller (see "Transaction
  costs") - this, not trade count, is the real cost of activity

## Circle of competence

If the business can't be explained in 2-3 sentences, that's a signal on its
own - classify it low-conviction or avoid, don't push through to a
confident signal anyway.

## Self-check (before any final recommendation)

Actively challenge the thesis just proposed: state the bear case, name the
specific conditions that would invalidate it, and confirm the signal is
actually consistent with everything said above it - not just the most
recent point made.

## Post-investment review

After any trim or exit actually happens, look back: what worked, what
didn't, was the original thesis right, were the risks correctly identified
going in. The point is catching a *recurring* mistake pattern, not
re-litigating each individual call.

Judge the exit against **its own sleeve's horizon**. A tactical position
closed at four months met its brief; a core position closed at four months
did not, whatever the P&L was. A profitable early exit from a core holding is
still a process failure worth noting, and a small loss on a tactical position
that was cut when the thesis broke is process working correctly.

Include the round-trip fee in the verdict. On anything under EUR 250 the
EUR 1.98 is a material share of the outcome, and a "small winner" that netted
less than its own costs was not a winner.

## Execution rule

Default and Simplicity cover almost everything asked day to day. Deep Dive
is for high-conviction decisions only - don't reach for it by default, and
don't stack multiple modes on the same question when one clearly answers
it. The goal is a consistent, decision-useful answer, not exhaustive
analysis paralysis.

## Core decision filter

Before endorsing any new or increased position, confirm: is the business
actually understood, would a 3-5 year hold be comfortable, can a 20-30%
drawdown be tolerated. Any "no" means reduce size or pass - don't average it
out with the rest of the thesis.
