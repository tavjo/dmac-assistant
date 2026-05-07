// T5 — Gemini/GCP client binding for the JudgeUITranscript function.
// Mirrors chat_nextseek's evaluator GCP client pattern (provider google-ai,
// api_key sourced from env.GCP_API_KEY).

retry_policy Exponential {
  max_retries 2
  strategy {
    type exponential_backoff
    delay_ms 300
    multiplier 1.5
    max_delay_ms 10000
  }
}

client<llm> GCPGemini {
  provider google-ai
  retry_policy Exponential
  options {
    model "gemini-2.0-pro-exp"
    api_key env.GCP_API_KEY
  }
}
