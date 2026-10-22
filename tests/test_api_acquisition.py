"""Source identity and completeness through public acquire and a real metadata process."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import test_link_input
from bbdown_fixture import configured_fake, fixture_config, URL, BV, MEDIA
from drum_score.public_video import acquire, InputError
from score_fixtures import score_frame, video_from_image


class APIAcquisitionTests(unittest.TestCase):
    def run_case(self, base, video, config=None, *, response=None):
        calls = base / 'events'
        def fetch(request, **kwargs):
            with calls.open('a') as event:
                event.write('media\n')
            return response(request, **kwargs) if response else io.BytesIO(video.read_bytes())
        with configured_fake(base, config or fixture_config(), video, response=fetch):
            try:
                source, origin = acquire(URL, base / 'result')
                return 0, {'origin': origin, 'source': {'path': str(source)}}, calls.read_text().splitlines() if calls.exists() else []
            except InputError as error:
                result = {'error': {'code': error.code, 'message': str(error),
                          **getattr(error, 'diagnostics', {})}}
                return 2, result, calls.read_text().splitlines() if calls.exists() else []

    def reject(self, config, expected='unavailable_page'):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            status, result, events = self.run_case(root, root / 'unused', config)
            self.assertEqual(status, 2, result)
            self.assertEqual(result['error']['code'], expected)
            self.assertEqual(events, [])
            self.assertFalse((root / 'result').exists())
            self.assertNotIn('DO_NOT_SAVE_TEST_SENTINEL', str(result))

    def test_metadata_selects_requested_page_and_records_full_identity(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            video = video_from_image(score_frame(), root)
            status, result, events = self.run_case(root, video)
            self.assertEqual(status, 0, result)
            self.assertEqual(result['origin']['cid'], 22)
            self.assertEqual(result['origin']['aid'], 44)
            self.assertEqual(result['origin']['full_duration'], 2)
            self.assertEqual(result['origin']['acquisition_route'], 'bbdown_direct')
            self.assertEqual(events, ['media'])
            self.assertEqual(Path(result['source']['path']).read_bytes(), video.read_bytes())

    def test_wrong_or_ambiguous_bvid_page_cid_and_aid_never_download(self):
        for field, value in [('bvid', 'BV1np421S78S'), ('aid', 0), ('aid', True),
                ('pages', [{'page': 1, 'cid': 11, 'duration': 2}]),
                ('pages', [{'page': 2, 'cid': 22, 'duration': 2}] * 2),
                ('pages', [{'page': 2, 'cid': False, 'duration': 2}])]:
            config = fixture_config()
            config['view'][field] = value
            with self.subTest(field=field, value=value):
                self.reject(config)

    def test_missing_complete_view_or_player_and_duplicate_responses_are_rejected(self):
        for mode in ('no-view', 'no-player', 'duplicate-view', 'duplicate-player', 'truncated-view', 'truncated-player'):
            config = fixture_config()
            view = {'code': 0, 'data': config['view']}
            player = {'code': 0, 'data': config['player']}
            config['responses'] = {'no-view': [player], 'no-player': [view],
                'duplicate-view': [view, view, player], 'duplicate-player': [view, player, player],
                'truncated-view': [player], 'truncated-player': [view]}[mode]
            if mode.startswith('truncated'):
                config['extra_stdout'] = 'Response: {"code":0,"data":' + 'x' * 8192 + '…（已截断）'
            with self.subTest(mode=mode):
                self.reject(config)

    def test_interactive_redirected_and_exclusive_videos_are_rejected(self):
        for target, field, value in [('view', 'rights', {'is_stein_gate': 1}),
                ('view', 'redirect_url', 'https://www.bilibili.com/bangumi/play/ep1'),
                ('view', 'is_upower_exclusive', True), ('player', 'is_upower_exclusive', True)]:
            config = fixture_config()
            config[target][field] = value
            self.reject(config, 'unsupported_stream')

    def test_missing_restriction_fields_cannot_be_assumed_false(self):
        for target, field in [('view', 'rights'), ('player', 'is_upower_exclusive')]:
            config = fixture_config()
            config[target].pop(field)
            self.reject(config)

    def test_player_cid_and_aid_must_match_view(self):
        for field, value in [('cid', 11), ('aid', 99), ('cid', True)]:
            config = fixture_config()
            config['player'][field] = value
            self.reject(config)

    def test_request_playurl_identity_must_match_the_selected_page(self):
        for query in ('avid=44&cid=11', 'avid=99&cid=22', 'bvid=BV1np421S78S&cid=22',
                      'avid=44&cid=22&cid=11', 'cid=22', 'avid=44&aid=99&cid=22'):
            self.reject(fixture_config(query=query))

    def test_missing_or_multiple_playurl_files_fail_closed(self):
        for files in (0, 2):
            self.reject(fixture_config(files=files))

    def test_preview_and_incomplete_declared_duration_never_download(self):
        for field, value in [('is_preview', True), ('is_upower_exclusive', True),
                             ('timelength', 500), ('timelength', 0), ('timelength', None)]:
            config = fixture_config()
            config['play'][field] = value
            self.reject(config, 'incomplete_video')

    def test_unknown_or_nonfinite_full_duration_is_rejected(self):
        for value in (None, 0, -1, True, '2'):
            config = fixture_config()
            config['view']['pages'][1]['duration'] = value
            self.reject(config, 'incomplete_video')

    def test_oversized_raw_output_is_bounded_and_not_published(self):
        self.reject(fixture_config(extra_stdout='DO_NOT_SAVE_TEST_SENTINEL' * 100000), 'download_too_large')

    def test_multisegment_durl_cannot_masquerade_as_complete_video(self):
        config = fixture_config(play={'timelength': 2000, 'durl': [{'url': MEDIA}, {'url': MEDIA}]})
        self.reject(config, 'unsupported_stream')

    def test_actual_duration_is_checked_for_every_successful_metadata_route(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            video = video_from_image(score_frame(), root)
            config = fixture_config()
            config['view']['pages'][1]['duration'] = 20
            config['play']['timelength'] = 20000
            status, result, events = self.run_case(root, video, config)
            self.assertEqual(status, 2, result)
            self.assertEqual(result['error']['code'], 'incomplete_video')
            self.assertEqual(events, ['media'])
            self.assertFalse((root / 'result').exists())

    def test_pinned_binary_digest_is_required_without_trusting_banner(self):
        from drum_score import bbdown_cli
        from bbdown_fixture import install_fake_bbdown
        import os
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            binary, digest = install_fake_bbdown(root, fixture_config())
            with patch.dict(os.environ, {'PATH': str(binary.parent) + os.pathsep + os.environ['PATH']}):
                with self.assertRaises(InputError) as raised:
                    acquire(URL, root / 'result')
            self.assertEqual(raised.exception.code, 'backend_version_mismatch')
            self.assertFalse((root / 'result').exists())

    def test_missing_binary_has_an_actionable_sanitized_error(self):
        from drum_score import bbdown_cli
        with tempfile.TemporaryDirectory() as d, patch.object(bbdown_cli.shutil, 'which', return_value=None):
            with self.assertRaises(InputError) as raised:
                acquire(URL, Path(d) / 'result')
            self.assertEqual(raised.exception.code, 'dependency_missing')

    def test_complete_playurl_json_size_limit_is_enforced(self):
        config = fixture_config()
        config['play']['large_unused'] = 'DO_NOT_SAVE_TEST_SENTINEL' * 100000
        self.reject(config, 'download_too_large')

    def test_truncated_or_duplicate_json_fields_do_not_override_identity(self):
        config = fixture_config()
        config['responses'] = [{'code': 0, 'data': config['player']}]
        config['extra_stdout'] = 'Response: {"code":0,"data":{"bvid":"' + BV + '","bvid":"' + BV + '","pages":[]}}'
        self.reject(config)

    def test_metadata_file_symlink_is_rejected_without_reading_target(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            sentinel = root / 'sentinel'
            sentinel.write_text('DO_NOT_SAVE_TEST_SENTINEL')
            config = fixture_config(files=0, debug_symlink=str(sentinel))
            status, result, events = self.run_case(root, root / 'unused', config)
            self.assertEqual(status, 2, result)
            self.assertEqual(events, [])
            self.assertEqual(sentinel.read_text(), 'DO_NOT_SAVE_TEST_SENTINEL')

    def test_format_labels_cannot_publish_arbitrary_upstream_strings(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            video = video_from_image(score_frame(), root)
            config = fixture_config()
            config['play']['dash']['video'][0]['id'] = 'DO_NOT_SAVE_TEST_SENTINEL'
            status, result, events = self.run_case(root, video, config)
            self.assertNotIn('DO_NOT_SAVE_TEST_SENTINEL', str(result))

    def test_complete_view_larger_than_legacy_log_cutoff_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            video = video_from_image(score_frame(), root)
            config = fixture_config()
            config['view']['desc'] = 'synthetic public description ' * 500
            self.assertGreater(len(json.dumps({'code': 0, 'data': config['view']})), 8192)
            status, result, events = self.run_case(root, video, config)
            self.assertEqual(status, 0, result)
            self.assertEqual(result['origin']['cid'], 22)
            self.assertEqual(events, ['media'])

    def test_complete_view_over_metadata_budget_is_rejected_before_media(self):
        config = fixture_config()
        config['view']['desc'] = 'x' * (2 * 1024**2 + 1)
        self.reject(config, 'download_too_large')
