import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

from ai_analysis import AnalysisError, analyze


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.cache=Path(folder.name)/"cache.sqlite3"
        self.prompt=Path(folder.name)/"prompt.md"
        self.prompt.write_text("分析规则",encoding="utf-8")
        self.job={"岗位":"工程师","岗位要求":"独立出图"}
        self.report={"summary":"有制图经验。","direction_mismatch":False,
                     "requirements":[],"soft_skills_note":"","unclear":[],"better_fit":[],"top_priorities":[]}

    def run_analysis(self, config, **kwargs):
        return analyze("已独立完成制图",self.job,config,cache=self.cache,prompt_path=self.prompt,**kwargs)

    def test_transport_retry_and_cache(self):
        received=[]
        report=self.report
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                reason="length" if len(received)==1 else "stop"
                choice={"finish_reason":reason,"message":{"content":json.dumps(report)}}
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"choices":[choice]}).encode())
        with ThreadingHTTPServer(("127.0.0.1",0),Handler) as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            try:
                config=(f"http://127.0.0.1:{server.server_port}/v1","test","")
                self.assertEqual(self.run_analysis(config),report)
                self.assertEqual(self.run_analysis(("","","")),report)
                self.assertEqual([r["max_tokens"] for r in received],[8192,16384])
                self.assertTrue(all(r["temperature"]==0 for r in received))
                self.assertEqual(received[0]["messages"][0]["content"],"分析规则")
                self.prompt.write_text("新分析规则",encoding="utf-8")
                self.run_analysis(config)
                self.assertEqual(received[-1]["messages"][0]["content"],"新分析规则")
                self.assertEqual(len(received),3)
            finally:
                server.shutdown()
                thread.join()

    def test_two_truncations_never_cached(self):
        send=Mock(return_value=("length",json.dumps(self.report)))
        with self.assertRaisesRegex(AnalysisError,"^分析被截断，请重试$"):
            self.run_analysis(("","test",""),send=send)
        self.assertEqual(send.call_count,2)
        self.assertIsNone(self.run_analysis(("","","")))
