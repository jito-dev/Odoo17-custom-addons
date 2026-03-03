/** @odoo-module **/

import { loadJS } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, onWillStart, onWillUnmount, useRef, useEffect } from "@odoo/owl";

// Three-tier bar colours matching the reference implementation
const COLOR_IN      = '#2680eb'; // fully inside avg range
const COLOR_PARTIAL = '#6aaff5'; // straddles an avg boundary
const COLOR_OUT     = '#c2d9ff'; // completely outside avg range

const COLOR_IN_HOVER      = '#1a6fd4';
const COLOR_PARTIAL_HOVER = '#4a98e0';
const COLOR_OUT_HOVER     = '#a8c4f0';

class SalaryChartWidget extends Component {
    static template = 'dev_cost_estimator.SalaryChartWidget';
    static props = { ...standardFieldProps };

    setup() {
        this.chartRef   = useRef('chart');
        this.tooltipRef = useRef('tooltip'); // pre-declared in template

        onWillStart(() => loadJS('/dev_cost_estimator/static/lib/d3/d3.min.js'));

        useEffect(
            (jsonStr) => { this._renderChart(jsonStr); },
            () => [this.props.record.data[this.props.name]]
        );

        onWillUnmount(() => {
            const el = this.chartRef.el;
            if (el) el.innerHTML = '';
        });
    }

    // ── data preparation ─────────────────────────────────────────────────────

    /**
     * Map the raw {salary, count} points from the backend directly to a
     * render-ready array. The backend already provides one data-point per
     * salary level — no aggregation or binning is done here.
     *
     * Three-tier range classification (mirrors the reference):
     *   'in'      — bar is fully contained in [avg_min, avg_max]
     *   'partial' — bar straddles one of the avg boundaries
     *   'out'     — bar sits completely outside the avg range
     */
    _prepareData(data) {
        const { avg_min, avg_max } = data;

        // The backend provides pre-binned data directly from the Djinni API.
        // Each point already carries salary_min / salary_max / count so we
        // map them straight to render-ready objects — no re-bucketing needed.
        return data.points.map(pt => {
            const salMin = pt.salary_min ?? pt.salary ?? 0;
            const salMax = pt.salary_max ?? (salMin + 1000);
            const count  = pt.count ?? 0;

            const isInRange = avg_min && avg_max
                ? salMin >= avg_min && salMax <= avg_max
                : false;

            const isPartiallyInRange = avg_min && avg_max
                ? (avg_min >= salMin && avg_min < salMax) ||
                  (avg_max >  salMin && avg_max < salMax) ||
                  avg_max === salMin
                : false;

            return {
                salary:    salMin,
                salMax,
                count,
                rangeType: isInRange ? 'in' : isPartiallyInRange ? 'partial' : 'out',
            };
        });
    }

    _getColor(d, hover = false) {
        if (d.rangeType === 'in')      return hover ? COLOR_IN_HOVER      : COLOR_IN;
        if (d.rangeType === 'partial') return hover ? COLOR_PARTIAL_HOVER : COLOR_PARTIAL;
        return hover ? COLOR_OUT_HOVER : COLOR_OUT;
    }

    // ── rendering ────────────────────────────────────────────────────────────

    _renderChart(jsonStr) {
        const container = this.chartRef.el;
        if (!container) return;

        container.innerHTML = '';
        if (!jsonStr) return;

        let data;
        try { data = JSON.parse(jsonStr); } catch { return; }
        if (!data.points || data.points.length === 0) return;

        const d3        = window.d3;
        const barData   = this._prepareData(data);
        const tooltipEl = this.tooltipRef.el;

        // The tooltip is position:absolute inside the position-relative wrapper.
        // Use the wrapper as the pointer-event origin so offsets are correct.
        const wrapper    = container.parentElement;
        const totalWidth = container.clientWidth || 640;

        const margin = { top: 16, right: 20, bottom: 40, left: 10 };
        const width  = totalWidth - margin.left - margin.right;
        const height = Math.round(totalWidth * 0.35) - margin.top - margin.bottom;

        // ── scales ───────────────────────────────────────────────────────────

        const x = d3.scaleBand()
            .domain(barData.map(d => String(d.salary)))
            .range([0, width])
            .paddingInner(0.05)
            .paddingOuter(0);

        const y = d3.scaleLinear()
            .domain([0, d3.max(barData, d => d.count)])
            .range([height, 0]);

        // ── SVG root ─────────────────────────────────────────────────────────

        const svg = d3.select(container)
            .append('svg')
            .attr('width',  totalWidth)
            .attr('height', height + margin.top + margin.bottom)
            .append('g')
            .attr('transform', `translate(${margin.left},${margin.top})`);

        // ── bar groups ───────────────────────────────────────────────────────
        // Each group holds:
        //   .bar         — the visible coloured rect
        //   .bar-overlay — a full-height transparent rect for reliable hit detection
        //                  (mirrors the reference's pattern)

        const self = this;

        const barGroups = svg.selectAll('.bar-group')
            .data(barData)
            .enter()
            .append('g')
            .attr('class', 'bar-group');

        barGroups.append('rect')
            .attr('class',  'bar')
            .attr('x',      d => x(String(d.salary)))
            .attr('y',      d => y(d.count))
            .attr('width',  x.bandwidth())
            .attr('height', d => Math.max(0, height - y(d.count)))
            .attr('fill',   d => self._getColor(d))
            .attr('rx', 3)
            .attr('ry', 3);

        barGroups.append('rect')
            .attr('class',  'bar-overlay')
            .attr('x',      d => x(String(d.salary)))
            .attr('y',      0)
            .attr('width',  x.bandwidth())
            .attr('height', height)
            .attr('fill',   'transparent');

        // ── mouse events ─────────────────────────────────────────────────────

        barGroups
            .on('mouseover', function (event, d) {
                d3.select(this).select('.bar')
                    .attr('fill', self._getColor(d, true));
            })
            .on('mousemove', function (event, d) {
                if (!d.count || !tooltipEl) return;

                const [mx, my] = d3.pointer(event, wrapper);
                const tw   = tooltipEl.offsetWidth || 200;
                const left = Math.min(Math.max(8, mx - tw / 2), wrapper.clientWidth - tw - 8);

                const pct = data.online_count
                    ? ` (${((d.count / data.online_count) * 100).toFixed(1)}%)`
                    : '';

                d3.select(tooltipEl)
                    .style('opacity', 1)
                    .style('left',    `${left}px`)
                    .style('top',     `${my - 70}px`)
                    .html(
                        `<strong>$${d.salary.toLocaleString()} \u2013 $${d.salMax.toLocaleString()}</strong>` +
                        `<br>${d.count.toLocaleString()} candidates${pct}`
                    );
            })
            .on('mouseout', function (event, d) {
                d3.select(this).select('.bar')
                    .attr('fill', self._getColor(d, false));

                if (tooltipEl) d3.select(tooltipEl).style('opacity', 0);
            });

        // ── X axis ───────────────────────────────────────────────────────────
        // Labels are placed at bar LEFT EDGES (not centers) so each label sits
        // between the previous bar and the current one, giving a clear sense of
        // the salary boundary / interval start.

        const maxLabels = 14;
        const stride    = Math.max(1, Math.ceil(barData.length / maxLabels));
        const tickVals  = barData
            .filter((_, i) => i % stride === 0)
            .map(d => String(d.salary));

        const axisG = svg.append('g')
            .attr('transform', `translate(0,${height})`)
            .call(
                d3.axisBottom(x)
                    .tickValues(tickVals)
                    .tickFormat(sal => Number(sal) >= 10000
                        ? `$${Number(sal) / 1000}k`
                        : `$${sal}`)
                    .tickSize(0)
                    .tickPadding(10)
            );

        axisG.call(g => g.select('.domain').remove());

        // Shift each tick from band-center (default) to band-left-edge.
        axisG.selectAll('.tick')
            .attr('transform', d => `translate(${x(d)}, 0)`);

        axisG.selectAll('text')
            .style('fill',      '#8a9bb0')
            .style('font-size', '11px');
    }
}

export const salaryChartField = {
    component: SalaryChartWidget,
    supportedTypes: ['text'],
    isEmpty: (record, fieldName) => !record.data[fieldName],
};

registry.category('fields').add('salary_chart', salaryChartField);
