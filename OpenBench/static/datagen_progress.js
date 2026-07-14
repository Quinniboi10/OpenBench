(function() {
    'use strict';

    const POLL_INTERVAL_MS = 30000;

    function formatRate(rate) {
        if (rate === null) return '\u2014';
        if (rate < 0.01) return '< 0.01';
        if (rate < 10) return rate.toFixed(2);
        return rate.toFixed(1);
    }

    function formatDuration(seconds) {
        if (seconds === null) return 'Calculating';
        if (seconds < 60) return '< 1 minute';

        const minutes = Math.ceil(seconds / 60);
        const days = Math.floor(minutes / 1440);
        const hours = Math.floor((minutes % 1440) / 60);
        const remainingMinutes = minutes % 60;

        if (days) return `${days}d ${hours}h`;
        if (hours) return `${hours}h ${remainingMinutes}m`;
        return `${remainingMinutes}m`;
    }

    function formatTime(timestamp) {
        return new Date(timestamp * 1000).toLocaleTimeString([], {
            hour: '2-digit', minute: '2-digit',
        });
    }

    window.initialize_datagen_progress = function(workloadId) {
        const panel = document.getElementById('datagen-progress');
        const rateElement = document.getElementById('datagen-rate');
        const etaElement = document.getElementById('datagen-eta');
        const completedElement = document.getElementById('datagen-completed');
        let timer = null;

        const graph = new window.OpenBenchHistoryGraph(
            document.getElementById('datagen-rate-graph'),
            {
                formatY: formatRate,
                formatX: formatTime,
                formatTooltip: point =>
                    `${formatTime(point.x)} | ${formatRate(point.y)} games/s | ${point.games.toLocaleString()} games`,
            }
        );

        function render(data) {
            panel.classList.remove('stale');
            rateElement.textContent = formatRate(data.currentRate);
            completedElement.textContent = `${data.games.toLocaleString()} / ${data.maxGames.toLocaleString()} games`;

            const etaText = {
                calculating: 'Calculating',
                no_recent_progress: 'No recent progress',
                complete: 'Complete',
                stopped: 'Stopped',
            };
            etaElement.textContent = data.state === 'running'
                ? formatDuration(data.etaSeconds)
                : etaText[data.state];

            graph.setData({
                points: data.series.map(point => ({
                    x: point.timestamp,
                    y: point.rate,
                    games: point.games,
                })),
                xMin: data.windowStart,
                xMax: data.windowEnd,
                emptyText: 'Waiting for completed games',
            });

            if (data.finished && timer !== null) {
                window.clearInterval(timer);
                timer = null;
            }
        }

        async function poll() {
            try {
                const response = await fetch(`/api/workload/${workloadId}/datagen-progress/`, {
                    credentials: 'same-origin',
                    cache: 'no-store',
                });
                if (!response.ok) throw new Error(`Progress request failed: ${response.status}`);

                const data = await response.json();
                if (data.error) throw new Error(data.error);
                render(data);
            } catch (error) {
                panel.classList.add('stale');
                console.error(error);
            }
        }

        poll();
        timer = window.setInterval(poll, POLL_INTERVAL_MS);
    };
})();
