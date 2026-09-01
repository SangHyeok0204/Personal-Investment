# -*- coding: utf-8 -*-
"""[시장 시그널] [G] 자가 검사 — 검사기가 실제로 검사하고 있는가 (2026-08-31).

`test_market_signal.py` 의 각 항목이 **정말 그 결함을 막고 있는지**를, 결함을 코드에
도로 심어 보고 테스트가 FAIL 로 뒤집히는지로 확인한다. pytest 로 안 돌린다 —
소스를 임시로 고쳤다 되돌리므로 일반 테스트 실행에 섞이면 안 된다.

    실행:  python tests/check_market_signal_selfcheck.py   (apps/collector 에서)

⚠️주입 도중 프로세스가 죽으면 소스가 고쳐진 채 남을 수 있다. finally 로 원복하지만,
  이상하면 `git diff apps/collector/collector/market_signal` 로 확인할 것.

★통과만 하는 검사기는 검사기가 아니다. 각 항목은 (정상=PASS, 주입후=FAIL) 이어야
  그 테스트가 실제로 그 결함을 막고 있다고 말할 수 있다.
"""
import sys, io, os, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 저장소 안에서 자기 위치로 경로를 잡는다(UNC 하드코딩 금지 — 컨테이너에서도 돌아야 한다).
_HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(_HERE)                      # apps/collector
MS = os.path.join(APP, 'collector', 'market_signal')
ENV = dict(os.environ,
           MS_KNOWLEDGE_TTL=os.path.join(MS, 'knowledge.ttl'),
           MS_MARKETS_TTL=os.path.join(MS, 'markets.ttl'))

NL = chr(10)

# (설명, [(파일, 원본, 버그), ...], 뒤집혀야 할 테스트)
INJ = [
    ("금리 방향 반전 제거", [
        ('graph.py', '    return -d if sig.get("is_yield") else d', '    return d')],
     "test_price_direction_inverts_for_yields"),

    ("비교 지평을 항상 당일로", [
        ('graph.py', '    h = RULE_HORIZON.get(sig.get("rule"), "dtd")',
         '    return "dtd"' + NL + '    h = RULE_HORIZON.get(sig.get("rule"), "dtd")')],
     "test_comparison_horizon_matches_rule"),

    ("동인 부호검사를 크기검사로", [
        ('graph.py', '    return da == b', '    return True')],
     "test_same_dir_checks_sign_not_just_magnitude"),

    # ★원래 결함 그대로: 사상 최고가면 직전 극값을 못 찾아 None 을 돌려주고,
    #   조건이 `is None or ...` 이라 **무조건 발화**했다. 두 곳을 함께 되돌려야 재현된다.
    ("range_break 원래 결함(None→무조건 발화)", [
        ('signal_rules.py', '    for i in range(len(ds) - 2, -1, -1):',
         '    return None' + NL + '    for i in range(len(ds) - 2, -1, -1):'),
        ('signal_rules.py',
         '        if (quiet is not None and quiet >= RANGE_NEW_D',
         '        if (quiet is None or quiet >= RANGE_NEW_D')],
     "test_range_break_does_not_fire_every_day_in_a_trend"),

    ("매크로 최소겹침을 1년용과 동일하게", [
        ('build_graph.py', 'MIN_OVERLAP_MACRO = 15', 'MIN_OVERLAP_MACRO = 60')],
     "test_macro_overlap_threshold_is_separate_from_yearly"),

    ("체제판정의 금리 반전 제거", [
        ('build_graph.py', '    if is_yield:' + NL + '        r6 = None if r6 is None else -r6',
         '    if False:' + NL + '        r6 = None if r6 is None else -r6')],
     "test_regime_inverts_for_yields"),

    ("채권 표시명에서 국가명 제거", [
        ('signal_rules.py',
         '            disp = f"{sub} {label}" if (c["yield"] and sub) else label',
         '            disp = label')],
     "test_bond_label_carries_country"),
]


def run(test):
    r = subprocess.run(
        [sys.executable, '-m', 'pytest',
         os.path.join(_HERE, 'test_market_signal.py'),
         '-q', '-k', test, '--no-header'],
        capture_output=True, text=True, env=ENV, cwd=APP)
    return r.returncode


print('%-38s %-7s %-7s %s' % ('주입한 결함', '정상', '주입후', '판정'))
print('-' * 74)
ok = 0
for desc, edits, test in INJ:
    originals = {}
    bad = None
    for fname, orig, bug in edits:
        p = os.path.join(MS, fname)
        src = originals.get(p) or io.open(p, encoding='utf-8').read()
        originals.setdefault(p, src)
        if src.count(orig) != 1:
            bad = '앵커 %d건' % src.count(orig)
            break
    if bad:
        print('%-38s %s' % (desc, bad + ' — 검사 불가'))
        continue

    before = run(test)
    # 주입
    cur = {p: s for p, s in originals.items()}
    for fname, orig, bug in edits:
        p = os.path.join(MS, fname)
        cur[p] = cur[p].replace(orig, bug, 1)
    for p, s in cur.items():
        io.open(p, 'w', encoding='utf-8').write(s)
    try:
        after = run(test)
    finally:
        for p, s in originals.items():          # ★반드시 원복
            io.open(p, 'w', encoding='utf-8').write(s)

    flipped = (before == 0 and after != 0)
    ok += 1 if flipped else 0
    print('%-38s %-7s %-7s %s' % (desc, 'PASS' if before == 0 else 'FAIL',
                                  'PASS' if after == 0 else 'FAIL',
                                  'OK 뒤집힘' if flipped else '★검사기 무력'))
print('-' * 74)
print('%d/%d 항목이 결함 주입 시 실제로 FAIL 로 뒤집혔다' % (ok, len(INJ)))
