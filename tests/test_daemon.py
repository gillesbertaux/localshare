from __future__ import annotations

import pytest

from localshare.daemon import _Daemon, candidate_ports


def test_candidate_ports_never_repeats_the_preference() -> None:
    assert candidate_ports(None) == [80, 7777]
    assert candidate_ports(80) == [80, 7777]
    assert candidate_ports(7777) == [7777, 80]
    assert candidate_ports(8080) == [8080, 80, 7777]


class _StubAd:
    """An advertisement that has already used up its restart budget."""

    hostname = "venue"
    starts = 5
    alive = False
    exhausted = True

    def start(self) -> None:
        raise AssertionError("an exhausted advertisement must not be restarted")


def test_daemon_reports_a_name_it_gave_up_on_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    daemon = _Daemon(preferred_port=None)
    daemon.ads = {"venue": _StubAd()}  # type: ignore[dict-item]

    daemon._keep_ads_alive()
    daemon._keep_ads_alive()

    assert capsys.readouterr().err.count("gave up advertising venue.local") == 1
