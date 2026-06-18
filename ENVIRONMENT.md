# Environment Snapshot

Date: 2026-06-15, America/Chicago.

## Host

- Workspace root: `/home/xqin5/multiaiagent`
- `/home/xqin5` is not a Git repository: `NOT APPLICABLE`
- Python used by `uv run`: CPython 3.12.7
- `uv`: 0.11.17

## GPU

Observed with `nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv,noheader`:

| GPU | Name | Total Memory | Used Memory | Utilization |
| --- | --- | ---: | ---: | ---: |
| 0 | NVIDIA A100 80GB PCIe | 81920 MiB | 74239 MiB | 0% |
| 1 | NVIDIA A100 80GB PCIe | 81920 MiB | 74239 MiB | 0% |
| 2 | NVIDIA A100 80GB PCIe | 81920 MiB | 76335 MiB | 0% |
| 3 | NVIDIA A100 80GB PCIe | 81920 MiB | 14 MiB | 0% |

## Active Model Endpoints

| Port | Served Model IDs | Root | Notes |
| ---: | --- | --- | --- |
| 8005 | `g4` | `/home/xqin5/hf_p08_models/gemma-4-31B-it` | vLLM, `gemma4` parser, max len 16384 |
| 8190 | `q` | `/home/xqin5/agentsearch/models/Qwen3.6-27B` | vLLM, max len 131072 |
| 8200 | `Qwen/Qwen3.6-27B`, `q`, `gpt-q` | `/home/xqin5/agentsearch/models/Qwen3.6-27B` | vLLM, `qwen3_coder` parser, max len 131072 |

Proposal models not currently confirmed as active endpoints: `gpt-oss-120b`, `Qwen3-32B`, `GLM-4.5-Air`, `Llama-3.3-70B-Instruct`.

## Dependency Notes

`uv run tau2 --help` initially failed in sandbox due DNS while downloading `numpy==2.3.5`. A network-approved rerun installed dependencies and made the tau2 CLI available.

