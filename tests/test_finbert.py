import numpy as np
import pytest
from financial_filing_agent.config.settings import Settings
from financial_filing_agent.models.finbert import get_finbert
from financial_filing_agent.retrieval.finbert_retriever import EmbeddingCache
from financial_filing_agent.schemas.evidence import EvidenceRow


def test_embedding_cache_reuses_rows(tmp_path):
    class Encoder:
        revision = "frozen-revision"
        def __init__(self):
            self.calls = []
        def encode(self, texts):
            self.calls.append(texts)
            return np.asarray([[1.0, 0.0] for t in texts], dtype="float32")
    encoder = Encoder()
    row = EvidenceRow(evidence_id="r", filing_hash="f", source="test", statement="operations", table=0, row=0, label="revenue", text="Revenue | 100")
    cache = EmbeddingCache(Settings(artifact_dir=tmp_path))
    first = cache.encode_rows(encoder, [row])
    second = cache.encode_rows(encoder, [row])
    assert np.array_equal(first, second)
    assert len(encoder.calls) == 1
    row.text += " changed"
    cache.encode_rows(encoder, [row])
    assert len(encoder.calls) == 2


@pytest.mark.live
def test_real_finbert_cpu_pooling_parity():
    import os
    if os.environ.get("FFA_RUN_LIVE") != "1":
        pytest.skip("Set FFA_RUN_LIVE=1 with cached FinBERT")
    import torch
    import torch.nn.functional as F
    model = get_finbert("yiyanghkust/finbert-pretrain", "88ab954a39ea6d3ce2b62cff086dd5ad1172c664", "cpu", 256, 4)
    assert model is get_finbert("yiyanghkust/finbert-pretrain", "88ab954a39ea6d3ce2b62cff086dd5ad1172c664", "cpu", 256, 4)
    texts = ["total net sales company revenue", "Total net sales | 416161 | 391035 | 383285", "Total cost of sales | 220960 | 210352 | 214137"]
    actual = model.encode(texts)
    expected = []
    for text in texts:
        inputs = model.tokenizer(text, return_tensors="pt", truncation=True, max_length=256)
        with torch.no_grad():
            hidden = model.model(**inputs).last_hidden_state
        mask = inputs["attention_mask"].unsqueeze(-1).float()
        expected.append(F.normalize((hidden * mask).sum(1) / mask.sum(1).clamp(min=1), p=2, dim=1).numpy()[0])
    assert actual.shape == (3, 768)
    assert np.allclose(actual, expected, atol=2e-6)
    assert np.allclose(np.linalg.norm(actual, axis=1), 1, atol=1e-6)
    scores = actual[1:] @ actual[0]
    assert scores[1] > scores[0]  # preserved notebook failure, not tuned away
    assert scores.tolist() == pytest.approx([0.5112578, 0.5349339], abs=2e-5)


@pytest.mark.live
def test_cuda_when_available():
    import os
    if os.environ.get("FFA_RUN_LIVE") != "1":
        pytest.skip("Live model test")
    import torch
    if not torch.cuda.is_available():
        pytest.skip("CUDA unavailable; CPU correctness tested separately")
    model = get_finbert("yiyanghkust/finbert-pretrain", "88ab954a39ea6d3ce2b62cff086dd5ad1172c664", "cuda", 256, 4)
    assert model.encode(["revenue"]).shape == (1, 768)
    assert model.device == "cuda"
