# Product Actions

The shared vocabulary for the product reports this repo sends: scheduled emails and Telegram posts
for the product team. Language moved here from `Lascade-Co/actions` (the report sections) and from
the two former digest repositories (**Digest** and **Chat summary**).

## Language — Daily Catchup

The org-wide daily engineering report pipeline (`.github/workflows/daily-catchup.yml`):
discover active repos → summarise each with Claude → merge into one daily file → commit it
to the `catchup` repo and email a styled report.

**Catchup**:
The daily pipeline (and the `Lascade-Co/catchup` data repo) that captures the org's last 24h
of engineering activity.
_Avoid_: digest, standup.

**Daily file**:
The merged `daily/YYYY-MM-DD.json` — one entry per active repo with its developers, bullets,
and enrichment. The single source the commit and email steps both consume.
_Avoid_: report (that's the email), summary (that's per-repo).

**Per-repo summary**:
One repo's `summary-*.json` artifact: developers with Claude bullets plus enrichment.
Produced by the `summarize` matrix job.

**Enrichment**:
The non-commit signals attached to each repo summary — merged **PRs**, active **branches**,
the in-window release **version** tag, and the repo's **tags**. All best-effort.

**Status**:
A commit's delivery state, decided deterministically from branch/PR state in the per-repo
step (never by Claude): **Published** (reachable from the default branch), **Testing** (on a
branch with an open PR), **Work in Progress** (on a branch with no PR). Bullets are grouped
by status, and these are the email's section headings.
_Avoid_: Shipped, In Progress (earlier freeform names — superseded by these three)._

**Exclude list**:
`data/catchup_exclude.txt` — owner/repo names omitted from the daily email (one per line,
`#` comments allowed). A repo is **included by default**; add it here to opt out. Excluded
repos are still summarised and committed to the daily file. Seeded from repos lacking the
`catchup-mail` topic, then maintained by hand — the runtime no longer reads topics.

**Active repo**:
A repo with non-bot commits in the look-back window — the only repos that get summarised and
appear in the daily file. (There is no "inactive" list in the email.)

**Report JSON**:
The email's intermediate `report.json` — Claude prose (headline, Needs you, display names, one
cited bullet per work item) merged with authoritative numbers, the deterministic **status**
sections, the work no bullet cites (shown verbatim as "Also"), each product's facts line
(version, merged PRs), and the icons and author tags from the data files
(`catchup_icons.json`, `catchup_people.json`). The renderer turns it into the HTML email.

**Authoritative**:
A value not trusted from Claude — computed from git/GitHub (commit counts, contributor list,
PR count, version, branches, stats) or derived deterministically (the **status** split).
Claude supplies prose only (headline, Needs you, display names, bullets).

## Relationships — Daily Catchup

- The **discover** job lists **active repos**; **summarize** turns each into a **per-repo
  summary** with **enrichment**.
- **collect** merges all per-repo summaries into the one **daily file**.
- **commit** publishes the daily file to the **catchup** repo; **email** drops repos in the
  **exclude list**, builds the **report JSON**, and sends it. commit and email run in parallel.

## Language — Blog SEO Audit

The daily cron audit (`.github/workflows/seo-blog-audit.yml`) that checks the newest blogs on
each configured site against a fixed rule set and sends `report.html` to Telegram when
something is wrong.

**Blog**:
One article published at `www.<domain>/hub/<slug>`.
_Avoid_: post, article, hub page.

**Blog listing**:
The paginated index at `www.<domain>/hub` that an audit run reads to decide which blogs to
check.
_Avoid_: hub, blog index, archive.

**CMS**:
The WordPress installation where blogs are authored, reachable at the **origin** as a REST API
under `/wp-json/`.
_Avoid_: WordPress (in code identifiers), backend, hub.

**Origin**:
The `hub.<domain>` host the **CMS** serves from. Every non-asset path on it redirects to the
canonical host.
_Avoid_: hub host, CMS host, WP host.

**Asset URL**:
An **origin** URL under `/wp-content/uploads/` — the only class of origin URL allowed to reach
a crawler.
_Avoid_: static asset, upload, media URL.

**Crawlable position**:
A place in served HTML where a URL is a navigational signal to a crawler — `a[href]`,
canonical, `og:url`, hreflang, JSON-LD `url`/`@id`/`item`, sitemap `loc`. A URL merely present
elsewhere in the markup is not in a crawlable position.
_Avoid_: visible link, public link.

**Contextual internal link**:
An `a[href]` inside the selected blog article body that points to a different path on the
canonical host. Site-wide navigation, headers, footers, asides, self-links, and sibling
subdomains do not count.
_Avoid_: site link, local link.

**Rule**:
One named check with a fixed ID (`A1`…`I4`), a slug, and a **severity**.
_Avoid_: test, validation, assertion.

**Finding**:
One instance of a **rule** firing against one **blog**.
_Avoid_: violation, issue, error (that's a severity).

**Severity**:
A rule's weight — **error** (crawl or index correctness is actively broken), **warn**
(threshold or hygiene), **info** (recorded for visibility, expected to be non-empty). Errors
and warns gate delivery; info never does.

**Suppressed rule**:
A rule named in a **site config**'s `suppress` list — still evaluated and still reported, but unable
to trigger its pipeline's consequence: delivery in an **audit run**. For known, accepted conditions;
a suppress entry means "accepted on this site" wherever it is read.
_Avoid_: disabled, ignored, muted.

**Site config**:
One entry in `data/seo_sites.json` — canonical host, **origin**, asset path prefixes, allowed
sibling subdomains, listing path, sitemap URL, blog count, thresholds, suppress list.

**Audit run**:
One execution of the audit for one **site config**. Sites run as parallel matrix jobs and
never share a report.

## Relationships — Blog SEO Audit

- A **site config** names exactly one **origin** and one **blog listing**.
- The **blog listing** yields the **blogs** an **audit run** checks (the first N in DOM order).
- Each **rule** yields zero or more **findings** per **blog**; **severity** decides whether an
  audit run delivers its report.
- **Origin** URLs are legitimate only as **asset URLs**. Any other origin URL is a **finding** —
  `error` when in a **crawlable position**, `warn` when merely present in the markup.

**Placeholder**:
A sized `<img>`/`<video>` stand-in in a draft, marked `data-placeholder`. An `error` (`D9`) in a published
**blog**.
_Avoid_: stand-in, dummy image, mock.

**Editor checklist**:
A block marked `data-strip-before-publish`, instructing its own deletion. An `error` (`D9`) in a published
**blog**.

## Language — Marketing Net

The daily cron (`.github/workflows/daily-marketing-net.yml`) that posts a three-image Telegram report:
month-to-date marketing net, cumulative marketing net, and per-day marketing net. Live results are not
persisted or booked; the closed March 2026 benchmark is retained only as an Infisical secret.

**Marketing net**:
Month-to-date revenue across the app stores minus month-to-date marketing spend.
_Avoid_: profit (the PNL app defines `gross_profit` and `contribution_profit` by different
formulas), influencer net, ROI, margin.

**Source**:
One contributor to the figure — **App Store** and **Play Store** on the revenue side, **Influencer**,
**Google Ads** and **Meta Ads** on the spend side. Each is read independently and fails
independently.

**Head**:
The PNL app's classification identity for a spend line, addressed by its `normalized_key`
(`INFLUENCER MARKETING`) and never by its manager-editable display name.
_Avoid_: category, bucket, line item.

**Unavailable**:
A **source** that yielded no figure this run — shown as `unavailable` and left out of the net, never
shown as `$0`, because a plausible zero is indistinguishable from a genuinely quiet month. Covers
both breakage and an empty **window** (the App Store on the 1st, whose window ends before the month
begins); the warning text distinguishes them, the state does not.
_Avoid_: missing, failed, null, zero.

**Window**:
The date span a **source** actually covers. Windows differ per source and are stated in the message
rather than clipped to match: the App Store stops at yesterday, every other source is fresh through
today.

**Net factor**:
The ratio of earnings to sales taken from the most recent **settled month**, applied to Play Store
month-to-date sales to estimate net. It exists because Google publishes no mid-month net figure.
_Avoid_: commission rate, take rate, multiplier.

**Settled month**:
A month whose Play Store bucket holds **both** a `sales/` and an `earnings/` report — the only kind
of month a **net factor** can come from. Earnings land around the middle of the following month.

**Rate date**:
The single date whose FX rates convert every non-USD amount in a run — always yesterday, the most
recent day a rate exists for. One date covers the whole run, including both sides of the **net
factor**.

**Benchmark**:
The closed March 2026 daily **source** data stored as base64 JSON. The comparison uses the same
day-of-month and the same per-source **windows** as the live report, then shows current **marketing
net** minus March **marketing net**. It is unavailable when any live **source** is unavailable.

**Complete marketing-net day**:
A calendar day for which all five daily **sources** are available. Because App Store publishes the
following day, marketing-net charts stop at yesterday even though the card includes today's Play
Store and spend values.

**Marketing-net estimate**:
The current month's average marketing net per **complete marketing-net day**, extended to the last
calendar day of the month. It is a run-rate projection, not a confidence forecast.

**Skip list**:
The Google Ads customer ids excluded from the MCC's children. Google Ads is include-by-default with
exclusions; Meta Ads is the opposite, an explicit list of accounts to read.

## Relationships — Marketing Net

- **Marketing net** = revenue **sources** − spend **sources**, each contributing over its own **window**.
- A **source** yields either an amount or **Unavailable**; there is no third state, and **Unavailable**
  is never coerced to `0`.
- The **marketing net** is itself **Unavailable** when no revenue **source** could be read — a net
  built from spend alone reads as a catastrophic loss to anyone who sees the figure before the
  warning.
- The **Play Store** source multiplies month-to-date sales by the **net factor** derived from the
  latest **settled month**.
- Every non-USD amount converts at the one **rate date** — including both sides of the **net factor**,
  so the ratio stays immune to FX drift.

## Language — Digests and chat summaries

The daily emails that were the `daily-email-digest-actions` and `chat-summary` repositories: web
revenue, app reviews, surveys, install → paid conversion, and the SalesIQ chat digests. Each goes out
in a Pacific and an Indian edition.

**Product report**:
A scheduled email or Telegram post for the product team: ad spend, catchup, install → paid, marketing
net, the digests and chat summaries, and the like. They live in this public, sealed repository.
_Avoid_: daily action.

**Digest**:
One daily email about one product area (web revenue, app reviews, a survey, install → paid
conversion). Digests share one look and one delivery routine.
_Avoid_: report (that is the umbrella for every product report), newsletter.

**Edition**:
The timezone-specific send of a **digest** or **chat summary**: PT (`America/Los_Angeles`, daylight
saving aware) or IST (`Asia/Kolkata`), each with its own recipients and its own local clock.
_Avoid_: region, locale, variant.

**Report date**:
The calendar day an email is about, read in its **edition**'s timezone. A report covers the window
from 05:00 on the previous day to 05:00 on the report date, and the subject names the report date.
When none is given, it is the latest day whose 05:00 local cutoff has passed.
_Avoid_: send date, run date.

**Hold**:
The wait between a finished build and the 05:55 local send, so every email lands at the same minute
regardless of how early it was built. A run that starts after the target sends at once, with its
original **report date**.
_Avoid_: delay, schedule, sleep.

**Delivery marker**:
The dated record that an **edition** of a report was sent for a **report date**. A later run that
finds the marker sends nothing. Previews and test sends never leave one, so they can never stand in
for a real delivery.
_Avoid_: sent flag, receipt, lock.

**Chat summary**:
A daily digest of Travel Animator or MarineRadar support chats. The day's chats are copied into a
dated sheet tab; each is translated, summarised and tagged, and the email combines saved summaries
with newly summarised ones, so the second **edition** can read what the first already processed.
A chat that could not be translated or summarised is left out, counted in the email, and retried on
the next run. It reads the current day's tab in Asia/Kolkata whatever the **report date** is.
_Avoid_: transcript digest, SalesIQ report.

## Relationships — Digests and chat summaries

- A **digest** or **chat summary** is sent once per **edition** per **report date**; the
  **delivery marker** is what makes a second attempt a no-op.
- The **hold** sits between building and sending, so a late build still sends with its original
  **report date** and never skips the day.
- A **chat summary** reads one sheet tab per product and combines saved and newly summarised chats.


## Example dialogue

> **Dev:** "How do I keep a noisy repo out of the email?"
> **Maintainer:** "Add it to data/catchup_exclude.txt. It's still summarised and committed
> to the daily file — it just won't show up in the *email*."

> **Dev:** "The A2 finding says the **origin** is leaking. Is the **blog listing** broken?"
> **Maintainer:** "No — the **blogs** render fine. The Next.js payload embeds **CMS** API URLs
> in the served HTML, so the origin is exposed in the markup but not in a **crawlable
> position**. That's why it's `warn` and not `error`. If it ever shows up in an `a[href]`,
> that's A1 and it's an `error`."

> **Dev:** "Meta's token expired overnight. Do we post $0 for it?"
> **Maintainer:** "No — it renders **unavailable** and drops out of the **marketing net**, with a
> warning line. A zero would read as 'we spent nothing on Meta this month', which is a different
> claim, and a much more believable one, than 'we couldn't ask'."

> **Dev:** "The PT build finished at 04:40. Why hasn't the email arrived?"
> **Maintainer:** "It is in the **hold**. Every **edition** sends at 05:55 local, so it waits.
> If the build had finished at 06:10 it would have sent at once, still dated with the original
> **report date**."

## Flagged ambiguities

- "summary" meant both the per-repo artifact and the emailed report — resolved: **per-repo
  summary** is the artifact, **report JSON** / email is the org-wide output.
- "influencer net" (the handoff document's name for the figure) — superseded by **Marketing net**
  once Google Ads and Meta Ads spend joined it; the old name described one of three spend lines and
  invited the reader to assume the other two were excluded.
- "net" — resolved: **Marketing net** is this figure only. The PNL app's `gross_profit` and
  `contribution_profit` are separate, computed differently, and this one is never called profit.
- "hub" meant three things — the CMS host, the blog index page, and the articles themselves.
  Resolved: **origin** is the host, **blog listing** is the index, **blog** is one article, and
  **CMS** is the authoring system. The word "hub" survives only as the literal URL path
  `/hub`, never as vocabulary.
- "report" meant any scheduled email and also one **report date**'s content — resolved: a
  **product report** is the email; the **report date** is the day it is about.

## Settled decisions — Install → paid

- 2026-11-04 — Android 4.0.x track deleted fully from the install→paid email (model, render,
  tests, crosscheck default builds); the Muscat alert-reconciliation SQL keeps 4.0 to stay matched
  with the alert producer. Why: series retired; no dead code; reconciliation must compare like cohorts.
- 2026-11-04 — `RULES` benchmark fingerprint left unchanged; `families` is historical.
  Why: editing it forces a benchmark secret rotation with no change to benchmark numbers.
- 2026-11-04 — meta-product-analysis install→paid stops excluding Android 5.x.
  Why: 5.x is now the whole Android base.
