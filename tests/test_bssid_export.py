"""Tests for the standalone BSSID export tool (no network access needed)."""
import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bssid_export as be  # noqa: E402


class FakeResponse:
    def __init__(self, data, headers: dict | None = None):
        self._data = data
        self.headers = headers or {}

    def json(self):
        return self._data


class FakeApi(be.MistSession):
    """Stands in for MistSession; serves canned JSON per path.

    A response value may be plain JSON or a FakeResponse (to set headers).
    """

    def __init__(self, responses: dict):
        self.responses = responses
        self.base = 'https://api.mist.com'
        self.calls: list[str] = []

    def get(self, path: str):
        self.calls.append(path)
        if path in self.responses:
            resp = self.responses[path]
            if isinstance(resp, Exception):
                raise resp
            return resp if isinstance(resp, FakeResponse) else FakeResponse(resp)
        raise AssertionError(f"Unexpected API path: {path}")


def paged(path: str, page: int, size: int = be.PAGE_SIZE) -> str:
    sep = '&' if '?' in path else '?'
    return f"{path}{sep}limit={size}&page={page}"


class TestPagination(unittest.TestCase):
    def test_follows_x_page_total(self):
        # Server caps at 2 per page even though 1000 was requested
        headers = {'X-Page-Total': '5', 'X-Page-Limit': '2'}
        api = FakeApi({
            paged('/x', 1): FakeResponse([1, 2], headers),
            paged('/x', 2): FakeResponse([3, 4], headers),
            paged('/x', 3): FakeResponse([5], headers),
        })
        self.assertEqual(api.get_all_pages('/x'), [1, 2, 3, 4, 5])

    def test_short_page_stops_without_total(self):
        api = FakeApi({paged('/x?type=ap', 1): [1, 2]})
        self.assertEqual(api.get_all_pages('/x?type=ap'), [1, 2])

    def test_empty_page_stops(self):
        api = FakeApi({
            paged('/x', 1): FakeResponse([1], {'X-Page-Total': '3'}),
            paged('/x', 2): FakeResponse([], {'X-Page-Total': '3'}),
        })
        self.assertEqual(api.get_all_pages('/x'), [1])

    def test_non_list_body_raises(self):
        api = FakeApi({paged('/x', 1): {'detail': 'nope'}})
        with self.assertRaises(be.requests.exceptions.RequestException):
            api.get_all_pages('/x')


def paged(path: str, page: int, size: int = be.PAGE_SIZE) -> str:
    sep = '&' if '?' in path else '?'
    return f"{path}{sep}limit={size}&page={page}"


class TestPagination(unittest.TestCase):
    def test_follows_x_page_total(self):
        # Server caps at 2 per page even though 1000 was requested
        api = FakeApi({
            paged('/x', 1): FakeResponse([1, 2], {'X-Page-Total': '5', 'X-Page-Limit': '2'}),
            paged('/x', 2): FakeResponse([3, 4], {'X-Page-Total': '5', 'X-Page-Limit': '2'}),
            paged('/x', 3): FakeResponse([5], {'X-Page-Total': '5', 'X-Page-Limit': '2'}),
        })
        self.assertEqual(api.get_all_pages('/x'), [1, 2, 3, 4, 5])

    def test_short_page_stops_without_total(self):
        api = FakeApi({paged('/x?type=ap', 1): [1, 2]})
        self.assertEqual(api.get_all_pages('/x?type=ap'), [1, 2])

    def test_x_page_limit_used_without_total(self):
        api = FakeApi({
            paged('/x', 1): FakeResponse([1, 2], {'X-Page-Limit': '2'}),
            paged('/x', 2): FakeResponse([3], {'X-Page-Limit': '2'}),
        })
        self.assertEqual(api.get_all_pages('/x'), [1, 2, 3])

    def test_empty_page_stops(self):
        api = FakeApi({
            paged('/x', 1): FakeResponse([1], {'X-Page-Total': '3'}),
            paged('/x', 2): FakeResponse([], {'X-Page-Total': '3'}),
        })
        self.assertEqual(api.get_all_pages('/x'), [1])

    def test_non_list_body_raises(self):
        api = FakeApi({paged('/x', 1): {'results': [1]}, '/y': {'results': []}})
        with self.assertRaises(be.requests.exceptions.RequestException):
            api.get_all_pages('/x')
        with self.assertRaises(be.requests.exceptions.RequestException):
            api.get_json_list('/y')


class TestExtractRadioMacs(unittest.TestCase):
    def test_all_bands(self):
        stat = {'radio_stat': {
            'band_24': {'mac': 'aa1'}, 'band_5': {'mac': 'bb2'}, 'band_6': {'mac': 'cc3'},
        }}
        self.assertEqual(be.extract_radio_macs(stat), ['aa1', 'bb2', 'cc3'])

    def test_missing_bands(self):
        stat = {'radio_stat': {'band_5': {'mac': 'bb2'}}}
        self.assertEqual(be.extract_radio_macs(stat), ['bb2'])

    def test_radio_stat_none(self):
        self.assertEqual(be.extract_radio_macs({'radio_stat': None}), [])
        self.assertEqual(be.extract_radio_macs({}), [])

    def test_band_none(self):
        stat = {'radio_stat': {'band_24': None, 'band_5': {'mac': 'x'}}}
        self.assertEqual(be.extract_radio_macs(stat), ['x'])


class TestHelpers(unittest.TestCase):
    def test_normalize_mac(self):
        self.assertEqual(be.normalize_mac('AA:BB-cc:00'), 'aabbcc00')

    def test_sanitize_filename(self):
        self.assertEqual(be.sanitize_filename('My Org / Prod!'), 'My_Org_Prod')
        self.assertEqual(be.sanitize_filename('___'), '')


class TestResolveApiUrl(unittest.TestCase):
    def test_explicit_url(self):
        with patch.dict(os.environ, {'MIST_API_URL': 'https://api.eu.mist.com/'}, clear=False):
            self.assertEqual(be.resolve_api_url(), 'https://api.eu.mist.com')

    def test_cloud_shorthand_variants(self):
        for value in ('global01', 'Global 01', 'GLOBAL-01', 'global_01'):
            with patch.dict(os.environ, {'MIST_CLOUD': value}, clear=False):
                os.environ.pop('MIST_API_URL', None)
                self.assertEqual(be.resolve_api_url(), 'https://api.mist.com', value)

    def test_cloud_bare_host(self):
        with patch.dict(os.environ, {'MIST_CLOUD': 'api.gc5.mist.com'}, clear=False):
            os.environ.pop('MIST_API_URL', None)
            self.assertEqual(be.resolve_api_url(), 'https://api.gc5.mist.com')

    def test_unknown_host_rejected(self):
        with patch.dict(os.environ, {'MIST_API_URL': 'https://evil.example.com'}, clear=False):
            os.environ.pop('MIST_CLOUD', None)
            with self.assertRaises(be.ConfigError):
                be.resolve_api_url()

    def test_http_scheme_rejected(self):
        with patch.dict(os.environ, {'MIST_API_URL': 'http://api.mist.com'}, clear=False):
            os.environ.pop('MIST_CLOUD', None)
            with self.assertRaises(be.ConfigError) as ctx:
                be.resolve_api_url()
            self.assertIn('https', str(ctx.exception))

    def test_conflicting_url_and_cloud(self):
        env = {'MIST_API_URL': 'https://api.mist.com', 'MIST_CLOUD': 'emea01'}
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaises(be.ConfigError) as ctx:
                be.resolve_api_url()
            self.assertIn('different', str(ctx.exception))

    def test_agreeing_url_and_cloud(self):
        env = {'MIST_API_URL': 'https://api.eu.mist.com/', 'MIST_CLOUD': 'emea01'}
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(be.resolve_api_url(), 'https://api.eu.mist.com')

    def test_nothing_set(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('MIST_API_URL', None)
            os.environ.pop('MIST_CLOUD', None)
            with self.assertRaises(be.ConfigError):
                be.resolve_api_url()


class TestMistSession(unittest.TestCase):
    def test_base_uses_only_allowlisted_hostname(self):
        session = be.MistSession('https://evil.example\\@api.mist.com', 'dummy-token')
        self.assertEqual(session.base, 'https://api.mist.com')


class TestLoadEnv(unittest.TestCase):
    def test_parse_and_no_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / '.env'
            env_file.write_text(
                '# comment\n'
                'MIST_ORG_ID="quoted-org"\n'
                'MIST_API_TOKEN=tok123\n'
                'BAD LINE\n',
                encoding='utf-8',
            )
            with patch.dict(os.environ, {'MIST_API_TOKEN': 'preset'}, clear=False):
                os.environ.pop('MIST_ORG_ID', None)
                self.assertTrue(be.load_env(env_file))
                self.assertEqual(os.environ['MIST_ORG_ID'], 'quoted-org')
                self.assertEqual(os.environ['MIST_API_TOKEN'], 'preset')  # not overridden

    def test_missing_file(self):
        self.assertFalse(be.load_env(Path('Z:/does/not/exist/.env')))

    def test_ignores_non_mist_environment_variables(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / '.env'
            env_file.write_text('HTTPS_PROXY=https://proxy.example\n', encoding='utf-8')
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop('HTTPS_PROXY', None)
                be.load_env(env_file)
                self.assertNotIn('HTTPS_PROXY', os.environ)

    def test_utf8_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / '.env'
            env_file.write_bytes('MIST_ORG_ID=bom-org\n'.encode('utf-8-sig'))
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop('MIST_ORG_ID', None)
                self.assertTrue(be.load_env(env_file))
                self.assertEqual(os.environ['MIST_ORG_ID'], 'bom-org')

    def test_utf16_raises_config_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / '.env'
            env_file.write_bytes('MIST_ORG_ID=x\n'.encode('utf-16'))
            with self.assertRaises(be.ConfigError) as ctx:
                be.load_env(env_file)
            self.assertIn('UTF-8', str(ctx.exception))

    def test_inline_comment_stripped(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / '.env'
            env_file.write_text(
                'MIST_ORG_ID=abc123  # production org\n'
                'MIST_API_TOKEN="tok#with#hash"  \n',
                encoding='utf-8',
            )
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop('MIST_ORG_ID', None)
                os.environ.pop('MIST_API_TOKEN', None)
                be.load_env(env_file)
                self.assertEqual(os.environ['MIST_ORG_ID'], 'abc123')
                self.assertEqual(os.environ['MIST_API_TOKEN'], 'tok#with#hash')


class TestMistSession(unittest.TestCase):
    def test_does_not_trust_proxy_or_ca_environment(self):
        session = be.MistSession('https://api.mist.com', 'dummy-token')
        self.assertFalse(session.session.trust_env)


    def test_quoted_value_with_inline_comment(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / '.env'
            env_file.write_text(
                'MIST_API_TOKEN="tok#with#hash"  # production token\n'
                "MIST_ORG_ID='org-1'  # id\n"
                'MIST_CLOUD="global01"\n',
                encoding='utf-8',
            )
            with patch.dict(os.environ, {}, clear=False):
                for key in ('MIST_API_TOKEN', 'MIST_ORG_ID', 'MIST_CLOUD'):
                    os.environ.pop(key, None)
                be.load_env(env_file)
                self.assertEqual(os.environ['MIST_API_TOKEN'], 'tok#with#hash')
                self.assertEqual(os.environ['MIST_ORG_ID'], 'org-1')
                self.assertEqual(os.environ['MIST_CLOUD'], 'global01')


class TestResolveScope(unittest.TestCase):
    SITES = [
        {'id': 'id-hq', 'name': 'HQ'},
        {'id': 'id-b7', 'name': 'Branch 7'},
        {'id': 'id-b8', 'name': 'Branch 8'},
    ]
    GROUPS = [
        {'id': 'g-1', 'name': 'Campus', 'site_ids': ['id-hq', 'id-b7']},
        {'id': 'g-2', 'name': 'Empty', 'site_ids': []},
    ]

    def test_entire_org(self):
        self.assertIsNone(be.resolve_scope(self.SITES, self.GROUPS, None, None))

    def test_sites_by_name_case_insensitive(self):
        result = be.resolve_scope(self.SITES, [], 'hq, branch 7', None)
        self.assertEqual(result, {'id-hq', 'id-b7'})

    def test_sites_by_id_and_name_mixed(self):
        result = be.resolve_scope(self.SITES, [], 'id-b8,HQ', None)
        self.assertEqual(result, {'id-b8', 'id-hq'})

    def test_unknown_site(self):
        with self.assertRaises(be.ConfigError):
            be.resolve_scope(self.SITES, [], 'Nope', None)

    COMMA_SITES = SITES + [
        {'id': 'id-dal', 'name': 'Dallas, TX'},
        {'id': 'id-dal2', 'name': 'Dallas'},
    ]

    def test_site_name_with_comma_as_one_unit(self):
        self.assertEqual(be.resolve_scope(self.COMMA_SITES, [], 'Dallas, TX', None),
                         {'id-dal'})

    def test_quoted_comma_name_with_others(self):
        result = be.resolve_scope(self.COMMA_SITES, [], 'HQ,"Dallas, TX"', None)
        self.assertEqual(result, {'id-hq', 'id-dal'})

    def test_repeated_sites_flag(self):
        args = be.build_parser().parse_args(['--sites', 'Dallas, TX', '--sites', 'HQ,Branch 7'])
        self.assertEqual(be.resolve_scope(self.COMMA_SITES, [], args.sites, None),
                         {'id-dal', 'id-hq', 'id-b7'})

    def test_unknown_comma_fragment_error_is_quoted(self):
        with self.assertRaises(be.ConfigError) as ctx:
            be.resolve_scope(self.SITES, [], 'Dallas, TX', None)
        msg = str(ctx.exception)
        self.assertIn('"Dallas", "TX"', msg)
        self.assertIn('site ID', msg)

    def test_group_by_name(self):
        result = be.resolve_scope(self.SITES, self.GROUPS, None, 'campus')
        self.assertEqual(result, {'id-hq', 'id-b7'})

    def test_group_by_id(self):
        result = be.resolve_scope(self.SITES, self.GROUPS, None, 'g-1')
        self.assertEqual(result, {'id-hq', 'id-b7'})

    def test_unknown_group(self):
        with self.assertRaises(be.ConfigError):
            be.resolve_scope(self.SITES, self.GROUPS, None, 'nope')

    def test_empty_group(self):
        with self.assertRaises(be.ConfigError):
            be.resolve_scope(self.SITES, self.GROUPS, None, 'Empty')

    def test_blank_sites_arg_errors(self):
        with self.assertRaises(be.ConfigError):
            be.resolve_scope(self.SITES, self.GROUPS, '', None)
        with self.assertRaises(be.ConfigError):
            be.resolve_scope(self.SITES, self.GROUPS, ' , ', None)

    def test_blank_group_arg_errors(self):
        with self.assertRaises(be.ConfigError):
            be.resolve_scope(self.SITES, self.GROUPS, None, '  ')


class TestFetchSitesAndGroups(unittest.TestCase):
    def test_site_past_first_page_gets_its_address(self):
        size = be.PAGE_SIZE
        page1 = [{'id': f's{i}', 'name': f'Store {i}', 'address': f'{i} Main St'}
                 for i in range(size)]
        page2 = [{'id': 'last', 'name': 'Store 9999', 'address': '9999 Elm St'}]
        hdr = {'X-Page-Total': str(size + 1)}
        api = FakeApi({
            paged('/api/v1/orgs/o1/sites', 1): FakeResponse(page1, hdr),
            paged('/api/v1/orgs/o1/sites', 2): FakeResponse(page2, hdr),
            f'/api/v1/orgs/o1/inventory?type=ap&limit={be.INVENTORY_PAGE_SIZE}&page=1': [
                {'type': 'ap', 'mac': 'aabbcc000001', 'site_id': 'last'},
            ],
            paged('/api/v1/sites/last/maps', 1): [],
            paged(
                f'/api/v1/orgs/o1/stats/devices?type=ap&fields={be.ORG_STATS_FIELDS}', 1
            ): [],
        })
        sites = be.fetch_sites(api, 'o1')
        self.assertEqual(len(sites), size + 1)
        self.assertEqual(be.resolve_scope(sites, [], 'Store 9999', None), {'last'})
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = be.export_bssids(api, 'o1', 'Org', sites, None, Path(tmp) / 'o.csv')
            with open(path, newline='', encoding='utf-8') as f:
                row = next(csv.DictReader(f))
        self.assertEqual(row['SITE'], 'Store 9999')
        self.assertEqual(row['SITE_ADDRESS'], '9999 Elm St')

    def test_site_groups_paginated(self):
        hdr = {'X-Page-Total': '3', 'X-Page-Limit': '2'}
        api = FakeApi({
            paged('/api/v1/orgs/o1/sitegroups', 1): FakeResponse(
                [{'id': 'g1', 'name': 'A'}, {'id': 'g2', 'name': 'B'}], hdr),
            paged('/api/v1/orgs/o1/sitegroups', 2): FakeResponse(
                [{'id': 'g3', 'name': 'Campus', 'site_ids': ['s1']}], hdr),
        })
        groups = be.fetch_site_groups(api, 'o1')
        self.assertEqual(be.resolve_scope([], groups, None, 'Campus'), {'s1'})


class TestFetchInventoryAps(unittest.TestCase):
    def test_pagination_and_filtering(self):
        page1 = [{'type': 'ap', 'mac': f'aabbccdd{i:04x}', 'site_id': 's1'}
                 for i in range(be.INVENTORY_PAGE_SIZE)]
        page2 = [
            {'type': 'ap', 'mac': 'AA:BB:CC:00:00:01', 'site_id': 's2'},
            {'type': 'switch', 'mac': 'ffffffffffff', 'site_id': 's1'},   # ignored even if server returns it
            {'type': 'ap', 'mac': 'aabbcc000002', 'site_id': None},       # unassigned
            {'type': 'ap', 'mac': '', 'site_id': 's1'},                   # no mac
        ]
        api = FakeApi({
            f'/api/v1/orgs/o1/inventory?type=ap&limit={be.INVENTORY_PAGE_SIZE}&page=1': page1,
            f'/api/v1/orgs/o1/inventory?type=ap&limit={be.INVENTORY_PAGE_SIZE}&page=2': page2,
        })
        aps = be.fetch_inventory_aps(api, 'o1')
        self.assertEqual(len(aps), be.INVENTORY_PAGE_SIZE + 1)
        self.assertIn('aabbcc000001', aps)
        self.assertEqual(aps['aabbcc000001']['raw_mac'], 'AA:BB:CC:00:00:01')
        self.assertEqual(aps['aabbcc000001']['site_id'], 's2')


class TestExport(unittest.TestCase):
    S1_STATS = [
        {'mac': 'aabbcc000001', 'site_id': 's1', 'name': 'AP-1', 'map_id': 'm1',
         'status': 'connected',
         'radio_stat': {'band_24': {'mac': 'radio24'}, 'band_5': {'mac': 'radio5'}},
         'lldp_stat': {'system_name': 'sw1', 'port_id': 'ge-0/0/1'}},
        {'mac': 'ddeeff000009', 'site_id': 's1', 'name': 'not-in-inventory'},
    ]
    S2_STATS = [
        {'mac': 'AA:BB:CC:00:00:02', 'site_id': 's2', 'name': 'AP-2', 'radio_stat': None,
         'lldp_stat': None},
    ]
    ORG_STATS_PATH = paged(
        f'/api/v1/orgs/o1/stats/devices?type=ap&fields={be.ORG_STATS_FIELDS}', 1)

    def _make_api(self, org_stats=None):
        return FakeApi({
            f'/api/v1/orgs/o1/inventory?type=ap&limit={be.INVENTORY_PAGE_SIZE}&page=1': [
                {'type': 'ap', 'mac': 'aabbcc000001', 'site_id': 's1'},
                {'type': 'ap', 'mac': 'aabbcc000002', 'site_id': 's2'},
                {'type': 'ap', 'mac': 'aabbcc000003', 'site_id': 's1',
                 'name': 'Lobby-AP'},  # no stats (offline)
                {'type': 'ap', 'mac': 'aabbcc000004', 'site_id': 's2',
                 'name': 'Inv-AP-4', 'hostname': 'host-4'},
                {'type': 'ap', 'mac': 'aabbcc000005', 'site_id': 's2',
                 'name': None, 'hostname': 'host-5'},  # offline, hostname only
            ],
            paged('/api/v1/sites/s1/maps', 1): [{'id': 'm1', 'name': 'Floor 1'}],
            paged('/api/v1/sites/s2/maps', 1): [],
            self.ORG_STATS_PATH: (
                self.S1_STATS + self.S2_STATS + [
                    {'mac': 'aabbcc000004', 'site_id': 's2', 'name': None},
                ] if org_stats is None else org_stats),
            paged('/api/v1/sites/s1/stats/devices?type=ap', 1): self.S1_STATS,
            paged('/api/v1/sites/s2/stats/devices?type=ap', 1): self.S2_STATS + [
                {'mac': 'aabbcc000004', 'name': None},  # null stats name
            ],
        })

    def test_org_wide_uses_single_org_stats_query(self):
        api = self._make_api()
        with tempfile.TemporaryDirectory() as tmp:
            be.export_bssids(api, 'o1', 'My Org', self.SITES, None, Path(tmp) / 'o.csv')
        self.assertEqual([c for c in api.calls if 'stats' in c], [self.ORG_STATS_PATH])
        self.assertIn('radio_stat', self.ORG_STATS_PATH)
        self.assertIn('lldp_stat', self.ORG_STATS_PATH)

    def test_org_stats_missing_radio_stat_falls_back_per_site(self):
        s1_trimmed = [{k: v for k, v in s.items() if k != 'radio_stat'}
                      for s in self.S1_STATS]
        api = self._make_api(org_stats=s1_trimmed + self.S2_STATS)
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = be.export_bssids(
                api, 'o1', 'My Org', self.SITES, None, Path(tmp) / 'o.csv')
            with open(path, newline='', encoding='utf-8') as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]['RADIO_MACS'], 'radio24, radio5')
        stats_calls = [c for c in api.calls if 'stats' in c]
        self.assertEqual(stats_calls, [self.ORG_STATS_PATH,
                                       paged('/api/v1/sites/s1/stats/devices?type=ap', 1)])

    def test_scoped_export_uses_per_site_stats(self):
        api = self._make_api()
        with tempfile.TemporaryDirectory() as tmp:
            be.export_bssids(api, 'o1', 'My Org', self.SITES, {'s2'}, Path(tmp) / 'o.csv')
        self.assertEqual([c for c in api.calls if 'stats' in c],
                         [paged('/api/v1/sites/s2/stats/devices?type=ap', 1)])

    SITES = [
        {'id': 's1', 'name': 'HQ', 'address': '1 Main St'},
        {'id': 's2', 'name': 'Branch', 'address': ''},
    ]

    def test_full_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out.csv'
            path, count = be.export_bssids(
                self._make_api(), 'o1', 'My Org', self.SITES, None, out)
            self.assertEqual(count, 5)
            with open(path, newline='', encoding='utf-8-sig') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual([r['AP_MAC'] for r in rows],
                             ['aabbcc000001', 'aabbcc000002', 'aabbcc000003',
                              'aabbcc000004', 'aabbcc000005'])
            self.assertEqual(rows[0]['NAME'], 'AP-1')
            self.assertEqual(rows[0]['MAP'], 'Floor 1')
            self.assertEqual(rows[0]['SITE'], 'HQ')
            self.assertEqual(rows[0]['RADIO_MACS'], 'radio24, radio5')
            self.assertEqual(rows[0]['SWITCH_NAME'], 'sw1')
            self.assertEqual(rows[0]['SWITCH_PORT'], 'ge-0/0/1')
            self.assertEqual(rows[1]['NAME'], 'AP-2')
            self.assertEqual(rows[1]['RADIO_MACS'], '')
            self.assertEqual(rows[2]['NAME'], 'Lobby-AP')  # offline: inventory name
            self.assertEqual(rows[2]['RADIO_MACS'], '')
            self.assertEqual(rows[3]['NAME'], 'Inv-AP-4')  # null stats name
            self.assertEqual(rows[4]['NAME'], 'host-5')  # hostname fallback

    def test_device_stats_second_page_lands_in_csv(self):
        stats_path = '/api/v1/sites/s1/stats/devices?type=ap'
        api = FakeApi({
            f'/api/v1/orgs/o1/inventory?type=ap&limit={be.INVENTORY_PAGE_SIZE}&page=1': [
                {'type': 'ap', 'mac': 'aabbcc000001', 'site_id': 's1'},
                {'type': 'ap', 'mac': 'aabbcc000002', 'site_id': 's1'},
            ],
            paged('/api/v1/sites/s1/maps', 1): [],
            # Server applies a 1-item page even though 1000 was requested
            paged(stats_path, 1): FakeResponse(
                [{'mac': 'aabbcc000001', 'name': 'AP-1',
                  'radio_stat': {'band_5': {'mac': 'r1'}}}],
                {'X-Page-Total': '2', 'X-Page-Limit': '1'}),
            paged(stats_path, 2): FakeResponse(
                [{'mac': 'aabbcc000002', 'name': 'AP-2',
                  'radio_stat': {'band_5': {'mac': 'r2'}}}],
                {'X-Page-Total': '2', 'X-Page-Limit': '1'}),
        })
        with tempfile.TemporaryDirectory() as tmp:
            # Scoped export still pages the per-site stats endpoint.
            path, _ = be.export_bssids(
                api, 'o1', 'My Org', self.SITES, {'s1'}, Path(tmp) / 'out.csv')
            with open(path, newline='', encoding='utf-8-sig') as f:
                rows = list(csv.DictReader(f))
        self.assertEqual([r['RADIO_MACS'] for r in rows], ['r1', 'r2'])
        self.assertEqual(rows[1]['NAME'], 'AP-2')

    def _failing_api(self, failing_path):
        api = self._make_api()
        real = api.get

        def get(path):
            # get_all_pages appends ?limit=&page= or &limit=&page=.
            if path == failing_path or path.startswith((failing_path + '&', failing_path + '?')):
                raise be.requests.exceptions.ReadTimeout('read timed out')
            return real(path)
        api.get = get
        return api

    def test_stats_failure_aborts_and_keeps_previous_csv(self):
        org_stats = f'/api/v1/orgs/o1/stats/devices?type=ap&fields={be.ORG_STATS_FIELDS}'
        for failing in (org_stats, '/api/v1/sites/s1/maps'):
            with self.subTest(failing=failing), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / 'out.csv'
                out.write_text('previous good export\n', encoding='utf-8')
                with self.assertRaises(be.requests.exceptions.RequestException):
                    be.export_bssids(self._failing_api(failing), 'o1', 'My Org',
                                     self.SITES, None, out)
                self.assertEqual(out.read_text(encoding='utf-8'), 'previous good export\n')
                self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ['out.csv'])

    def test_stats_failure_exits_nonzero(self):
        api = self._failing_api(
            f'/api/v1/orgs/o1/stats/devices?type=ap&fields={be.ORG_STATS_FIELDS}')
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(be, 'load_config', return_value={
                 'api_url': 'https://api.mist.com', 'api_token': 't', 'org_id': 'o1'}), \
             patch.object(be, 'MistSession', return_value=api), \
             patch.object(be, 'validate_credentials', return_value='My Org'), \
             patch.object(be, 'fetch_sites', return_value=self.SITES):
            rc = be.main(['--all', '-o', str(Path(tmp) / 'out.csv')])
            self.assertEqual(rc, 2)
            self.assertFalse((Path(tmp) / 'out.csv').exists())

    def test_csv_has_utf8_bom_for_excel(self):
        sites = [{'id': 's1', 'name': 'São Paulo', 'address': '1 Avenida Café'},
                 {'id': 's2', 'name': 'Branch', 'address': ''}]
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = be.export_bssids(
                self._make_api(), 'o1', 'My Org', sites, None, Path(tmp) / 'out.csv')
            raw = path.read_bytes()
            self.assertTrue(raw.startswith(b'\xef\xbb\xbfNAME,'))
            self.assertIn('Avenida Café'.encode('utf-8'), raw)
            with open(path, newline='', encoding='utf-8-sig') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]['SITE'], 'São Paulo')
            self.assertEqual(rows[0]['SITE_ADDRESS'], '1 Avenida Café')

    def test_null_stats_mac_is_skipped(self):
        api = self._make_api()
        api.responses[self.ORG_STATS_PATH].insert(
            0, {'mac': None, 'name': 'ghost', 'site_id': 's1'})
        api.responses[self.ORG_STATS_PATH].append({'name': 'no-mac', 'site_id': 's2'})
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out.csv'
            path, count = be.export_bssids(api, 'o1', 'My Org', self.SITES, None, out)
            self.assertEqual(count, 5)
            with open(path, newline='', encoding='utf-8-sig') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]['NAME'], 'AP-1')
            self.assertNotIn('ghost', [r['NAME'] for r in rows])
            self.assertNotIn('no-mac', [r['NAME'] for r in rows])

    def test_maps_past_first_page(self):
        api = self._make_api()
        total = {'X-Page-Total': str(be.PAGE_SIZE + 1)}
        page1 = [{'id': f'filler{i}', 'name': f'F{i}'} for i in range(be.PAGE_SIZE)]
        api.responses[paged('/api/v1/sites/s1/maps', 1)] = FakeResponse(page1, total)
        api.responses[paged('/api/v1/sites/s1/maps', 2)] = FakeResponse(
            [{'id': 'm1', 'name': 'Floor 1'}], total)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out.csv'
            path, _ = be.export_bssids(api, 'o1', 'My Org', self.SITES, None, out)
            with open(path, newline='', encoding='utf-8-sig') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]['MAP'], 'Floor 1')

    def test_scoped_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out.csv'
            path, count = be.export_bssids(
                self._make_api(), 'o1', 'My Org', self.SITES, {'s2'}, out)
            self.assertEqual(count, 3)
            with open(path, newline='', encoding='utf-8-sig') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual({r['SITE'] for r in rows}, {'Branch'})

    def test_empty_scope_raises(self):
        with self.assertRaises(be.ConfigError):
            be.export_bssids(self._make_api(), 'o1', 'My Org', self.SITES,
                             {'no-such-site'}, None)

    def test_output_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = be.export_bssids(
                self._make_api(), 'o1', 'My Org', self.SITES, None, Path(tmp))
            self.assertTrue(str(path).startswith(tmp))
            self.assertTrue(path.name.startswith('My_Org.bssid-export-'))
            self.assertTrue(path.name.endswith('.csv'))

    def test_output_nonexistent_directory_is_created(self):
        # A -o path without a file extension is a directory, even if it
        # doesn't exist yet — never an extensionless output file.
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'exports'
            path, _ = be.export_bssids(
                self._make_api(), 'o1', 'My Org', self.SITES, None, target)
            self.assertTrue(target.is_dir())
            self.assertEqual(path.parent, target)
            self.assertTrue(path.name.endswith('.csv'))


    def test_output_tilde_is_expanded(self):
        with tempfile.TemporaryDirectory() as home, \
                tempfile.TemporaryDirectory() as cwd:
            prev = os.getcwd()
            os.chdir(cwd)
            try:
                with patch.dict(os.environ, {'HOME': home, 'USERPROFILE': home}):
                    path, _ = be.export_bssids(
                        self._make_api(), 'o1', 'My Org', self.SITES, None,
                        Path('~/exports'))
                    file_path, _ = be.export_bssids(
                        self._make_api(), 'o1', 'My Org', self.SITES, None,
                        Path('~/out/file.csv'))
            finally:
                os.chdir(prev)
            self.assertEqual(path.parent, Path(home) / 'exports')
            self.assertEqual(file_path, Path(home) / 'out' / 'file.csv')
            self.assertTrue(file_path.is_file())
            self.assertFalse((Path(cwd) / '~').exists())


class TestInteractiveHelpers(unittest.TestCase):
    SITES = [
        {'id': 'id-a', 'name': 'Alpha'},
        {'id': 'id-b', 'name': 'Beta'},
        {'id': 'id-c', 'name': 'Gamma'},
    ]
    GROUPS = [
        {'id': 'g-1', 'name': 'Campus', 'site_ids': ['id-a']},
        {'id': 'g-2', 'name': 'Retail', 'site_ids': ['id-b', 'id-c']},
    ]

    def test_cloud_menu_matches_endpoints(self):
        items = be.cloud_menu()
        self.assertEqual(len(items), len(be.CLOUD_ENDPOINTS))
        self.assertEqual(items[0], ('Global 01', 'https://api.mist.com'))
        self.assertIn(('EMEA 01', 'https://api.eu.mist.com'), items)
        self.assertIn(('APAC 03', 'https://api.gc7.mist.com'), items)

    def test_parse_site_selection_numbers(self):
        self.assertEqual(be.parse_site_selection('1,3', self.SITES), {'id-a', 'id-c'})

    def test_parse_site_selection_mixed(self):
        self.assertEqual(be.parse_site_selection('2, gamma, id-a', self.SITES),
                         {'id-a', 'id-b', 'id-c'})

    def test_parse_site_selection_out_of_range_number_is_name(self):
        with self.assertRaises(be.ConfigError):
            be.parse_site_selection('99', self.SITES)

    def test_parse_site_selection_comma_in_name(self):
        sites = self.SITES + [{'id': 'id-d', 'name': 'Dallas, TX'}]
        self.assertEqual(be.parse_site_selection('dallas, tx', sites), {'id-d'})
        self.assertEqual(be.parse_site_selection('1, "Dallas, TX"', sites),
                         {'id-a', 'id-d'})

    def test_parse_site_selection_empty(self):
        with self.assertRaises(be.ConfigError):
            be.parse_site_selection(' , ', self.SITES)

    def test_match_group_by_number_name_id(self):
        self.assertEqual(be.match_group('2', self.GROUPS)['id'], 'g-2')
        self.assertEqual(be.match_group('campus', self.GROUPS)['id'], 'g-1')
        self.assertEqual(be.match_group('g-2', self.GROUPS)['id'], 'g-2')

    DUP_GROUPS = [
        {'id': 'g-1', 'name': 'Campus', 'site_ids': ['id-a']},
        {'id': 'g-9', 'name': 'campus', 'site_ids': ['id-b', 'id-c']},
    ]

    def test_duplicate_group_name_is_ambiguous(self):
        with self.assertRaises(be.ConfigError) as ctx:
            be.match_group('Campus', self.DUP_GROUPS)
        self.assertIn('g-1', str(ctx.exception))
        self.assertIn('g-9', str(ctx.exception))
        with self.assertRaises(be.ConfigError) as ctx:
            be.resolve_scope(self.SITES, self.DUP_GROUPS, None, 'Campus')
        self.assertIn('group ID', str(ctx.exception))

    def test_duplicate_group_name_resolved_by_id_or_number(self):
        self.assertEqual(be.match_group('g-9', self.DUP_GROUPS)['id'], 'g-9')
        self.assertEqual(be.match_group('1', self.DUP_GROUPS)['id'], 'g-1')
        self.assertEqual(be.resolve_scope(self.SITES, self.DUP_GROUPS, None, 'g-9'),
                         {'id-b', 'id-c'})

    def test_match_group_unknown(self):
        with self.assertRaises(be.ConfigError):
            be.match_group('nope', self.GROUPS)

    def test_numeric_name_collision_is_ambiguous(self):
        # A site literally named '1' sitting at a different list position
        # must not be silently resolved either way.
        sites = [{'id': 'id-x', 'name': 'Zeta'}, {'id': 'id-y', 'name': '1'}]
        with self.assertRaises(be.ConfigError) as ctx:
            be.parse_site_selection('1', sites)
        self.assertIn('disambiguate', str(ctx.exception))

    def test_numeric_name_collision_same_entry_ok(self):
        # Site named '1' that IS entry 1 — no ambiguity.
        sites = [{'id': 'id-y', 'name': '1'}, {'id': 'id-x', 'name': 'Zeta'}]
        self.assertEqual(be.parse_site_selection('1', sites), {'id-y'})

    def test_group_numeric_name_collision_is_ambiguous(self):
        groups = [{'id': 'g-x', 'name': 'Main', 'site_ids': ['a']},
                  {'id': 'g-y', 'name': '1', 'site_ids': ['b']}]
        with self.assertRaises(be.ConfigError):
            be.match_group('1', groups)

    def test_write_env_file_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / 'deep' / 'nested' / '.env'
            be.write_env_file(env_file, 'https://api.mist.com', 't', 'o')
            self.assertTrue(env_file.is_file())

    def test_shadowing_env_vars(self):
        with patch.object(be, '_SHELL_ENV',
                          {'MIST_API_TOKEN': 'stale-token', 'MIST_CLOUD': 'emea01'}):
            shadowing = be.shadowing_env_vars('https://api.mist.com', 'new-token', 'org')
            self.assertEqual(set(shadowing), {'MIST_API_TOKEN', 'MIST_CLOUD'})
        with patch.object(be, '_SHELL_ENV', {'MIST_CLOUD': 'global01'}):
            # shell MIST_CLOUD agrees with the saved URL — no warning
            self.assertEqual(be.shadowing_env_vars('https://api.mist.com', 't', 'o'), [])
        with patch.object(be, '_SHELL_ENV', {}):
            self.assertEqual(be.shadowing_env_vars('https://api.mist.com', 't', 'o'), [])

    def test_write_env_file_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / '.env'
            be.write_env_file(env_file, 'https://api.eu.mist.com', 'tok-1', 'org-1')
            with patch.dict(os.environ, {}, clear=False):
                for key in ('MIST_API_TOKEN', 'MIST_ORG_ID', 'MIST_API_URL', 'MIST_CLOUD'):
                    os.environ.pop(key, None)
                config = be.load_config(env_file)
                self.assertEqual(config['api_url'], 'https://api.eu.mist.com')
                self.assertEqual(config['api_token'], 'tok-1')
                self.assertEqual(config['org_id'], 'org-1')

    def test_interactive_setup_writes_env_and_returns_config(self):
        answers = iter(['org-1', 'tok-1', '6'])  # 6 = EMEA 01
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / '.env'
            with patch('builtins.input', lambda *_: next(answers)), \
                 patch.object(be, 'validate_credentials', return_value='Test Org'):
                config = be.interactive_setup(env_file)
            self.assertEqual(config['org_name'], 'Test Org')
            self.assertEqual(config['api_url'], 'https://api.eu.mist.com')
            self.assertTrue(env_file.is_file())
            self.assertIn('MIST_ORG_ID=org-1', env_file.read_text(encoding='utf-8'))


class TestWantsInteractive(unittest.TestCase):
    def _args(self, argv):
        return be.build_parser().parse_args(argv)

    def test_no_args_is_interactive(self):
        self.assertTrue(be.wants_interactive(self._args([])))

    def test_env_alone_is_interactive(self):
        self.assertTrue(be.wants_interactive(self._args(['--env', 'x'])))

    def test_action_flags_are_cli(self):
        for argv in (['--all'], ['--sites', 'HQ'], ['--site-group', 'g'],
                     ['--list-sites'], ['--list-groups'], ['-o', 'out.csv']):
            self.assertFalse(be.wants_interactive(self._args(argv)), argv)

    def test_all_conflicts_with_sites(self):
        with self.assertRaises(SystemExit):
            self._args(['--all', '--sites', 'HQ'])


class TestLoadConfig(unittest.TestCase):
    def test_missing_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / '.env'
            env_file.write_text('MIST_API_TOKEN=your-api-token-here\n', encoding='utf-8')
            with patch.dict(os.environ, {}, clear=False):
                for key in ('MIST_API_TOKEN', 'MIST_ORG_ID', 'MIST_API_URL', 'MIST_CLOUD'):
                    os.environ.pop(key, None)
                with self.assertRaises(be.ConfigError) as ctx:
                    be.load_config(env_file)
                self.assertIn('MIST_API_TOKEN', str(ctx.exception))
                self.assertIn('MIST_ORG_ID', str(ctx.exception))

    def test_explicit_env_missing_file(self):
        with self.assertRaises(be.ConfigError):
            be.load_config(Path('Z:/does/not/exist/.env'))

    def test_valid_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / '.env'
            env_file.write_text(
                'MIST_API_TOKEN=tok\nMIST_ORG_ID=org\nMIST_CLOUD=emea01\n',
                encoding='utf-8',
            )
            with patch.dict(os.environ, {}, clear=False):
                for key in ('MIST_API_TOKEN', 'MIST_ORG_ID', 'MIST_API_URL', 'MIST_CLOUD'):
                    os.environ.pop(key, None)
                config = be.load_config(env_file)
                self.assertEqual(config['api_url'], 'https://api.eu.mist.com')
                self.assertEqual(config['api_token'], 'tok')
                self.assertEqual(config['org_id'], 'org')


if __name__ == '__main__':
    unittest.main()
