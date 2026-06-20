"""RE de producción con Gemini — extractor id15 (given_entities).

Dos modos:
  - sync:  1 llamada por artículo (para smoke / validar la API key y la calidad).
  - batch: Gemini Batch API (50% más barato, ventana ~24h) para los 80k+.

La API key se lee de la variable GEMINI_API_KEY (cargada de .env, gitignored).
NUNCA hardcodear la key.

Flujo batch: build_jsonl → submit (upload + create) → poll → fetch (download + reensamblar
por `key`=article_id). Re-enviar solo los FAILED/EXPIRED.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENOME = ROOT / "text2sg" / "prompts" / "id15_champion.json"


def load_genome(path: Path | str = GENOME) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_api_key() -> str:
    """Lee GEMINI_API_KEY del entorno o de .env (gitignored)."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    break
    if not key:
        raise RuntimeError("Falta GEMINI_API_KEY (en entorno o .env)")
    return key


def build_user_prompt(body: str, actors: list[str], max_chars: int = 6000) -> str:
    """Prompt de usuario para given_entities: artículo + lista de actores."""
    al = ", ".join(actors)
    return (f"ARTÍCULO:\n{body[:max_chars]}\n\n"
            f"ACTORES PRESENTES: {al}\n\n"
            "Extraé las relaciones políticas explícitas entre estos actores según las "
            "instrucciones del sistema. Devolvé SOLO el JSON, sin markdown.")


def make_client(api_key: str | None = None):
    from google import genai
    return genai.Client(api_key=api_key or load_api_key())


# Tope de tokens de salida: backstop contra respuestas desbocadas (runaway → costo).
# Medido: output típico ~600 tok, cola densa hasta ~3300 (25 relaciones en 1 art).
# 8192 cubre la cola con holgura SIN truncar JSON legítimo (un cap bajo corta el JSON
# a media frase → json.loads falla → se pierde el artículo en el fetch). No cambia el
# costo esperado: la respuesta para cuando termina, el tope solo frena un loop.
MAX_OUTPUT_TOKENS = 8192


def extract_sync(cl, body: str, actors: list[str], genome: dict,
                 max_output_tokens: int = MAX_OUTPUT_TOKENS) -> str:
    """Una llamada síncrona. Devuelve el texto (JSON) crudo del modelo."""
    from google.genai import types
    resp = cl.models.generate_content(
        model=genome["model"],
        contents=build_user_prompt(body, actors),
        config=types.GenerateContentConfig(
            system_instruction=genome["prompt_text"],
            response_mime_type="application/json",
            temperature=0,
            max_output_tokens=max_output_tokens,
        ),
    )
    return resp.text


# ── Batch API ───────────────────────────────────────────────────────────────
def build_jsonl(items: list[tuple[str, str, list[str]]], genome: dict, path: Path | str,
                max_output_tokens: int = MAX_OUTPUT_TOKENS) -> Path:
    """items: [(article_id, body, actors)]. Escribe el JSONL de entrada del batch.

    `max_output_tokens` topa la salida por request → protege el presupuesto contra
    respuestas desbocadas (clave en batches grandes; ver MAX_OUTPUT_TOKENS)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for key, body, actors in items:
            req = {
                "key": key,
                "request": {
                    "contents": [{"role": "user", "parts": [{"text": build_user_prompt(body, actors)}]}],
                    "system_instruction": {"parts": [{"text": genome["prompt_text"]}]},
                    "generation_config": {"response_mime_type": "application/json", "temperature": 0,
                                          "max_output_tokens": max_output_tokens},
                },
            }
            f.write(json.dumps(req, ensure_ascii=False) + "\n")
    return path


def submit(cl, jsonl_path: Path | str, genome: dict, display: str = "re-prod") -> str:
    """Sube el JSONL y crea el batch. Devuelve el nombre del job."""
    up = cl.files.upload(file=str(jsonl_path),
                         config={"mime_type": "application/jsonl", "display_name": display})
    batch = cl.batches.create(model=genome["model"], src=up.name,
                              config={"display_name": display})
    return batch.name


def poll(cl, name: str) -> str:
    b = cl.batches.get(name=name)
    return getattr(b.state, "name", str(b.state))


def fetch(cl, name: str) -> dict[str, str]:
    """Descarga los resultados del batch → {article_id: texto_json_crudo}."""
    b = cl.batches.get(name=name)
    out: dict[str, str] = {}
    dest = getattr(b, "dest", None)
    if dest and getattr(dest, "file_name", None):
        content = cl.files.download(file=dest.file_name).decode("utf-8")
        for line in content.splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            key = rec.get("key")
            resp = rec.get("response", {})
            try:
                out[key] = resp["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError):
                out[key] = ""
    return out
