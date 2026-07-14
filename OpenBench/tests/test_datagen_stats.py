import math

from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.db import DatabaseError
from django.test import Client, RequestFactory, TestCase
from django.utils import timezone

import OpenBench.datagen_stats as datagen_stats
import OpenBench.utils
import OpenBench.workloads.get_workload as get_workload_module

from OpenBench.models import DatagenSample, Engine, Machine, Profile, Result, Test


class DatagenTestCase(TestCase):

    def setUp(self):
        self.engine = Engine.objects.create(name='Engine', source='https://example.com', sha='a' * 40, bench=1)

    def workload(self, **overrides):
        fields = {
            'author': 'author',
            'book_name': 'NONE',
            'dev': self.engine,
            'dev_repo': 'https://example.com',
            'dev_engine': 'Engine',
            'dev_options': 'Threads=1 Hash=16',
            'dev_time_control': 'N=1',
            'base': self.engine,
            'base_repo': 'https://example.com',
            'base_engine': 'Engine',
            'base_options': 'Threads=1 Hash=16',
            'base_time_control': 'N=1',
            'test_mode': 'DATAGEN',
            'max_games': 1000,
        }
        fields.update(overrides)
        return Test.objects.create(**fields)

    def sample(self, workload, games, created):
        return DatagenSample.objects.create(test=workload, games=games, created=created)


class SampleRecordingTests(DatagenTestCase):

    def test_samples_are_throttled_and_final_sample_is_forced(self):
        now = timezone.now()
        workload = self.workload(games=0)

        first = datagen_stats.record_sample(workload, now=now)
        workload.games = 30
        workload.save(update_fields=['games'])
        throttled = datagen_stats.record_sample(workload, now=now + timedelta(seconds=30))
        forced = datagen_stats.record_sample(workload, force=True, now=now + timedelta(seconds=31))

        self.assertEqual(first.pk, throttled.pk)
        self.assertNotEqual(first.pk, forced.pk)
        self.assertEqual(list(workload.datagen_samples.values_list('games', flat=True)), [0, 30])

    def test_retention_keeps_one_anchor_before_window(self):
        now = timezone.now()
        workload = self.workload(games=40)
        oldest = self.sample(workload, 0, now - timedelta(hours=3))
        anchor = self.sample(workload, 10, now - timedelta(hours=2, minutes=30))
        recent = self.sample(workload, 20, now - timedelta(hours=1))

        datagen_stats.record_sample(workload, force=True, now=now)

        remaining = set(workload.datagen_samples.values_list('pk', flat=True))
        self.assertNotIn(oldest.pk, remaining)
        self.assertIn(anchor.pk, remaining)
        self.assertIn(recent.pk, remaining)

    @mock.patch('OpenBench.datagen_stats.record_sample', side_effect=DatabaseError('unavailable'))
    def test_safe_recording_contains_database_errors(self, _record):
        workload = self.workload()
        with mock.patch.object(datagen_stats.LOGGER, 'exception') as logged:
            self.assertIsNone(datagen_stats.safe_record_sample(workload.id))
        logged.assert_called_once()


class ProgressCalculationTests(DatagenTestCase):

    def test_time_based_ema_decays_during_zero_progress(self):
        now = timezone.now()
        workload = self.workload(games=120)
        self.sample(workload, 0, now - timedelta(minutes=3))
        self.sample(workload, 60, now - timedelta(minutes=2))
        self.sample(workload, 120, now - timedelta(minutes=1))

        payload = datagen_stats.progress_payload(workload, now=now)
        decay_alpha = 1.0 - pow(0.5, 60 / datagen_stats.EMA_HALF_LIFE_SECONDS)
        expected = 1.0 + decay_alpha * (0.0 - 1.0)

        self.assertEqual(payload['state'], 'running')
        self.assertAlmostEqual(payload['currentRate'], expected)
        self.assertEqual(payload['etaSeconds'], math.ceil(880 / expected))
        self.assertEqual(payload['series'][-1]['games'], 120)

    def test_no_samples_is_calculating_without_fabricated_rate(self):
        payload = datagen_stats.progress_payload(self.workload(games=500))
        self.assertEqual(payload['state'], 'calculating')
        self.assertIsNone(payload['currentRate'])
        self.assertEqual(payload['series'], [])

    def test_stall_complete_and_stopped_states(self):
        now = timezone.now()
        stalled = self.workload(games=60)
        self.sample(stalled, 0, now - timedelta(minutes=12))
        self.sample(stalled, 60, now - timedelta(minutes=11))
        self.assertEqual(datagen_stats.progress_payload(stalled, now=now)['state'], 'no_recent_progress')

        complete = self.workload(games=1000, finished=True)
        complete_payload = datagen_stats.progress_payload(complete, now=now)
        self.assertEqual(complete_payload['state'], 'complete')
        self.assertEqual(complete_payload['etaSeconds'], 0)

        stopped = self.workload(games=500, finished=True)
        self.assertEqual(datagen_stats.progress_payload(stopped, now=now)['state'], 'stopped')

    def test_recent_query_includes_anchor_before_window(self):
        now = timezone.now()
        workload = self.workload(games=180)
        self.sample(workload, 0, now - timedelta(hours=3))
        self.sample(workload, 60, now - timedelta(hours=2, minutes=1))
        self.sample(workload, 120, now - timedelta(hours=1, minutes=59))
        self.sample(workload, 180, now - timedelta(hours=1, minutes=58))

        payload = datagen_stats.progress_payload(workload, now=now)
        self.assertEqual(payload['series'][0]['games'], 120)


class DatagenProgressIntegrationTests(DatagenTestCase):

    @mock.patch('OpenBench.workloads.get_workload.workload_to_dictionary', return_value={})
    @mock.patch('OpenBench.workloads.get_workload.select_workload')
    @mock.patch('OpenBench.datagen_stats.safe_record_sample')
    def test_worker_assignment_records_a_baseline(self, record, select, _serialize):
        user = User.objects.create_user('worker')
        workload = self.workload()
        machine = Machine.objects.create(user=user, info={'concurrency': 1})
        select.return_value = workload

        get_workload_module.get_workload(RequestFactory().get('/'), machine)

        record.assert_called_once_with(workload.id)

    def test_endpoint_returns_progress_and_disables_caching(self):
        workload = self.workload()
        response = Client().get('/api/workload/%d/datagen-progress/' % workload.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(set(response.json()), {
            'games', 'maxGames', 'finished', 'generatedAt', 'windowStart',
            'windowEnd', 'currentRate', 'etaSeconds', 'state', 'series',
        })

    def test_widget_only_appears_on_datagen_pages(self):
        datagen = self.workload()
        fixed = self.workload(test_mode='GAMES')
        client = Client()

        datagen_page = client.get('/datagen/%d/' % datagen.id)
        fixed_page = client.get('/test/%d/' % fixed.id)

        self.assertContains(datagen_page, 'id="datagen-rate-graph"')
        self.assertNotContains(fixed_page, 'id="datagen-rate-graph"')

    @mock.patch('OpenBench.datagen_stats.record_sample', side_effect=DatabaseError('unavailable'))
    def test_telemetry_failure_does_not_rollback_results(self, _record):
        user = User.objects.create_user('worker')
        Profile.objects.create(user=user, enabled=True)
        workload = self.workload(games=0, approved=True)
        machine = Machine.objects.create(user=user, info={}, workload=workload.id)
        result = Result.objects.create(test=workload, machine=machine)
        request = RequestFactory().post('/clientSubmitResults/', {
            'crashes': '0',
            'timelosses': '0',
            'illegals': '0',
            'machine_id': str(machine.id),
            'result_id': str(result.id),
            'test_id': str(workload.id),
            'trinomial': '0 2 0',
            'pentanomial': '0 0 1 0 0',
        })

        with mock.patch.object(datagen_stats.LOGGER, 'exception') as logged:
            with self.captureOnCommitCallbacks(execute=True):
                response = OpenBench.utils.update_test(request, machine)

        workload.refresh_from_db()
        result.refresh_from_db()
        logged.assert_called_once()
        self.assertEqual(response, {})
        self.assertEqual(workload.games, 2)
        self.assertEqual(result.games, 2)
