import unittest
from assessment import assess


def compare(resume, title, needs):
    return assess(resume, {"岗位": title, "岗位要求": needs})


class ScreeningTests(unittest.TestCase):
    def test_unrelated_job_despite_teamwork_and_english(self):
        result = compare("机械设计工程师。大学英语四级。负责跨部门沟通。",
                         "Product Lead - China", "Requirements\n产品管理经验\n跨部门沟通")
        self.assertTrue(result["mismatch"])
        self.assertEqual((result["grade"], result["facts"]), ("低", []))

    def test_tool_alone_does_not_prove_years_or_optional_credential(self):
        proof = "使用 SolidWorks 完成夹具设计"
        result = compare(proof, "机械工程师", "岗位要求：至少三年 SolidWorks 设计经验。加分项：电工证。")
        self.assertTrue(any(quote == proof for _, quote in result["facts"]))
        self.assertIn("至少三年 SolidWorks 设计经验", result["missing"]["必须"])
        self.assertIn("电工证", result["missing"]["加分"])
        self.assertNotEqual(result["grade"], "高")

    def test_literal_requirement_has_verbatim_proof(self):
        proof = "独立完成机械夹具设计"
        result = compare(proof, "机械工程师", "岗位要求：" + proof)
        self.assertEqual(result["grade"], "高")
        self.assertIn((proof, proof), result["facts"])


if __name__ == "__main__":
    unittest.main()
