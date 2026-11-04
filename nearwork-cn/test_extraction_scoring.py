from pathlib import Path
import tempfile, unittest
from unittest.mock import patch
from contextlib import closing
from job_store import connect,save,search
from extraction import rules,enrich
from scoring import score

class FieldAndScoreTests(unittest.TestCase):
    def test_scoring_caps_evidence_and_half_up(self):
        def item(name,kind="must",status="met",gate=False,proof="原文"):
            return dict(requirement=name,importance=kind,status=status,hard_gate=gate,evidence=proof)
        rows=[item(str(i)) for i in range(5)]
        rows.append(item("可选","nice","partial"))
        report=dict(requirements=rows,direction_mismatch=False)
        self.assertEqual(score(report,"原文")[0],97)
        rows[0]=item("学历",gate=True,proof="编造")
        self.assertEqual(score(report,"原文")[0],55)
        rows[0]=item("年限",status="partial",gate=True)
        self.assertEqual(score(report,"原文")[0],75)
        report["direction_mismatch"]=True
        self.assertEqual(score(report,"原文")[0],20)
        report=dict(requirements=[item("主项"),item("次项","nice","partial")],direction_mismatch=False)
        self.assertEqual(score(report,"原文")[0],88)

    def test_progress_and_filter(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"jobs.db"
            src=dict(type="lever",slug="demo",name="示例",industry="机械",domestic="民企")
            rows=[("1","设计","上海","本科。3年工作经验。月薪15k-20k","https://example.com/1")]
            with closing(connect(path)) as db:
                save(db,src,rows,"today")
                def send(config,messages,limit):
                    return "stop",json.dumps({"rows":[{"id":0,"fields":{"languages":None}}]})
                with patch("extraction.time.sleep"):
                    enrich(db,("","mock",""),send)
                save(db,src,rows,"later")
                self.assertEqual(db.execute("SELECT pending FROM extracted").fetchone()[0],0)
                j,=search("上海","","",path,filters={"years":3,"degree":"本科","only":["languages"],"low":18000})
                self.assertEqual(j["salary"]["cny_min"],15000)
                self.assertFalse(search("上海","","",path,filters={"unknown":False}))
                self.assertFalse(search("上海","","",path,filters={"years":2}))
            from contextlib import redirect_stdout
            from io import StringIO
            from sync_jobs import audit
            out=StringIO()
            with redirect_stdout(out):
                audit(path)
            self.assertIn("设计 示例",out.getvalue())
            self.assertIn("月薪15k-20k",out.getvalue())
