"""Independent numerical checks of the categorical rating filter."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '.github' / 'workflows' / 'football_results.py'
spec = importlib.util.spec_from_file_location('football_rating_model', SOURCE)
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


class RatingMathTests(unittest.TestCase):
    def test_categorical_covariance_has_two_residual_dimensions(self):
        for p in [np.array([.4, .3, .3]), np.array([.95, .03, .02])]:
            c = np.diag(p)-np.outer(p, p)
            self.assertEqual(np.linalg.matrix_rank(c), 2)
            expected = sum(p[i]*((y-p) @ np.linalg.pinv(c) @ (y-p)) for i,y in enumerate(np.eye(3)))
            self.assertAlmostEqual(expected, 2.)

    def test_scalar_update_matches_independent_two_residual_matrix_ekf(self):
        rng = np.random.default_rng(123)
        for _ in range(100):
            sh, sa = rng.normal(size=2)
            vh, va = rng.uniform(.001, .5, 2)
            hb, lk = rng.uniform(.1, .6), rng.uniform(-1., 0.)
            p = model.predict_probs(sh, sa, hb, lk)
            c = np.diag(p)-np.outer(p,p)
            a = np.array([1.,0.,-1.])
            gradient = model.BETA*c@a
            h = np.column_stack([gradient, -gradient])[:2]
            prior = np.diag([vh,va])
            r = c[:2,:2]
            gain = prior@h.T@np.linalg.inv(h@prior@h.T+r)
            identity = np.eye(2)
            posterior = (identity-gain@h)@prior@(identity-gain@h).T+gain@r@gain.T
            for index, result in enumerate('HDA'):
                state = np.array([sh,sa])+gain@(np.eye(3)[index]-p)[:2]
                actual = model.categorical_update(sh,vh,sa,va,result,hb,lk)
                np.testing.assert_allclose([actual[0],actual[2]],state,atol=1e-12)
                np.testing.assert_allclose([actual[1],actual[3]],np.diag(posterior),atol=1e-12)

    def test_score_and_information_match_log_likelihood_derivatives(self):
        for sh in [-3.,0.,2.]:
            for index in range(3):
                eps=1e-4
                logp=lambda x: np.log(model.predict_probs(x,.4,.3,-.4)[index])
                p=model.predict_probs(sh,.4,.3,-.4)
                score=model.BETA*(1-index-(p[0]-p[2]))
                info=model.BETA**2*(p[0]+p[2]-(p[0]-p[2])**2)
                self.assertAlmostEqual((logp(sh+eps)-logp(sh-eps))/(2*eps),score,places=7)
                self.assertAlmostEqual(-(logp(sh+eps)-2*logp(sh)+logp(sh-eps))/eps**2,info,places=6)

    def test_probabilities_are_stable_and_normalized(self):
        for sh in [-1000., -5., 0., 5., 1000.]:
            p=model.predict_probs(sh,0.,.3,-.4)
            self.assertTrue(np.isfinite(p).all())
            self.assertTrue((p>=0).all())
            self.assertAlmostEqual(p.sum(),1.)
        p=model.predict_probs(1.,1.,.3,-.4)
        self.assertGreater(p[0],p[2])

    def test_ou_has_calendar_semigroup_and_uncertainty_after_absence(self):
        full=model.forecast_team(2.,.02,1,1,28)
        half=model.forecast_team(2.,.02,1,1,14)
        np.testing.assert_allclose(model.forecast_team(*half,1,1,14),full,atol=1e-14)
        self.assertEqual(model.forecast_team(2.,.02,1,1,0),(2.,.02))
        long=model.forecast_team(2.,.02,1,1,365)
        self.assertGreater(long[1],full[1])
        self.assertLess(long[0],full[0])
        with self.assertRaises(ValueError): model.forecast_team(2.,.02,1,1,-1)

    def test_new_clubs_have_uncertainty_and_result_moves_winner_up(self):
        self.assertGreater(model.Team('New').var[0],0)
        for sh,sa in [(-3.,3.),(0.,0.),(3.,-3.)]:
            for result, sign in [('H',1),('A',-1)]:
                out=model.categorical_update(sh,.1,sa,.2,result,.3,-.4)
                self.assertGreaterEqual(sign*(out[0]-sh),0)
                self.assertLessEqual(sign*(out[2]-sa),0)
                self.assertGreater(out[1],0)
                self.assertLess(out[1],.1)
                self.assertGreater(out[3],0)
                self.assertLess(out[3],.2)

    def test_same_day_results_do_not_change_other_matches_baseline(self):
        import pandas as pd
        rows=pd.DataFrame([
            dict(Date='2020-01-01',HomeTeam='A',AwayTeam='B',Tier=1,Result='H',hGoal=4,aGoal=0),
            dict(Date='2020-01-01',HomeTeam='C',AwayTeam='D',Tier=1,Result='A',hGoal=0,aGoal=1),
        ])
        first=model.process_match_rows(rows.itertuples(index=False),[],model.initial_baselines())
        rows.loc[0,'Result']='A'
        rows.loc[0,['hGoal','aGoal']]=[0,1]
        second=model.process_match_rows(rows.itertuples(index=False),[],model.initial_baselines())
        self.assertEqual(first[1]['HomeWinProbability'],second[1]['HomeWinProbability'])

    def test_margin_likelihood_is_normalized_and_derivatives_are_correct(self):
        for delta in [-1.7, .2, 2.3]:
            for result,z in [('H',1),('A',-1)]:
                eta=-.2+model.MARGIN_SLOPE*z*delta
                k=np.arange(1000)
                probs=np.exp(k*eta-(k+1)*np.logaddexp(0,eta))
                self.assertAlmostEqual(probs.sum(),1.,places=12)
                expected_score=0.
                for excess in [0,1,3,8]:
                    margin=z*(excess+1)
                    score,info,intercept=model.margin_terms(delta,result,margin,-.2)
                    logp=lambda d: excess*(-.2+model.MARGIN_SLOPE*z*d)-(excess+1)*np.logaddexp(0,-.2+model.MARGIN_SLOPE*z*d)
                    eps=1e-4
                    self.assertAlmostEqual((logp(delta+eps)-logp(delta-eps))/(2*eps),score,places=7)
                    self.assertAlmostEqual(-(logp(delta+eps)-2*logp(delta)+logp(delta-eps))/eps**2,info,places=5)
                scores=np.array([model.margin_terms(delta,result,z*(int(e)+1),-.2)[0] for e in k])
                self.assertAlmostEqual(float(probs@scores),0.,places=12)

    def test_scoreline_updates_use_margin_but_never_leak_it_into_prediction(self):
        small=model.scoreline_update(0.,.1,0.,.1,1,0,.3,-.4,-.2)
        large=model.scoreline_update(0.,.1,0.,.1,4,0,.3,-.4,-.2)
        same_margin=model.scoreline_update(0.,.1,0.,.1,2,1,.3,-.4,-.2)
        self.assertGreater(large[0],small[0])
        np.testing.assert_array_equal(small[4],large[4])
        np.testing.assert_allclose(small[:4],same_margin[:4],atol=0)
        draw=model.scoreline_update(.3,.1,-.1,.2,2,2,.3,-.4,-.2)
        categorical=model.categorical_update(.3,.1,-.1,.2,'D',.3,-.4)
        np.testing.assert_allclose(draw[:4],categorical[:4],atol=0)

    def test_scoreline_posterior_matches_joint_likelihood_curvature(self):
        sh,sa,vh,va=.2,-.3,.1,.2
        for hg,ag in [(1,0),(4,0),(0,3),(2,2)]:
            result='H' if hg>ag else 'A' if hg<ag else 'D'
            delta=model.BETA*(sh-sa)+.3
            p=model.predict_probs(sh,sa,.3,-.4)
            margin_score,margin_info,_=model.margin_terms(delta,result,hg-ag,-.2)
            z={'H':1,'D':0,'A':-1}[result]
            m=p[0]-p[2]
            direction=np.array([model.BETA,-model.BETA])
            score=direction*(z-m+margin_score)
            precision=np.diag([1/vh,1/va])+(p[0]+p[2]-m*m+margin_info)*np.outer(direction,direction)
            covariance=np.linalg.inv(precision)
            expected=np.array([sh,sa])+covariance@score
            actual=model.scoreline_update(sh,vh,sa,va,hg,ag,.3,-.4,-.2)
            np.testing.assert_allclose([actual[0],actual[2]],expected,atol=1e-14)
            np.testing.assert_allclose([actual[1],actual[3]],np.diag(covariance),atol=1e-14)


if __name__=='__main__': unittest.main()
