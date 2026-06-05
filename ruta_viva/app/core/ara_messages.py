from __future__ import annotations

from typing import ClassVar


class AraMessages:
    _default_lang: ClassVar[str] = "es"

    _messages: ClassVar[dict[str, dict[str, str]]] = {
        "es": {
            # ============================================================
            # Intent base & question (build_assistant_message)
            # ============================================================
            "assistant_surprise_base": (
                "Perfecto, puedo encargarme de equilibrar alojamiento, "
                "comidas y actividades"
            ),
            "assistant_surprise_question": (
                "Si quieres, puedo crear el itinerario con lo acordado "
                "o seguimos afinando algún detalle."
            ),
            "assistant_alojamiento_base": (
                "Perfecto, buscaremos alojamiento como base del viaje"
            ),
            "assistant_alojamiento_question": (
                "Te dejo opciones visuales si hay alternativas; "
                "luego podemos sumar comidas y actividades cercanas."
            ),
            "assistant_gastronomia_completed_base": (
                "Perfecto, dejamos la comida encaminada"
            ),
            "assistant_gastronomia_completed_question": (
                "Ahora conviene equilibrar el viaje con naturaleza, "
                "cultura, descanso o alguna actividad distinta."
            ),
            "assistant_gastronomia_specific_base": (
                "Perfecto, ya sé qué tipo de comida buscas"
            ),
            "assistant_gastronomia_specific_question": (
                "Te dejo opciones en las tarjetas. Después podemos sumar "
                "actividades para que la ruta no quede centrada solo en comida."
            ),
            "assistant_gastronomia_base": (
                "Perfecto, podemos buscar algo rico para comer"
            ),
            "assistant_gastronomia_question": (
                "¿Quieres comida local, pizza, café, vista o algo rápido?"
            ),
            "assistant_naturaleza_specific_base": (
                "Perfecto, ya tengo una idea clara del panorama natural "
                "que buscas"
            ),
            "assistant_naturaleza_specific_question": (
                "Puedo afinar por dificultad, horario, cercanía "
                "o combinarlo con una pausa para comer."
            ),
            "assistant_naturaleza_base": (
                "Podemos armar una salida con naturaleza y buenos paisajes"
            ),
            "assistant_naturaleza_question": (
                "¿Te interesan más senderos, miradores, lagos "
                "o actividades suaves?"
            ),
            "assistant_cultura_base": (
                "Podemos orientar el recorrido hacia cultura local, "
                "historia y patrimonio"
            ),
            "assistant_cultura_question": (
                "¿Quieres algo más histórico, mapuche, artesanal o urbano?"
            ),
            "assistant_descanso_base": (
                "Puedo armar algo más relajado, con menos traslados "
                "y mejores pausas"
            ),
            "assistant_descanso_question": (
                "¿Quieres termas, naturaleza suave o una ruta tranquila "
                "con comida?"
            ),
            "assistant_exploracion_base": (
                "Cuéntame qué tipo de experiencia te gustaría priorizar"
            ),
            "assistant_exploracion_question": (
                "¿Qué tipo de experiencia quieres priorizar: naturaleza, "
                "comida, cultura o descanso?"
            ),

            # — suffixes (conditional) —
            "assistant_poi_suffix": ". Te dejo opciones visuales en las tarjetas",
            "assistant_tags_suffix": ". Tomaré en cuenta: {tags}",
            "assistant_auto_generate_prefix": (
                "Perfecto, puedo encargarme de todo con una ruta "
                "equilibrada. {base}"
            ),

            # ============================================================
            # Generate request messages
            # ============================================================
            "generate_surprise": (
                "Listo, puedo armar una ruta sorpresa equilibrada "
                "con lo que ya conversamos. No la voy a limitar a una sola "
                "categoría: combinaré alojamiento, comidas, actividades, "
                "pausas y lugares cercanos según tus fechas y ubicación."
            ),
            "generate_normal": (
                "Listo, puedo crear el itinerario con lo que ya acordamos. "
                "Usaré las fechas, ubicación, preferencias y lugares "
                "seleccionados para armar una ruta coherente y variada."
            ),
            "generate_detail_positive_prefix": "priorizaré ",
            "generate_detail_negative_prefix": "evitaré ",
            "generate_detail_prefix": " Además, {details}.",
            "generate_detail_joiner": ", y ",

            # ============================================================
            # Replacement messages
            # ============================================================
            "replacement_no_alternatives": (
                "Entendí que quieres cambiar {poi_name}, pero todavía "
                "no encontré una alternativa sólida con el contexto "
                "disponible. Puedes decirme si prefieres algo más cercano, "
                "gastronómico, natural o tranquilo."
            ),
            "replacement_with_alternatives": (
                "Entendí que quieres cambiar la parada {poi_name}. "
                "Encontré alternativas reales para reemplazarla: {names}. "
                "Elige una opción o dime qué criterio priorizar: cercanía, "
                "tipo de experiencia, horario o ritmo del viaje."
            ),
            "replacement_complete": (
                "Listo, reemplace esa parada por {poi_name}. El itinerario "
                "quedo actualizado y puedes revisarlo en el mapa o en el detalle."
            ),

            # ============================================================
            # POI selection
            # ============================================================
            "selection_lodging": (
                "Perfecto, guardare {poi_name} como alojamiento base "
                "probable del viaje. Si despues quieres dormir en otra zona, "
                "dime el dia o la noche y lo ajusto."
            ),
            "selection_meal": (
                "Perfecto, guardare {poi_name} como opcion gastronomica "
                "y la ubicare donde mejor calce. Si la quieres para un dia "
                "especifico, dime por ejemplo: lunes almuerzo o ultima noche."
            ),
            "selection_default": (
                "Perfecto, considerare {poi_name} dentro de la ruta. "
                "Si no me indicas un dia especifico, lo ubicare "
                "automaticamente en el mejor momento."
            ),

            # ============================================================
            # Session / Orchestrator messages
            # ============================================================
            "session_reset_prefix": (
                "Perfecto, dejamos atras el plan anterior y partimos "
                "con una idea nueva. "
            ),
            "session_generation_complete": (
                "Listo, armé un itinerario personalizado con lo que conversamos."
            ),
            "session_generation_failed": (
                "Tuve un problema armando el itinerario completo. "
                "Puedes intentarlo de nuevo o ajustar un poco la búsqueda."
            ),

            # ============================================================
            # Quick reply labels and values
            # ============================================================
            # ── alojamiento ──
            "reply_sumar_comida_label": "Sumar comida",
            "reply_sumar_comida_value": "Agrega una pausa para comer",
            "reply_sumar_naturaleza_label": "Sumar naturaleza",
            "reply_sumar_naturaleza_value": "Agrega naturaleza al viaje",
            "reply_poco_traslado_label": "Poco traslado",
            "reply_poco_traslado_value": "Prefiero poco traslado",
            "reply_algo_tranquilo_label": "Algo tranquilo",
            "reply_algo_tranquilo_value": "Prefiero algo tranquilo",

            # ── gastronomia completed ──
            "reply_sumar_cultura_label": "Sumar cultura",
            "reply_sumar_cultura_value": "Agrega cultura local al viaje",
            "reply_sumar_descanso_label": "Sumar descanso",
            "reply_sumar_descanso_value": "Agrega una actividad tranquila",

            # ── gastronomia specific ──
            "reply_vista_lago_label": "Con vista",
            "reply_vista_lago_value": "Prefiero una opción con vista",
            "reply_mas_cercano_label": "Más cercano",
            "reply_mas_cercano_value": "Prioriza lo más cercano",
            "reply_ambiente_familiar_label": "Ambiente familiar",
            "reply_ambiente_familiar_value": "Busco ambiente familiar",
            "reply_rapido_y_simple_label": "Rápido y simple",
            "reply_rapido_y_simple_value": "Prefiero algo rápido",

            # ── gastronomia broad ──
            "reply_comida_local_label": "Comida local",
            "reply_comida_local_value": "Quiero comida local",
            "reply_pizza_label": "Pizza",
            "reply_pizza_value": "Quiero pizza",
            "reply_cafe_label": "Café",
            "reply_cafe_value": "Quiero un café",
            "reply_vista_lago_broad_value": "Quiero algo con vista",

            # ── naturaleza specific ──
            "reply_baja_dificultad_label": "Baja dificultad",
            "reply_baja_dificultad_value": "Prefiero baja dificultad",
            "reply_mejor_horario_label": "Mejor horario",
            "reply_mejor_horario_value": "Prioriza el mejor horario",
            "reply_combinar_comida_label": "Sumar comida",
            "reply_combinar_comida_value": "Agrega una pausa para comer",

            # ── naturaleza broad ──
            "reply_senderos_label": "Senderos",
            "reply_senderos_value": "Quiero senderos",
            "reply_miradores_label": "Miradores",
            "reply_miradores_value": "Quiero miradores",
            "reply_lagos_label": "Lagos",
            "reply_lagos_value": "Quiero visitar lagos",
            "reply_aire_libre_label": "Aire libre",
            "reply_aire_libre_value": "Quiero actividades al aire libre",

            # ── cultura ──
            "reply_museos_label": "Museos",
            "reply_museos_value": "Quiero museos",
            "reply_mapuche_label": "Cultura mapuche",
            "reply_mapuche_value": "Quiero cultura mapuche",
            "reply_artesanias_label": "Artesanías",
            "reply_artesanias_value": "Quiero artesanías",
            "reply_historia_label": "Historia local",
            "reply_historia_value": "Quiero historia local",

            # ── descanso ──
            "reply_termas_label": "Termas",
            "reply_termas_value": "Quiero termas",
            "reply_tranquilo_label": "Algo tranquilo",
            "reply_tranquilo_value": "Busco algo tranquilo",
            "reply_naturaleza_suave_label": "Naturaleza suave",
            "reply_naturaleza_suave_value": "Quiero naturaleza suave",

            # ── exploratory (else) ──
            "reply_naturaleza_label": "Naturaleza",
            "reply_naturaleza_value": "Quiero naturaleza",
            "reply_gastronomia_label": "Comida",
            "reply_gastronomia_value": "Quiero comida",
            "reply_cultura_label": "Cultura",
            "reply_cultura_value": "Quiero cultura",
            "reply_descanso_label": "Descanso",
            "reply_descanso_value": "Quiero algo tranquilo",

            # ── extra options (turn >= 2) ──
            "reply_ver_opciones_label": "Ver opciones",
            "reply_ver_opciones_value": "Muéstrame opciones",
            "reply_ajustar_cercania_label": "Más cercano",
            "reply_ajustar_cercania_value": "Prioriza cercanía",
            "reply_ajustar_ritmo_label": "Más tranquilo",
            "reply_ajustar_ritmo_value": "Prefiero una ruta tranquila",

            # ── always-appended ──
            "reply_hazlo_todo_tu_label": "Hazlo todo tú",
            "reply_hazlo_todo_tu_value": (
                "Haz una ruta sorpresa equilibrada y completa con "
                "alojamiento, comidas y actividades"
            ),
            "reply_crear_itinerario_label": "Crear itinerario",
            "reply_crear_itinerario_value": "Crear itinerario con lo acordado",

            # ── replacement quick replies ──
            "reply_usar_poi_prefix": "Usar ",
            "reply_buscar_mas_alternativas_label": "Buscar más alternativas",
            "reply_buscar_mas_alternativas_value": (
                "Busca más alternativas para esta parada"
            ),

            # ── orchestrator quick replies ──
            "reply_ver_itinerario_label": "Ver itinerario",
            "reply_ver_itinerario_value": "Ver itinerario {itinerary_id}",
            "reply_generar_itinerario_label": "Generar itinerario",

            # ============================================================
            # Misc (from skeleton / future use)
            # ============================================================
            "greeting": (
                "Soy Ara, tu asistente de viajes para La Araucanía. "
                "Contame: ¿a dónde querés ir?, ¿cuántos días?, y ¿qué ritmo te gusta? "
                "También podés decirme \"hacelo todo vos\" o ir eligiendo cada paso vos mismo."
            ),
            "greeting_with_dates": (
                "¡Hola! Soy Ara. Veo que tienes fechas para tu viaje: "
                "{start_date} al {end_date}. ¿Qué tipo de experiencia buscas?"
            ),
            "greeting_from_step": (
                "¡Hola! Veo que quieres cambiar el paso "
                "\"{poi_name}\" de tu itinerario. Déjame buscar alternativas..."
            ),
            "refine_meal": "¡Excelente elección! ¿Qué tipo de comida te gustaría?",
            "refine_activity": "¿Qué tipo de actividades prefieres?",
            "refine_lodging": "¿Buscas algún tipo de alojamiento en particular?",
            "refine_general": "Cuéntame más sobre lo que te gustaría hacer...",
            "poi_selected": "¡Anotado! He agregado {poi_name} a tu plan.",
            "poi_already_selected": "Ese lugar ya está en tu selección.",
            "trip_reset": "¡Empecemos de nuevo! ¿Qué tipo de experiencia buscas para tu viaje?",
            "ready_to_generate": "Ya tenemos varios lugares para tu itinerario. ¿Quieres que lo arme ahora?",
            "generating": (
                "Perfecto, estoy armando tu itinerario. Puedes seguir usando "
                "la app y revisar el resultado en unos momentos."
            ),
            "generation_complete": (
                "¡Listo! Tu itinerario está listo. Puedes verlo en la sección "
                "de Itinerarios."
            ),
            "generation_failed": (
                "Tuve un problema armando el itinerario completo. "
                "¿Quieres que lo intente de nuevo?"
            ),
            "replacement_suggestions": (
                "Encontré estas alternativas para reemplazar \"{poi_name}\":"
            ),
            "step_replaced": (
                "¡Listo! He reemplazado \"{old_name}\" por \"{new_name}\" "
                "en tu itinerario."
            ),
            "free_question_general": "Déjame ver... {answer}",
            "destination_scope_small": (
                "Encontré {count} lugares en {location}. "
                "¿Quieres que amplíe la búsqueda?"
            ),
            "destination_scope_expanded": (
                "Amplié la búsqueda. Ahora tengo {count} opciones para ti."
            ),
            "diversified_results": (
                "También encontré estas otras opciones que podrían interesarte:"
            ),
            "unknown_intent": "No estoy segura de haber entendido. ¿Podrías darme más detalles?",
            "no_results": (
                "No encontré lugares que coincidan con lo que buscas. "
                "¿Quieres probar con otros criterios?"
            ),
            "weather_context": (
                "El pronóstico para {date} en {location}: "
                "{description}, {temp}°C."
            ),
            "general_error": "Ups, tuve un problema. ¿Podemos intentarlo de nuevo?",
            # ============================================================
            # Day-aware flow (nuevo -- Camino C Hibrido)
            # ============================================================
            "cta_que_arme_ara": "Que lo arme Ara",
            "cta_pasemos_al": "Pasemos al {day}",
            "cta_otro_dia": "Otro dia",
            "cta_si_mas_actividades": "Si, mas actividades",
            "cta_empezar_alojamiento": "Alojamiento",
            "cta_empezar_actividades": "Actividades",
            "cta_sin_preferencias": "Sin preferencias",
            "lodging_disclaimer": (
                "Los alojamientos son sugerencias para tu itinerario. "
                "Las reservas, precios y disponibilidad las gestionas por tu cuenta. "
                "Ruta Viva no realiza reservas ni garantiza disponibilidad."
            ),
            "lodging_ask_if_needed": (
                "Ya tenes donde alojarte o queres que busque opciones?"
            ),
            "lodging_already_have": "Ya tengo donde",
            "lodging_buscar_opciones": "Buscar opciones",
            "lodging_no_needed": "No necesito",
            "lodging_ask_mode": (
                "Te quedas en {name} todos los dias o solo algunos?"
            ),
            "lodging_mode_all": "Todos los dias",
            "lodging_mode_single": "Solo el {day}",
            "lodging_mode_weekend": "El finde nomas",
            "lodging_selected": (
                "Perfecto. {name} queda como alojamiento{detail}."
            ),
            "day_greeting_with_weather": (
                "{day}. {weather_summary}"
            ),
            "day_what_to_do": "Que hacemos el {day}?",
            "day_empty_warning": (
                "Este dia esta sin actividades planificadas. "
                "Queres que te recomiende algo o lo dejamos libre?"
            ),
            "day_skip_confirm": (
                "El {day} todavia no tiene actividades. "
                "Seguro que pasamos al siguiente?"
            ),
            "day_skip_yes": "Si, dejarlo vacio",
            "day_skip_no": "No, mejor sigo con {day}",
            "day_free": "Dejarlo libre",
            "day_recommend": "Recomiendame algo",
            "progress_lodging": "Alojamiento: {name}",
            "progress_day_in_progress": "{label}: en progreso",
            "progress_day_completed": "{label}: completado",
            "progress_day_pending": "{label}: pendiente",
            "progress_day_skipped": "{label}: sin actividades",
            "que_arme_ara_food_pref": (
                "Dale. Antes de armar todo, alguna preferencia de comida?"
            ),
            "que_arme_ara_generating": (
                "Perfecto, estoy armando tu itinerario. "
                "Te aviso en unos momentos."
            ),
            "que_arme_ara_done": (
                "Listo. Arme tu itinerario con {steps} actividades en {days} dias. "
                "Queres ajustar algo?"
            ),
            "replacement_same_category": (
                "Encontre estas alternativas de {category} para reemplazar {name}:"
            ),
            "destination_expanded_warning": (
                "Amplie la busqueda fuera de {original}. "
                "Los lugares de {expanded} estan a {km} km aproximadamente."
            ),
        },
    }

    @classmethod
    def get(cls, key: str, lang: str | None = None, **kwargs: str | int | float) -> str:
        lang = lang or cls._default_lang
        messages = cls._messages.get(lang, cls._messages[cls._default_lang])
        template = messages.get(key, key)
        if kwargs:
            return template.format(**kwargs)
        return template
