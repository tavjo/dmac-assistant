retry_policy Exponential {
  max_retries 2
  strategy {
    type exponential_backoff
    delay_ms 300
    multiplier 1.5
    max_delay_ms 10000
  }
}

client<llm> GCPReasoner {
  provider google-ai
  retry_policy Exponential
  options {
    model "gemini-3.1-pro-preview"
    api_key env.GCP_API_KEY
  }
}
