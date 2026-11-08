import copy, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build

PLAN = build.load_plan(Path(__file__).resolve().parent.parent / "plans/2026-12_rebuild.yaml")

def errs(mut):
    p = copy.deepcopy(PLAN); mut(p); return build.validate(p)[0]

def test_baseline_plan_is_clean():
    assert errs(lambda p: None) == []

def test_over_cap_blocks():
    assert any("exceeds" in e for e in errs(lambda p: p["meta"]["campaigns"][0].update(monthly_budget=60000)))

def test_shared_budget_blocks():
    assert any("shared budgets" in e for e in errs(lambda p: p["google"]["campaigns"][0].update(shared_budget="Main")))

def test_long_headline_blocks():
    def m(p): p["google"]["campaigns"][0]["ad_groups"][0]["rsa"]["headlines"][0] = "x" * 31
    assert any("over 30" in e for e in errs(m))

def test_test_lane_needs_one_concept_per_adset():
    def m(p):
        a = p["meta"]["campaigns"][1]["adsets"][0]; a["ads"].append(dict(a["ads"][0], name="extra"))
    assert any("exactly 1 concept" in e for e in errs(m))

def test_forecast_outside_target_blocks():
    def m(p):
        for c in p["meta"]["campaigns"]: c["assumed_cpa"] = 400
    assert any("outside" in e for e in errs(m))

def test_unverified_uk_gate_builds_paused(tmp_path):
    p = copy.deepcopy(PLAN)
    rows = build.google_rows(p)
    uk = [r for r in rows if r["Campaign"].startswith("GOOG_Search_NonBrand_UK") and r["Campaign Daily Budget"]]
    assert uk[0]["Campaign Status"] == "Paused"
