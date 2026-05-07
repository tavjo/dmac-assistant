// T5 — BAML codegen target for the dmac-assistant E2E judge.
//
// `baml-cli generate --from /app/tools/e2e/baml_src` writes the generated
// client into `<output_dir>/baml_client/`. We want the artifact at
// `/app/tools/e2e/baml_client/`, which is a sibling of `baml_src/`, so
// output_dir is "../" (relative to baml_src/).

generator target {
    output_type "python/pydantic"
    output_dir "../"
    version "0.222.0"
    default_client_mode sync
}
