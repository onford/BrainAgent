import gc
import warnings

import pytest

from app.owned_thread import _owned_thread


def test_missing_event_loop_does_not_leak_coroutine_or_start_work():
    calls = []
    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter('always')
        operation = _owned_thread(lambda: calls.append('started'))
        with pytest.raises(RuntimeError, match='no running event loop'):
            operation.send(None)
        operation.close()
        gc.collect()
    assert calls == []
    assert not any(issubclass(item.category, RuntimeWarning) for item in observed)
