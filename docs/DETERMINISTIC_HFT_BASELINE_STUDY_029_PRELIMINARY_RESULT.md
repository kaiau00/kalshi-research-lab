# Deterministic HFT Baseline Study 029 — preliminary replay

Run October 23, 2026 under registration SHA-256
`14d855d0059931b9b4d2de06e362cea6a9924c2dacd2981d52937948e01a67b5`.

This was the first P&L replay of the frozen Study 029 baseline. It used 76 verified main recorder segments and 172
verified public-trade segments, merged by local receipt time. The main-manifest SHA-256 was
`2000e0cad25f8e893042d3db6aca49b539a874be8223f49e360f8bc2275764a6`; the trade-manifest SHA-256 was
`f3a42c00a027496455b2ba23d2f5f8d60050c9d9cdf7fa808fadd4865fbb4f37`.

## Result

The 39.2045-hour slice covered three UTC dates and 2,049,350 validated public trades. The engine generated two
quote intents. One was rejected at its modeled 500 ms acknowledgement because it had become marketable. One joined
the back of the displayed queue and was later canceled by the deterministic refresh rule. It received no plausible
fill. Two public trades had ambiguous cross-stream ordering and received no queue credit.

There were zero settled fills and $0 net P&L. Only the zero-unresolved-exposure gate passed. The 20-date,
1,000-fill, profitability, top-three-concentration, four-of-five-block and one-cent-stress gates all failed or were
not measurable. `credible_edge=false` and `jev_comparison_authorized=false`.

The result means this exact baseline is too selective to establish an HFT edge on the available tape. It does not
support adding Jev, increasing risk or promoting the strategy. Any parameter change would be a new registered
candidate and would need a separate development/validation split; it cannot overwrite this result.

The machine-readable report is [HFT_BASELINE_STUDY_029_PRELIMINARY_RESULT.json](HFT_BASELINE_STUDY_029_PRELIMINARY_RESULT.json).
