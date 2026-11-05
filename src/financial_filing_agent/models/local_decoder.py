import json
import copy
import time
from datetime import datetime, timezone
import requests


class DecoderError(RuntimeError):
    pass


class OllamaDecoder:
    def __init__(self, settings):
        self.settings = settings
        self.calls = []
        self.version = {"name": settings.decoder_model, "digest": None}

    def status(self):
        try:
            tags = requests.get(self.settings.ollama_url + "/api/tags", timeout=3)
            tags.raise_for_status()
            models = tags.json().get("models", [])
            match = next((m for m in models if m["name"] == self.settings.decoder_model), None)
            if match:
                self.version["digest"] = match.get("digest")
            result = {"available": bool(match), "server_available": True, "model": self.settings.decoder_model,
                      "digest": self.version["digest"], "gpu": "unknown (model not resident or diagnostics unavailable)"}
            try:
                ps = requests.get(self.settings.ollama_url + "/api/ps", timeout=3)
                ps.raise_for_status()
                resident = next((m for m in ps.json().get("models", []) if m["name"] == self.settings.decoder_model), None)
                if resident:
                    result["gpu"] = {"size_vram": resident.get("size_vram"), "size": resident.get("size"),
                                     "note": "Resident VRAM allocation; not a guarantee of full GPU execution"}
            except requests.RequestException:
                pass
            return result
        except requests.RequestException as exc:
            return {"available": False, "server_available": False, "model": self.settings.decoder_model, "error": str(exc), "gpu": "unknown"}

    def complete(self, role, system, payload, schema):
        if self.settings.expected_decoder_digest and self.version["digest"] is None:
            self.runtime_status = self.status()
            if self.version["digest"] != self.settings.expected_decoder_digest:
                raise DecoderError("Decoder digest does not match the frozen research configuration")
        if len(json.dumps(payload)) + len(system) > self.settings.decoder_context * 2:
            raise DecoderError("Decoder payload exceeds conservative context budget; narrow candidate scope")
        request = {"model": self.settings.decoder_model, "stream": False,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                   "format": schema.model_json_schema(), "options": {"temperature": self.settings.temperature,
                       "num_ctx": self.settings.decoder_context, "num_predict": self.settings.decoder_output_tokens}}
        for attempt in range(self.settings.transport_retries + 1):
            started = time.perf_counter()
            event = {"role": role, "attempt": attempt, "timestamp": datetime.now(timezone.utc).isoformat(),
                     "request": copy.deepcopy(request)}
            try:
                response = requests.post(self.settings.ollama_url + "/api/chat", json=request, timeout=self.settings.decoder_timeout)
                response.raise_for_status()
                data = response.json()
                raw = data["message"]["content"]
                event["raw_output"] = raw
                result = schema.model_validate_json(raw)
                event["output"] = result.model_dump(mode="json")
                event["runtime"] = {k: data.get(k) for k in ("total_duration", "load_duration", "prompt_eval_count", "eval_count")}
                if self.version["digest"] is None:
                    self.runtime_status = self.status()
                return result
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                event["error"] = str(exc)
                if attempt == self.settings.transport_retries:
                    raise DecoderError(f"{role} call failed: {exc}") from exc
                # A retry includes the validation feedback so a schema-valid but
                # semantically invalid first response is not repeated blindly.
                request["messages"] = request["messages"][:2] + [{"role": "user", "content": "Previous output failed validation. Return a corrected object only. Validation: " + str(exc)[:1500]}]
            finally:
                event["seconds"] = time.perf_counter() - started
                self.calls.append(event)
        raise DecoderError("Decoder retry budget exhausted")
