# 0.5.5

Includes first/last/next pose references and source-bound crop plans from 0.5.4.
Fix validation order when a caller overrides an already prepared frame count:
reject the changed export contract before diagnosing its now-mismatched phases.
Existing outputs remain untouched by rejection.
