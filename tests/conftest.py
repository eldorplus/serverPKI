
from pathlib import Path
from subprocess import Popen, PIPE
import pty, re, os, re, shutil, sys, typing

import pytest

from serverPKI.db import DbConnection as dbc
from serverPKI.utils import parse_config, parse_options, Pathes
from .parameters import CLIENT_CERT_1, SERVICE, TEST_PLACE_1, CA_CERT_PASS_PHASE
error_marker =  re.compile('ERROR|FATAL|STATEMENT|HINT')

DEFAULT_DB = 'postgres'
TEMP_DIR = ((Path(__file__).parent.resolve()) / 'tmpdir').resolve()
INSTALL_DIR = ((Path(__file__).parent.parent.resolve()) / 'install').resolve()
FRESH_INSTALL_DIR = INSTALL_DIR / 'fresh_install'


config_file = None

##def setup_directories(Optional[only] = None) -> None:

def get_config_path():
    cd = Path(__file__).parent.resolve()
    config_file = (cd / 'conf' / 'serverpki.conf' ).resolve()
    return config_file

def setup_directories(only: typing.Optional[str] = None) -> None:
    """
    Make sure work and db directories exist and clear them.
    :param only: Optional path to clear
    :return: None
    """
    if only:
        shutil.rmtree(only)
        os.makedirs(only, mode=0o750)
    else:
        shutil.rmtree(Pathes.home)
        os.makedirs(Pathes.work, mode=0o750)
        os.makedirs(Pathes.db, mode=0o750)

def run_command(cmd):
    p = process = Popen(cmd, stdout=PIPE, stderr=PIPE, text=True)
    stdout, stderr = p.communicate()
    print(stdout)
    print(stderr)
    return (p.returncode, stdout)


def get_hostname():
    status, stdout = run_command('hostname')
    return stdout.strip()


class Psql(object):

    global config_file

    from serverPKI.utils import DBAccount

    parse_options()
    parse_config(str(config_file))

    db_default_db = DEFAULT_DB
    install_dir = INSTALL_DIR
    fresh_install_dir = FRESH_INSTALL_DIR

    db_host = DBAccount.dbHost
    db_port = str(DBAccount.dbPort)
    db_user = DBAccount.dbUser
    dba_user = DBAccount.dbDbaUser
    db_database = DBAccount.dbDatabase

    def __init__(self):
        pass

    def run_psql(self,
                 cmd: str = None,
                 sql_file: str = None,
                 alt_db: bool = False,
                 run_as_dba: bool = False) -> typing.Tuple[str, str, int]:
        """
        Send SQL to server, using psql utility
        :param cmd: Issue this SQL command
        :param sql_file: Let server execute this SQL file
        :param alt_db: Use alternate DB (usually 'postgres')
        :param run_as_dba: User dba username from config for connection
        :return: (stdout, stderr, status)
        """

        if run_as_dba:
            if self.dba_user:
                user_option = ('-U', self.dba_user)
            else:
                user_option = tuple()
        else:
            user_option = ('-U', self.db_user)

        cmds = ('psql',
                '-h', self.db_host,
                '-p', self.db_port,
                '-d', self.db_database if not alt_db else self.db_default_db)
        if cmd:
            print(cmd)
            p = Popen(cmds + ('-c', cmd) + user_option,
                      stdout=PIPE, stderr=PIPE, text=True)
        elif sql_file:
            p = Popen(cmds + ('-f', sql_file) + user_option,
                      stdout=PIPE, stderr=PIPE, text=True)
        else:
            assert False, 'tests.db.Psql.run_psql missing one of args "cmd" or "sql_file"'

        stdout, stderr = p.communicate()

        status = p.returncode
        if p.returncode:
            print('?Failed with status={}. Error message follows:'.format(p.returncode))
            print(stderr)
        for line in re.split("\n+", stderr):
            if error_marker.search(line):
                print(line)
                status = -1

        return (stdout, stderr, status)


class Db(object):

    def __init__(selfself):
        pass

    def open(self):
        pe = dbc('serverpki')
        self.db = pe.open()

        return self.db


@pytest.fixture(scope="package")
def psql_handle():

    psql = Psql()

    missing_role_msg = """
    CREATE ROLE "{}" WITH
      LOGIN
      NOSUPERUSER
      INHERIT
      CREATEDB
      NOCREATEROLE
      NOREPLICATION;
    ALTER ROLE "{}" SET search_path TO pki, dd, public;
    """.format(psql.db_user, psql.db_user)
    
    # just test, if we can connect to server
    (stdout, stderr, status) = psql.run_psql(cmd='SELECT NOW();', alt_db=True)
    if status:
        print('[? missing role {} ?? - create it first:]'.format(
            psql.db_user))
        print(missing_role_msg)
        sys.exit(1)

    print('[(Re)creating database {}]'.format(psql.db_database))
    (stdout, stderr, status) = psql.run_psql(
        cmd='DROP DATABASE IF EXISTS "{}";'.format(
            psql.db_database),
        alt_db=True)
    if status:
        sys.exit(1)

    (stdout, stderr, status) = psql.run_psql(
        cmd='CREATE DATABASE "{}"'.format(
            psql.db_database),
        alt_db=True)
    if status:
        assert False

    print('[Creating schemd dd]')
    sql_file = str(psql.fresh_install_dir / 'create_schema_dd.sql')
    (stdout, stderr, status) = psql.run_psql(sql_file=sql_file)
    if status:
        assert False

    print('[Creating extension citext]')
    sql_file = str(psql.fresh_install_dir / 'create_extension_citext.sql')
    (stdout, stderr, status) = psql.run_psql(sql_file=sql_file, run_as_dba=True)
    if status:
        assert False

    print('[Creating schemd pki]')
    sql_file = str(psql.fresh_install_dir / 'create_schema_pki.sql')
    (stdout, stderr, status) = psql.run_psql(sql_file=sql_file)
    if status:
        assert False

    print('[Loading services]')
    sql_file = str(psql.fresh_install_dir / 'load_services.sql')
    (stdout, stderr, status) = psql.run_psql(sql_file=sql_file)
    if status:
        assert False

    """
    print('[Loading test data]')
    with open(str(INSTALL_DIR / 'load_testdata.sql'), 'r') as sql_file:
        (stdout, stderr, status) = psql.run_psql(sql_file=fd)
        if status:
            assert False
    """
    print('[Creating triggers and functions of schema pki]')
    sql_file = str(psql.fresh_install_dir / 'create_triggers_pki.sql')
    (stdout, stderr, status) = psql.run_psql(sql_file=sql_file)
    if status:
        assert False

    yield psql
    psql = None

@pytest.fixture(scope="package")
def db_handle(psql_handle):

    db = Db()
    yield db.open()
    db = None


@pytest.fixture(scope="package")
def create_local_cert_meta(db_handle):

    result = db_handle.query.first("""
    INSERT INTO DISTHOSTS (fqdn) VALUES($1::TEXT)""", get_hostname())
    assert result == 1

    result = db_handle.query.first("""
    INSERT INTO PLACES(name, cert_path) VALUES($1::TEXT, $2::TEXT)""",
                                   TEST_PLACE_1, str(TEMP_DIR))
    assert result == 1

    result = db_handle.query.first("""
    SELECT * FROM add_cert($1::TEXT::citext, 'client'::TEXT::subject_type, 'local'::TEXT::cert_type, 'rsa'::TEXT::cert_encryption_algo, 'False', NULL, NULL, NULL, $2::TEXT::citext, NULL, $3::TEXT::citext)
    """, CLIENT_CERT_1, get_hostname(), TEST_PLACE_1)
    print(result)

@pytest.fixture(scope="package")
def create_CAcert_from_scratch(db_handle):

    master, slave = pty.openpty()
    p = Popen(('operate_serverPKI', '--issue-local-CAcert', '-f', config_file) ,
              stdin=slave, text=True, shell=True)
    os.write(master, str(CA_CERT_PASS_PHASE + '\n' + CA_CERT_PASS_PHASE + '\n').encode("UTF-8"))
    p.wait()
    os.close(master)
    os.close(slave)
    stdout, stderr = p.communicate()
    print(stdout)
    print(stderr)
    assert p.returncode == 0


@pytest.fixture(scope="package")
def export_cert(create_CAcert_from_scratch):

    # cleanup work directory and ca files
    # status, stdout = run_command(('rm', '-r', '-f', Pathes.work ))
    assert status == 0

    # export ca files
    # status, stdout = run_command(('operate_serverPKI', '-f', config_file, -E, '1'))
    assert status == 0
