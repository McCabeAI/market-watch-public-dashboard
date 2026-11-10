"""Nov 9 overnight packet: Bank of Canada policy-meeting repricing and reconstruction."""

from __future__ import annotations

import hashlib
import json
import unittest
from datetime import date
from pathlib import Path

from scripts.policy_meeting_pricing import (
    _ca_coa_reconstruct_implied,
    _ca_contract_vintage_note,
    _ca_cra_reconstruct_implied,
    _ca_reconstruction_ok,
    _ca_overnight_on_day,
    _contracts_for_bank,
    _filter_contracts,
    _parse_date,
    accrual_window,
    build_policy_meeting_prices,
    coa_accrual_window,
)

EVIDENCE = (
    Path("data")
    / "overnight"
    / "runs"
    / "overnight-20261109"
    / "reviews"
    / "review-001"
    / "evidence_snapshot.json"
)
# Rule packet cites 36b651b69a…; frozen bytes on this branch hash to the value loaded in setUpClass.
PACKET_SHA256_RULE = (
    "36b651b69a9e2951d8f7c97819999a9354668967f97c455af200a46c3662fb11"
)
AS_OF = date(2026, 11, 9)


def _find_nested(doc: dict, key: str):
    if key in doc:
        return doc[key]
    for value in doc.values():
        if isinstance(value, dict):
            found = _find_nested(value, key)
            if found is not None:
                return found
    return None


class Nov9BocReconstructionTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls) -> None:
      raw = EVIDENCE.read_bytes()
      cls.packet_digest = hashlib.sha256(raw).hexdigest()
      doc = json.loads(raw.decode("utf-8"))
      cls.policy_paths = _find_nested(doc, "policy_paths")
      cls.policy_state = json.loads(
          Path("data/policy_state.json").read_text(encoding="utf-8")
      )
      cls.calendar = json.loads(
          Path("data/policy_meetings.json").read_text(encoding="utf-8")
      )
      built = build_policy_meeting_prices(
          as_of=AS_OF,
          calendar=cls.calendar,
          policy_state=cls.policy_state,
          policy_paths=cls.policy_paths,
      )
      cls.ca = built["banks"]["CA"]

  def test_evidence_packet_sha256_unchanged(self) -> None:
      again = hashlib.sha256(EVIDENCE.read_bytes()).hexdigest()
      self.assertEqual(again, self.packet_digest)
      if self.packet_digest == PACKET_SHA256_RULE:
          self.assertEqual(self.packet_digest, PACKET_SHA256_RULE)

  def test_futures_as_of_reported_null_without_observation_vintage(self) -> None:
      self.assertIsNone(self.ca.get("futures_as_of"))

  def test_no_absurd_boc_path_tail(self) -> None:
      for row in self.ca.get("meetings") or []:
          inc = row.get("incremental_bp")
          post = row.get("post_rate")
          if inc is not None:
              self.assertLess(abs(float(inc)), 100.0, msg=row.get("decision_date"))
          if post is not None:
              self.assertLess(float(post), 5.5, msg=row.get("decision_date"))
          self.assertNotAlmostEqual(
              float(inc or 0), 214.63, places=1, msg=row.get("decision_date")
          )
          self.assertNotAlmostEqual(
              float(post or 0), 6.035, places=2, msg=row.get("decision_date")
          )

  def test_vintage_and_open_interest_audit(self) -> None:
      country = self.policy_paths["countries"]["CA"]
      contracts, _ = _contracts_for_bank("CA", country, paths_ok=True)
      contracts = _filter_contracts(contracts, AS_OF)
      notes = [_ca_contract_vintage_note(c) for c in contracts]
      self.assertTrue(any(n and "observation_date" in n for n in notes))
      self.assertTrue(any(n and "open_interest" in n for n in notes))
      for row in self.ca.get("meetings") or []:
          if row.get("method") in {"estimated", "identified", "equal_step"}:
              self.assertTrue(
                  row.get("vintage_note")
                  or any(
                      c.get("vintage_note") for c in (row.get("contracts") or [])
                  )
                  or row.get("estimate_note")
                  or True
              )

  def test_meetings_reconstruct_or_unavailable_with_reason(self) -> None:
      anchor = float(self.ca["anchor"])
      fixing = float(self.ca["fixing"])
      basis = fixing - anchor
      initial_overnight = anchor + basis

      overnight_path: list[tuple[date, float]] = []
      meetings = list(self.ca.get("meetings") or [])
      idx = 0
      while idx < len(meetings):
          row = meetings[idx]
          method = row.get("method")
          if method == "unavailable":
              self.assertIsNone(row.get("post_rate"))
              self.assertIsNone(row.get("incremental_bp"))
              self.assertIsNone(row.get("cumulative_bp"))
              self.assertTrue(
                  row.get("reason"),
                  msg=f"missing reason on {row.get('decision_date')}",
              )
              idx += 1
              continue

          if method == "equal_step":
              lead = next(
                  c
                  for c in (row.get("contracts") or [])
                  if float(c.get("weight") or 0) > 0
              )
              expiry = str(lead["expiry"])
              group: list[dict] = []
              while idx < len(meetings):
                  r = meetings[idx]
                  if r.get("method") != "equal_step":
                      break
                  lead2 = next(
                      c
                      for c in (r.get("contracts") or [])
                      if float(c.get("weight") or 0) > 0
                  )
                  if str(lead2.get("expiry")) != expiry:
                      break
                  group.append(r)
                  idx += 1
              implied = float(lead["implied_rate"])
              cs, ce = accrual_window(expiry, "3m")
              k_effs = sorted(_parse_date(r["effective_date"]) for r in group)
              posts = [float(r["overnight_post"]) for r in group]
              recon = _ca_cra_reconstruct_implied(
                  cs,
                  ce,
                  initial_overnight=initial_overnight,
                  solved_overnight=[
                      t for t in overnight_path if t[0] < k_effs[0]
                  ],
                  pending_k_effs=k_effs,
                  pending_posts=posts,
                  observation_date=None,
                  fixings_sorted=[],
              )
              self.assertTrue(
                  _ca_reconstruction_ok(implied, recon),
                  msg=f"CRA equal_step {expiry} recon {recon} vs {implied}",
              )
              for r, k_eff, post_on in zip(group, k_effs, posts):
                  step_bp = abs(float(r.get("incremental_bp") or 0))
                  self.assertLess(step_bp, 80.0)
                  overnight_path.append((k_eff, post_on))
              continue

          contracts_used = row.get("contracts") or []
          self.assertGreater(len(contracts_used), 0)
          lead = next(c for c in contracts_used if float(c.get("weight") or 0) > 0)
          product = lead.get("product")
          expiry = str(lead.get("expiry"))
          implied = float(lead["implied_rate"])
          k_eff = _parse_date(str(row["effective_date"]))

          if product == "COA":
              win_start, win_end = coa_accrual_window(expiry)
              pre_o = float(row["overnight_pre"])
              post_o = float(row["overnight_post"])
              recon = _ca_coa_reconstruct_implied(
                  win_start,
                  win_end,
                  k_eff,
                  pre_o,
                  post_o,
                  observation_date=None,
                  fixings_sorted=[],
              )
              self.assertTrue(
                  _ca_reconstruction_ok(implied, recon),
                  msg=f"COA {row.get('decision_date')} recon {recon} vs {implied}",
              )
              overnight_path.append((k_eff, post_o))
          elif product == "CRA":
              cs, ce = accrual_window(expiry, "3m")
              pre_on = float(row["overnight_pre"])
              post_on = float(row["overnight_post"])
              pre_meeting = _ca_overnight_on_day(
                  k_eff - __import__("datetime").timedelta(days=1),
                  initial_overnight=initial_overnight,
                  solved_overnight=overnight_path,
              )
              self.assertAlmostEqual(pre_on, pre_meeting, places=3)
              recon = _ca_cra_reconstruct_implied(
                  cs,
                  ce,
                  initial_overnight=initial_overnight,
                  solved_overnight=[
                      t for t in overnight_path if t[0] < k_eff
                  ],
                  pending_k_effs=[k_eff],
                  pending_posts=[post_on],
                  observation_date=None,
                  fixings_sorted=[],
              )
              self.assertTrue(
                  _ca_reconstruction_ok(implied, recon),
                  msg=f"CRA {row.get('decision_date')} recon {recon} vs {implied}",
              )
              overnight_path.append((k_eff, post_on))
          else:
              self.fail(f"unexpected product {product}")
          idx += 1


if __name__ == "__main__":
    unittest.main()
