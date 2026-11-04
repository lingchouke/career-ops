import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_store import library_stats, search, status
from sync_jobs import synchronize


class LibraryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = Path(folder.name)/"jobs.db"
        self.config = Path(folder.name)/"companies.json"
        self.config.write_text(json.dumps([
            {"type":"greenhouse","slug":"a","industry":"制造","name":"甲公司"},
            {"type":"lever","slug":"b","industry":"软件","name":"乙公司"}]),encoding="utf-8")

    def sync(self, request):
        return synchronize(self.config,self.db,request)

    def test_full_snapshot_filter_pagination_and_offline(self):
        def request(url, params):
            if "greenhouse" in url:
                self.assertEqual(params, {"content":"true"})
                return {"jobs":[{"id":1,"title":"Mechanical Engineer","location":{"name":"Shanghai"},
                                 "content":"&lt;p&gt;任职要求&lt;/p&gt;&lt;p&gt;使用夹具&lt;/p&gt;",
                                 "absolute_url":"https://example.com/a"}]}
            self.assertEqual(params["mode"],"json")
            if params["skip"]==2:
                return []
            self.assertEqual(params["skip"],0)
            return [{"id":str(i),"text":"Engineer","categories":{"location":"Berlin","allLocations":["Berlin","上海"]},
                     "descriptionPlain":"开头与正文","lists":[{"text":"条件","content":"<li>必须会 SQL</li>"}],
                     "additionalPlain":"结尾","salaryDescriptionPlain":"薪资说明","hostedUrl":"https://example.com/b"}
                    for i in (1,2)]
        with patch("sync_jobs.PAGE",2):
            self.assertEqual(self.sync(request),({"甲公司":1,"乙公司":2},{}))
        with patch("socket.socket.connect",side_effect=AssertionError("search attempted network access")):
            stats = library_stats(self.db)
            self.assertEqual(stats.companies,{"甲公司":1,"乙公司":2})
            self.assertEqual(stats.cities,{"上海":3,"柏林":2})
            self.assertEqual(len(search("不限","","",self.db)),stats.total)
            for city,count in stats.cities.items():
                self.assertEqual(len(search(city,"","",self.db)),count)
            a, = search("上海市","制造","机械工程师 夹具",self.db)
            self.assertEqual(a["岗位要求"],"任职要求\n使用夹具")
            b = search("上海","软件","sql",self.db)
            self.assertEqual(len(b),2)
            self.assertEqual(b[0]["岗位要求"],"开头与正文\n条件\n必须会 SQL\n结尾\n薪资说明")
            self.assertEqual(search("深圳","制造","",self.db),[])
        def partial(url, params):
            if "greenhouse" in url:
                return {"jobs":[]}
            if params["skip"]:
                raise TimeoutError()
            return [{"id":"new","text":"New","hostedUrl":"https://example.com/new"}]
        with patch("sync_jobs.PAGE",1):
            ok, failed = self.sync(partial)
        self.assertEqual(ok,{"甲公司":0})
        self.assertIn("乙公司",failed)
        self.assertEqual(len(search("","软件","sql",self.db)),2)
        self.assertEqual(status(self.db)[0],2)
        self.assertFalse(search("","软件","New",self.db))
        self.config.write_text("[]",encoding="utf-8")
        self.sync(partial)
        self.assertEqual(status(self.db)[0],0)


if __name__ == "__main__":
    unittest.main()
