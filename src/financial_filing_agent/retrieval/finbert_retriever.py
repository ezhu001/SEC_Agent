import json
import numpy as np
from ..services.cache import digest, atomic_json


class EmbeddingCache:
    def __init__(self, settings):
        self.settings = settings
        self.last_stats = {}

    def encode_rows(self, encoder, rows):
        vectors, missing, keys = {}, [], {}
        for row in rows:
            key = digest(json.dumps({"filing": row.filing_hash, "parser": self.settings.parser_version,
                "model": self.settings.finbert_model, "revision": encoder.revision,
                "tokenizer": self.settings.finbert_model, "preprocessing": "masked-mean-l2-v1",
                "max_length": self.settings.token_limit, "text_hash": digest(row.text)}, sort_keys=True))
            path = self.settings.artifact_dir / "embeddings" / (key + ".json")
            keys[row.evidence_id] = path
            if path.exists():
                vectors[row.evidence_id] = np.asarray(json.loads(path.read_text(encoding="utf-8")), dtype="float32")
            else:
                missing.append(row)
        if missing:
            for row, vector in zip(missing, encoder.encode([r.text for r in missing])):
                vectors[row.evidence_id] = vector
                atomic_json(keys[row.evidence_id], vector.tolist())
        self.last_stats = {"encoded_rows": len(missing), "cache_hits": len(rows) - len(missing)}
        return np.stack([vectors[r.evidence_id] for r in rows]) if rows else np.empty((0, 0))
