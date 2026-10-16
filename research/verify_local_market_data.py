"""Independent checks of the recorded inventory. Reads source files; never repairs them."""
from __future__ import annotations
import csv
import hashlib
import json
import math
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

def resolve_source(file_id, primary, secondary):
    owner, kind, name = file_id.split('/', 2)
    folder = {'raw': '分钟_当月下月_拼接/_raw', 'continuous': '分钟_当月下月_拼接', 'main': '分钟'}[kind]
    return (primary if owner == 'primary' else secondary) / folder / name

def verify(inventory, primary=None, secondary=None):
    primary = Path(primary or os.environ.get('IM_IH_AUDIT_SOURCE_ROOT', ROOT.parent/'数据/期货/股指期货'))
    secondary = Path(secondary or os.environ.get('IM_IH_AUDIT_SECONDARY_ROOT', ROOT.parent.parent/'1-AI学习/股指期货'))
    mismatches = []
    checked = 0
    for p in inventory['profiles']:
        path = resolve_source(p['file_id'], primary, secondary)
        h = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024*1024), b''):
                h.update(chunk)
        checked += 1
        if h.hexdigest() != p['sha256']:
            mismatches.append(p['file_id'])
    anomalies = Counter()
    for p in inventory['profiles']:
        if not p['file_id'].startswith('primary/raw/') or not p['invalid_price_rows']:
            continue
        with resolve_source(p['file_id'], primary, secondary).open(encoding='utf-8-sig', newline='') as stream:
            for row in csv.DictReader(stream):
                try:
                    values = [float(row[x]) for x in ('open','high','low','close')]
                except (ValueError, TypeError):
                    values = [float('nan')]
                if not all(math.isfinite(x) for x in values):
                    anomalies['nonfinite_ohlc_rows'] += 1
                    anomalies['datetime_contains_nul_rows'] += int('\x00' in str(row['datetime'] or ''))
                    anomalies['structurally_short_rows'] += int(any(v is None for v in row.values()))
                    anomalies['all_fields_empty_rows'] += int(all(not str(v or '').strip() for v in row.values()))
                    anomalies['empty_datetime_rows'] += int(not str(row['datetime'] or '').strip())
                anomalies['actual_zero_or_negative_ohlc_rows'] += int(any(x <= 0 for x in values))
    cases = []
    for expected in inventory['event_date_coverage_only']:
        observed = []
        for symbol in ('IM','IH'):
            with (primary/'分钟_当月下月_拼接/_raw'/f"{symbol}{expected['month']}_1分钟.csv").open(encoding='utf-8-sig', newline='') as stream:
                labels = [r['datetime'] for r in csv.DictReader(stream) if r['datetime'].startswith(expected['date'])]
            observed.append(labels)
        a,b = map(set, observed)
        cases.append({'date':expected['date'], 'month':expected['month'],
                      'im_rows':len(observed[0]), 'ih_rows':len(observed[1]),
                      'shared_labels':len(a & b), 'duplicates':sum(len(v)-len(set(v)) for v in observed),
                      'agrees_with_inventory':len(a & b)==expected['common_labels'] and len(observed[0])==expected['im_rows'] and len(observed[1])==expected['ih_rows']})
    label_sets, clock = {}, {}
    start = set(range(570,690)) | set(range(780,900))
    end = set(range(571,691)) | set(range(781,901))
    for symbol,label in (('IM','中证1000'),('IH','上证50')):
        df = pd.read_csv(primary/'分钟_当月下月_拼接'/f'{label}_{symbol}_1分钟_当月下月拼接.csv', usecols=['datetime'])
        t = pd.to_datetime(df['datetime'], errors='raise')
        label_sets[symbol] = set(t)
        grids = Counter(); examples = {'start':[], 'end':[], 'other':[]}
        for day, group in t.groupby(t.dt.strftime('%Y-%m-%d')):
            minutes = set(group.dt.hour*60+group.dt.minute)
            kind = 'start' if minutes == start else 'end' if minutes == end else 'other'
            grids[kind] += 1
            if len(examples[kind])<6: examples[kind].append(day)
        clock[symbol] = {'day_grid_counts':dict(grids), 'examples':examples}
    imdays = {x.strftime('%Y-%m-%d') for x in label_sets['IM']}
    ihdays = {x.strftime('%Y-%m-%d') for x in label_sets['IH']}
    unmatched = Counter(x.strftime('%Y-%m-%d') for x in label_sets['IM'] ^ label_sets['IH'] if x.strftime('%Y-%m-%d') in imdays & ihdays)
    return {'checked_at':datetime.now(timezone.utc).isoformat(),
            'hashes_rechecked':checked, 'hash_mismatches':mismatches,
            'independent_csv_anomaly_counts':dict(anomalies), 'independent_case_checks':cases,
            'continuous_day_grids':clock, 'im_observed_dates_absent_from_ih':sorted(imdays-ihdays),
            'ih_only_date_count':len(ihdays-imdays),
            'shared_day_unmatched_labels_by_date':dict(sorted(unmatched.items())),
            'limits':['Grid names are diagnostic hypotheses, not verified vendor bar semantics.',
                      'Matching labels and hashes do not establish synchronized quotes, complete trading calendars or fills.']}

if __name__ == '__main__':
    inventory_path = ROOT/'data/local_market_data_inventory_20261016.json'
    result = verify(json.loads(inventory_path.read_text(encoding='utf8')))
    (ROOT/'data/local_market_data_verification_20261016.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
