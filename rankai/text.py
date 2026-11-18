"""Text helpers: HTML to plain text, tokens for FTS5 (English words + CJK bigrams), contact redaction, rule fields."""
import html
import re

_TAG = re.compile(r'<[^>]+>')
_WS = re.compile(r'[ \t\r\f\v]+')
_CJK = re.compile(r'[㐀-鿿豈-﫿]')
_RUN = re.compile(r'[㐀-鿿豈-﫿]+|[a-z0-9][a-z0-9+#]*')
STOP = set('a an and are as at be by for from in is it of on or that the this to with we you your our will'.split())


def plain(s: str | None) -> str:
    """HTML (possibly escaped twice, as Greenhouse sends it) to plain text with line breaks kept."""
    if not s:
        return ''
    s = html.unescape(html.unescape(s))
    s = re.sub(r'(?i)<\s*(br|/p|/li|/h\d|/div|/tr)\s*/?>', '\n', s)
    s = _TAG.sub(' ', s)
    s = html.unescape(s)
    s = _WS.sub(' ', s)
    return re.sub(r'\n\s*\n+', '\n', s).strip()


def has_cjk(s: str) -> bool:
    return bool(_CJK.search(s or ''))


def lang(s: str) -> str:
    s = s or ''
    n = len(_CJK.findall(s))
    return 'zh' if n >= 5 and n / max(len(s), 1) > 0.05 else 'en'


class _OpenCC:
    """Traditional -> simplified Chinese through the system libopencc (Ubuntu package libopencc1.1, already installed
    for the input methods; no Python package). Without the library, text is returned unchanged."""
    def __init__(self, config: str = '/usr/share/opencc/t2s.json'):
        import ctypes
        import ctypes.util
        self.h = None
        try:
            lib = ctypes.CDLL(ctypes.util.find_library('opencc') or 'libopencc.so.1.1')
        except OSError:
            return
        lib.opencc_open.restype = ctypes.c_void_p
        lib.opencc_open.argtypes = [ctypes.c_char_p]
        lib.opencc_convert_utf8.restype = ctypes.c_void_p
        lib.opencc_convert_utf8.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        lib.opencc_convert_utf8_free.argtypes = [ctypes.c_void_p]
        h = lib.opencc_open(config.encode())
        if h and h != ctypes.c_void_p(-1).value:
            self.lib, self.h, self.ct = lib, h, ctypes

    def __call__(self, s: str) -> str:
        if not self.h or not s:
            return s
        b = s.encode()
        r = self.lib.opencc_convert_utf8(self.h, b, len(b))
        if not r:
            return s
        out = self.ct.string_at(r).decode()
        self.lib.opencc_convert_utf8_free(r)
        return out


_T2S = None


def to_simplified(s: str) -> str:
    global _T2S
    if _T2S is None:
        _T2S = _OpenCC()
    return _T2S(s) if s and has_cjk(s) else s


def tokens(s: str) -> list[str]:
    """English/number words (c++ -> cplusplus, c# -> csharp) and CJK character bigrams (single chars kept alone).
    CJK is folded to simplified first (10-30), so 「財務」 in a Taiwan posting matches a 「财务」 search."""
    out = []
    for m in _RUN.finditer(to_simplified(s or '').lower()):
        w = m.group()
        if _CJK.match(w):
            out.extend([w] if len(w) == 1 else [w[i:i + 2] for i in range(len(w) - 1)])
        elif w not in STOP:
            out.append(w.replace('+', 'plus').replace('#', 'sharp'))
    return out


_EMAIL = re.compile(r'[\w.+-]+@[\w-]+(\.[\w-]+)+')
_PHONE = re.compile(r'(?<!\w)\+?\d[\d\s()-]{7,}\d(?!\w)')
_DATE = re.compile(r'(?:19|20)\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])(?!\d)')
_RANGE = re.compile(r'([1-9]\d{2,6})\s*-\s*([1-9]\d{2,6})')
_MONEY_NEAR = re.compile(r'(?i)[$€£¥元万千]|\b(usd|eur|gbp|cny|rmb|cad|aud|twd|hkd|jpy|inr|php|czk|pln|chf|sek|k|pay|salary|per)\b'
                         r'|薪|/\s*(hr|hour|month|year)')


def _phone(m) -> str:
    """[phone] unless the digits are a date or a pay range: _PHONE alone took every 2026-10-27 and 161000-170000."""
    t, s, a, b = m.group(0), m.string, m.start(), m.end()
    if len(re.sub(r'\D', '', _DATE.sub('', t))) < 7:  # dates and date ranges only
        return t
    if (a > 1 and s[a - 1] == ',' and s[a - 2].isdigit() and re.match(r'\d{3}(?!\d)', t)
            and re.match(r',\d{3}(?!\d)', s[b:b + 5])):
        return t  # the middle of a thousands-grouped amount: "$120,000 - 150,000" -> "000 - 150"
    y = re.fullmatch(r'((?:19|20)\d{2})\s*-\s*((?:19|20)\d{2})', t.strip())
    if y and int(y[2]) == int(y[1]) + 1:
        return t  # "School Year 2026 - 2027"
    money = _MONEY_NEAR.search(s[max(0, a - 12):b + 12])
    r = _RANGE.fullmatch(t.strip())
    if money and r and int(r[1]) < int(r[2]) and abs(len(r[1]) - len(r[2])) <= 1:
        return t  # "15000-25000元", "Pay: 161000-170000 USD"
    if money and re.fullmatch(r'[1-9]\d{0,2}(?: \d{3})+(?:\s*-\s*[1-9]\d{0,2}(?: \d{3})+)?', t.strip()):
        return t  # space-grouped amounts next to a currency: "CZK 1 300 000"
    return '[phone]'
_IM = re.compile(r'(?i)(微信|vx|wx|wechat|weixin|qq|telegram|tg|whatsapp)\s*(号|id)?\s*[:：]?\s*[\w@.+-]{4,}')
_URLISH = re.compile(r'(?i)(t\.me|wa\.me)/\S+')


def redact(s: str) -> str:
    """Remove contact details before text leaves this machine (labelers, cloud judges)."""
    s = _EMAIL.sub('[email]', s or '')
    s = _URLISH.sub('[im]', s)
    s = _IM.sub(lambda m: m.group(1) + ' [id]', s)
    return _PHONE.sub(_phone, s)


# ---------------------------------------------------------------- rule fields (v0, no model)
REMOTE_YES = re.compile(r'(?i)\b(remote|anywhere|work from home|wfh|distributed|fully[- ]remote)\b|远程|在家办公|居家')
REMOTE_NO = re.compile(r'(?i)\b(on[- ]?site|in[- ]office|in office)\b|驻场|坐班|到岗|现场办公|线下办公')
# 11-06: "不支持远程" was read as remote (2 rubychina posts). English stays narrow: "remote-first, but not remote-only"
# is common boilerplate and is not a negation.
REMOTE_NOT = re.compile(r'(不(支持|接受|提供|能|可以?|考虑)|无法|非|拒绝|暂不)\s?(远程|居家|在家办公)'
                        r'|(?i:\b(this|the) (role|position|job) is not (a )?remote\b|\bno remote (work|options?)\b)')
HYBRID = re.compile(r'(?i)\bhybrid\b|混合办公')


def remote_flag(*parts: str) -> float | None:
    """1 remote, 0.5 hybrid, 0 on-site, None unknown. Location/title fields should come first in parts."""
    s = ' '.join(p for p in parts if p)
    if HYBRID.search(s):
        return 0.5
    if REMOTE_NOT.search(s):
        return 0.0
    if REMOTE_YES.search(s):
        return 1.0
    if REMOTE_NO.search(s):
        return 0.0
    return None


_KIND_RULES = [  # first match wins; applied to title + type fields (not the whole body)
    ('internship', re.compile(r'(?i)\bintern(ship)?\b|实习')),
    ('cofounder', re.compile(r'(?i)co-?founder|合伙人|找合伙|技术合伙')),
    ('bounty', re.compile(r'(?i)\bbount(y|ies)\b|悬赏|赏金')),
    ('outsourcing', re.compile(r'外包|私活|接单|项目合作|二开')),
    # part-time before contract (10-29): "Marketing VA - PART TIME" with type "Contractor" is a part-time role, and a
    # contract search already accepts part-time postings (search.parse_query)
    ('parttime', re.compile(r'(?i)part[- ]?time|兼职')),
    ('contract', re.compile(r'(?i)\bcontract(or)?\b|\bfreelance(r)?\b|自由职业')),
]


def kind_of(text: str, default: str = 'fulltime') -> str:
    for k, rx in _KIND_RULES:
        if rx.search(text or ''):
            return k
    return default


FX_USD = {'USD': 1.0, 'EUR': 1.1, 'GBP': 1.27, 'CAD': 0.73, 'AUD': 0.66, 'CNY': 0.14, 'RMB': 0.14, 'INR': 0.012,
          'CHF': 1.15, 'SGD': 0.75, 'JPY': 0.0067, 'PLN': 0.25, 'SEK': 0.095, 'BRL': 0.18, 'TWD': 0.031,
          'HKD': 0.128, 'NZD': 0.6, 'KRW': 0.00073, 'PHP': 0.018, 'MXN': 0.055, 'ZAR': 0.055, 'NGN': 0.00065,
          'KES': 0.0077, 'IDR': 0.000062, 'VND': 0.00004, 'THB': 0.028, 'MYR': 0.22, 'PKR': 0.0036, 'EGP': 0.02,
          'DKK': 0.147, 'NOK': 0.094, 'CZK': 0.044, 'HUF': 0.0028, 'RON': 0.22, 'ILS': 0.27, 'AED': 0.27,
          'SAR': 0.27, 'TRY': 0.03, 'UAH': 0.024, 'ARS': 0.001, 'CLP': 0.0011, 'COP': 0.00025, 'PEN': 0.27}  # rough, for filtering only
PER_YEAR = {'year': 1, 'month': 12, 'week': 50, 'day': 250, 'hour': 2000}

_MONEY = re.compile(r'(?i)(US\$|\$|€|£|¥|USD|EUR|GBP|CNY|RMB)\s?(\d{1,3}(?:[,.]\d{3})+|\d+(?:\.\d+)?)\s?(k|K)?'
                    r'(?:\s?(?:-|–|—|to|~)\s?(?:US\$|\$|€|£|¥)?\s?(\d{1,3}(?:[,.]\d{3})+|\d+(?:\.\d+)?)\s?(k|K)?)?')
_CNK = re.compile(r'(\d{1,3})\s?[-~–]\s?(\d{1,3})\s?[kK千]')
_SYM = {'$': 'USD', 'US$': 'USD', '€': 'EUR', '£': 'GBP', '¥': 'CNY'}


def _num(s, k):
    v = float(s.replace(',', '').replace('.', '') if re.search(r'[,.]\d{3}$', s) else s)
    return v * 1000 if k else v


def _period(ctx: str, lo: float) -> str:
    c = ctx.lower()
    if re.search(r'/\s?h(ou)?r|per hour|hourly|时薪|/小时|每小时', c):
        return 'hour'
    if re.search(r'/\s?mo|per month|monthly|月薪|/月|每月', c):
        return 'month'
    if re.search(r'/\s?day|per day|daily|日薪|/天', c):
        return 'day'
    return 'hour' if lo < 500 else 'year'


_PAYCTX = re.compile(r'(?i)salary|compensation|\bpay\b|base|range|\bote\b|rate|per (year|hour|month)|/\s?(yr|year|hr|hour|mo)'
                     r'|annual|hourly|薪|待遇|报酬|预算')


def salary_from_text(s: str):
    """First plausible pay range in free text -> (min, max, currency, period) or None. Skips funding amounts
    ('$125M raised'), lone numbers without pay context, and values outside 5k-2M USD a year.
    V2EX style '20-30K' = CNY per month."""
    s = s or ''
    for m in _MONEY.finditer(s):
        if re.match(r'\s?(m|b|bn|mm|million|billion)\b', s[m.end():m.end() + 9], re.I):
            continue
        cur = _SYM.get(m.group(1), m.group(1).upper())
        cur = 'CNY' if cur == 'RMB' else cur
        lo = _num(m.group(2), m.group(3))
        hi = _num(m.group(4), m.group(5) or m.group(3)) if m.group(4) else lo
        if not (m.group(4) or m.group(3) or _PAYCTX.search(s[max(0, m.start() - 80):m.end() + 30])):
            continue
        period = _period(s[m.start():m.end() + 25], lo)
        if not 5e3 <= (usd_year(lo, cur, period) or 0) <= 2e6:
            continue
        return lo, max(lo, hi), cur, period
    m = _CNK.search(s)
    if m and has_cjk(s):
        return float(m.group(1)) * 1000, float(m.group(2)) * 1000, 'CNY', 'month'
    return None


_QCUR = [('JPY', r'jpy|日元|日圆|円'), ('EUR', r'eur|€|欧元'), ('GBP', r'gbp|£|英镑'), ('CAD', r'cad|加元|加币'),
         ('AUD', r'aud|澳元|澳币'), ('NZD', r'nzd|纽币|新西兰元'), ('HKD', r'hkd|港币|港元'), ('TWD', r'twd|ntd|台币|新台币'),
         ('SGD', r'sgd|新币|新加坡元'), ('CHF', r'chf'), ('INR', r'inr|卢比'),
         ('USD', r'usd|us\$|\$|美元|美金|dollars?'), ('CNY', r'cny|rmb|¥|元|人民币|块')]
_QAMT = re.compile(r'(?i)(?<![a-z0-9.])(\d+(?:\.\d+)?|[一二两三四五六七八九十]{1,3})\s*(万|千|k)?(?![a-z0-9.])')
_QPAYWORD = re.compile(r'(?i)薪|salary|\bpay\b|wage|compensation|待遇|报酬|minimum|at least|不低于|起|以上|\+')
_CN_DIGIT = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}


def _cn_num(s: str) -> float:
    if s[0].isdigit():
        return float(s)
    if '十' in s:  # 十, 十五, 二十, 二十五
        a, _, b = s.partition('十')
        return (_CN_DIGIT.get(a, 1) if a else 1) * 10 + (_CN_DIGIT.get(b, 0) if b else 0)
    return float(_CN_DIGIT.get(s, 0))


def query_pay(q: str):
    """The minimum pay a search states -> (amount, currency, period) or None.
    '年薪700万日元起' -> (7e6, JPY, year); '月薪两万起' -> (2e4, CNY, month); 'NZD 90k+' -> (9e4, NZD, year);
    'hourly $40+' -> (40, USD, hour). A number counts only next to a currency (within 6 characters) or a pay word
    in its clause, so '带过10人团队', '10 hours a week' and '5年经验' give nothing."""
    for clause in re.split(r'[，,;；。]', q or ''):
        for m in _QAMT.finditer(clause):
            near = clause[max(0, m.start() - 6):m.end() + 6].lower()
            cur = next((c for c, rx in _QCUR if re.search(rx, near)), None)
            if not cur and not (_QPAYWORD.search(clause) and (m.group(2) or re.search(r'薪|salary|pay|wage', clause, re.I))):
                continue
            if re.match(r'\s*(人|个|年经验|years?|hours?|小时|周|天|days?|weeks?|months?|个月)', clause[m.end():], re.I) \
                    and not cur:
                continue
            v = _cn_num(m.group(1)) * {'万': 1e4, '千': 1e3, 'k': 1e3, 'K': 1e3}.get(m.group(2) or '', 1)
            if v <= 0:
                continue
            cur = cur or ('CNY' if has_cjk(q) else 'USD')
            c = clause.lower()
            if re.search(r'时薪|/\s?h(ou)?r\b|/小时|每小时|hourly|per hour|an hour', c):
                per = 'hour'
            elif re.search(r'月薪|/\s?mo\b|/月|每月|per month|a month|monthly', c):
                per = 'month'
            elif re.search(r'日薪|/天|每天|per day|a day|daily', c):
                per = 'day'
            elif re.search(r'年薪|/\s?yr\b|/年|每年|per year|a year|annual|yearly', c):
                per = 'year'
            else:
                per = 'month' if cur == 'CNY' and v < 1e5 else 'hour' if v < 500 else 'year'
            return v, cur, per
    return None


def usd_year(v: float | None, currency: str | None, period: str | None) -> float | None:
    fx = FX_USD.get((currency or 'USD').upper())
    if v is None or fx is None:  # unknown currency: no USD figure rather than a wrong one
        return None
    return v * fx * PER_YEAR.get(period or 'year', 1)
