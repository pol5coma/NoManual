## Architecture


# REST API

- /manual               [POST]  -> upload
- /manuals              [GET]   -> returns all manuals
- /manuals/{id}/extract [POST]  -> extract manual's pages.


# RAG Patterns:

- Skills-guided retrieval: 
The user asks a question. The agent loads a relevant skill that describes how to search your corpus (which index to use, query formulation, citation format). The agent calls your retrieval tool following that guidance, then synthesizes an answer.

- Rubric-checked grounding (We're going to use this one): 
The user asks a question. The agent retrieves evidence and drafts an answer. A grader sub-agent, configured with RubricMiddleware, evaluates whether the response is grounded in the retrieved source material. The agent revises until the rubric passes or an iteration cap is reached.

- Todo-driven investigation: 
The user asks a question. If you opt into task planning, the agent uses the planning tool to create a todo list of documentation pages or search queries to investigate. It retrieves results for each item, then synthesizes a response from the collected evidence.

- Retrieve, offload, and delegate: 
The user asks a question. The agent retrieves matching chunks and writes them to the filesystem backend rather than keeping full text in the orchestrator context. Subagents read, search, and summarize individual files in parallel. For large documents, the agent can paginate through files with built-in search tools or run a code interpreter to produce tables, timelines, or visuals from source data.

# When to use Fine tuning vs RAG:

- Both methodologies handles different approaches. 

- RAG: It is used to bring grounded and original content to the LLM knowledge so it can reasoning better and reduce a lot (not avoid) the hallucination. To decrease hallucination we would introduce more strategies like guardrails, promting and if we see inconsistency, then we would fine-tune the model.

- Fine tuning: It is used when we need the model to have a specific behaviour. Sometimes prompting is not enough and introduces bias / inconsistency. Fine tuning re-trains the model and modify the weights given a topic-specific dataset. This way the model is trained to behave as expected following a specific format, style, or task pattern given in the dataset, reducing a lot the inconsistency. For example, if we want a structured JSON as a result of certain operation, training the model with datasets with that schema, would make the model answer 99% correctly rather than just by prompting strategy.

- SFT — Supervised Fine-Tuning: dataset de input → respuesta ideal. Es el más común. Sirve para enseñar formato, estilo, clasificación, tool calling o comportamiento específico.
- DPO — Direct Preference Optimization: dataset con respuesta buena vs respuesta mala; enseñas preferencias.
- RFT — Reinforcement Fine-Tuning: defines un grader/reward y optimizas el modelo según la puntuación. Para tareas de razonamiento bastante más específicas.

- LoRA (Low-Rank Adaptation): no entrenas todos los pesos; congelas el modelo y entrenas pequeños adapters. Mucho más barato.
- QLoRA: LoRA + modelo base cuantizado, normalmente 4-bit → todavía menos VRAM. Hugging Face PEFT soporta este enfoque.

- Se puede hacer con modelos open-weight como Qwen, Llama, Mistral, etc., usando Transformers + PEFT. En APIs managed depende del proveedor/modelo. OpenAI actualmente está retirando progresivamente su plataforma clásica de fine-tuning para nuevos usuarios, aunque documenta SFT, DPO y RFT para modelos existentes.

