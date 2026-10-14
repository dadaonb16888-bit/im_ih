import copy
import unittest
from unittest.mock import patch

import test_ai_research as fixture
from test_news_screening import rounds
from event_engine.engine import utc
from event_engine.news_screening import NewsScreening

SCREEN = utc('2026-10-13T11:00:00+08:00')
AFTER = utc('2026-10-13T13:00:00+08:00')


class ResearchQueueTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.AIResearchTests(); self.f.setUp()
        self.engine = self.f.engine
        self.screen = NewsScreening(self.engine)
        self.engine.link_information('fixture-event', 'fixture-news')
        self.apply_screen(['fixture-news'], 'screen1', SCREEN)

    def tearDown(self):
        self.f.tearDown()

    def apply_screen(self, ids, pid, at):
        pack = {'pack_id': pid, 'actor': 'Codex', 'version': 'news-screening-v1',
            'generated_at': fixture.OLD, 'screenings': [
                {'screening_id': pid + iid, 'information_id': iid, 'summary': 'Synthetic short fact',
                 'input_rounds': rounds()} for iid in ids]}
        with patch('event_engine.news_screening.now', return_value=at):
            self.screen.apply_pack(pack)

    def queue(self, at=fixture.KNOWN):
        return self.screen.report(at)['research_queue']

    def review(self, gaps=None):
        a = self.f.assessment()
        if gaps is not None: a['gaps'] = gaps
        self.f.research.apply_pack(self.f.pack(a))

    def test_related_news_grouped_once_and_new_source_requires_review(self):
        self.review()
        self.engine.add_information(self.f.make_source('second'))
        self.engine.link_information('fixture-event', 'second')
        self.apply_screen(['second'], 'screen2', SCREEN)
        queue = self.queue()
        self.assertEqual(len(queue['tasks']), 1)
        self.assertEqual(queue['tasks'][0]['source_count'], 2)
        self.assertEqual(queue['tasks'][0]['status'], 'NeedsReview')
        self.assertIsNone(queue['tasks'][0]['research_bias'])

    def test_latest_review_with_gaps_is_waiting_not_pending_repeated_research(self):
        self.review()
        queue = self.queue(); task = queue['tasks'][0]
        self.assertEqual(task['status'], 'ReviewedWithGaps')
        self.assertEqual(queue['counts']['NeedsReview'], 0)
        self.assertTrue(task['gaps'])
        self.assertFalse(task['trade_permission'])
        self.assertFalse(queue['entry_allowed'])

    def test_complete_review_is_research_completion_only(self):
        self.review([])
        task = self.queue()['tasks'][0]
        self.assertEqual(task['status'], 'Reviewed')
        self.assertFalse(task['entry_allowed'])
        self.assertEqual(self.engine.db.execute('SELECT count(*) FROM state_updates').fetchone()[0], 0)

    def test_old_assessment_and_future_assessment_not_used(self):
        self.review()
        self.assertEqual(self.queue(SCREEN)['tasks'][0]['status'], 'NeedsReview')
        self.apply_screen(['fixture-news'], 'screen2', AFTER)
        self.assertEqual(self.queue(AFTER)['tasks'][0]['status'], 'NeedsReview')
        self.assertEqual(self.queue()['tasks'][0]['status'], 'ReviewedWithGaps')

    def test_changed_causal_digest_requires_new_review(self):
        self.review()
        self.engine.update_event({'update_id': 'new-cause', 'event_id': 'fixture-event',
            'known_at': AFTER, 'effective_at': AFTER, 'source_type': 'News',
            'information_gain': 'Low', 'facts': 'Synthetic follow-up', 'reason': 'Synthetic clarification',
            'evidence': ['https://fixture.invalid/fixture-news'], 'changes': {}})
        self.assertEqual(self.queue(AFTER)['tasks'][0]['status'], 'NeedsReview')
        self.assertEqual(self.queue()['tasks'][0]['status'], 'ReviewedWithGaps')

    def test_unlinked_and_ambiguous_news_never_choose_arbitrary_parent(self):
        self.engine.add_information(self.f.make_source('unlinked'))
        self.apply_screen(['unlinked'], 'unlinked', SCREEN)
        self.engine.create_event({'event_id': 'other', 'name': 'Other synthetic cause',
            'known_at': fixture.OLD, 'category': 'TECH', 'detection_mode': 'News'})
        self.engine.link_information('other', 'fixture-news')
        queue = self.queue()
        self.assertEqual(queue['tasks'], [])
        self.assertEqual(len(queue['needs_association']), 2)

    def test_future_parent_not_visible_and_old_background_not_researched(self):
        self.engine.create_event({'event_id': 'future-parent', 'name': 'Future synthetic cause',
            'known_at': AFTER, 'category': 'TECH', 'detection_mode': 'News'})
        self.engine.link_information('future-parent', 'fixture-news')
        report = self.screen.report(fixture.KNOWN)
        self.assertEqual(report['information'][0]['event_ids'], ['fixture-event'])
        self.assertEqual(len(report['research_queue']['tasks']), 1)
        pack = {'pack_id': 'background', 'actor': 'Codex', 'version': 'news-screening-v1',
            'generated_at': fixture.OLD, 'screenings': [{'screening_id': 'background',
                'information_id': 'fixture-news', 'summary': 'Repeat synthetic report',
                'input_rounds': {'round1': {**rounds()['round1'], 'duplicate': True}}}]}
        with patch('event_engine.news_screening.now', return_value=AFTER): self.screen.apply_pack(pack)
        self.assertEqual(self.queue(AFTER)['tasks'], [])
