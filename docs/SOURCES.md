# Sources and terms of use

rankai fetches only from public endpoints: official APIs, RSS feeds, public ATS (applicant tracking system) job-board
endpoints, a government open-data API and the GitHub search API. Each result keeps the original link and names its
source. Where a source's license or terms ask for attribution, the text is stored in `rankai/sources.py: ATTRIBUTION`.

**This page records what each source's terms, robots.txt and API documentation said when they were read on 2026-10-29
and 2026-10-30.** It is not legal advice, and terms change. Read each source's current terms before you run its
fetcher, and use the data the way those terms allow. The evidence pages saved during the review (robots.txt, terms
and API docs) are not in this repository.

## Rules the fetchers follow

- Keep every limit a source documents (`rankai/ingest.py: MIN_GAP_H` and pauses in `rankai/sources.py`).
- **robots.txt vs. official API docs.** If a provider's own documentation invites calls to an API and every
  documented limit is kept, the API is used even when robots.txt disallows that path. Remotive is the only case
  (`Disallow: /api/*`). This rule does not cover undocumented endpoints.
- Undocumented endpoints are used only after an explicit decision, slowly, indexed locally and shown as title + link.
  ncss.cn is the only one, and it is opt-in in this repository (see below).
- No personal job-seeker posts: the V2EX `cv` node and Hacker News "SEEKING WORK" comments are excluded, and a filter
  drops seeker comments from the hiring threads.
- Contact details (email, phone, WeChat/QQ/Telegram IDs) are redacted from government-source text at fetch time, and
  from all free text before it goes to an external model or labeler (`rankai/text.py: redact`).
- Postings are used for local search and as features. No language model is trained on posting text.

## The 15 sources

| Source (`source`) | Access method | What it adds | Terms note (as read 2026-10-29/30) | Status |
|---|---|---|---|---|
| Greenhouse (`greenhouse`) | Public ATS job-board API, per company (~47 seed companies) | Full-time roles at tech and some non-tech employers | Public endpoint meant for showing a company's open jobs. Third-party use is not addressed in terms we found | Default |
| Ashby (`ashby`) | Public ATS job-posting API, per company (~20) | AI and dev-tool companies | Same as Greenhouse | Default |
| Lever (`lever`) | Public ATS postings API, per company (2) | Full-time roles | Same as Greenhouse | Default |
| SmartRecruiters (`smartrecruiters`) | Public Posting API, per company (7, capped at 150–300 each) | Non-tech employers | API docs describe it as the feed for career pages. Third-party use not verified. Companies on the smartrecruiters.com robots.txt opt-out list (e.g. Bosch) are skipped | Default |
| Himalayas (`himalayas`) | Official public API: browse feed + title search | Remote jobs; the largest supplier of good results | 60 requests/min, 10,000/day; credit Himalayas and link to the original | Default |
| Remotive (`remotive`) | Official public API | Remote jobs | At most 4 calls a day; link to the original and credit Remotive; data is delayed 24 h. robots.txt disallows `/api/*`; used under the docs-over-robots rule above | Default (**decision needed**, see below) |
| Jobicy (`jobicy`) | Official public API (7-day feed) | Remote jobs, many non-tech | At most one automated pass per hour; credit Jobicy; apply links must point to the original; storing allowed | Default |
| Arbeitnow (`arbeitnow`) | Official free API | European jobs (EN/DE) | Free; do not abuse; link to the original | Default |
| We Work Remotely (`wwr`) | Public RSS feeds (7 categories) | Remote jobs | robots.txt `Allow: /`; public RSS | Default |
| Hacker News (`hn`) | Algolia HN Search API | "Who is hiring" and "Freelancer? Seeking freelancer?" threads | Public API. Job-seeker comments excluded | Default |
| V2EX (`v2ex`) | Official API v1 / Atom feeds (`jobs`, `remote`, `outsourcing` nodes) | Chinese tech jobs and outsourcing | 120 requests/hour. `cv` node excluded (personal data) | Default |
| Ruby China (`rubychina`) | Public API v3, jobs node | Chinese tech jobs (small) | **Not reviewed in the 10-29 terms check** | Default (**decision needed**) |
| GitHub (`github`) | GitHub search API through an authenticated `gh` CLI | Open-source bounties (`bounty`, `💎 Bounty`, `help wanted`; issues commented on by the Algora and Opire bots) | GitHub API terms and rate limits. Algora's and Opire's own sites forbid automated access or mirroring, so their bounties are read only through GitHub search | Default (needs `gh auth login`) |
| Taiwan Jobs open data (`taiwanjobs`) | Government open-data XML API (data.gov.tw dataset 44062), per postal code | Taiwan jobs in every industry (Traditional Chinese) | Open Government Data License, version 1.0: any use, with the attribution text in `ATTRIBUTION`. No contact-detail field; text is still redacted | Default |
| ncss.cn, China's national graduate employment service (`ncss`) | **Undocumented** list JSON + public detail pages | Graduate jobs and internships in mainland China, all industries | No robots.txt (the path returns an HTML page). No terms found, only a copyright notice. Used under self-imposed conditions: at most one request every 5 s, local index only, results shown as title + link, contact details removed | **Opt-in** (**decision needed**) |

Corpus share on 2026-11-17 (82,169 postings): Himalayas 29,512 · ncss 12,714 · Greenhouse 10,859 · Arbeitnow 7,271 ·
Taiwan Jobs 5,781 · Jobicy 5,074 · Ashby 3,504 · SmartRecruiters 3,372 · GitHub 2,104 · WWR 779 · HN 502 · Lever 392 ·
V2EX 255 · Ruby China 31 · Remotive 19.

### Sources that need the owner's decision before a public release

None of the 15 sources' terms, as read, forbid automated access. Three are in a grey zone:

1. **ncss.cn.** The API is undocumented and no terms were found. It was used privately on the conditions above. In
   this repository the fetcher stays, but it is opt-in: `python -m rankai ingest` skips it, and it runs only when
   named (`python -m rankai ingest ncss`). Options: keep it opt-in (current), keep it in the default set, or remove
   the connector.
2. **Remotive.** Its API docs invite use, but its robots.txt disallows `/api/*`. It is kept under the
   docs-over-robots rule. It contributes 19 postings.
3. **Ruby China.** It uses a public API, but its terms were not part of the 10-29 review. It contributes 31 postings.
   Its terms should be checked, or the fetcher dropped.

The ATS endpoints (Greenhouse, Ashby, Lever, SmartRecruiters) are public by design. No terms we found address
third-party aggregation either way.

## Sources not used

| Source | Reason |
|---|---|
| RemoteOK | robots.txt blocks ClaudeBot, CCBot and other AI crawlers |
| LinkedIn, Indeed, Boss Zhipin, Lagou | Terms forbid scraping |
| V2EX `cv` node, HN "SEEKING WORK" | Individual job seekers' posts (personal data) |
| Freelancer.com, Contra, Dribbble, Behance, Zhubajie, Epwk, Zcool, Mihuashi, Proginn | Terms or technical measures forbid automated access (Freelancer's terms cover its API too; Zhubajie has CAPTCHA; Mihuashi signs requests) |
| Shixiseng, Nowcoder, China Public Employment (job.mohrss.gov.cn) | Terms forbid copying or reposting |
| Idealist, jobs.ac.uk, Hong Kong Labour Department, Hello Work, EURES, UK DWP | Need prior permission, are restricted to registered bodies, or are blocked by robots.txt |
| Gitee | robots.txt disallows `/api` |
| Indie Hackers, Reddit, YC co-founder matching, CoFoundersLab | robots.txt disallows everything, or login required |
| Algora, Opire websites | Terms forbid automated access or mirroring (their bounties come in through GitHub search instead) |
| IssueHunt, Polar, Gitcoin | No longer run open-source issue bounties |
| Canada Job Bank open data | License allows use, but it is a monthly snapshot without descriptions or employer names; sampled links had expired (HTTP 410) |
| Adzuna, USAJOBS | Terms allow use with a free key; not added (no key registered) |
| Hangzhou / Shanghai / Shenzhen government open data | Permissive licenses, but they need a registered (Shanghai, Shenzhen: identity-verified) account; not added |
| ReliefWeb jobs API | Content limited to personal, non-commercial use, with no redistribution; needs an approved app name; not added |
| Eleduck RSS | Reposting allowed only unmodified, with author and link, and not for posts marked "no reposting" (not visible in RSS); not added |
| MyCareersFuture (Singapore), NHS Jobs (UK) | Terms pages could not be read without JavaScript; not added |
| New Zealand Education Gazette | Its CC BY license explicitly excludes vacancy notices |
| Philadelphia city jobs, publicjobs.ie, careers.vic.gov.au | Rights reserved, personal non-commercial only, or no license found |

Two job sites (Workable, Teamtailor) declare `ai-train=no` in robots.txt. They are not used. If they were added, their
postings would need a "no training" flag.

## Gaps no permitted source fills

The 2026-10-29/30 review found no permitted source for:
- buyer-side outsourcing (someone looking for a provider to do a design or video project);
- co-founder searches outside tech;
- city-specific non-tech jobs in many cities.

See [EVALUATION.md](EVALUATION.md#coverage-gaps) for how these gaps show up in the results.
