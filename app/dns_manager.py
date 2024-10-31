import dns.exception
import dns.resolver
import dns.zone
import logging
import os
import requests

from pathlib import Path
from jinja2 import Environment, FileSystemLoader

from .named_manager import NamedManager

MAIN_ZONE_FILE = '/etc/bind/main-zone'
MAIN_CONFIG_FILE = '/etc/bind/named.conf.local'
USER_ZONES_DIR = '/etc/bind/user-zones'
TEMPLATES_DIR = '/code/templates/bind'
ZONEFILE_TEMPLATE = 'main-zone.j2'
MAIN_CONFIG_TEMPLATE = 'named.conf.local.j2'
USER_ZONE_TEMPLATE = 'user-zone.j2'

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


class PublicIpNotFound(Exception):
    pass


class ZoneManager(object):
    
    def __init__(self) -> None:
        self._public_ip = None
        self.origin = os.getenv('ROOT_DOMAIN', 'example.com.')
        if not self.origin.endswith('.'):
            self.origin += '.'
        logger.info(f'ORIGIN {self.origin}')
        self.jinja_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))

        # user_list = [f for f in Path(USER_ZONES_DIR).iterdir()],
        user_list = ['test', 'santi']
        Path(USER_ZONES_DIR).mkdir(exist_ok=True)
        self.full_reset()
        # self.load_root_zone()

    @property
    def public_ip(self) -> str | None:
        if not self._public_ip:
            try:
                self._public_ip = self.get_public_ip()
            except PublicIpNotFound as e:
                self._public_ip = None
                logger.error(f'Error finding public IP: {e}')
        return self._public_ip

    def full_reset(self) -> None:
        self.reset_main_zone()
        self.reset_all_user_zonefiles()
        self.reset_bind_conf()

    # def load_root_zone(self) -> None:
    #     self.root = dns.zone.from_file(MAIN_ZONE_FILE, relativize=False)

    # def check_zone_file_dnspython(self, zone_file: str, origin: str):
    #     try:
    #         logger.info(f'Checking zone file {zone_file}')
    #         zone = dns.zone.from_file(zone_file, origin=origin)  # Change the origin accordingly
    #         for name, node in zone.nodes.items():
    #             print(f"Records for {name}:")
    #             for record in node.rdatas:
    #                 logger.debug(record)
    #     except FileNotFoundError as e:
    #         logger.error(f'File not found: {zone_file}')
    #     except dns.exception.DNSException as e:
    #         logger.error(f"Error reading zone file: {e}")

    def get_user_zonefile(self, username: str) -> str:
        zonefile = Path(USER_ZONES_DIR) / username
        if not zonefile.exists():
            logger.info(f'Zone file does not exist for user: {username}')
            self.reset_user_zonefile(username)
            self.reset_bind_conf()
        return zonefile.read_text()

    def find_user_list(self):
        return [f.name for f in Path(USER_ZONES_DIR).iterdir() if f.is_file()]

    def reset_main_zone(self):
        user_list = self.find_user_list()
        self.reset_zonefile(self.origin, ZONEFILE_TEMPLATE, MAIN_ZONE_FILE, user_list)

    def reset_user_zonefile(self, username: str) -> None:
        origin = username + '.' + self.origin
        zonefile = Path(USER_ZONES_DIR) / username
        self.reset_zonefile(origin, USER_ZONE_TEMPLATE, zonefile)

    def reset_zonefile(self, origin: str, zone_template: str, zonefile: str|Path, user_list: list[str] = []) -> None:
        logger.info(f'Resetting zone {zonefile}')
        if not self.public_ip:
            return
        template = self.jinja_env.get_template(zone_template)
        data = {
                'origin': origin,
                'ns_ip': self.public_ip,
                'user_list': user_list,
                }
        zone = template.render(data)
        Path(zonefile).write_text(zone)

    def reset_bind_conf(self) -> None:
        '''Reads all user names from `users_dir` and resets bind config config for their zones.'''
        user_list = self.find_user_list()
        self.reset_bind_conf_users(MAIN_CONFIG_TEMPLATE, MAIN_CONFIG_FILE, user_list)

    def reset_bind_conf_users(self, template_file: str, conf_file: str, user_list: list[str]) -> None:
        logger.info(f'Resetting bind config {conf_file}')
        template = self.jinja_env.get_template(template_file)
        data = { 
                'origin': self.origin, 
                'user_list': user_list,
                }
        print(data)
        data = template.render(data)
        Path(conf_file).write_text(data)

    def reset_all_user_zonefiles(self) -> None:
        '''Remove all user zone files and create new ones for user_list'''
        users_dir = USER_ZONES_DIR
        logger.info(f'Resetting user zones dir {users_dir}')
        try:
            os.rmdir(users_dir)
            os.mkdir(users_dir)
        except Exception as e:
            logger.error(f'Error resetting user zone dir {users_dir}: {e}')
        for user in self.find_user_list():
            self.reset_user_zonefile(user)

    def get_public_ip(self) -> str | None:
        urls = [
            "https://ifconfig.me",
            "https://api.ipify.org",
        ]
        for url in urls:
            try:
                response = requests.get(url)
                if response.status_code == 200:
                    logger.info(f'Found public IP {response.text} from {url}')
                    return response.text
            except requests.RequestException as e:
                raise PublicIpNotFound(e)

