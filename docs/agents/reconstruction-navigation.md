# Agent-first navigation and redraw boundary

`score_workflow.py` adds the Issue #56 boundary while the historical default remains unchanged. `prepare(source, task)` accepts a local path or public URL. Public URLs use the existing anonymous `public_video.acquire` boundary and then share the same PTS/hash protected local task record.

`navigate` creates low resolution probes without adding native captures. The Agent chooses times and views the resulting source images; `capture` retains native resolution only when requested. `present` records which probe/native images were actually shown. `assemble` receives Agent supplied position labels and continuity/first-last notes, removes only same-position overlap, and retains later repeated music as a separate position.

For each paginated rough page, `redraw_inputs` persists source hashes and complete source boundaries. The host image tool is called by the Agent: call `begin_redraw` before invocation, then `finish_redraw` with the actual output and receipt. A rejected page may have one persisted correction; a second rejection routes automatically to vector fallback. Failed/unavailable host calls can call `fail_redraw`. No receipt is treated as proof that a tool was invoked.

`export` keeps accepted host PNG bytes or geometric vector material by page, reflows complete systems through the shared A4 paginator, and records routes and material hashes. Use `review_pdf` only after rendering and viewing every output page. Interrupted tasks reload only intact derivations; damaged hashes are rejected.

The module is intentionally not the product default until the final integration ticket switches the command entry point.
