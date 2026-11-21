"""Email shell for the chat digest: a line-by-line port of chat-summary src/shell.js.

The head, CSS and outer body are copied verbatim from the JS template (itself
mined from product-intelligence/Style Template/styleguide-email.html, with text
slots and .tfix). Keep every literal byte-identical: the golden fixture
(fixtures/email-golden.json) pins the whole document. scripts/common/email_shell.py
is a different revision (stat grid, badges, cells) and is not interchangeable.

Text arguments are escaped with esc(); cell()'s inner, table cells given as
{"html": ...}, and document()'s body/footer are trusted, already-composed HTML.
Invalid presentation values raise DigestError with fixed messages.
"""
import re

from cs_errors import DigestError

FONT_HEADING = "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
FONT_BODY = "'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif"
BG = "#f5f3f1"
INK = "#222222"
MUTED = "#555555"
CAPTION = "#666666"
RULE = "#dddddd"
STRIPE = "#ece9e6"
CARD = "#fefefe"
STAT_LABEL = "#777777"
GREEN = "#2a8c4a"
RED = "#c0392b"
AMBER = "#c9922a"
BLUE = "#2980b9"

_ENTITIES = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}


def esc(value):
    """JS esc(): String(value ?? "") with & < > " ' replaced (note &#39;, not &#x27;)."""
    return re.sub(r"[&<>\"']", lambda m: _ENTITIES[m.group(0)], js_string(value))


def js_string(value):
    """String(value ?? "") for the values the digest renders."""
    if value is None:
        return ""
    if value is True or value is False:
        return "true" if value else "false"
    return str(value)


_HEAD = """<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" lang="en" dir="ltr">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta http-equiv="X-UA-Compatible" content="IE=edge" />
    <meta name="color-scheme" content="light dark" />
    <meta name="supported-color-schemes" content="light dark" />
    <meta name="format-detection" content="telephone=no, date=no, address=no, email=no" />
    <title>__TITLE__</title>

    <!--[if mso]>
    <noscript>
        <xml>
            <o:OfficeDocumentSettings>
                <o:AllowPNG/>
                <o:PixelsPerInch>96</o:PixelsPerInch>
            </o:OfficeDocumentSettings>
        </xml>
    </noscript>
    <![endif]-->

    <!-- Web fonts: hidden from Outlook to prevent Times New Roman fallback -->
    <!--[if !mso]><!-->
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    </style>
    <!--<![endif]-->

    <!-- Outlook-only font fallback -->
    <!--[if mso]>
    <style type="text/css">
        body, table, td, th, p, li, a, span {
            font-family: 'Segoe UI', Arial, sans-serif !important;
        }
        h1, h2, h3, h4, h5, h6 {
            font-family: 'Segoe UI', Arial, sans-serif !important;
        }
    </style>
    <![endif]-->

    <style type="text/css">
        /* ============================================
           EMAIL CLIENT RESETS
           ============================================ */
        #outlook a { padding: 0; }
        body { margin: 0 !important; padding: 0 !important; width: 100% !important; -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }
        table { border-collapse: collapse; mso-table-lspace: 0pt; mso-table-rspace: 0pt; }
        td { border-collapse: collapse; }
        img { border: 0; height: auto; line-height: 100%; outline: none; text-decoration: none; display: block; -ms-interpolation-mode: bicubic; }
        p { margin: 0; Margin: 0; }
        a { color: #222222; }
        .ExternalClass { width: 100%; }
        .ExternalClass, .ExternalClass p, .ExternalClass span, .ExternalClass font, .ExternalClass td, .ExternalClass div { line-height: 100%; }

        /* iOS auto-link overrides */
        a[x-apple-data-detectors] {
            color: inherit !important;
            text-decoration: none !important;
            font-size: inherit !important;
            font-family: inherit !important;
            font-weight: inherit !important;
            line-height: inherit !important;
        }

        /* ============================================
           RESPONSIVE
           ============================================ */
        @media only screen and (max-width: 480px) {
            .email-container { width: 100% !important; max-width: 100% !important; }
            .fluid { width: 100% !important; max-width: 100% !important; height: auto !important; }
            .stack-column { display: block !important; width: 100% !important; max-width: 100% !important; direction: ltr !important; }
            .stack-column-center { text-align: center !important; }
            .center-on-narrow { text-align: center !important; display: block !important; margin-left: auto !important; margin-right: auto !important; float: none !important; }
            table.center-on-narrow { display: inline-block !important; }
            .email-container td.body-cell { padding-left: 20px !important; padding-right: 20px !important; }
            .mobile-pad { padding-left: 20px !important; padding-right: 20px !important; }
            h1.email-h1 { font-size: 26px !important; }
            h2.email-h2 { font-size: 20px !important; }
            .mobile-full { width: 100% !important; }
            .mobile-hide { display: none !important; }
            .mobile-show { display: block !important; max-height: none !important; overflow: visible !important; }
            .avatar-col { max-width: 50% !important; width: 50% !important; }
            .avatar-circle { width: 48px !important; height: 48px !important; font-size: 18px !important; line-height: 48px !important; }
            .avatar-name { font-size: 12px !important; }
            .avatar-subtitle { font-size: 11px !important; }
            .stat-col { max-width: 50% !important; width: 50% !important; }
            .stat-value { font-size: 28px !important; }
            .stat-value-3 { font-size: 22px !important; }
            .stat-card-3 { padding-left: 6px !important; padding-right: 6px !important; }
            .bar-label-cell { width: 100px !important; font-size: 11px !important; }
            .contributor-col { display: block !important; width: 100% !important; max-width: 100% !important; }
        }

        /* ============================================
           DARK MODE — Apple Mail, iOS, macOS Mail
           ============================================ */
        @media (prefers-color-scheme: dark) {
            .body-bg { background-color: #1a1a18 !important; }
            .email-body-bg { background-color: #222220 !important; }
            .card-bg { background-color: #2a2927 !important; }
            .text-main { color: #e0ddd8 !important; }
            .heading-dm { color: #ece9e4 !important; }
            .text-muted { color: #a8a49e !important; }
            .email-link { color: #c8c4be !important; }
            .divider-line { border-color: #3a3835 !important; }
            .code-inline { background-color: #2a2927 !important; color: #e0ddd8 !important; border-color: #3a3835 !important; }
            .footer-bg { background-color: #1a1a18 !important; }
            .callout-info-bg { background-color: #2a2927 !important; border-color: #5a6a9a !important; }
            .callout-warning-bg { background-color: #2a2927 !important; }
            .callout-info-border { background-color: #5a6a9a !important; }
            .badge-bg { background-color: #3a3835 !important; color: #e0ddd8 !important; }
            .badge-outline { border-color: #5a5855 !important; color: #e0ddd8 !important; }
            .mark-bg { background-color: #4a4530 !important; color: #e0ddd8 !important; }
            .kbd-bg { background-color: #3a3835 !important; border-color: #5a5855 !important; color: #e0ddd8 !important; }
            .aside-bg { background-color: #2a2927 !important; }
            .table-stripe { background-color: #2a2927 !important; }
            .table-border { border-color: #3a3835 !important; }
            .btn-primary { background-color: #e0ddd8 !important; color: #1a1a18 !important; border-color: #e0ddd8 !important; }
            .btn-secondary { background-color: transparent !important; color: #e0ddd8 !important; border-color: #e0ddd8 !important; }
            .preheader-bg { background-color: #1a1a18 !important; }
            .header-border { border-color: #3a3835 !important; }
            .blockquote-border { background-color: #5a5855 !important; }
            .pullquote-border { border-color: #5a5855 !important; }
            .img-border { border-color: #3a3835 !important; }
            .avatar-name-dm { color: #ece9e4 !important; }
            .avatar-subtitle-dm { color: #a8a49e !important; }
            .stat-card-dm { background-color: #2a2927 !important; }
            .stat-label-dm { color: #a8a49e !important; }
            .timeline-border-dm { border-color: #3a3835 !important; }
            .timeline-text-dm { color: #e0ddd8 !important; }
            .timeline-time-dm { color: #a8a49e !important; }
            .bar-chart-dm { background-color: #2a2927 !important; }
            .bar-track-dm { background-color: #1a1a18 !important; }
            .bar-label-dm { color: #a8a49e !important; }
            .bar-title-dm { color: #a8a49e !important; }
            .contributor-card-dm { background-color: #2a2927 !important; }
            .contributor-meta-dm { color: #a8a49e !important; }
            .callout-critical-dm { background-color: #2a2220 !important; }
            .badge-critical-dm { color: #f0a094 !important; }
            .badge-warning-dm { color: #e6c27a !important; }
            .badge-positive-dm { color: #8fd3a5 !important; }
            .badge-info-dm { color: #9cc9ec !important; }
            .callout-positive-dm { background-color: #202a22 !important; }
            .callout-info-dm { background-color: #20242a !important; }
        }

        /* Outlook mobile dark mode */
        [data-ogsc] .body-bg { background-color: #1a1a18 !important; }
        [data-ogsc] .email-body-bg { background-color: #222220 !important; }
        [data-ogsc] .card-bg { background-color: #2a2927 !important; }
        [data-ogsc] .text-main { color: #e0ddd8 !important; }
        [data-ogsc] .heading-dm { color: #ece9e4 !important; }
        [data-ogsc] .text-muted { color: #a8a49e !important; }
        [data-ogsc] .email-link { color: #c8c4be !important; }
        [data-ogsc] .divider-line { border-color: #3a3835 !important; }
        [data-ogsc] .footer-bg { background-color: #1a1a18 !important; }
        [data-ogsc] .btn-primary { background-color: #e0ddd8 !important; color: #1a1a18 !important; }
        [data-ogsc] .btn-secondary { color: #e0ddd8 !important; border-color: #e0ddd8 !important; }
        [data-ogsc] .avatar-name-dm { color: #ece9e4 !important; }
        [data-ogsc] .avatar-subtitle-dm { color: #a8a49e !important; }
        [data-ogsc] .stat-card-dm { background-color: #2a2927 !important; }
        [data-ogsc] .stat-label-dm { color: #a8a49e !important; }
        [data-ogsc] .timeline-border-dm { border-color: #3a3835 !important; }
        [data-ogsc] .timeline-text-dm { color: #e0ddd8 !important; }
        [data-ogsc] .timeline-time-dm { color: #a8a49e !important; }
        [data-ogsc] .bar-chart-dm { background-color: #2a2927 !important; }
        [data-ogsc] .bar-track-dm { background-color: #1a1a18 !important; }
        [data-ogsc] .bar-label-dm { color: #a8a49e !important; }
        [data-ogsc] .contributor-card-dm { background-color: #2a2927 !important; }
        [data-ogsc] .contributor-meta-dm { color: #a8a49e !important; }
        [data-ogsc] .callout-critical-dm { background-color: #2a2220 !important; }
        [data-ogsc] .badge-critical-dm { color: #f0a094 !important; }
        [data-ogsc] .badge-warning-dm { color: #e6c27a !important; }
        [data-ogsc] .badge-positive-dm { color: #8fd3a5 !important; }
        [data-ogsc] .badge-info-dm { color: #9cc9ec !important; }
        [data-ogsc] .callout-positive-dm { background-color: #202a22 !important; }
        [data-ogsc] .callout-info-dm { background-color: #20242a !important; }
    </style>
    <style>
        .tfix { width: 100% !important; table-layout: fixed !important; }
    </style>
</head>"""

_OPEN_BODY = """<body style="margin:0; padding:0; background-color:#f5f3f1; width:100%; -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%;" class="body-bg">

    <!-- Preheader text (hidden) -->
    <div style="display:none; font-size:1px; color:#f5f3f1; line-height:1px; max-height:0px; max-width:0px; opacity:0; overflow:hidden; mso-hide:all;" class="preheader-bg">
        __PREHEADER__
        &zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;
    </div>

    <!-- Outer background table -->
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background-color:#f5f3f1;" class="body-bg">
    <tr>
    <td align="center" valign="top" style="padding:20px 10px;">

        <!-- Ghost table for Outlook -->
        <!--[if mso]>
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="600" align="center">
        <tr>
        <td>
        <![endif]-->

        <!-- Email container -->
        <div style="max-width:600px; width:100%; margin:0 auto;" class="email-container">


"""

_CLOSE_BODY = """        </div>
        <!-- /Email container -->

        <!--[if mso]>
        </td>
        </tr>
        </table>
        <![endif]-->

    </td>
    </tr>
    </table>
    <!-- /Outer background table -->

</body>
</html>
"""

def head(title):
    return _HEAD.replace("__TITLE__", esc(title), 1)


def open_body(preheader):
    return _OPEN_BODY.replace("__PREHEADER__", esc(preheader), 1)


def close_body():
    return _CLOSE_BODY


PRESENTATION = 'role="presentation" cellspacing="0" cellpadding="0" border="0"'


def section_open():
    return f'<table {PRESENTATION} width="100%" style="background-color:{BG};" class="email-body-bg">'


def section_close():
    return "</table>"


def cell(inner, pad="16px 40px 0 40px"):
    """inner is composed HTML; text belongs in p(), small(), or another escaping helper."""
    if not isinstance(pad, str) or not re.fullmatch(r"[0-9.px% ]+", pad):
        raise DigestError("Invalid cell padding")
    return f'<tr><td style="padding:{pad};" class="body-cell">{inner}</td></tr>'


def h2(text):
    return (f'<h2 class="email-h2 heading-dm" style="margin:0; Margin:0; font-family:{FONT_HEADING}; font-size:22px; '
            f'font-weight:700; line-height:1.3; letter-spacing:-0.015em; color:{INK};">{esc(text)}</h2>')


def h3(text):
    return (f'<h3 class="heading-dm" style="margin:0; Margin:0; font-family:{FONT_HEADING}; font-size:18px; '
            f'font-weight:600; line-height:1.3; color:{INK};">{esc(text)}</h3>')


def p(text):
    return (f'<p style="margin:0; Margin:0; font-family:{FONT_BODY}; font-size:16px; line-height:1.6; '
            f'letter-spacing:0.01em; color:{INK};" class="text-main">{esc(text)}</p>')


def lead(text):
    return (f'<p style="margin:0; Margin:0; font-family:{FONT_BODY}; font-size:18px; line-height:1.55; '
            f'color:{MUTED};" class="text-muted">{esc(text)}</p>')


def small(text):
    return (f'<p style="margin:0; Margin:0; font-family:{FONT_BODY}; font-size:13px; line-height:1.5; '
            f'color:{CAPTION};" class="text-muted">{esc(text)}</p>')


def masthead(eyebrow, title, lead_text=None, caption=None):
    return (section_open()
            + f'<tr><td style="padding:40px 40px 10px 40px; text-align:left;" class="body-cell"><p style="margin:0; '
              f'Margin:0; font-family:{FONT_HEADING}; font-size:12px; font-weight:600; letter-spacing:0.08em; '
              f'text-transform:uppercase; color:{MUTED};" class="text-muted heading-dm">{esc(eyebrow)}</p></td></tr>'
            + cell(f'<h1 class="email-h1 heading-dm text-main" style="margin:0; Margin:0; font-family:{FONT_HEADING}; '
                   f'font-size:30px; font-weight:700; line-height:1.1; letter-spacing:-0.02em; color:{INK};">'
                   f'{esc(title)}</h1>', "10px 40px 0 40px")
            + ("" if lead_text is None else cell(lead(lead_text)))
            + ("" if caption is None else cell(small(caption)))
            + cell(f'<table {PRESENTATION} width="100%"><tr><td style="border-top:2px solid {INK}; font-size:1px; '
                   'line-height:1px; mso-line-height-rule:exactly;" class="header-border">&nbsp;</td></tr></table>',
                   "24px 40px 0 40px")
            + section_close())


def table(headers, rows, aligns=None, striped=True, widths=None):
    """Plain cells are escaped. Use {"html": fragment} only for shell-generated markup."""
    def alignment(index):
        align = aligns[index] if aligns is not None and index < len(aligns) and aligns[index] is not None else "left"
        if align not in ("left", "center", "right"):
            raise DigestError("Invalid table alignment")
        return align

    heading = ""
    for index, label in enumerate(headers):
        width = widths[index] if widths is not None and index < len(widths) else None
        if width is not None and not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?%?", js_string(width)):
            raise DigestError("Invalid table width")
        width_attr = "" if width is None else f' width="{esc(width)}"'
        heading += (f'<th align="{alignment(index)}"{width_attr} style="padding:10px 12px; font-family:{FONT_HEADING}; '
                    'font-weight:600; font-size:13px; text-transform:uppercase; letter-spacing:0.03em; '
                    f'border-bottom:2px solid {INK}; word-break:normal; overflow-wrap:normal; hyphens:none; '
                    f'color:{INK};" class="heading-dm header-border">{esc(label)}</th>')
    body = ""
    for row_index, row in enumerate(rows):
        stripe = (f' style="background-color:{STRIPE};" class="table-stripe"'
                  if striped and row_index % 2 == 0 else "")
        body += f"<tr{stripe}>"
        for index, value in enumerate(row):
            inner = value["html"] if isinstance(value, dict) and "html" in value else esc(value)
            align = ("" if aligns is None or index >= len(aligns) or aligns[index] is None
                     else f' align="{alignment(index)}"')
            style = "" if striped else f" border-bottom:1px solid {RULE};"
            hook = "" if striped else ' class="divider-line"'
            body += f'<td{align} style="padding:10px 12px;{style}"{hook}>{inner}</td>'
        body += "</tr>"
    return (f'<table cellspacing="0" cellpadding="0" border="0" width="100%" style="font-family:{FONT_BODY}; '
            f'font-size:14px; line-height:1.5; color:{INK}; border-collapse:collapse;" class="text-main">'
            f"<tr>{heading}</tr>{body}</table>")


def _css_color(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise DigestError("Invalid color")
    return value


def _stat_rows(count):
    if count <= 3:
        return [count]
    if count == 4:
        return [2, 2]
    sizes = [3] * (count // 3)
    if count % 3:
        sizes.append(count % 3)
    return sizes


def stat_grid(stats):
    """Plain table rows of (value, label[, color]) stat cards; place inside cell()."""
    values = list(stats)
    if not values:
        return ""
    html = ""
    position = 0
    for size in _stat_rows(len(values)):
        row = values[position:position + size]
        position += size
        three = size == 3
        value_hook = "stat-value heading-dm" + (" stat-value-3" if three else "")
        card_hook = "stat-card-dm" + (" stat-card-3" if three else "")
        cell_width = f"{100 / size:.4g}%"
        html += (f'<table {PRESENTATION} width="100%" align="center" style="width:100%; max-width:{168 * size}px; '
                 'margin:0 auto; table-layout:fixed;" class="stat-row"><tr>')
        for stat in row:
            value, label = stat[0], stat[1]
            color = stat[2] if len(stat) > 2 else INK
            html += (f'<td width="{cell_width}" valign="top" align="center" style="padding:4px;" class="stat-cell">'
                     f'<table {PRESENTATION} width="100%"><tr><td bgcolor="{CARD}" style="background-color:{CARD}; '
                     f'padding:16px 12px; text-align:center;" class="{card_hook}"><p style="margin:0; Margin:0; '
                     f'font-family:{FONT_HEADING}; font-size:32px; font-weight:700; line-height:1.1; '
                     f'white-space:nowrap; color:{_css_color(color)};" class="{value_hook}">{esc(value)}</p>'
                     f'<p style="margin:4px 0 0 0; Margin:4px 0 0 0; font-family:{FONT_HEADING}; font-size:11px; '
                     'font-weight:600; text-transform:uppercase; letter-spacing:0.04em; '
                     f'color:{STAT_LABEL};" class="stat-label-dm">{esc(label)}</p></td></tr></table></td>')
        html += "</tr></table>\n"
    return html


_BADGES = {
    "default": ("5px 10px", "#e8e6e3", INK, "badge-bg", ""),
    "outline": ("4px 9px", "transparent", INK, "badge-outline", " border:1px solid #888888;"),
    "muted": ("5px 10px", "#dddad7", MUTED, "badge-bg text-muted", ""),
    "critical": ("5px 10px", "#fdf0ee", RED, "callout-critical-dm badge-critical-dm", ""),
    "warning": ("5px 10px", "#faf3e6", "#8a6520", "callout-warning-bg badge-warning-dm", ""),
    "positive": ("5px 10px", "#f0f8f2", GREEN, "callout-positive-dm badge-positive-dm", ""),
    "info": ("5px 10px", "#eef5fb", BLUE, "callout-info-bg badge-info-dm", ""),
}


def badge(text, variant="default", color=None):
    if variant not in _BADGES:
        raise DigestError("Invalid badge variant")
    padding, bg, default_color, classes, border = _BADGES[variant]
    shown = default_color if color is None else _css_color(color)
    return (f'<span style="display:inline-block; font-family:{FONT_HEADING}; font-size:11px; font-weight:600; '
            f'line-height:1; padding:{padding}; border-radius:12px; background-color:{bg}; color:{shown}; '
            f'text-transform:uppercase; letter-spacing:0.03em;{border}" class="{classes}">{esc(text)}</span>')


# kind: (bar colour, title colour, background, classes, bar class, table attrs, weight, tracking, line height)
_CALLOUTS = {
    "note": (INK, INK, STRIPE, "callout-info-bg", "callout-info-border", ' class="callout-info-bg"', 600, "0.03em", "1.6"),
    "warning": (AMBER, "#8a6520", "#faf3e6", "callout-warning-bg", "", ' class="callout-warning-bg"', 600, "0.03em",
                "1.6"),
    "critical": (RED, RED, "#fdf0ee", "callout-critical-dm", "", ' style="margin-bottom:16px;"', 700, "0.04em", "1.55"),
    "positive": (GREEN, GREEN, "#f0f8f2", "callout-positive-dm", "", ' style="margin-bottom:16px;"', 700, "0.04em",
                 "1.55"),
    "info": (BLUE, BLUE, "#eef5fb", "callout-info-dm", "", "", 700, "0.04em", "1.55"),
}


def callout(kind, title, body):
    """body is plain text or a list of plain-text lines."""
    if kind not in _CALLOUTS:
        raise DigestError("Invalid callout kind")
    color, title_color, bg, classes, border, table_attrs, weight, tracking, line_height = _CALLOUTS[kind]
    lines = "<br />".join(esc(line) for line in (body if isinstance(body, (list, tuple)) else [body]))
    bar_class = f' class="{border}"' if border else ""
    return (f'<table {PRESENTATION} width="100%"{table_attrs}><tr><td width="4" bgcolor="{color}" '
            f'style="background-color:{color};"{bar_class}></td><td bgcolor="{bg}" style="background-color:{bg}; '
            f'padding:16px 20px;" class="{classes}"><p style="margin:0; Margin:0 0 4px 0; font-family:{FONT_HEADING}; '
            f'font-size:13px; font-weight:{weight}; text-transform:uppercase; letter-spacing:{tracking}; '
            f'color:{title_color};" class="heading-dm">{esc(title)}</p><p style="margin:0; Margin:0; '
            f'font-family:{FONT_BODY}; font-size:15px; line-height:{line_height}; color:{INK};" class="text-main">'
            f"{lines}</p></td></tr></table>")


def button(label, href, secondary=False):
    kind = "btn-secondary" if secondary else "btn-primary"
    td_style = "" if secondary else f" background-color:{INK};"
    td_bg = "" if secondary else f' bgcolor="{INK}"'
    return (f'<table {PRESENTATION}><tr><td style="border-radius:6px;{td_style}"{td_bg} class="{kind}">'
            f'<a href="{esc(href)}" style="display:inline-block; padding:12px 28px; font-family:{FONT_HEADING}; '
            f'font-size:15px; font-weight:600; line-height:1.2; color:{INK if secondary else BG}; '
            f'text-decoration:none; border-radius:6px; border:2px solid {INK};'
            f'{" background-color:transparent;" if secondary else ""}" class="{kind}">{esc(label)}</a></td></tr></table>')


def divider():
    return (f'<table {PRESENTATION} width="100%"><tr><td style="border-top:1px solid {RULE}; font-size:1px; '
            'line-height:1px; mso-line-height-rule:exactly;" class="divider-line">&nbsp;</td></tr></table>')


def spacer():
    return (section_open() + '<tr><td style="padding:40px 0 0 0; font-size:1px; line-height:1px; '
            'mso-line-height-rule:exactly;">&nbsp;</td></tr>' + section_close())


def footer(title, lines, links=(), address_lines=()):
    link_html = ""
    if links:
        link_html = (f'<p style="margin:0; Margin:0 0 8px 0; font-family:{FONT_BODY}; font-size:12px; line-height:1.5; '
                     f'color:{MUTED}; text-align:center;" class="text-muted">'
                     + " &nbsp;&middot;&nbsp; ".join(
                         f'<a href="{esc(href)}" style="color:{MUTED}; text-decoration:underline;" '
                         f'class="email-link">{esc(label)}</a>' for label, href in links)
                     + "</p>")
    address_html = ""
    if address_lines:
        address_html = (f'<p style="margin:0; Margin:0; font-family:{FONT_BODY}; font-size:11px; line-height:1.4; '
                        'color:#888888; text-align:center;" class="text-muted">'
                        + "<br />".join(esc(line) for line in address_lines) + "</p>")
    return (f'<table {PRESENTATION} width="100%"><tr><td bgcolor="{STRIPE}" style="background-color:{STRIPE}; '
            'padding:32px 40px; border-radius:0 0 6px 6px;" class="footer-bg body-cell"><p style="margin:0; '
            f'Margin:0 0 8px 0; font-family:{FONT_HEADING}; font-size:13px; font-weight:600; color:{INK}; '
            f'text-align:center;" class="heading-dm">{esc(title)}</p><p style="margin:0; Margin:0 0 16px 0; '
            f'font-family:{FONT_BODY}; font-size:12px; line-height:1.5; color:{MUTED}; text-align:center;" '
            f'class="text-muted">{"<br />".join(esc(line) for line in lines)}</p>{link_html}{address_html}'
            "</td></tr></table>")


def document(title, preheader, body_html, footer_html):
    """body_html and footer_html are composed HTML; text slots escape at their helper."""
    return head(title) + open_body(preheader) + body_html + spacer() + footer_html + close_body()
