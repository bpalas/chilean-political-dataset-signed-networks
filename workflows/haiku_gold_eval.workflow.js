// Test con gold (RE) — corre el extractor haiku_ge_best sobre el test set del gold v2
// (75 art, actores dados = given_entities) y guarda predicciones para score_gold.py.
// $0 (sesión). Mismo extractor que producción, sin gate de evidencia (el scorer compara
// tripletas contra el gold). GROUP art/agente para amortizar overhead.
//
// Requiere: data/processed/gold_test/input.json (scripts arman el input).
// Uso: Workflow({ script:'workflows/haiku_gold_eval.workflow.js' })
// Salida: data/processed/gold_test/preds.json  → luego: python scripts/score_gold.py
export const meta = {
  name: 'haiku-gold-eval',
  description: 'Genera predicciones RE del extractor Haiku sobre el test set del gold v2 (given_entities) para medir P/R/f0.5',
  phases: [
    { title: 'Setup', detail: 'leer input.json (75 art con actores)' },
    { title: 'Extract', detail: 'extractor Haiku por grupo de GROUP' },
    { title: 'Consolidate', detail: 'unir shards → preds.json' },
  ],
}

const A = (typeof args === 'string') ? (() => { try { return JSON.parse(args) } catch { return {} } })() : (args || {})
const GROUP = A.group || 5
const DIR = 'data/processed/gold_test'

const ACT = ['endorses','attacks','allies_with','calls_on','distances_from','questions','negotiates_with','competes_with','accuses']
const REL_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    results: { type: 'array', items: {
      type: 'object', additionalProperties: false,
      properties: {
        idx: { type: 'integer' },
        relations: { type: 'array', items: {
          type: 'object', additionalProperties: false,
          properties: {
            from_entity: { type: 'string' }, to_entity: { type: 'string' },
            act_type: { type: 'string', enum: ACT },
            polarity: { type: 'string', enum: ['positive','negative','neutral'] },
            issue: { type: 'string' }, evidence_quote: { type: 'string' },
          },
          required: ['from_entity','to_entity','act_type','polarity','issue','evidence_quote'],
        } },
      },
      required: ['idx','relations'],
    } },
  },
  required: ['results'],
}

phase('Setup')
const setup = await agent(
  `Corré: python -c "import json; d=json.load(open('${DIR}/input.json',encoding='utf-8')); print(json.dumps({'n':len(d)}))" y devolvé {n}.`,
  { label: 'setup', phase: 'Setup', model: 'sonnet',
    schema: { type:'object', additionalProperties:false, properties:{ n:{type:'integer'} }, required:['n'] } }
)
if (!setup || !setup.n) return { error: 'falta gold_test/input.json' }
log(`${setup.n} artículos del test set · grupos de ${GROUP}`)

const groups = []
for (let i = 0; i < setup.n; i += GROUP) {
  const g = []
  for (let j = i; j < Math.min(i + GROUP, setup.n); j++) g.push(j)
  groups.push(g)
}

phase('Extract')
await pipeline(
  groups,
  async (g) => {
    const r = await agent(
      `Leé el sistema de extracción en text2sg/prompts/haiku_ge_best.txt y seguilo al pie.
En ${DIR}/input.json procesá los artículos con índices ${JSON.stringify(g)} (cada uno tiene
"body" y "actors"). Para CADA artículo extraé relaciones SOLO entre sus actores, con cita
literal (evidence_quote = substring del body). Devolvé {"results":[{"idx":i,"relations":[...]}]}.`,
      { label: `gold:${g[0]}-${g[g.length-1]}`, phase: 'Extract', model: 'haiku', schema: REL_SCHEMA }
    )
    return { g, results: (r && r.results) || [] }
  },
  async (ext) => {
    if (!ext || !ext.results.length) return null
    const payload = JSON.stringify(ext.results)
    return agent(
      `Guardá el shard. Corré:

python - <<'PY'
import json
res = json.loads('''${payload}''')
inp = json.load(open("${DIR}/input.json", encoding="utf-8"))
out=[{"article_id": inp[r["idx"]]["article_id"], "relations": r["relations"]} for r in res]
import os; os.makedirs("${DIR}/preds_shards", exist_ok=True)
json.dump(out, open(f"${DIR}/preds_shards/shard-{out[0]['article_id']}.json","w",encoding="utf-8"), ensure_ascii=False)
print(json.dumps({"articles": len(out)}))
PY`,
      { label: `save:${ext.g[0]}`, phase: 'Extract', model: 'sonnet',
        schema: { type:'object', additionalProperties:false, properties:{ articles:{type:'integer'} }, required:['articles'] } }
    )
  }
)

phase('Consolidate')
const done = await agent(
  `Uní los shards en preds.json. Corré:

python - <<'PY'
import json, glob
out=[]
for sh in glob.glob("${DIR}/preds_shards/shard-*.json"):
    out += json.load(open(sh,encoding="utf-8"))
json.dump(out, open("${DIR}/preds.json","w",encoding="utf-8"), ensure_ascii=False)
print(json.dumps({"articles": len(out), "relations": sum(len(x["relations"]) for x in out)}))
PY`,
  { label: 'consolidate', phase: 'Consolidate', model: 'sonnet',
    schema: { type:'object', additionalProperties:false,
      properties:{ articles:{type:'integer'}, relations:{type:'integer'} }, required:['articles'] } }
)
return { ...(done || {}) }
