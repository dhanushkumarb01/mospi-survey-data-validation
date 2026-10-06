from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_supervisor_workspace_surfaces_follow_the_review_journey():
    ui = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    api = (ROOT / "api.py").read_text(encoding="utf-8")
    for required in ("overview", "cases", "casePage", "groups", "reviewed", "technical", "openPosition", "nextPositionAfterDecision",
                     "Why it needs attention", "Similar people", "What supports this finding", "What should you check?",
                     "What did you conclude?", "Why it's high on the review list", "About this FSU", "Whole FSU — not this individual record",
                     "What happens next", "What should I review today?", "Why these records are here", "Where are unusual changes occurring?",
                     "No cases match", "could not be loaded"):
        assert required in ui, required
    for endpoint in ("/api/cases", "/api/patterns", "/api/export/queue", "LIMIT ? OFFSET ?", "/api/overview", "/api/queue/position",
                     "/api/reviews", "/api/groups"):
        assert endpoint in api, endpoint


def test_primary_navigation_has_no_research_pages():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    nav = html.split('<nav id="nav"', 1)[1].split("</nav>", 1)[0]
    primary = nav.split("nav-divider", 1)[0]
    for label in ("Overview", "Cases to review", "Group alerts", "Area trends", "Reviewed cases"):
        assert label in primary
    for removed in ("Evidence &amp; models", "Evidence & models", "Research evaluation", "Pattern explorer"):
        assert removed not in html
    assert "Technical reference" in nav.split("nav-divider", 1)[1]


def test_case_page_wording_avoids_model_jargon():
    ui = (ROOT / "ui" / "app.js").read_text(encoding="utf-8").lower()
    case_page = ui.split("async function casepage", 1)[1].split("async function groups", 1)[0]
    for word in ("isolation forest", "surprisal", "calibrated rank", "raw stored evidence", "conditional expectation", "percentile position",
                 "risk score", "influence score", "local outlier"):
        assert word not in case_page, word


def test_fsu_evidence_is_kept_out_of_the_record_evidence_list():
    ui = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    rows = ui.split("function evidenceRows", 1)[1].split("function evidenceHtml", 1)[0]
    assert "'pattern'" not in rows            # group evidence never appears as a record-level row
    assert "function fsuBlock" in ui and "fsu-block" in ui
