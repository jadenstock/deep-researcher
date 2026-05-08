"""Agent tool functions.

Python functions registered as tools on PydanticAI agents. Tools mediate
all access to the note graph and retrieval layer so that agents never
touch state directly.

MVP set:
    load_note, search_notes, create_note, edit_note,
    web_search, academic_search,
    get_paper_metadata, get_papers_citing, get_papers_cited_by,
    fetch_and_extract, resolve_oa_pdf,
    load_source_section,
    spawn_task, ask_user.
"""
