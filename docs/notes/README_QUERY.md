uv run python scripts/smoke_live_rag.py \
  "sample_data/[FUJIFILM+BI]+Biodegradable+Particles_20240611M-1.pdf" \
  --max-pages 24 --max-chunks 80 \
  --question "Compare FBP-C01, FBP-C02 and FBP-C03"


uv run python scripts/smoke_live_rag.py \
  "sample_data/Presentation MIZOAN SOLUBIL ORG 1300- V2.pdf" \
  --max-pages 24 --max-chunks 80 \
  --question "what are the products from Biobeautech?"
  

