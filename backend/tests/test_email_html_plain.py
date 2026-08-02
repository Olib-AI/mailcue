"""Tests for the generated text/plain alternative of HTML email."""

from app.emails.service import _html_to_plain_text


def test_html_to_plain_text_preserves_paragraph_boundaries() -> None:
    html = (
        "<p>Hi there,</p>"
        "<p>This is a quick check on the schedule for the coming days. "
        "Let me know if anything has changed.</p>"
        "<p>Best,</p>"
    )

    assert _html_to_plain_text(html) == (
        "Hi there,\n\n"
        "This is a quick check on the schedule for the coming days. "
        "Let me know if anything has changed.\n\n"
        "Best,"
    )


def test_html_to_plain_text_handles_breaks_lists_entities_and_hidden_content() -> None:
    html = """
        <head><title>Not message content</title></head>
        <p>Hello <strong>Tom &amp; Jerry</strong><br>Next line</p>
        <ul><li>First item</li><li>Second item</li></ul>
        <script>tracking()</script><style>.hidden { display: none }</style>
    """

    assert _html_to_plain_text(html) == (
        "Hello Tom & Jerry\nNext line\n\n- First item\n- Second item"
    )
