// NER Discovery: 1 agente Haiku por artículo, en paralelo.
// Extrae TODAS las entidades con sus aliases/surface_forms.
// Sin API key: usa el budget de sesión Claude (Max plan).
//
// Uso: Workflow({ script: 'workflows/haiku_ner_discovery.workflow.js',
//                 args: { articles_dir: '...', sample_file: '...', out_dir: '...' } })
//
// Output: data/processed/ner/proto_gazetteer.json + ner_raw.json
export const meta = {
  name: 'haiku-ner-discovery',
  description: 'NER Haiku: extrae entidades + aliases por artículo, agrega proto-gazetteer',
  phases: [
    { title: 'Setup', detail: 'leer IDs y preparar directorio de salida' },
    { title: 'NER', detail: '1 agente Haiku por artículo en paralelo' },
    { title: 'Aggregate', detail: 'fusionar entidades entre artículos → proto-gazetteer' },
  ],
}

const A = (typeof args === 'string')
  ? (() => { try { return JSON.parse(args) } catch { return {} } })()
  : (args || {})

// Paths por defecto (ajustar vía args)
const SAMPLE   = A.sample_file  || 'data/processed/ner/sample.json'
const ART_DIR  = A.articles_dir || 'data/processed/ner/articles'
const OUT_DIR  = A.out_dir      || 'data/processed/ner'
const N_ART    = A.n_art        || 60

const NER_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    article_id: { type: 'string' },
    entities: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          canonical: { type: 'string' },
          type: { type: 'string',
                  enum: ['person','party','institution','coalition','movement','org','location','other'] },
          role: { type: 'string' },
          surface_forms: { type: 'array', items: { type: 'string' } },
        },
        required: ['canonical', 'type', 'surface_forms'],
      },
    },
  },
  required: ['article_id', 'entities'],
}

const NER_PROMPT = `Sos un extractor de entidades para noticias chilenas.
Tu tarea es identificar TODAS las entidades nombradas relevantes en el artículo y sus alias.

INSTRUCCIONES:
1. Extraé TODAS las entidades: personas, partidos, instituciones, coaliciones, movimientos,
   organizaciones, empresas, medios, etc. No filtrés por relevancia política estricta.

2. Para CADA entidad, listá TODAS las formas en que el artículo se refiere a ella:
   - Nombre completo: "Gabriel Boric Font"
   - Nombre corto: "Boric"
   - Cargo/título: "el presidente", "el mandatario"
   - Pronombres contextuales: "el gobierno" cuando claramente refiere al presidente
   - Apodos o variantes

3. Identificá el nombre CANÓNICO (el más completo que aparece en el texto).
4. Tipificá: person / party / institution / coalition / movement / org / location / other
5. Si podés inferir el rol del contexto (ej: "ministro de Hacienda"), incluyelo en "role".

IMPORTANTE: Es mejor incluir de más que de menos — capturá todas las formas superficiales.`

// ── Setup ─────────────────────────────────────────────────────────────────────
phase('Setup')

const setup = await agent(
  `Lee ${SAMPLE} y devolvé la lista de IDs. Asegurate de que el directorio ${OUT_DIR} exista.
Corre: python -c "import json,sys; d=json.load(open('${SAMPLE}')); print(json.dumps({'ids':d['ids'][:${N_ART}],'n':min(${N_ART},len(d['ids']))}))"
Devolvé: { ids: [...], n: int }`,
  {
    label: 'setup', phase: 'Setup', model: 'sonnet',
    schema: {
      type: 'object', additionalProperties: false,
      properties: {
        ids: { type: 'array', items: { type: 'string' } },
        n: { type: 'integer' },
      },
      required: ['ids', 'n'],
    },
  }
)

if (!setup || !setup.ids || setup.ids.length === 0) {
  return { error: 'setup failed — verificá que sample_file existe' }
}
log(`${setup.n} artículos para NER`)

// ── NER paralela ──────────────────────────────────────────────────────────────
phase('NER')

const nerResults = await parallel(
  setup.ids.map(aid => async () => {
    const res = await agent(
      `${NER_PROMPT}

PASO 1: Lee el archivo ${ART_DIR}/${aid}.json — campo "body" es el texto del artículo.
PASO 2: Extraé todas las entidades con sus aliases.
PASO 3: Devolvé {"article_id": "${aid}", "entities": [...]}`,
      { label: `ner:${aid}`, phase: 'NER', model: 'haiku', schema: NER_SCHEMA }
    )
    if (!res) return { article_id: aid, entities: [] }
    return res
  })
)

const valid = nerResults.filter(Boolean)
const total = valid.reduce((s, r) => s + r.entities.length, 0)
log(`NER: ${valid.length} artículos, ${total} menciones de entidades`)

// ── Aggregate ─────────────────────────────────────────────────────────────────
phase('Aggregate')

const aggregated = await agent(
  `Sos un agente de agregación de entidades.
Tenés resultados NER de ${valid.length} artículos. Fusioná entidades equivalentes:
- Criterio conservador: solapamiento claro de surface_forms O canonical de uno contenido en el otro
- Contá n_articles (cuántos artículos mencionan cada entidad)
- Ordená por n_articles descendente
- Devolvé los top-100 más frecuentes

DATOS: ${JSON.stringify(valid, null, 1)}

Devolvé: { gazetteer: [{canonical, type, role, surface_forms, n_articles}...], total_unique: int }`,
  {
    label: 'aggregate', phase: 'Aggregate', model: 'sonnet',
    schema: {
      type: 'object', additionalProperties: false,
      properties: {
        gazetteer: {
          type: 'array',
          items: {
            type: 'object', additionalProperties: false,
            properties: {
              canonical: { type: 'string' },
              type: { type: 'string' },
              role: { type: 'string' },
              surface_forms: { type: 'array', items: { type: 'string' } },
              n_articles: { type: 'integer' },
            },
            required: ['canonical', 'type', 'surface_forms', 'n_articles'],
          },
        },
        total_unique: { type: 'integer' },
      },
      required: ['gazetteer', 'total_unique'],
    },
  }
)

// Guardar
await agent(
  `Guarda:
1. ${OUT_DIR}/ner_raw.json: ${JSON.stringify(valid, null, 2)}
2. ${OUT_DIR}/proto_gazetteer.json: ${JSON.stringify(aggregated, null, 2)}
Confirma con { saved: true }`,
  {
    label: 'save', phase: 'Aggregate', model: 'sonnet',
    schema: { type: 'object', properties: { saved: { type: 'boolean' } }, required: ['saved'] },
  }
)

return {
  n_articles: valid.length,
  total_mentions: total,
  unique_entities: aggregated ? aggregated.total_unique : 0,
  top_10: aggregated ? aggregated.gazetteer.slice(0, 10) : [],
}
