"""Research scoring fixtures; no real news or production writes."""
import copy
import unittest
from event_engine.score_evidence import validate_score_basis, research_preview, RUBRIC_VERSION

PUBLIC = '2026-10-09T18:02:25+08:00'
KNOWN = '2026-10-13T20:00:00+08:00'


class ScoreEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.sources = {'fixture': {'url': 'https://fixture.invalid/news', 'published_at': PUBLIC}}
        self.checks = {'fixture': 'Read'}
        values = {'source': self.sources['fixture']['url'], 'source_reliability': 'A',
                  'impact_score': 2, 'confidence_score': .25, 'persistence_score': 1.0}
        self.card = {'assessment_id': 'test', 'event_id': 'event', 'known_at': KNOWN,
            'bias': 'IM', 'decision': 'Directional', 'horizon': 'Trend',
            'research_mode': 'CurrentReview', 'gaps': ['Missing exposure'], **values,
            'score_basis': {'rubric_version': RUBRIC_VERSION,
                'components': {k: {'value': v, 'reason': 'Fixture reasoning', 'source_ids': ['fixture']} for k, v in values.items()},
                'reference_time': {'value': PUBLIC, 'reason': 'Reference only', 'source_ids': ['fixture']}}}

    def validate(self):
        validate_score_basis(self.card, self.sources, self.checks, KNOWN)

    def test_reference_score_is_visible_research_only_not_formal_direction(self):
        self.validate()
        result = research_preview(self.card, KNOWN)
        self.assertGreater(result['score'], 0)
        self.assertEqual(result['event_strength'], .5)
        self.assertFalse(result['trade_permission'])
        self.assertFalse(result['entry_allowed'])
        self.assertEqual(result['time_basis'], 'SourcePublicationReference')

    def test_date_only_keeps_basic_strength_but_has_no_decayed_score(self):
        self.sources['fixture']['published_at'] = '2026-10-09'
        self.card['score_basis']['reference_time']['value'] = None
        self.validate()
        result = research_preview(self.card, KNOWN)
        self.assertEqual(result['event_strength'], .5)
        self.assertIsNone(result['score'])
        self.assertIsNone(result['freshness'])
        self.assertIn('event_time', result['score_gaps'])

    def test_date_only_cannot_be_filled_as_midnight(self):
        self.sources['fixture']['published_at'] = '2026-10-09'
        self.card['score_basis']['reference_time']['value'] = '2026-10-09T00:00:00+08:00'
        with self.assertRaises(ValueError):
            self.validate()

    def test_reference_requires_same_original_source_time(self):
        self.card['score_basis']['reference_time']['value'] = '2026-10-09T18:00:00+08:00'
        with self.assertRaises(ValueError):
            self.validate()

    def test_source_reference_in_future_is_rejected(self):
        self.card['score_basis']['reference_time']['value'] = '2026-10-14T00:00:00+08:00'
        with self.assertRaises(ValueError):
            self.validate()

    def test_numeric_value_cannot_diverge_from_rationale(self):
        self.card['score_basis']['components']['impact_score']['value'] = 5
        with self.assertRaises(ValueError):
            self.validate()

    def test_all_components_need_reasons_and_evidence(self):
        for field in ('source', 'source_reliability', 'impact_score', 'confidence_score', 'persistence_score'):
            original = copy.deepcopy(self.card)
            self.card['score_basis']['components'][field]['reason'] = ''
            with self.assertRaises(ValueError):
                self.validate()
            self.card = copy.deepcopy(original)
            self.card['score_basis']['components'][field]['source_ids'] = []
            with self.assertRaises(ValueError):
                self.validate()
            self.card = copy.deepcopy(original)

    def test_unread_or_unreferenced_evidence_cannot_support_score(self):
        self.checks['fixture'] = 'Unavailable'
        with self.assertRaises(ValueError):
            self.validate()
        self.checks['fixture'] = 'Read'
        self.card['score_basis']['components']['impact_score']['source_ids'] = ['other']
        with self.assertRaises(ValueError):
            self.validate()

    def test_claimed_source_url_must_match_cited_source(self):
        self.card['source'] = 'https://fixture.invalid/unread'
        self.card['score_basis']['components']['source']['value'] = self.card['source']
        with self.assertRaises(ValueError):
            self.validate()

    def test_unknown_direction_cannot_use_factual_confidence(self):
        self.card.update({'decision': 'InsufficientEvidence', 'bias': None})
        with self.assertRaises(ValueError):
            self.validate()
        self.card['confidence_score'] = None
        self.card['score_basis']['components']['confidence_score']['value'] = None
        self.validate()
        self.assertIsNone(research_preview(self.card, KNOWN)['score'])

    def test_future_card_not_visible(self):
        self.assertIsNone(research_preview(self.card, '2026-10-13T19:59:59+08:00'))

    def test_legacy_numeric_card_without_audited_basis_is_unscored(self):
        del self.card['score_basis']
        self.validate()
        result = research_preview(self.card, KNOWN)
        self.assertIsNone(result['score'])
        self.assertEqual(result['score_gaps'], ['score_basis_missing'])

    def test_unknown_rubric_and_incomplete_contract_rejected(self):
        self.card['score_basis']['rubric_version'] = 'unknown'
        with self.assertRaises(ValueError):
            self.validate()
        self.card['score_basis']['rubric_version'] = RUBRIC_VERSION
        del self.card['score_basis']['components']['impact_score']
        with self.assertRaises(ValueError):
            self.validate()
