# Model Discovery Ranking Design

## Goal

Make default `model-discovery` results useful for the RX 7900 XT instead of reflecting only Hugging Face download order.

## Ranking

The command still queries Hugging Face broadly for `GGUF`, then ranks candidates locally before printing.

Buckets:

1. `target`: `14B-40B`, preferred for this machine.
2. `unknown`: unusual size names, kept visible for inspection.
3. `small`: `1B-9B`, demoted as speed/test candidates.
4. `huge`: `70B+`, demoted as unlikely without major tradeoffs.

Within buckets, boost candidates whose repo names or tags suggest code, coder, reasoning, R1, Qwen, Gemma, or gpt-oss relevance. Use Hugging Face downloads as a tiebreaker.

## Output

Each Hugging Face candidate should include `purpose`, `class`, `fit`, and a short note. Tiny models remain visible but should not dominate the default list.
