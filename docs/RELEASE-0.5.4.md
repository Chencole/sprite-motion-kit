# 0.5.4

Prepared actions now include explicit first/last/next reference strips. Loops
continue from their last sampled pose into the first; one-shot actions hold the
settled final pose. Generation packets include this third reference, and final
pose checks compare the endpoint displacement with the intended reference.

Add source-bound crop plans and source-image overlays. Fixed margins and gutters
can be represented without individually recentering characters. New final
exports require inspected crop geometry. Pose observations, extraction and batch
acceptance use the same rectangles and fingerprints; changed source images,
reordered/overlapping cells and variable body crops are rejected.

Diagnostic previews remain available independently of final acceptance. This
release does not regenerate game art or certify previous failed animations.
Reference conditioning cannot guarantee perfect image-model output.
