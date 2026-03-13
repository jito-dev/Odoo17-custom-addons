/** @odoo-module **/

import { loadJS } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, onWillStart, onWillUnmount, useRef, useEffect } from "@odoo/owl";

// Three-tier bar colours — same as single-chart widget
const COLOR_IN      = '#2680eb';
const COLOR_PARTIAL = '#6aaff5';
const COLOR_OUT     = '#c2d9ff';

const COLOR_IN_HOVER      = '#1a6fd4';
const COLOR_PARTIAL_HOVER = '#4a98e0';
const COLOR_OUT_HOVER     = '#a8c4f0';

// ── chart rendering (pure function, no Owl deps) ──────────────────────────────

function prepareData(data) {
    const { avg_min, avg_max } = data;
    return data.points.map(pt => {
        const salMin = pt.salary_min ?? pt.salary ?? 0;
        const salMax = pt.salary_max ?? (salMin + 1000);
        const count  = pt.count ?? 0;

        const isIn = avg_min && avg_max
            ? salMin >= avg_min && salMax <= avg_max
            : false;

        const isPartial = avg_min && avg_max
            ? (avg_min >= salMin && avg_min < salMax) ||
              (avg_max >  salMin && avg_max < salMax) ||
              avg_max === salMin
            : false;

        return { salary: salMin, salMax, count, rangeType: isIn ? 'in' : isPartial ? 'partial' : 'out' };
    });
}

function getColor(d, hover = false) {
    if (d.rangeType === 'in')      return hover ? COLOR_IN_HOVER      : COLOR_IN;
    if (d.rangeType === 'partial') return hover ? COLOR_PARTIAL_HOVER : COLOR_PARTIAL;
    return hover ? COLOR_OUT_HOVER : COLOR_OUT;
}

function _showNoData(container) {
    container.innerHTML = '';
    const img = document.createElement('img');
    img.src = '/dev_cost_estimator/static/src/img/no-data.png';
    img.alt = 'No data available';
    img.className = 'multi-chart-no-data';
    container.appendChild(img);
}

function _hasUsableData(data) {
    if (!data.points || data.points.length === 0) return false;
    if (!data.avg_min && !data.avg_max) return false;
    return data.points.some(pt => (pt.count ?? 0) > 0);
}

function renderBarChart(container, tooltipEl, data) {
    container.innerHTML = '';
    if (!_hasUsableData(data)) {
        _showNoData(container);
        return;
    }

    try {
    const d3       = window.d3;
    if (!d3) throw new Error('D3 not loaded');
    const barData  = prepareData(data);
    const wrapper  = container.parentElement;
    const totalWidth = container.clientWidth || 640;

    const margin = { top: 16, right: 20, bottom: 40, left: 10 };
    const width  = totalWidth - margin.left - margin.right;
    const height = Math.round(totalWidth * 0.32) - margin.top - margin.bottom;

    const x = d3.scaleBand()
        .domain(barData.map(d => String(d.salary)))
        .range([0, width])
        .paddingInner(0.05)
        .paddingOuter(0);

    const y = d3.scaleLinear()
        .domain([0, d3.max(barData, d => d.count)])
        .range([height, 0]);

    const svg = d3.select(container)
        .append('svg')
        .attr('width',  totalWidth)
        .attr('height', height + margin.top + margin.bottom)
        .append('g')
        .attr('transform', `translate(${margin.left},${margin.top})`);

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
        .attr('fill',   d => getColor(d))
        .attr('rx', 3).attr('ry', 3);

    barGroups.append('rect')
        .attr('class',  'bar-overlay')
        .attr('x',      d => x(String(d.salary)))
        .attr('y',      0)
        .attr('width',  x.bandwidth())
        .attr('height', height)
        .attr('fill',   'transparent');

    barGroups
        .on('mouseover', function (event, d) {
            d3.select(this).select('.bar').attr('fill', getColor(d, true));
        })
        .on('mousemove', function (event, d) {
            if (!d.count || !tooltipEl) return;
            const [mx, my] = d3.pointer(event, wrapper);
            const tw   = tooltipEl.offsetWidth || 200;
            const left = Math.min(Math.max(8, mx - tw / 2), wrapper.clientWidth - tw - 8);
            const pct  = data.online_count
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
            d3.select(this).select('.bar').attr('fill', getColor(d, false));
            if (tooltipEl) d3.select(tooltipEl).style('opacity', 0);
        });

    const maxLabels = 14;
    const stride    = Math.max(1, Math.ceil(barData.length / maxLabels));
    const tickVals  = barData.filter((_, i) => i % stride === 0).map(d => String(d.salary));

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
    axisG.selectAll('.tick').attr('transform', d => `translate(${x(d)}, 0)`);
    axisG.selectAll('text').style('fill', '#8a9bb0').style('font-size', '11px');

    } catch (err) {
        console.warn('[SalaryChart] render error:', err);
        _showNoData(container);
    }
}

// ── Owl component ─────────────────────────────────────────────────────────────

class MultiSalaryChartWidget extends Component {
    static template = 'dev_cost_estimator.MultiSalaryChartWidget';
    static props = { ...standardFieldProps };

    setup() {
        this.rootRef = useRef('root');

        onWillStart(() => loadJS('/dev_cost_estimator/static/lib/d3/d3.min.js'));

        useEffect(
            (jsonStr) => { this._renderAll(jsonStr); },
            () => [this.props.record.data[this.props.name]]
        );

        onWillUnmount(() => {
            const el = this.rootRef.el;
            if (el) el.innerHTML = '';
        });
    }

    _renderAll(jsonStr) {
        const root = this.rootRef.el;
        if (!root) return;
        root.innerHTML = '';
        if (!jsonStr) return;

        let list;
        try { list = JSON.parse(jsonStr); } catch { return; }
        if (!Array.isArray(list) || list.length === 0) return;

        list.forEach((entry, idx) => {
            const section = document.createElement('div');
            section.className = 'multi-chart-section' + (idx > 0 ? ' multi-chart-section--separator' : '');

            // ── header ────────────────────────────────────────────────────────
            const header = document.createElement('div');
            header.className = 'multi-chart-header';

            const title = document.createElement('div');
            title.className = 'multi-chart-title';
            title.textContent = entry.category_name || 'All';
            header.appendChild(title);

            // salary range pills
            if (entry.salary_monthly) {
                const pills = document.createElement('div');
                pills.className = 'multi-chart-salary-pills';

                const salaryData = [
                    { value: entry.salary_monthly },
                    { value: entry.salary_hourly },
                    { value: entry.salary_daily },
                ];
                salaryData.forEach(({ value }) => {
                    if (!value) return;
                    const pill = document.createElement('div');
                    pill.className = 'multi-chart-salary-pill';
                    pill.innerHTML = `<span class="multi-chart-salary-value">${value}</span>`;
                    pills.appendChild(pill);
                });
                header.appendChild(pills);
            }

            section.appendChild(header);

            // ── chart area ────────────────────────────────────────────────────
            const chartWrap = document.createElement('div');
            chartWrap.className = 'multi-chart-wrap';
            chartWrap.style.position = 'relative';

            const chartDiv = document.createElement('div');
            chartDiv.className = 'multi-chart-bars';

            const tooltipDiv = document.createElement('div');
            tooltipDiv.className = 'chart-tooltip';
            tooltipDiv.style.cssText =
                'position:absolute;opacity:0;pointer-events:none;background:#1e2837;' +
                'color:white;padding:8px;border-radius:4px;z-index:10;';

            chartWrap.appendChild(chartDiv);
            chartWrap.appendChild(tooltipDiv);
            section.appendChild(chartWrap);

            // ── footer ────────────────────────────────────────────────────────
            if (entry.online_count || entry.cached_at) {
                const footer = document.createElement('div');
                footer.className = 'multi-chart-footer';

                if (entry.online_count) {
                    const onl = document.createElement('span');
                    onl.textContent = `${entry.online_count.toLocaleString()} candidates online`;
                    footer.appendChild(onl);
                }
                if (entry.cached_at) {
                    const sep = document.createElement('span');
                    sep.className = 'multi-chart-footer-sep';
                    sep.textContent = '·';
                    footer.appendChild(sep);

                    const ts = document.createElement('span');
                    try {
                        const d = new Date(entry.cached_at.replace(' ', 'T') + 'Z');
                        ts.textContent = `Data as of ${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}`;
                    } catch {
                        ts.textContent = `Data as of ${entry.cached_at}`;
                    }
                    footer.appendChild(ts);
                }
                section.appendChild(footer);
            }

            root.appendChild(section);

            // render D3 after the DOM node is attached so clientWidth is correct
            requestAnimationFrame(() => {
                renderBarChart(chartDiv, tooltipDiv, entry);
            });
        });
    }
}

export const multiSalaryChartField = {
    component: MultiSalaryChartWidget,
    supportedTypes: ['text'],
    isEmpty: (record, fieldName) => !record.data[fieldName],
};

registry.category('fields').add('multi_salary_chart', multiSalaryChartField);
