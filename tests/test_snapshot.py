import cv2
import numpy as np
import pytest

from lorwright.core.util.snapshot import save_snapshot


@pytest.mark.parametrize("failure", [None, False, cv2.error("encode failed")])
def test_save_snapshot_returns_only_written_paths(tmp_path, monkeypatch, failure):
    image = np.zeros((12, 12, 3), np.uint8)
    if failure is not None:
        def write_error(*args):
            if isinstance(failure, Exception):
                raise failure
            return failure

        monkeypatch.setattr(cv2, "imwrite", write_error)

    path = save_snapshot(image, tmp_path, tag="stop")
    if failure is None:
        assert path is not None and path.is_file()
        assert np.array_equal(cv2.imread(str(path)), image)
    else:
        assert path is None
