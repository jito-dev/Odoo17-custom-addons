/** @odoo-module **/

import { loadJS } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, onWillStart, onWillUnmount, useRef, useEffect } from "@odoo/owl";

const BIN_SIZE = 500;
const COLOR_AVG = '#2680eb';
const COLOR_OTHER = '#c2d9ff';

class SalaryChartWidget extends Component {
    static template = 'dev_cost_estimator.SalaryChartWidget';
    static props = { ...standardFieldProps };

    setup() {
        this.canvasRef = useRef('canvas');
        this.chart = null;

        onWillStart(() => loadJS('/web/static/lib/Chart/Chart.js'));

        useEffect(
            (jsonStr) => {
                this._renderChart(jsonStr);
            },
            () => [this.props.record.data[this.props.name]]
        );

        onWillUnmount(() => {
            if (this.chart) {
                this.chart.destroy();
                this.chart = null;
            }
        });
    }

    _renderChart(jsonStr) {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }

        const canvas = this.canvasRef.el;
        if (!canvas || !jsonStr) return;

        let data;
        try {
            data = JSON.parse(jsonStr);
        } catch {
            return;
        }

        if (!data.points || data.points.length === 0) return;

        // Aggregate salary points into $500 bins
        const binsMap = {};
        for (const pt of data.points) {
            const binStart = Math.floor(pt.salary / BIN_SIZE) * BIN_SIZE;
            binsMap[binStart] = (binsMap[binStart] || 0) + pt.count;
        }

        const salaries = Object.keys(binsMap).map(Number);
        const minSal = Math.min(...salaries);
        const maxSal = Math.max(...salaries) + BIN_SIZE;
        const startPlot = Math.max(0, minSal - BIN_SIZE);

        const labels = [];
        const counts = [];
        const colors = [];

        for (let sal = startPlot; sal < maxSal; sal += BIN_SIZE) {
            const count = binsMap[sal] || 0;
            const binCenter = sal + BIN_SIZE / 2;
            const isAvg = (data.avg_min && data.avg_max)
                ? binCenter >= data.avg_min && binCenter <= data.avg_max
                : false;

            labels.push(sal >= 10000 ? `$${sal / 1000}k` : `$${sal}`);
            counts.push(count);
            colors.push(isAvg ? COLOR_AVG : COLOR_OTHER);
        }

        const ctx = canvas.getContext('2d');
        // Chart is already loaded via loadJS, available as global
        this.chart = new window.Chart(ctx, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    data: counts,
                    backgroundColor: colors,
                    borderWidth: 0,
                    borderRadius: 3,
                    barPercentage: 0.92,
                    categoryPercentage: 1.0,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 350 },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: (items) => {
                                const idx = items[0].dataIndex;
                                const sal = startPlot + idx * BIN_SIZE;
                                return `$${sal.toLocaleString()} – $${(sal + BIN_SIZE).toLocaleString()}`;
                            },
                            label: (item) => `${item.raw.toLocaleString()} candidates`,
                        },
                    },
                },
                scales: {
                    x: {
                        grid: { display: false },
                        border: { display: false },
                        ticks: {
                            maxRotation: 0,
                            autoSkip: true,
                            maxTicksLimit: 14,
                            font: { size: 11 },
                            color: '#8a9bb0',
                        },
                    },
                    y: {
                        display: false,
                        beginAtZero: true,
                    },
                },
            },
        });
    }
}

export const salaryChartField = {
    component: SalaryChartWidget,
    supportedTypes: ['char'],
    isEmpty: (record, fieldName) => !record.data[fieldName],
};

registry.category('fields').add('salary_chart', salaryChartField);
