import unittest

import trial_analysis as ta


class AnalysisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = ta.build(ta.HERE / "records")
        cls.result = ta.summarise(cls.ctx)

    def block(self, week, name):
        return next(b for b in self.result["blocks"]
                    if b["week"] == week and b["block"] == name)

    def test_assignment_is_never_rewritten_by_contacts_or_moves(self):
        # 1A-1 转去 1B，但结果仍按首班 1A 归入处理组；接触不改变区组构成。
        self.assertEqual(self.ctx["room_of"]["1A-1"], "1A")
        self.assertTrue(self.ctx["room_info"]["1A"]["assigned"])
        self.assertFalse(self.ctx["room_info"]["1B"]["assigned"])
        self.assertEqual(self.result["n_blocks"], 12)

    def test_each_block_is_one_treatment_one_control(self):
        for b in self.result["blocks"]:
            self.assertTrue(self.ctx["room_info"][b["treatment"]]["assigned"])
            self.assertFalse(self.ctx["room_info"][b["control"]]["assigned"])

    def test_cancelled_window_without_reopen_is_invalid(self):
        self.assertFalse(self.ctx["windows"]["3H"]["valid"])
        self.assertIsNone(self.ctx["windows"]["3H"]["open"])

    def test_reopened_window_replaces_cancelled_one(self):
        # 2D 首窗 day 28 被取消，day 31 补开；day 35 的观测应算有效。
        self.assertTrue(self.ctx["windows"]["2D"]["valid"])
        self.assertEqual(self.ctx["windows"]["2D"]["open"], 34)
        self.assertEqual(self.ctx["windows"]["2D"]["close"], 40)
        self.assertIn("2D-7", self.ctx["scores"])
        self.assertEqual(self.ctx["scores"]["2D-7"], 9)

    def test_no_observation_outside_effective_windows(self):
        self.assertEqual(self.result["excluded_observations"], [])

    def test_block_with_no_valid_window_is_bounded_not_dropped(self):
        b = self.block(3, "b4")
        self.assertEqual((b["treatment"], b["control"]), ("3G", "3H"))
        self.assertEqual(b["obs_c"], 0)
        self.assertIsNone(b["diff"])          # 不进点估计
        lo, hi = b["bounds_0_10"]             # 但不从边界中消失
        self.assertLess(lo, 0)
        self.assertGreater(hi, 0)

    def test_partial_missing_counts_are_in_bounds(self):
        b = self.block(2, "b3")               # 两侧各缺 1 人
        self.assertEqual((b["obs_t"], b["obs_c"]), (7, 7))
        lo, hi = b["bounds_0_10"]
        self.assertNotAlmostEqual(lo, hi)

    def test_primary_estimate_uses_block_not_student_weights(self):
        itt = self.result["itt_complete_case"]
        self.assertEqual(itt["n"], 11)        # 12 个区组减去无窗口的 3H
        diffs = [b["diff"] for b in self.result["blocks"] if b["diff"] is not None]
        self.assertAlmostEqual(itt["mean"], sum(diffs) / len(diffs))
        # 随机单位是区组：标准误按 11 个区组差值算，而不是按 170 名学生算。
        expected_se = ta.stdev(diffs) / 11 ** 0.5
        self.assertAlmostEqual(itt["se"], expected_se)
        self.assertEqual(self.result["student_naive"]["n_t"]
                         + self.result["student_naive"]["n_c"], 170)
        self.assertNotAlmostEqual(itt["se"],
                                  self.result["student_naive"]["se_welch"])

    def test_unknown_outcome_is_not_imputed_as_zero(self):
        # 若把 3H 当 0 分，总体会大幅抬高；主估计不应接近该值。
        diffs = [b["diff"] for b in self.result["blocks"] if b["diff"] is not None]
        zero_imputed = (sum(diffs) + 7.0 - 0.0) / 12
        self.assertNotAlmostEqual(self.result["itt_complete_case"]["mean"],
                                  zero_imputed, places=1)
        lo, hi = self.result["bounds"]["bounds_0_10"]
        self.assertLess(lo, self.result["itt_complete_case"]["mean"])
        self.assertGreater(hi, self.result["itt_complete_case"]["mean"])

    def test_contact_audit_flags_cross_arm_links(self):
        contacts = {(e["kind"], tuple(e["rooms"])): e
                    for e in self.result["audit"]["contacts"]}
        self.assertTrue(contacts[("同教师", ("1A", "1B"))]["cross_arm"])
        self.assertTrue(contacts[("联合讨论", ("1C", "1F"))]["cross_arm"])
        self.assertFalse(contacts[("联合讨论", ("2B", "2D"))]["cross_arm"])
        self.assertTrue(contacts[("临时合班", ("3A", "3H"))]["cross_arm"])
        moves = {m["student"]: m for m in self.result["audit"]["moves"]}
        self.assertTrue(moves["1A-1"]["cross_arm"])
        self.assertFalse(moves["2B-2"]["cross_arm"])

    def test_contact_subsets_are_described_not_redefined_as_random(self):
        ledger = {e["question"]: e for e in self.result["ledger"]}
        statuses = {e["question"]: e["status"] for e in self.result["ledger"]}
        descriptive = [q for q, s in statuses.items() if s == "仅描述"]
        self.assertTrue(any("接触" in q for q in descriptive))
        self.assertTrue(any("先独立" in q for q in descriptive))
        primary = [s for s in statuses.values() if s.startswith("有设计依据")]
        self.assertEqual(len(primary), 2)

    def test_delivery_is_not_used_to_form_trial_groups(self):
        # 每臂各 12 人实际顺序与分派相反、各 24 人无回执；若按交付分组
        # 点数会变。主估计仍以分派为准。
        row = self.result["compliance"]["assigned"]
        self.assertEqual(row["enrolled"]["independent_first"], 60)
        self.assertEqual(row["enrolled"]["other_order"], 12)
        self.assertEqual(row["enrolled"]["no_receipt"], 24)
        itt = self.result["itt_complete_case"]["mean"]
        self.assertAlmostEqual(itt, 0.034, places=2)

    def test_proposal_grades_reflect_identifiability(self):
        grades = {p["proposal"]: p for p in self.result["proposals"]}
        self.assertEqual(grades["分开"]["grade"], "A")
        self.assertEqual(grades["只共享教师"]["grade"], "C")
        self.assertEqual(grades["混排"]["grade"], "C")
        self.assertEqual(grades["分开"]["shared_teacher_blocks"], [])
        self.assertEqual(grades["分开"]["blocks"], 4)
        for name in ("只共享教师", "混排"):
            self.assertTrue(grades[name]["shared_teacher_blocks"])
        self.assertTrue(grades["混排"]["discussion_blocks"])

    def test_proposal_audit_detects_cross_block_teacher(self):
        rows = [
            {"proposal": "x", "room": "5A", "block": "b1", "teacher": "t0",
             "partner": None, "eligible": 6},
            {"proposal": "x", "room": "5B", "block": "b1", "teacher": "t1",
             "partner": None, "eligible": 6},
            {"proposal": "x", "room": "5C", "block": "b2", "teacher": "t0",
             "partner": None, "eligible": 6},
            {"proposal": "x", "room": "5D", "block": "b2", "teacher": "t1",
             "partner": None, "eligible": 6},
        ]
        audit = ta.audit_proposals(self.ctx, rows)[0]
        self.assertEqual(audit["grade"], "C")
        self.assertIn("t0", audit["cross_block_teacher"])

    def test_proposal_audit_keeps_clean_block_randomisation(self):
        rows = [
            {"proposal": "y", "room": "5A", "block": "b1", "teacher": "t0",
             "partner": None, "eligible": 6},
            {"proposal": "y", "room": "5B", "block": "b1", "teacher": "t1",
             "partner": None, "eligible": 6},
        ]
        audit = ta.audit_proposals(self.ctx, rows)[0]
        self.assertEqual(audit["grade"], "A")

    def test_required_blocks_grows_as_effect_shrinks(self):
        req = self.result["required_blocks"]
        self.assertLess(req["1.0"]["sd_0.644"], req["0.5"]["sd_0.644"])
        self.assertLess(req["0.5"]["sd_0.644"], req["0.4"]["sd_0.644"])


if __name__ == "__main__":
    unittest.main()
