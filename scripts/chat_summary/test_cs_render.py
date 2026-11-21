"""Port of rendering.test.js (digest cases), subject.test.js, the rendering half of
diagnostics.test.js, and the byte-exact golden fixture from the JS app."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import pytest

import cs_render
import cs_shell as shell
from cs_errors import DigestError, failure_message
from cs_render import TAG_STYLE, build_digest_email, format_time, render, subject

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "email-golden.json").read_text(encoding="utf-8"))
URL = "https://docs.google.com/"


def chat(**overrides):
    item = {
        "row": 2, "cell_ref": "E2", "link": "https://docs.google.com/spreadsheets/d/example/edit#range=E2",
        "when": datetime(2025, 10, 21, 4, 30), "summary": "Export is stuck.",
        "sentiment": "negative", "tag": "unanswered",
    }
    item.update(overrides)
    return item


def attention_fragment(html):
    match = re.search(r'<td[^>]*class="callout-critical-dm">([\s\S]*?)</td>', html)
    return match.group(1) if match else ""


# --- golden ----------------------------------------------------------------------

@pytest.mark.parametrize("case", ["mixed", "empty", "unprocessedOnly"])
def test_render_matches_js_golden_bytes(case):
    golden = GOLDEN[case]
    got_subject, got_html, got_text = render(golden["args"])
    assert got_subject == golden["subject"]
    assert got_text == golden["text"]
    assert got_html.encode("utf-8") == golden["html"].encode("utf-8")


def test_golden_pins_the_sept_short_month_and_plural_quirks():
    _, _, text = render(GOLDEN["mixed"]["args"])
    assert "Since 3 Sept 11:05 PM\n" in text
    assert GOLDEN["mixed"]["subject"].endswith("— 6 chats")


# --- rendering.test.js -----------------------------------------------------------

def test_digest_uses_shell_with_responsive_and_dark_mode_hooks():
    html, _ = build_digest_email([chat()], "2025-10-21", URL, "Travel Animator")
    assert html.startswith("<!DOCTYPE html PUBLIC")
    assert "max-width:600px" in html
    assert "prefers-color-scheme: dark" in html
    assert "[data-ogsc]" in html
    assert re.search(r"<h1[^>]*>Travel Animator chat summary</h1>", html)
    assert "Tuesday, 21 October 2025 · 1 chat" in html
    assert "View all in Sheets" in html
    assert 'class="footer-bg body-cell"' in html


def test_digest_groups_sentiment_and_orders_unanswered_before_answered():
    items = [
        chat(row=2, cell_ref="E2", summary="Answered issue", tag="answered"),
        chat(row=4, cell_ref="E4", summary="Open issue"),
        chat(row=3, cell_ref="E3", summary="General question", sentiment="neutral", tag="forwarded"),
        chat(row=5, cell_ref="E5", summary="Thank you", sentiment="positive", tag="answered"),
        chat(row=6, cell_ref="E6", summary="Do not render an abandoned summary", tag="abandoned"),
    ]
    html, text = build_digest_email(items, "2025-10-21", URL, "MarineRadar")
    detail = html[html.index(">Negative · 2 chats</h2>"):]
    assert detail.index("Open issue") < detail.index("Answered issue")
    assert detail.index("Answered issue") < detail.index("General question")
    assert detail.index("General question") < detail.index("Thank you")
    assert re.search(r'<p[^>]*class="text-muted"[^>]*>Abandoned · 1 chat · No real question or no reply\.</p>', html)
    assert "Do not render an abandoned summary" not in html
    assert "NEGATIVE (2)" in text
    assert "- [Unanswered] Open issue · https://docs.google.com/spreadsheets/d/example/edit#range=E2\n" in text
    assert "ABANDONED: 1 chat\n" in text
    visible = re.sub(r"<[^>]+>", "", html) + re.sub(r"https:\S+", "", text)
    assert not re.search(r"\bE[2-6]\b", visible)


def test_digest_uses_semantic_status_colours_and_keeps_abandoned_muted():
    items = [chat(row=i + 2, cell_ref=f"E{i + 2}", tag=tag, sentiment="neutral")
             for i, tag in enumerate(["unanswered", "forwarded", "answered", "abandoned"])]
    html, _ = build_digest_email(items, "2025-10-21", URL, "MarineRadar")
    badges = []
    for style, classes, label in re.findall(
            r'<span style="([^"]*)" class="([^"]*)">(Unanswered|Forwarded|Answered)</span>', html):
        background = re.search(r"background-color:(#[a-f0-9]+);", style)
        color = re.search(r"(?:^|; )color:(#[a-f0-9]+);", style)
        badges.append({"label": label, "background": background and background.group(1),
                       "color": color and color.group(1), "classes": classes})
    assert badges == [
        {"label": "Unanswered", "background": "#fdf0ee", "color": "#c0392b",
         "classes": "callout-critical-dm badge-critical-dm"},
        {"label": "Forwarded", "background": "#faf3e6", "color": "#8a6520",
         "classes": "callout-warning-bg badge-warning-dm"},
        {"label": "Answered", "background": "#f0f8f2", "color": "#2a8c4a",
         "classes": "callout-positive-dm badge-positive-dm"},
    ]
    assert re.search(r'<p[^>]*color:#666666;" class="text-muted">Abandoned · 1 chat · No real question or no reply\.</p>',
                     html)
    abandoned = TAG_STYLE["abandoned"]
    assert re.search(r'background-color:#dddad7; color:#555555;[^>]*class="badge-bg text-muted">Abandoned</span>',
                     shell.badge(abandoned["label"], abandoned["variant"]))


def test_four_stat_cards_follow_header_rule_and_count_abandoned_separately():
    items = [chat(row=2), chat(row=3), chat(row=4, sentiment="neutral"), chat(row=5, sentiment="positive"),
             chat(row=6, sentiment="positive"), chat(row=7, sentiment="positive"),
             chat(row=8, sentiment="negative", tag="abandoned")]
    html, text = build_digest_email(items, "2025-10-21", URL, "MarineRadar")
    cards = [{"label": label, "count": int(count), "color": color} for color, count, label in re.findall(
        r'<p[^>]*color:(#[a-f0-9]+);" class="stat-value heading-dm">(\d+)</p><p[^>]*class="stat-label-dm">([^<]+)</p>',
        html)]
    assert cards == [
        {"label": "Negative", "count": 2, "color": "#c0392b"},
        {"label": "Neutral", "count": 1, "color": "#222222"},
        {"label": "Positive", "count": 3, "color": "#2a8c4a"},
        {"label": "Abandoned", "count": 1, "color": "#555555"},
    ]
    assert re.search(r'class="header-border">&nbsp;</td></tr></table></td></tr></table><table[^>]*><tr><td '
                     r'style="padding:16px 40px 0 40px;" class="body-cell"><table[^>]*class="stat-row">', html)
    assert [row.count('class="stat-cell"') for row in html.split('class="stat-row"')[1:]] == [2, 2]
    assert "Negative: 2 · Neutral: 1 · Positive: 3 · Abandoned: 1" in text


def test_attention_flags_negative_unanswered_or_forwarded_only():
    flagged = [chat(row=12, cell_ref="C12", summary="Export is stuck.\n  Please help."),
               chat(row=13, cell_ref="C13", summary="Support escalation", tag="forwarded")]
    other = [chat(row=14, cell_ref="C14", summary="Fixed export", tag="answered"),
             chat(row=15, cell_ref="C15", summary="Plain question", sentiment="neutral"),
             chat(row=16, cell_ref="C16", summary="Thank you", sentiment="positive", tag="forwarded"),
             chat(row=17, cell_ref="C17", summary="No reply", tag="abandoned")]
    html, text = build_digest_email(other + flagged, "2025-10-21", URL, "MarineRadar")
    attention = attention_fragment(html)
    assert "Needs your attention" in attention
    assert "Export is stuck. Please help.<br />Support escalation" in attention
    assert not re.search(r"Fixed export|Plain question|Thank you|No reply", attention)
    assert "Needs your attention\nExport is stuck. Please help.\nSupport escalation\n" in text
    assert html.index(">Abandoned</p>") < html.index(">Needs your attention</p>")
    assert html.index(">Needs your attention</p>") < html.index(">Negative · 3 chats</h2>")


def test_attention_keywords_flag_every_sentiment_and_status():
    summaries = ["Refund requested", "Subscription cancellation", "Unexpected charge", "SCAM report",
                 "Legal concern", "Data\nloss", "Safety issue", "Two refunds", "Account cancelled",
                 "Charged twice", "Chargeback pending"]
    for summary in summaries:
        html, text = build_digest_email([chat(cell_ref="C12", summary=summary, sentiment="positive", tag="answered")],
                                        "2025-10-21", URL, "MarineRadar")
        line = re.sub(r"\s+", " ", summary)
        assert line in attention_fragment(html), summary
        assert f"Needs your attention\n{line}\n" in text, summary
    html, _ = build_digest_email([chat(summary="Data-loss report", tag="abandoned")], "2025-10-21", URL, "MarineRadar")
    assert "Data-loss report" in attention_fragment(html)


def test_attention_lists_at_most_five_in_sheet_order():
    items = [chat(row=i + 12, cell_ref=f"C{i + 12}", summary=f"Refund request {i + 1}") for i in range(7)][::-1]
    html, text = build_digest_email(items, "2025-10-21", URL, "MarineRadar")
    attention = attention_fragment(html)
    lines = [item["summary"] for item in items[::-1][:5]]
    assert "<br />".join(lines) + "<br />+2 more" in attention
    assert not re.search(r"Refund request (?:6|7)", attention)
    assert "Needs your attention\n" + "\n".join(lines) + "\n+2 more\n" in text
    assert text.count("+2 more") == 1


def test_attention_truncates_normalized_summaries_at_word_boundary():
    summary = ("  Customer requested a refund after the app charged them twice and support has\nnot replied for "
               "three days.\tThey are waiting for a response.  ")
    expected = "Customer requested a refund after the app charged them twice and support has not replied…"
    html, text = build_digest_email([chat(cell_ref="C2", summary=summary)], "2025-10-21", URL, "MarineRadar")
    attention = attention_fragment(html)
    assert expected in attention
    assert not re.search(r"for three days|waiting for a response|\n|\t", attention)
    assert text.split("\nNeeds your attention\n")[1].split("\n\n")[0] == expected
    assert shell.esc(summary) in html, "HTML detail preserves the original summary"
    assert summary in text, "text detail preserves the original summary"


def test_attention_keeps_90_chars_and_bounds_a_long_unicode_token():
    exact = "x" * 88 + " y"
    short_html, short_text = build_digest_email([chat(summary=exact)], "2025-10-21", URL, "MarineRadar")
    assert exact in attention_fragment(short_html)
    assert "…" not in attention_fragment(short_html)
    assert f"Needs your attention\n{exact}\n" in short_text
    summary = "🔒" * 100
    expected = "🔒" * 89 + "…"
    html, text = build_digest_email([chat(summary=summary)], "2025-10-21", URL, "MarineRadar")
    assert expected in attention_fragment(html)
    assert f"Needs your attention\n{expected}\n" in text
    assert "�" not in attention_fragment(html)


def test_attention_classifies_full_summary_and_truncated_text_stays_escaped():
    summary = ("The <customer> asks about a saved map & route. " + "The export still does not work. " * 3
               + "They requested a refund.")
    html, text = build_digest_email([chat(summary=summary, sentiment="neutral", tag="answered")],
                                    "2025-10-21", URL, "MarineRadar")
    attention = attention_fragment(html)
    assert "Needs your attention" in attention
    assert "The &lt;customer&gt; asks about a saved map &amp; route." in attention
    assert re.search(r"…</p>", attention)
    assert not re.search(r"<customer>|refund", attention)
    assert "Needs your attention\nThe <customer> asks about a saved map & route." in text


def test_chat_table_has_full_width_linked_summary_and_fixed_status_column():
    link = "https://docs.google.com/spreadsheets/d/example/edit#range=C22"
    html, _ = build_digest_email([chat(cell_ref="C22", link=link, summary="Vessels not showing", time="12:59 PM")],
                                 "2025-10-21", URL, "MarineRadar")
    headers = [(label, (re.search(r' width="([^"]*)"', attrs) or [None, None])[1])
               for attrs, label in re.findall(r"<th([^>]*)>([^<]*)</th>", html)]
    assert headers == [("Summary", "100%"), ("Status", "128")]
    assert (f'<a href="{shell.esc(link)}" style="color:#222222; text-decoration:none;" '
            'class="email-link">Vessels not showing</a>') in html
    visible = re.sub(r"<[^>]+>", "", html)
    assert not re.search(r"C22|12:59 PM", visible)
    assert "&#8599;" not in html
    assert re.search(r'<span style="white-space:nowrap;"><span[^>]*class="callout-critical-dm badge-critical-dm">'
                     r'Unanswered</span></span>', html)


def test_attention_omitted_without_matches_including_similar_words():
    for items in ([], [chat(summary="Recharged battery; legally purchased app", sentiment="neutral", tag="answered")]):
        html, text = build_digest_email(items, "2025-10-21", URL, "MarineRadar")
        assert attention_fragment(html) == ""
        assert not re.search(r"Needs your attention|All clear", html + text, re.I)
    html, text = build_digest_email([], "2025-10-21", URL, "MarineRadar")
    assert html.count('class="stat-value heading-dm">0</p>') == 4
    assert "Negative: 0 · Neutral: 0 · Positive: 0 · Abandoned: 0" in text


def test_digest_uses_canonical_spacing_captions_links_and_footer():
    html, _ = build_digest_email([chat()], "2025-10-21", URL, "MarineRadar")
    assert re.search(r'<td style="padding:32px 40px 0 40px;" class="body-cell"><h2[^>]*>Negative · 1 chat</h2>', html)
    assert re.search(r'<td style="padding:16px 40px 0 40px;" class="body-cell"><p[^>]*>Frustrated, complaints, '
                     r'bugs</p>', html)
    assert shell.small("4:30 AM") not in html
    assert ('<a href="https://docs.google.com/spreadsheets/d/example/edit#range=E2" style="color:#222222; '
            'text-decoration:none;" class="email-link">Export is stuck.</a>') in html
    assert not re.search(r'padding:8px 40px 0 40px|width="18%"|class="text-main tfix"', html)
    assert "font-size:12px; line-height:1.5; color:#555555; text-align:center;" in html
    assert re.search(r'<p[^>]*font-size:11px; line-height:1.4; color:#888888; text-align:center;" '
                     r'class="text-muted">Report for Tuesday, 21 October 2025</p>', html)


def test_digest_escapes_user_text_and_link_attributes():
    item = chat(summary='<script>alert("summary")</script> & details', cell_ref='E2" onclick="bad',
                link='https://example.test/?q="bad"&a=1')
    html, text = build_digest_email([item], "2025-10-21", 'https://example.test/?q="sheet"&a=2', 'A < B & "C"')
    assert not re.search(r'<script>|<img src=x|onclick="bad', html)
    assert "&lt;script&gt;alert(&quot;summary&quot;)&lt;/script&gt; &amp; details" in html
    assert 'href="https://example.test/?q=&quot;bad&quot;&amp;a=1"' in html
    assert 'href="https://example.test/?q=&quot;sheet&quot;&amp;a=2"' in html
    assert "A &lt; B &amp; &quot;C&quot;" in html
    assert '<script>alert("summary")</script> & details' in text


def test_zero_chats_still_produces_a_complete_digest():
    html, text = build_digest_email([], "2025-11-01", URL, "Travel Animator")
    assert "Saturday, 1 November 2025 · 0 chats" in html
    assert "No chats for this report" in html
    assert re.search(r"</html>\s*$", html)
    assert "0 chats" in text
    assert "could not be processed" not in html + text


def test_unprocessed_counts_appear_once_beside_abandoned_section():
    note = "3 chats could not be processed and are not shown."
    html, text = build_digest_email([chat(tag="abandoned")], "2025-11-01", URL, "Travel Animator", 3)
    assert html.count(note) == 1
    assert text.count(note) == 1
    assert re.search(r'<p[^>]*class="text-muted"[^>]*>3 chats could not be processed and are not shown\.</p>', html)
    assert html.index("Abandoned ·") < html.index(note)
    assert html.index(note) < html.index("View all in Sheets")


def test_only_unprocessed_chat_explains_omission_without_claiming_empty_tab():
    html, text = build_digest_email([], "2025-11-01", URL, "Travel Animator", 1)
    for body in (html, text):
        assert "1 chat could not be processed and is not shown." in body
        assert "No chats for this report" not in body


def test_sheet_wall_clock_times_are_not_converted():
    assert format_time(datetime(2025, 10, 21, 4, 30)) == "4:30 AM"
    assert format_time(datetime(2025, 10, 21, 12, 59)) == "12:59 PM"
    assert format_time(datetime(2025, 10, 21, 0, 5)) == "12:05 AM"


# --- subject.test.js -------------------------------------------------------------

def test_subject_keeps_calendar_report_date_in_pt_edition():
    assert subject("Travel Animator chats", "2025-10-21", "America/Los_Angeles", "14 chats") == \
        "Travel Animator chats · Tue, Oct 21 — 14 chats"


def test_subject_uses_single_digit_day_without_year():
    assert subject("MarineRadar chats", "2025-11-01", "Asia/Kolkata", "1 chat") == \
        "MarineRadar chats · Sat, Nov 1 — 1 chat"


def test_subject_converts_instants_into_edition_timezone():
    instant = datetime(2026, 10, 21, 1, tzinfo=timezone.utc)
    assert subject("Chats", instant, "America/Los_Angeles", "0 chats") == "Chats · Tue, Oct 20 — 0 chats"
    assert subject("Chats", instant, "Asia/Kolkata", "0 chats") == "Chats · Wed, Oct 21 — 0 chats"


def test_subject_rejects_invalid_calendar_date():
    with pytest.raises(DigestError, match="Invalid report date"):
        subject("Chats", "2026-02-30", "Asia/Kolkata", "0 chats")


def test_subject_uses_en_us_sep_not_en_gb_sept():
    assert subject("Chats", "2025-09-03", "Asia/Kolkata", "0 chats") == "Chats · Wed, Sep 3 — 0 chats"


# --- diagnostics.test.js (rendering) ---------------------------------------------

def test_fixed_rendering_messages_never_echo_invalid_input():
    for operation, message in [
        (lambda: subject("Name", "PRIVATE_INVALID_DATE", "Asia/Kolkata", "0 chats"), "Invalid report date"),
        (lambda: build_digest_email([], "PRIVATE_INVALID_DATE", "https://example.test", "Name"), "Invalid report date"),
        (lambda: build_digest_email([], "2026-10-21\n", "https://example.test", "Name"), "Invalid report date"),
        (lambda: shell.table(["Header"], [["Value"]], ["PRIVATE_INVALID_ALIGNMENT"]), "Invalid table alignment"),
    ]:
        with pytest.raises(DigestError) as caught:
            operation()
        assert failure_message(caught.value, "build") == message


def test_render_reads_iso_strings_and_datetimes_alike():
    args = dict(GOLDEN["mixed"]["args"])
    args["items"] = [dict(item, when=cs_render.parse_when(item["when"])) for item in args["items"]]
    assert render(args) == render(GOLDEN["mixed"]["args"])
