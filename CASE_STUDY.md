# Early Shift Case Study

## Overview
Early Shift is a Roblox creator-intelligence system: it tracks CCU movement, matches that movement to recent YouTube coverage, and adds retention context so a studio can tell the difference between a flash spike and growth that actually sticks.

This case study is based on the current local DuckDB snapshot in `early_shift.db`.

## Snapshot
- CCU rows: 79,804
- Tracked games: 1,026
- YouTube videos indexed: 33,847
- Distinct YouTube channels indexed: 19,713
- Creator-linked detections: 568
- Retention profiles computed: 540

## Date Coverage
- CCU coverage window: 2025-09-23 to 2026-03-15
- Creator-linked spike coverage window: 2025-12-21 to 2026-02-07

The mismatch matters. CCU collection is current through March 15, 2026, but the latest creator-linked spike already recorded in this database is February 7, 2026. That makes this a real snapshot of current capabilities, not a polished sample dataset.

## What the Public Surface Now Shows
The public-lite Streamlit surface focuses on three things:
- creator impact
- detection proof
- a "check a Roblox game" tool for fast studio-facing recommendations

That is the right packaging layer for Early Shift now. The analytics engine already exists; the leverage comes from making the strongest parts legible in under five minutes.

## Proof Points

### 1. Creator impact is already visible
Recent creator patterns in this snapshot include:

| Creator | Spike Videos | Games Covered | Median Growth | Median Lag |
| --- | --- | --- | --- | --- |
| CaptainT1 | 10 | 5 | +85.9% | 24.5h |
| Wity gaming | 10 | 5 | +79.4% | 23.1h |
| Fisher Roblox | 6 | 3 | +46.7% | 23.6h |
| axolotl_glitch | 6 | 3 | +53.7% | 38.0h |

This is the useful part for a studio. The product is not just saying "YouTube was active." It is saying which creators repeatedly show up before lift, across how many games, and how quickly the lift tends to land.

### 2. Detection volume is already nontrivial
In the last 14 days of creator-linked detections relative to the latest spike date in the DB:
- detections: 124
- distinct games detected: 62
- median growth at detection: +87.5%
- average growth at detection: +106.6%

That is enough density to show the system is past toy-demo stage.

### 3. Retention context makes the signal more useful
The system already has 540 retention profiles with:
- average stickiness index: 0.835
- average decay time: 4.16 days
- average spike count over 60 days: 7.34

This is important because a studio does not just want "who caused a spike." It wants to know whether that spike tends to hold or disappear.

## Example Cases

| Game | Standout Creator | Growth at Detection | CCU at Detection | Stickiness | Decay Days |
| --- | --- | --- | --- | --- | --- |
| Brookhaven RP | AFTER GAMING BROOKHAVEN | +169.4% | 601,802 | 100.0% | 3.0 |
| Murder Mystery 2 | prizmatic | +150.1% | 146,070 | 87.7% | 3.0 |
| Glide Tower | CaptainT1 | +156.1% | 5,412 | 100.0% | 4.0 |

These examples are not meant as causal proof in the scientific sense. They are operational proof that the pipeline can surface creator-linked lift, attach timing, and add quality context.

## Why This Matters
For Roblox hiring:
- it demonstrates creator empathy, product sense, and applied analytics rather than just data collection

For studio outreach:
- it gives a simple wedge: "check your game, see the creator signal, decide what to do next"

For the product itself:
- the next highest-leverage work is not another analytics subsystem
- the next highest-leverage work is packaging the existing signal into a clean public report and a narrow tool a developer can use immediately

## Current Limits
- Creator-linked spike data in this snapshot currently stops on February 7, 2026.
- Thumbnail CTR and impression analysis are still a weak priority because YouTube public APIs do not cleanly provide arbitrary-channel CTR data without analytics ownership and auth.
- Detection quality should continue to be framed as evidence-backed correlation, not deterministic attribution.
