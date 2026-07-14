(function() {
    'use strict';

    const WIDTH = 320;
    const TOP = 6;
    const BOTTOM = 106;

    function clamp(value, minimum, maximum) {
        return Math.max(minimum, Math.min(maximum, value));
    }

    class OpenBenchHistoryGraph {
        constructor(root, options) {
            this.root = root;
            this.options = options || {};
            this.points = [];

            this.svg = root.querySelector('.history-graph-svg');
            this.plot = root.querySelector('.history-graph-plot');
            this.path = root.querySelector('.history-graph-path');
            this.empty = root.querySelector('.history-graph-empty');
            this.ymax = root.querySelector('.history-graph-ymax');
            this.ymid = root.querySelector('.history-graph-ymid');
            this.xmin = root.querySelector('.history-graph-xmin');
            this.xmax = root.querySelector('.history-graph-xmax');
            this.hoverLine = root.querySelector('.history-graph-hover-line');
            this.hoverPoint = root.querySelector('.history-graph-hover-point');
            this.tooltip = root.querySelector('.history-graph-tooltip');

            this.svg.addEventListener('mousemove', event => this._activateNearest(event.clientX));
            this.svg.addEventListener('mouseenter', event => this._activateNearest(event.clientX));
            this.svg.addEventListener('mouseleave', () => this._clearActive());
        }

        setData(data) {
            const input = data.points || [];
            const xMin = data.xMin;
            const xMax = Math.max(data.xMax, xMin + 1);
            const yMax = Math.max(1, ...input.map(point => point.y)) * 1.1;
            const formatY = this.options.formatY || (value => value.toFixed(1));
            const formatX = this.options.formatX || (value => String(value));

            this.ymax.textContent = formatY(yMax);
            this.ymid.textContent = formatY(yMax / 2);
            this.xmin.textContent = formatX(xMin);
            this.xmax.textContent = formatX(xMax);

            this.points = input.map(point => ({
                ...point,
                plotX: (point.x - xMin) / (xMax - xMin) * WIDTH,
                plotY: BOTTOM - point.y / yMax * (BOTTOM - TOP),
            }));

            if (this.points.length < 2) {
                this.path.setAttribute('d', '');
                this.empty.textContent = data.emptyText || 'Waiting for history...';
                this.empty.style.display = 'block';
                this._clearActive();
                return;
            }

            this.empty.style.display = 'none';
            this.path.setAttribute('d', this.points.map((point, index) =>
                `${index ? 'L' : 'M'} ${point.plotX.toFixed(2)} ${point.plotY.toFixed(2)}`
            ).join(' '));
        }

        _nearest(clientX) {
            if (!this.points.length) return null;

            const rect = this.svg.getBoundingClientRect();
            const localX = (clientX - rect.left) / rect.width * WIDTH;
            return this.points.reduce((nearest, point) =>
                Math.abs(point.plotX - localX) < Math.abs(nearest.plotX - localX) ? point : nearest
            );
        }

        _activateNearest(clientX) {
            const point = this._nearest(clientX);
            if (!point) return;

            this.hoverLine.setAttribute('x1', point.plotX);
            this.hoverLine.setAttribute('x2', point.plotX);
            this.hoverPoint.setAttribute('cx', point.plotX);
            this.hoverPoint.setAttribute('cy', point.plotY);

            const formatTooltip = this.options.formatTooltip || (value => String(value.y));
            this.tooltip.textContent = formatTooltip(point);
            this.tooltip.classList.add('active');
            this.hoverLine.classList.add('active');
            this.hoverPoint.classList.add('active');

            const suggestedLeft = point.plotX / WIDTH * this.plot.clientWidth + 8;
            this.tooltip.style.left = `${clamp(
                suggestedLeft, 4, this.plot.clientWidth - this.tooltip.offsetWidth - 4
            )}px`;
            this.tooltip.style.top = `${Math.max(2, point.plotY - this.tooltip.offsetHeight - 6)}px`;
        }

        _clearActive() {
            this.tooltip.classList.remove('active');
            this.hoverLine.classList.remove('active');
            this.hoverPoint.classList.remove('active');
        }
    }

    window.OpenBenchHistoryGraph = OpenBenchHistoryGraph;
})();
