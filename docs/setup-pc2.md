# Setup de la 2ª laptop — NER distribuido (HF + GitHub)

Repartir el NER (GLiNER, Pasada 1) entre 2 laptops iguales. **No requiere conexión en
vivo** entre las máquinas: cada una baja su parte, procesa, y sube resultados a HuggingFace.
Aplica a escalas grandes (383k / 4.88M); para el 80k una sola PC alcanza.

Solo acelera el **NER** (cómputo local en GPU). El **RE** (subagentes Haiku) NO se acelera
con 2 PC — corre en la nube de Anthropic, limitado por la cuenta, no por el hardware.

## Una sola vez: subir el corpus a HF (desde la PC principal)

```bash
# token con scope write: https://huggingface.co/settings/tokens
export HF_TOKEN=hf_xxx              # (PowerShell: $env:HF_TOKEN="hf_xxx")
python scripts/hf_sync.py push --repo TUUSUARIO/clivaje-corpus \
    --path data/processed/samples/political_2019_2022_383k.parquet
```
El corpus va **privado** (noticias con copyright). Los resultados NER pueden ir públicos.

## En la 2ª laptop (setup único)

```bash
git clone https://github.com/bpalas/chilean-political-dataset-signed-networks
cd chilean-political-dataset-signed-networks
pip install gliner duckdb pandas pyarrow huggingface_hub
export HF_TOKEN=hf_xxx
python scripts/hf_sync.py pull --repo TUUSUARIO/clivaje-corpus --out data/processed/samples
```
El modelo GLiNER se baja solo de HuggingFace la 1ª vez.

## Correr (cada laptop su mitad)

```bash
# PC principal (laptop A):
HF_HUB_DISABLE_SYMLINKS=1 python scripts/run_ner_gliner.py \
    --source data/processed/samples/political_2019_2022_383k.parquet --shard 0/2

# laptop B:
HF_HUB_DISABLE_SYMLINKS=1 python scripts/run_ner_gliner.py \
    --source data/processed/samples/political_2019_2022_383k.parquet --shard 1/2
```
`--shard k/N` hace que cada máquina tome 1 de cada N artículos. Los shards de cada laptop
llevan prefijo distinto (`part-s0-…`, `part-s1-…`) → **no colisionan** al juntarlos.
Cada laptop tiene su propio checkpoint (`state-s{k}-*.json`), resumible.

## Juntar resultados

```bash
# laptop B sube sus shards:
python scripts/hf_sync.py push --repo TUUSUARIO/clivaje-ner --path data/processed/ner/gliner --public
# PC principal los baja y ya tiene todo junto en data/processed/ner/gliner/:
python scripts/hf_sync.py pull --repo TUUSUARIO/clivaje-ner --out data/processed/ner/gliner
```
Como los nombres no colisionan, ambos juegos de shards conviven y se consolidan juntos.

## Doble propósito
El corpus en HF sirve también para la **publicación** del dataset (Zenodo/HF + DOI) que
ya está en el roadmap. Subirlo ahora adelanta ese paso.
