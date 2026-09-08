from app.workflows.source_reader import PageText


def test_ordered_protocol_steps_keep_run_numbers_and_nested_lists():
    page = PageText("https://example.org/dataset")
    page.feed(
        "<ol><li>eyes open</li><li>eyes closed</li>"
        "<li>movement<ul><li>left/right</li></ul></li>"
        "<li>imagery</li></ol>"
        '<ol start="8"><li>imagery</li><li value="12">imagery</li></ol>'
        '<ol start="4" reversed><li>four</li><li>three</li></ol>'
        "<script><ol><li>hidden</li></ol></script>"
    )
    assert page.parts == [
        "1.",
        "eyes open",
        "2.",
        "eyes closed",
        "3.",
        "movement",
        "left/right",
        "4.",
        "imagery",
        "8.",
        "imagery",
        "12.",
        "imagery",
        "4.",
        "four",
        "3.",
        "three",
    ]
