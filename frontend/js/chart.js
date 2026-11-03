import { CONFIG } from "./config.js";

let chart = null;

const UP = "#22d3ee";
const DOWN = "#a78bfa";
const GRID = "rgba(148, 163, 184, 0.08)";
const TICKS = "#6b7894";

function areaGradient(ctx, color) {
  const height = Math.max(ctx.canvas.height, 320);
  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, `${color}33`);
  gradient.addColorStop(1, `${color}00`);
  return gradient;
}

export function initChart(canvas) {
  if (chart) return chart;
  if (typeof window.Chart === "undefined") {
    console.error("Chart.js no está cargado (revisá vendor/chart.umd.min.js).");
    return null;
  }
  const ctx = canvas.getContext("2d");

  chart = new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "Subida",
          data: [],
          borderColor: UP,
          backgroundColor: areaGradient(ctx, UP),
          borderWidth: 2,
          tension: 0.35,
          fill: true,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointHoverBackgroundColor: UP,
          pointHitRadius: 14,
        },
        {
          label: "Bajada",
          data: [],
          borderColor: DOWN,
          backgroundColor: areaGradient(ctx, DOWN),
          borderWidth: 2,
          tension: 0.35,
          fill: true,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointHoverBackgroundColor: DOWN,
          pointHitRadius: 14,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          display: true,
          position: "top",
          align: "end",
          labels: {
            color: "#9aa8c4",
            usePointStyle: true,
            pointStyle: "circle",
            boxWidth: 7,
            boxHeight: 7,
            padding: 16,
            font: { size: 12 },
          },
        },
        tooltip: {
          backgroundColor: "rgba(12, 18, 36, 0.96)",
          borderColor: "rgba(148, 163, 184, 0.18)",
          borderWidth: 1,
          titleColor: "#e8eeff",
          bodyColor: "#b6c2dc",
          padding: 12,
          cornerRadius: 10,
          displayColors: true,
          usePointStyle: true,
          callbacks: {
            label: (item) => ` ${item.dataset.label}: ${formatMbps(item.parsed.y)} Mbps`,
          },
        },
      },
      scales: {
        x: {
          grid: { color: GRID, drawTicks: false },
          border: { display: false },
          ticks: {
            color: TICKS,
            maxRotation: 0,
            autoSkip: true,
            maxTicksLimit: 8,
            font: { size: 11 },
          },
        },
        y: {
          beginAtZero: true,
          grid: { color: GRID, drawTicks: false },
          border: { display: false },
          ticks: {
            color: TICKS,
            padding: 8,
            font: { size: 11 },
            callback: (value) => `${value} Mbps`,
          },
        },
      },
    },
  });

  return chart;
}

export function appendPoint(label, up, down) {
  if (!chart) return;
  const { labels, datasets } = chart.data;
  labels.push(label);
  datasets[0].data.push(up);
  datasets[1].data.push(down);

  const overflow = labels.length - CONFIG.CHART_MAX_POINTS;
  if (overflow > 0) {
    labels.splice(0, overflow);
    datasets[0].data.splice(0, overflow);
    datasets[1].data.splice(0, overflow);
  }
  chart.update("none");
}

export function resetChart() {
  if (!chart) return;
  chart.data.labels = [];
  chart.data.datasets[0].data = [];
  chart.data.datasets[1].data = [];
  chart.update("none");
}

export function formatMbps(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (value >= 10) return value.toFixed(2);
  if (value >= 1) return value.toFixed(3);
  if (value >= 0.01) return value.toFixed(4);
  return value.toFixed(5);
}
