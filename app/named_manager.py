import subprocess


class NamedManager(object):

    @classmethod
    def run_named(cls) -> None:
        subprocess.run(['named'])

    @classmethod
    def named_checkconf(cls) -> tuple[bool, str]:
        '''
        Runs named-checkconf.
        Returns a tuple (success, msg):
        - success = {True|False}
        - msg: message in case of error
        '''
        proc = subprocess.run(['named-checkconf'], 
                              stdout=subprocess.PIPE, 
                              stderr=subprocess.STDOUT,
                              text=True)
        if proc.returncode == 0:
            return (True, proc.stdout)
        else:
            return (False, proc.stdout)

    @classmethod
    def named_checkzone(cls, origin, zone_file) -> tuple[bool, str]:
        proc = subprocess.run(['named-checkzone', origin, zone_file], 
                              stdout=subprocess.PIPE, 
                              stderr=subprocess.STDOUT,
                              text=True)
        if proc.returncode == 0:
            return (True, proc.stdout)
        else:
            return (False, proc.stdout)

