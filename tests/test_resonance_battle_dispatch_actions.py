from __future__ import annotations

import unittest

from plans.resonance.src.actions.battle_dispatch_actions import (
    BattleDispatchError,
    resonance_group_consecutive_jobs_by_route,
    resonance_group_gp_jobs,
    resonance_validate_battle_jobs,
)


class TestResonanceBattleDispatchActions(unittest.TestCase):
    def test_tie_an_expel_missing_stage_fails(self):
        jobs = [
            {
                "route_id": "ct.tie_an.shoggolith_city.expel",
                "difficulty": 3,
            }
        ]

        with self.assertRaises(BattleDispatchError) as cm:
            resonance_validate_battle_jobs(jobs)

        self.assertEqual(cm.exception.code, "invalid_tie_an_expel")

    def test_regional_missing_threat_level_fails(self):
        jobs = [
            {
                "route_id": "ct.regional_ops_center.wilderness_station",
                "difficulty": 2,
            }
        ]

        with self.assertRaises(BattleDispatchError) as cm:
            resonance_validate_battle_jobs(jobs)

        self.assertEqual(cm.exception.code, "invalid_regional_ops")

    def test_gp_action_summary_missing_difficulty_fails(self):
        jobs = [
            {
                "route_id": "gp.action_summary.blade_encirclement.special_order",
            }
        ]

        with self.assertRaises(BattleDispatchError) as cm:
            resonance_validate_battle_jobs(jobs)

        self.assertEqual(cm.exception.code, "invalid_gp_action_summary")

    def test_tie_an_bounty_rejects_difficulty(self):
        jobs = [
            {
                "route_id": "ct.tie_an.shoggolith_city.bounty",
                "difficulty": 2,
            }
        ]

        with self.assertRaises(BattleDispatchError) as cm:
            resonance_validate_battle_jobs(jobs)

        self.assertEqual(cm.exception.code, "invalid_job_field")

    def test_gp_structural_rejects_difficulty(self):
        jobs = [
            {
                "route_id": "gp.structural_exploration.echo_buoy",
                "difficulty": 2,
            }
        ]

        with self.assertRaises(BattleDispatchError) as cm:
            resonance_validate_battle_jobs(jobs)

        self.assertEqual(cm.exception.code, "invalid_job_field")

    def test_difficulty_out_of_range_fails(self):
        jobs = [
            {
                "route_id": "gp.structural_exploration.echo_buoy",
                "difficulty": 7,
            }
        ]

        with self.assertRaises(BattleDispatchError) as cm:
            resonance_validate_battle_jobs(jobs)

        self.assertEqual(cm.exception.code, "invalid_difficulty")

    def test_unknown_route_id_fails(self):
        jobs = [
            {
                "route_id": "ct.tie_an.unknown_city.expel",
                "difficulty": 1,
                "stage": 1,
            }
        ]

        with self.assertRaises(BattleDispatchError) as cm:
            resonance_validate_battle_jobs(jobs)

        self.assertEqual(cm.exception.code, "unknown_route_id")

    def test_valid_mixed_jobs_are_normalized(self):
        jobs = [
            {
                "route_id": "ct.tie_an.shoggolith_city.expel",
                "difficulty": 4,
                "stage": 2,
            },
            {
                "route_id": "ct.tie_an.shoggolith_city.bounty",
            },
            {
                "route_id": "ct.regional_ops_center.wilderness_station",
                "difficulty": 5,
                "threat_level": 11,
            },
            {
                "route_id": "gp.action_summary.global_supply.savior",
                "difficulty": 2,
            },
        ]

        out = resonance_validate_battle_jobs(jobs)
        self.assertTrue(out["ok"])
        self.assertEqual(out["job_count"], 4)

        n0 = out["normalized_jobs"][0]
        self.assertEqual(n0["ct_subcategory"], "tie_an")
        self.assertEqual(n0["mission_type"], "expel")
        self.assertEqual(n0["stage"], 2)
        self.assertEqual(n0["difficulty"], 4)

        n1 = out["normalized_jobs"][1]
        self.assertEqual(n1["mission_type"], "bounty")
        self.assertIsNone(n1["stage"])
        self.assertIsNone(n1["threat_level"])

        n2 = out["normalized_jobs"][2]
        self.assertEqual(n2["ct_subcategory"], "regional_ops_center")
        self.assertEqual(n2["threat_level"], 11)
        self.assertEqual(n2["difficulty"], 5)

        n3 = out["normalized_jobs"][3]
        self.assertEqual(n3["main_category"], "gp")
        self.assertEqual(n3["gp_subcategory"], "action_summary")
        self.assertEqual(n3["gp_group_key"], "global_supply")
        self.assertEqual(n3["gp_stage_name"], "特供·救世")

    def test_run_count_field_is_rejected(self):
        jobs = [
            {
                "route_id": "ct.tie_an.shoggolith_city.expel",
                "difficulty": 2,
                "stage": 1,
                "run_count": 2,
            }
        ]

        with self.assertRaises(BattleDispatchError) as cm:
            resonance_validate_battle_jobs(jobs)

        self.assertEqual(cm.exception.code, "invalid_job_field")

    def test_group_gp_jobs_preserves_first_seen_order(self):
        jobs = [
            {"route_id": "gp.structural_exploration.echo_buoy"},
            {"route_id": "gp.action_summary.global_supply.savior"},
            {"route_id": "gp.structural_exploration.birch_buoy"},
        ]

        out = resonance_group_gp_jobs(jobs)
        self.assertEqual(out["category_order"], ["structural_exploration", "action_summary"])
        self.assertEqual(len(out["structural_exploration_jobs"]), 2)
        self.assertEqual(len(out["action_summary_jobs"]), 1)

    def test_group_consecutive_jobs_by_route(self):
        jobs = [
            {"route_id": "gp.action_summary.global_supply.savior", "difficulty": 1},
            {"route_id": "gp.action_summary.global_supply.savior", "difficulty": 2},
            {"route_id": "gp.action_summary.global_supply.standard", "difficulty": 1},
        ]

        out = resonance_group_consecutive_jobs_by_route(jobs)
        self.assertEqual(out["group_count"], 2)
        self.assertEqual(out["groups"][0]["route_id"], "gp.action_summary.global_supply.savior")
        self.assertEqual(out["groups"][0]["job_count"], 2)
        self.assertEqual(out["groups"][1]["route_id"], "gp.action_summary.global_supply.standard")


if __name__ == "__main__":
    unittest.main()
