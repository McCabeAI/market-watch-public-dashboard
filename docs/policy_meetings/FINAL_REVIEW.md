# Final review

Reviewer: Opus 5.5 high (`claude-opus-5-5-high`), agent `bc-e6a43906-36ec-5c2e-a473-9bbb21c9f279`.
The bare id `claude-opus-5-5` does not resolve in this environment. The high non-fast slug was the invocation that actually ran. The initial plan is `docs/policy_meetings/ARCHITECTURE.md` from agent `bc-9ecb41db-2c4c-518e-8f9a-22cd6d3c42ae`.

Verdict: one repair, then the paper, settlement, and old-book paths were accepted.

The repair is in `scripts/policy_meeting_pricing.py`. Past decision dates with no matching official history were treated as still unresolved, so a meeting could be printed more than once and Canada’s next decision could be dropped. Unresolved meetings are now only those whose effective date is after the as-of date, and the equal-step group keeps the meeting being solved. `tests/test_policy_meeting_pricing.py` covers the saved Bank of Canada calendar.

Independent Composer 2.5 verification (`bc-81034019-ecad-540f-ace1-9a4e8de561df`) ran 86 focused tests, 0 failures, before that repair. The same pricing, paper, calendar, policy-state, country-detail, and catalog tests passed again after the repair (50 tests).

Not blocking, and still true after the repair:

- Canada, Australia, and the euro area official series are standing anchors. Their dates are the series observation or announcement, not the calendar decision date, so settlement to those calendar dates stays on the last mark until a decision-dated outcome exists. The United States settles on the FOMC decision date.
- New Zealand has no schedule (HTTP 403) and no short-rate strip. The euro area has no FST3 settlements. Japan’s later 2026 decisions are PDFs, so the older HTML guideline is not used as the target.
