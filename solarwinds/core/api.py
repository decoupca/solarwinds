import requests
from orionsdk import SwisClient
from requests.packages.urllib3.exceptions import InsecureRequestWarning


class API(object):
    def __init__(self, host, username, password, validate_cert=False, **kwargs):
        if not validate_cert:
            requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
        self.host = host
        self.username = username
        self.password = password
        self.swis = SwisClient(host, username, password)