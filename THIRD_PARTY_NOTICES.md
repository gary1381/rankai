# Third-party notices

This repository contains no vendored third-party source code, model weights or posting data. Its programs use the
following through public interfaces. Each is installed or obtained separately:

| Dependency | License | Used by |
|---|---|---|
| Anthropic Python SDK (`anthropic`) | MIT | `rankai/llm.py` |
| Model Context Protocol Python SDK (`mcp`) | MIT | `rankai/mcp_server.py` |
| NumPy, SciPy, scikit-learn, matplotlib | BSD-3-Clause / BSD-3-Clause / BSD-3-Clause / PSF-based (matplotlib license) | ranking, evaluation, charts |
| OpenCC (system library `libopencc`, `t2s.json`), loaded with ctypes if present | Apache-2.0 | `rankai/text.py`: Traditional to Simplified folding |
| multilingual-e5-small (served by your own embedding server) | MIT | `rankai/models.py` |
| Qwen3-Reranker-0.6B (served by your own vLLM) | Apache-2.0 | `rankai/models.py`; the prompt template follows the model card |
| Claude Haiku (Anthropic API) | Anthropic commercial terms | query rewrite, posting labels |

## Data sources

Postings come from third-party services under their own terms; see [docs/SOURCES.md](docs/SOURCES.md). No posting
text is included here. When results are shown, keep each source's attribution (`rankai/sources.py: ATTRIBUTION`).
For example, Taiwan Jobs open data (data.gov.tw dataset 44062) is used under the Open Government Data License,
version 1.0, which requires its attribution text.
