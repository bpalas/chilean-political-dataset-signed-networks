# Overnight — completa el NER de toda la ventana 2014-2026 (los dos períodos nuevos).
# $0 (GPU local). Idempotente: si algo ya está hecho, el resume por article_id lo salta.
# Cada paso es resumible: si se corta, relanzás este mismo script y sigue.
#
# Uso (en TU terminal PowerShell, NO dentro de Claude, para que sobreviva la noche):
#   powershell -ExecutionPolicy Bypass -File scripts\overnight.ps1
#
# ⚠️ NO correr dos NER a la vez (comparten state-w*.json → corrupción). Si dejaste un
#    NER corriendo en otra ventana, cerralo antes de lanzar esto.

$ErrorActionPreference = "Continue"
Set-Location "C:\Users\Benjamin Palacios\Documents\Github\chilean-political-dataset-signed-networks"
$env:HF_HUB_DISABLE_SYMLINKS = "1"
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"

$log = "overnight.log"
function Log($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $m" | Tee-Object -FilePath $log -Append }

Log "================= INICIO overnight ================="

Log "[1/3] NER 2022-2026 (resume — termina lo que falte)"
python scripts/run_ner_gliner.py --source data/processed/samples/political_2022_2026_80k.parquet --workers 2 --fp16 2>>overnight_err.log | Tee-Object -FilePath $log -Append

Log "[2/3] Construir muestra 2014-2018 (80k, prefiltro político)"
python scripts/build_political_sample.py --year-range 2014 2018 --limit 80000 --out data/processed/samples/political_2014_2018_80k.parquet 2>>overnight_err.log | Tee-Object -FilePath $log -Append

Log "[3/3] NER 2014-2018"
python scripts/run_ner_gliner.py --source data/processed/samples/political_2014_2018_80k.parquet --workers 2 --fp16 2>>overnight_err.log | Tee-Object -FilePath $log -Append

# Recuento final
$done = python -c "import json,glob; d=set(); [d.update(json.load(open(f))) for f in glob.glob('data/processed/ner/gliner/state-*.json')]; print(len(d))"
Log "NER global total: $done articulos"
Log "================= FIN overnight ================="
