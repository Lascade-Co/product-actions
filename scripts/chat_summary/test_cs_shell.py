"""Port of chat-summary test/template-components.test.js plus the shell cases of rendering.test.js."""
import re

import pytest

import cs_shell as shell
from cs_errors import DigestError

HEADING_FONT = "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
BODY_FONT = "'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif"


def tags(html, tag):
    return [dict(re.findall(r'([\w-]+)="([^"]*)"', attrs))
            for attrs in re.findall(rf"<{tag}\b([^>]*)>", html)]


def test_header_uses_canonical_eyebrow_heading_lead_and_rule_cells():
    html = shell.masthead("Daily chat digest", "Travel Animator chat summary", "Tuesday · 4 chats")
    assert [t["style"] for t in tags(html, "td") if t.get("class") == "body-cell"] == [
        "padding:40px 40px 10px 40px; text-align:left;",
        "padding:10px 40px 0 40px;",
        "padding:16px 40px 0 40px;",
        "padding:24px 40px 0 40px;",
    ]
    assert tags(html, "p") == [
        {"style": f"margin:0; Margin:0; font-family:{HEADING_FONT}; font-size:12px; font-weight:600; "
                  "letter-spacing:0.08em; text-transform:uppercase; color:#555555;",
         "class": "text-muted heading-dm"},
        {"style": f"margin:0; Margin:0; font-family:{BODY_FONT}; font-size:18px; line-height:1.55; color:#555555;",
         "class": "text-muted"},
    ]
    assert tags(html, "h1") == [{
        "class": "email-h1 heading-dm text-main",
        "style": f"margin:0; Margin:0; font-family:{HEADING_FONT}; font-size:30px; font-weight:700; "
                 "line-height:1.1; letter-spacing:-0.02em; color:#222222;",
    }]
    assert tags(html, "td")[-1] == {
        "style": "border-top:2px solid #222222; font-size:1px; line-height:1px; mso-line-height-rule:exactly;",
        "class": "header-border",
    }


def test_striped_table_matches_canonical_markup():
    html = shell.table(["Chat", "Summary"], [["C12", "One"], ["C13", "Two"], ["C14", "Three"]])
    assert tags(html, "table") == [{
        "cellspacing": "0", "cellpadding": "0", "border": "0", "width": "100%",
        "style": f"font-family:{BODY_FONT}; font-size:14px; line-height:1.5; color:#222222; border-collapse:collapse;",
        "class": "text-main",
    }]
    assert tags(html, "th") == [{
        "align": "left",
        "style": f"padding:10px 12px; font-family:{HEADING_FONT}; font-weight:600; font-size:13px; "
                 "text-transform:uppercase; letter-spacing:0.03em; border-bottom:2px solid #222222; "
                 "word-break:normal; overflow-wrap:normal; hyphens:none; color:#222222;",
        "class": "heading-dm header-border",
    }] * 2
    stripe = {"style": "background-color:#ece9e6;", "class": "table-stripe"}
    assert tags(html, "tr") == [{}, stripe, {}, stripe]
    assert tags(html, "td") == [{"style": "padding:10px 12px;"}] * 6
    assert tags(shell.table(["Chat"], [["C12"]], None, False), "td") == [{
        "style": "padding:10px 12px; border-bottom:1px solid #dddddd;", "class": "divider-line",
    }]


STAT_LAYOUTS = [
    (1, [(1, "100%", "168px")]),
    (2, [(2, "50%", "336px")]),
    (3, [(3, "33.33%", "504px")]),
    (4, [(2, "50%", "336px"), (2, "50%", "336px")]),
    (5, [(3, "33.33%", "504px"), (2, "50%", "336px")]),
    (6, [(3, "33.33%", "504px"), (3, "33.33%", "504px")]),
    (7, [(3, "33.33%", "504px"), (3, "33.33%", "504px"), (1, "100%", "168px")]),
]


@pytest.mark.parametrize("count,layout", STAT_LAYOUTS)
def test_stat_grid_keeps_cards_in_plain_table_rows(count, layout):
    html = shell.stat_grid([(i + 1, f"Metric {i + 1}", "#222222") for i in range(count)])
    starts = [m.start() for m in re.finditer(r'<table\b[^>]*class="stat-row">', html)]
    rows = [html[s:(starts[i + 1] if i + 1 < len(starts) else len(html))] for i, s in enumerate(starts)]
    assert len(rows) == len(layout)
    assert html.startswith('<table role="presentation"')
    assert html.endswith("</tr></table>\n")
    assert not re.search(r"display:inline-block|<div\b|<!--\[if mso\]", html)
    assert len(tags(html, "table")) == count + len(layout)
    assert len(tags(html, "td")) == count * 2
    assert re.findall(r'class="stat-label-dm">([^<]*)</p>', html) == [f"Metric {i + 1}" for i in range(count)]
    for row, (size, width, max_width) in zip(rows, layout):
        assert tags(row, "table")[0] == {
            "role": "presentation", "cellspacing": "0", "cellpadding": "0", "border": "0", "width": "100%",
            "align": "center", "style": f"width:100%; max-width:{max_width}; margin:0 auto; table-layout:fixed;",
            "class": "stat-row",
        }
        assert [t for t in tags(row, "td") if t.get("class") == "stat-cell"] == [
            {"width": width, "valign": "top", "align": "center", "style": "padding:4px;", "class": "stat-cell"}
        ] * size
        assert [t for t in tags(row, "td") if "stat-card-dm" in t.get("class", "")] == [{
            "bgcolor": "#fefefe", "style": "background-color:#fefefe; padding:16px 12px; text-align:center;",
            "class": "stat-card-dm stat-card-3" if size == 3 else "stat-card-dm",
        }] * size
        assert [t["class"] for t in tags(row, "p") if "stat-value" in t.get("class", "")] == \
            ["stat-value heading-dm stat-value-3" if size == 3 else "stat-value heading-dm"] * size


def test_empty_stat_grids_emit_no_markup():
    assert shell.stat_grid([]) == ""


def test_stat_cards_retain_typography_and_escape_values():
    html = shell.stat_grid([("<3>", "Negative & urgent", "#c0392b"), (4, "Neutral", "#222222"),
                            (5, "Positive", "#2a8c4a")])
    expected = []
    for color in ("#c0392b", "#222222", "#2a8c4a"):
        expected += [
            {"style": f"margin:0; Margin:0; font-family:{HEADING_FONT}; font-size:32px; font-weight:700; "
                      f"line-height:1.1; white-space:nowrap; color:{color};",
             "class": "stat-value heading-dm stat-value-3"},
            {"style": f"margin:4px 0 0 0; Margin:4px 0 0 0; font-family:{HEADING_FONT}; font-size:11px; "
                      "font-weight:600; text-transform:uppercase; letter-spacing:0.04em; color:#777777;",
             "class": "stat-label-dm"},
        ]
    assert tags(html, "p") == expected
    assert re.search(r">&lt;3&gt;</p>", html)
    assert re.search(r">Negative &amp; urgent</p>", html)


def test_three_card_rows_use_narrower_mobile_typography():
    mobile = re.search(r"@media only screen and \(max-width: 480px\) \{([\s\S]*?)\n        \}",
                       shell.head("Mobile digest"))
    assert mobile
    assert re.search(r"\.stat-value-3 \{ font-size: 22px !important; \}", mobile.group(1))
    assert re.search(r"\.stat-card-3 \{ padding-left: 6px !important; padding-right: 6px !important; \}",
                     mobile.group(1))


def test_badge_variants_retain_template_sizes():
    prefix = f"display:inline-block; font-family:{HEADING_FONT}; font-size:11px; font-weight:600; line-height:1; "
    variants = [
        ("default", "padding:5px 10px; border-radius:12px; background-color:#e8e6e3; color:#222222; "
                    "text-transform:uppercase; letter-spacing:0.03em;", "badge-bg"),
        ("outline", "padding:4px 9px; border-radius:12px; background-color:transparent; color:#222222; "
                    "text-transform:uppercase; letter-spacing:0.03em; border:1px solid #888888;", "badge-outline"),
        ("muted", "padding:5px 10px; border-radius:12px; background-color:#dddad7; color:#555555; "
                  "text-transform:uppercase; letter-spacing:0.03em;", "badge-bg text-muted"),
    ]
    for variant, suffix, classes in variants:
        html = shell.badge("<status>", variant)
        assert tags(html, "span") == [{"style": prefix + suffix, "class": classes}]
        assert re.search(r">&lt;status&gt;</span>", html)


@pytest.mark.parametrize("variant,background,color,classes", [
    ("critical", "#fdf0ee", "#c0392b", "callout-critical-dm badge-critical-dm"),
    ("warning", "#faf3e6", "#8a6520", "callout-warning-bg badge-warning-dm"),
    ("positive", "#f0f8f2", "#2a8c4a", "callout-positive-dm badge-positive-dm"),
    ("info", "#eef5fb", "#2980b9", "callout-info-bg badge-info-dm"),
])
def test_semantic_badges_use_colours_and_default_pill(variant, background, color, classes):
    html = shell.badge("<status>", variant)
    assert tags(html, "span") == [{
        "style": f"display:inline-block; font-family:{HEADING_FONT}; font-size:11px; font-weight:600; "
                 f"line-height:1; padding:5px 10px; border-radius:12px; background-color:{background}; "
                 f"color:{color}; text-transform:uppercase; letter-spacing:0.03em;",
        "class": classes,
    }]
    assert re.search(r">&lt;status&gt;</span>", html)


DARK_BADGE_COLORS = [("critical", "#f0a094"), ("warning", "#e6c27a"), ("positive", "#8fd3a5"), ("info", "#9cc9ec")]
DARK = r"@media \(prefers-color-scheme: dark\) \{([\s\S]*?)\n        \}"


def test_semantic_badge_colours_override_inside_dark_mode_query():
    dark = re.search(DARK, shell.head("Dark-mode digest"))
    assert dark
    colors = re.findall(r"^\s*\.badge-(critical|warning|positive|info)-dm\s*\{\s*color:\s*(#[a-f0-9]{6}) "
                        r"!important;\s*\}", dark.group(1), re.M)
    assert colors == DARK_BADGE_COLORS


def test_outlook_badge_colours_scoped_to_data_ogsc_outside_dark_query():
    html = shell.head("Outlook dark-mode digest")
    dark = re.search(DARK, html)
    assert dark
    outside = html.replace(dark.group(0), "", 1)
    colors = re.findall(r"^\s*\[data-ogsc\] \.badge-(critical|warning|positive|info)-dm\s*\{\s*color:\s*"
                        r"(#[a-f0-9]{6}) !important;\s*\}", outside, re.M)
    assert colors == DARK_BADGE_COLORS
    assert not re.search(r"^\s*\.badge-(critical|warning|positive|info)-dm\s*\{", outside, re.M)


def test_callouts_match_each_variant_and_escape_multiline_content():
    variants = [
        ("note", "#222222", "#ece9e6", "callout-info-bg", "#222222", 600, "0.03em", "1.6"),
        ("warning", "#c9922a", "#faf3e6", "callout-warning-bg", "#8a6520", 600, "0.03em", "1.6"),
        ("critical", "#c0392b", "#fdf0ee", "callout-critical-dm", "#c0392b", 700, "0.04em", "1.55"),
        ("positive", "#2a8c4a", "#f0f8f2", "callout-positive-dm", "#2a8c4a", 700, "0.04em", "1.55"),
        ("info", "#2980b9", "#eef5fb", "callout-info-dm", "#2980b9", 700, "0.04em", "1.55"),
    ]
    for kind, bar, background, classes, title_color, weight, tracking, line_height in variants:
        html = shell.callout(kind, "<Needs attention>", ["C12 · <refund>", "C13 · A & B"])
        table_attrs = {"role": "presentation", "cellspacing": "0", "cellpadding": "0", "border": "0", "width": "100%"}
        if kind in ("note", "warning"):
            table_attrs["class"] = classes
        if kind in ("critical", "positive"):
            table_attrs["style"] = "margin-bottom:16px;"
        assert tags(html, "table") == [table_attrs]
        bar_attrs = {"width": "4", "bgcolor": bar, "style": f"background-color:{bar};"}
        if kind == "note":
            bar_attrs["class"] = "callout-info-border"
        assert tags(html, "td") == [bar_attrs, {
            "bgcolor": background, "style": f"background-color:{background}; padding:16px 20px;", "class": classes,
        }]
        assert tags(html, "p") == [
            {"style": f"margin:0; Margin:0 0 4px 0; font-family:{HEADING_FONT}; font-size:13px; "
                      f"font-weight:{weight}; text-transform:uppercase; letter-spacing:{tracking}; "
                      f"color:{title_color};", "class": "heading-dm"},
            {"style": f"margin:0; Margin:0; font-family:{BODY_FONT}; font-size:15px; line-height:{line_height}; "
                      "color:#222222;", "class": "text-main"},
        ]
        assert "&lt;Needs attention&gt;" in html
        assert "C12 · &lt;refund&gt;<br />C13 · A &amp; B" in html


def test_buttons_match_primary_and_secondary_components():
    for secondary in (False, True):
        html = shell.button("<View>", 'https://example.test/?q="a"&b=2', secondary)
        assert tags(html, "td") == [
            {"style": "border-radius:6px;", "class": "btn-secondary"} if secondary else
            {"style": "border-radius:6px; background-color:#222222;", "bgcolor": "#222222", "class": "btn-primary"}
        ]
        assert tags(html, "a") == [{
            "href": "https://example.test/?q=&quot;a&quot;&amp;b=2",
            "style": f"display:inline-block; padding:12px 28px; font-family:{HEADING_FONT}; font-size:15px; "
                     f"font-weight:600; line-height:1.2; color:{'#222222' if secondary else '#f5f3f1'}; "
                     "text-decoration:none; border-radius:6px; border:2px solid #222222;"
                     + (" background-color:transparent;" if secondary else ""),
            "class": "btn-secondary" if secondary else "btn-primary",
        }]
        assert ">&lt;View&gt;</a>" in html


def test_footer_uses_canonical_typography_and_rounded_corners():
    html = shell.footer("<Title>", ["<Description>", "Second line"], [["<Sheets>", 'https://example.test/?q="x"']],
                        ["<Report date>", "Second attribution"])
    assert tags(html, "td") == [{
        "bgcolor": "#ece9e6", "style": "background-color:#ece9e6; padding:32px 40px; border-radius:0 0 6px 6px;",
        "class": "footer-bg body-cell",
    }]
    assert tags(html, "p") == [
        {"style": f"margin:0; Margin:0 0 8px 0; font-family:{HEADING_FONT}; font-size:13px; font-weight:600; "
                  "color:#222222; text-align:center;", "class": "heading-dm"},
        {"style": f"margin:0; Margin:0 0 16px 0; font-family:{BODY_FONT}; font-size:12px; line-height:1.5; "
                  "color:#555555; text-align:center;", "class": "text-muted"},
        {"style": f"margin:0; Margin:0 0 8px 0; font-family:{BODY_FONT}; font-size:12px; line-height:1.5; "
                  "color:#555555; text-align:center;", "class": "text-muted"},
        {"style": f"margin:0; Margin:0; font-family:{BODY_FONT}; font-size:11px; line-height:1.4; "
                  "color:#888888; text-align:center;", "class": "text-muted"},
    ]
    assert tags(html, "a") == [{
        "href": "https://example.test/?q=&quot;x&quot;", "style": "color:#555555; text-decoration:underline;",
        "class": "email-link",
    }]
    assert "&lt;Description&gt;<br />Second line" in html
    assert "&lt;Report date&gt;<br />Second attribution" in html
    assert not re.search(r"<Title>|<Description>|<Sheets>|<Report date>", html)


# --- shell cases from rendering.test.js ------------------------------------------

def test_shell_escapes_text_while_preserving_composed_cells():
    html = shell.table(["<Header>"], [["<User text>"], [{"html": shell.badge("<Open>")}]])
    assert "&lt;Header&gt;" in html
    assert "&lt;User text&gt;" in html
    assert re.search(r"<span[^>]*>&lt;Open&gt;</span>", html)
    assert not re.search(r"<Header>|<User text>|<Open>", html)


def test_shell_text_helpers_and_footer_escape_their_data():
    html = "".join([
        shell.masthead("<eyebrow>", "<title>", "<lead>", "<caption>"),
        shell.h2("<h2>"), shell.h3("<h3>"), shell.p("<body>"),
        shell.lead("<intro>"), shell.small("<small>"),
        shell.callout("critical", "<alert>", "<message>"),
        shell.footer("<footer>", ["<line>"], [["<link>", 'https://example.test/?q="footer"']]),
    ])
    for text in ("eyebrow", "title", "lead", "caption", "h2", "h3", "body", "intro", "small", "alert", "message",
                 "footer", "line", "link"):
        assert f"&lt;{text}&gt;" in html, text
    assert 'href="https://example.test/?q=&quot;footer&quot;"' in html


def test_stat_grid_groups_five_cards_and_escapes_values():
    html = shell.stat_grid([("<1>", "<label>", "#c0392b"), (2, "Two"), (3, "Three"), (4, "Four"), (5, "Five")])
    assert [row.count('class="stat-cell"') for row in html.split('class="stat-row"')[1:]] == [3, 2]
    assert "&lt;1&gt;" in html
    assert "&lt;label&gt;" in html


def test_esc_matches_the_js_entity_set():
    assert shell.esc("&<>\"'") == "&amp;&lt;&gt;&quot;&#39;"
    assert shell.esc(None) == ""
    assert shell.esc(2) == "2"


def test_shell_rejects_invalid_presentation_values_with_fixed_messages():
    for call, message in [
        (lambda: shell.cell("x", "1px;color:red"), "Invalid cell padding"),
        (lambda: shell.table(["H"], [["V"]], ["PRIVATE"]), "Invalid table alignment"),
        (lambda: shell.table(["H"], [["V"]], None, True, ["10px"]), "Invalid table width"),
        (lambda: shell.stat_grid([(1, "x", "red")]), "Invalid color"),
        (lambda: shell.badge("x", "PRIVATE"), "Invalid badge variant"),
        (lambda: shell.callout("PRIVATE", "t", "b"), "Invalid callout kind"),
    ]:
        with pytest.raises(DigestError) as caught:
            call()
        assert str(caught.value) == message
