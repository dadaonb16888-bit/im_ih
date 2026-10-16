"""Read-only local IM/IH minute-data inventory. No signals, fills, network or source writes."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
START_GRID = set(range(570, 690)) | set(range(780, 900))
END_GRID = set(range(571, 691)) | set(range(781, 901))
EVENT_CASES = [('2402', '2024-02-05'), ('2502', '2025-02-05'), ('2504', '2025-04-07')]

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def profile(path, file_id):
    before = path.stat()
    source_hash = digest(path)
    frame = pd.read_csv(path, encoding='utf-8-sig', low_memory=False)
    columns = list(frame.columns)
    times = pd.to_datetime(frame['datetime'], errors='coerce', format='mixed')
    if times.dt.tz is not None:
        raise ValueError('Explicit timezone found; review normalization before comparison: ' + file_id)
    price = frame.reindex(columns=['open', 'high', 'low', 'close']).apply(pd.to_numeric, errors='coerce')
    finite = price.notna().all(axis=1) & ~price.isin([float('inf'), float('-inf')]).any(axis=1)
    positive = price.gt(0).all(axis=1)
    consistent = (price['high'] >= price[['open', 'close', 'low']].max(axis=1)) & (price['low'] <= price[['open', 'close', 'high']].min(axis=1))
    bad_price = ~(finite & positive & consistent)
    duplicate_time = times.notna() & times.duplicated(keep=False)
    valid = times.notna() & ~bad_price & ~duplicate_time
    minute = times.dt.hour * 60 + times.dt.minute
    aligned = times.dt.second.eq(0) & times.dt.microsecond.eq(0)
    counts = times.dropna().dt.strftime('%Y-%m-%d').value_counts()
    extras = {}
    for col in ('volume', 'open_oi', 'close_oi'):
        if col not in frame:
            extras[col] = {'missing_column': True, 'null_rows': len(frame), 'negative_rows': 0}
            continue
        values = pd.to_numeric(frame[col], errors='coerce')
        extras[col] = {'missing_column': False, 'null_rows': int(values.isna().sum()),
                       'negative_rows': int(values.lt(0).sum()), 'zero_rows': int(values.eq(0).sum())}
    stat_after = path.stat()
    after_hash = digest(path)
    stable = before.st_size == stat_after.st_size and before.st_mtime_ns == stat_after.st_mtime_ns and source_hash == after_hash
    result = {'file_id': file_id, 'bytes': before.st_size, 'sha256': source_hash,
              'unchanged_during_read': stable, 'rows': len(frame), 'columns': columns,
              'start_stored': str(times.min()) if times.notna().any() else None,
              'end_stored': str(times.max()) if times.notna().any() else None,
              'timezone_stored': 'naive; not assigned or converted by this audit',
              'days_observed': len(counts), 'invalid_datetime_rows': int(times.isna().sum()),
              'duplicate_time_extra_rows': int(times.notna().sum() - times.dropna().nunique()),
              'rows_at_duplicated_times': int(duplicate_time.sum()), 'exact_duplicate_extra_rows': int(frame.duplicated().sum()),
              'reverse_time_steps': int(times.diff().dt.total_seconds().lt(0).sum()),
              'invalid_price_rows': int(bad_price.sum()), 'nonfinite_price_rows': int((~finite).sum()),
              'not_all_prices_positive_rows': int((~positive).sum()), 'inconsistent_ohlc_rows': int((~consistent & finite).sum()),
              'missing_by_column': {c: int(frame[c].isna().sum()) for c in columns},
              'additional_fields': extras, 'nonminute_aligned_rows': int((times.notna() & ~aligned).sum()),
              'outside_start_grid_rows': int((times.notna() & (~minute.isin(START_GRID) | ~aligned)).sum()),
              'outside_end_grid_rows': int((times.notna() & (~minute.isin(END_GRID) | ~aligned)).sum()),
              'outside_both_grids_rows': int((times.notna() & ~minute.isin(START_GRID | END_GRID)).sum()),
              'days_with_240_rows': int(counts.eq(240).sum()), 'days_under_240_rows': int(counts.lt(240).sum()),
              'days_over_240_rows': int(counts.gt(240).sum()),
              'endpoint_counts': {t: int(times.dt.strftime('%H:%M').eq(t).sum()) for t in ('09:30','09:31','11:29','11:30','13:00','13:01','14:59','15:00')},
              'hour_counts': {str(int(k)): int(v) for k,v in times.dt.hour.dropna().value_counts().sort_index().items()},
              'quote_columns': [c for c in columns if re.search(r'bid|ask|quote|买一|卖一|盘口', c, re.I)],
              'contract_count': int(frame['contract'].nunique()) if 'contract' in frame else None,
              'symbol_examples': frame['symbol'].dropna().astype(str).unique()[:3].tolist() if 'symbol' in frame else [],
              'valid_unique_time_rows': int(valid.sum())}
    slim = pd.DataFrame({'time': times, 'valid': valid, 'close': price['close']})
    if 'contract' in frame:
        slim['contract'] = frame['contract'].fillna('').astype(str)
        result['contract_change_steps'] = int((slim['contract'].ne(slim['contract'].shift()) & slim['contract'].shift().notna()).sum())
    result['incomplete_day_examples'] = sorted([{'date': d, 'rows': int(n)} for d,n in counts.items() if n != 240], key=lambda x:x['date'])[:6]
    return result, slim

def pair_labels(im, ih, name):
    # Exclude all ambiguous duplicate timestamps, not just one arbitrarily retained row.
    ai = pd.DatetimeIndex(im.loc[im['time'].notna(), 'time'].drop_duplicates())
    bi = pd.DatetimeIndex(ih.loc[ih['time'].notna(), 'time'].drop_duplicates())
    shared_days = set(ai.strftime('%Y-%m-%d')) & set(bi.strftime('%Y-%m-%d'))
    a = ai[ai.strftime('%Y-%m-%d').isin(shared_days)]
    b = bi[bi.strftime('%Y-%m-%d').isin(shared_days)]
    common = a.intersection(b)
    union = a.union(b)
    va = pd.DatetimeIndex(im.loc[im['valid'], 'time'])
    vb = pd.DatetimeIndex(ih.loc[ih['valid'], 'time'])
    usable = va.intersection(vb)
    return {'pair': name, 'shared_observed_days': len(shared_days), 'im_labels_on_shared_days': len(a),
            'ih_labels_on_shared_days': len(b), 'common_labels': len(common), 'union_labels': len(union),
            'im_only_labels_on_shared_days': len(a.difference(b)), 'ih_only_labels_on_shared_days': len(b.difference(a)),
            'common_over_union': len(common)/len(union) if len(union) else None,
            'usable_both_price_unique_rows': len(usable),
            'first_common_stored': str(common.min()) if len(common) else None,
            'last_common_stored': str(common.max()) if len(common) else None}

def audit(primary=None, secondary=None):
    primary = Path(primary or os.environ.get('IM_IH_AUDIT_SOURCE_ROOT', ROOT.parent/'数据/期货/股指期货'))
    secondary = Path(secondary or os.environ.get('IM_IH_AUDIT_SECONDARY_ROOT', ROOT.parent.parent/'1-AI学习/股指期货'))
    raw = primary/'分钟_当月下月_拼接/_raw'
    raw_files = [p for p in sorted(raw.glob('*_1分钟.csv')) if re.fullmatch(r'(IM|IH)\d{4}_1分钟\.csv',p.name)]
    if not raw_files: raise ValueError('No concrete IM/IH raw minute files in configured source root')
    profiles, raw_slim, continuous, main = [], {}, {}, {}
    for path in raw_files:
        contract = path.name.split('_')[0]
        result, slim = profile(path, 'primary/raw/'+path.name)
        result['contract_from_filename'] = contract
        profiles.append(result); raw_slim[contract] = slim
    for symbol, label in (('IM','中证1000'),('IH','上证50')):
        for kind, folder, filename, bucket in (
            ('continuous','分钟_当月下月_拼接',f'{label}_{symbol}_1分钟_当月下月拼接.csv',continuous),
            ('main','分钟',f'{label}_CFFEX_{symbol}_1分钟.csv',main)):
            path = primary/folder/filename
            if path.exists():
                result, slim = profile(path,'primary/'+kind+'/'+filename)
                profiles.append(result); bucket[symbol] = slim
    secondary_slim = {}
    if secondary.exists():
        selected = list((secondary/'分钟_当月下月_拼接').glob('中证1000_IM_1分钟_当月下月拼接*.csv'))
        selected += list((secondary/'分钟_当月下月_拼接').glob('上证50_IH_1分钟_当月下月拼接.csv'))
        for path in sorted(selected):
            result, slim = profile(path,'secondary/continuous/'+path.name)
            profiles.append(result); secondary_slim[path.name] = slim
    suffixes = sorted(set(k[2:] for k in raw_slim if k.startswith('IM')) & set(k[2:] for k in raw_slim if k.startswith('IH')))
    pairs = [pair_labels(raw_slim['IM'+s],raw_slim['IH'+s],s) for s in suffixes]
    cases = []
    for suffix,date in EVENT_CASES:
        im,ih=raw_slim.get('IM'+suffix),raw_slim.get('IH'+suffix)
        if im is None or ih is None:
            cases.append({'month':suffix,'date':date,'available':False});continue
        a=im.loc[im['time'].dt.strftime('%Y-%m-%d').eq(date)]
        b=ih.loc[ih['time'].dt.strftime('%Y-%m-%d').eq(date)]
        cases.append({'month':suffix,'date':date,'available':True,'im_rows':len(a),'ih_rows':len(b),
                      **pair_labels(a,b,suffix),
                      'im_first_stored':str(a['time'].min()),'im_last_stored':str(a['time'].max()),
                      'ih_first_stored':str(b['time'].min()),'ih_last_stored':str(b['time'].max())})
    cont_pair = None
    if set(continuous)=={'IM','IH'}:
        a,b=continuous['IM'],continuous['IH']
        cont_pair=pair_labels(a,b,'calendar-continuous')
        ac=a.loc[a['valid']].set_index('time');bc=b.loc[b['valid']].set_index('time')
        both=ac.index.intersection(bc.index)
        mismatch=ac.loc[both,'contract'].str[2:].to_numpy()!=bc.loc[both,'contract'].str[2:].to_numpy()
        cont_pair['month_mismatch_rows']=int(mismatch.sum())
        cont_pair['month_mismatch_days']=len(set(both[mismatch].strftime('%Y-%m-%d')))
        cont_pair['month_mismatch_examples']=[{'time':str(t),'im':ac.at[t,'contract'],'ih':bc.at[t,'contract']} for t in both[mismatch][:5]]
    main_diagnostics=[]
    for symbol, slim in main.items():
        if symbol not in continuous:continue
        a=pd.DatetimeIndex(slim['time'].dropna().drop_duplicates())
        b=pd.DatetimeIndex(continuous[symbol]['time'].dropna().drop_duplicates())
        main_diagnostics.append({'symbol':symbol,'as_stored_label_intersection':len(a.intersection(b)),
                                 'plus_8_hours_label_intersection':len((a+pd.Timedelta(hours=8)).intersection(b)),
                                 'interpretation':'clock-alignment diagnostic only; not a timezone proof or automatic conversion'})
    summary={'primary_raw_files':len(raw_files),'im_raw_files':sum(k.startswith('IM') for k in raw_slim),
             'ih_raw_files':sum(k.startswith('IH') for k in raw_slim),'same_month_pairs':len(pairs),
             'files_profiled':len(profiles),'rows_profiled':sum(p['rows'] for p in profiles),
             'files_with_quote_columns':sum(bool(p['quote_columns']) for p in profiles),
             'source_files_unchanged':all(p['unchanged_during_read'] for p in profiles),
             'raw_rows_with_invalid_prices':sum(p['invalid_price_rows'] for p in profiles if p['file_id'].startswith('primary/raw/')),
             'raw_duplicate_time_extra_rows':sum(p['duplicate_time_extra_rows'] for p in profiles if p['file_id'].startswith('primary/raw/'))}
    return {'checked_at':datetime.now(timezone.utc).isoformat(),'scope':'local file quality, not a strategy backtest or full-disk quote search',
            'summary':summary,'profiles':profiles,'raw_pair_labels':pairs,'event_date_coverage_only':cases,
            'continuous_pair':cont_pair,'main_clock_diagnostics':main_diagnostics,
            'interpretive_limits':['same minute label does not prove simultaneous trade/quote time',
                                   '240-row grids are diagnostics; no official trading-calendar or no-trade-bar convention verified',
                                   'raw filenames identify contracts but original vendor provenance per row is not certified',
                                   'no signal, return, strategy ranking, market confirmation, fill or source repair produced']}

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root');parser.add_argument('--secondary-root');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=audit(args.source_root,args.secondary_root)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(result['summary'],ensure_ascii=False))
