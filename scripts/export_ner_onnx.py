"""Exporta GLiNER a ONNX y lo benchmarkea vs PyTorch fp16, verificando paridad.

RESULTADO (RTX 4070 8GB, 2026-06-19): ONNX es UN CALLEJÓN SIN SALIDA para este modelo.
    PyTorch fp16   14.8 art/s
    ONNX CUDA       0.9 art/s   (0.06x — 16x MÁS LENTO) | Jaccard 0.9897 (export correcto)
Dos causas independientes:
  1. El loader ONNX de GLiNER 0.2.27 NO respeta `providers=[CUDA…]`: la InferenceSession
     queda en CPUExecutionProvider (verificado con sess.get_providers()). Corre el
     transformer en CPU → de ahí el 16x.
  2. El head de spans de gliner_multi-v2.1 es un LSTM (warnings PackPadded/PadPacked al
     exportar) con shapes variables — el peor caso para ONNX-CUDA. Aun forzando GPU,
     improbable que supere a fp16 y arriesga correctitud.
Conclusión: el campeón de velocidad sigue siendo PyTorch + --fp16 (~1.5x, paridad 0.99).
Se deja este script como evidencia reproducible del descarte, no como camino de prod.

La hipótesis original (ONNX fusiona kernels → más rápido) era razonable pero falló en
la práctica; medir antes de adoptar evitó cablear una regresión de 16x en producción.

Pasos:
  1. export    — carga GLiNER PyTorch, exporta a data/models/gliner_onnx/model.onnx
  2. bench     — corre PyTorch fp16 vs ONNX (CUDA EP) sobre N artículos, compara
                 velocidad y paridad de entidades (Jaccard sobre (text.lower, type)).

Uso:
    python scripts/export_ner_onnx.py export
    python scripts/export_ner_onnx.py bench --limit 200
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "data/processed/samples/political_2019_2022_80k.parquet"
ONNX_DIR = ROOT / "data/models/gliner_onnx"


def cmd_export(args) -> None:
    from text2sg.ner_gliner import DEFAULT_MODEL, load_model
    print(f"Cargando {DEFAULT_MODEL} (PyTorch)…")
    model = load_model(device="cpu")  # el export corre en CPU
    ONNX_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Exportando a ONNX → {ONNX_DIR} (opset 19, esto tarda ~1-2 min)…")
    res = model.export_to_onnx(ONNX_DIR, quantize=args.quantize)
    print("Listo:", res)


def _ent_set(res: dict) -> set:
    return {(e["text"].lower(), e["type"]) for e in res["entities"]}


def cmd_bench(args) -> None:
    import pandas as pd
    import torch
    from gliner import GLiNER
    from text2sg.ner_gliner import LABELS_ES, extract_batch, load_model

    df = pd.read_parquet(SOURCE, columns=["article_id", "body"]).head(args.limit)
    rows = list(df.itertuples(index=False, name=None))
    print(f"Artículos: {len(rows)} | GPU: {torch.cuda.get_device_name(0)}\n")

    def run_all(model, fp16=False) -> tuple[list[dict], float]:
        out: list[dict] = []
        t0 = time.time()
        for s in range(0, len(rows), args.bs):
            out.extend(extract_batch(model, rows[s:s + args.bs], fp16=fp16))
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        return out, time.time() - t0

    # --- PyTorch fp16 (el campeón actual) ---
    pt = load_model()
    run_all(pt, fp16=True)  # warmup
    base, t_pt = run_all(pt, fp16=True)
    r_pt = len(rows) / t_pt
    print(f"PyTorch fp16   {t_pt:6.2f}s  {r_pt:6.1f} art/s")
    del pt
    torch.cuda.empty_cache()

    # --- ONNX (CUDA EP) ---
    onnx_file = "model_quantized.onnx" if args.quantized else "model.onnx"
    ox = GLiNER.from_pretrained(
        str(ONNX_DIR), load_onnx_model=True, onnx_model_file=onnx_file,
        load_tokenizer=True, providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    run_all(ox)  # warmup
    onnx_out, t_ox = run_all(ox)
    r_ox = len(rows) / t_ox

    # paridad
    jacc, lost, gained = [], 0, 0
    for ra, rb in zip(base, onnx_out):
        sa, sb = _ent_set(ra), _ent_set(rb)
        jacc.append(len(sa & sb) / (len(sa | sb) or 1))
        lost += len(sa - sb)
        gained += len(sb - sa)
    j = sum(jacc) / len(jacc)
    print(f"ONNX CUDA      {t_ox:6.2f}s  {r_ox:6.1f} art/s  ({r_ox/r_pt:.2f}x vs fp16) "
          f"| Jaccard {j:.4f}  -{lost}/+{gained} ent")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pe = sub.add_parser("export")
    pe.add_argument("--quantize", action="store_true", help="genera también int8 (CPU)")
    pe.set_defaults(func=cmd_export)
    pb = sub.add_parser("bench")
    pb.add_argument("--limit", type=int, default=200)
    pb.add_argument("--bs", type=int, default=16)
    pb.add_argument("--quantized", action="store_true", help="benchmarkea el int8")
    pb.set_defaults(func=cmd_bench)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
