import copy
import unittest
from event_engine.fund_flow import compare_shares


class FundFlowTests(unittest.TestCase):
    def setUp(self):
        self.at='2026-10-14T09:20:00+08:00'
        self.previous={'fund_code':'512100','share_date':'2026-10-09','measure':'TotalShares','value':'100','unit':'万份',
                       'source_id':'fixture-before','source_url':'https://example.invalid/previous','read_status':'Read','known_at':self.at}
        self.current={**self.previous,'share_date':'2026-10-12','value':'120','source_id':'fixture-after'}
        self.nav={'fund_code':'512100','nav_date':'2026-10-12','measure':'UnitNAV','value':'2','currency':'CNY',
                  'source_id':'fixture-nav','source_url':'https://example.invalid/nav','read_status':'Read','known_at':self.at}
        self.review={'status':'Clear','scale_factor':1,'source_ids':['fixture-actions'],'reason':'Synthetic action review','known_at':self.at}

    def test_units_and_checked_notional_never_create_bias_or_cash_flow(self):
        result=compare_shares(self.previous,self.current,self.at,self.review,self.nav)
        self.assertEqual(result['share_delta_unadjusted'],200000)
        self.assertAlmostEqual(result['share_change_pct_unadjusted'],20)
        self.assertEqual(result['net_creation_notional_estimate'],400000)
        self.assertNotIn('cash_flow',result)
        self.assertIsNone(result['bias']);self.assertFalse(result['trade_permission'])

    def test_missing_action_check_keeps_notional_unknown_even_with_nav(self):
        result=compare_shares(self.previous,self.current,self.at,nav=self.nav)
        self.assertEqual(result['share_delta_unadjusted'],200000)
        self.assertIsNone(result['share_delta_adjusted']);self.assertIsNone(result['net_creation_notional_estimate'])

    def test_split_adjustment_is_not_subscription(self):
        after={**self.current,'value':'200'};review={**self.review,'status':'Adjusted','scale_factor':2}
        result=compare_shares(self.previous,after,self.at,review,self.nav)
        self.assertEqual(result['share_delta_unadjusted'],1000000)
        self.assertEqual(result['share_delta_adjusted'],0)
        self.assertEqual(result['net_creation_notional_estimate'],0)

    def test_pcf_limits_wrong_units_and_nonfinite_values_rejected(self):
        for changes in ({'measure':'CreationRedemptionUnit'},{'measure':'RedemptionLimit'},{'unit':'万元'},{'value':True},{'value':'NaN'},{'value':'Infinity'},{'value':'1e9999'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                compare_shares(self.previous,{**self.current,**changes},self.at)

    def test_other_product_misaligned_nav_and_future_knowledge_rejected(self):
        for changes in ({'fund_code':'510050'},{'known_at':'2026-10-14T10:00:00+08:00'},{'read_status':'Partial'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                compare_shares(self.previous,{**self.current,**changes},self.at)
        with self.assertRaises(ValueError):compare_shares(self.previous,self.current,self.at,self.review,{**self.nav,'nav_date':'2026-10-13'})
        with self.assertRaises(ValueError):compare_shares(self.previous,self.current,self.at,{**self.review,'source_ids':[]})

    def test_zero_baseline_and_negative_share_change(self):
        empty={**self.previous,'value':'0'}
        self.assertIsNone(compare_shares(empty,self.current,self.at)['share_change_pct_unadjusted'])
        redeem={**self.current,'value':'90'}
        self.assertEqual(compare_shares(self.previous,redeem,self.at,self.review,self.nav)['net_creation_notional_estimate'],-200000)
