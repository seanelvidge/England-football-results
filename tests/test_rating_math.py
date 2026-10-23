"""Regression checks for the rating filter; no downloads or results updates."""
import importlib.util
import inspect
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '.github' / 'workflows' / 'football_results.py'
if not SOURCE.exists():
    SOURCE = ROOT / 'football_results.py'
spec = importlib.util.spec_from_file_location('football_rating_model', SOURCE)
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


class RatingMathTests(unittest.TestCase):
    def test_nis_target_matches_independent_outcome_residuals(self):
        target = inspect.signature(model.ekf_update_one_match).parameters['nis_target'].default
        initial = inspect.signature(model.ekf_update_one_match).parameters['nis_ewma'].default
        for probs in [np.array([.4, .3, .3]), np.array([.95, .03, .02])]:
            cov = np.diag(probs) - np.outer(probs, probs)
            inverse = np.linalg.pinv(cov)
            expected_nis = sum(
                probs[i] * ((outcome - probs) @ inverse @ (outcome - probs))
                for i, outcome in enumerate(np.eye(3))
            )
            self.assertEqual(np.linalg.matrix_rank(cov), 2)
            self.assertAlmostEqual(target, expected_nis)
            self.assertEqual(initial, target)

    def test_controller_does_not_change_dispersion_at_expected_nis(self):
        # Freeze the EWMA at the categorical expectation to isolate the controller.
        out = model.ekf_update_one_match(
            1., .1, 1, 1., .1, 1, 2026, 'H', 1,
            nis_ewma=2., alpha_nis=0., phi0=1.,
        )
        phi_after = out[5] if len(out) == 6 else out[13]
        self.assertAlmostEqual(phi_after, 1.)

    def test_era_baseline_and_probability_normalization(self):
        for year in [1888, 1950, 2026]:
            home, away, draw = model.era_probs_from_year(year)
            np.testing.assert_allclose(
                model.predict_probs(0., 0., year, beta=.9), [home, draw, away]
            )
            for skill in [-6., -1., 0., 1., 6.]:
                probs = model.predict_probs(skill, 0., year, beta=.9)
                self.assertTrue(np.isfinite(probs).all())
                self.assertTrue((probs > 0).all())
                self.assertAlmostEqual(probs.sum(), 1.)

    def test_observation_jacobian_matches_finite_differences(self):
        jacobian = getattr(model, 'jacobian', None) or model.jacobian_H
        for home, away in [(-3., 2.), (0., 0.), (1., 2.), (3., -2.)]:
            delta = 1e-5
            finite_diff = (
                model.predict_probs(home + delta, away, 2026, beta=.9)
                - model.predict_probs(home - delta, away, 2026, beta=.9)
            ) / (2 * delta)
            actual = jacobian(home, away, 2026, beta=.9)
            np.testing.assert_allclose(actual[:, 0], finite_diff, atol=1e-10)
            np.testing.assert_allclose(actual[:, 0], -actual[:, 1])
            np.testing.assert_allclose(actual.sum(axis=0), 0., atol=1e-14)

    def test_decisive_result_moves_winner_up_from_forecast(self):
        for home, away in [(-3., 3.), (0., 0.), (3., -3.)]:
            for vh, va in [(0., 0.), (.01, .3), (.3, .01)]:
                forecast = .997 * np.array([home, away]) + .003 * 1.5
                for result, signs in [('H', [1., -1.]), ('A', [-1., 1.])]:
                    out = model.ekf_update_one_match(home, vh, 1, away, va, 1, 2026, result, 1)
                    contribution = np.array([out[0], out[2]]) - forecast
                    self.assertTrue((contribution * signs >= -1e-10).all())
                    self.assertTrue(np.isfinite(out[:4]).all())
                    self.assertGreater(out[1], 0.)
                    self.assertGreater(out[3], 0.)

    def test_mean_reversion_can_outweigh_a_favourites_win(self):
        out = model.ekf_update_one_match(5., .001, 1, 3., .001, 1, 2026, 'H', 1)
        self.assertLess(out[0], 5.)
        self.assertLess(out[2], 3.)
        self.assertGreater(out[0], .997 * 5. + .003 * 1.5)


if __name__ == '__main__':
    unittest.main()
