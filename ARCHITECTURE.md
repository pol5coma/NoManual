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