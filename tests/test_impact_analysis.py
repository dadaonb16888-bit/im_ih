"""Policy evidence guards use invented sources, never historical market claims."""
import copy
import unittest
from event_engine.impact_analysis import validate_impact_analysis


def analysis_fixture():
    return {'version': 'policy-paths-v1', 'policy_deltas': [{
        'item_id': 'delta', 'topic': 'Fixture proposed rule', 'new_fact': 'Proposed change',
        'baseline': 'Previous arrangement', 'new_source_ids': ['news'],
        'baseline_source_ids': ['old'], 'baseline_kind': 'EarlierSource',
        'change_type': 'Strengthened', 'stage': 'Draft', 'magnitude': None,
        'reason': 'Fixture comparison', 'limits': 'Implementation unknown'}],
        'beneficiary_paths': [{'path_id': 'path', 'beneficiary': 'Fixture company',
            'style': 'Both', 'benefit': 'Potential demand', 'offsets': 'Unverified costs',
            'effect': 'Unknown', 'effect_status': 'Hypothesis', 'exposure_type': 'Business',
            'exposure_as_of': '2026-10-13', 'source_ids': ['news'], 'limits': 'No profit estimate'}],
        'conclusion': 'No demonstrated relative advantage', 'limits': ['Fixture limitation']}


class ImpactAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.assessment = {'bias': None, 'impact_analysis': analysis_fixture()}
        self.sources = {'news': {'published_at': '2026-10-09'}, 'old': {'published_at': '2025-05-07'}}
        self.checks = {'news': 'Read', 'old': 'Partial'}

    def validate(self, at='2026-10-13T14:00:00Z'):
        validate_impact_analysis(self.assessment, self.sources, self.checks, at)

    def test_optional_analysis_preserves_legacy_and_unknown_direction(self):
        validate_impact_analysis({}, {}, {}, '2026-10-13T14:00:00Z')
        before = copy.deepcopy(self.assessment)
        self.validate()
        self.assertEqual(before, self.assessment)

    def test_unknown_baseline_cannot_claim_increment(self):
        row = self.assessment['impact_analysis']['policy_deltas'][0]
        row.update(baseline_kind='NotFound', baseline_source_ids=[])
        with self.assertRaises(ValueError): self.validate()
        row['change_type'] = 'Unknown'
        self.validate()

    def test_only_read_sources_can_support_tables(self):
        for status in ('Unavailable', None):
            with self.subTest(status=status):
                self.checks['old'] = status
                with self.assertRaises(ValueError): self.validate()

    def test_unknown_source_and_duplicate_reference_rejected(self):
        row = self.assessment['impact_analysis']['policy_deltas'][0]
        for ids in (['missing'], ['news', 'news']):
            row['new_source_ids'] = ids
            with self.assertRaises(ValueError): self.validate()

    def test_baseline_dates_require_strict_prior_day(self):
        for value in ('2026-10-09', '2026-10-10', 'not-a-date', None):
            with self.subTest(value=value):
                self.sources['old']['published_at'] = value
                with self.assertRaises(ValueError): self.validate()

    def test_issuer_comparison_is_explicit_not_fake_prior_document(self):
        row = self.assessment['impact_analysis']['policy_deltas'][0]
        row.update(baseline_kind='IssuerComparison', baseline_source_ids=['news'])
        self.validate()

    def test_sector_proxy_cannot_verify_enterprise_net_benefit(self):
        row = self.assessment['impact_analysis']['beneficiary_paths'][0]
        row.update(exposure_type='SectorProxy', effect_status='VerifiedMechanism')
        with self.assertRaises(ValueError): self.validate()
        row['effect_status'] = 'Hypothesis'
        self.validate()

    def test_business_exposure_requires_nonfuture_date(self):
        row = self.assessment['impact_analysis']['beneficiary_paths'][0]
        for value in (None, '2026-10-14', 'wrong'):
            row['exposure_as_of'] = value
            with self.assertRaises(ValueError): self.validate()

    def test_exposure_date_uses_china_calendar_across_utc_midnight(self):
        self.validate('2026-10-12T16:01:00Z')

    def test_disclosed_portfolio_keeps_report_date_and_requires_read_source(self):
        row = self.assessment['impact_analysis']['beneficiary_paths'][0]
        row.update(exposure_type='PortfolioDisclosure', exposure_as_of='2026-06-30')
        self.validate()
        for value in (None, '2026-10-14'):
            row['exposure_as_of'] = value
            with self.assertRaises(ValueError): self.validate()
        row['exposure_as_of'] = '2026-06-30'
        self.checks['news'] = 'Unavailable'
        with self.assertRaises(ValueError): self.validate()

    def test_unknown_fields_and_duplicate_row_ids_rejected(self):
        rows = self.assessment['impact_analysis']['policy_deltas']
        rows.append(copy.deepcopy(rows[0]))
        with self.assertRaises(ValueError): self.validate()
        rows.pop()
        rows[0]['automatic_bias'] = 'Strong IM'
        with self.assertRaises(ValueError): self.validate()

