/** @odoo-module **/

import { loadJS } from "@web/core/assets";
import { registry } from "@web/core/registry";

// ── colour scheme (mirrors multi_salary_chart_widget.js) ─────────────────────

const COLOR_IN      = '#2680eb';
const COLOR_PARTIAL = '#6aaff5';
const COLOR_OUT     = '#c2d9ff';

function _prepareData(data) {
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

function _getColor(d) {
    if (d.rangeType === 'in')      return COLOR_IN;
    if (d.rangeType === 'partial') return COLOR_PARTIAL;
    return COLOR_OUT;
}

function _hasUsableData(data) {
    if (!data.points || data.points.length === 0) return false;
    if (!data.avg_min && !data.avg_max) return false;
    return data.points.some(pt => (pt.count ?? 0) > 0);
}

function _renderBarChartForPdf(container, data) {
    container.innerHTML = '';
    if (!_hasUsableData(data)) {
        const img = document.createElement('img');
        img.src = '/dev_cost_estimator/static/src/img/no-data.png';
        img.alt = 'No data available';
        img.style.cssText = 'width:100%;max-width:400px;display:block;margin:16px auto;';
        container.appendChild(img);
        return;
    }
    try {

    const d3      = window.d3;
    const barData = _prepareData(data);

    // Use explicit pixel width from container style; fall back to 720
    const totalWidth = container.offsetWidth || 720;

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
        .attr('fill',   d => _getColor(d))
        .attr('rx', 3).attr('ry', 3);

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
    axisG.selectAll('text')
        .style('fill',      '#8a9bb0')
        .style('font-size', '11px')
        .style('font-family', 'Arial, sans-serif');

    } catch (err) {
        console.warn('[PDF chart] render error:', err);
        container.innerHTML = '';
        const img = document.createElement('img');
        img.src = '/dev_cost_estimator/static/src/img/no-data.png';
        img.style.cssText = 'width:100%;max-width:400px;display:block;margin:16px auto;';
        container.appendChild(img);
    }
}

// ── off-screen section builder ────────────────────────────────────────────────

function _buildChartSection(entry) {
    const wrap = document.createElement('div');
    wrap.style.cssText =
        'width:740px;background:#fff;padding:24px 20px 16px;box-sizing:border-box;font-family:Arial,sans-serif;';

    // Title
    const title = document.createElement('div');
    title.style.cssText =
        'font-size:22px;font-weight:800;color:#2c3e50;margin-bottom:14px;letter-spacing:-0.02em;';
    title.textContent = entry.category_name || 'All';
    wrap.appendChild(title);

    // Salary pills
    const pillsData = [
        { label: 'Monthly', value: entry.salary_monthly },
        { label: 'Hourly',  value: entry.salary_hourly },
        { label: 'Daily',   value: entry.salary_daily },
    ].filter(p => p.value);

    if (pillsData.length) {
        const pillsRow = document.createElement('div');
        pillsRow.style.cssText = 'display:flex;gap:40px;margin-bottom:16px;';
        pillsData.forEach(({ label, value }) => {
            const pill = document.createElement('div');
            pill.innerHTML =
                `<div style="font-size:11px;font-weight:600;color:#8a9bb0;text-transform:uppercase;` +
                `letter-spacing:0.05em;margin-bottom:3px;">${label}</div>` +
                `<div style="font-size:18px;font-weight:700;color:#4e5d6c;">${value}</div>`;
            pillsRow.appendChild(pill);
        });
        wrap.appendChild(pillsRow);
    }

    // Chart
    const chartDiv = document.createElement('div');
    chartDiv.style.cssText = 'width:740px;';
    wrap.appendChild(chartDiv);
    _renderBarChartForPdf(chartDiv, entry);

    // Footer
    const parts = [];
    if (entry.online_count) {
        parts.push(`${Number(entry.online_count).toLocaleString()} candidates online`);
    }
    if (entry.cached_at) {
        try {
            const d = new Date(entry.cached_at.replace(' ', 'T') + 'Z');
            parts.push(`Data as of ${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}`);
        } catch {
            parts.push(`Data as of ${entry.cached_at}`);
        }
    }
    if (parts.length) {
        const footer = document.createElement('div');
        footer.style.cssText =
            'font-size:12px;color:#8a9bb0;margin-top:8px;font-family:Arial,sans-serif;';
        footer.textContent = parts.join(' · ');
        wrap.appendChild(footer);
    }

    return wrap;
}

// ── logo loading ──────────────────────────────────────────────────────────────

async function _loadLogoAsDataUrl() {
    const svgText = await fetch('/dev_cost_estimator/static/src/img/dark-logo.svg')
        .then(r => r.text());

    return new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => {
            const canvas  = document.createElement('canvas');
            canvas.width  = img.width  || 125;
            canvas.height = img.height || 48;
            canvas.getContext('2d').drawImage(img, 0, 0);
            resolve({ url: canvas.toDataURL('image/png'), width: canvas.width, height: canvas.height });
        };
        img.onerror = reject;
        img.src = 'data:image/svg+xml;base64,' + btoa(svgText);
    });
}

// ── PDF generation ────────────────────────────────────────────────────────────

async function generatePdf(chartsData) {
    // Load all external dependencies in parallel
    await Promise.all([
        loadJS('/dev_cost_estimator/static/lib/d3/d3.min.js'),
        loadJS('/dev_cost_estimator/static/lib/jspdf/jspdf.umd.min.js'),
        loadJS('/web_editor/static/lib/html2canvas.js'),
    ]);

    const { jsPDF }   = window.jspdf;
    const html2canvas = window.html2canvas;

    const pdf       = new jsPDF('p', 'mm', 'a4');
    const pdfWidth  = pdf.internal.pageSize.getWidth();   // 210 mm
    const pdfHeight = pdf.internal.pageSize.getHeight();  // 297 mm
    const marginMm  = 10;
    const usableW   = pdfWidth - marginMm * 2;            // 190 mm

    // Load logo once
    let logoUrl = null;
    let logoHeightMm = 0;
    try {
        const logo = await _loadLogoAsDataUrl();
        const logoWidthMm = 30;
        logoHeightMm = (logo.height / logo.width) * logoWidthMm;
        logoUrl = logo.url;
        // Will be added per page below
        void logoWidthMm;  // used below
    } catch (e) {
        console.warn('[PDF export] Could not load logo:', e);
    }

    const logoWidthMm = 30;  // same value used for addImage

    for (let i = 0; i < chartsData.length; i++) {
        if (i > 0) pdf.addPage();

        // Logo
        if (logoUrl) {
            pdf.addImage(logoUrl, 'PNG', marginMm, marginMm, logoWidthMm, logoHeightMm);
        }

        // Build off-screen chart section
        const container = document.createElement('div');
        container.style.cssText = 'position:absolute;left:-9999px;top:0;';
        document.body.appendChild(container);

        const section = _buildChartSection(chartsData[i]);
        container.appendChild(section);

        // Wait for D3 to finish rendering the SVG
        await new Promise(resolve => requestAnimationFrame(resolve));
        await new Promise(resolve => requestAnimationFrame(resolve));

        const canvas = await html2canvas(section, {
            backgroundColor: '#ffffff',
            scale: 2,
            useCORS: true,
            logging: false,
        });
        document.body.removeChild(container);

        const imgData = canvas.toDataURL('image/png');
        const imgProps = pdf.getImageProperties(imgData);
        const imgHeightMm = (imgProps.height * usableW) / imgProps.width;

        const yStart = marginMm + logoHeightMm + 6;
        const availH = pdfHeight - yStart - marginMm;

        pdf.addImage(
            imgData, 'PNG',
            marginMm, yStart,
            usableW, Math.min(imgHeightMm, availH)
        );
    }

    pdf.save('Jito_Estimated_Price_report.pdf');
}

// ── Odoo client action registration ──────────────────────────────────────────

registry.category('actions').add('dev_cost_estimator.export_pdf', async (env, action) => {
    let chartsData;
    try {
        chartsData = JSON.parse(action.params?.charts_json || '[]');
    } catch {
        chartsData = [];
    }
    if (!chartsData.length) return;
    await generatePdf(chartsData);
});
