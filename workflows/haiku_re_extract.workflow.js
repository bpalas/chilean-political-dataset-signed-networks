// Relationship Extraction (Pasada 3) — subagentes Haiku, GROUP artículos por agente.
// $0 (budget de sesión). Para una MUESTRA (cap ~1000 agentes), no para 80k+.
//
// Optimización vs 1-agente-por-artículo: cada agente procesa GROUP=5 artículos en un
// prompt → el prompt haiku_ge_best (~15k chars) se lee N/5 veces, no N. pipeline() solapa
// extracción y guardado sin barreras. Guardado INCREMENTAL por grupo: cada grupo escribe
// su shard (nombre = 1er article_id, estable) apenas se extrae → si corta, se pierde ≤GROUP.
// Checkpoint: el setup omite los article_id ya presentes en shards. El gate de evidencia
// (substring literal) se RE-APLICA determinista en la consolidación.
//
// Requiere NER previo (actores) en data/processed/ner/gliner/.
// Uso: Workflow({ script:'workflows/haiku_re_extract.workflow.js', args:{ n_art:200, group:5 } })
// Salida: data/processed/re/shards/shard-*.json (incremental) + relations.parquet (final)
export const meta = {
  name: 'haiku-re-extract',
  description: 'Relationship Extraction con subagentes Haiku (GROUP art/agente), pipeline sin barreras, guardado incremental y gate de evidencia determinista',
  phases: [
    { title: 'Setup', detail: 'join body + actores, calcular pendientes (checkpoint)' },
    { title: 'Extract', detail: 'agente Haiku por grupo de GROUP artículos' },
    { title: 'Consolidate', detail: 'unir shards + gate de evidencia → parquet' },
  ],
}

const A = (typeof args === 'string') ? (() => { try { return JSON.parse(args) } catch { return {} } })() : (args || {})
const N_ART = A.n_art || 200
const GROUP = A.group || 5            // artículos por agente (amortiza el overhead del prompt)
const DIR   = 'data/processed/re'

const ACT = ['endorses','attacks','allies_with','calls_on','distances_from','questions','negotiates_with','competes_with','accuses']
// Output del agente: una entrada por artículo del grupo, cada una con sus relaciones.
const GROUP_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    results: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          idx: { type: 'integer' },
          relations: {
            type: 'array',
            items: {
              type: 'object', additionalProperties: false,
              properties: {
                from_entity: { type: 'string' }, to_entity: { type: 'string' },
                act_type: { type: 'string', enum: ACT },
                polarity: { type: 'string', enum: ['positive','negative','neutral'] },
                issue: { type: 'string' }, evidence_quote: { type: 'string' },
              },
              required: ['from_entity','to_entity','act_type','polarity','issue','evidence_quote'],
            },
          },
        },
        required: ['idx','relations'],
      },
    },
  },
  required: ['results'],
}

// ── Setup: pendientes (body + actores) con checkpoint sobre shards existentes ──
phase('Setup')
const setup = await agent(
  `Preparar la muestra para RE con checkpoint. Corré este Python y devolvé {n, already_done}:

python - <<'PY'
import json, glob, os, pandas as pd
os.makedirs("${DIR}/shards", exist_ok=True)
done=set()
for sh in glob.glob("${DIR}/shards/shard-*.json"):
    for rec in json.load(open(sh,encoding="utf-8")): done.add(rec["article_id"])
samp = pd.read_parquet("data/processed/samples/political_2019_2022_80k.parquet", columns=["article_id","body"])
ner = pd.concat([pd.read_parquet(s) for s in glob.glob("data/processed/ner/gliner/year=*/part-*.parquet")], ignore_index=True)
keep={"person","party","institution","coalition","movement","org"}
pend=[]
for _,r in ner.iterrows():
    if r.article_id in done: continue
    b = samp.loc[samp.article_id==r.article_id,"body"]
    if b.empty: continue
    actors=sorted({e["text"] for e in json.loads(r.entities) if e["type"] in keep})
    if len(actors)>=2: pend.append({"article_id":r.article_id,"body":b.iloc[0],"actors":actors})
    if len(pend)>=${N_ART}: break
json.dump(pend, open("${DIR}/pending.json","w",encoding="utf-8"), ensure_ascii=False)
print(json.dumps({"n":len(pend),"already_done":len(done)}))
PY`,
  { label: 'setup', phase: 'Setup', model: 'sonnet',
    schema: { type:'object', additionalProperties:false,
      properties:{ n:{type:'integer'}, already_done:{type:'integer'} }, required:['n'] } }
)
if (!setup || !setup.n) return { done: setup ? setup.already_done : 0, note: 'nada pendiente o falta NER' }
log(`${setup.n} pendientes (ya hechos: ${setup.already_done || 0}) · grupos de ${GROUP}`)

// Agrupar índices [0..n) en grupos de GROUP
const groups = []
for (let i = 0; i < setup.n; i += GROUP) {
  const g = []
  for (let j = i; j < Math.min(i + GROUP, setup.n); j++) g.push(j)
  groups.push(g)
}

// ── Extract: pipeline sin barreras — extraer grupo → guardar su shard ──
phase('Extract')
await pipeline(
  groups,
  // Stage 1 — 1 agente Haiku procesa GROUP artículos
  async (g) => {
    const r = await agent(
      `Leé el sistema de extracción en text2sg/prompts/haiku_ge_best.txt y seguilo al pie.
En ${DIR}/pending.json procesá los artículos con estos índices: ${JSON.stringify(g)}.
Cada uno tiene "body" y "actors". Para CADA artículo, extraé relaciones SOLO entre sus
actores, auto-verificando: dirección (from=quien realiza el acto; pasivas "X criticado por
Y" -> from=Y), polaridad (positive/negative/neutral), y evidencia (evidence_quote = texto
LITERAL del body; si no podés citar literal, no la emitas).
Devolvé {"results":[{"idx":<índice>,"relations":[...]}, ...]} con una entrada por índice.`,
      { label: `re:${g[0]}-${g[g.length-1]}`, phase: 'Extract', model: 'haiku', schema: GROUP_SCHEMA }
    )
    return { g, results: (r && r.results) || [] }
  },
  // Stage 2 — guardar el shard del grupo (incremental, nombre = 1er article_id del grupo)
  async (ext) => {
    if (!ext || !ext.results.length) return null
    const payload = JSON.stringify(ext.results)
    return agent(
      `Guardá el shard de este grupo RE. Corré:

python - <<'PY'
import json
res = json.loads('''${payload}''')
pend = json.load(open("${DIR}/pending.json", encoding="utf-8"))
out=[{"article_id": pend[r["idx"]]["article_id"], "relations": r["relations"]} for r in res]
name = out[0]["article_id"] if out else "empty"
json.dump(out, open(f"${DIR}/shards/shard-{name}.json","w",encoding="utf-8"), ensure_ascii=False)
print(json.dumps({"shard": name, "articles": len(out)}))
PY`,
      { label: `save:${ext.g[0]}`, phase: 'Extract', model: 'sonnet',
        schema: { type:'object', additionalProperties:false,
          properties:{ shard:{type:'string'}, articles:{type:'integer'} }, required:['articles'] } }
    )
  }
)

// ── Consolidate: unir shards + gate de evidencia determinista → parquet ──
phase('Consolidate')
const consolidated = await agent(
  `Consolidá los shards RE aplicando el gate de evidencia (substring literal ≥8 chars). Corré:

python - <<'PY'
import json, glob, pandas as pd
samp = pd.read_parquet("data/processed/samples/political_2019_2022_80k.parquet", columns=["article_id","body","publish_date","source","year"])
bodies = dict(zip(samp.article_id, samp.body))
rows=[]; kept=0; dropped=0
for sh in glob.glob("${DIR}/shards/shard-*.json"):
    for rec in json.load(open(sh,encoding="utf-8")):
        body = bodies.get(rec["article_id"],"")
        for r in rec["relations"]:
            q=(r.get("evidence_quote") or "").strip()
            if len(q)>=8 and q in body: rows.append({"article_id":rec["article_id"], **r}); kept+=1
            else: dropped+=1
df=pd.DataFrame(rows)
if len(df):
    df=df.merge(samp[["article_id","publish_date","source","year"]], on="article_id", how="left")
df.to_parquet("${DIR}/relations.parquet", index=False)
print(json.dumps({"relations_kept":kept,"dropped_by_evidence":dropped,
                  "articles_with_rels": int(df.article_id.nunique()) if len(df) else 0}))
PY`,
  { label: 'consolidate', phase: 'Consolidate', model: 'sonnet',
    schema: { type:'object', additionalProperties:false,
      properties:{ relations_kept:{type:'integer'}, dropped_by_evidence:{type:'integer'},
        articles_with_rels:{type:'integer'} }, required:['relations_kept'] } }
)

return { pending: setup.n, group_size: GROUP, ...(consolidated || {}) }
