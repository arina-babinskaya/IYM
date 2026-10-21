#!/usr/bin/env bash
set -euo pipefail

HOST="${OLLAMA_HOST:-http://localhost:11434}"
LLM="${RC_LLM_MODEL:-qwen2.5:14b-instruct-q4_K_M}"
EMB="${RC_EMBED_MODEL:-bge-m3}"

ollama pull "$LLM"
ollama pull "$EMB"

echo "--- прогрев и проверка ---"
time curl -s "$HOST/api/chat" -d "{\"model\":\"$LLM\",\"stream\":false,\"keep_alive\":\"24h\",
  \"format\":{\"type\":\"object\",\"properties\":{\"room\":{\"type\":\"string\"},\"area\":{\"type\":\"number\"}},\"required\":[\"room\",\"area\"]},
  \"messages\":[{\"role\":\"user\",\"content\":\"Ванная 2 на 3 метра. Верни JSON.\"}]}" | head -c 400; echo
time curl -s "$HOST/api/embed" -d "{\"model\":\"$EMB\",\"input\":[\"ламинат 33 класс\"],\"keep_alive\":\"24h\"}" | head -c 120; echo
ollama ps
