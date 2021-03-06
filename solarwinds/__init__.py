from solarwinds.client import SwisClient
from solarwinds.models.orion import Orion


class api(object):
    def __init__(self, hostname, username, password, verify=False, timeout=60):
        self.hostname = hostname
        self.username = username
        self.password = password
        self.swis = SwisClient(
            hostname=hostname,
            username=username,
            password=password,
            verify=verify,
            timeout=timeout,
        )
        self.orion = Orion(self.swis)


__all__ = [api]
