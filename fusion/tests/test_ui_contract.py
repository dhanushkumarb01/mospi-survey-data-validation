from pathlib import Path


ROOT = Path(__file__).parents[1]
UI = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")


def test_supervisor_workspace_follows_the_review_workflow():
    api = (ROOT / "api.py").read_text(encoding="utf-8")
    for required in ("overview", "worklist", "cases", "casePage", "groups", "reviewed", "technical", "What was recorded", "What to check",
                     "Your decision", "What could not be checked", "Audit history", "How it was verified", "Next case"):
        assert required in UI, required
    for endpoint in ("/api/cases", "/api/worklist", "/api/export/queue", "LIMIT ? OFFSET ?", "/api/overview", "/api/queue/position",
                     "/api/reviews", "/api/groups", "/api/feedback", "/api/audit/verify"):
        assert endpoint in api, endpoint


def test_primary_navigation_is_a_plain_dashboard():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    nav = html.split('<nav id="nav"', 1)[1].split("</nav>", 1)[0]
    for label in ("Overview", "Worklist by FSU", "All cases", "Group alerts", "Area trends", "Decisions", "Technical reference"):
        assert label in nav
    assert "Powered by <b>INNODATATICS</b>" in html and "MoSPI" in html
    css = (ROOT / "ui" / "styles.css").read_text(encoding="utf-8")
    assert "@font-face" not in css and "animation" not in css and "@keyframes" not in css     # plain government dashboard
    # one restrained navy-to-indigo blend on a few surfaces only; no radial/conic effects or decorative washes
    assert css.count("gradient") <= 5 and "radial-gradient" not in css and "conic-gradient" not in css
    assert "backdrop-filter" not in css     # no glass effects


def test_case_page_wording_avoids_model_jargon_outside_technical_details():
    case_page = UI.split("async function casePage", 1)[1].split("async function groups", 1)[0].lower()
    for word in ("isolation forest", "surprisal", "calibrated rank", "risk score", "influence score", "local outlier", "p-value", "conformal"):
        assert word not in case_page, word


def test_group_evidence_is_shown_separately_with_the_mandatory_sentence():
    story = (ROOT / "story.py").read_text(encoding="utf-8")
    assert "does not mean that any answer" in story
    assert "function groupHtml" in UI and "panel violet" in UI
    assert "if (s.source === 'pattern') return ''" in UI     # never rendered as record-level evidence
