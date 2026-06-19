"""Sincroniza datos con HuggingFace Hub para cómputo distribuido entre laptops.

`push` sube una carpeta o archivo a un dataset; `pull` lo baja. Pensado para repartir
el NER entre 2 máquinas: subís el corpus una vez, cada laptop lo baja, corre su --shard,
y sube sus resultados; al final bajás todo y consolidás.

Auth: token HF en la variable HF_TOKEN, o `huggingface-cli login` una vez.
Token: https://huggingface.co/settings/tokens (scope write).

⚠️ El CORPUS son noticias con copyright (licencia CC-BY-NC) → subilo PRIVADO (default).
Los RESULTADOS del NER (entidades, sin el texto completo) pueden ir públicos (--public).

Uso:
    # 1) en la PC principal, subir el corpus (privado):
    python scripts/hf_sync.py push --repo TUUSUARIO/clivaje-corpus \\
        --path data/processed/samples/political_2019_2022_80k.parquet
    # 2) en la PC2, bajarlo:
    python scripts/hf_sync.py pull --repo TUUSUARIO/clivaje-corpus --out data/processed/samples
    # 3) cada laptop sube sus shards de NER:
    python scripts/hf_sync.py push --repo TUUSUARIO/clivaje-ner --path data/processed/ner/gliner
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("push", help="subir carpeta/archivo a un dataset HF")
    p.add_argument("--repo", required=True, help="usuario/nombre-del-dataset")
    p.add_argument("--path", required=True, help="archivo o carpeta local a subir")
    p.add_argument("--public", action="store_true", help="dataset público (default: privado)")
    q = sub.add_parser("pull", help="bajar un dataset HF")
    q.add_argument("--repo", required=True)
    q.add_argument("--out", default=".", help="carpeta destino")
    args = ap.parse_args()

    from huggingface_hub import HfApi, create_repo, snapshot_download

    if args.cmd == "push":
        create_repo(args.repo, repo_type="dataset", private=not args.public, exist_ok=True)
        path = Path(args.path)
        api = HfApi()
        if path.is_dir():
            api.upload_folder(folder_path=str(path), repo_id=args.repo, repo_type="dataset")
        else:
            api.upload_file(path_or_fileobj=str(path), path_in_repo=path.name,
                            repo_id=args.repo, repo_type="dataset")
        print(f"Subido {args.path} → {args.repo} ({'público' if args.public else 'privado'})")
    else:
        d = snapshot_download(repo_id=args.repo, repo_type="dataset", local_dir=args.out)
        print(f"Bajado {args.repo} → {d}")


if __name__ == "__main__":
    main()
