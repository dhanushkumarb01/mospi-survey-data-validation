# MoSPI supervisor UI — redesign to the reference design language (6 Oct 2026)

Scope: `fusion/ui/index.html`, `fusion/ui/app.js`, `fusion/ui/styles.css`, `fusion/ui/fonts/`, and one additive field in `fusion/explain.py`. No change to preprocessing, peer groups, models, fusion calculations, stored runs or API contracts used by tests.

## Reference → MoSPI mapping

| Reference element | MoSPI use (real data only) |
|---|---|
| Dark hero with red light streaks and nav inside it | Overview: "What should I review today?" with the queue size and the start action |
| Floating white cards with a dot-matrix and pill bars | Ranked records by priority group (dots scaled to the largest group; exact counts shown); highest-priority waiting vs decided; FSU and area alerts |
| Mission card + giant "72%" card | Why records are at the top (clickable reasons) + share of the highest-priority queue with a decision |
| Vertical pill tabs driving a cross-fading media panel | Up next · Group alerts · Area trends · Recent decisions |
| Accordion rows ("Track performance ⌄") | Disclosures everywhere: list size, method, record details, audit trail, technical JSON |
| Giant number with a small two-line label | List counts on Cases, Group alerts, Area trends, Reviewed; rank on the case page |
| Red-dot text tabs | Review status, decision filter, area level |
| Thumbnail list with tags | Area changes (direction glyph + from → to + period) |
| Closing call-to-action over a perspective floor, big wordmark footer | Start review; MoSPI footer with navigation |

## Colour semantics

Red = highest priority, "this record", issue confirmed · Violet = whole-FSU (group) evidence only · Green = decided / confirmed valid · Yellow = waiting / needs follow-up · everything else ink and greys. The hero streaks and perspective floors are decorative and carry no data.

## Data honesty

- Every figure is read from the API. Count-up animations always end on the stored value; with reduced motion the final value is shown immediately.
- Bars in small cards use proportional widths with a minimum width for legibility; the exact number is always written in or beside the bar.
- Area trends keep missing periods as visible gaps and state how many periods have no value.
- `GET /api/cases?summaries=true` now also returns `comparison` (stored `observed_value`, `peer_median`, `quantile_0_05`, `quantile_0_95`, position and comparable count, unchanged) so each case card can draw where the value sits. Covered by `fusion/tests/test_explain.py`.

## Fonts

Bebas Neue and Inter Tight (SIL Open Font License) are self-hosted in `fusion/ui/fonts/`, so the page makes no external requests and the existing Content-Security-Policy is unchanged.

## Verification

Checked at 2560×1440, 1920×1080, 1440×900, 1366×768, 820×1180 and 390×844 with no horizontal overflow and no console errors. The review workflow was exercised end to end (queue start, keyboard decision, note, save and next, filters, CSV link, Reviewed list, Overview counts) against a scratch copy of the runs; the real `review_audit.sqlite` files were not touched.
