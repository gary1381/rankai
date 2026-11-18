"""Public job / collaboration sources. Each fetcher yields (source_id, raw, normalized dict).

Terms we follow (checked 2026-10-29, see docs/SOURCES.md). Check each source's current terms yourself before running
a fetcher; the notes below record what was read on that date, not legal advice:
keep the original URL and name the source on every result; Remotive at most 4 calls a day; no RemoteOK (robots.txt
blocks AI crawlers); no Gitee (robots.txt disallows /api); no V2EX `cv` node and no HN "SEEKING WORK" comments
(individual job seekers, personal data).
An API the provider's own docs invite us to call is used even where robots.txt disallows its path (Remotive /api/*),
keeping every documented limit (project rule, 2026-10-29). Undocumented endpoints (ncss.cn) only after an explicit
owner decision, slowly, indexed locally and shown as title + link.
Government sources: contact details are removed from the text at fetch time (redact), not only before LLM calls.
"""
import http.client
import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from .db import connect
from .text import kind_of, plain, redact, remote_flag, salary_from_text

UA = {'User-Agent': 'Mozilla/5.0 (rankai research prototype; personal, non-commercial)', 'Accept': '*/*'}

# Seed companies with public ATS boards (probed 2026-10-29; slugs that 404 were dropped).
GREENHOUSE = ('anthropic databricks scaleai cloudflare gitlab figma stripe airbnb dropbox discord coinbase datadog '
              'mongodb vercel togetherai elastic samsara twilio okta pinterest instacart duolingo lyft reddit asana '
              # added 2026-10-29 for non-software roles and cities (health, education, retail, finance; Dublin, Toronto)
              'glossier sweetgreen peloton coursera khanacademy masterclass oscar flatironhealth zocdoc faire squarespace '
              'chime robinhood affirm brex intercom ziprecruiter everlane classpass monzo gocardless deliveroo').split()
ASHBY = ('openai perplexity cohere langchain pinecone modal replit notion linear ramp cursor elevenlabs supabase posthog '
         'sierra harvey baseten character lovable n8n').split()
LEVER = 'spotify zoox'.split()
# SmartRecruiters Posting API, employers not on the www.smartrecruiters.com robots.txt opt-out list (BoschGroup is).
SMARTRECRUITERS = {'SGS': 300, 'Equinox': 300, 'ServiceNow': 200, 'Experian': 200, 'WesternDigital': 150,
                   'Ubisoft2': 150, 'Sodexo': 150}

SOURCE_TYPE = {'greenhouse': 'ats', 'ashby': 'ats', 'lever': 'ats', 'smartrecruiters': 'ats', 'himalayas': 'board',
               'remotive': 'board', 'jobicy': 'board', 'arbeitnow': 'board', 'wwr': 'board', 'taiwanjobs': 'board',
               'ncss': 'board', 'hn': 'forum', 'v2ex': 'forum', 'rubychina': 'forum', 'github': 'code'}
# Fetched only when named on the command line (`python -m rankai ingest ncss`), never by a plain `ingest`: no
# published terms or API docs were found for it, so running it is the user's own decision (docs/SOURCES.md).
OPT_IN = {'ncss'}
# Attribution the source's licence or terms asks for; shown with results.
ATTRIBUTION = {'taiwanjobs': '資料來源：勞動部勞動力發展署「台灣就業通網站職缺清單」，政府資料開放授權條款-第1版',
               'ncss': '来源：国家大学生就业服务平台（ncss.cn）', 'remotive': 'Source: Remotive', 'jobicy': 'Source: Jobicy',
               'himalayas': 'Source: Himalayas', 'wwr': 'Source: We Work Remotely'}


def get(url: str, timeout: int = 40, raw: bool = False):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        b = r.read()
    return b if raw else json.loads(b)


def iso(v) -> str | None:
    """unix seconds / ms / ISO / RFC 822 -> ISO UTC."""
    if v in (None, ''):
        return None
    try:
        if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
            v = float(v)
            v = v / 1000 if v > 1e11 else v
            return datetime.fromtimestamp(v, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        for f in ('%a, %d %b %Y %H:%M:%S %z', '%Y-%m-%d %H:%M:%S'):
            try:
                d = datetime.strptime(v, f)
                return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            except ValueError:
                pass
        d = datetime.fromisoformat(v.replace('Z', '+00:00'))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except (ValueError, OSError):
        return None


def _salary(text: str, lo=None, hi=None, cur=None, period=None):
    if lo or hi:
        return dict(salary_min=float(lo or hi), salary_max=float(hi or lo), currency=(cur or 'USD').upper(),
                    period=period or 'year')
    s = salary_from_text(text)
    return dict(zip(('salary_min', 'salary_max', 'currency', 'period'), s)) if s else {}


def _period(p: str | None) -> str | None:
    p = (p or '').lower()
    for k, v in (('hour', 'hour'), ('month', 'month'), ('week', 'week'), ('day', 'day'), ('year', 'year'),
                 ('annual', 'year')):
        if k in p:
            return v
    return None


# ---------------------------------------------------------------- ATS boards (official employer sources)
def greenhouse(slug: str):
    for j in get(f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true').get('jobs', []):
        text = plain(j.get('content'))
        loc = (j.get('location') or {}).get('name') or ''
        yield str(j['id']), j, dict(
            url=j.get('absolute_url'), apply_url=j.get('absolute_url'), title=j.get('title'),
            org=j.get('company_name') or slug, location=loc, remote=remote_flag(loc, j.get('title')),
            kind=kind_of(j.get('title')), posted_at=iso(j.get('first_published') or j.get('updated_at')),
            tags=', '.join(d.get('name', '') for d in j.get('departments') or []), text=text, **_salary(text))


def ashby(slug: str):
    d = get(f'https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true', timeout=90)
    for j in d.get('jobs', []):
        if j.get('isListed') is False:
            continue
        et = (j.get('employmentType') or '').lower()
        kind = {'intern': 'internship', 'parttime': 'parttime', 'contract': 'contract', 'temporary': 'contract'}.get(
            et, kind_of(j.get('title')))
        wt = (j.get('workplaceType') or '').lower()
        # workplaceType first (11-06): Ashby sets isRemote on hybrid jobs too (1,436 stored hybrid jobs read as remote)
        remote = {'remote': 1.0, 'hybrid': 0.5, 'onsite': 0.0}.get(wt, 1.0 if j.get('isRemote') else None)
        sal = {}
        for c in (j.get('compensation') or {}).get('summaryComponents') or []:
            if c.get('compensationType') == 'Salary' and (c.get('minValue') or c.get('maxValue')):
                sal = _salary('', c.get('minValue'), c.get('maxValue'), c.get('currencyCode'),
                              _period(c.get('interval')) or 'year')
                break
        text = j.get('descriptionPlain') or plain(j.get('descriptionHtml'))
        yield str(j.get('id') or j.get('jobUrl')), j, dict(
            url=j.get('jobUrl'), apply_url=j.get('applyUrl'), title=j.get('title'), org=slug,
            location=j.get('location') or '', remote=remote, kind=kind, posted_at=iso(j.get('publishedAt')),
            tags=', '.join(x for x in (j.get('department'), j.get('team')) if x), text=text,
            **(sal or _salary(text)))


def lever(slug: str):
    for j in get(f'https://api.lever.co/v0/postings/{slug}?mode=json'):
        cat = j.get('categories') or {}
        wt = (j.get('workplaceType') or '').lower()
        remote = {'remote': 1.0, 'hybrid': 0.5, 'on-site': 0.0}.get(wt, remote_flag(cat.get('location')))
        text = '\n'.join([j.get('descriptionPlain') or ''] +
                         [f"{x.get('text', '')}\n{plain(x.get('content'))}" for x in j.get('lists') or []] +
                         [j.get('additionalPlain') or ''])
        sr = j.get('salaryRange') or {}
        yield j['id'], j, dict(
            url=j.get('hostedUrl'), apply_url=j.get('applyUrl'), title=j.get('text'), org=slug,
            location=cat.get('location') or '', remote=remote,
            kind=kind_of(f"{j.get('text')} {cat.get('commitment', '')}"), posted_at=iso(j.get('createdAt')),
            tags=', '.join(x for x in (cat.get('team'), cat.get('department')) if x), text=text,
            **_salary(text, sr.get('min'), sr.get('max'), sr.get('currency'), _period(sr.get('interval'))))


def smartrecruiters(company: str, cap: int = 200, pause: float = 0.5):
    """Posting API: list (100 a page), then one detail call per posting for the job ad text."""
    n, offset = 0, 0
    while n < cap:
        d = get(f'https://api.smartrecruiters.com/v1/companies/{company}/postings?limit=100&offset={offset}')
        for p in d.get('content', []):
            if n >= cap:
                break
            n += 1
            j = get(f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{p['id']}")
            sec = (j.get('jobAd') or {}).get('sections') or {}
            text = '\n'.join(plain((sec.get(k) or {}).get('text')) for k in
                             ('companyDescription', 'jobDescription', 'qualifications', 'additionalInformation'))
            loc = j.get('location') or {}
            where = ', '.join(x for x in (loc.get('city'), loc.get('region'), loc.get('country', '').upper()) if x)
            et = ((j.get('typeOfEmployment') or {}).get('label') or '')
            yield str(p['id']), j, dict(
                url=j.get('postingUrl') or f"https://jobs.smartrecruiters.com/{company}/{p['id']}",
                apply_url=j.get('applyUrl'), title=j.get('name'), org=(j.get('company') or {}).get('name') or company,
                location=where, remote=1.0 if loc.get('remote') else 0.5 if loc.get('hybrid') else remote_flag(where),
                kind=kind_of(f"{j.get('name')} {et}"), posted_at=iso(j.get('releasedDate')),
                tags=', '.join(x for x in ((j.get('department') or {}).get('label'), (j.get('function') or {}).get('label'),
                                           (j.get('industry') or {}).get('label'), et) if x),
                text=text, **_salary(text[:3000]))
            time.sleep(pause)
        offset += 100
        if offset >= (d.get('totalFound') or 0):
            break


# ---------------------------------------------------------------- job boards
def himalayas(limit: int = 4000, pause: float = 1.0):
    """Browse feed, newest first, 20 a page. About 150 jobs are posted an hour (11-07), so the newest 1,000 covered
    7 hours and a daily pass missed the rest: read back until a whole page is already stored (about 180 requests a
    day), at most `limit` jobs. Published limit: 60 requests a minute, 10,000 a day, shared by keyless callers."""
    stored = {r[0] for r in connect().execute("select source_id from opps where source='himalayas'")}
    cursor, n = None, 0
    while n < limit:
        q = {'limit': 20} | ({'cursor': cursor} if cursor else {})
        d = get('https://himalayas.app/jobs/api?' + urllib.parse.urlencode(q))
        if d.get('jobs') and all(j.get('guid') in stored for j in d['jobs']):
            break
        for j in d.get('jobs', []):
            n += 1
            loc = ', '.join(j.get('locationRestrictions') or []) or 'Anywhere'
            yield j.get('guid'), j, dict(
                url=j.get('guid'), apply_url=j.get('applicationLink'), title=j.get('title'), org=j.get('companyName'),
                location=f'Remote ({loc})', remote=1.0,
                kind=kind_of(f"{j.get('title')} {j.get('employmentType', '')}"), posted_at=iso(j.get('pubDate')),
                tags=', '.join((j.get('categories') or [])[:8]), text=plain(j.get('description')),
                **_salary('', j.get('minSalary'), j.get('maxSalary'), j.get('currency'),
                          _period(j.get('salaryPeriod')) or 'year'))
        cursor = d.get('nextCursor')
        if not cursor or not d.get('jobs'):
            break
        time.sleep(pause)


HIMALAYAS_TERMS = ('accountant', 'bookkeeper', 'payroll', 'tax', 'auditor', 'financial analyst', 'controller', 'recruiter',
                   'human resources', 'customer support', 'customer success', 'account manager', 'sales', 'marketing',
                   'content writer', 'copywriter', 'editor', 'podcast', 'video editor', 'social media',
                   'community manager', 'graphic designer', 'illustrator', 'ux writer', 'translator', 'teacher',
                   'tutor', 'instructional designer', 'clinical', 'nurse', 'medical', 'legal', 'paralegal',
                   'operations', 'project manager', 'executive assistant', 'virtual assistant', 'procurement',
                   'supply chain', 'public relations')


def himalayas_search(terms=HIMALAYAS_TERMS, pages: int = 3, pause: float = 1.2):
    """Search API (20 a page, ?page=N): non-software roles the browse feed's newest 1,000 miss.
    Published limit: 60 requests a minute, 10,000 a day, shared by keyless callers."""
    for t in terms:
        for page in range(1, pages + 1):
            d = get('https://himalayas.app/jobs/api/search?' + urllib.parse.urlencode({'q': t, 'page': page}))
            for j in d.get('jobs', []):
                loc = ', '.join(j.get('locationRestrictions') or []) or 'Anywhere'
                yield j.get('guid'), j, dict(
                    url=j.get('guid'), apply_url=j.get('applicationLink'), title=j.get('title'),
                    org=j.get('companyName'), location=f'Remote ({loc})', remote=1.0,
                    kind=kind_of(f"{j.get('title')} {j.get('employmentType', '')}"), posted_at=iso(j.get('pubDate')),
                    tags=', '.join((j.get('categories') or [])[:8]), text=plain(j.get('description')),
                    **_salary('', j.get('minSalary'), j.get('maxSalary'), j.get('currency'),
                              _period(j.get('salaryPeriod')) or 'year'))
            time.sleep(pause)
            if (d.get('offset') or 0) + (d.get('limit') or 20) >= (d.get('totalCount') or 0):
                break


def remotive():
    d = get('https://remotive.com/api/remote-jobs')
    for j in d.get('jobs', []):
        text = plain(j.get('description'))
        yield str(j['id']), j, dict(
            url=j.get('url'), apply_url=j.get('url'), title=j.get('title'), org=j.get('company_name'),
            location=f"Remote ({j.get('candidate_required_location') or 'Anywhere'})", remote=1.0,
            kind=kind_of(f"{j.get('title')} {(j.get('job_type') or '').replace('_', ' ')}"),
            posted_at=iso(j.get('publication_date')), tags=', '.join([j.get('category') or ''] + (j.get('tags') or [])[:8]),
            text=text, **_salary(f"{j.get('salary') or ''} {text[:3000]}"))


def jobicy(max_pages: int = 30, pause: float = 1.0):
    """One pass over the 7-day feed, following nextCursor (all industries). Jobicy: start a new automated pass at
    most once an hour; keep the Jobicy listing URL and credit Jobicy."""
    cursor = None
    for _ in range(max_pages):
        d = get('https://jobicy.com/api/jobs?' + urllib.parse.urlencode({'count': 100} | ({'cursor': cursor} if cursor else {})))
        for j in d.get('jobs', []):
            jt = ' '.join(j.get('jobType') or []) if isinstance(j.get('jobType'), list) else (j.get('jobType') or '')
            ind = j.get('jobIndustry')
            yield str(j['id']), j, dict(
                url=j.get('url'), apply_url=j.get('url'), title=j.get('jobTitle'), org=j.get('companyName'),
                location=f"Remote ({j.get('jobGeo') or 'Anywhere'})", remote=1.0,
                kind=kind_of(f"{j.get('jobTitle')} {jt}"), posted_at=iso(j.get('pubDate')),
                tags=', '.join(x for x in [', '.join(ind) if isinstance(ind, list) else ind, j.get('jobLevel')] if x),
                text=plain(j.get('jobDescription') or j.get('jobExcerpt')),
                **_salary('', j.get('salaryMin') or j.get('annualSalaryMin'), j.get('salaryMax') or j.get('annualSalaryMax'),
                          j.get('salaryCurrency'), _period(j.get('salaryPeriod')) or 'year'))
        cursor = d.get('nextCursor')
        if not cursor or not d.get('jobs'):
            break
        time.sleep(pause)


def arbeitnow(pages: int = 3, pause: float = 1.0):
    for p in range(1, pages + 1):
        d = get(f'https://www.arbeitnow.com/api/job-board-api?page={p}')
        for j in d.get('data', []):
            text = plain(j.get('description'))
            yield j['slug'], j, dict(
                url=j.get('url'), apply_url=j.get('url'), title=j.get('title'), org=j.get('company_name'),
                location=j.get('location') or '', remote=1.0 if j.get('remote') else remote_flag(j.get('location')),
                kind=kind_of(f"{j.get('title')} {' '.join(j.get('job_types') or [])}"),
                posted_at=iso(j.get('created_at')), tags=', '.join((j.get('tags') or [])[:8]), text=text,
                **_salary(text))
        if not (d.get('links') or {}).get('next'):
            break
        time.sleep(pause)


WWR_FEEDS = ('remote-jobs', 'categories/remote-customer-support-jobs', 'categories/remote-sales-and-marketing-jobs',
             'categories/remote-design-jobs', 'categories/remote-management-and-finance-jobs',
             'categories/remote-product-jobs', 'categories/all-other-remote-jobs')


def wwr(feeds=WWR_FEEDS, pause: float = 1.0):
    for feed in feeds:
        yield from _wwr_feed(feed)
        time.sleep(pause)


def _wwr_feed(feed: str):
    root = ET.fromstring(get(f'https://weworkremotely.com/{feed}.rss', raw=True))
    for it in root.iter('item'):
        g = {c.tag: (c.text or '') for c in it}
        org, _, title = g.get('title', '').partition(': ')
        text = plain(g.get('description'))
        yield g.get('guid') or g.get('link'), g, dict(
            url=g.get('link'), apply_url=g.get('link'), title=title or org, org=org if title else '',
            location=f"Remote ({g.get('region') or 'Anywhere'})", remote=1.0,
            kind=kind_of(f"{title} {g.get('type', '')}"), posted_at=iso(g.get('pubDate')),
            tags=g.get('category', ''), text=text, **_salary(text))


# ---------------------------------------------------------------- forums and code hosts
def _hn_threads():
    d = get('https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=12')
    out = {}
    for h in d.get('hits', []):
        t = h.get('title', '')
        key = 'hiring' if 'Who is hiring' in t else 'freelancer' if 'Freelancer' in t else None
        if key and key not in out:
            out[key] = (h['objectID'], t)
    return out


_HN_SEEKER = re.compile(r'(?is)^\s*(location\s*:.{0,200}(remote\s*:|willing to relocate)|seeking work|i am (an? )?'
                        r'.{0,40}(developer|engineer|designer)\b.{0,120}(looking|seeking|available|open to|link))')


def hn():
    for key, (sid, title) in _hn_threads().items():
        d = get(f'https://hn.algolia.com/api/v1/items/{sid}', timeout=90)
        for c in d.get('children') or []:
            text = plain(c.get('text'))
            if not text or (key == 'freelancer' and not re.match(r'(?i)\s*seeking\s+freelancer', text)) \
                    or _HN_SEEKER.search(text[:400]):
                continue  # individuals advertising themselves ("SEEKING WORK", misplaced "who wants to be hired")
            first = text.split('\n', 1)[0][:200]
            if key == 'freelancer':
                first = re.sub(r'(?i)^\s*seeking\s+freelancer\s*[-:|]*\s*', '', first)
            parts = [p.strip() for p in re.split(r'\s*\|\s*|\s+[—–-]\s+', first) if p.strip()]
            org = re.sub(r'\s*\(.*?\)\s*', ' ', parts[0]).strip()[:80] if len(parts) > 1 else ''
            yield str(c['id']), {'thread': title, **{k: c.get(k) for k in ('id', 'created_at', 'text')}}, dict(
                url=f"https://news.ycombinator.com/item?id={c['id']}", apply_url=None,
                title=' | '.join(parts[1:3]) if len(parts) > 1 else first[:120], org=org,
                location=next((p for p in parts if re.search(r'(?i)remote|onsite|hybrid|,', p)), ''),
                remote=remote_flag(first, text[:600]),
                kind='contract' if key == 'freelancer' else kind_of(first),
                posted_at=iso(c.get('created_at')), tags=f'hn:{key}', text=text, **_salary(text[:2000]))


ATOM = '{http://www.w3.org/2005/Atom}'


def v2ex(nodes=('jobs', 'remote', 'outsourcing'), pause: float = 2.0):
    """Node Atom feeds (50 newest topics each, with content). The v1 JSON API ignores its page parameter."""
    for node in nodes:
        root = ET.fromstring(get(f'https://www.v2ex.com/feed/{node}.xml', raw=True))
        for e in root.findall(f'{ATOM}entry'):
            link = (e.find(f'{ATOM}link').get('href') or '').split('#')[0]
            tid = link.rstrip('/').split('/')[-1]
            title = e.findtext(f'{ATOM}title') or ''
            text = plain(e.findtext(f'{ATOM}content'))
            yield tid, {'node': node, 'link': link, 'title': title, 'published': e.findtext(f'{ATOM}published'),
                        'content': text}, dict(
                url=link, apply_url=None, title=title, org='', location='',
                remote=1.0 if node == 'remote' else remote_flag(title, text[:800]),
                kind=kind_of(title, 'outsourcing' if node == 'outsourcing' else 'fulltime'),
                posted_at=iso(e.findtext(f'{ATOM}published')), tags=f'v2ex:{node}', text=text,
                **_salary(f'{title} {text[:2000]}'))
        time.sleep(pause)


def rubychina(max_topics: int = 80, days: int = 365, pause: float = 1.0):
    """Ruby China 招聘 node (id 25): list, then one call per topic for the body; topics older than `days` skipped."""
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    lst = get('https://ruby-china.org/api/v3/topics?node_id=25&limit=150').get('topics', [])
    n = 0
    for t in lst:
        created = datetime.fromisoformat(t['created_at']).timestamp()
        if created < cutoff or t.get('deleted'):
            continue
        if n >= max_topics:
            break
        n += 1
        try:
            d = get(f"https://ruby-china.org/api/v3/topics/{t['id']}").get('topic', {})
        except urllib.error.HTTPError:  # deleted or hidden topics answer 404 / 406
            continue
        text = plain(d.get('body_html') or d.get('body'))
        title = t.get('title') or ''
        yield str(t['id']), {k: d.get(k) for k in ('id', 'title', 'created_at', 'body')}, dict(
            url=f"https://ruby-china.org/topics/{t['id']}", apply_url=None, title=title, org='', location='',
            remote=remote_flag(title, text[:800]), kind=kind_of(title), posted_at=iso(t.get('created_at')),
            tags='rubychina:jobs', text=text, **_salary(f'{title} {text[:2000]}'))
        time.sleep(pause)


GITHUB_QUERIES = ('label:bounty is:open is:issue', 'label:"💎 Bounty" is:open is:issue',
                  'label:"help wanted" is:open is:issue llm', 'label:"help wanted" is:open is:issue rag',
                  # bounties posted by the Algora / Opire bots without a label (10-30; their own sites forbid scraping)
                  'commenter:app/algora-pbc is:open is:issue', 'commenter:app/opirebot is:open is:issue') + tuple(
    f'label:{lab} is:open is:issue language:{lg}' for lab in ('bounty', '"💎 Bounty"')
    for lg in ('go', 'typescript', 'javascript', 'vue', 'dart', 'java', 'kotlin', 'swift', 'rust', 'python'))


def github(per_query: int = 100):
    seen = set()
    for q in GITHUB_QUERIES:
        out = subprocess.run(['gh', 'api', '-X', 'GET', 'search/issues', '-f', f'q={q}', '-f', 'sort=created',
                              '-f', f'per_page={per_query}'], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise RuntimeError(out.stderr[-300:])
        for it in json.loads(out.stdout).get('items', []):
            if it['id'] in seen:
                continue
            seen.add(it['id'])
            repo = it.get('repository_url', '').split('/repos/')[-1]
            labels = [x.get('name', '') for x in it.get('labels') or []]
            body = it.get('body') or ''
            yield str(it['id']), {k: it.get(k) for k in ('id', 'title', 'html_url', 'created_at', 'body')} | {
                'labels': labels, 'repo': repo}, dict(
                url=it.get('html_url'), apply_url=it.get('html_url'), title=it.get('title'), org=repo,
                location='Remote (open source)', remote=1.0, kind='bounty', posted_at=iso(it.get('created_at')),
                tags=', '.join(labels[:8]), text=plain(body)[:8000], **_salary(f"{it.get('title')} {body[:1500]}"))
        time.sleep(7)  # search API: 10 requests/min unauthenticated, 30 authenticated


# ---------------------------------------------------------------- government job services (Chinese)
# 3-digit postal districts: Taipei, New Taipei, Taoyuan, Hsinchu, Taichung, Tainan, Kaohsiung, Keelung, Changhua, Yilan
TAIWAN_ZIP = ('100', '104', '105', '106', '110', '114', '220', '231', '241', '330', '300', '302', '400', '403', '407',
              '408', '700', '710', '800', '802', '806', '813', '200', '500', '260')
_TW = {'OCCU_DESC': 'title', 'WK_TYPE': 'type', 'CJOB_NAME1': 'cat1', 'CJOB_NAME2': 'cat2', 'JOB_DETAIL': 'detail',
       'CITYNAME': 'city', 'EXPERIENCE': 'exp', 'WKTIME': 'hours', 'SALARYCD': 'paytype', 'NT_L': 'pay_lo', 'NT_U': 'pay_hi',
       'EDGRDESC': 'edu', 'URL_QUERY': 'url', 'COMPNAME': 'org', 'TRANDATE': 'updated', 'STOP_DATE': 'deadline',
       'JOB_PERSON': 'headcount'}


def taiwanjobs(zips=TAIWAN_ZIP, per_zip: int = 120, pause: float = 3.0):
    """台灣就業通 open data API (data.gov.tw 44062; 政府資料開放授權條款-第1版, attribution in ATTRIBUTION).
    At most 1,000 rows per call; sliced by 3-digit postal district."""
    for z in zips:
        xml = None
        for attempt in range(2):  # the service sometimes cuts a response short
            try:
                xml = get(f'https://free.taiwanjobs.gov.tw/webservice_taipei/Webservice.ashx?count={per_zip}&zipno={z}',
                          raw=True, timeout=90).decode('utf-8', 'ignore')
                break
            except (OSError, http.client.HTTPException):
                time.sleep(10)
        if xml is None:
            print(f'taiwanjobs: zip {z} failed twice, skipped', flush=True)
            continue
        root = ET.fromstring(re.sub(r'<(/?)([A-Za-z0-9_]+)（[^）>]*）>', r'<\1\2>', xml))  # tags carry （中文名）
        for e in root.iter('Data'):
            g = {}
            for c in e:
                if c.tag in _TW:
                    g[_TW[c.tag]] = (c.text or '').strip()
            if not g.get('url') or not g.get('title'):
                continue
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(g['url']).query)
            sid = (qs.get('HIRE_ID') or [g['url']])[0]
            per = {'月薪': 'month', '時薪': 'hour', '日薪': 'day', '年薪': 'year'}.get(g.get('paytype', ''))
            lo, hi = (float(g[k]) if (g.get(k) or '').replace('.', '').isdigit() and float(g[k]) > 0 else None
                      for k in ('pay_lo', 'pay_hi'))
            text = redact('\n'.join(x for x in (g.get('detail'), f"職類：{g.get('cat1', '')} / {g.get('cat2', '')}",
                                                 f"工作時間：{g.get('hours', '')}", f"經驗：{g.get('exp', '')}",
                                                 f"學歷：{g.get('edu', '')}", f"截止：{g.get('deadline', '')}") if x))
            wt = g.get('type', '')
            yield sid, g, dict(
                url=g['url'], apply_url=g['url'], title=g['title'], org=g.get('org', ''), location=g.get('city', ''),
                remote=remote_flag(g['title'], text[:600]),
                kind='parttime' if '部分' in wt or '兼職' in wt else kind_of(g['title'], 'fulltime'),
                posted_at=iso((g.get('updated') or '').replace('/', '-')[:10] + ' 00:00:00') if g.get('updated') else None,
                tags=', '.join(x for x in (g.get('cat1'), g.get('cat2'), wt) if x), text=text,
                **(_salary('', lo, hi, 'TWD', per) if per and (lo or hi) else {}))
        time.sleep(pause)


NCSS_KEYWORDS = ('财务', '会计', '审计', '税务', '运营', '新媒体', '策划', '游戏策划', '教师', '老师', '教研', '实验', '机械',
                 '公关', '销售', '客服', '人力资源', '招聘', '行政', '法务', '设计', '翻译', '市场', '采购', '管培',
                 '编辑', '物流', '质检', '护士', '实习')


# tier-1 and "new tier-1" cities (Yicai 2024 list); codes from ncss.cn/student/code?type=areacodejc
NCSS_CITIES = {'北京': '110100', '上海': '310100', '广州': '440100', '深圳': '440300', '成都': '510100', '杭州': '330100',
               '重庆': '500100', '苏州': '320500', '武汉': '420100', '西安': '610100', '南京': '320100', '长沙': '430100',
               '天津': '120100', '郑州': '410100', '东莞': '441900', '无锡': '320200', '宁波': '330200', '青岛': '370200',
               '合肥': '340100'}
NCSS_TYPES = {'': 'fulltime', '02': 'parttime', '03': 'internship'}  # jobType filter ('' = any) -> default kind


def _get_once_more(url: str, raw: bool = False, wait: float = 60.0):
    """A dropped connection gets one retry after `wait` s; a second failure in a row stops the pass (10-30: one reset
    after ~10 min at the 5 s pace, the site answered normally again a few minutes later)."""
    try:
        return get(url, raw=raw)
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        time.sleep(wait)
        return get(url, raw=raw)


def _ncss_page(params: dict, tag: str, kind: str, city: str | None, seen: set, pause: float):
    """One list request, then the detail page of every job not seen before."""
    d = _get_once_more('https://www.ncss.cn/student/jobs/jobslist/ajax/?' + urllib.parse.urlencode(params))
    time.sleep(pause)
    for j in ((d.get('data') or {}).get('list') or []):
        jid = j.get('jobId')
        if not jid or jid in seen:
            continue
        seen.add(jid)
        url = f'https://www.ncss.cn/student/jobs/{jid}/detail.html'
        try:
            page = _get_once_more(url, raw=True).decode('utf-8', 'ignore')
        except urllib.error.HTTPError:
            continue
        finally:
            time.sleep(pause)
        m = re.search(r'class="details"(.*?)(扫码|</section>|<footer)', page, re.S)
        body = redact(re.sub(r'^[>\s]*职位详情\s*', '', plain(m.group(1))) if m else '')
        lo, hi = (float(j.get(k) or 0) for k in ('lowMonthPay', 'highMonthPay'))
        lo, hi = (v * 1000 if 0 < v < 100 else v for v in (lo, hi))  # list gives 8.0 (= 8k) or 8000
        text = '\n'.join(x for x in (body, f"学历：{j.get('degreeName') or ''}", f"专业：{j.get('major') or ''}",
                                     f"单位性质：{j.get('recProperty') or ''}") if x)
        province = j.get('areaCodeName') or ''  # the list gives the province only
        yield jid, {k: j.get(k) for k in ('jobId', 'jobName', 'recName', 'areaCodeName', 'degreeName', 'major',
                                          'lowMonthPay', 'highMonthPay', 'publishDate', 'recProperty')} | (
            {'areaCode': params['areaCode']} if city else {}), dict(
            url=url, apply_url=url, title=j.get('jobName'), org=j.get('recName') or '',
            location=f'{city}, {province}' if city and province != city else province,
            remote=remote_flag(j.get('jobName'), body[:600]), kind=kind_of(j.get('jobName'), kind),
            posted_at=iso(j.get('publishDate')), tags=f"ncss:{tag}, {j.get('recProperty') or ''}", text=text,
            **(_salary('', lo or None, hi or None, 'CNY', 'month') if (lo or hi) else _salary(body[:2000])))


def _ncss_seen() -> set:
    return {r[0] for r in connect().execute("select source_id from opps where source='ncss'")}  # no detail re-fetch


def ncss(keywords=NCSS_KEYWORDS, per_keyword: int = 25, pause: float = 5.0):
    """国家大学生就业服务平台: undocumented list JSON + public detail pages; no published terms were found.
    Used (owner decision, 2026-10-29) only on these conditions: one request every 5 s, local index only, results shown
    as title + link. Contact details are redacted. Not called unless you name it (see docs/SOURCES.md)."""
    seen = _ncss_seen()
    for kw in keywords:
        yield from _ncss_page({'jobName': kw, 'offset': 1, 'limit': per_keyword}, kw, 'fulltime', None, seen, pause)


def ncss_city(cities=NCSS_CITIES, types=NCSS_TYPES, per_query: int = 50, pause: float = 5.0):
    """Same source and terms as ncss(), filtered by city and job type (10-30): the keyword pass gave 0-31 postings per
    city. A job found this way is in that city, so its location names the city, not only the province."""
    seen = _ncss_seen()
    for city, code in cities.items():
        for jt, kind in types.items():
            yield from _ncss_page({'areaCode': code, 'offset': 1, 'limit': per_query} | ({'jobType': jt} if jt else {}),
                                  f'{city}/{kind}' if jt else city, kind, city, seen, pause)


def all_fetchers():
    """(source name, sub-key, generator factory)."""
    fs = [('greenhouse', s, (lambda s=s: greenhouse(s))) for s in GREENHOUSE]
    fs += [('ashby', s, (lambda s=s: ashby(s))) for s in ASHBY]
    fs += [('lever', s, (lambda s=s: lever(s))) for s in LEVER]
    fs += [('smartrecruiters', s, (lambda s=s, n=n: smartrecruiters(s, n))) for s, n in SMARTRECRUITERS.items()]
    fs += [('himalayas', '', himalayas), ('himalayas', 'search', himalayas_search), ('remotive', '', remotive),
           ('jobicy', '', jobicy), ('arbeitnow', '', arbeitnow), ('wwr', '', wwr), ('hn', '', hn), ('v2ex', '', v2ex),
           ('rubychina', '', rubychina), ('github', '', github), ('taiwanjobs', '', taiwanjobs), ('ncss', '', ncss),
           ('ncss', 'city', ncss_city)]
    return fs
