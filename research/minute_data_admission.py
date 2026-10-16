"""Offline minute-record quarantine and evidence dossier. No normalization, prices or signals exported."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ('datetime', 'open', 'high', 'low', 'close')
START_GRID = frozenset(range(570, 690)) | frozenset(range(780, 900))
END_GRID = frozenset(range(571, 691)) | frozenset(range(781, 901))
MINUTE_LABEL = re.compile(r'\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:00(?:\.0+)?')


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def inspect_record(row, ordinal):
    """Return metadata only. Ordinal counts CSV data records, excluding the header."""
    reasons = []
    if None in row or any(row.get(k) is None for k in REQUIRED):
        reasons.append('MALFORMED_RECORD')
    if any('\x00' in str(v) for v in row.values()):
        reasons.append('NUL_BYTE')
    label = row.get('datetime') or ''
    time = None
    try:
        time = datetime.fromisoformat(label)
        if time.tzinfo is not None:
            reasons.append('UNREVIEWED_TIMEZONE')
            time = None  # No conversion or mixing of aware and naive timestamps.
        elif not MINUTE_LABEL.fullmatch(label):
            reasons.append('NOT_MINUTE_ALIGNED')
    except (ValueError, TypeError):
        reasons.append('INVALID_DATETIME')
    try:
        prices = [float(row[k]) for k in ('open', 'high', 'low', 'close')]
    except (ValueError, TypeError, KeyError):
        prices = [float('nan')] * 4
    if not all(math.isfinite(x) for x in prices):
        reasons.append('PRICE_MISSING_OR_NONFINITE')
    else:
        opening, high, low, close = prices
        if any(x <= 0 for x in prices):
            reasons.append('PRICE_NOT_POSITIVE')
        if high < max(opening, low, close) or low > min(opening, high, close):
            reasons.append('OHLC_INCONSISTENT')
    return {'ordinal': ordinal, 'time': time, 'reasons': reasons}


def inspect_file(path, file_id, expected_hash):
    before = digest(path)
    if before != expected_hash:
        raise ValueError('SOURCE_CHANGED_SINCE_INVENTORY: ' + file_id)
    records = []
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)) or not set(REQUIRED).issubset(fields):
            raise ValueError('UNSUPPORTED_SCHEMA: ' + file_id)
        for ordinal, row in enumerate(reader, 1):
            records.append(inspect_record(row, ordinal))
    if digest(path) != before:
        raise ValueError('SOURCE_CHANGED_DURING_READ: ' + file_id)
    frequency = Counter(r['time'] for r in records if r['time'] is not None)
    for record in records:
        if record['time'] is not None and frequency[record['time']] > 1:
            record['reasons'].append('DUPLICATE_TIME')
    counts = Counter(reason for r in records for reason in r['reasons'])
    quarantine = [
        {'file_id': file_id, 'csv_record_ordinal': r['ordinal'],
         'time_stored': r['time'].isoformat(sep=' ') if r['time'] is not None else None,
         'reasons': r['reasons']}
        for r in records if r['reasons']
    ]
    summary = {'file_id': file_id, 'sha256': before, 'rows_read': len(records),
               'quarantined_rows': len(quarantine), 'reason_counts': dict(counts),
               'structurally_valid_rows': len(records) - len(quarantine),
               'source_unchanged': True, 'vendor': None, 'timezone': None,
               'bar_label_semantics': None, 'official_calendar_verified': False,
               'data_use_status': 'DIAGNOSTIC_ONLY', 'research_admitted': False}
    return summary, records, quarantine


def observed_day(records, day):
    selected = [r for r in records if r['time'] is not None and r['time'].date().isoformat() == day]
    times = {r['time'] for r in selected}
    minutes = {t.hour * 60 + t.minute for t in times}
    grid = 'StartLike' if minutes == START_GRID else 'EndLike' if minutes == END_GRID else 'Other'
    valid = {r['time'] for r in selected if not r['reasons']}
    return {'date': day, 'rows': len(selected), 'unique_labels': len(times),
            'structurally_valid_unique_labels': len(valid),
            'quarantined_rows_with_known_date': sum(bool(r['reasons']) for r in selected),
            'grid_diagnostic': grid if selected else 'Absent',
            'first_stored': min(times).isoformat(sep=' ') if times else None,
            'last_stored': max(times).isoformat(sep=' ') if times else None}, times, valid


def inspect_pair(im_records, ih_records, day, im_contract, ih_contract):
    if not re.fullmatch(r'IM\d{4}', im_contract) or not re.fullmatch(r'IH\d{4}', ih_contract) or im_contract[2:] != ih_contract[2:]:
        raise ValueError('SAME_EXPIRY_CONTRACTS_REQUIRED')
    im, a, va = observed_day(im_records, day)
    ih, b, vb = observed_day(ih_records, day)
    blockers = ['TIMEZONE_UNVERIFIED', 'BAR_SEMANTICS_UNVERIFIED', 'ROW_VENDOR_UNVERIFIED', 'OFFICIAL_CALENDAR_UNVERIFIED']
    if not a or not b:
        blockers.append('ONE_OR_BOTH_LEGS_ABSENT')
    if a != b:
        blockers.append('UNMATCHED_LABELS')
    if len(va) != len(a) or len(vb) != len(b):
        blockers.append('QUARANTINED_LABELS')
    if im['grid_diagnostic'] != ih['grid_diagnostic']:
        blockers.append('GRID_DIAGNOSTICS_DIFFER')
    return {'date': day, 'im_contract': im_contract, 'ih_contract': ih_contract,
            'im': im, 'ih': ih, 'common_stored_labels': len(a & b),
            'common_structurally_valid_labels': len(va & vb),
            'im_only_labels': len(a - b), 'ih_only_labels': len(b - a),
            'structurally_aligned_observation': bool(a) and a == b and va == a and vb == b,
            'blockers': blockers, 'research_admitted': False, 'entry_allowed': False}


def build_dossier(inventory, contract, source_root):
    if contract['schema_version'] != 1 or contract['mode'] != 'DIAGNOSTIC_ONLY':
        raise ValueError('Unsupported contract version or mode')
    cases = contract['case_checks'] + contract['gap_checks']
    names = {leg + c['month'] for c in cases for leg in ('IM', 'IH')}
    selected = [p for p in inventory['profiles'] if p['file_id'].startswith('primary/raw/') and
                (p.get('contract_from_filename') in names or p['invalid_price_rows'] > 0)]
    found = {p.get('contract_from_filename') for p in selected}
    if not names.issubset(found):
        raise ValueError('Required case/gap contracts missing from inventory')
    files, records, quarantine = [], {}, []
    for profile in selected:
        file_id = profile['file_id']
        if not re.fullmatch(r'primary/raw/(IM|IH)\d{4}_1分钟\.csv', file_id):
            raise ValueError('Unsupported source identity')
        path = Path(source_root) / '分钟_当月下月_拼接/_raw' / file_id.split('/')[-1]
        summary, rows, bad = inspect_file(path, file_id, profile['sha256'])
        files.append(summary)
        records[profile['contract_from_filename']] = rows
        quarantine.extend(bad)
    def pairs(items):
        return [inspect_pair(records['IM'+c['month']], records['IH'+c['month']], c['date'],
                             'IM'+c['month'], 'IH'+c['month']) for c in items]
    return {'schema_version': 1, 'contract_id': contract['contract_id'],
            'checked_at': datetime.now(timezone.utc).isoformat(),
            'inventory_checked_at': inventory['checked_at'],
            'selection': 'six case contracts, four gap contracts, and all previously price-anomalous raw files; deduplicated',
            'summary': {'files_rechecked': len(files), 'rows_read': sum(p['rows_read'] for p in files),
                        'quarantined_rows': len(quarantine),
                        'structurally_valid_rows': sum(p['structurally_valid_rows'] for p in files),
                        'case_days': len(contract['case_checks']), 'gap_days': len(contract['gap_checks']),
                        'research_admitted_case_days': 0, 'entry_allowed': False},
            'files': files, 'quarantine_index': quarantine,
            'case_days': pairs(contract['case_checks']), 'gap_days': pairs(contract['gap_checks']),
            'limits': ['Unknown timezone/vendor/bar semantics remain null; diagnostic grids are not evidence of vendor conventions.',
                       'CSV record ordinal excludes header and is not a physical line number.',
                       'Unparseable timestamps cannot be assigned to a trading day; file-level quarantine remains.',
                       'No normalization, forward fill, raw prices, relative candle, signal or executable order produced.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, default=ROOT/'data/local_market_data_inventory_20261016.json')
    parser.add_argument('--contract', type=Path, default=ROOT/'data/minute_data_contract_v0_1.json')
    parser.add_argument('--source-root', type=Path, default=Path(os.environ.get('IM_IH_AUDIT_SOURCE_ROOT', ROOT.parent/'数据/期货/股指期货')))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Output already exists; use a new audit filename to preserve the old version')
    result = build_dossier(json.loads(args.inventory.read_text(encoding='utf8')),
                           json.loads(args.contract.read_text(encoding='utf8')), args.source_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create protects an existing audit from replacement by a concurrent run.
    with args.output.open('x', encoding='utf8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(result['summary'], ensure_ascii=False))
