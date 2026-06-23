# Overnight — NER del top-up proporcional (251k art) → completa 480k en 2014-2026.
# $0 (GPU local). Idempotente: el resume por article_id salta lo ya hecho.
# Si se corta, relanzás este mismo script y sigue.
#
# Uso (en TU terminal PowerShell, NO dentro de Claude, para que sobreviva la noche):
#   powershell -ExecutionPolicy Bypass -File scripts\overnight.ps1
#
# REGLAS DE ORO:
#   1. Cerrá la sesión de Claude antes de lanzar (nunca dos NER a la vez → corrompe state-w*.json).
#   2. Laptop enchufada y suspensión en "Nunca" (si se duerme, el NER pausa).

$ErrorActionPreference = "Continue"
Set-Location "C:\Users\Benjamin Palacios\Documents\Github\chilean-political-dataset-signed-networks"
$env:HF_HUB_DISABLE_SYMLINKS = "1"
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"

$log = "overnight.log"
function Log($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $m" | Tee-Object -FilePath $log -Append }

Log "================= INICIO overnight (top-up 251k) ================="

Log "NER top-up proporcional (251k art nuevos, ~5.8h a ~12 art/s fp16)"
python scripts/run_ner_gliner.py --source data/processed/samples/political_topup_251k.parquet --workers 2 --fp16 2>>overnight_err.log | Tee-Object -FilePath $log -Append

$done = python -c "import json,glob; d=set(); [d.update(json.load(open(f))) for f in glob.glob('data/processed/ner/gliner/state-*.json')]; print(len(d))"
Log "NER global total: $done articulos"
Log "================= FIN overnight ================="
