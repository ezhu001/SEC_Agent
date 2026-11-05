import time
from .lexical_retriever import lexical_signals
from .finbert_retriever import EmbeddingCache
from ..config.financial_concepts import CONCEPTS


class HybridRetriever:
    def __init__(self, encoder_provider, settings):
        self.provider, self.settings = encoder_provider, settings
        self.cache = EmbeddingCache(settings)

    def rank(self, rows, component, periods, query):
        if not rows:
            return [], {"candidate_count": 0, "top_1": None, "top_2": None, "margin": None}
        started = time.perf_counter()
        encoder = self.provider()
        model_load_seconds = time.perf_counter() - started
        before_encoding = encoder.encoding_seconds
        vectors = self.cache.encode_rows(encoder, rows)
        q = encoder.encode([query])[0]
        scores = vectors @ q
        ranked = []
        for row, score in zip(rows, scores):
            lexical, exact, xbrl = lexical_signals(row, component)
            signals = {"finbert": float(score), "lexical": lexical, "exact_label": exact, "xbrl": xbrl,
                "statement": row.statement == CONCEPTS[component][0],
                "periods": all(sum(f.period == p for f in row.facts) == 1 for p in periods),
                "numeric": bool(row.facts)}
            fusion = self.settings.semantic_weight * float(score) + self.settings.lexical_weight * lexical + self.settings.xbrl_weight * int(xbrl)
            ranked.append({"evidence_id": row.evidence_id, "label": row.label, "signals": signals, "fusion_score": fusion})
        ranked.sort(key=lambda r: (-r["fusion_score"], r["evidence_id"]))
        top = ranked[0]["fusion_score"]
        second = ranked[1]["fusion_score"] if len(ranked) > 1 else None
        semantic_order = sorted(ranked, key=lambda r: -r["signals"]["finbert"])
        lexical_order = sorted(ranked, key=lambda r: -r["signals"]["lexical"])
        return ranked, {"candidate_count": len(rows), "top_1": top, "top_2": second,
            "margin": top - second if second is not None else None, "seconds": time.perf_counter() - started,
            "top_1_finbert": semantic_order[0]["signals"]["finbert"],
            "top_2_finbert": semantic_order[1]["signals"]["finbert"] if len(ranked) > 1 else None,
            "semantic_lexical_top_agreement": semantic_order[0]["evidence_id"] == lexical_order[0]["evidence_id"],
            "statement_available": any(r["signals"]["statement"] for r in ranked),
            "period_available": any(r["signals"]["periods"] for r in ranked),
            "lexical_support": any(r["signals"]["exact_label"] for r in ranked),
            "xbrl_support": any(r["signals"]["xbrl"] for r in ranked),
            "finbert_device": encoder.device, "finbert_revision": encoder.revision,
            "encoding_seconds_cumulative": encoder.encoding_seconds,
            "encoding_seconds": encoder.encoding_seconds - before_encoding,
            "model_load_seconds": model_load_seconds, "embedding_cache": self.cache.last_stats}
