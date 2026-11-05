import os
import threading
import time
from functools import lru_cache


class FinBERT:
    def __init__(self, settings):
        os.environ.setdefault("USE_TF", "0")
        os.environ.setdefault("USE_FLAX", "0")
        import torch
        from transformers import AutoTokenizer, BertModel
        self.settings = settings
        self.device = "cuda" if settings.finbert_device == "auto" and torch.cuda.is_available() else settings.finbert_device
        if self.device == "auto":
            self.device = "cpu"
        if self.device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but unavailable; select cpu or auto")
        self.tokenizer = AutoTokenizer.from_pretrained(settings.finbert_model, revision=settings.finbert_revision)
        self.model = BertModel.from_pretrained(settings.finbert_model, revision=settings.finbert_revision).to(self.device).eval()
        self.revision = getattr(self.model.config, "_commit_hash", None) or settings.finbert_revision
        self.lock = threading.Lock()
        self.encoding_seconds = 0.0

    def encode(self, texts):
        import torch
        import torch.nn.functional as F
        import numpy as np
        if not texts:
            return np.empty((0, self.model.config.hidden_size), dtype="float32")
        started = time.perf_counter()
        batches = []
        with self.lock, torch.inference_mode():
            for offset in range(0, len(texts), self.settings.batch_size):
                inputs = self.tokenizer(texts[offset:offset + self.settings.batch_size], return_tensors="pt",
                    padding=True, truncation=True, max_length=self.settings.token_limit)
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
                hidden = self.model(**inputs).last_hidden_state
                mask = inputs["attention_mask"].unsqueeze(-1).float()
                pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1.0)
                batches.append(F.normalize(pooled, p=2, dim=1).cpu().numpy())
        self.encoding_seconds += time.perf_counter() - started
        return np.concatenate(batches)


@lru_cache(maxsize=4)
def get_finbert(model, revision, device, token_limit, batch_size):
    from ..config.settings import Settings
    return FinBERT(Settings(finbert_model=model, finbert_revision=revision, finbert_device=device,
                            token_limit=token_limit, batch_size=batch_size))
