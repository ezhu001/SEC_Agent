import streamlit as st
from ..config.settings import Settings
from ..models.local_decoder import OllamaDecoder
from ..services.pipeline import Pipeline
from ..services.cache import digest
from .components import show_result
from ..config.formulas import FORMULAS
from ..config.prompts import VERIFIER, CORRECTOR, PLANNER
from ..schemas.results import Verification


def main():
    st.set_page_config(page_title="Financial filing evidence", layout="wide")
    settings = Settings()
    st.title("Financial filing evidence")
    st.write("Ask a supported financial question about an SEC filing. Review the source rows, verification, and deterministic calculation.")
    with st.sidebar:
        st.header("Local runtime")
        qwen_enabled = st.checkbox("Enable Qwen agents", value=settings.qwen_enabled)
        settings = settings.model_copy(update={"qwen_enabled": qwen_enabled})
        st.caption("Qwen ON: model planning/review/recovery where needed. Qwen OFF: choose a metric and fiscal years; use deterministic concept checks. FinBERT retrieval remains enabled.")
        st.caption("Mode changes apply to the next run. Saved results display the mode used for that run.")
        with st.expander("Qwen responsibilities and actual prompts"):
            st.write("Planner maps free text to registered formulas. Verifier reviews one row under a bounded contract. Corrector can choose existing supplied rows within a fixed budget. None can calculate, invent facts, change formulas or add required checks.")
            st.write("The decoder's response is a proposal validated by Python, not executable authority. A prompt alone cannot guarantee model correctness.")
            st.write("Actual verifier system prompt")
            st.code(VERIFIER, language="text")
            st.write("General verifier schema. Each request further restricts check names to open_checks and requires exactly one cited result per open check; the run's contract is shown in Verification.")
            st.json(Verification.model_json_schema())
            st.write("Planner prompt")
            st.code(PLANNER, language="text")
            st.write("Recovery prompt")
            st.code(CORRECTOR, language="text")
        st.write("Decoder", settings.decoder_model)
        st.write("FinBERT", settings.finbert_model)
        st.write("Device selection", settings.finbert_device)
        if st.button("Check Ollama status", disabled=not qwen_enabled):
            st.session_state.runtime_status = OllamaDecoder(settings).status()
        if qwen_enabled and "runtime_status" in st.session_state:
            st.json(st.session_state.runtime_status)
        debug = st.checkbox("Debug configuration")
        if debug:
            st.json(settings.model_dump(mode="json"))
        st.caption("Ollama manages decoder GPU allocation. FinBERT uses CUDA when available under auto.")
    formula_id = st.selectbox("Financial metric / calculation", ["From question"] + list(FORMULAS),
                             format_func=lambda key: key.replace("_", " ").title())
    if formula_id != "From question":
        spec = FORMULAS[formula_id]
        st.caption(f"Formula: {spec.description}. Required components: {', '.join(spec.components)}. Required years: {spec.periods}. Python calculates and compares the results.")
    with st.form("analysis"):
        source = st.text_input("SEC ticker / CIK / accession, SEC URL, or cached local HTML path", placeholder="AAPL or AAPL/0000320193-25-000079")
        upload = st.file_uploader("Or upload SEC HTML", type=["html", "htm"])
        question = st.text_area("Financial question", placeholder="How did total revenue change from FY2024 to FY2025?")
        period_text = st.text_input("Explicit fiscal periods (optional)", placeholder="FY2025 FY2024")
        supporting_uploads = st.file_uploader("Supporting same-company filings (optional)", type=["html", "htm"], accept_multiple_files=True)
        use_cache = st.checkbox("Search cached same-company filings for missing years", value=False)
        submitted = st.form_submit_button("Run Analysis", type="primary")
    if submitted:
        st.session_state.pop("result", None)
        st.session_state.execution_steps = []
        if upload:
            raw = upload.getvalue()
            path = settings.artifact_dir / "uploads" / (digest(raw) + ".html")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            source = str(path.resolve())
        supporting_sources = []
        for supporting in supporting_uploads or []:
            raw = supporting.getvalue()
            path = settings.artifact_dir / "uploads" / (digest(raw) + ".html")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            supporting_sources.append(str(path.resolve()))
        with st.status("Starting analysis…", expanded=True) as progress:
            def update_progress(event):
                st.session_state.execution_steps.append(event)
                component = f" — {event['component']}" if event.get("component") else ""
                if event["phase"] == "started":
                    progress.update(label=event["label"] + component, state="running")
                    progress.write("⏳ " + event["label"] + component)
                else:
                    marker = "✗" if event.get("status") == "ERROR" else "✓"
                    progress.write(f"{marker} {event['label']} ({event['seconds']:.1f}s)" +
                                   (" — " + event["detail"] if event["detail"] else ""))
            result = Pipeline(settings).run(question, source, period_text.split() or None, on_progress=update_progress,
                      formula_id=None if formula_id == "From question" else formula_id,
                      supplementary_sources=supporting_sources, use_cached_filings=use_cache)
            st.session_state.result = result
            progress.update(label="Analysis: " + result["final_status"],
                            state="error" if result["final_status"] == "ERROR" else "complete", expanded=True)
    elif st.session_state.get("execution_steps"):
        with st.expander("Execution steps"):
            for step in st.session_state.execution_steps:
                if step["phase"] == "completed":
                    st.write(f"{step['label']} ({step['seconds']:.1f}s) — {step['detail']}")
    if "result" in st.session_state:
        show_result(st.session_state.result)


if __name__ == "__main__":
    main()
