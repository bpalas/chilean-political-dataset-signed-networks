"""
Pipeline de creación del dataset Chilean Political Signed Networks.

Módulos:
  corpus_data   — ingesta y dedup del corpus raw (DuckDB + Parquet)
  topic_model   — modelado de tópicos (BERTopic)
  ner           — detección de entidades y aliases (LLM-based)
  er            — entity resolution: gazetteer + rapidfuzz + Splink
"""
