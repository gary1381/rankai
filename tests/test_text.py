"""python -m pytest tests -q"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rankai.text import kind_of, redact  # noqa: E402

PHONES = ['+1 (555) 123-4567', '138 0013 8000', '13800138000', '010-12345678', '555-123-4567', '+44 20 7946 0958',
          '2345-6789 ext', '0755-1234567', '电话 13912345678 薪资面议', 'Tel 912 345 678', 'call 2026-2028 now']
KEEP = ['posted 2026-10-27', '2026-10-27T10:00:00Z', '2026-10-01 - 2026-10-31', 'Pay: 161000-170000 USD per year',
        '$120,000 - $150,000', '$120,000 - 150,000 a year', '15000-25000元', '月薪 8000-12000', '100000 - 150000 CNY',
        '2026/10/27', 'salary 85000 - 95000', 'School Year 2026 - 2027', 'CZK 1 300 000 - CZK 1 600 000',
        '£124,400 - 165,000 + bonus']


def test_phones_are_redacted():
    for p in PHONES:
        out = redact(p)
        assert '[phone]' in out and not any(ch.isdigit() for ch in out.replace('[phone]', '').split('ext')[0][:6]), (p, out)


def test_dates_and_pay_survive():
    for s in KEEP:
        assert redact(s) == s, (s, redact(s))


def test_date_next_to_phone_still_hides_the_phone():
    assert '13800138000' not in redact('2026-10-27 13800138000')
    assert '13800138000' not in redact('posted 2026-10-27, call 13800138000')


def test_comma_separated_phones_are_redacted():
    out = redact('Tel 13822214255,13912345678')
    assert '13822214255' not in out and '13912345678' not in out, out


def test_part_time_wins_over_contract():
    assert kind_of('Marketing VA - PART TIME Contractor') == 'parttime'
    assert kind_of('Freelance writer 兼职') == 'parttime'
    assert kind_of('Six-month contract event producer') == 'contract'
    assert kind_of('Part-time intern') == 'internship'


def test_query_pay():
    from rankai.text import query_pay
    cases = {
        '全职大阪 bilingual tour operations coordinator，需会中文，年薪700万日元起': (7e6, 'JPY', 'year'),
        '南京全职财务分析师，熟练做预算和经营报表，年薪25万起': (25e4, 'CNY', 'year'),
        '全职远程供应链计划专员，熟悉跨境电商，月薪1.8万起': (1.8e4, 'CNY', 'month'),
        '远程品牌设计师全职，月薪不低于2万': (2e4, 'CNY', 'month'),
        '我想找全职远程用户研究的工作，会做访谈，月薪两万起': (2e4, 'CNY', 'month'),
        'full-time school counselor in New Zealand, NZD 90k+': (9e4, 'NZD', 'year'),
        'Toronto staff accountant, full-time, CAD 75k a year': (75e3, 'CAD', 'year'),
        '全职 remote UX writer，月薪 18k 起': (18e3, 'CNY', 'month'),
        'full-time remote technical recruiter, $70k+ per year': (7e4, 'USD', 'year'),
        '全职 remote sustainable sourcing manager，年薪 90k USD 起': (9e4, 'USD', 'year'),
        'I want a full-time remote science editor, at least $60k a year': (6e4, 'USD', 'year'),
        'full-time remote compensation analyst, $85k minimum': (85e3, 'USD', 'year'),
        '月薪 3000 欧元以上': (3000, 'EUR', 'month'),
        'hourly $40+ freelance': (40, 'USD', 'hour'),
    }
    for q, want in cases.items():
        got = query_pay(q)
        assert got and abs(got[0] - want[0]) < 1e-6 and got[1:] == want[1:], (q, got)
    for q in ['全职远程电商售后主管，带过10人客服团队', 'contract bookkeeper, 10 hours a week, remote', '后端 5年经验 以上',
              'six-month contract event producer in Austin', 'open-source bounty: fix a race in a Go CLI', '周三晚带成人课程',
              'Rust 项目 10k stars 开源']:
        assert query_pay(q) is None, (q, query_pay(q))


def test_traditional_folds_to_simplified():
    from rankai.text import to_simplified, tokens
    assert to_simplified('財務會計 台北 餐廳內場廚師') == '财务会计 台北 餐厅内场厨师'
    assert tokens('財務') == tokens('财务')
    assert to_simplified('remote engineer') == 'remote engineer'


def test_negated_remote_is_on_site():
    from rankai.text import remote_flag
    assert remote_flag('[广州][不支持远程] 高级全栈工程师') == 0.0
    assert remote_flag('Ruby 全栈', '此岗位仅仅接受现场办公 不接受远程支持') == 0.0
    assert remote_flag('Remote - USA', 'Coinbase is a remote-first, but not remote-only company.') == 1.0
    assert remote_flag('远程 兼职 前端') == 1.0
