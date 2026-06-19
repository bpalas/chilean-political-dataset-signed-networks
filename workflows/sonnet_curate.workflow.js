// Curación del top-grado con Sonnet — corrige canonical/tipo y detecta merges.
// Determinístico salvo este paso: Sonnet razona sobre los actores frecuentes (el núcleo
// del grafo) que cubren ~80% del volumen. La aplicación a la DB es determinística (apply).
//
// Requiere: data/processed/curation/top_nodes.json (scripts/build_graph + extract).
// Uso: Workflow({ script:'workflows/sonnet_curate.workflow.js' })
// Salida: data/processed/curation/curations.json → luego: python scripts/curate_apply.py
export const meta = {
  name: 'sonnet-curate',
  description: 'Cura el top-grado de nodos con Sonnet: canonical Title Case, tipo correcto, merges (siglas↔nombre, duplicados), marca genéricos',
  phases: [{ title: 'Curate', detail: 'Sonnet revisa el top-N de actores' }],
}

const DIR = 'data/processed/curation'
const TYPES = ['person','party','institution','coalition','movement','org','other']

const SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    curations: { type: 'array', items: {
      type: 'object', additionalProperties: false,
      properties: {
        node_id:    { type: 'string' },
        canonical:  { type: 'string' },                 // nombre correcto, Title Case
        type:       { type: 'string', enum: TYPES },
        merge_into: { type: 'string' },                 // node_id del representante (o el propio si único)
        is_generic: { type: 'boolean' },                // genérico no-actor (acuerdo, Estado...)
      },
      required: ['node_id','canonical','type','merge_into','is_generic'],
    } },
  },
  required: ['curations'],
}

phase('Curate')
const res = await agent(
  `Sos un curador experto de un grafo de actores políticos chilenos (2019-2022).
Leé ${DIR}/top_nodes.json: una lista de actores, cada uno con node_id, canonical actual,
type, n_mentions y aliases (formas en que aparece en las noticias).

Para CADA actor devolvé un objeto con:
- node_id: el mismo.
- canonical: el nombre CANÓNICO correcto, en Title Case y bien escrito. Corregí typos
  ("sebastián piñera"→"Sebastián Piñera") y canonicals mal asignados (si los aliases dicen
  CONGRESO, el canonical es "Congreso Nacional", no "Senado").
- type: person|party|institution|coalition|movement|org|other (corregí si está mal).
- merge_into: si este actor es EL MISMO que otro de la lista (sigla vs nombre como
  DC↔Democracia Cristiana, UDI↔Unión Demócrata Independiente, RN↔Renovación Nacional; o
  nodos duplicados como dos "Renovación Nacional", "Piñera"↔"Sebastián Piñera"), poné el
  node_id del representante (elegí el de MAYOR n_mentions del grupo). Si es único, poné su
  propio node_id.
- is_generic: true si es un genérico que NO es un actor nombrado ("acuerdo", "Estado",
  "Presidente"/"Ejecutivo" sin nombre propio). Esos no se mergean; solo se marcan.

Reglas: NUNCA mergees dos PERSONAS distintas ni tipos distintos (un partido ≠ una persona).
Ante la duda, no mergees (merge_into = su propio node_id).

Devolvé {"curations":[...]} con UNA entrada por actor de la lista.`,
  { label: 'curate', phase: 'Curate', model: 'sonnet', schema: SCHEMA }
)

if (!res || !res.curations) return { error: 'curación vacía' }

await agent(
  `Guardá la curación. Corré:

python - <<'PY'
import json
cur = ${JSON.stringify(res.curations ? { curations: res.curations } : {})}
json.dump(cur["curations"], open("${DIR}/curations.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
merges = sum(1 for c in cur["curations"] if c["merge_into"] != c["node_id"])
gen = sum(1 for c in cur["curations"] if c["is_generic"])
print(json.dumps({"curated": len(cur["curations"]), "merges": merges, "generics": gen}))
PY`,
  { label: 'save', phase: 'Curate', model: 'sonnet',
    schema: { type:'object', additionalProperties:false,
      properties:{ curated:{type:'integer'}, merges:{type:'integer'}, generics:{type:'integer'} }, required:['curated'] } }
)

return { curated: res.curations.length }
