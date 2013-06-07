"""Deploys web application
Usage: fab -H $REMOTE_HOSTNAME  [-u $REMOTE_USERNAME] deploy:bundle_name=$BUNDLE_NAME, \
                        bundle_extracted_name=$BUNDLE_EXTRACTED_NAME, \
                        [do_health_check=True|False], [remote_server=$REMOTE_SERVER]
                        
The '-H $REMOTE_HOSTNAME' is used by ssh/scp and can be configured via SSH config files.
The 'remote_server=$REMOTE_SERVER' is used to make an HTTP request for a health check and may
be the same as $REMOTE_HOSTNAME'
-u is used to override the env.user variable used for ssh connections
@author: Raymond Mauge
$Date$
$Revision$
"""
from fabric.api import *
from fabric.contrib.files import exists
import atexit
import httplib
import os
import re
import shlex
import socket
import subprocess
import time
import sys

# Globals (Dicts populated on separate lines for clarity)
# Adds custom dict to the Fabric global env dict
CONFIG = env['deploy'] = {}
CONFIG['REMOTE_USER'] = 'root' #Can be overridden by '-u $USERNAME' on command line
CONFIG['REMOTE_SERVER'] = None #The health check is run against this host
CONFIG['REMOTE_SERVER_PORT'] = 8080
CONFIG['LIFERAY_HOME'] = '/opt/liferay/'
CONFIG['CURRENT_SYMLINK'] = CONFIG['LIFERAY_HOME'] + 'current'
CONFIG['PREVIOUS_SYMLINK'] = CONFIG['LIFERAY_HOME'] + 'previous'
CONFIG['REMOTE_DEPLOYS_DIR'] = CONFIG['LIFERAY_HOME'] + 'deploys/'
CONFIG['REMOTE_BUNDLES_DIR'] = CONFIG['LIFERAY_HOME'] + 'bundles/'
CONFIG['LOCAL_BUNDLES_DIR'] = '/srv/deploys/liferay/'
CONFIG['BUNDLE_FILE_NAME'] = None # Tar'ed liferay bundle
CONFIG['BUNDLE_EXTRACTED_NAME'] = None #Name when extracted (' un' tar'ed)
CONFIG['HEALTH_CHECK_URL'] = '/web/health/check.jsp'

env.shell = "/bin/bash -l -c -i"

# Approximate time for Liferay initialization
LIFERAY_STARTUP_MINS = 5

if env.ssh_config_path and os.path.isfile(os.path.expanduser(env.ssh_config_path)):
    env.use_ssh_config = True

def get_free_port():
    host = socket.gethostbyname(socket.gethostname())
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((host, 0))
    local_port = s.getsockname()[1]
    s.close()
    return local_port

def current_time_gmt():
    return time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())

@task
def debug():
    print("Custom CONFIG properties:")
    for key, value in CONFIG.iteritems():
        print(key, value)

@task
def enable_puppet():
    print("Enabling Puppet")
    return sudo('puppetd --enable')

@task
def disable_puppet():
    print("Disabling Puppet")
    return sudo('puppetd --disable')

@task
def start_apache():
    print("Starting Apache")
    return sudo('service apache2 start')

@task
def stop_apache():
    print("Stopping Apache")
    return sudo('service apache2 stop')

@task 
def start_liferay():
    print("Starting Liferay")
    return sudo('service liferay start')

@task
def stop_liferay():
    print("Stopping Liferay")
    return sudo('service liferay stop')

def wait_for_liferay():
    # Give Liferay some time to startup before trying
    print("Waiting for {0} minutes while Liferay starts".format(LIFERAY_STARTUP_MINS))
    print("Wait for Liferay started at: {0}".format(current_time_gmt()))
    time.sleep(LIFERAY_STARTUP_MINS * 60)
    print("Wait for Liferay completed at: {0}".format(current_time_gmt()))

"""Return True or False

Attempts an HTTP GET for a health check URL and parses page content.
returns True if attempt is successful and false otherwise
Connects on a local port using a subsequent SSH connection tunnel
"""
@task
def health_check():
    
    if not CONFIG['REMOTE_SERVER']:
        print("No remote server has been set, skipping health check")
        return False
    
    print("Health check started at: {0}".format(current_time_gmt()))

    MAX_ATTEMPTS = 3
    success = False
    
    free_local_port = get_free_port()
    
    tunnel  = SSHTunnel(env.user, env.host_string, CONFIG['REMOTE_SERVER'], dest_port=CONFIG['REMOTE_SERVER_PORT'], local_port=free_local_port)
    
    with settings(warn_only=True):
        for attempts in range(MAX_ATTEMPTS):
            try:
                print ("Running Liferay health check, attempt {0} ...".format(attempts + 1))
                conn  = httplib.HTTPConnection(CONFIG['REMOTE_SERVER'], port=free_local_port,  timeout=5)
                conn.request('GET', CONFIG['HEALTH_CHECK_URL'])
                check_response = conn.getresponse()
                print("Attempt {0}: Got response {1} from Liferay".format(attempts + 1, check_response.status))
                if check_response.status == httplib.OK:
                    data = check_response.read()
                    upAttrMatchObj = re.search(r'ENVIRONMENT STATUS: <span class="success">(.*?)</span>', data, re.IGNORECASE)
                    if upAttrMatchObj:
                        if upAttrMatchObj.group(1) == "UP":
                            success = True
                            break
                conn.close()
            except Exception:
                    #Ignore any exceptions
                    print ("An exception occurred on attempt {0}".format(attempts + 1))
                    print  ("Exception: {0}".format( sys.exc_info()[0] ))
    print("Health check completed at: {0}, success: {1}".format(current_time_gmt(), success))
    return success

@task
def copy_bundle():
    # Copy Liferay bundle to deploy server
    local_bundle_file = CONFIG['LOCAL_BUNDLES_DIR'] + CONFIG['BUNDLE_FILE_NAME']
    print "Copying Liferay bundle, {0}, to remote server, {1}".format(local_bundle_file, env.host)
    bundle_transfer_result = put(local_bundle_file, CONFIG['REMOTE_BUNDLES_DIR'])

    if bundle_transfer_result.failed:
        abort("Liferay bundle failed to transfer. Quitting")

def clean_up():
    # Clean up temporary files
    print("Removing bundle file: {0} ".format(CONFIG['REMOTE_BUNDLES_DIR'] + CONFIG['BUNDLE_FILE_NAME']))
    with settings(warn_only=True):
        if exists(CONFIG['REMOTE_BUNDLES_DIR'] + CONFIG['BUNDLE_FILE_NAME']):
            run('rm ' + CONFIG['REMOTE_BUNDLES_DIR'] + CONFIG['BUNDLE_FILE_NAME'])

"""Main deploy task
This task should be executed with the required arguments which are saved globally for use
later used by other tasks. The arguments are passed as strings from the command line so they are always not None.
Checks are done for the string "None" or "False" or "True"  or "" instead
"""
@task
def deploy(bundle_name, bundle_extracted_name, do_health_check='False', remote_server=''):
    if not bundle_name:
        abort("Deployment bundle is not set")

    if not bundle_extracted_name:
        abort("Bundle extracted name is not set")

    # env.user is passed as a command line arg not a method arg
    if not env.user:
        env.user = CONFIG['REMOTE_USER']

    print("Current user: {0}".format(env.user))

    print("Starting deploy to {0}".format(env.host_string))
    CONFIG['REMOTE_SERVER'] = remote_server
    CONFIG['BUNDLE_FILE_NAME'] = bundle_name
    CONFIG['BUNDLE_EXTRACTED_NAME'] = bundle_extracted_name

    debug()
    
    disable_puppet()

    stop_apache_result = stop_apache()
    if stop_apache_result.failed:
        abort("Apache failed to stop. Quitting")

    stop_liferay_result = stop_liferay()
    if stop_liferay_result.failed:
        abort("Liferay failed to stop. Quitting")

    copy_bundle()

    new_deploy_dir = CONFIG['REMOTE_DEPLOYS_DIR'] + CONFIG['BUNDLE_EXTRACTED_NAME']

    with settings(warn_only=True):
        if exists(new_deploy_dir):
            print ("An indentically named deploy '{0}' was found and will be deleted".format(new_deploy_dir))
            run('rm -rf {0}'.format(new_deploy_dir))

    with cd(CONFIG['REMOTE_DEPLOYS_DIR']):
        with hide('stdout'):
            print("Unpacking current bundle")
            bundle_extract_result = run('tar -xvf {0}'.format(CONFIG['REMOTE_BUNDLES_DIR'] + CONFIG['BUNDLE_FILE_NAME']))
        if bundle_extract_result.failed:
            abort("Liferay bundle failed to extract successfully. Quitting")

    # Mark current deploy as previous with symlink
    with settings(warn_only=True):
        if exists(CONFIG['CURRENT_SYMLINK']):
            print ("Moving 'current' deploy symlink to 'previous'")
            current_link_target = run('readlink {0}'.format(CONFIG['CURRENT_SYMLINK']))
            run('rm {0}'.format(CONFIG['CURRENT_SYMLINK']))
            if exists(CONFIG['PREVIOUS_SYMLINK']):
                run('rm {0}'.format(CONFIG['PREVIOUS_SYMLINK']))
            run('ln -s {0} {1}'.format(current_link_target, CONFIG['PREVIOUS_SYMLINK']))

    # Point current symlink to newly extracted bundle
    print("Creating symlink for current deploy")
    run('ln -s {0} {1}'.format(new_deploy_dir, CONFIG['CURRENT_SYMLINK']))

    # Set scripts as executable
    with cd(CONFIG['CURRENT_SYMLINK'] + '/tomcat/bin'):
        print("Setting scripts as executable")
        run('chmod ug+x *.sh')

    clean_up()
    start_liferay()
    wait_for_liferay()

    if do_health_check.lower() == 'true':
        if health_check():
            print "Liferay passed startup validation"
            start_apache_result = start_apache()
            if start_apache_result.failed:
                abort("Apache failed to restart. Please check")
            print("Startup successful")
            enable_puppet()
        else:
            abort("Liferay failed startup validation. Apache will not be started. Please check {0}. Current time {1}".format(CONFIG['HEALTH_CHECK_URL'], current_time_gmt()))
    else:
        print("Skipping health checks")
        start_apache_result =  start_apache()
        if start_apache_result.failed:
            abort("Apache failed to restart. Please check")
        else:
            print("Startup successful")
            enable_puppet()

"""http://www.alleyinteractive.com/blog/ssh-tunnel-fabric/
"""
class SSHTunnel:
    def __init__(self, bridge_user, bridge_host, dest_host, bridge_port=22, dest_port=22, local_port=2022, timeout=15):
        self.local_port = local_port
        cmd = 'ssh -vAN -L %d:%s:%d %s@%s' % (local_port, dest_host, dest_port, bridge_user, bridge_host)
        self.p = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        start_time = time.time()
        atexit.register(self.p.kill)
        while not 'Entering interactive session' in self.p.stderr.readline():
            if time.time() > start_time + timeout:
                raise "SSH tunnel timed out"
    def entrance(self):
        return 'localhost:%d' % self.local_port
