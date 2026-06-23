# Multi-Agent Figures

This directory contains figures for the RAVEL multi-agent write-safety project. It is
independent from `/home/xqin5/llmlanguage`.

## Latest figures

- `fig01_corrected_unsafe_writes.png`: corrected oracle-based primary result.
- `fig02_safety_rate_and_overblock.png`: unsafe execution rate and clean-control overblock.
- `fig03_fieldmask_extension.png`: V2 FieldMask extension, reported separately from primary.
- `fig04_token_overhead.png`: gate-ON token overhead in corrected and V2 analyses.

## Sources

Primary corrected analysis:

```text
results/mas_safety_corrected/safety_corrected_results.csv
```

FieldMask extension:

```text
results/mas_safety_v2/safety_v2_results.csv
```

Regenerate:

```bash
cd /home/xqin5/multiaiagent
python scripts/plot_latest_multiagent_results.py
```
