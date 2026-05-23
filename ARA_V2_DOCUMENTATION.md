# Ara v2 — Asistente Conversacional de Ruta Viva

## Overview

Ara v2 es la segunda generación del asistente conversacional de Ruta Viva. Reemplaza el sistema monolítico de v1 (2376 líneas de handlers hardcodeados) por una arquitectura modular basada en:

1. **Comprensión semántica** (GPT-4o-mini) — entiende la intención del usuario en lenguaje natural.
2. **Memoria persistente** (embeddings en PostgreSQL) — recuerda preferencias y restricciones del usuario entre sesiones.
3. **Orquestación de herramientas** — ejecuta search_pois, get_weather, build_itinerary, answer_question, suggest_replacement según la intención detectada.
4. **Respuestas naturales** (GPT-4o-mini) — genera texto contextual con quick replies solo cuando hay decisiones puntuales.

## Arquitectura

```
Usuario → Endpoint HTTP → ConversationProcessor
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              MemoryService    Comprensor    ToolOrchestrator
              (recuperar)    (GPT-4o-mini)   (ejecutar tools)
                    │               │               │
                    ▼               ▼               ▼
              conversation_   Comprehension   ToolExecution
              memory table      Result          Result
                                    │
                                    ▼
                          ResponseGenerator
                          (GPT-4o-mini + fallbacks)
                                    │
                                    ▼
                          AraSessionResponse
```

## Nuevos Servicios (app/services/ara_v2/)

| Archivo | Responsabilidad |
|---------|----------------|
| `comprehender.py` | Wrapper de GPT-4o-mini para comprensión de intención. JSON schema estricto. Fallback a reglas simples. |
| `comprehension_fallback.py` | Reglas simples para cuando GPT-4o-mini falla. Detecta destinos, intenciones, fechas, preferencias. |
| `conversation_processor.py` | Orquesta el flujo completo: memoria → comprensor → guardar hechos → herramientas → respuesta. |
| `memory_service.py` | CRUD de memoria semántica con embeddings. Aislamiento estricto por tourist_id. Actualiza TouristProfile. |
| `prompt_manager.py` | Construye prompts parametrizados por capas. Templates para comprensión, generación y respuesta. |
| `response_generator.py` | Genera respuestas naturales con GPT-4o-mini. Fallbacks estructurados por topic. Quick replies contextuales. |
| `tool_orchestrator.py` | Ejecuta herramientas según ComprehensionResult. Paralelo (search_pois + get_weather) y secuencial (build_itinerary). |
| `answer_service.py` | RAG sobre descripciones de POIs para responder preguntas puntuales. Evidence level tracking. |
| `utils.py` | Helper get_gpt_mini_client() para GPT-4o-mini. |

## Migración: Qué se eliminó de v1 y por qué

| Archivo v1 | Reemplazado por | Razón |
|-----------|----------------|-------|
| `ara_turn_classifier.py` | `comprehender.py` | Clasificación por reglas → comprensión semántica con LLM |
| `ara_preference_merger.py` | `memory_service.py` | Merge de preferencias en dict → memoria semántica con embeddings |
| `ara_response_builder.py` | `response_generator.py` | Quick replies hardcodeados → respuestas naturales con GPT-4o-mini |
| `ara_constants.py` | Varios | Términos hardcodeados → config DB + servicios específicos |

## Contratos HTTP

**NO CAMBIARON.** El frontend no se entera de la migración.

| Endpoint | Método | Request | Response |
|----------|--------|---------|----------|
| `/api/v1/ara/sessions` | POST | `AraSessionCreate` | `AraSessionResponse` |
| `/api/v1/ara/sessions/{id}/messages` | POST | `AraMessageCreate` | `AraSessionResponse` |
| `/api/v1/ara/sessions/{id}/generate-itinerary` | POST | `AraGenerateItineraryRequest` | `AraGenerateItineraryResponse` |
| `/api/v1/ara/sessions/{id}/generate-itinerary/stream` | POST | `AraGenerateItineraryRequest` | `text/event-stream` |

## Flujo de Conversación

### Paso 1: Recuperar memoria
- `MemoryService.retrieve_relevant_facts(db, tourist_id, user_message, top_k=5)`
- Busca hechos semánticamente relevantes en `conversation_memory` table.
- Aislamiento estricto: solo hechos del mismo tourist_id.

### Paso 2: Comprender
- `Comprensor.comprehend(user_message, session_messages, relevant_facts, trip_draft, candidate_pois_count)`
- Llama GPT-4o-mini con JSON schema estricto.
- Si falla → fallback a reglas simples.
- Devuelve `ComprehensionResult` con: intenciones, entidades, herramientas necesarias, preguntas pendientes, actualizaciones de memoria.

### Paso 3: Guardar hechos
- Itera `actualizaciones_memoria` del ComprehensionResult.
- `MemoryService.store_fact(db, tourist_id, session_id, hecho, categoria, confianza)`
- Genera embedding automáticamente. Si falla, guarda sin embedding.

### Paso 4: Actualizar perfil
- Si `categoria == "preferencia"` y `confianza > 0.8` → `MemoryService.update_tourist_profile_embedding()`
- Media móvil exponencial: 90% perfil actual + 10% nuevo hecho.

### Paso 5: Ejecutar herramientas
- `ToolOrchestrator.execute(comprehension, session, user, db)`
- Paralelo: search_pois + get_weather
- Secuencial: build_itinerary, suggest_replacement, answer_question

### Paso 6: Generar respuesta
- `ResponseGenerator.generate_response(comprehension, tool_result, session)`
- GPT-4o-mini con system prompt contextual (tono, destino, fechas, alojamiento, preferencias).
- Si falla → fallback por topic.
- Quick replies solo en decisiones puntuales.

### Paso 7: Persistir y retornar
- Guarda mensajes de usuario y asistente en DB.
- Retorna `AraSessionResponse` con assistant_message, quick_replies, candidate_pois, weather.

## Configuración

### Variables de entorno
| Variable | Default | Descripción |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | API key de OpenAI (embeddings + GPT-4o-mini) |
| `DEEPSEEK_API_KEY` | — | API key de DeepSeek (generación de itinerarios) |
| `OPENWEATHER_API_KEY` | — | API key de OpenWeatherMap (pronóstico) |
| `OPENAI_GPT_MINI_MODEL` | `gpt-4o-mini` | Modelo para comprensión y respuestas |
| `GPT_MINI_TIMEOUT_SECONDS` | `10.0` | Timeout para GPT-4o-mini |

## Tests

### Unitarios (tests/unit/ara_v2/)
- `test_memory_service.py` — 6 tests (store, retrieve, isolation, summary)
- `test_prompt_manager.py` — 12 tests (comprehension, generation, answer prompts)
- `test_comprehender.py` — 26 tests (fallback intentions, entities, memory, edge cases, mocks)
- `test_memory_integration.py` — 8 tests (store from comprehension, cross-turns, isolation, profile update, failure handling)
- `test_tool_orchestrator.py` — 10 tests (search, weather, itinerary, answer, replacement, parallel, failure)
- `test_response_generator.py` — 14 tests (itinerary, search, answer, clarify, replace, error, quick replies, fallbacks)

### E2E (tests/e2e/)
- `test_ara_v2_flow.py` — 8 tests (create session, generate itinerary, search POIs, answer question, memory persistence, quick replies, replacement, streaming)

**Total: 84 tests de Ara v2 + 64 tests existentes = 148 tests totales.**
