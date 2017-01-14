# Copyright 2016 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import sys

from test_utils import CharmTestCase
from mock import patch, MagicMock

os.environ['JUJU_UNIT_NAME'] = 'UNIT_TEST/0'  # noqa - needed for import

# python-apt is not installed as part of test-requirements but is imported by
# some charmhelpers modules so create a fake import.
mock_apt = MagicMock()
sys.modules['apt'] = mock_apt
mock_apt.apt_pkg = MagicMock()

with patch('charmhelpers.contrib.hardening.harden.harden') as mock_dec:
    mock_dec.side_effect = (lambda *dargs, **dkwargs: lambda f:
                            lambda *args, **kwargs: f(*args, **kwargs))
    import rabbitmq_server_relations

TO_PATCH = [
    # charmhelpers.core.hookenv
    'is_leader',
    'relation_ids',
    'related_units',
]


class RelationUtil(CharmTestCase):
    def setUp(self):
        self.fake_repo = {}
        super(RelationUtil, self).setUp(rabbitmq_server_relations,
                                        TO_PATCH)

    @patch('rabbitmq_server_relations.rabbit.leader_node_is_ready')
    @patch('rabbitmq_server_relations.peer_store_and_set')
    @patch('rabbitmq_server_relations.config')
    @patch('rabbitmq_server_relations.relation_set')
    @patch('rabbitmq_server_relations.cmp_pkgrevno')
    @patch('rabbitmq_server_relations.is_clustered')
    @patch('rabbitmq_server_relations.ssl_utils.configure_client_ssl')
    @patch('rabbitmq_server_relations.rabbit.get_unit_ip')
    @patch('rabbitmq_server_relations.relation_get')
    @patch('rabbitmq_server_relations.is_elected_leader')
    def test_amqp_changed_compare_versions_ha_queues(
            self,
            is_elected_leader,
            relation_get,
            get_unit_ip,
            configure_client_ssl,
            is_clustered,
            cmp_pkgrevno,
            relation_set,
            mock_config,
            mock_peer_store_and_set,
            mock_leader_node_is_ready):
        """
        Compare version above and below 3.0.1.
        Make sure ha_queues is set correctly on each side.
        """

        def config(key):
            if key == 'prefer-ipv6':
                return False

            return None

        mock_leader_node_is_ready.return_value = True
        mock_config.side_effect = config
        host_addr = "10.1.2.3"
        get_unit_ip.return_value = host_addr
        is_elected_leader.return_value = True
        relation_get.return_value = {}
        is_clustered.return_value = False
        cmp_pkgrevno.return_value = -1

        rabbitmq_server_relations.amqp_changed(None, None)
        mock_peer_store_and_set.assert_called_with(
            relation_settings={'private-address': '10.1.2.3',
                               'hostname': host_addr,
                               'ha_queues': True},
            relation_id=None)

        cmp_pkgrevno.return_value = 1
        rabbitmq_server_relations.amqp_changed(None, None)
        mock_peer_store_and_set.assert_called_with(
            relation_settings={'private-address': '10.1.2.3',
                               'hostname': host_addr},
            relation_id=None)

    @patch('rabbitmq_server_relations.rabbit.leader_node_is_ready')
    @patch('rabbitmq_server_relations.peer_store_and_set')
    @patch('rabbitmq_server_relations.config')
    @patch('rabbitmq_server_relations.relation_set')
    @patch('rabbitmq_server_relations.cmp_pkgrevno')
    @patch('rabbitmq_server_relations.is_clustered')
    @patch('rabbitmq_server_relations.ssl_utils.configure_client_ssl')
    @patch('rabbitmq_server_relations.rabbit.get_unit_ip')
    @patch('rabbitmq_server_relations.relation_get')
    @patch('rabbitmq_server_relations.is_elected_leader')
    def test_amqp_changed_compare_versions_ha_queues_prefer_ipv6(
            self,
            is_elected_leader,
            relation_get,
            get_unit_ip,
            configure_client_ssl,
            is_clustered,
            cmp_pkgrevno,
            relation_set,
            mock_config,
            mock_peer_store_and_set,
            mock_leader_node_is_ready):
        """
        Compare version above and below 3.0.1.
        Make sure ha_queues is set correctly on each side.
        """

        def config(key):
            if key == 'prefer-ipv6':
                return True

            return None

        mock_leader_node_is_ready.return_value = True
        mock_config.side_effect = config
        ipv6_addr = "2001:db8:1:0:f816:3eff:fed6:c140"
        get_unit_ip.return_value = ipv6_addr
        is_elected_leader.return_value = True
        relation_get.return_value = {}
        is_clustered.return_value = False
        cmp_pkgrevno.return_value = -1

        rabbitmq_server_relations.amqp_changed(None, None)
        mock_peer_store_and_set.assert_called_with(
            relation_settings={'private-address': ipv6_addr,
                               'hostname': ipv6_addr,
                               'ha_queues': True},
            relation_id=None)

        cmp_pkgrevno.return_value = 1
        rabbitmq_server_relations.amqp_changed(None, None)
        mock_peer_store_and_set.assert_called_with(
            relation_settings={'private-address': ipv6_addr,
                               'hostname': ipv6_addr},
            relation_id=None)

    @patch('rabbitmq_server_relations.amqp_changed')
    @patch('rabbitmq_server_relations.rabbit.client_node_is_ready')
    @patch('rabbitmq_server_relations.rabbit.leader_node_is_ready')
    def test_update_clients(self, mock_leader_node_is_ready,
                            mock_client_node_is_ready,
                            mock_amqp_changed):
        # Not ready
        mock_client_node_is_ready.return_value = False
        mock_leader_node_is_ready.return_value = False
        rabbitmq_server_relations.update_clients()
        self.assertFalse(mock_amqp_changed.called)

        # Leader Ready
        self.relation_ids.return_value = ['amqp:0']
        self.related_units.return_value = ['client/0']
        mock_leader_node_is_ready.return_value = True
        mock_client_node_is_ready.return_value = False
        rabbitmq_server_relations.update_clients()
        mock_amqp_changed.assert_called_with(relation_id='amqp:0',
                                             remote_unit='client/0')

        # Client Ready
        self.relation_ids.return_value = ['amqp:0']
        self.related_units.return_value = ['client/0']
        mock_leader_node_is_ready.return_value = False
        mock_client_node_is_ready.return_value = True
        rabbitmq_server_relations.update_clients()
        mock_amqp_changed.assert_called_with(relation_id='amqp:0',
                                             remote_unit='client/0')

        # Both Ready
        self.relation_ids.return_value = ['amqp:0']
        self.related_units.return_value = ['client/0']
        mock_leader_node_is_ready.return_value = True
        mock_client_node_is_ready.return_value = True
        rabbitmq_server_relations.update_clients()
        mock_amqp_changed.assert_called_with(relation_id='amqp:0',
                                             remote_unit='client/0')
