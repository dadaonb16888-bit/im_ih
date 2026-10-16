"""Offline quality gates must not convert intact-looking bars into certified inputs."""
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from research.minute_data_admission import digest, inspect_file, inspect_pair, inspect_record


def row(time='2024-02-05 09:30:00', **changes):
    value = dict(datetime=time, open='10', high='12', low='9', close='11')
    return dict(value, **changes)


def complete_day(start_like=True):
    starts = [(9, 30), (13, 0)] if start_like else [(9, 31), (13, 1)]
    labels = [datetime(2024, 2, 5, h, m) + timedelta(minutes=i) for h,m in starts for i in range(120)]
    return [inspect_record(row(t.isoformat(sep=' ')), i+1) for i,t in enumerate(labels)]


class MinuteDataAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'IM2402_1分钟.csv'

    def write(self, rows):
        with self.path.open('w', encoding='utf8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['datetime','open','high','low','close'])
            writer.writeheader(); writer.writerows(rows)
        return digest(self.path)

    def test_nul_short_record_cannot_be_assigned_to_an_event_day(self):
        item = inspect_record({'datetime':'\x00'*25,'open':None,'high':None,'low':None,'close':None}, 7)
        self.assertIsNone(item['time'])
        self.assertEqual(set(item['reasons']), {'NUL_BYTE','MALFORMED_RECORD','INVALID_DATETIME','PRICE_MISSING_OR_NONFINITE'})

    def test_invalid_ohlc_domains_are_rejected(self):
        for changes,reason in [({'open':''},'PRICE_MISSING_OR_NONFINITE'),({'close':'inf'},'PRICE_MISSING_OR_NONFINITE'),
                               ({'low':'0'},'PRICE_NOT_POSITIVE'),({'high':'10'},'OHLC_INCONSISTENT')]:
            with self.subTest(changes=changes):
                self.assertIn(reason, inspect_record(row(**changes), 1)['reasons'])

    def test_all_duplicate_time_records_are_quarantined(self):
        expected = self.write([row(), row(close='10.5'), row('2024-02-05 09:31:00')])
        summary, records, quarantine = inspect_file(self.path, 'primary/raw/IM2402_1分钟.csv', expected)
        self.assertEqual([q['csv_record_ordinal'] for q in quarantine], [1,2])
        self.assertTrue(all('DUPLICATE_TIME' in q['reasons'] for q in quarantine))
        self.assertEqual(summary['structurally_valid_rows'],1)
        self.assertNotIn('open',json.dumps(quarantine))
        self.assertNotIn(str(self.path),json.dumps(summary))

    def test_fractional_minute_and_aware_clock_are_not_silently_shifted(self):
        for label in ('2024-02-05 09:30:01','2024-02-05 09:30:00.000000001'):
            self.assertIn('NOT_MINUTE_ALIGNED',inspect_record(row(label),1)['reasons'])
        item=inspect_record(row('2024-02-05 01:30:00+00:00'),1)
        self.assertIsNone(item['time'])
        self.assertIn('UNREVIEWED_TIMEZONE',item['reasons'])

    def test_changed_source_is_rejected_without_repair(self):
        old=self.write([row()]); self.write([row(close='10.5')]);before=self.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED_SINCE_INVENTORY'):
            inspect_file(self.path,'primary/raw/IM2402_1分钟.csv',old)
        self.assertEqual(self.path.read_bytes(),before)

    def test_change_during_read_does_not_produce_a_dossier(self):
        sha=self.write([row()])
        with patch('research.minute_data_admission.digest',side_effect=[sha,'changed']):
            with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED_DURING_READ'):
                inspect_file(self.path,'primary/raw/IM2402_1分钟.csv',sha)

    def test_schema_drift_is_not_accepted_by_column_position(self):
        self.path.write_text('datetime,open,high,low,last\n2024-02-05 09:30:00,10,12,9,11\n',encoding='utf8')
        with self.assertRaisesRegex(ValueError,'UNSUPPORTED_SCHEMA'):
            inspect_file(self.path,'primary/raw/IM2402_1分钟.csv',digest(self.path))

    def test_complete_paired_grid_does_not_prove_time_semantics(self):
        result=inspect_pair(complete_day(),complete_day(),'2024-02-05','IM2402','IH2402')
        self.assertEqual(result['common_structurally_valid_labels'],240)
        self.assertTrue(result['structurally_aligned_observation'])
        self.assertFalse(result['research_admitted']); self.assertFalse(result['entry_allowed'])
        self.assertIn('BAR_SEMANTICS_UNVERIFIED',result['blockers'])
        self.assertIn('TIMEZONE_UNVERIFIED',result['blockers'])

    def test_start_end_grid_disagreement_is_not_auto_shifted(self):
        result=inspect_pair(complete_day(),complete_day(False),'2024-02-05','IM2402','IH2402')
        self.assertEqual(result['common_stored_labels'],238)
        self.assertEqual((result['im_only_labels'],result['ih_only_labels']),(2,2))
        self.assertIn('GRID_DIAGNOSTICS_DIFFER',result['blockers'])
        self.assertFalse(result['structurally_aligned_observation'])

    def test_absent_leg_is_not_filled_or_hidden_by_an_inner_join(self):
        result=inspect_pair(complete_day(),[],'2024-02-05','IM2402','IH2402')
        self.assertEqual(result['ih']['grid_diagnostic'],'Absent')
        self.assertEqual(result['common_structurally_valid_labels'],0)
        self.assertEqual(result['im_only_labels'],240)
        self.assertIn('ONE_OR_BOTH_LEGS_ABSENT',result['blockers'])

    def test_mixed_expiry_pairing_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'SAME_EXPIRY_CONTRACTS_REQUIRED'):
            inspect_pair(complete_day(),complete_day(),'2024-02-05','IM2402','IH2403')

    def test_existing_audit_file_is_preserved(self):
        output=Path(self.temp.name)/'prior.json';output.write_text('prior audit',encoding='utf8')
        script=Path(__file__).resolve().parents[1]/'research/minute_data_admission.py'
        result=subprocess.run([sys.executable,str(script),'--output',str(output)],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Output already exists',result.stderr)
        self.assertEqual(output.read_text(encoding='utf8'),'prior audit')


if __name__=='__main__':
    unittest.main()
