import logging
import math

from datetime import timedelta

from django.db import DatabaseError
from django.utils import timezone

from OpenBench.models import DatagenSample, Test


LOGGER = logging.getLogger(__name__)

SAMPLE_INTERVAL = timedelta(minutes=1)
HISTORY_WINDOW = timedelta(hours=2)
EMA_HALF_LIFE_SECONDS = timedelta(minutes=5).total_seconds()
STALL_THRESHOLD = timedelta(minutes=10)


def _prune_samples(test, now):

    cutoff = now - HISTORY_WINDOW
    anchor = DatagenSample.objects.filter(
        test=test, created__lte=cutoff
    ).order_by('-created').first()

    stale = DatagenSample.objects.filter(test=test, created__lt=cutoff)
    if anchor:
        stale = stale.exclude(pk=anchor.pk)
    stale.delete()


def record_sample(test, force=False, now=None):

    now = now or timezone.now()
    latest = DatagenSample.objects.filter(test=test).order_by('-created').first()

    if latest and not force and now - latest.created < SAMPLE_INTERVAL:
        return latest

    sample = DatagenSample.objects.create(test=test, games=test.games, created=now)
    _prune_samples(test, now)
    return sample


def safe_record_sample(test_id, force=False):

    try:
        test = Test.objects.only('id', 'games').get(pk=test_id, test_mode='DATAGEN')
        return record_sample(test, force=force)
    except (DatabaseError, Test.DoesNotExist):
        LOGGER.exception('Unable to record progress for datagen workload %s', test_id)
        return None


def _recent_samples(test, now):

    cutoff = now - HISTORY_WINDOW
    anchor = DatagenSample.objects.filter(
        test=test, created__lte=cutoff
    ).order_by('-created').first()
    samples = list(DatagenSample.objects.filter(
        test=test, created__gt=cutoff, created__lte=now
    ).order_by('created'))

    if anchor:
        samples.insert(0, anchor)
    return samples


def progress_payload(test, now=None):

    now = now or timezone.now()
    samples = _recent_samples(test, now)

    points = [(sample.created, sample.games) for sample in samples]
    if points and (points[-1][0] < now or points[-1][1] != test.games):
        points.append((now, test.games))

    ema_rate = None
    last_progress = None
    series = []

    for previous, current in zip(points, points[1:]):
        elapsed = (current[0] - previous[0]).total_seconds()
        completed = current[1] - previous[1]
        if elapsed <= 0:
            continue

        if completed < 0:
            ema_rate = None
            continue

        measured_rate = completed / elapsed
        alpha = 1.0 - math.pow(0.5, elapsed / EMA_HALF_LIFE_SECONDS)

        if ema_rate is None and completed > 0:
            ema_rate = measured_rate
        elif ema_rate is not None:
            ema_rate += alpha * (measured_rate - ema_rate)

        if completed > 0:
            last_progress = current[0]

        if ema_rate is not None and current[0] >= now - HISTORY_WINDOW:
            series.append({
                'timestamp': current[0].timestamp(),
                'rate': ema_rate,
                'games': current[1],
            })

    remaining = max(0, test.max_games - test.games)
    eta_seconds = None

    if remaining == 0:
        state = 'complete'
        eta_seconds = 0
    elif test.finished:
        state = 'stopped'
    elif last_progress is None or ema_rate is None:
        state = 'calculating'
    elif now - last_progress >= STALL_THRESHOLD:
        state = 'no_recent_progress'
    else:
        state = 'running'
        eta_seconds = math.ceil(remaining / ema_rate)

    first_timestamp = points[0][0] if points else now
    window_start = max(now - HISTORY_WINDOW, first_timestamp)

    return {
        'games': test.games,
        'maxGames': test.max_games,
        'finished': test.finished,
        'generatedAt': now.timestamp(),
        'windowStart': window_start.timestamp(),
        'windowEnd': now.timestamp(),
        'currentRate': ema_rate,
        'etaSeconds': eta_seconds,
        'state': state,
        'series': series,
    }
