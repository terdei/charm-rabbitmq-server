# Easy file synchronization among peer units using ssh + unison.
#
# From *both* peer relation -joined and -changed, add a call to
# ssh_authorized_peers() describing the peer relation and the desired
# user + group.  After all peer relations have settled, all hosts should
# be able to connect to on another via key auth'd ssh as the specified user.
#
# Other hooks are then free to synchronize files and directories using
# sync_to_peers().
#
# For a peer relation named 'cluster', for example:
#
# cluster-relation-joined:
# ...
# ssh_authorized_peers(peer_interface='cluster',
#                      user='juju_ssh', group='juju_ssh',
#                      ensure_user=True)
# ...
#
# cluster-relation-changed:
# ...
# ssh_authorized_peers(peer_interface='cluster',
#                      user='juju_ssh', group='juju_ssh',
#                      ensure_user=True)
# ...
#
# Hooks are now free to sync files as easily as:
#
# files = ['/etc/fstab', '/etc/apt.conf.d/']
# sync_to_peers(peer_interface='cluster',
#                user='juju_ssh, paths=[files])
#
# It is assumed the charm itself has setup permissions on each unit
# such that 'juju_ssh' has read + write permissions.  Also assumed
# that the calling charm takes care of leader delegation.
#
# Additionally files can be synchronized only to an specific unit:
# sync_to_peer(slave_address, user='juju_ssh',
#              paths=[files], verbose=False)

import os
import pwd

from copy import copy
from subprocess import check_call, check_output

from charmhelpers.core.host import (
    adduser,
    add_user_to_group,
)

from charmhelpers.core.hookenv import (
    log,
    hook_name,
    relation_ids,
    related_units,
    relation_set,
    relation_get,
    unit_private_ip,
    ERROR,
)

BASE_CMD = ['unison', '-auto', '-batch=true', '-confirmbigdel=false',
            '-fastcheck=true', '-group=false', '-owner=false',
            '-prefer=newer', '-times=true']


def get_homedir(user):
    try:
        user = pwd.getpwnam(user)
        return user.pw_dir
    except KeyError:
        log('Could not get homedir for user %s: user exists?', ERROR)
        raise Exception


def create_private_key(user, priv_key_path):
    if not os.path.isfile(priv_key_path):
        log('Generating new SSH key for user %s.' % user)
        cmd = ['ssh-keygen', '-q', '-N', '', '-t', 'rsa', '-b', '2048',
               '-f', priv_key_path]
        check_call(cmd)
    else:
        log('SSH key already exists at %s.' % priv_key_path)
    check_call(['chown', user, priv_key_path])
    check_call(['chmod', '0600', priv_key_path])


def create_public_key(user, priv_key_path, pub_key_path):
    if not os.path.isfile(pub_key_path):
        log('Generating missing ssh public key @ %s.' % pub_key_path)
        cmd = ['ssh-keygen', '-y', '-f', priv_key_path]
        p = check_output(cmd).strip()
        with open(pub_key_path, 'wb') as out:
            out.write(p)
    check_call(['chown', user, pub_key_path])


def get_keypair(user):
    home_dir = get_homedir(user)
    ssh_dir = os.path.join(home_dir, '.ssh')
    priv_key = os.path.join(ssh_dir, 'id_rsa')
    pub_key = '%s.pub' % priv_key

    if not os.path.isdir(ssh_dir):
        os.mkdir(ssh_dir)
        check_call(['chown', '-R', user, ssh_dir])

    create_private_key(user, priv_key)
    create_public_key(user, priv_key, pub_key)

    with open(priv_key, 'r') as p:
        _priv = p.read().strip()

    with open(pub_key, 'r') as p:
        _pub = p.read().strip()

    return (_priv, _pub)


def write_authorized_keys(user, keys):
    home_dir = get_homedir(user)
    ssh_dir = os.path.join(home_dir, '.ssh')
    auth_keys = os.path.join(ssh_dir, 'authorized_keys')
    log('Syncing authorized_keys @ %s.' % auth_keys)
    with open(auth_keys, 'wb') as out:
        for k in keys:
            out.write('%s\n' % k)


def write_known_hosts(user, hosts):
    home_dir = get_homedir(user)
    ssh_dir = os.path.join(home_dir, '.ssh')
    known_hosts = os.path.join(ssh_dir, 'known_hosts')
    khosts = []
    for host in hosts:
        cmd = ['ssh-keyscan', '-H', '-t', 'rsa', host]
        remote_key = check_output(cmd).strip()
        khosts.append(remote_key)
    log('Syncing known_hosts @ %s.' % known_hosts)
    with open(known_hosts, 'wb') as out:
        for host in khosts:
            out.write('%s\n' % host)


def ensure_user(user, group=None):
    adduser(user)
    if group:
        add_user_to_group(user, group)


def ssh_authorized_peers(peer_interface, user, group=None,
                         ensure_local_user=False):
    """
    Main setup function, should be called from both peer -changed and -joined
    hooks with the same parameters.
    """
    if ensure_local_user:
        ensure_user(user, group)
    priv_key, pub_key = get_keypair(user)
    hook = hook_name()
    if hook == '%s-relation-joined' % peer_interface:
        relation_set(ssh_pub_key=pub_key)
    elif hook == '%s-relation-changed' % peer_interface:
        hosts = []
        keys = []

        for r_id in relation_ids(peer_interface):
            for unit in related_units(r_id):
                ssh_pub_key = relation_get('ssh_pub_key',
                                           rid=r_id,
                                           unit=unit)
                priv_addr = relation_get('private-address',
                                         rid=r_id,
                                         unit=unit)
                if ssh_pub_key:
                    keys.append(ssh_pub_key)
                    hosts.append(priv_addr)
                else:
                    log('ssh_authorized_peers(): ssh_pub_key '
                        'missing for unit %s, skipping.' % unit)
        write_authorized_keys(user, keys)
        write_known_hosts(user, hosts)
        authed_hosts = ':'.join(hosts)
        relation_set(ssh_authorized_hosts=authed_hosts)


def _run_as_user(user):
    try:
        user = pwd.getpwnam(user)
        log('in unison run as user, run as %s' % str(user))
    except KeyError:
        log('Invalid user: %s' % user)
        raise Exception
    uid, gid = user.pw_uid, user.pw_gid
    os.environ['HOME'] = user.pw_dir
    os.setgid(gid)
    os.setgroups([gid])
    os.setuid(uid)


def run_as_user(user, cmd):
    return check_output(cmd, preexec_fn=_run_as_user(user), cwd='/')


def collect_authed_hosts(peer_interface):
    '''Iterate through the units on peer interface to find all that
    have the calling host in its authorized hosts list'''
    hosts = []
    for r_id in (relation_ids(peer_interface) or []):
        for unit in related_units(r_id):
            private_addr = relation_get('private-address',
                                        rid=r_id, unit=unit)
            authed_hosts = relation_get('ssh_authorized_hosts',
                                        rid=r_id, unit=unit)

            if not authed_hosts:
                log('Peer %s has not authorized *any* hosts yet, skipping.')
                continue

            if unit_private_ip() in authed_hosts.split(':'):
                hosts.append(private_addr)
            else:
                log('Peer %s has not authorized *this* host yet, skipping.')

    return hosts


def sync_path_to_host(path, host, user, verbose=False):
    cmd = copy(BASE_CMD)
    if not verbose:
        cmd.append('-silent')

    # removing trailing slash from directory paths, unison
    # doesn't like these.
    if path.endswith('/'):
        path = path[:(len(path) - 1)]

    cmd = cmd + [path, 'ssh://%s@%s/%s' % (user, host, path)]
    log('Unison command: %s' % str(cmd))

    output = ''
    try:
        log('Syncing local path %s to %s@%s:%s' % (path, user, host, path))
        output = run_as_user(user, cmd)
        log('Result of sync: %s' % str(output))
    except Exception as e:
        log('Error syncing remote files: %s - %s' % (str(e), str(output)))


def sync_to_peer(host, user, paths=[], verbose=False):
    '''Sync paths to an specific host'''
    [sync_path_to_host(p, host, user, verbose) for p in paths]


def sync_to_peers(peer_interface, user, paths=[], verbose=False):
    '''Sync all hosts to an specific path'''
    for host in collect_authed_hosts(peer_interface):
        sync_to_peer(host, user, paths, verbose)
