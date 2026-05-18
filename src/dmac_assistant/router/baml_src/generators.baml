// T1.1 — BAML codegen target for the bridge-side LLM router.
//
// `baml-cli generate --from src/dmac_assistant/router/baml_src` writes the
// generated client into `<output_dir>/baml_client/`. We want the artifact at
// `src/dmac_assistant/router/baml_client/`, which is a sibling of
// `baml_src/`, so output_dir is "../" (relative to baml_src/).
//
// Version aligned with tools/e2e/baml_src/generators.baml so the bridge and
// the e2e judge share the same baml_py runtime. Distinct from
// vendor/chat_nextseek/.../baml_src/generators.baml (pins 0.221.0 for the
// in-container Python 3.14 runtime).

generator target {
    output_type "python/pydantic"
    output_dir "../"
    version "0.222.0"
    default_client_mode async
}
