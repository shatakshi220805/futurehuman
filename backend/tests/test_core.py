import os, sys, tempfile, time, unittest
os.environ["FH_DB"] = tempfile.mktemp(suffix=".db"); sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import core

class T(unittest.TestCase):
    @classmethod
    def setUpClass(c): c.u = core.register("a@b.co", "password1"); c.v = core.register("x@y.co", "password2")
    def test_auth(self):
        self.assertEqual(core.login("a@b.co", "password1"), self.u); self.assertEqual(core.check_token(core.make_token(self.u)), self.u)
        with self.assertRaises(ValueError): core.login("a@b.co", "wrongpass1")
        self.assertIsNone(core.check_token("bad.token"))
    def test_extract_and_ask(self):
        core.add_memory(self.u, "Email from Ravi Mehta: please send the updated deck by Friday", "Gmail", project="Fundraising", ts=time.time() - 3 * 86400)
        core.add_memory(self.u, "Fundraising strategy doc: drafted revenue projections, not yet sent", "Google Docs", project="Fundraising")
        r = core.ask(self.u, "What did the investor Ravi ask me to send, and progress since?")
        self.assertIn("deck", r["answer"]); self.assertIn("unverified", r["progress"]["verdict"]); self.assertEqual(core.ask(self.v, "deck")["sources"], [])
    def test_commitments(self):
        a = core.analyse("Ravi: Can you send it?\nI'll send the proposal by Friday.\nMohit will share the prototype next week.\nLet's revisit pricing later.", "Sam")
        self.assertEqual(len(a["commitments"]), 2); self.assertEqual(a["commitments"][0]["who"], "Sam"); self.assertTrue(a["commitments"][1]["due"]); self.assertEqual(len(a["tentative"]), 1); self.assertEqual(len(a["questions"]), 1)
    def test_meeting_flow(self):
        mid = core.start_meeting(self.u, "Sync", "Roadmap"); r = core.meeting_chunk(self.u, mid, "Mohit", "I'll share the prototype tomorrow.")
        self.assertEqual(r["saved"][0]["kind"], "commitment"); s = core.finish_meeting(self.u, mid); self.assertEqual(s["speakers"], ["Mohit"])
    def test_alerts_and_corrections(self):
        m = core.add_memory(self.u, "Ravi asked for the contract by tomorrow", "Gmail", project="Deal", people=["Ravi"], due=time.time() + 3600 * 6)
        c = [x for x in core.candidates(self.u, "Deal", 0) if x["memory"]["id"] == m["id"]][0]; self.assertTrue(c["notify"])
        core.dismiss(self.u, m["id"]); self.assertFalse([x for x in core.candidates(self.u, "Deal", 0) if x["memory"]["id"] == m["id"]][0]["notify"])
        self.assertEqual(core.update(self.u, m["id"], status="outdated")["status"], "outdated"); self.assertTrue(core.delete(self.u, m["id"])); self.assertIsNone(core.get(self.u, m["id"]))
    def test_dedupe_and_brief(self):
        a = core.add_memory(self.u, "Same screen text", "Chrome"); b = core.add_memory(self.u, "Same screen text", "Chrome"); self.assertEqual(a["id"], b["id"])
        core.add_memory(self.u, "Ravi asked about pricing", "Slack"); self.assertEqual(core.brief(self.u, "Ravi")["person"], "Ravi"); self.assertIn("Hi Ravi", core.draft_email(self.u, "Ravi")["body"])
    def test_vector_hybrid_and_rate_and_learning(self):
        m = core.add_memory(self.v, "Invoice due next month for Acme", "Gmail"); r = core.search(self.v, "invoicing")
        self.assertTrue(r and r[0]["id"] == m["id"] and r[0]["via"] in ("vector", "hybrid"))
        rl = core.RateLimiter(3, 60); self.assertEqual([rl.allow("x") for _ in range(4)], [True, True, True, False])
        base = core.add_memory(self.v, "Send Kim the audit by tomorrow", "Gmail", project="P", people=["Kim"], due=time.time() + 3600 * 12)
        s0 = core.candidates(self.v, "P", 0)[0]["score"]
        for i in range(6): x = core.add_memory(self.v, f"Noise task {i} due tomorrow", "Gmail", project="P", due=time.time() + 86400); core.dismiss(self.v, x["id"])
        s1 = [c for c in core.candidates(self.v, "P", 0) if c["memory"]["id"] == base["id"]][0]["score"]; self.assertLess(s1, s0)
        mb = core.morning_brief(self.v); self.assertTrue(mb["sections"] and mb["sections"][0]["project"] == "P")
if __name__ == "__main__": unittest.main()
