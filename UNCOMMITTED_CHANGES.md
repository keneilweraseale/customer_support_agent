# Uncommitted Changes

This report summarizes the repository changes present before this report was
created. The worktree contains both staged and unstaged edits. No untracked
source files were present; this report itself is a new untracked Markdown file.

## Summary

The changes improve customer-support conversations with multi-intent handling,
better JSON-backed conversation memory, recall of earlier messages, restoration
of the active chat after sign-in, and warm conversation closings. Existing
support tickets remain open unless separately resolved; a closing response
does not claim that an issue has been fixed.

## Files changed

| File | Summary |
|---|---|
| `README.md` | Documents multi-intent routing, expanded conversation memory, and conversational closings. |
| `agent_flow.svg` | Updates the memory-flow diagram to reflect the expanded retained conversation context. |
| `app/agent/intent_classifier.py` | Extends validated LLM intent classification for multiple tasks, conversation recall, and closing messages. |
| `app/agent/router.py` | Routes combined questions, memory-recall requests, and thank-you/goodbye messages while preserving real support requests. |
| `app/api/chat.py` | Connects retrieved conversation context and recall to chat; adds owner-verified history loading and open-ticket-aware closings. |
| `app/services/conversation_memory.py` | Retains the first user message, stores a larger bounded transcript, selects relevant older turns, and answers recall requests. |
| `app/storage/json_store.py` | Raises the bounded JSON conversation-history limit while retaining existing expiry and ownership checks. |
| `app/storage/models.py` | Updates the conversation-memory schema for the larger history and separately retained first message. |
| `data/conversation_memory.json` | Contains modified demo conversation-memory records from application/test activity. |
| `data/support_tickets.json` | Contains added demo support-ticket records from application/test activity. |
| `frontend/src/App.jsx` | Restores the active conversation after sign-in and displays route labels for recall and closing responses. |
| `frontend/src/api.js` | Adds the authenticated API call for restoring conversation history. |
| `tests/test_api.py` | Adds API coverage for multi-intent responses, memory recall/history ownership, and ticket-aware closings. |
| `tests/test_intent_classifier.py` | Tests the additional supported intent classifications. |
| `tests/test_memory.py` | Tests expanded memory, sensitive-data redaction, first-message recall, and retrieval of older context. |
| `tests/test_router.py` | Tests multi-intent routing, recall intent, and conversational closings. |

## Staging status

- **Staged and unstaged edits:** `README.md`, `app/agent/intent_classifier.py`,
  `app/agent/router.py`, `app/api/chat.py`, `data/conversation_memory.json`,
  `frontend/src/App.jsx`, `tests/test_api.py`,
  `tests/test_intent_classifier.py`, and `tests/test_router.py`.
- **Staged edits only:** `agent_flow.svg`,
  `app/services/conversation_memory.py`, `app/storage/json_store.py`,
  `app/storage/models.py`, `data/support_tickets.json`,
  `frontend/src/api.js`, and `tests/test_memory.py`.

The two `data/` files are demo/runtime records, not implementation code; review
them separately before committing if they should not be included.
