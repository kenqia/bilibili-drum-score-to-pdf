"""Assertions shared by HTTP/real-worker history scenarios, not production code."""
import json

from drum_score.jobs import Jobs


def assert_record(case, task, auth, *, status, operation='submit', cache=None):
    jobs = Jobs(case.data)
    matches = [record for record in jobs.records.query(task=task)
               if record['operation'] == operation and record['status'] == status]
    case.assertEqual(len(matches), 1)
    record = matches[0]
    case.assertEqual(record['schema_version'], 1)
    case.assertEqual(record['input']['url'], 'https://www.bilibili.com/video/BV1rH4y1R7Rk?p=2')
    case.assertTrue(record['program']['version'])
    case.assertIsInstance(record['created_at'], (int, float))
    case.assertGreaterEqual(record['started_at'], record['created_at'])
    case.assertGreaterEqual(record['finished_at'], record['started_at'])
    case.assertEqual(record['expires_at'] - record['finished_at'], 604800)
    state = case.state(task, auth)
    case.assertEqual(record['settings']['options'], state['options'])
    case.assertIsInstance(record['settings']['limits'], dict)
    case.assertTrue(record['settings']['limits'])
    serialized = json.dumps(record)
    case.assertNotIn(auth['Authorization'].removeprefix('Bearer '), serialized)
    case.assertNotIn('SYNTHETIC_SIGNED_ADDRESS_AND_PRIVATE_PATH', serialized)
    if status == 'complete':
        manifest = json.loads((jobs.attempt_root(task, record['attempt']) / 'result/manifest.json').read_text())
        case.assertEqual(record['output'], manifest)
        case.assertEqual(record['input']['resolved_url'], manifest['source']['url'])
        case.assertIsNone(record['error'])
        case.assertFalse(manifest['reliable'])
        case.assertTrue(manifest['pages'])
        if cache:
            case.assertEqual(manifest['source']['cache']['status'], cache)
    elif status == 'failed':
        case.assertEqual(record['error']['code'], state['error']['code'])
        case.assertTrue(record['error']['stage'])
        case.assertIsNone(record['output'])
    elif status == 'cancelled':
        case.assertIsNone(record['output'])
    return record
