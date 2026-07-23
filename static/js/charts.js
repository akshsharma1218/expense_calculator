window.FinFlowCharts = (function () {
  const COLORS = ['#6366f1', '#22d3ee', '#a78bfa', '#34d399', '#f87171', '#fbbf24', '#818cf8', '#6ee7b7'];

  const formatCompactCurrency = (value) => {
    const number = Number(value) || 0;
    const absValue = Math.abs(number);

    let scaled = number;
    let suffix = '';

    if (absValue >= 10000000) {
      scaled = number / 10000000;
      suffix = 'Cr';
    } else if (absValue >= 100000) {
      scaled = number / 100000;
      suffix = 'L';
    } else if (absValue >= 1000) {
      scaled = number / 1000;
      suffix = 'K';
    }

    const formatted = suffix
      ? (Number.isInteger(scaled) ? String(scaled) : scaled.toFixed(1).replace(/\.0$/, ''))
      : number.toLocaleString('en-IN');

    return '₹' + formatted + suffix;
  };

  const baseOptions = {
    chart: {
      fontFamily: '"Plus Jakarta Sans", sans-serif',
      background: 'transparent',
      toolbar: { show: false },
      animations: {
        enabled: true,
        easing: 'easeinout',
        speed: 800,
        animateGradually: { enabled: true, delay: 120 },
      },
    },
    theme: { mode: 'dark' },
    grid: {
      borderColor: 'rgba(255,255,255,0.06)',
      strokeDashArray: 4,
    },
    tooltip: {
      theme: 'dark',
      style: { fontSize: '13px' },
    },
  };

  function renderMonthlyTrend(containerId, data) {
    const el = document.getElementById(containerId);
    if (!el || !data || !data.length || typeof ApexCharts === 'undefined') return;

    const labels = data.map((d) => d.label);
    const income = data.map((d) => d.income);
    const expense = data.map((d) => d.expense);

    const chart = new ApexCharts(el, {
      ...baseOptions,
      chart: { ...baseOptions.chart, type: 'area', height: 300 },
      series: [
        { name: 'Income', data: income },
        { name: 'Expense', data: expense },
      ],
      colors: ['#34d399', '#f87171'],
      fill: {
        type: 'gradient',
        gradient: {
          shadeIntensity: 1,
          opacityFrom: 0.35,
          opacityTo: 0.02,
          stops: [0, 100],
        },
      },
      stroke: { curve: 'smooth', width: 2.5 },
      xaxis: {
        categories: labels,
        labels: { style: { colors: '#8b9cb8', fontSize: '12px' } },
        axisBorder: { show: false },
        axisTicks: { show: false },
      },
      yaxis: {
        labels: {
          style: { colors: '#8b9cb8', fontSize: '12px' },
          formatter: (v) => formatCompactCurrency(v),
        },
      },
      legend: {
        position: 'top',
        horizontalAlign: 'right',
        labels: { colors: '#8b9cb8' },
        markers: { radius: 12 },
      },
      dataLabels: { enabled: false },
    });

    chart.render();
    return chart;
  }

  function renderDonut(containerId, data, options = {}) {
    const el = document.getElementById(containerId);
    if (!el || !data || !data.length || typeof ApexCharts === 'undefined') return;

    data = data.filter((d) => d.type === 'expense');
    
    const labels = data.map((d) => d.name);
    const values = data.map((d) => Math.abs(d.total));

    const chart = new ApexCharts(el, {
      ...baseOptions,
      chart: { ...baseOptions.chart, type: 'donut', height: options.height || 280 },
      series: values,
      labels: labels,
      colors: COLORS,
      plotOptions: {
        pie: {
          donut: {
            size: '72%',
            labels: {
              show: true,
              name: { color: '#8b9cb8', fontSize: '13px' },
              value: {
                color: '#f0f4fc',
                fontSize: '1.4rem',
                fontWeight: 700,
                formatter: (v) => '₹' + Number(v).toLocaleString('en-IN'),
              },
              total: {
                show: true,
                label: options.totalLabel || 'Total',
                color: '#8b9cb8',
                formatter: (w) => {
                  const sum = w.globals.seriesTotals.reduce((a, b) => a + b, 0);
                  return '₹' + sum.toLocaleString('en-IN');
                },
              },
            },
          },
        },
      },
      legend: {
        position: 'bottom',
        labels: { colors: '#8b9cb8' },
        markers: { radius: 12 },
      },
      dataLabels: { enabled: false },
      stroke: { width: 2, colors: ['#060b14'] },
    });

    chart.render();
    return chart;
  }

  function renderBar(containerId, data, options = {}, data_type) {
    const el = document.getElementById(containerId);
    if (!el || !data || !data.length || typeof ApexCharts === 'undefined') return;
    data = data.filter((d) => d.type === data_type);
    const labels = data.map((d) => d.name);
    const values = data.map((d) => Math.abs(d.total));

    const chart = new ApexCharts(el, {
      ...baseOptions,
      chart: { ...baseOptions.chart, type: 'bar', height: options.height || 320 },
      series: [{ name: 'Amount', data: values }],
      colors: [options.color || '#6366f1'],
      plotOptions: {
        bar: {
          borderRadius: 8,
          columnWidth: '55%',
          distributed: true,
        },
      },
      colors: COLORS,
      xaxis: {
        categories: labels,
        labels: {
          style: { colors: '#8b9cb8', fontSize: '11px' },
          rotate: -35,
          trim: true,
        },
        axisBorder: { show: false },
        axisTicks: { show: false },
      },
      yaxis: {
        labels: {
          style: { colors: '#8b9cb8' },
          formatter: (v) => formatCompactCurrency(v),
        },
      },
      legend: { show: false },
      dataLabels: { enabled: false },
    });

    chart.render();
    return chart;
  }

  function renderBarHor(containerId, data, options = {}, data_type) {
    const el = document.getElementById(containerId);
    if (!el || !data || !data.length || typeof ApexCharts === 'undefined') return;
    data = data.filter((d) => d.type === data_type);
    const labels = data.map((d) => d.name);
    const values = data.map((d) => Math.abs(d.total));

    const chart = new ApexCharts(el, {
      ...baseOptions,
      chart: { ...baseOptions.chart, type: 'bar', height: options.height || 320 },
      series: [{ name: 'Amount', data: values }],
      colors: [options.color || '#6366f1'],
      plotOptions: {
        bar: {
          borderRadius: 8,
          horizontal: true,
          barHeight: '55%',
          distributed: true,
        },
      },
      colors: COLORS,
      xaxis: {
        categories: labels,
        labels: {
          style: { colors: '#8b9cb8' },
          formatter: (v) => formatCompactCurrency(v),
        },
      },
      yaxis: {
        labels: {
          style: { colors: '#8b9cb8', fontSize: '11px' },
          trim: true,
        },
      },
      legend: { show: false },
      dataLabels: { enabled: false },
    });

    chart.render();
    return chart;
  }

  function renderAccountBar(containerId, data) {
    const el = document.getElementById(containerId);
    if (!el || !data || !data.length || typeof ApexCharts === 'undefined') return;

    const chart = new ApexCharts(el, {
      ...baseOptions,
      chart: { ...baseOptions.chart, type: 'bar', height: Math.max(200, data.length * 48) },
      series: [{ name: 'Balance', data: data.map((d) => d.balance) }],
      plotOptions: {
        bar: { borderRadius: 8, horizontal: true, barHeight: '65%' },
      },
      colors: ['#6366f1'],
      fill: {
        type: 'gradient',
        gradient: { shade: 'dark', type: 'horizontal', gradientToColors: ['#22d3ee'] },
      },
      xaxis: {
        categories: data.map((d) => d.name),
        labels: {
          style: { colors: '#8b9cb8' },
          formatter: (v) => formatCompactCurrency(v),
        },
      },
      yaxis: {
        labels: { style: { colors: '#8b9cb8', fontSize: '12px' } },
      },
      legend: { show: false },
      dataLabels: { enabled: false },
      grid: { ...baseOptions.grid, padding: { left: 10 } },
    });

    chart.render();
    return chart;
  }

  return {
    renderMonthlyTrend,
    renderDonut,
    renderBar,
    renderBarHor,
    renderAccountBar,
  };
})();
