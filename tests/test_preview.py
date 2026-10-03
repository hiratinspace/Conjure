import numpy as np

from pipeline.preview import Preview, draw_text_lines


def test_disabled_preview_never_opens_a_window():
    preview = Preview(enabled=False)
    assert preview.show(np.zeros((10, 10, 3), np.uint8), lines=["x"]) is None
    assert not preview._window_open


def test_draw_text_lines_marks_the_frame():
    frame = np.zeros((60, 200, 3), np.uint8)
    draw_text_lines(frame, ["30.0 fps"])
    assert frame.any()
