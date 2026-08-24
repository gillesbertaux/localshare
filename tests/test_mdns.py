from __future__ import annotations

from localshare.mdns import MAX_STARTS, Advertisement, Publisher


def test_dns_sd_argv_registers_host_and_service() -> None:
    publisher = Publisher(binary="/usr/bin/dns-sd", kind="dns-sd")
    assert publisher.argv("venue", "192.168.1.24", 80) == [
        "/usr/bin/dns-sd",
        "-P",
        "venue",
        "_http._tcp",
        "local",
        "80",
        "venue.local",
        "192.168.1.24",
    ]


def test_avahi_argv_registers_address_record() -> None:
    publisher = Publisher(binary="/usr/bin/avahi-publish", kind="avahi-publish")
    assert publisher.argv("venue", "192.168.1.24", 80) == [
        "/usr/bin/avahi-publish",
        "-a",
        "-R",
        "venue.local",
        "192.168.1.24",
    ]


def test_advertisement_stops_retrying_a_failing_responder() -> None:
    ad = Advertisement(
        Publisher(binary="/usr/bin/true", kind="dns-sd"), "venue", "192.168.1.24", 80
    )
    ad.starts = MAX_STARTS
    ad.start()
    assert ad.exhausted is True
    assert ad.alive is False
