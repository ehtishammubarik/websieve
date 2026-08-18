from websieve.clean.boilerplate import extract

BODY = (
    "Running GPU workloads on Kubernetes requires the device plugin to advertise "
    "nvidia.com/gpu as a schedulable resource across every node in the pool."
)
BODY2 = (
    "MIG partitioning lets a single A100 present as up to seven independent "
    "instances, which changes the bin packing problem for inference workloads."
)

PAGE = f"""<html><head><title>Tom &amp; Jerry&#39;s Blog</title></head><body>
<nav><a href="/">Home</a><a href="/a">About</a><a href="/c">Contact</a></nav>
<article><h1>GPU scheduling</h1><p>{BODY}</p><p>{BODY2}</p></article>
<footer><a href="/p">Privacy</a><a href="/t">Terms</a></footer>
<script>var tracking = 1;</script></body></html>"""


def test_extracts_body_text():
    text, _ = extract(PAGE)
    assert BODY in text and BODY2 in text


def test_drops_nav_footer_and_script():
    text, _ = extract(PAGE)
    for junk in ("Home", "About", "Privacy", "Terms", "var tracking"):
        assert junk not in text


def test_keeps_heading_adjacent_to_body():
    text, _ = extract(PAGE)
    assert "GPU scheduling" in text


def test_decodes_title_entities():
    _, title = extract(PAGE)
    assert title == "Tom & Jerry's Blog"


def test_empty_and_whitespace_input():
    assert extract("") == ("", None)
    assert extract("   ") == ("", None)


def test_malformed_html_does_not_raise():
    text, _ = extract("<div><p>unclosed " + BODY)
    assert isinstance(text, str)


def test_no_body_content_returns_empty_text():
    text, title = extract("<html><head><title>T</title></head><body></body></html>")
    assert text == ""
    assert title == "T"


def test_inline_tags_do_not_fuse_words():
    text, _ = extract(f"<p>{BODY} <em>emphasis</em> tail continues here.</p>")
    assert "emphasistail" not in text


def test_fragmented_short_paragraphs_survive_a_dominant_sidebar():
    paragraphs = [f"Body segment {index} keeps linked evidence nearby." for index in range(1, 7)]
    rendered = [
        paragraph.replace("linked evidence", '<a href="/source">linked evidence</a>')
        for paragraph in paragraphs
    ]
    sidebar = "Unrelated sidebar promotion " * 9
    page = (
        "<article>"
        + "".join(f"<p>{paragraph}</p>" for paragraph in rendered[:3])
        + f'<div class="sidebar">{sidebar}</div>'
        + "".join(f"<p>{paragraph}</p>" for paragraph in rendered[3:])
        + "</article>"
    )

    text, _ = extract(page)

    assert all(paragraph in text for paragraph in paragraphs)


def test_long_unsemantic_link_cloud_stays_outside_body_run():
    link_cloud = "".join(
        f'<a href="/related/{index}">Related story {index}</a>' for index in range(12)
    )

    text, _ = extract(f"<div>{link_cloud}</div><p>{BODY}</p><div>{link_cloud}</div>")

    assert BODY in text
    assert "Related story" not in text
