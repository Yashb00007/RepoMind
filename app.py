import streamlit as st

from repomind.indexer import index_repo
from repomind.qa import retrieve, stream_answer
from repomind.store import list_repos

QUICK_QUESTIONS = {
    "Architecture overview": "Give me a high-level overview of this project's architecture: the main components and how they fit together.",
    "API endpoints": "List the main API endpoints or routes and where each one is defined.",
    "Dependencies": "What are the main dependencies and frameworks, and what is each one used for?",
    "Request flow": "Walk me through what happens when a request comes in, step by step, naming the files involved.",
}

st.set_page_config(page_title="RepoMind")
st.title("RepoMind")
st.caption("Connect a GitHub repo, then ask anything about its architecture.")

# ---- Sidebar ---------------------------------------------------------------
with st.sidebar:
    st.header("1. Connect a repo")
    source = st.text_input("GitHub URL or local path", placeholder="https://github.com/pallets/flask")
    full = st.checkbox("Full re-index", help="Rebuild from scratch instead of only updating changed files")
    if st.button("Index repository", disabled=not source):
        try:
            with st.status("Indexing...", expanded=True) as status:
                r = index_repo(source, progress=st.write, full=full)
                if r.up_to_date:
                    status.update(label=f"{r.name} is already up to date", state="complete")
                else:
                    kind = "Updated" if r.incremental else "Indexed"
                    status.update(
                        label=f"{kind} {r.name}: {r.files} files, {r.chunks_added} chunks written",
                        state="complete",
                    )
        except Exception as e:
            st.error(f"Indexing failed: {e}")

    st.header("2. Pick a repo")
    repos = list_repos()
    repo = st.selectbox("Indexed repositories", repos) if repos else None

    if repo:
        st.header("3. Quick questions")
        for label, text in QUICK_QUESTIONS.items():
            if st.button(label):
                st.session_state["pending"] = text
        if st.button("Clear chat"):
            st.session_state[f"chat:{repo}"] = []

if not repo:
    st.info("Index a repository from the sidebar to get started.")
    st.stop()

# ---- Chat ------------------------------------------------------------------
history = st.session_state.setdefault(f"chat:{repo}", [])


def show_sources(hits):
    with st.expander("Sources"):
        for h in hits:
            line = f"`{h['path']}` lines {h['start_line']}-{h['end_line']} ({h['via']})"
            if h.get("symbols"):
                line += f" - {h['symbols']}"
            st.markdown(line)


for msg in history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("sources"):
            show_sources(msg["sources"])

question = st.chat_input(f"Ask about {repo}...") or st.session_state.pop("pending", None)
if question:
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Searching the code..."):
                hits, query = retrieve(repo, question, history)
        except RuntimeError as e:
            st.error(str(e))
            st.stop()
        if query != question:
            st.caption(f"Searched for: {query}")
        answer = st.write_stream(stream_answer(question, hits, history))
        show_sources(hits)

    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": answer, "sources": hits})
