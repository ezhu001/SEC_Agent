import json
import streamlit as st


def show_result(result):
    status = result["final_status"]
    st.subheader(status)
    if "config" in result:
        mode = "enabled" if result["config"].get("qwen_enabled", True) else "disabled (deterministic rules only)"
        st.caption(f"Qwen agents: {mode}. Decoder calls: {result.get('decoder_call_count', 0)}.")
    if result.get("input_inventory"):
        st.write("Required calculation inputs")
        st.table([{"Component": c["component"], "Fiscal year": c["period"], "Availability": c["status"]}
                  for c in result["input_inventory"]])
    calc = result.get("calculation_result")
    if status == "SUCCESS" and calc:
        st.metric(calc["formula_id"].replace("_", " ").title(), f"{calc['value']:.6g} {calc['unit']}")
        st.write(calc["formula"])
        st.json(calc["inputs"])
        if calc.get("comparison"):
            comparison = calc["comparison"]
            st.write(f"{comparison['old_period']}: {comparison['old_value']:.6g} → {comparison['new_period']}: {comparison['new_value']:.6g} {comparison.get('period_value_unit', '')}")
            st.write(f"Absolute change: {comparison['absolute_change']:.6g} {comparison.get('absolute_change_unit', '')} ({comparison['direction']})")
            relative = comparison.get("relative_change_percent")
            if relative is not None:
                st.write(f"Relative change: {relative:.6g}%")
            elif comparison.get("relative_change_note"):
                st.caption(comparison["relative_change_note"])
        st.caption("All values, differences and comparisons above were computed by the registered Python calculator; the decoder did not perform arithmetic.")
    for warning in result["warnings"]:
        st.info(warning)
    if status != "SUCCESS":
        for error in result["errors"]:
            st.error(f"{error['node']}: {error['message']}")
    st.write("Filing", result["filing_metadata"])
    evidence = result.get("final_response", {}).get("evidence", {})
    for component, row in evidence.items():
        st.write(f"**{component.replace('_', ' ').title()}: {row['label']}**")
        st.caption(f"Table {row['table']}, row {row['row']} · {row['evidence_id']}")
        st.write(row["text"])
    panels = {
        "Task plan": result.get("task_plan"),
        "Required inputs by component and year": result.get("input_inventory", []),
        "Retrieval candidates and signals": result["retrieval_results"],
        "Retrieval diagnostics": result["retrieval_diagnostics"],
        "Evidence sufficiency": result["evidence_sufficiency"],
        "Verification": result["verification_results"],
        "Correction and expanded search": {"corrections": result["correction_results"], "expansions": result["expanded_search_count"]},
        "Deterministic guards": result["guard_results"],
        "Calculation details": calc,
        "Timings and runtime": {"timings": result["timings"], "decoder_calls": result["decoder_call_count"], "models": result["model_versions"]},
        "Warnings and errors": {"warnings": result["warnings"], "errors": result["errors"]},
    }
    for title, value in panels.items():
        with st.expander(title):
            st.json(value)
    st.download_button("Download audit state", json.dumps(result, indent=2), file_name=result["request_id"] + ".json", mime="application/json")
    if result.get("audit_complete", True) and result.get("audit_path"):
        st.caption("Complete model call audit saved at " + result["audit_path"])
    else:
        st.error("Audit persistence failed. This run is an operational ERROR; the downloadable state contains the original failure.")
        if result.get("audit_path"):
            st.caption("Last saved partial audit: " + result["audit_path"])
