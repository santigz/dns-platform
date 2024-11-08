import base64
import ipaddress
import dns.exception
import dns.resolver
import dns.zone
import hashlib
import hmac
import logging
import os
import requests
import secrets
import shutil

from datetime import datetime, timedelta
from typing import Dict
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from pathlib import Path

from .named_manager import NamedManager, NamedCheckConfError, NamedCheckZoneError, NamedReloadError

# Bind globals
BIND_DIR = '/etc/bind/'
MAIN_ZONE_FILE = '/etc/bind/main-zone'
CUSTOM_RRS_FILE = '/etc/bind/custom-records'
USER_ZONES_DIR = '/etc/bind/user-zones/'
USER_TOKENS_DIR = '/etc/bind/user-tokens/'
BACKUPS_DIR = '/etc/bind/backups/'

# Templates globals
TEMPLATES_DIR = '/code/templates/bind/'
ZONEFILE_TEMPLATE = 'main-zone.j2'
NAMED_CONF_TEMPLATE = 'named.conf.j2'
NAMED_CONF_LOCAL_TEMPLATE = 'named.conf.local.j2'
NAMED_CONF_RNDC_TEMPLATE = 'named.conf.rndc.j2'
RNDC_CONF_TEMPLATE = 'rndc.conf.j2'
USER_ZONE_TEMPLATE = 'user-zone.j2'

PUBLIC_IP_REFRESH = 1 # Hours to refresh the public IP
USER_TOKEN_LENGTH = 16

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


class PublicIpNotFound(Exception):
    pass

class BadZoneFile(Exception):
    pass

class ZoneFileCheckError(Exception):
    pass

class ZoneCreationError(Exception):
    pass



class ZoneManager(object):
    
    def __init__(self, origin) -> None:
        self._public_ip = None
        self._public_ip_last_date = datetime.now() - timedelta(hours=PUBLIC_IP_REFRESH*2)
        self.origin = origin
        if not self.origin.endswith('.'):
            self.origin += '.'
        logger.info(f'ORIGIN {self.origin}')
        self.jinja_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
        Path(USER_ZONES_DIR).mkdir(exist_ok=True)
        Path(USER_TOKENS_DIR).mkdir(exist_ok=True)
        bind_failed = False
        try:
            NamedManager.check_and_run(self.origin, MAIN_ZONE_FILE)
            logger.info('Bind passed checks and is running.')
        except NamedCheckConfError as e:
            bind_failed = True
            logger.error(f'ERROR in named-checkconf!!!!!!\n{e}')
        except NamedCheckZoneError as e:
            bind_failed = True
            contents = Path(MAIN_ZONE_FILE).read_text()
            logger.error(f'Main zone file:\n{contents}')
            logger.error(f'ERROR in named-checkzone in main zone!!!!!!\n{e}')
        if bind_failed:
            try:
                logger.info('Doing a backup and full Bind reset. All previous config is removed.')
                self.backup()
                self.full_reset()
                logger.info('Trying to start bind after reset.')
                NamedManager.check_and_run(self.origin, MAIN_ZONE_FILE)
            except Exception:
                logger.error(f'Failed resetting. Can not continue Bind.')
                raise

    @property
    def public_ip(self) -> str | None:
        delta = datetime.now() - self._public_ip_last_date
        if not self._public_ip or delta > timedelta(hours=PUBLIC_IP_REFRESH):
            try:
                self._public_ip = self.get_public_ip()
                self._public_ip_last_date = datetime.now()
            except PublicIpNotFound as e:
                logger.error(f'Could not find public IP: {e}')
        return self._public_ip

    def full_reset(self) -> None:
        self.reset_main_zone()
        self.reset_all_user_zonefiles()
        self.reset_bind_conf()
        self.reset_rndc()

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

    def user_zone_origin(self, username):
        return username + '.' + self.origin;

    def get_user_zonefile(self, username: str) -> str:
        zonefile = Path(USER_ZONES_DIR) / username
        if not zonefile.exists():
            logger.info(f'Zone file does not exist for user: {username}')
            self.reset_user_zonefile(username)
            self.reset_bind_conf()
        return zonefile.read_text()

    # def zonefile_to_json(self, zonefile: str):
    #     zone = dns.zone.from_file(zonefile, relativize=False)
    #     for (name, node) in zone.items():
    #         print(name)
    #         for rdset in node:
    #             type = rdset.rdtype
    #             print(f'{dns.rdatatype.to_text(rdset.rdtype)}')
    #             for rr in rdset:
    #                 print(f'rr {rr}')
    #         print()

    def find_user_list(self):
        return [f.name for f in Path(USER_ZONES_DIR).iterdir() if f.is_file()]

    def reset_main_zone(self):
        user_list = self.find_user_list()
        self.reset_zonefile(self.origin, ZONEFILE_TEMPLATE, MAIN_ZONE_FILE, user_list)

    def set_user_zonefile(self, username: str, zone_data: str) -> None:
        origin = username + '.' + self.origin
        tmp_zonefile = Path(USER_ZONES_DIR) / Path(username + '.tmp')
        try:
            tmp_zonefile.write_text(zone_data)
            msg = NamedManager.named_checkzone(origin, tmp_zonefile)
        except OSError:
            tmp_zonefile.unlink(missing_ok=True)
            raise Exception('Internal file system error.')
        except NamedCheckZoneError as e:
            tmp_zonefile.unlink(missing_ok=True)
            raise BadZoneFile(e)
        except Exception:
            tmp_zonefile.unlink(missing_ok=True)
            raise ZoneFileCheckError('Unknown error checking the zone.')
        zonefile = Path(USER_ZONES_DIR) / username
        try:
            self.replace_zone_if_reloads(tmp_zonefile, username)
        except NamedReloadError as e:
            raise BadZoneFile('Zone seems OK but there was an error reloading Bind.')

    def replace_zone_if_reloads(self, tmp_zonefile: Path, username: str) -> None:
        zonefile = Path(USER_ZONES_DIR) / username
        zonefile_backup = zonefile.with_suffix('.orig')
        shutil.copy2(zonefile, zonefile_backup)
        tmp_zonefile.replace(zonefile)
        try:
            NamedManager.reload()
            zonefile_backup.unlink()
        except NamedReloadError:
            contents = zonefile.read_text()
            logger.error(f'Passed named-checkzone but reload error for user {username}:\n{contents}')
            shutil.copy2(zonefile_backup, zonefile)
            try:
                NamedManager.reload()
            except NamedReloadError:
                logger.error(f'VERY BAD SITUATION: failed reverting a reload error for user {username}. ******')
                raise
            raise

    def reset_user_zonefile(self, username: str) -> None:
        origin = username + '.' + self.origin
        zonefile = Path(USER_ZONES_DIR) / username
        self.reset_zonefile(origin, USER_ZONE_TEMPLATE, zonefile)

    def custom_records(self):
        try:
            return Path(CUSTOM_RRS_FILE).read_text()
        except:
            return ''

    def reset_zonefile(self, origin: str, zone_template: str, zonefile: str|Path, user_list: list[str] = []) -> str:
        logger.info(f'Resetting zone {zonefile}')
        if not self.public_ip:
            raise ZoneCreationError('No public IP')
        try:
            template = self.jinja_env.get_template(zone_template)
            # TODO: get custom records only for main zone, not for all
            data = {
                    'origin': origin,
                    'ns_ip': self.public_ip,
                    'user_list': user_list,
                    'custom_records': self.custom_records(),
                    }
            zone = template.render(data)
            Path(zonefile).write_text(zone)
            return zone
        except:
            raise ZoneCreationError()


    def reset_bind_conf(self) -> None:
        '''Reads all user names from `users_dir` and resets bind config config for their zones.'''
        user_list = self.find_user_list()
        # self.reset_bind_conf_users(NAMED_CONF_LOCAL_TEMPLATE, NAMED_CONF_LOCAL_FILE, user_list)
        self.write_template(NAMED_CONF_LOCAL_TEMPLATE, 
                            BIND_DIR, 
                            { 
                                'origin': self.origin, 
                                'user_list': user_list,
                            })


    # def reset_bind_conf_users(self, template_file: str, conf_file: str, user_list: list[str]) -> None:
    #     logger.info(f'Resetting bind config {conf_file}')
    #     template = self.jinja_env.get_template(template_file)
    #     data = { 
    #             'origin': self.origin, 
    #             'user_list': user_list,
    #             }
    #     print(data)
    #     data = template.render(data)
    #     Path(conf_file).write_text(data)

    def reset_all_user_zonefiles(self) -> None:
        '''Remove all user zone files and create new ones for user_list'''
        users_dir = USER_ZONES_DIR
        logger.info(f'Resetting user zones dir {users_dir}')
        try:
            shutil.rmtree(users_dir)
            os.mkdir(users_dir)
        except Exception as e:
            logger.error(f'Error resetting user zone dir {users_dir}: {e}')
        for user in self.find_user_list():
            self.reset_user_zonefile(user)

    def get_public_ip(self) -> str | None:
        urls = [
            "https://ifconfig.me",
            "https://api.ipify.org",
            "https://ipinfo.io/ip",
            "https://icanhazip.com",
        ]
        for url in urls:
            try:
                response = requests.get(url)
                if response.status_code == 200:
                    logger.info(f'Found public IP {response.text} from {url}')
                    ip = response.text.strip()
                    ipaddress.IPv4Address(ip) # Throws if ip is invalid
                    return ip
            except:
                logger.warning(f'Failed asking public IP to {url}')
                continue
        raise PublicIpNotFound()



    def write_template(self, template, dir, data):
        name, extension = os.path.splitext(template)
        if extension != '.j2':
            logger.error(f'Template file should have .j2 extension: {template}')
        template = self.jinja_env.get_template(template)
        data = template.render(data)
        file = Path(dir) / name
        Path(file).write_text(data)


    def reset_rndc(self):
        secret_raw = secrets.token_bytes(32)
        rndc_secret = base64.b64encode(secret_raw).decode()
        data = {'rndc_secret': rndc_secret}
        self.write_template(RNDC_CONF_TEMPLATE, BIND_DIR, data)
        self.write_template(NAMED_CONF_RNDC_TEMPLATE, BIND_DIR, data)
        self.write_template(NAMED_CONF_TEMPLATE, BIND_DIR, {})

    def backup(self):
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        bkp_dir = Path(BACKUPS_DIR) / timestamp
        try:
            bkp_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(MAIN_ZONE_FILE, bkp_dir)
            shutil.copy2(CUSTOM_RRS_FILE, bkp_dir)
            shutil.copytree(USER_ZONES_DIR, bkp_dir)
            shutil.copy2('/etc/bind/named.conf.local', bkp_dir)
        except Exception:
            logger.error(f'Failed backup {bkp_dir}.')

    def generate_token(self) -> str:
        raw_token = secrets.token_hex(USER_TOKEN_LENGTH // 2)
        return '-'.join(raw_token[i:i+4] for i in range(0, len(raw_token), 4))

    def load_user_tokens(self) -> Dict[str, str]:
        tokens = {}
        for f_name in Path(USER_TOKENS_DIR).iterdir():
            try:
                if f_name.is_file():
                    tokens[f_name]= f_name.read_text()
            except:
                continue
        return tokens

    def reset_user_token(self, username: str) -> str:
        token = self.generate_token()
        token_file = Path(USER_TOKENS_DIR) / username
        token_file.write_text(token)
        return token

    def get_user_token(self, username: str) -> str:
        tokens = self.load_user_tokens()
        if username in tokens:
            return tokens[username]
        else:
            return self.reset_user_token(username)

    def delete_user_token(self, username) -> None:
        token_file = Path(USER_TOKENS_DIR) / username
        token_file.unlink(missing_ok=True)

    def find_user_for_token(self, token: str) -> str|None:
        tokens = self.load_user_tokens()
        for user_name, user_token in tokens.items():
            if user_token == token:
                return user_name
        return None

